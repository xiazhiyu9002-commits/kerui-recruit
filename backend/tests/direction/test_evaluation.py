from __future__ import annotations

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import IndexSyncRecord, JdRevision, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.classifier import DirectionClassifier
from kerui_recruit.direction.evaluation import DirectionEvaluationService, DirectionInputChanged
from kerui_recruit.direction.models import DirectionDecision, DirectionProfile, build_direction_label
from kerui_recruit.direction.service import DirectionConflict, DirectionService
from kerui_recruit.jd.ingest import IngestJd, JdIngestService
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.storage.blobs import BlobStore


def make_pdf_bytes() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Resume")
    content = pdf.tobytes()
    pdf.close()
    return content


def _machine_profile(code: str = "BACKEND") -> dict:
    return DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(code, source="LLM", confidence=0.9, is_primary=True),
    ]).model_dump(mode="json")


def _user_profile(code: str = "AI_ML") -> DirectionProfile:
    return DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(code, source="USER", confidence=1.0, is_primary=True),
    ])


def _decision(code: str, **overrides) -> DirectionDecision:
    outcome = overrides.pop("outcome", None)
    if outcome is None:
        outcome = "SUCCESS_DIRECTION" if overrides.get("llm_error_code") is None else "NETWORK_UPSTREAM_FAILURE"
    profile = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(code, source="LLM", confidence=0.9, is_primary=True),
    ])
    return DirectionDecision(effective_profile=profile, outcome=outcome, **overrides)


class _FakeClassifier:
    def __init__(self, decision: DirectionDecision, mutate=None) -> None:
        self.decision = decision
        self.mutate = mutate
        self.calls = 0

    async def classify(self, payload):
        self.calls += 1
        if self.mutate is not None:
            self.mutate()
        return self.decision


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
        revision.parsed_data = {"direction_profile": _machine_profile("BACKEND")}
        revision.review_data = {"direction_profile": _machine_profile("BACKEND")}
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
        revision.parsed_data = {"direction_profile": _machine_profile("BACKEND")}
        revision.review_data = {"direction_profile": _machine_profile("BACKEND")}
        session.commit()
    return engine, factory, ingested.revision_id, ingested.jd_id


def _service(factory, classifier) -> DirectionEvaluationService:
    return DirectionEvaluationService(
        session_factory=factory,
        classifier=classifier,
        direction_service=DirectionService(factory),
    )


def _set_manual_override(factory, model, revision_id: str, code: str) -> None:
    with factory() as session, session.begin():
        revision = session.get(model, revision_id)
        profile = _user_profile(code).model_dump(mode="json")
        manual = dict(revision.manual_overrides or {})
        manual["direction_profile"] = profile
        revision.manual_overrides = manual
        parsed = dict(revision.parsed_data or {})
        parsed["direction_profile"] = profile
        revision.parsed_data = parsed


@pytest.mark.asyncio
async def test_reevaluate_without_manual_updates_machine_and_effective(tmp_path) -> None:
    engine, factory, revision_id, candidate_id = _resume_revision(tmp_path)
    classifier = _FakeClassifier(_decision("AI_ML"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.machine_profile.role_families[0].code == "AI_ML"
    assert result.manual_profile is None
    assert result.effective_profile.role_families[0].code == "AI_ML"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert (revision.manual_overrides or {}).get("direction_profile") is None
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "candidate", IndexSyncRecord.entity_id == candidate_id))
        assert sync is not None and sync.requested_mode == "METADATA"


@pytest.mark.asyncio
async def test_reevaluate_with_manual_only_updates_machine(tmp_path) -> None:
    engine, factory, revision_id, candidate_id = _resume_revision(tmp_path)
    DirectionService(factory).apply_override(
        entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
    )
    classifier = _FakeClassifier(_decision("BACKEND"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.machine_profile.role_families[0].code == "BACKEND"
    assert result.manual_profile is not None
    assert result.manual_profile.role_families[0].code == "AI_ML"
    assert result.effective_profile.role_families[0].code == "AI_ML"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert revision.manual_overrides["direction_profile"]["role_families"][0]["code"] == "AI_ML"


@pytest.mark.asyncio
async def test_reevaluate_jd(tmp_path) -> None:
    engine, factory, revision_id, jd_id = _jd_revision(tmp_path)
    classifier = _FakeClassifier(_decision("RISK_STRATEGY"))
    result = await _service(factory, classifier).re_evaluate("jd_revision", revision_id)

    assert result.effective_profile.role_families[0].code == "RISK_STRATEGY"
    with Session(engine) as session:
        revision = session.get(JdRevision, revision_id)
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "RISK_STRATEGY"
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "jd", IndexSyncRecord.entity_id == jd_id))
        assert sync is not None and sync.requested_mode == "METADATA"


