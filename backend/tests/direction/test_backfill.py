from __future__ import annotations

import asyncio
import json
import os

import pymupdf
import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import JdRevision, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.backfill import DirectionBackfillService
from kerui_recruit.direction.classifier import DirectionClassifier
from kerui_recruit.direction.models import DirectionDecision, DirectionProfile, build_direction_label
from kerui_recruit.jd.ingest import IngestJd, JdIngestService
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.storage.blobs import BlobStore


class FakeClassifier:
    def __init__(self, decision: DirectionDecision | None = None):
        self.decision = decision
        self.calls = 0
        self.llm_provider = object()  # 模拟 LLM Provider 已启用

    async def classify(self, payload) -> DirectionDecision:
        self.calls += 1
        if self.decision is None:
            profile = DirectionProfile(status="CONFIDENT", role_families=[
                build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
            ])
            self.decision = DirectionDecision(effective_profile=profile)
        return self.decision


def _make_pdf() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Resume")
    content = pdf.tobytes()
    pdf.close()
    return content


def _setup(tmp_path):
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(IngestResume(filename="a.pdf", content=_make_pdf()))
        revision = session.get(ResumeRevision, ingested.revision_id)
        revision.status = "READY"
        revision.parsed_data = {"summary": "后端工程师", "skills": ["Java"]}
        session.commit()
    return engine, factory, ingested.revision_id


