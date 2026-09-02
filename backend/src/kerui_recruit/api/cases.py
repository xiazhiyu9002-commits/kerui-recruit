from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import Candidate, CandidateJobCase, CaseEvent, Jd


router = APIRouter(prefix="/api/case", tags=["case"])


class CreateCaseRequest(BaseModel):
    candidate_id: str = Field(min_length=1)
    jd_id: str = Field(min_length=1)
    note: str | None = None


class CaseResponse(BaseModel):
    id: str
    candidate_id: str
    jd_id: str
    stage: str
    note: str | None
    candidate_name: str = ""
    company: str = ""
    jd_title: str = ""
    can_advance: bool = True
    blocked_reason: str | None = None


class RoundResponse(BaseModel):
    id: str
    round_no: int
    round_name: str
    round_type: str | None
    skipped: bool


class EventResponse(BaseModel):
    id: str
    event_type: str
    case_round_id: str | None
    round_name: str | None
    occurred_at: datetime
    recorded_at: datetime
    result: str | None
    note: str | None
    status: str

    @field_validator("occurred_at", "recorded_at", mode="before")
    @classmethod
    def utc_wire_time(cls, value):
        return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


class CaseDetailResponse(CaseResponse):
    rounds: list[RoundResponse]
    events: list[EventResponse]
    process_rounds: list[dict] = Field(default_factory=list)
    template_version: int | None = None


class TimeAndNote(BaseModel):
    occurred_at: datetime | None = None
    note: str | None = None
    idempotency_key: str | None = None


class EnterInterviewRequest(TimeAndNote):
    round_name: str | None = None
    round_type: str | None = None


class RecordResultRequest(TimeAndNote):
    case_round_id: str = Field(min_length=1)
    result: str = Field(min_length=1)


class PassAndAdvanceRequest(TimeAndNote):
    case_round_id: str = Field(min_length=1)
    next_round_name: str | None = None
    next_round_type: str | None = None


class OfferStatusRequest(TimeAndNote):
    result: str = Field(min_length=1)


class ExitRequest(TimeAndNote):
    result: str | None = None


class VoidEventRequest(BaseModel):
    note: str | None = None


class ProcessRoundItem(BaseModel):
    round_no: int
    round_name: str
    round_type: str | None = None


class SetProcessRequest(BaseModel):
    rounds: list[ProcessRoundItem]


@router.post("", response_model=CaseResponse)
def create_case(command: CreateCaseRequest, request: Request) -> CaseResponse:
    services: AppServices = request.app.state.services
    case = services.case_service.create(
        candidate_id=command.candidate_id,
        jd_id=command.jd_id,
        note=command.note,
    )
    return _case_to_response(case, _contexts(services, [case.id]).get(case.id, {}))


@router.get("", response_model=list[CaseResponse])
def list_cases(
    request: Request,
    candidate_id: str | None = None,
    jd_id: str | None = None,
) -> list[CaseResponse]:
    services: AppServices = request.app.state.services
    cases = services.case_service.list_cases(candidate_id=candidate_id, jd_id=jd_id)
    contexts = _contexts(services, [c.id for c in cases])
    return [_case_to_response(c, contexts.get(c.id, {})) for c in cases]


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(case_id: str, request: Request) -> CaseDetailResponse:
    services: AppServices = request.app.state.services
    case = services.case_service.get(case_id)
    rounds = services.case_service.get_rounds(case_id)
    events = services.case_service.get_timeline(case_id)
    round_names = {r.id: r.round_name for r in rounds}
    return CaseDetailResponse(
        id=case.id,
        candidate_id=case.candidate_id,
        jd_id=case.jd_id,
        stage=case.stage,
        note=case.note,
        **_contexts(services, [case_id]).get(case_id, {}),
        process_rounds=case.template_snapshot or [],
        template_version=case.template_version,
        rounds=[
            RoundResponse(
                id=r.id,
                round_no=r.round_no,
                round_name=r.round_name,
                round_type=r.round_type,
                skipped=r.skipped,
            )
            for r in rounds
        ],
        events=[
            EventResponse(
                id=e.id,
                event_type=e.event_type,
                case_round_id=e.case_round_id,
                round_name=round_names.get(e.case_round_id) if e.case_round_id else None,
                occurred_at=e.occurred_at,
                recorded_at=e.recorded_at,
                result=e.result,
                note=e.note,
                status=e.status,
            )
            for e in events
        ],
    )


