from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices
from kerui_recruit.search.contracts import CandidateFilters
from kerui_recruit.search.query import parse_query


router = APIRouter(prefix="/api/search", tags=["search"])


class CandidateFiltersRequest(BaseModel):
    min_years: float | None = Field(default=None, ge=0, le=80)
    highest_degree: str | None = None
    location: str | None = None
    candidate_status: str | None = "AVAILABLE"
    max_qs_rank: int | None = Field(default=None, ge=1)


class CandidateSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    filters: CandidateFiltersRequest = Field(default_factory=CandidateFiltersRequest)
    limit: int = Field(default=20, ge=1, le=100)


class CandidateSearchItem(BaseModel):
    candidate_id: str
    revision_id: str
    content: str
    score: float
    matched_channels: tuple[str, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None
    qs_rank: int | None = None


class CandidateSearchResponse(BaseModel):
    items: list[CandidateSearchItem]
    degraded_reasons: list[str]


@router.post("/candidates", response_model=CandidateSearchResponse)
async def search_candidates(
    command: CandidateSearchRequest,
    request: Request,
) -> CandidateSearchResponse:
    services: AppServices = request.app.state.services
    parsed = parse_query(command.query)
    explicit = CandidateFilters(**command.filters.model_dump())
    page = await services.search_service.search(
        parsed.keywords,
        _merge_filters(parsed.filters, explicit),
        limit=command.limit,
    )
    return CandidateSearchResponse(
        items=[
            CandidateSearchItem(
                candidate_id=hit.candidate_id,
                revision_id=hit.revision_id,
                content=hit.content,
                score=hit.score,
                matched_channels=hit.matched_channels,
                total_years=hit.total_years,
                highest_degree=hit.highest_degree,
                location=hit.location,
                qs_rank=hit.qs_rank,
            )
            for hit in page.items
        ],
        degraded_reasons=list(page.degraded_reasons),
    )


def _merge_filters(parsed: CandidateFilters, explicit: CandidateFilters) -> CandidateFilters:
    """Explicit form filters win over natural-language conditions; otherwise fall back."""
    return CandidateFilters(
        min_years=explicit.min_years if explicit.min_years is not None else parsed.min_years,
        highest_degree=explicit.highest_degree or parsed.highest_degree,
        location=explicit.location or parsed.location,
        candidate_status=explicit.candidate_status or parsed.candidate_status,
        max_qs_rank=explicit.max_qs_rank if explicit.max_qs_rank is not None else parsed.max_qs_rank,
    )
