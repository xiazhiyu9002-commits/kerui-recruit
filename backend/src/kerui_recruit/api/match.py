from fastapi import APIRouter, Request
from fastapi.responses import Response
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


class ReverseMatchItem(BaseModel):
    jd_id: str
    revision_id: str
    company: str
    title: str
    score: float


@router.post("/jd", response_model=MatchResponse)
async def match_jd(command: MatchJdRequest, request: Request) -> MatchResponse:
    services: AppServices = request.app.state.services
    page = await services.match_service.match_jd(
        revision_id=command.revision_id,
        limit=command.limit,
    )
    run_id = services.match_service.record_run(
        revision_id=command.revision_id,
        hits=page.items,
    )
    return MatchResponse(
        run_id=run_id,
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


@router.get("/run/{run_id}/export")
def export_match_run(run_id: str, request: Request) -> Response:
    services: AppServices = request.app.state.services
    xlsx_bytes = services.export_service.export_match_run(run_id)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="match_{run_id}.xlsx"'},
    )


@router.get("/reverse/{candidate_id}", response_model=list[ReverseMatchItem])
async def reverse_match(candidate_id: str, request: Request) -> list[ReverseMatchItem]:
    services: AppServices = request.app.state.services
    matches = await services.scheduler_service.reverse_match_candidate(candidate_id)
    return [
        ReverseMatchItem(
            jd_id=m.jd_id,
            revision_id=m.revision_id,
            company=m.company,
            title=m.title,
            score=m.score,
        )
        for m in matches
    ]