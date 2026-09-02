from pathlib import Path

from kerui_recruit.search.contracts import SearchChunk
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex


class JdSearchIndex:
    """A separate, versioned hybrid projection of open, current, READY jobs.

    The durable sync worker owns eligibility and computes one embedding per JD
    revision. Candidate matching queries this index, never the talent pool.
    """

    def __init__(self, root: Path, *, vector_dimension: int,
                 embedding_model: str = "unspecified", schema_version: str = "2",
                 chunk_version: str = "1") -> None:
        self.index = LanceDBSearchIndex(root, vector_dimension=vector_dimension,
                                       embedding_model=embedding_model,
                                       schema_version=schema_version, chunk_version=chunk_version)

    def upsert(self, *, jd_id: str, revision_id: str, content: str,
               vector: tuple[float, ...] | list[float], company: str = "", title: str = "",
               min_years: float | None = None, highest_degree: str | None = None,
               location: str | None = None) -> None:
        self.index.replace_candidate([SearchChunk(
            id=f"jd:{jd_id}:{revision_id}", candidate_id=jd_id, revision_id=revision_id,
            content=content, vector=tuple(vector), total_years=min_years,
            highest_degree=highest_degree, location=location, candidate_status="AVAILABLE")])

    def delete_jd(self, jd_id: str) -> None:
        self.index.delete_candidate(jd_id)

    def is_ready(self) -> bool:
        return self.index.is_ready() and self.index.warmup() > 0
