"""机器方向显式重评估：在无人工覆盖时更新有效方向，有人工覆盖时只更新机器草稿。"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import JdRevision, ResumeRevision
from kerui_recruit.direction.backfill import _build_input, _input_fingerprint
from kerui_recruit.direction.classifier import DirectionClassificationInput, DirectionClassifier
from kerui_recruit.direction.models import (
    DirectionProfile,
    OUTCOME_PROVIDER_DISABLED,
    OUTCOME_SUCCESS_DIRECTION,
    OUTCOME_SUCCESS_UNKNOWN,
    build_direction_diagnostics,
    parse_direction_profile,
)
from kerui_recruit.direction.service import DirectionConflict, DirectionService
from kerui_recruit.search.sync import enqueue_sync


class DirectionInputChanged(ValueError):
    code = "E_DIRECTION_INPUT_CHANGED"


@dataclass(frozen=True, slots=True)
class DirectionEvaluationResult:
    machine_profile: DirectionProfile
    manual_profile: DirectionProfile | None
    effective_profile: DirectionProfile
    profile_version: str


class DirectionEvaluationService:
    """显式机器方向重评估。严禁在 SQLite 事务内等待 LLM。"""

    def __init__(self, session_factory: sessionmaker[Session], classifier: DirectionClassifier,
                 direction_service: DirectionService) -> None:
        self.session_factory = session_factory
        self.classifier = classifier
        self.direction_service = direction_service

    async def re_evaluate(self, entity_type: str, entity_id: str,
                          expected_profile_version: str | None = None) -> DirectionEvaluationResult:
        model = ResumeRevision if entity_type == "resume_revision" else JdRevision
        with self.session_factory() as session:
            revision = session.get(model, entity_id)
            if revision is None:
                raise LookupError(f"{entity_type} not found: {entity_id}")
            if not getattr(revision, "is_current", True):
                raise DirectionConflict("只能重评估当前版本的岗位或简历方向")
            parsed_before = dict(revision.parsed_data or {})
            old_effective = parse_direction_profile(parsed_before.get("direction_profile"))
            if expected_profile_version is not None:
                version = self.direction_service._profile_version(session, entity_type, entity_id, old_effective)
                if expected_profile_version != version:
                    raise DirectionConflict("方向已被他人修改，请刷新后重试")
            payload_before = _build_input(parsed_before, entity_type)
            fingerprint_before = _input_fingerprint(payload_before)

        # 关事务后调用 LLM。
        decision = await self.classifier.classify(payload_before)

        with self.session_factory() as session, session.begin():
            revision = session.get(model, entity_id)
            if revision is None:
                raise LookupError(f"{entity_type} not found: {entity_id}")
            if not getattr(revision, "is_current", True):
                raise DirectionConflict("只能重评估当前版本的岗位或简历方向")
            current_parsed = dict(revision.parsed_data or {})
            fingerprint_after = _input_fingerprint(_build_input(current_parsed, entity_type))
            if fingerprint_before != fingerprint_after:
                raise DirectionInputChanged("简历或岗位内容已变化，请刷新后重试")
            current_effective = parse_direction_profile(current_parsed.get("direction_profile"))
            # LLM 返回后重新校验 profile version（等待期间可能被他人保存）。
            if expected_profile_version is not None:
                version_after = self.direction_service._profile_version(
                    session, entity_type, entity_id, current_effective)
                if expected_profile_version != version_after:
                    raise DirectionConflict("方向已被他人修改，请刷新后重试")

            manual_profile = parse_direction_profile(
                (dict(revision.manual_overrides or {})).get("direction_profile")) \
                if (revision.manual_overrides or {}).get("direction_profile") else None

            outcome = decision.outcome
            old_valid = old_effective.status != "UNKNOWN"
            if outcome == OUTCOME_SUCCESS_DIRECTION:
                overwrite = True
            elif outcome in (OUTCOME_SUCCESS_UNKNOWN, OUTCOME_PROVIDER_DISABLED):
                # 成功但 UNKNOWN：不降级也不升级，保持旧值。
                # Provider 不可用：安全保持原值，零写入。
                overwrite = False
            else:
                # 失败类别：旧值有效绝不覆盖；旧值 UNKNOWN 仅可靠规则兜底时更新。
                overwrite = (not old_valid) and decision.used_rule_fallback

            review = dict(revision.review_data or {})
            review["direction_diagnostics"] = build_direction_diagnostics(decision)
            if overwrite:
                machine_json = decision.effective_profile.model_dump(mode="json")
                review["direction_profile"] = machine_json
                if manual_profile is None:
                    parsed = dict(revision.parsed_data or {})
                    parsed["direction_profile"] = machine_json
                    revision.parsed_data = parsed
                    kind, entity_key = DirectionService._index_target(revision)
                    enqueue_sync(session, kind, entity_key, mode="METADATA")
            revision.review_data = review

            effective = parse_direction_profile((dict(revision.parsed_data or {})).get("direction_profile"))
            machine = parse_direction_profile((dict(revision.review_data or {})).get("direction_profile"))
            version = self.direction_service._profile_version(session, entity_type, entity_id, effective)

        return DirectionEvaluationResult(
            machine_profile=machine,
            manual_profile=manual_profile,
            effective_profile=effective,
            profile_version=version,
        )
