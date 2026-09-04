from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import (
    Candidate,
    CandidateContact,
    Jd,
    JdRevision,
    MatchResult,
    MatchRun,
    ResumeRevision,
)
from kerui_recruit.search.contracts import resolve_search_status


router = APIRouter(prefix="/api/match", tags=["match"])


class MatchJdRequest(BaseModel):
    revision_id: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class MatchItem(BaseModel):
    candidate_id: str
    revision_id: str
    name: str = ""
    phone: str | None = None
    parsed_data: dict | None = None
    original_filename: str | None = None
    content: str
    score: float
    matched_channels: tuple[str, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None
    result_id: str | None = None
    jd_primary_direction: str | None = None
    candidate_primary_direction: str | None = None
    candidate_direction_source: str | None = None
    direction_status: str | None = None
    direction_compatibility: float | None = None
    direction_explanation: str | None = None
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class MatchResponse(BaseModel):
    run_id: str | None
    items: list[MatchItem]
    status: str = "success"
    empty_reason: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)


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
    status = resolve_search_status(page.items, page.empty_reason, page.degraded_reasons)
    # index_not_ready / service_error 不应写入看似正常的空 match_run。
    recorded = None
    if status not in ("index_not_ready", "service_error"):
        recorded = services.match_service.record_run(
            revision_id=command.revision_id,
            hits=page.items,
        )
    candidate_ids = [hit.candidate_id for hit in page.items]
    revision_ids = [hit.revision_id for hit in page.items]
    with services.session_factory() as session:
        names: dict[str, str] = {}
        phones: dict[str, str | None] = {}
        if candidate_ids:
            for candidate_id, display_name, phone_encrypted in session.execute(
                select(Candidate.id, Candidate.display_name, CandidateContact.phone_encrypted)
                .outerjoin(CandidateContact, CandidateContact.candidate_id == Candidate.id)
                .where(Candidate.id.in_(candidate_ids))
            ).all():
                names[candidate_id] = display_name
                phones[candidate_id] = phone_encrypted
        revisions = (
            {
                revision.id: revision
                for revision in session.scalars(
                    select(ResumeRevision).where(ResumeRevision.id.in_(revision_ids))
                ).all()
            }
            if revision_ids
            else {}
        )
    encryption = services.encryption_service

    def _item(hit) -> MatchItem:
        match_score = services.match_service.score(command.revision_id, hit)
        return MatchItem(
            candidate_id=hit.candidate_id,
            revision_id=hit.revision_id,
            name=names.get(hit.candidate_id, hit.candidate_id),
            phone=(
                encryption.decrypt(phones.get(hit.candidate_id))
                if encryption is not None and phones.get(hit.candidate_id)
                else None
            ),
            parsed_data=(
                revisions[hit.revision_id].parsed_data
                if hit.revision_id in revisions
                else None
            ),
            original_filename=(
                revisions[hit.revision_id].original_filename
                if hit.revision_id in revisions
                else None
            ),
            content=hit.content,
            score=match_score.total,
            matched_channels=hit.matched_channels,
            total_years=hit.total_years,
            highest_degree=hit.highest_degree,
            location=hit.location,
            result_id=recorded.result_ids.get(hit.candidate_id) if recorded else None,
            jd_primary_direction=match_score.jd_primary_direction,
            candidate_primary_direction=match_score.candidate_primary_direction,
            candidate_direction_source=match_score.candidate_direction_source,
            direction_status=match_score.direction_status,
            direction_compatibility=match_score.breakdown.get("direction_compatibility"),
            direction_explanation=match_score.direction_explanation,
            matched_skills=list(match_score.matched_skills),
            missing_skills=list(match_score.missing_skills),
        )

    return MatchResponse(
        run_id=recorded.run_id if recorded else None,
        status=status,
        empty_reason=page.empty_reason,
        degraded_reasons=list(page.degraded_reasons),
        items=[_item(hit) for hit in page.items],
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


class BatchMatchRequest(BaseModel):
    revision_ids: list[str] = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class BatchMatchResult(BaseModel):
    revision_id: str
    run_id: str
    items: list[MatchItem]


class BatchMatchResponse(BaseModel):
    results: list[BatchMatchResult]


@router.post("/batch", response_model=BatchMatchResponse)
async def match_batch(command: BatchMatchRequest, request: Request) -> BatchMatchResponse:
    services: AppServices = request.app.state.services
    results: list[BatchMatchResult] = []
    for revision_id in command.revision_ids:
        page = await services.match_service.match_jd(
            revision_id=revision_id,
            limit=command.limit,
        )
        recorded = services.match_service.record_run(
            revision_id=revision_id,
            hits=page.items,
        )
        results.append(
            BatchMatchResult(
                revision_id=revision_id,
                run_id=recorded.run_id,
                items=[
                    MatchItem(
                        candidate_id=hit.candidate_id,
                        revision_id=hit.revision_id,
                        content=hit.content,
                        score=services.match_service.score(revision_id, hit).total,
                        matched_channels=hit.matched_channels,
                        total_years=hit.total_years,
                        highest_degree=hit.highest_degree,
                        location=hit.location,
                        result_id=recorded.result_ids.get(hit.candidate_id),
                    )
                    for hit in page.items
                ],
            )
        )
    return BatchMatchResponse(results=results)


class MarkResultRequest(BaseModel):
    status: str = Field(pattern="^(未处理|保留)$")


class MarkResultResponse(BaseModel):
    result_id: str
    status: str


@router.post("/result/{result_id}/mark", response_model=MarkResultResponse)
def mark_result(result_id: str, command: MarkResultRequest, request: Request) -> MarkResultResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session, session.begin():
        result = session.get(MatchResult, result_id)
        if result is None:
            raise ApiError(404, "E_MATCH_RESULT_NOT_FOUND", "匹配结果不存在")
        result.status = command.status
    return MarkResultResponse(result_id=result_id, status=command.status)


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


class MatchResultItem(BaseModel):
    result_id: str
    candidate_id: str
    name: str
    score: float
    status: str
    total_years: float | None
    highest_degree: str | None
    location: str | None
    direction_compatibility: float | None = None
    jd_primary_direction: str | None = None
    candidate_primary_direction: str | None = None
    candidate_direction_source: str | None = None
    direction_status: str | None = None
    direction_explanation: str | None = None
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class MatchResultGroup(BaseModel):
    jd_id: str
    revision_id: str
    company: str
    title: str
    items: list[MatchResultItem]


class MatchResultsResponse(BaseModel):
    groups: list[MatchResultGroup]


@router.get("/results", response_model=MatchResultsResponse)
def list_match_results(
    request: Request,
    limit_per_jd: int = Query(20, ge=1, le=100),
) -> MatchResultsResponse:
    """Group persisted match results by JD, keeping the top-k candidates each."""
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        results = session.scalars(
            select(MatchResult)
            .join(MatchRun, MatchResult.run_id == MatchRun.id)
            .order_by(MatchRun.created_at.desc(), MatchResult.total_score.desc())
        ).all()

        groups: dict[str, MatchResultGroup] = {}
        seen: dict[str, set[str]] = {}
        for result in results:
            revision_id = result.jd_revision_id
            if revision_id is None:
                continue

            group = groups.get(revision_id)
            if group is None:
                revision = session.get(JdRevision, revision_id)
                if revision is None:
                    continue
                jd = session.get(Jd, revision.jd_id)
                group = MatchResultGroup(
                    jd_id=revision.jd_id,
                    revision_id=revision_id,
                    company=jd.company if jd else "—",
                    title=jd.title if jd else "—",
                    items=[],
                )
                groups[revision_id] = group
                seen[revision_id] = set()

            if result.candidate_id in seen[revision_id]:
                continue
            if len(group.items) >= limit_per_jd:
                continue
            seen[revision_id].add(result.candidate_id)

            candidate = session.get(Candidate, result.candidate_id)
            revision = (
                session.get(ResumeRevision, result.resume_revision_id)
                if result.resume_revision_id
                else None
            )
            breakdown = result.score_breakdown or {}
            group.items.append(
                MatchResultItem(
                    result_id=result.id,
                    candidate_id=result.candidate_id,
                    name=candidate.display_name if candidate else result.candidate_id,
                    score=float(result.total_score or 0),
                    status=result.status,
                    total_years=(
                        float(candidate.total_years)
                        if candidate and candidate.total_years is not None
                        else None
                    ),
                    highest_degree=candidate.highest_degree if candidate else None,
                    location=(
                        (revision.parsed_data or {}).get("location")
                        if revision and revision.parsed_data
                        else None
                    ),
                    direction_compatibility=breakdown.get("direction_compatibility"),
                    jd_primary_direction=breakdown.get("jd_primary_direction"),
                    candidate_primary_direction=breakdown.get("candidate_primary_direction"),
                    candidate_direction_source=breakdown.get("candidate_direction_source"),
                    direction_status=breakdown.get("direction_status"),
                    direction_explanation=breakdown.get("direction_explanation"),
                    matched_skills=breakdown.get("matched_skills") or [],
                    missing_skills=breakdown.get("missing_skills") or [],
                )
            )
    return MatchResultsResponse(groups=list(groups.values()))


@router.get("/jd/{revision_id}/export")
def export_match_jd(revision_id: str, request: Request) -> Response:
    services: AppServices = request.app.state.services
    xlsx_bytes = services.export_service.export_match_jd(revision_id)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="match_{revision_id}.xlsx"'},
    )


