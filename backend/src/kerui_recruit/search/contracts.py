from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SearchChunk:
    id: str
    candidate_id: str
    revision_id: str
    content: str
    vector: tuple[float, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None
    candidate_status: str


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    min_years: float | None = None
    highest_degree: str | None = None
    location: str | None = None
    candidate_status: str | None = "AVAILABLE"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    query_vector: tuple[float, ...]
    filters: CandidateFilters
    limit: int = 20


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    candidate_id: str
    revision_id: str
    content: str
    score: float
    matched_channels: tuple[str, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[SearchHit, ...]
    degraded_reasons: tuple[str, ...] = ()


class SearchIndex(Protocol):
    def upsert(self, chunks: list[SearchChunk]) -> None: ...

    def delete_revision(self, revision_id: str) -> None: ...

    def search(self, request: SearchRequest) -> list[SearchHit]: ...
