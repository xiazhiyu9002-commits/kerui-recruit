from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from lancedb.index import FTS

from kerui_recruit.search.contracts import (
    CandidateFilters,
    SearchChunk,
    SearchHit,
    SearchRequest,
)


class LanceDBSearchIndex:
    table_name = "candidate_chunks"
    rrf_k = 60

    def __init__(self, root: Path, *, vector_dimension: int) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.vector_dimension = vector_dimension
        self.database = lancedb.connect(str(root))

    def upsert(self, chunks: list[SearchChunk]) -> None:
        if not chunks:
            return
        records = [self._record(chunk) for chunk in chunks]
        if not self._table_exists():
            table = self.database.create_table(
                self.table_name,
                data=records,
                schema=self._schema(),
            )
        else:
            table = self.database.open_table(self.table_name)
            chunk_ids = ", ".join(self._quote(chunk.id) for chunk in chunks)
            table.delete(f"id IN ({chunk_ids})")
            table.add(records)
        table.create_index(
            "content",
            config=FTS(
                base_tokenizer="ngram",
                ngram_min_length=2,
                ngram_max_length=3,
                lower_case=True,
                stem=False,
                remove_stop_words=False,
            ),
            replace=True,
        )

    def delete_revision(self, revision_id: str) -> None:
        if not self._table_exists():
            return
        self.database.open_table(self.table_name).delete(
            f"revision_id = {self._quote(revision_id)}"
        )

    def search(self, request: SearchRequest) -> list[SearchHit]:
        if not self._table_exists():
            return []
        table = self.database.open_table(self.table_name)
        if table.count_rows() == 0:
            return []
        where = self._where(request.filters)
        retrieval_limit = max(request.limit * 4, 100)
        bm25_query = table.search(
            request.query,
            query_type="fts",
            fts_columns="content",
        )
        vector_query = table.search(
            list(request.query_vector),
            vector_column_name="vector",
            query_type="vector",
        )
        if where:
            bm25_query = bm25_query.where(where)
            vector_query = vector_query.where(where, prefilter=True)
        bm25_rows = bm25_query.limit(retrieval_limit).to_list()
        vector_rows = vector_query.limit(retrieval_limit).to_list()
        return self._rrf(bm25_rows, vector_rows, request.limit)

    def _rrf(
        self,
        bm25_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
        limit: int,
    ) -> list[SearchHit]:
        scores: dict[str, float] = defaultdict(float)
        channels: dict[str, list[str]] = defaultdict(list)
        rows: dict[str, dict[str, Any]] = {}
        for channel, ranked_rows in (("bm25", bm25_rows), ("vector", vector_rows)):
            for rank, row in enumerate(ranked_rows, start=1):
                chunk_id = row["id"]
                scores[chunk_id] += 1.0 / (self.rrf_k + rank)
                channels[chunk_id].append(channel)
                rows[chunk_id] = row
        ordered_ids = sorted(scores, key=lambda item: (-scores[item], item))
        hits: list[SearchHit] = []
        seen_candidates: set[str] = set()
        for chunk_id in ordered_ids:
            row = rows[chunk_id]
            candidate_id = row["candidate_id"]
            if candidate_id in seen_candidates:
                continue
            seen_candidates.add(candidate_id)
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    candidate_id=candidate_id,
                    revision_id=row["revision_id"],
                    content=row["content"],
                    score=scores[chunk_id],
                    matched_channels=tuple(channels[chunk_id]),
                    total_years=row.get("total_years"),
                    highest_degree=row.get("highest_degree"),
                    location=row.get("location"),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def _record(self, chunk: SearchChunk) -> dict[str, Any]:
        if len(chunk.vector) != self.vector_dimension:
            raise ValueError(
                f"Expected vector dimension {self.vector_dimension}, got {len(chunk.vector)}"
            )
        return {
            "id": chunk.id,
            "candidate_id": chunk.candidate_id,
            "revision_id": chunk.revision_id,
            "content": chunk.content,
            "vector": list(chunk.vector),
            "total_years": chunk.total_years,
            "highest_degree": chunk.highest_degree,
            "location": chunk.location,
            "candidate_status": chunk.candidate_status,
        }

    def _table_exists(self) -> bool:
        return self.table_name in self.database.list_tables().tables

    def _schema(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field("id", pa.string(), nullable=False),
                pa.field("candidate_id", pa.string(), nullable=False),
                pa.field("revision_id", pa.string(), nullable=False),
                pa.field("content", pa.string(), nullable=False),
                pa.field(
                    "vector",
                    pa.list_(pa.float32(), self.vector_dimension),
                    nullable=False,
                ),
                pa.field("total_years", pa.float64()),
                pa.field("highest_degree", pa.string()),
                pa.field("location", pa.string()),
                pa.field("candidate_status", pa.string(), nullable=False),
            ]
        )

    @classmethod
    def _where(cls, filters: CandidateFilters) -> str:
        clauses: list[str] = []
        if filters.min_years is not None:
            clauses.append(f"total_years >= {float(filters.min_years)}")
        if filters.highest_degree:
            clauses.append(f"highest_degree = {cls._quote(filters.highest_degree)}")
        if filters.location:
            clauses.append(f"location = {cls._quote(filters.location)}")
        if filters.candidate_status:
            clauses.append(
                f"candidate_status = {cls._quote(filters.candidate_status)}"
            )
        return " AND ".join(clauses)

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