class CreateCaseFromResultResponse(BaseModel):
    case_id: str
    result_id: str
    status: str


@router.post("/result/{result_id}/create-case", response_model=CreateCaseFromResultResponse)
def create_case_from_result(result_id: str, request: Request) -> CreateCaseFromResultResponse:
    """Turn a persisted match result into a recruitment case and link it back."""
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        result = session.get(MatchResult, result_id)
        if result is None:
            raise ApiError(404, "E_MATCH_RESULT_NOT_FOUND", "匹配结果不存在")
        revision = (
            session.get(JdRevision, result.jd_revision_id)
            if result.jd_revision_id
            else None
        )
        if revision is None:
            raise ApiError(409, "E_MATCH_RESULT_NO_JD", "匹配结果缺少岗位信息")
        candidate_id = result.candidate_id
        jd_id = revision.jd_id

    case = services.case_service.create(candidate_id=candidate_id, jd_id=jd_id)

    with services.session_factory() as session, session.begin():
        result = session.get(MatchResult, result_id)
        result.case_id = case.id
        result.status = "保留"
    return CreateCaseFromResultResponse(
        case_id=case.id, result_id=result_id, status="保留"
    )


class CandidateMatchItem(BaseModel):
    result_id: str
    jd_id: str
    revision_id: str
    company: str
    title: str
    score: float
    status: str
    case_id: str | None
    jd_status: str = "OPEN"
    ai_category: str | None = None
    parsed_data: dict | None = None
    source_text: str | None = None


