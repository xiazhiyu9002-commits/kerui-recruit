import asyncio
import threading
from pathlib import Path

import httpx
import pymupdf
import pytest

from kerui_recruit.core.settings import Settings
from kerui_recruit.db.models import ResumeRevision, TaskRecord
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.runtime import (
    _lease_recovery_loop,
    _worker_loop,
    build_runtime,
    create_runtime_app,
)
from kerui_recruit.search.contracts import CandidateFilters
from sqlalchemy import select


def make_resume_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Zhang San Python Finance 6 years Master Shanghai")
    content = document.tobytes()
    document.close()
    return content


@pytest.mark.asyncio
async def test_runtime_processes_an_import_without_external_services(tmp_path: Path) -> None:
    """Removing the packaged worker or local providers must break the offline first-run flow."""
    settings = Settings(data_root=tmp_path / "data", session_token="launch-token")
    runtime = build_runtime(settings)
    with runtime.services.session_factory() as session:
        imported = ResumeIngestService(session, runtime.services.blob_store).ingest(
            IngestResume(filename="张三.pdf", content=make_resume_pdf())
        )

    assert await runtime.worker.run_once() is True

    with runtime.services.session_factory() as session:
        assert session.get(TaskRecord, imported.task_id).status == "SUCCESS"
        assert session.get(ResumeRevision, imported.revision_id).status == "READY"
    page = await runtime.services.search_service.search(
        "Python", CandidateFilters(), limit=20
    )
    assert page.items[0].candidate_id == imported.candidate_id


@pytest.mark.asyncio
async def test_runtime_app_reports_readiness_after_local_stores_open(tmp_path: Path) -> None:
    """The desktop shell must not show the UI before the embedded stores are ready."""
    settings = Settings(data_root=tmp_path / "data", session_token="launch-token")
    app = create_runtime_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_busy_local_worker_yields_to_api_requests() -> None:
    class BusyWorker:
        def __init__(self) -> None:
            self.calls = 0
            self.block = asyncio.Event()

        async def run_once(self) -> bool:
            self.calls += 1
            if self.calls > 10:
                await self.block.wait()
            return True

    worker = BusyWorker()
    task = asyncio.create_task(_worker_loop(worker))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    observed_calls = worker.calls
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert observed_calls == 1


@pytest.mark.asyncio
async def test_runtime_periodically_recovers_expired_task_leases() -> None:
    class Repository:
        def __init__(self) -> None:
            self.called = threading.Event()

        def recover_expired_leases(self) -> int:
            self.called.set()
            return 1

    repository = Repository()
    task = asyncio.create_task(
        _lease_recovery_loop(repository, interval_seconds=0.01)  # type: ignore[arg-type]
    )
    assert await asyncio.to_thread(repository.called.wait, 0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_passive_match_failure_is_retryable_without_reparsing(tmp_path, monkeypatch):
    runtime = build_runtime(Settings(data_root=tmp_path / 'data', session_token='test'))
    with runtime.services.session_factory() as session:
        imported = ResumeIngestService(session, runtime.services.blob_store).ingest(
            IngestResume(filename='sample.pdf', content=make_resume_pdf()))
    async def unavailable(*args, **kwargs):
        raise RuntimeError('controlled match outage')
    monkeypatch.setattr(runtime.services.match_service, 'reverse_match_candidate', unavailable)
    assert await runtime.worker.run_once()
    with runtime.services.session_factory() as session:
        assert session.get(TaskRecord, imported.task_id).status == 'SUCCESS'
        task = session.scalar(select(TaskRecord).where(TaskRecord.task_type == 'MATCH_CANDIDATE'))
        assert task is not None and task.status == 'QUEUED'
        match_task_id = task.id
    assert await runtime.worker.run_once()
    with runtime.services.session_factory() as session:
        assert session.get(TaskRecord, match_task_id).status == 'RETRY_WAIT'
        assert session.get(ResumeRevision, imported.revision_id).status == 'READY'


@pytest.mark.asyncio
async def test_embedding_outage_does_not_turn_successful_parsing_into_failure(tmp_path, monkeypatch):
    runtime = build_runtime(Settings(data_root=tmp_path / 'data', session_token='test'))
    with runtime.services.session_factory() as session:
        imported = ResumeIngestService(session, runtime.services.blob_store).ingest(
            IngestResume(filename='sample.pdf', content=make_resume_pdf()))
    async def unavailable(*args, **kwargs):
        raise RuntimeError('controlled embedding outage')
    monkeypatch.setattr(runtime.providers.embedding, 'embed_documents', unavailable)
    assert await runtime.worker.run_once()
    with runtime.services.session_factory() as session:
        assert session.get(TaskRecord, imported.task_id).status == 'SUCCESS'
        assert session.get(ResumeRevision, imported.revision_id).status == 'READY'
    assert runtime.services.index_sync_service.status()['failed'] == 1


def test_runtime_reconciles_legacy_onboarding_projection_before_serving(tmp_path):
    from kerui_recruit.cases.service import CaseService
    from kerui_recruit.db.models import Candidate, IndexSyncRecord, Jd

    settings = Settings(data_root=tmp_path / "data", session_token="test")
    first = build_runtime(settings)
    with first.services.session_factory() as session, session.begin():
        candidate = Candidate(display_name="Legacy", status="AVAILABLE")
        job = Jd(company="Legacy Co", title="Role", status="OPEN")
        session.add_all([candidate, job])
        session.flush()
        candidate_id, job_id = candidate.id, job.id
    cases = CaseService(first.services.session_factory)
    case = cases.create(candidate_id=candidate_id, jd_id=job_id)
    cases.onboard(case.id)
    with first.services.session_factory() as session, session.begin():
        candidate = session.get(Candidate, candidate_id)
        candidate.status = "AVAILABLE"
        candidate.workflow_previous_status = None
        session.query(IndexSyncRecord).filter_by(entity_type="candidate", entity_id=candidate_id).delete()
    first.services.backup_service.engine.dispose()

    restarted = build_runtime(settings)
    with restarted.services.session_factory() as session:
        candidate = session.get(Candidate, candidate_id)
        assert candidate.status == "ON_HOLD"
        assert candidate.workflow_previous_status == "AVAILABLE"
        sync = session.scalar(select(IndexSyncRecord).where(
            IndexSyncRecord.entity_type == "candidate", IndexSyncRecord.entity_id == candidate_id))
        assert sync is not None and sync.requested_version > sync.applied_version
    restarted.services.backup_service.engine.dispose()
