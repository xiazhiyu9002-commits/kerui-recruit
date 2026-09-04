from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import JdRevision, ResumeRevision
from kerui_recruit.direction.evaluation import DirectionEvaluationResult, DirectionInputChanged
from kerui_recruit.direction.models import DirectionProfile
from kerui_recruit.direction.service import (
    DirectionConflict,
    DirectionOverrideResult,
    DirectionProfileDetail,
    DirectionTaxonomyVersionError,
)
from kerui_recruit.direction.taxonomy import (
    BUSINESS_DOMAIN_LABELS,
    LEADERSHIP_LABELS,
    ROLE_FAMILIES,
    TAXONOMY_VERSION,
)
from kerui_recruit.search.live import projection_is_current

router = APIRouter(tags=["directions"])


class SaveDirectionProfileRequest(BaseModel):
    direction_profile: DirectionProfile
    reason: str | None = None
    expected_profile_version: str | None = None


class DirectionProfileResponse(BaseModel):
    direction_profile: DirectionProfile
    profile_version: str
    correction_id: str | None = None


class DirectionProfileDetailResponse(BaseModel):
    direction_profile: DirectionProfile
    effective_profile: DirectionProfile
    machine_profile: DirectionProfile
    manual_profile: DirectionProfile | None = None
    profile_version: str
    latest_active_correction_id: str | None = None
    has_manual_override: bool = False
    sync_status: str = "未知"
    scoring_impact: dict = {}


class ReevaluateDirectionRequest(BaseModel):
    expected_profile_version: str | None = None


class DirectionEvaluationResponse(BaseModel):
    machine_profile: DirectionProfile
    manual_profile: DirectionProfile | None = None
    effective_profile: DirectionProfile
    profile_version: str


@router.get("/api/directions/taxonomy")
def taxonomy() -> dict:
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "role_families": [
            {"code": rf.code, "label": rf.label, "aliases": list(rf.aliases)}
            for rf in ROLE_FAMILIES
        ],
        "leadership": LEADERSHIP_LABELS,
        "business_domains": BUSINESS_DOMAIN_LABELS,
    }


@router.get("/api/resumes/revisions/{revision_id}/direction-profile", response_model=DirectionProfileDetailResponse)
def get_resume_direction_profile(revision_id: str, request: Request) -> DirectionProfileDetailResponse:
    services: AppServices = request.app.state.services
    detail = services.direction_service.get_profile_detail("resume_revision", revision_id)
    return _to_detail_response(detail, sync_status=_sync_status(services, "resume_revision", revision_id))


@router.put("/api/resumes/revisions/{revision_id}/direction-profile", response_model=DirectionProfileResponse)
def put_resume_direction_profile(revision_id: str, command: SaveDirectionProfileRequest, request: Request) -> DirectionProfileResponse:
    services: AppServices = request.app.state.services
    result = _save(services, "resume_revision", revision_id, command)
    return DirectionProfileResponse(direction_profile=result.profile, profile_version=result.profile_version, correction_id=result.correction_id)


@router.get("/api/jd/revisions/{revision_id}/direction-profile", response_model=DirectionProfileDetailResponse)
def get_jd_direction_profile(revision_id: str, request: Request) -> DirectionProfileDetailResponse:
    services: AppServices = request.app.state.services
    detail = services.direction_service.get_profile_detail("jd_revision", revision_id)
    return _to_detail_response(detail, sync_status=_sync_status(services, "jd_revision", revision_id))


@router.put("/api/jd/revisions/{revision_id}/direction-profile", response_model=DirectionProfileResponse)
def put_jd_direction_profile(revision_id: str, command: SaveDirectionProfileRequest, request: Request) -> DirectionProfileResponse:
    services: AppServices = request.app.state.services
    result = _save(services, "jd_revision", revision_id, command)
    return DirectionProfileResponse(direction_profile=result.profile, profile_version=result.profile_version, correction_id=result.correction_id)


