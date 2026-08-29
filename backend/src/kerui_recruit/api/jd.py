from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.jd.extract import UnsupportedJdType, extract_jd_text
from kerui_recruit.jd.ingest import IngestJd, JdIngestService


router = APIRouter(prefix="/api/jd", tags=["jd"])


class ImportJdRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    source_text: str = Field(min_length=1, max_length=100_000)


class ImportJdResponse(BaseModel):
    jd_id: str
    revision_id: str


@router.post("/import", response_model=ImportJdResponse, status_code=202)
async def import_jd(command: ImportJdRequest, request: Request) -> ImportJdResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        result = JdIngestService(session).ingest(
            IngestJd(company=command.company, title=command.title, source_text=command.source_text)
        )
    return ImportJdResponse(jd_id=result.jd_id, revision_id=result.revision_id)


@router.post("/import-file", response_model=ImportJdResponse, status_code=202)
async def import_jd_file(
    request: Request,
    file: UploadFile = File(...),
    company: str = Form(""),
    title: str = Form(""),
) -> ImportJdResponse:
    services: AppServices = request.app.state.services
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ApiError(413, "E_FILE_TOO_LARGE", "JD 文件不能超过 10MB")
    filename = file.filename or "jd"
    try:
        source_text = extract_jd_text(filename, content)
    except UnsupportedJdType:
        raise ApiError(415, "E_JD_FILE_TYPE_UNSUPPORTED", "仅支持 Word 和 Excel 格式的 JD 文件")
    if not source_text.strip():
        raise ApiError(422, "E_JD_EMPTY", "无法从 JD 文件中提取到文本")

    with services.session_factory() as session:
        result = JdIngestService(session).ingest(
            IngestJd(
                company=company.strip() or "未知",
                title=title.strip() or Path(filename).stem,
                source_text=source_text,
            )
        )
    return ImportJdResponse(jd_id=result.jd_id, revision_id=result.revision_id)