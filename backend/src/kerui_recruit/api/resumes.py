from dataclasses import asdict

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService


router = APIRouter(prefix="/api/resumes", tags=["resumes"])


class ImportResumeResponse(BaseModel):
    candidate_id: str
    document_id: str
    revision_id: str
    blob_id: str
    task_id: str


@router.post("/import", response_model=ImportResumeResponse, status_code=202)
async def import_resume(request: Request, file: UploadFile = File(...)) -> ImportResumeResponse:
    services: AppServices = request.app.state.services
    content = await file.read(30 * 1024 * 1024 + 1)
    if len(content) > 30 * 1024 * 1024:
        raise ApiError(413, "E_FILE_TOO_LARGE", "单个简历文件不能超过 30MB")
    filename = file.filename or "resume"
    with services.session_factory() as session:
        result = ResumeIngestService(session, services.blob_store).ingest(
            IngestResume(filename=filename, content=content)
        )
    return ImportResumeResponse(**asdict(result))