@pytest.mark.asyncio
async def test_reevaluate_jd_with_manual_only_updates_machine(tmp_path) -> None:
    engine, factory, revision_id, jd_id = _jd_revision(tmp_path)
    _set_manual_override(factory, JdRevision, revision_id, "RISK_STRATEGY")
    classifier = _FakeClassifier(_decision("BACKEND"))
    result = await _service(factory, classifier).re_evaluate("jd_revision", revision_id)

    assert result.machine_profile.role_families[0].code == "BACKEND"
    assert result.effective_profile.role_families[0].code == "RISK_STRATEGY"
    with Session(engine) as session:
        revision = session.get(JdRevision, revision_id)
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "RISK_STRATEGY"


@pytest.mark.asyncio
async def test_reevaluate_with_manual_does_not_enqueue_sync(tmp_path) -> None:
    engine, factory, revision_id, candidate_id = _resume_revision(tmp_path)
    _set_manual_override(factory, ResumeRevision, revision_id, "AI_ML")
    classifier = _FakeClassifier(_decision("BACKEND"))
    await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    with Session(engine) as session:
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "candidate", IndexSyncRecord.entity_id == candidate_id))
        assert sync is None
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"


@pytest.mark.asyncio
async def test_reevaluate_conflict_on_wrong_expected_version(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    classifier = _FakeClassifier(_decision("AI_ML"))
    with pytest.raises(DirectionConflict):
        await _service(factory, classifier).re_evaluate(
            "resume_revision", revision_id, expected_profile_version="wrong-version",
        )


@pytest.mark.asyncio
async def test_reevaluate_raises_on_input_fingerprint_change(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)

    def mutate() -> None:
        with factory() as session, session.begin():
            revision = session.get(ResumeRevision, revision_id)
            parsed = dict(revision.parsed_data or {})
            parsed["experiences"] = [{"title": "数据科学家"}]
            revision.parsed_data = parsed

    classifier = _FakeClassifier(_decision("AI_ML"), mutate=mutate)
    with pytest.raises(DirectionInputChanged):
        await _service(factory, classifier).re_evaluate("resume_revision", revision_id)


@pytest.mark.asyncio
async def test_reevaluate_llm_failure_preserves_manual_effective(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    DirectionService(factory).apply_override(
        entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"),
    )
    decision = _decision("BACKEND", used_rule_fallback=True, llm_error_code="E_API_TIMEOUT")
    classifier = _FakeClassifier(decision)
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.machine_profile.role_families[0].code == "BACKEND"
    assert result.effective_profile.role_families[0].code == "AI_ML"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.review_data["direction_diagnostics"]["llm_error_code"] == "E_API_TIMEOUT"
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"


def _unknown_decision(**overrides) -> DirectionDecision:
    outcome = overrides.pop("outcome", None)
    if outcome is None:
        outcome = "SUCCESS_UNKNOWN" if overrides.get("llm_error_code") is None else "NETWORK_UPSTREAM_FAILURE"
    return DirectionDecision(effective_profile=DirectionProfile.unknown(), outcome=outcome, **overrides)


def _set_effective(factory, model, revision_id: str, profile: DirectionProfile) -> None:
    with factory() as session, session.begin():
        revision = session.get(model, revision_id)
        revision.parsed_data = dict(revision.parsed_data or {})
        revision.parsed_data["direction_profile"] = profile.model_dump(mode="json")
        revision.review_data = dict(revision.review_data or {})
        revision.review_data["direction_profile"] = profile.model_dump(mode="json")


@pytest.mark.asyncio
async def test_llm_failure_unknown_keeps_confident(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)  # 旧 effective = BACKEND CONFIDENT
    classifier = _FakeClassifier(_unknown_decision(used_rule_fallback=False, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.status == "CONFIDENT"
    assert result.effective_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.review_data["direction_diagnostics"]["llm_error_code"] == "E_API_TIMEOUT"
        # 失败场景不产生索引任务。
        assert session.scalar(select(IndexSyncRecord.id)) is None


@pytest.mark.asyncio
async def test_llm_failure_unknown_keeps_uncertain(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    _set_effective(factory, ResumeRevision, revision_id, DirectionProfile(status="UNCERTAIN", role_families=[
        build_direction_label("BACKEND", source="LLM", confidence=0.6, is_primary=True),
    ]))
    classifier = _FakeClassifier(_unknown_decision(used_rule_fallback=False, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.status == "UNCERTAIN"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["status"] == "UNCERTAIN"


@pytest.mark.asyncio
async def test_unknown_effective_updates_with_reliable_rule_fallback(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    _set_effective(factory, ResumeRevision, revision_id, DirectionProfile.unknown())
    # 规则可靠兜底得到 CONFIDENT BACKEND。
    classifier = _FakeClassifier(_decision("BACKEND", used_rule_fallback=True, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.status == "CONFIDENT"
    assert result.effective_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"


@pytest.mark.asyncio
async def test_llm_failure_unknown_keeps_jd_effective(tmp_path) -> None:
    engine, factory, revision_id, jd_id = _jd_revision(tmp_path)
    classifier = _FakeClassifier(_unknown_decision(used_rule_fallback=False, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("jd_revision", revision_id)

    assert result.effective_profile.status == "CONFIDENT"
    assert result.effective_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(JdRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert session.scalar(select(IndexSyncRecord.id)) is None


@pytest.mark.asyncio
async def test_reevaluate_version_change_during_llm_conflicts(tmp_path) -> None:
    _, factory, revision_id, _ = _resume_revision(tmp_path)
    profile, version = DirectionService(factory).get_profile("resume_revision", revision_id)

    def mutate() -> None:
        DirectionService(factory).apply_override(
            entity_type="resume_revision", entity_id=revision_id, profile=_user_profile("AI_ML"))

    classifier = _FakeClassifier(_decision("BACKEND"), mutate=mutate)
    with pytest.raises(DirectionConflict):
        await _service(factory, classifier).re_evaluate(
            "resume_revision", revision_id, expected_profile_version=version)


@pytest.mark.asyncio
async def test_success_unknown_and_failure_diagnostics_differ(tmp_path) -> None:
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    engine, factory, revision_id, _ = _resume_revision(first_dir)
    # 成功但明确 UNKNOWN：llm_error_code 为 None。
    await _service(factory, _FakeClassifier(_unknown_decision(llm_successes=1, llm_failures=0))).re_evaluate(
        "resume_revision", revision_id)
    with Session(engine) as session:
        first = session.get(ResumeRevision, revision_id).review_data["direction_diagnostics"]
    # 失败：llm_error_code 有值。
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    engine2, factory2, revision_id2, _ = _resume_revision(second_dir)
    await _service(factory2, _FakeClassifier(
        _unknown_decision(used_rule_fallback=False, llm_error_code="E_API_TIMEOUT", llm_successes=0, llm_failures=1),
    )).re_evaluate("resume_revision", revision_id2)
    with Session(engine2) as session:
        second = session.get(ResumeRevision, revision_id2).review_data["direction_diagnostics"]

    assert first["llm_error_code"] is None
    assert second["llm_error_code"] == "E_API_TIMEOUT"


@pytest.mark.asyncio
async def test_llm_failure_rule_fallback_keeps_confident(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)  # 旧 = BACKEND CONFIDENT
    # LLM 失败但规则兜底得到不同方向 AI_ML，仍不得覆盖旧有效方向。
    classifier = _FakeClassifier(_decision("AI_ML", used_rule_fallback=True, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.role_families[0].code == "BACKEND"
    assert result.machine_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert session.scalar(select(IndexSyncRecord.id)) is None


@pytest.mark.asyncio
async def test_llm_failure_rule_fallback_keeps_uncertain(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    _set_effective(factory, ResumeRevision, revision_id, DirectionProfile(status="UNCERTAIN", role_families=[
        build_direction_label("BACKEND", source="LLM", confidence=0.6, is_primary=True),
    ]))
    classifier = _FakeClassifier(_decision("AI_ML", used_rule_fallback=True, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.status == "UNCERTAIN"
    assert result.effective_profile.role_families[0].code == "BACKEND"


@pytest.mark.asyncio
async def test_success_unknown_keeps_confident(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    classifier = _FakeClassifier(_unknown_decision(llm_successes=1, llm_failures=0, outcome="SUCCESS_UNKNOWN"))
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        diag = revision.review_data["direction_diagnostics"]
        assert diag["outcome"] == "SUCCESS_UNKNOWN"
        assert diag["llm_successes"] == 1
        assert diag["llm_failures"] == 0
        assert session.scalar(select(IndexSyncRecord.id)) is None


@pytest.mark.asyncio
async def test_provider_disabled_zero_write(tmp_path) -> None:
    engine, factory, revision_id, _ = _resume_revision(tmp_path)
    classifier = DirectionClassifier(None)  # 无 Provider
    result = await _service(factory, classifier).re_evaluate("resume_revision", revision_id)

    assert result.effective_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert session.scalar(select(IndexSyncRecord.id)) is None


@pytest.mark.asyncio
async def test_llm_failure_rule_fallback_keeps_jd(tmp_path) -> None:
    engine, factory, revision_id, jd_id = _jd_revision(tmp_path)  # 旧 = BACKEND CONFIDENT
    classifier = _FakeClassifier(_decision("AI_ML", used_rule_fallback=True, llm_error_code="E_API_TIMEOUT"))
    result = await _service(factory, classifier).re_evaluate("jd_revision", revision_id)

    assert result.effective_profile.role_families[0].code == "BACKEND"
    with Session(engine) as session:
        revision = session.get(JdRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert session.scalar(select(IndexSyncRecord.id)) is None
