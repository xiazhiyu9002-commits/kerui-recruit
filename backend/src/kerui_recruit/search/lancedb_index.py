from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
import json
import threading
import time
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


SEARCH_DEADLINE: ContextVar[float | None] = ContextVar("search_execution_deadline", default=None)


class LanceDBSearchIndex:
    table_name = "candidate_chunks"
    rrf_k = 60
    optimize_every = 20

    def __init__(self, root: Path, *, vector_dimension: int,
                 embedding_model: str = "unspecified", schema_version: str = "2",
                 chunk_version: str = "1") -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.vector_dimension = vector_dimension
        self.database = lancedb.connect(str(root))
        self._pending_modifications = 0
        self._dirty_marker = root / ".fts-dirty"
        self._metadata_path = root / "candidate-index-metadata.json"
        self.metadata = {"schema_version": str(schema_version), "embedding_model": embedding_model,
                         "vector_dimension": vector_dimension, "chunk_version": str(chunk_version)}
        self._write_lock = threading.RLock()

    @property
    def compatibility_error(self) -> str | None:
        if not self._table_exists():
            return None
        try:
            actual = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "Index incompatible: missing or invalid metadata; explicit rebuild required"
        if actual != self.metadata:
            return "Index incompatible: schema, model, dimension or chunk version changed; explicit rebuild required"
        schema = getattr(self.database.open_table(self.table_name), "schema", None)
        if schema is not None and ("preferred_locations" not in schema.names or
                                   schema.field("vector").type.list_size != self.vector_dimension):
            return "Index incompatible: physical schema differs; explicit rebuild required"
        return None

    def is_compatible(self) -> bool:
        return self.compatibility_error is None

    def _require_compatible(self) -> None:
        error = self.compatibility_error
        if error:
            raise ValueError(error)

    def upsert(self, chunks: list[SearchChunk]) -> None:
        with self._write_lock:
            self._upsert(chunks)

    def _upsert(self, chunks: list[SearchChunk]) -> None:
        if not chunks:
            return
        self._require_compatible()
        records = [self._record(chunk) for chunk in chunks]
        if not self._table_exists():
            table = self.database.create_table(
                self.table_name,
                data=records,
                schema=self._schema(),
            )
            self._create_fts_index(table)
            temporary = self._metadata_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.metadata, sort_keys=True), encoding="utf-8")
            temporary.replace(self._metadata_path)
        else:
            table = self.database.open_table(self.table_name)
            chunk_ids = ", ".join(self._quote(chunk.id) for chunk in chunks)
            table.delete(f"id IN ({chunk_ids})")
            table.add(records)
            self._dirty_marker.touch(exist_ok=True)
            self._pending_modifications += 1
            if self._pending_modifications >= self.optimize_every:
                table.optimize()
                self._dirty_marker.unlink(missing_ok=True)
                self._pending_modifications = 0

    def delete_candidate(self, candidate_id: str) -> None:
        with self._write_lock:
            if self._table_exists():
                self.database.open_table(self.table_name).delete(f"candidate_id = {self._quote(candidate_id)}")

    def replace_candidate(self, chunks: list[SearchChunk]) -> None:
        """Replace all projected revisions of one candidate; empty deletion uses delete_candidate."""
        if not chunks or len({chunk.candidate_id for chunk in chunks}) != 1:
            raise ValueError("replace_candidate requires chunks for exactly one candidate")
        with self._write_lock:
            self._require_compatible()
            # Validate before removing any existing rows. A failed write remains retryable.
            for chunk in chunks:
                self._record(chunk)
            self.delete_candidate(chunks[0].candidate_id)
            self._upsert(chunks)

    def update_candidate_filters(self, candidate_id: str, **fields: Any) -> None:
        allowed = {"total_years", "highest_degree", "location", "candidate_status", "qs_rank",
                   "school_level", "preferred_location", "preferred_locations"}
        if not fields.keys() <= allowed:
            raise ValueError("Unsupported candidate projection fields")
        if "preferred_locations" in fields or "preferred_location" in fields:
            values = list(fields.get("preferred_locations") or ())
            if fields.get("preferred_location"):
                values.insert(0, fields["preferred_location"])
            fields["preferred_locations"] = list(dict.fromkeys(values))
            fields["preferred_location"] = values[0] if values else None
        with self._write_lock:
            self._require_compatible()
            if self._table_exists() and fields:
                self.database.open_table(self.table_name).update(
                    where=f"candidate_id = {self._quote(candidate_id)}", values=fields)

    @staticmethod
    def _ensure_column(table: Any, name: str) -> None:
        """给旧表补充缺失列（schema evolution），避免带新字段写入时报错。"""
        schema = getattr(table, "schema", None)
        if schema is not None and name not in schema.names:
            table.add_columns(pa.field(name, pa.string()))

    @staticmethod
    def _create_fts_index(table: Any) -> None:
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

    def get_revision_chunks(self, revision_id: str) -> list[dict[str, Any]]:
        """Return the raw rows (with vectors) for a revision, in arbitrary order."""
        if not self._table_exists():
            return []
        table = self.database.open_table(self.table_name)
        return table.search(None).where(f"revision_id = {self._quote(revision_id)}").limit(None).to_list()

    def get_candidate_chunk_contents(self, candidate_ids: list[str]) -> dict[str, list[str]]:
        """Return all chunk contents keyed by candidate_id, without pandas round-trip."""
        self._check_deadline()
        if not self._table_exists() or not candidate_ids:
            return {}
        table = self.database.open_table(self.table_name)
        ids = ", ".join(self._quote(c) for c in candidate_ids)
        try:
            rows = table.search(None).where(f"candidate_id IN ({ids})").limit(None).to_list()
        except Exception:
            return {}
        result: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            result[row["candidate_id"]].append(row["content"])
        return dict(result)

    def warmup(self) -> int:
        """Open the index table and return its row count to preload it."""
        if not self._table_exists():
            return 0
        return self.database.open_table(self.table_name).count_rows()

    def is_ready(self) -> bool:
        """True when the index table exists（轻量检查，避免 count_rows 阻塞）。"""
        return self._table_exists() and self.is_compatible()

    def optimize_pending(self) -> bool:
        """Add the last partial write batch to FTS without blocking readiness."""
        if not self._table_exists() or not self._dirty_marker.exists():
            return False
        self.database.open_table(self.table_name).optimize()
        self._dirty_marker.unlink(missing_ok=True)
        self._pending_modifications = 0
        return True

    def search(self, request: SearchRequest) -> list[SearchHit]:
        fts_rows = self.search_fts(request.query, request.filters, request.limit)
        if not request.query_vector:
            return self.fuse(fts_rows, [], request.limit)
        vector_rows = self.search_vector(request.query_vector, request.filters, request.limit)
        return self.fuse(fts_rows, vector_rows, request.limit)

    def search_fts(self, query: str, filters: CandidateFilters, limit: int) -> list[dict[str, Any]]:
        self._require_compatible()
        if not self._table_exists():
            return []
        table = self.database.open_table(self.table_name)
        if table.count_rows() == 0:
            return []
        where = self._where(filters)
        builder = table.search(query, query_type="fts", fts_columns="content")
        if where:
            builder = builder.where(where)
        return self._candidate_rows(builder, table.count_rows(), limit, filters)

    def search_vector(self, query_vector: tuple[float, ...], filters: CandidateFilters, limit: int) -> list[dict[str, Any]]:
        self._require_compatible()
        if not self._table_exists() or not query_vector:
            return []
        table = self.database.open_table(self.table_name)
        if table.count_rows() == 0:
            return []
        where = self._where(filters)
        builder = table.search(list(query_vector), vector_column_name="vector", query_type="vector")
        if where:
            builder = builder.where(where, prefilter=True)
        return self._candidate_rows(builder, table.count_rows(), limit, filters)

    def _candidate_rows(self, builder: Any, row_count: int, limit: int,
                        filters: CandidateFilters) -> list[dict[str, Any]]:
        """Expand ranked recall until enough *eligible candidates*, or all rows, are read."""
        retrieval_limit = min(max(limit, 32), row_count)
        while retrieval_limit:
            self._check_deadline()
            rows = builder.limit(retrieval_limit).to_list()
            self._check_deadline()
            unique: dict[str, dict[str, Any]] = {}
            for row in rows:
                unique.setdefault(row["candidate_id"], row)
            if filters.exclude_skills:
                from kerui_recruit.search.query import has_skill
                evidence = self.get_candidate_chunk_contents(list(unique))
                if any(not evidence.get(cid) for cid in unique):
                    raise ValueError("EXCLUSION_UNVERIFIED")
                unique = {cid: row for cid, row in unique.items() if evidence.get(cid) and not any(
                    has_skill(content, skill) for content in evidence[cid] for skill in filters.exclude_skills)}
                for row in unique.values():
                    row["_verified_exclusions"] = filters.exclude_skills
            if len(unique) >= limit or len(rows) < retrieval_limit or retrieval_limit >= row_count:
                return list(unique.values())[:limit]
            retrieval_limit = min(retrieval_limit * 2, row_count)
        return []

    @staticmethod
    def _check_deadline() -> None:
        deadline = SEARCH_DEADLINE.get()
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Search deadline reached")

    def fuse(self, fts_rows: list[dict[str, Any]], vector_rows: list[dict[str, Any]], limit: int) -> list[SearchHit]:
        return self._rrf(fts_rows, vector_rows, limit)

    def filter_search(self, filters: CandidateFilters, limit: int) -> list[SearchHit]:
        """Filter-only retrieval（无文本/语义查询），用于纯过滤条件查询。"""
        self._require_compatible()
        if not self._table_exists():
            return []
        table = self.database.open_table(self.table_name)
        if table.count_rows() == 0:
            return []
        where = self._where(filters)
        builder = table.search(None)
        if where:
            builder = builder.where(where)
        # Exclusions are verified by the service within the request deadline.
        rows = self._candidate_rows(builder, table.count_rows(), limit, filters)
        return [self._hit_from_row(row, 0.0, ()) for row in rows]

    @staticmethod
    def _hit_from_row(row: dict[str, Any], score: float, channels: tuple[str, ...]) -> SearchHit:
        return SearchHit(
            chunk_id=row["id"],
            candidate_id=row["candidate_id"],
            revision_id=row["revision_id"],
            content=row["content"],
            score=score,
            matched_channels=channels,
            total_years=row.get("total_years"),
            highest_degree=row.get("highest_degree"),
            location=row.get("location"),
            qs_rank=row.get("qs_rank"),
            verified_exclusions=tuple(row.get("_verified_exclusions", ())),
        )

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
                    qs_rank=row.get("qs_rank"),
                    verified_exclusions=tuple(row.get("_verified_exclusions", ())),
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
            "qs_rank": chunk.qs_rank,
            "school_level": chunk.school_level,
            "preferred_location": chunk.preferred_location,
            "preferred_locations": list(dict.fromkeys((
                *((chunk.preferred_location,) if chunk.preferred_location else ()), *chunk.preferred_locations))),
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
                pa.field("qs_rank", pa.int64()),
                pa.field("school_level", pa.string()),
                pa.field("preferred_location", pa.string()),
                pa.field("preferred_locations", pa.list_(pa.string())),
            ]
        )

    @classmethod
    def _where(cls, filters: CandidateFilters) -> str:
        clauses: list[str] = []
        if filters.min_years is not None:
            clauses.append(f"total_years >= {float(filters.min_years)}")
        if filters.max_years is not None:
            clauses.append(f"total_years <= {float(filters.max_years)}")
        degree_values = filters.degree_values()
        if degree_values:
            quoted = ", ".join(cls._quote(d) for d in degree_values)
            clauses.append(f"highest_degree IN ({quoted})")
        location_values = filters.location_values()
        if location_values:
            quoted = ", ".join(cls._quote(loc) for loc in location_values)
            clauses.append(f"location IN ({quoted})")
        preferred_values = filters.preferred_location_values()
        if preferred_values:
            quoted = ", ".join(cls._quote(loc) for loc in preferred_values)
            clauses.append(f"array_has_any(preferred_locations, [{quoted}])")
        if filters.candidate_status:
            clauses.append(
                f"candidate_status = {cls._quote(filters.candidate_status)}"
            )
        if filters.max_qs_rank is not None:
            clauses.append(f"qs_rank <= {int(filters.max_qs_rank)}")
        school_values = filters.school_level_values()
        if school_values:
            quoted = ", ".join(cls._quote(s) for s in school_values)
            clauses.append(f"school_level IN ({quoted})")
        return " AND ".join(clauses)

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
