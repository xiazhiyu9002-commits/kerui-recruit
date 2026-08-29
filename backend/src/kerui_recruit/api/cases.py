from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/case", tags=["case"])


class CreateCaseRequest(BaseModel):
    candidate_id: str = Field(min_length=1)
    jd_id: str = Field(min_length=1)
    note: str | None = None


class AdvanceCaseRequest(BaseModel):
    stage: str = Field(min_length=1)
    note: str | None = None


class CaseResponse(BaseModel):
    id: str
    candidate_id: str
    jd_id: str
    stage: str
    note: str | None


class StageEventResponse(BaseModel):
    id: str
    stage: str
    note: str | None


@router.post("", response_model=CaseResponse)
def create_case(command: CreateCaseRequest, request: Request) -> CaseResponse:
    services: AppServices = request.app.state.services
    case = services.case_service.create(
        candidate_id=command.candidate_id,
        jd_id=command.jd_id,
        note=command.note,
    )
    return _case_to_response(case)


@router.get("", response_model=list[CaseResponse])
def list_cases(
    request: Request,
    candidate_id: str | None = None,
    jd_id: str | None = None,
) -> list[CaseResponse]:
    services: AppServices = request.app.state.services
    cases = services.case_service.list_cases(candidate_id=candidate_id, jd_id=jd_id)
    return [_case_to_response(c) for c in cases]


@router.get("/{case_id}/events", response_model=list[StageEventResponse])
def get_events(case_id: str, request: Request) -> list[StageEventResponse]:
    services: AppServices = request.app.state.services
    events = services.case_service.get_events(case_id)
    return [StageEventResponse(id=e.id, stage=e.stage, note=e.note) for e in events]


@router.post("/{case_id}/advance", response_model=CaseResponse)
def advance_case(
    case_id: str, command: AdvanceCaseRequest, request: Request
) -> CaseResponse:
    services: AppServices = request.app.state.services
    case = services.case_service.advance(case_id, stage=command.stage, note=command.note)
    return _case_to_response(case)


@router.post("/{case_id}/undo", response_model=CaseResponse)
def undo_case(case_id: str, request: Request) -> CaseResponse:
    services: AppServices = request.app.state.services
    case = services.case_service.undo(case_id)
    return _case_to_response(case)


def _case_to_response(case) -> CaseResponse:
    return CaseResponse(
        id=case.id,
        candidate_id=case.candidate_id,
        jd_id=case.jd_id,
        stage=case.stage,
        note=case.note,
    )
