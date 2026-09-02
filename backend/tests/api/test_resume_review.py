from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from kerui_recruit.db.models import ResumeRevision, TaskRecord
from kerui_recruit.main import create_app
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.resumes.pipeline import PipelineFailure
from tests.api.test_local_api import build_services, make_pdf_bytes
from tests.resumes.test_pipeline_ocr import EmptyResumeParser, RecordingOCRProvider


@pytest.mark.asyncio
async def test_review_edits_survive_force_ocr_and_are_explicitly_approved(tmp_path: Path) -> None:
    services, pipeline = build_services(tmp_path)
    with services.session_factory() as session:
        imported = ResumeIngestService(session, services.blob_store).ingest(
            IngestResume(filename="resume.pdf", content=make_pdf_bytes()))
    pipeline.parser = EmptyResumeParser()
    with pytest.raises(PipelineFailure):
        await pipeline.run(imported.revision_id)
    transport = httpx.ASGITransport(app=create_app(services))
    async with httpx.AsyncClient(transport=transport, base_url="http://local",
                               headers={"X-Kerui-Session": "test-token"}) as client:
        detail = await client.get(f"/api/resumes/revisions/{imported.revision_id}/review")
        assert detail.status_code == 200
        assert detail.json()["review_required"] is True
        assert "Python Finance" in detail.json()["raw_text"]
        edit = await client.put(f"/api/resumes/candidate/{imported.candidate_id}/field",
                                json={"field": "name", "value": "人工校正姓名"})
        assert edit.status_code == 200
        insufficient = await client.post(f"/api/resumes/revisions/{imported.revision_id}/review", json={"fields": {}})
        assert insufficient.status_code == 422
        approved = await client.post(f"/api/resumes/revisions/{imported.revision_id}/review",
                                     json={"fields": {"skills": ["人工风控技能"], "highest_degree": "本科"}})
        assert approved.status_code == 200
        assert approved.json()["status"] == "READY"
        pipeline.ocr_provider = RecordingOCRProvider({0: "Python Finance resume after OCR with education and experience"})
        await pipeline.run(imported.revision_id, force_ocr=True)
        detail = (await client.get(f"/api/resumes/revisions/{imported.revision_id}/review")).json()
        assert detail["parsed_data"]["name"] == "人工校正姓名"
        assert detail["parsed_data"]["skills"] == ["人工风控技能"]
        assert detail["review_data"]["name"] is None
        assert detail["manual_overrides"]["name"] == "人工校正姓名"


@pytest.mark.asyncio
async def test_reparse_can_be_requested_again_after_success(tmp_path: Path) -> None:
    services, _ = build_services(tmp_path)
    with services.session_factory() as session:
        imported = ResumeIngestService(session, services.blob_store).ingest(
            IngestResume(filename="resume.pdf", content=make_pdf_bytes()))
    transport = httpx.ASGITransport(app=create_app(services))
    async with httpx.AsyncClient(transport=transport, base_url="http://local",
                               headers={"X-Kerui-Session": "test-token"}) as client:
        path = f"/api/resumes/revisions/{imported.revision_id}/reparse"
        first = (await client.post(path, json={"force_ocr": True})).json()
        duplicate = (await client.post(path, json={"force_ocr": True})).json()
        assert duplicate["task_id"] == first["task_id"]
        with services.session_factory() as session, session.begin():
            session.get(TaskRecord, first["task_id"]).status = "SUCCESS"
        second = (await client.post(path, json={"force_ocr": True})).json()
        assert second["task_id"] != first["task_id"]
