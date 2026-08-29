from pathlib import Path

import httpx
import pymupdf
import pytest

from kerui_recruit.core.settings import Settings
from kerui_recruit.db.models import ResumeRevision, TaskRecord
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.runtime import build_runtime, create_runtime_app
from kerui_recruit.search.contracts import CandidateFilters


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