@router.post("/{case_id}/recommend", response_model=EventResponse)
def recommend(case_id: str, command: TimeAndNote, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.recommend(
        case_id,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/{case_id}/enter-interview", response_model=EventResponse)
def enter_interview(case_id: str, command: EnterInterviewRequest, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.enter_interview(
        case_id,
        round_name=command.round_name,
        round_type=command.round_type,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/{case_id}/result", response_model=EventResponse)
def record_result(case_id: str, command: RecordResultRequest, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.record_result(
        case_id,
        case_round_id=command.case_round_id,
        result=command.result,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/{case_id}/pass-and-advance", response_model=list[EventResponse])
def pass_and_advance(case_id: str, command: PassAndAdvanceRequest, request: Request) -> list[EventResponse]:
    services: AppServices = request.app.state.services
    events = services.case_service.pass_and_advance(
        case_id,
        case_round_id=command.case_round_id,
        next_round_name=command.next_round_name,
        next_round_type=command.next_round_type,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return [_event_to_response(e) for e in events]


@router.post("/{case_id}/offer", response_model=EventResponse)
def offer(case_id: str, command: TimeAndNote, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.offer(
        case_id,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/{case_id}/offer-status", response_model=EventResponse)
def offer_status(case_id: str, command: OfferStatusRequest, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.update_offer(
        case_id,
        result=command.result,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/{case_id}/onboard", response_model=EventResponse)
def onboard(case_id: str, command: TimeAndNote, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.onboard(
        case_id,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/{case_id}/exit", response_model=EventResponse)
def exit_case(case_id: str, command: ExitRequest, request: Request) -> EventResponse:
    services: AppServices = request.app.state.services
    event = services.case_service.exit(
        case_id,
        result=command.result,
        occurred_at=command.occurred_at,
        note=command.note,
        idempotency_key=command.idempotency_key,
    )
    return _event_to_response(event)


@router.post("/event/{event_id}/void")
def void_event(event_id: str, command: VoidEventRequest, request: Request) -> dict:
    services: AppServices = request.app.state.services
    services.case_service.void_event(event_id, note=command.note)
    return {"deleted": event_id}


@router.get("/process/{jd_id}")
def get_process(jd_id: str, request: Request) -> list[dict]:
    services: AppServices = request.app.state.services
    return services.case_service.get_process(jd_id)


@router.put("/process/{jd_id}")
def set_process(jd_id: str, command: SetProcessRequest, request: Request) -> list[dict]:
    services: AppServices = request.app.state.services
    return services.case_service.set_process(
        jd_id, [item.model_dump() for item in command.rounds]
    )


def _contexts(services, ids):
    if not ids:
        return {}
    with services.session_factory() as session:
        rows = session.execute(select(CandidateJobCase, Candidate, Jd)
            .join(Candidate, CandidateJobCase.candidate_id == Candidate.id)
            .join(Jd, CandidateJobCase.jd_id == Jd.id).where(CandidateJobCase.id.in_(ids))).all()
    result = {}
    for case, candidate, jd in rows:
        reason = None
        if case.deleted_at or jd.deleted_at or jd.status != "OPEN":
            reason = "岗位已关闭或删除"
        elif candidate.deleted_at or candidate.status != "AVAILABLE":
            reason = "候选人不可推荐或待复核"
        elif case.stage in ("入职", "候选人拒绝", "客户拒绝"):
            reason = "流程已结束，可查看历史或纠错"
        result[case.id] = {"candidate_name": candidate.display_name, "company": jd.company,
            "jd_title": jd.title, "can_advance": reason is None, "blocked_reason": reason}
    return result


def _case_to_response(case: CandidateJobCase, context: dict | None = None) -> CaseResponse:
    return CaseResponse(
        id=case.id,
        candidate_id=case.candidate_id,
        jd_id=case.jd_id,
        stage=case.stage,
        note=case.note,
        **(context or {}),
    )


def _event_to_response(event: CaseEvent) -> EventResponse:
    return EventResponse(
        id=event.id,
        event_type=event.event_type,
        case_round_id=event.case_round_id,
        round_name=None,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        result=event.result,
        note=event.note,
        status=event.status,
    )
