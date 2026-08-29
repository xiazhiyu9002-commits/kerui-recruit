from dataclasses import asdict
from pathlib import Path

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


class ImportFolderRequest(BaseModel):
    directory: str


class ImportFolderResponse(BaseModel):
    imported: list[ImportResumeResponse]
    skipped: list[str]
    errors: list[str]


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


@router.post("/import-folder", response_model=ImportFolderResponse)
def import_folder(command: ImportFolderRequest, request: Request) -> ImportFolderResponse:
    services: AppServices = request.app.state.services
    directory = Path(command.directory).expanduser()
    if not directory.is_dir():
        raise ApiError(400, "E_INVALID_DIRECTORY", "目录不存在或不可访问")

    imported: list[ImportResumeResponse] = []
    skipped: list[str] = []
    errors: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ResumeIngestService.allowed_suffixes:
            skipped.append(path.name)
            continue
        try:
            content = path.read_bytes()
            if len(content) > 30 * 1024 * 1024:
                errors.append(f"{path.name}: 文件超过 30MB")
                continue
            with services.session_factory() as session:
                result = ResumeIngestService(session, services.blob_store).ingest(
                    IngestResume(filename=path.name, content=content)
                )
            imported.append(ImportResumeResponse(**asdict(result)))
        except Exception as exc:  # noqa: BLE001 - report per-file failures
            errors.append(f"{path.name}: {exc}")
    return ImportFolderResponse(imported=imported, skipped=skipped, errors=errors)
