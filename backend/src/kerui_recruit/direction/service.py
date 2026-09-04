from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import CorrectionLog, JdRevision, ResumeRevision
from kerui_recruit.direction.models import (
    CLASSIFIER_VERSION,
    TAXONOMY_VERSION,
    DirectionProfile,
    parse_direction_profile,
)
from kerui_recruit.search.sync import enqueue_sync


class DirectionConflict(ValueError):
    code = "E_DIRECTION_CONFLICT"


class DirectionTaxonomyVersionError(ValueError):
    code = "E_DIRECTION_TAXONOMY_VERSION"


@dataclass(frozen=True, slots=True)
class DirectionProfileDetail:
    effective_profile: DirectionProfile
    machine_profile: DirectionProfile
    manual_profile: DirectionProfile | None
    profile_version: str
    latest_active_correction_id: str | None
    has_manual_override: bool


@dataclass(frozen=True, slots=True)
class DirectionOverrideResult:
    correction_id: str
    profile_version: str
    profile: DirectionProfile


class DirectionService:
    """方向保存与恢复的唯一业务入口。

    人工覆盖写入 CorrectionLog，可撤销；只更新索引元数据（METADATA），不调用 embedding。
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def get_profile(self, entity_type: str, entity_id: str) -> tuple[DirectionProfile, str]:
        with self.session_factory() as session:
            revision = self._revision(session, entity_type, entity_id)
            profile = self._effective_profile(revision)
            version = self._profile_version(session, entity_type, entity_id, profile)
            return profile, version

    def get_profile_detail(self, entity_type: str, entity_id: str) -> DirectionProfileDetail:
        with self.session_factory() as session:
            revision = self._revision(session, entity_type, entity_id)
            effective = self._effective_profile(revision)
            machine = self._machine_profile(revision)
            manual = self._manual_profile(revision)
            version = self._profile_version(session, entity_type, entity_id, effective)
            latest_id = self._latest_active_correction_id(session, entity_type, entity_id)
            return DirectionProfileDetail(
                effective_profile=effective,
                machine_profile=machine,
                manual_profile=manual,
                profile_version=version,
                latest_active_correction_id=latest_id,
                has_manual_override=manual is not None,
            )

    def apply_override(
        self,
        *,
        entity_type: str,
        entity_id: str,
        profile: DirectionProfile,
        reason: str | None = None,
        expected_profile_version: str | None = None,
    ) -> DirectionOverrideResult:
        profile = self._as_user_profile(profile)
        if profile.taxonomy_version != TAXONOMY_VERSION:
            raise DirectionTaxonomyVersionError("方向 taxonomy 版本已过时，请刷新后重试")
        profile = profile.model_copy(update={"classifier_version": CLASSIFIER_VERSION})
        with self.session_factory() as session, session.begin():
            revision = self._revision(session, entity_type, entity_id)
            self._assert_current(revision)
            current = self._effective_profile(revision)
            version = self._profile_version(session, entity_type, entity_id, current)
            if expected_profile_version is not None and expected_profile_version != version:
                raise DirectionConflict("方向已被他人修改，请刷新后重试")
            old_value = json.dumps(current.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            new_value = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            log = CorrectionLog(
                entity_type=entity_type,
                entity_id=entity_id,
                field_name="direction_profile",
                old_value=old_value,
                new_value=new_value,
                reason=reason,
            )
            session.add(log)
            session.flush()
            self._write_profile(revision, profile.model_dump(mode="json"))
            kind, entity_key = self._index_target(revision)
            enqueue_sync(session, kind, entity_key, mode="METADATA")
            new_version = self._profile_version(session, entity_type, entity_id, profile)
            return DirectionOverrideResult(correction_id=log.id, profile_version=new_version, profile=profile)

    def undo_override(self, correction_id: str) -> CorrectionLog:
        with self.session_factory() as session, session.begin():
            log = session.get(CorrectionLog, correction_id)
            if log is None:
                raise LookupError(f"CorrectionLog not found: {correction_id}")
            if log.reverted:
                raise ValueError(f"Correction already reverted: {correction_id}")
            latest = session.scalar(select(CorrectionLog.id).where(
                CorrectionLog.entity_type == log.entity_type,
                CorrectionLog.entity_id == log.entity_id,
                CorrectionLog.field_name == "direction_profile",
                CorrectionLog.reverted.is_(False),
            ).order_by(CorrectionLog.created_at.desc(), CorrectionLog.id.desc()).limit(1))
            if latest != correction_id:
                raise DirectionConflict("只能撤销最新的一次方向修改")
            revision = self._revision(session, log.entity_type, log.entity_id)
            previous = json.loads(log.old_value) if log.old_value else None
            previous_profile = parse_direction_profile(previous) if previous else None
            if previous_profile is not None and previous_profile.is_manual:
                # 存在上一人工值：恢复上一人工值。
                self._write_profile(revision, previous)
            else:
                # 没有上一人工值：删除 manual override，恢复 review_data 机器结果（或 UNKNOWN）。
                self._remove_manual_override(revision)
            log.reverted = True
            log.reverted_at = datetime.now(timezone.utc)
            kind, entity_key = self._index_target(revision)
            enqueue_sync(session, kind, entity_key, mode="METADATA")
            return log

    def _write_profile(self, revision, profile_json: dict) -> None:
        manual = dict(revision.manual_overrides or {})
        manual["direction_profile"] = profile_json
        revision.manual_overrides = manual
        parsed = dict(revision.parsed_data or {})
        parsed["direction_profile"] = profile_json
        revision.parsed_data = parsed
        # review_data 机器结果保持不变。

    def _remove_manual_override(self, revision) -> None:
        manual = dict(revision.manual_overrides or {})
        manual.pop("direction_profile", None)
        revision.manual_overrides = manual or None
        parsed = dict(revision.parsed_data or {})
        machine = (revision.review_data or {}).get("direction_profile")
        if machine:
            parsed["direction_profile"] = machine
        else:
            parsed["direction_profile"] = DirectionProfile.unknown().model_dump(mode="json")
        revision.parsed_data = parsed

    @staticmethod
    def _effective_profile(revision) -> DirectionProfile:
        data = (revision.parsed_data or {}).get("direction_profile")
        return parse_direction_profile(data)

    @staticmethod
    def _machine_profile(revision) -> DirectionProfile:
        data = (revision.review_data or {}).get("direction_profile")
        return parse_direction_profile(data)

    @staticmethod
    def _manual_profile(revision) -> DirectionProfile | None:
        data = (revision.manual_overrides or {}).get("direction_profile")
        return parse_direction_profile(data) if data else None

    @staticmethod
    def _latest_active_correction_id(session: Session, entity_type: str, entity_id: str) -> str | None:
        return session.scalar(select(CorrectionLog.id).where(
            CorrectionLog.entity_type == entity_type,
            CorrectionLog.entity_id == entity_id,
            CorrectionLog.field_name == "direction_profile",
            CorrectionLog.reverted.is_(False),
        ).order_by(CorrectionLog.created_at.desc(), CorrectionLog.id.desc()).limit(1))

    @staticmethod
    def _as_user_profile(profile: DirectionProfile) -> DirectionProfile:
        role = [item.model_copy(update={"source": "USER", "confidence": 1.0}) for item in profile.role_families]
        leadership = profile.leadership.model_copy(update={"source": "USER", "confidence": 1.0}) if profile.leadership else None
        domains = [item.model_copy(update={"source": "USER", "confidence": 1.0}) for item in profile.business_domains]
        return profile.model_copy(update={"role_families": role, "leadership": leadership, "business_domains": domains})

    @staticmethod
    def _revision(session: Session, entity_type: str, entity_id: str):
        if entity_type == "resume_revision":
            revision = session.get(ResumeRevision, entity_id)
        elif entity_type == "jd_revision":
            revision = session.get(JdRevision, entity_id)
        else:
            raise ValueError(f"Unknown entity type: {entity_type}")
        if revision is None:
            raise LookupError(f"{entity_type} not found: {entity_id}")
        return revision

    @staticmethod
    def _assert_current(revision) -> None:
        if not getattr(revision, "is_current", True):
            raise DirectionConflict("只能修改当前版本的岗位或简历方向")

    @staticmethod
    def _index_target(revision) -> tuple[str, str]:
        if isinstance(revision, ResumeRevision):
            return "candidate", revision.document.candidate_id
        return "jd", revision.jd_id

    @staticmethod
    def _profile_version(session: Session, entity_type: str, entity_id: str, profile: DirectionProfile) -> str:
        latest = session.scalar(select(CorrectionLog.id).where(
            CorrectionLog.entity_type == entity_type,
            CorrectionLog.entity_id == entity_id,
            CorrectionLog.field_name == "direction_profile",
        ).order_by(CorrectionLog.created_at.desc(), CorrectionLog.id.desc()).limit(1))
        payload = json.dumps({
            "profile": profile.model_dump(mode="json"),
            "correction_id": latest or "",
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
