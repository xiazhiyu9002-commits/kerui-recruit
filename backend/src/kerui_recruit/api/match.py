from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/match", tags=["match"])


class MatchJdRequest(BaseModel):
    revision_id: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class MatchItem(BaseModel):
    candidate_id: str
    revision_id: str
    content: str
    score: float
    matched_channels: tuple[str, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None


class MatchResponse(BaseModel):
    run_id: str
    items: list[MatchItem]


@router.post("/jd", response_model=MatchResponse)
async def match_jd(command: MatchJdRequest, request: Request) -> MatchResponse:
    services: AppServices = request.app.state.services
    page = await services.match_service.match_jd(
        revision_id=command.revision_id,
        limit=command.limit,
    )
    return MatchResponse(
        run_id="",
        items=[
            MatchItem(
                candidate_id=hit.candidate_id,
                revision_id=hit.revision_id,
                content=hit.content,
                score=hit.score,
                matched_channels=hit.matched_channels,
                total_years=hit.total_years,
                highest_degree=hit.highest_degree,
                location=hit.location,
            )
            for hit in page.items
        ],
    )