@pytest.mark.asyncio
async def test_dry_run_does_not_modify(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    service = DirectionBackfillService(factory, FakeClassifier())
    stats = await service.run(entity_types=("resume_revision",), mode="dry-run")
    assert stats.scanned >= 1
    assert stats.needs_backfill >= 1
    with factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        assert "direction_profile" not in (revision.parsed_data or {})


@pytest.mark.asyncio
async def test_full_backfill_classifies(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    classifier = FakeClassifier()
    service = DirectionBackfillService(factory, classifier)
    stats = await service.run(entity_types=("resume_revision",), mode="full")
    assert stats.success >= 1
    assert classifier.calls >= 1
    with factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"


@pytest.mark.asyncio
async def test_manual_override_skipped(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    manual = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("AI_ML", source="USER", confidence=1.0, is_primary=True),
    ]).model_dump(mode="json")
    with factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        revision.manual_overrides = {"direction_profile": manual}
        session.commit()
    classifier = FakeClassifier()
    service = DirectionBackfillService(factory, classifier)
    stats = await service.run(entity_types=("resume_revision",), mode="full")
    assert stats.manual_skipped >= 1
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_backfill_covers_jd_revision(tmp_path) -> None:
    engine = create_engine_for(tmp_path / "jd.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        ingested = JdIngestService(session).ingest(IngestJd(company="某金融", title="Java", source_text="Java 后端"))
        revision = session.get(JdRevision, ingested.revision_id)
        revision.status = "READY"
        revision.parsed_data = {"title": "Java 后端", "required_skills": ["Java"]}
        session.commit()
    service = DirectionBackfillService(factory, FakeClassifier())
    stats = await service.run(entity_types=("jd_revision",), mode="full")
    assert stats.success >= 1
    with Session(engine) as session:
        revision = session.get(JdRevision, ingested.revision_id)
        assert "direction_profile" in revision.parsed_data


def test_preflight_reports_schema_and_counts(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    service = DirectionBackfillService(factory, FakeClassifier())
    report = service.preflight()
    assert report["schema_supported"] is True
    assert report["candidate_count"] >= 1
    assert report["llm_enabled"] is True
    assert report["manual_override_count"] == 0


class RetryableFallbackClassifier:
    """先返回可重试的兜底，随后返回正常结果，用于验证 429 退避重试。"""

    def __init__(self, error_code: str, retries_before_success: int) -> None:
        self.error_code = error_code
        self.retries_before_success = retries_before_success
        self.calls = 0

    async def classify(self, payload) -> DirectionDecision:
        self.calls += 1
        if self.calls <= self.retries_before_success:
            return DirectionDecision(
                effective_profile=DirectionProfile(status="UNKNOWN", role_families=[]),
                used_rule_fallback=True,
                llm_error_code=self.error_code,
            )
        return DirectionDecision(effective_profile=DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
        ]))


@pytest.mark.asyncio
async def test_retryable_error_is_retried(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    service = DirectionBackfillService(
        sessionmaker(create_engine_for(tmp_path / "r.sqlite3"), expire_on_commit=False),
        RetryableFallbackClassifier("E_API_RATE_LIMIT", retries_before_success=2),
    )
    decision = await service._classify({"summary": "后端"}, "resume_revision")
    assert decision.used_rule_fallback is False


@pytest.mark.asyncio
async def test_non_retryable_error_not_retried(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    service = DirectionBackfillService(
        sessionmaker(create_engine_for(tmp_path / "n.sqlite3"), expire_on_commit=False),
        RetryableFallbackClassifier("E_API_SCHEMA", retries_before_success=99),
    )
    decision = await service._classify({"summary": "后端"}, "resume_revision")
    assert decision.used_rule_fallback is True
    assert decision.llm_error_code == "E_API_SCHEMA"


async def _no_sleep(_: float) -> None:
    return None


def test_is_retryable_whitelist() -> None:
    assert DirectionBackfillService._is_retryable("E_API_RATE_LIMIT") is True
    assert DirectionBackfillService._is_retryable("E_API_NETWORK") is True
    assert DirectionBackfillService._is_retryable("E_API_SCHEMA") is False
    assert DirectionBackfillService._is_retryable(None) is False


def test_distribution_warnings_flags_imbalance() -> None:
    from kerui_recruit.direction.backfill import BackfillStats
    stats = BackfillStats(distribution={"BACKEND": 80, "AI_ML": 20})
    warnings = DirectionBackfillService.distribution_warnings(stats)
    assert any("BACKEND" in w and "70%" in w for w in warnings)
    stats = BackfillStats(distribution={"UNKNOWN": 60, "BACKEND": 40})
    warnings = DirectionBackfillService.distribution_warnings(stats)
    assert any("UNKNOWN" in w and "50%" in w for w in warnings)


def _set_profile(factory, revision_id, profile: DirectionProfile) -> None:
    with factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        revision.parsed_data = dict(revision.parsed_data or {})
        revision.parsed_data["direction_profile"] = profile.model_dump(mode="json")
        session.commit()


@pytest.mark.asyncio
async def test_current_version_confident_skipped(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    _set_profile(factory, revision_id, DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True)]))
    classifier = FakeClassifier()
    stats = await DirectionBackfillService(factory, classifier).run(
        entity_types=("resume_revision",), mode="dry-run")
    assert stats.already_current_skipped >= 1
    assert stats.needs_backfill == 0
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_current_version_uncertain_skipped(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    _set_profile(factory, revision_id, DirectionProfile(status="UNCERTAIN", role_families=[
        build_direction_label("BACKEND", source="LLM", confidence=0.6, is_primary=True)]))
    classifier = FakeClassifier()
    stats = await DirectionBackfillService(factory, classifier).run(
        entity_types=("resume_revision",), mode="dry-run")
    assert stats.already_current_skipped >= 1
    assert stats.needs_backfill == 0
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_current_version_unknown_skipped(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    _set_profile(factory, revision_id, DirectionProfile(status="UNKNOWN"))
    classifier = FakeClassifier()
    stats = await DirectionBackfillService(factory, classifier).run(
        entity_types=("resume_revision",), mode="dry-run")
    assert stats.already_current_skipped >= 1
    assert stats.current_unknown >= 1
    assert stats.needs_backfill == 0
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_stale_taxonomy_needs_backfill(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    _set_profile(factory, revision_id, DirectionProfile(
        status="CONFIDENT", taxonomy_version="old-taxonomy", role_families=[
            build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True)]))
    stats = await DirectionBackfillService(factory, FakeClassifier()).run(
        entity_types=("resume_revision",), mode="dry-run")
    assert stats.needs_backfill >= 1


@pytest.mark.asyncio
async def test_rules_only_does_not_call_llm(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    classifier = FakeClassifier()
    stats = await DirectionBackfillService(factory, classifier).run(
        entity_types=("resume_revision",), mode="rules-only")
    assert stats.scanned >= 1
    assert classifier.calls == 0
    with factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        assert "direction_profile" not in (revision.parsed_data or {})


@pytest.mark.asyncio
async def test_max_items_precise(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    # 再补两条，共 3 条 READY 记录。
    with factory() as session:
        from kerui_recruit.db.models import ResumeDocument, Blob
        base = session.get(ResumeRevision, revision_id)
        for i in range(2):
            doc = ResumeDocument(candidate_id=base.document.candidate_id)
            rev = ResumeRevision(document=doc, blob_id=base.blob_id, content_sha256=f"b{i}" * 32,
                                original_filename=f"r{i}.pdf", status="READY", is_current=False,
                                parsed_data={"summary": "x"})
            session.add(rev)
        session.commit()
    stats = await DirectionBackfillService(factory, FakeClassifier()).run(
        entity_types=("resume_revision",), mode="dry-run", max_items=1, batch_size=20)
    assert stats.scanned == 1


def test_single_task_lock(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    state_dir = tmp_path / "state"
    a = DirectionBackfillService(factory, FakeClassifier(), state_dir=state_dir)
    b = DirectionBackfillService(factory, FakeClassifier(), state_dir=state_dir)
    a._acquire_lock("run-a")
    with pytest.raises(RuntimeError):
        b._acquire_lock("run-b")
    a._release_lock("run-a")
    b._acquire_lock("run-b")
    b._release_lock("run-b")


def test_stale_lock_is_cleared(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    state_dir = tmp_path / "state"
    service = DirectionBackfillService(factory, FakeClassifier(), state_dir=state_dir)
    # 伪造一个已不存在 PID 的陈旧锁。
    service._acquire_lock("stale")
    service._release_lock("stale")
    with open(service.lock_path, "w", encoding="utf-8") as fh:
        import json
        json.dump({"run_id": "stale", "pid": 999999, "started_at": "x"}, fh)
    # 陈旧锁不阻止新任务。
    service._acquire_lock("fresh")
    service._release_lock("fresh")


class MutatingClassifier:
    """在 classify() 期间对数据库做一次变更，模拟 LLM 等待期的并发写。"""

    def __init__(self, factory, mutate) -> None:
        self.factory = factory
        self.mutate = mutate
        self.calls = 0
        self.llm_provider = object()

    async def classify(self, payload) -> DirectionDecision:
        self.calls += 1
        with self.factory() as session:
            self.mutate(session)
            session.commit()
        profile = DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
        ])
        return DirectionDecision(effective_profile=profile)


def _no_index_sync(factory) -> int:
    from kerui_recruit.db.models import IndexSyncRecord
    with factory() as session:
        return session.query(IndexSyncRecord).count()


@pytest.mark.asyncio
async def test_llm_window_manual_override_not_overwritten(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    manual = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("AI_ML", source="USER", confidence=1.0, is_primary=True),
    ]).model_dump(mode="json")

    def mutate(session):
        rev = session.get(ResumeRevision, revision_id)
        rev.manual_overrides = {"direction_profile": manual}

    stats = await DirectionBackfillService(factory, MutatingClassifier(factory, mutate)).run(
        entity_types=("resume_revision",), mode="full")
    assert stats.conflict_skipped >= 1
    with factory() as session:
        rev = session.get(ResumeRevision, revision_id)
        assert rev.manual_overrides["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert "direction_profile" not in (rev.parsed_data or {})
    assert _no_index_sync(factory) == 0


@pytest.mark.asyncio
async def test_llm_window_input_change_not_written(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)

    def mutate(session):
        rev = session.get(ResumeRevision, revision_id)
        parsed = dict(rev.parsed_data or {})
        parsed["skills"] = ["Python"]
        rev.parsed_data = parsed

    stats = await DirectionBackfillService(factory, MutatingClassifier(factory, mutate)).run(
        entity_types=("resume_revision",), mode="full")
    assert stats.conflict_skipped >= 1
    with factory() as session:
        rev = session.get(ResumeRevision, revision_id)
        assert rev.parsed_data["skills"] == ["Python"]
        assert "direction_profile" not in rev.parsed_data
    assert _no_index_sync(factory) == 0


@pytest.mark.asyncio
async def test_llm_window_not_current_not_written(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)

    def mutate(session):
        rev = session.get(ResumeRevision, revision_id)
        rev.is_current = False

    stats = await DirectionBackfillService(factory, MutatingClassifier(factory, mutate)).run(
        entity_types=("resume_revision",), mode="full")
    assert stats.conflict_skipped >= 1
    with factory() as session:
        rev = session.get(ResumeRevision, revision_id)
        assert rev.is_current is False
        assert "direction_profile" not in (rev.parsed_data or {})
    assert _no_index_sync(factory) == 0


@pytest.mark.asyncio
async def test_llm_window_already_backfilled_not_rewritten(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    already = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("AI_ML", source="LLM", confidence=0.9, is_primary=True),
    ]).model_dump(mode="json")

    def mutate(session):
        rev = session.get(ResumeRevision, revision_id)
        parsed = dict(rev.parsed_data or {})
        parsed["direction_profile"] = already
        rev.parsed_data = parsed

    stats = await DirectionBackfillService(factory, MutatingClassifier(factory, mutate)).run(
        entity_types=("resume_revision",), mode="full")
    assert stats.conflict_skipped >= 1
    with factory() as session:
        rev = session.get(ResumeRevision, revision_id)
        assert rev.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
    assert _no_index_sync(factory) == 0


@pytest.mark.asyncio
async def test_no_conflict_writes_and_enqueues_metadata(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    stats = await DirectionBackfillService(factory, FakeClassifier()).run(
        entity_types=("resume_revision",), mode="full")
    assert stats.success >= 1
    assert stats.conflict_skipped == 0
    from kerui_recruit.db.models import IndexSyncRecord
    with factory() as session:
        record = session.query(IndexSyncRecord).one()
        assert record.entity_type == "candidate"
        assert record.requested_mode == "METADATA"


def test_cursor_persist_merges_entity_types(tmp_path) -> None:
    from kerui_recruit.direction.backfill import BackfillStats
    engine, factory, revision_id = _setup(tmp_path)
    state_dir = tmp_path / "state"
    service = DirectionBackfillService(factory, FakeClassifier(), state_dir=state_dir)
    stats = BackfillStats()
    service._persist_cursor("resume_revision", "r-1", stats, "run-1", "full")
    service._persist_cursor("jd_revision", "j-1", stats, "run-1", "full")
    state = service._read_state()
    assert state["entity_cursors"] == {"resume_revision": "r-1", "jd_revision": "j-1"}


class RaisingClassifier:
    def __init__(self) -> None:
        self.llm_provider = object()

    async def classify(self, payload):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_errors_structured_in_to_dict(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    stats = await DirectionBackfillService(factory, RaisingClassifier()).run(
        entity_types=("resume_revision",), mode="full")
    d = stats.to_dict()
    assert stats.failed >= 1
    assert isinstance(d["errors"], list) and isinstance(d["errors"][0], dict)
    assert d["errors"][0]["error_type"] == "RuntimeError"
    assert d["errors"][0]["entity_type"] == "resume_revision"
    assert d["errors"][0]["revision_id"] == revision_id
    assert d["errors"][0]["retryable"] is False


@pytest.mark.asyncio
async def test_skip_reasons_structured_in_to_dict(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    manual = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("AI_ML", source="USER", confidence=1.0, is_primary=True),
    ]).model_dump(mode="json")

    def mutate(session):
        rev = session.get(ResumeRevision, revision_id)
        rev.manual_overrides = {"direction_profile": manual}

    stats = await DirectionBackfillService(factory, MutatingClassifier(factory, mutate)).run(
        entity_types=("resume_revision",), mode="full")
    d = stats.to_dict()
    assert stats.conflict_skipped >= 1
    assert isinstance(d["skip_reasons"], list) and isinstance(d["skip_reasons"][0], dict)
    assert d["skip_reasons"][0]["reason"] == "manual_override"
    assert d["skip_reasons"][0]["revision_id"] == revision_id


@pytest.mark.asyncio
async def test_full_without_llm_provider_zero_write(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    service = DirectionBackfillService(factory, DirectionClassifier(None))
    with pytest.raises(RuntimeError, match="LLM Provider"):
        await service.run(entity_types=("resume_revision",), mode="full")
    with factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        assert "direction_profile" not in (revision.parsed_data or {})


@pytest.mark.asyncio
async def test_max_items_pauses_limit_not_done(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    state_dir = tmp_path / "state"
    service = DirectionBackfillService(factory, FakeClassifier(), state_dir=state_dir)
    await service.run(entity_types=("resume_revision",), mode="full", max_items=1)
    state = service._read_state()
    assert state["status"] == "PAUSED_LIMIT"
    assert state["entity_cursors"]


def test_validate_resume_state_rejects_incompatible(tmp_path) -> None:
    from kerui_recruit.direction.backfill import _atomic_write_json
    engine, factory, revision_id = _setup(tmp_path)
    service = DirectionBackfillService(factory, FakeClassifier(), state_dir=tmp_path / "state")
    _atomic_write_json(service.state_path, {"format_version": 99, "status": "PAUSED_LIMIT",
                                            "entity_cursors": {}, "stats": {}})
    assert service._validate_resume_state(service._read_state()) is not None


def test_validate_resume_state_rejects_done(tmp_path) -> None:
    from kerui_recruit.direction.backfill import TAXONOMY_VERSION, CLASSIFIER_VERSION, _atomic_write_json
    engine, factory, revision_id = _setup(tmp_path)
    service = DirectionBackfillService(factory, FakeClassifier(), state_dir=tmp_path / "state")
    _atomic_write_json(service.state_path, {"format_version": 1, "status": "DONE",
                                            "taxonomy_version": TAXONOMY_VERSION,
                                            "classifier_version": CLASSIFIER_VERSION,
                                            "entity_cursors": {}, "stats": {}})
    assert service._validate_resume_state(service._read_state()) is not None


def test_stats_from_state_restores_cumulative(tmp_path) -> None:
    from kerui_recruit.direction.backfill import BackfillStats
    raw = BackfillStats(scanned=10, success=5, failed=2, llm_attempts=7, distribution={"BACKEND": 5})
    state = {"stats": raw.to_dict()}
    restored = DirectionBackfillService._stats_from_state(state)
    assert restored.scanned == 10
    assert restored.success == 5
    assert restored.failed == 2
    assert restored.llm_attempts == 7
    assert restored.distribution == {"BACKEND": 5}


def test_lock_states(tmp_path) -> None:
    engine, factory, revision_id = _setup(tmp_path)
    service = DirectionBackfillService(factory, FakeClassifier(), state_dir=tmp_path / "state")
    # ACTIVE
    service._acquire_lock("run-1")
    state, reason = service._lock_state(service._read_lock())
    assert state == "ACTIVE"
    service._release_lock("run-1")
    # STALE_DEAD_PID
    service.lock_path.write_text(json.dumps({"run_id": "x", "pid": 999999, "started_at": "now"}),
                                 encoding="utf-8")
    assert service._lock_state(service._read_lock())[0] == "STALE_DEAD_PID"
    # INVALID
    service.lock_path.write_text("{not json", encoding="utf-8")
    assert service._lock_state(service._read_lock())[0] == "INVALID"
    # EXPIRED_LIVE（PID 存活但已过期）
    service.lock_path.write_text(json.dumps(
        {"run_id": "x", "pid": os.getpid(), "started_at": "2000-01-01T00:00:00+00:00"}),
        encoding="utf-8")
    assert service._lock_state(service._read_lock())[0] == "EXPIRED_LIVE"