@router.post("/api/resumes/revisions/{revision_id}/direction-profile/re-evaluate", response_model=DirectionEvaluationResponse)
async def reevaluate_resume_direction(revision_id: str, command: ReevaluateDirectionRequest, request: Request) -> DirectionEvaluationResponse:
    services: AppServices = request.app.state.services
    result = await _reevaluate(services, "resume_revision", revision_id, command)
    return _to_evaluation_response(result)


@router.post("/api/jd/revisions/{revision_id}/direction-profile/re-evaluate", response_model=DirectionEvaluationResponse)
async def reevaluate_jd_direction(revision_id: str, command: ReevaluateDirectionRequest, request: Request) -> DirectionEvaluationResponse:
    services: AppServices = request.app.state.services
    result = await _reevaluate(services, "jd_revision", revision_id, command)
    return _to_evaluation_response(result)


def _to_detail_response(detail: DirectionProfileDetail, *, sync_status: str = "未知") -> DirectionProfileDetailResponse:
    return DirectionProfileDetailResponse(
        direction_profile=detail.effective_profile,
        effective_profile=detail.effective_profile,
        machine_profile=detail.machine_profile,
        manual_profile=detail.manual_profile,
        profile_version=detail.profile_version,
        latest_active_correction_id=detail.latest_active_correction_id,
        has_manual_override=detail.has_manual_override,
        sync_status=sync_status,
        scoring_impact=_scoring_impact(),
    )


def _sync_status(services: AppServices, entity_type: str, entity_id: str) -> str:
    with services.session_factory() as session:
        if entity_type == "resume_revision":
            revision = session.get(ResumeRevision, entity_id)
            if revision is None:
                return "未知"
            kind, key = "candidate", revision.document.candidate_id
        elif entity_type == "jd_revision":
            revision = session.get(JdRevision, entity_id)
            if revision is None:
                return "未知"
            kind, key = "jd", revision.jd_id
        else:
            return "未知"
        current = session.scalar(select(projection_is_current(kind, key)))
        return "已同步" if current else "待同步"


def _scoring_impact() -> dict:
    return {
        "weight": 0.30,
        "description": "方向兼容度在匹配综合分中权重 30%（相关性 35% + 技能覆盖 25% + 方向 30% + 年限 10%）。主方向同时决定搜索时的方向软加权与 JD↔候选人的匹配方向。",
    }


def _to_evaluation_response(result: DirectionEvaluationResult) -> DirectionEvaluationResponse:
    return DirectionEvaluationResponse(
        machine_profile=result.machine_profile,
        manual_profile=result.manual_profile,
        effective_profile=result.effective_profile,
        profile_version=result.profile_version,
    )


async def _reevaluate(services: AppServices, entity_type: str, entity_id: str,
                      command: ReevaluateDirectionRequest) -> DirectionEvaluationResult:
    evaluation = services.direction_evaluation_service
    if evaluation is None:
        raise ApiError(503, "E_DIRECTION_UNAVAILABLE", "方向重评估服务不可用")
    try:
        return await evaluation.re_evaluate(
            entity_type=entity_type,
            entity_id=entity_id,
            expected_profile_version=command.expected_profile_version,
        )
    except DirectionConflict as error:
        raise ApiError(409, error.code, str(error)) from error
    except DirectionInputChanged as error:
        raise ApiError(409, error.code, str(error)) from error
    except LookupError as error:
        raise ApiError(404, "E_DIRECTION_NOT_FOUND", str(error)) from error


def _save(services: AppServices, entity_type: str, entity_id: str, command: SaveDirectionProfileRequest) -> DirectionOverrideResult:
    try:
        return services.direction_service.apply_override(
            entity_type=entity_type,
            entity_id=entity_id,
            profile=command.direction_profile,
            reason=command.reason,
            expected_profile_version=command.expected_profile_version,
        )
    except DirectionConflict as error:
        raise ApiError(409, error.code, str(error)) from error
    except DirectionTaxonomyVersionError as error:
        raise ApiError(422, error.code, str(error)) from error
    except LookupError as error:
        raise ApiError(404, "E_DIRECTION_NOT_FOUND", str(error)) from error