@router.get("/candidate/{candidate_id}", response_model=list[CandidateMatchItem])
def list_candidate_matches(candidate_id: str, request: Request) -> list[CandidateMatchItem]:
    """Return persisted matches for one candidate, deduplicated by JD."""
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        results = session.scalars(
            select(MatchResult)
            .join(MatchRun, MatchResult.run_id == MatchRun.id)
            .where(MatchResult.candidate_id == candidate_id)
            .order_by(MatchRun.created_at.desc(), MatchResult.total_score.desc())
        ).all()

        items: list[CandidateMatchItem] = []
        seen_jd: set[str] = set()
        for result in results:
            revision_id = result.jd_revision_id
            if revision_id is None:
                continue
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                continue
            if revision.jd_id in seen_jd:
                continue
            seen_jd.add(revision.jd_id)
            jd = session.get(Jd, revision.jd_id)
            items.append(
                CandidateMatchItem(
                    result_id=result.id,
                    jd_id=revision.jd_id,
                    revision_id=revision_id,
                    company=jd.company if jd else "—",
                    title=jd.title if jd else "—",
                    score=float(result.total_score or 0),
                    status=result.status,
                    case_id=result.case_id,
                )
            )
    return items


@router.post("/candidate/{candidate_id}", response_model=list[CandidateMatchItem])
async def match_candidate(candidate_id: str, request: Request) -> list[CandidateMatchItem]:
    """Run and persist a candidate-driven reverse match, returning the matched JDs."""
    services: AppServices = request.app.state.services
    records = await services.match_service.reverse_match_candidate(candidate_id)
    recorded = services.match_service.record_reverse_run(
        candidate_id=candidate_id,
        records=records,
    )
    with services.session_factory() as session:
        jds = {
            jd.id: jd
            for jd in session.scalars(
                select(Jd).where(Jd.id.in_([record.jd_id for record in records]))
            ).all()
        } if records else {}
        revisions = {
            revision.id: revision
            for revision in session.scalars(
                select(JdRevision).where(
                    JdRevision.id.in_([record.revision_id for record in records])
                )
            ).all()
        } if records else {}
    items: list[CandidateMatchItem] = []
    for record in records:
        total = (record.score or services.match_service.score(record.revision_id, record.hit)).total
        jd = jds.get(record.jd_id)
        revision = revisions.get(record.revision_id)
        items.append(
            CandidateMatchItem(
                result_id=recorded.result_ids.get(record.revision_id) or "",
                jd_id=record.jd_id,
                revision_id=record.revision_id,
                company=record.company,
                title=record.title,
                score=total,
                status="未处理",
                case_id=None,
                jd_status=jd.status if jd else "OPEN",
                ai_category=revision.ai_category if revision else None,
                parsed_data=revision.parsed_data if revision else None,
                source_text=revision.source_text if revision else None,
            )
        )
    return items
