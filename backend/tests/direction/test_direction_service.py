from __future__ import annotations

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import CorrectionLog, IndexSyncRecord, JdRevision, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.models import CLASSIFIER_VERSION, DirectionProfile, build_direction_label
from kerui_recruit.direction.service import DirectionConflict, DirectionService, DirectionTaxonomyVersionError
from kerui_recruit.jd.ingest import IngestJd, JdIngestService
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.storage.blobs import BlobStore


def make_pdf_bytes() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Resume")
    content = pdf.tobytes()
    pdf.close()
    return content


def _machine_profile() -> dict:
    return DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
    ]).model_dump(mode="json")


def _user_profile(primary: str = "AI_ML") -> DirectionProfile:
    return DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(primary, source="USER", confidence=1.0, is_primary=True),
    ])


def _resume_revision(tmp_path):
    engine = create_engine_for(tmp_path / "resume.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(
            IngestResume(filename="张三.pdf", content=make_pdf_bytes())
        )
        revision = session.get(ResumeRevision, ingested.revision_id)
        revision.parsed_data = {"direction_profile": _machine_profile()}
        revision.review_data = {"direction_profile": _machine_profile()}
        session.commit()
    return engine, factory, ingested.revision_id, ingested.candidate_id


def _jd_revision(tmp_path):
    engine = create_engine_for(tmp_path / "jd.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        ingested = JdIngestService(session).ingest(
            IngestJd(company="某金融", title="Java", source_text="Java 后端")
        )
        revision = session.get(JdRevision, ingested.revision_id)
        revision.parsed_data = {"direction_profile": _machine_profile()}
        revision.review_data = {"direction_profile": _machine_profile()}
        session.commit()
    return engine, factory, ingested.revision_id, ingested.jd_id


def test_apply_override_updates_profile_and_writes_correction(tmp_path) -> None:
    engine, factory, revision_id, candidate_id = _resume_revision(tmp_path)
    service = DirectionService(factory)
    result = service.apply_override(
        entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
    )
    correction_id = result.correction_id
    assert correction_id
    assert result.profile.role_families[0].source == "USER"
    assert result.profile.role_families[0].confidence == 1.0
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert revision.manual_overrides["direction_profile"]["role_families"][0]["source"] == "USER"
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        log = session.scalar(select(CorrectionLog).where(CorrectionLog.id == correction_id))
        assert log is not None and log.field_name == "direction_profile"
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "candidate", IndexSyncRecord.entity_id == candidate_id))
        assert sync is not None and sync.requested_mode == "METADATA"


def test_undo_restores_machine_result(tmp_path) -> None:
    engine, factory, revision_id, candidate_id = _resume_revision(tmp_path)
    service = DirectionService(factory)
    correction_id = service.apply_override(
        entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
    ).correction_id
    service.undo_override(correction_id)
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.parsed_data["direction_profile"]["role_families"][0]["source"] == "LLM"
        assert (revision.manual_overrides or {}).get("direction_profile") is None
        # 撤销也走 METADATA 同步（不调用 embedding）。
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "candidate", IndexSyncRecord.entity_id == candidate_id))
        assert sync is not None and sync.requested_mode == "METADATA"


def test_expected_profile_version_conflict(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    service = DirectionService(factory)
    profile, version = service.get_profile("resume_revision", revision_id)
    assert version
    with pytest.raises(DirectionConflict):
        service.apply_override(
            entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
            expected_profile_version="wrong-version",
        )


def test_only_latest_undo_allowed(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    service = DirectionService(factory)
    first = service.apply_override(entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML")).correction_id
    service.apply_override(entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("BACKEND"))
    with pytest.raises(DirectionConflict):
        service.undo_override(first)


def test_jd_direction_override(tmp_path) -> None:
    engine, factory, revision_id, jd_id = _jd_revision(tmp_path)
    service = DirectionService(factory)
    correction_id = service.apply_override(
        entity_type="jd_revision", entity_id=revision_id, profile=_user_profile("RISK_STRATEGY"),
    ).correction_id
    with Session(engine) as session:
        revision = session.get(JdRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "RISK_STRATEGY"
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "jd", IndexSyncRecord.entity_id == jd_id))
        assert sync is not None and sync.requested_mode == "METADATA"


def test_get_profile_detail_separates_machine_manual_effective(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    service = DirectionService(factory)

    before = service.get_profile_detail("resume_revision", revision_id)
    assert before.effective_profile.role_families[0].code == "BACKEND"
    assert before.machine_profile.role_families[0].code == "BACKEND"
    assert before.manual_profile is None
    assert before.has_manual_override is False
    assert before.latest_active_correction_id is None

    correction_id = service.apply_override(
        entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
    ).correction_id

    after = service.get_profile_detail("resume_revision", revision_id)
    assert after.effective_profile.role_families[0].code == "AI_ML"
    assert after.machine_profile.role_families[0].code == "BACKEND"
    assert after.manual_profile is not None
    assert after.manual_profile.role_families[0].code == "AI_ML"
    assert after.has_manual_override is True
    assert after.latest_active_correction_id == correction_id


def test_latest_active_correction_id_only_active(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    service = DirectionService(factory)
    correction_id = service.apply_override(
        entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
    ).correction_id
    assert service.get_profile_detail("resume_revision", revision_id).latest_active_correction_id == correction_id
    service.undo_override(correction_id)
    assert service.get_profile_detail("resume_revision", revision_id).latest_active_correction_id is None


def test_apply_override_rejects_old_taxonomy_version(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    service = DirectionService(factory)
    stale = _user_profile("AI_ML").model_copy(update={"taxonomy_version": "old"})
    with pytest.raises(DirectionTaxonomyVersionError):
        service.apply_override(entity_type="resume_revision", entity_id=revision_id, profile=stale)


def test_apply_override_normalizes_classifier_version(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    service = DirectionService(factory)
    stale = _user_profile("AI_ML").model_copy(update={"classifier_version": "stale"})
    service.apply_override(entity_type="resume_revision", entity_id=revision_id, profile=stale)
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["classifier_version"] == CLASSIFIER_VERSION
