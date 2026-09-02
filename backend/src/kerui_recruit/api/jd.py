from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import Jd, JdRevision
from kerui_recruit.jd.extract import UnsupportedJdType, extract_jd_text, split_jd_text
from kerui_recruit.jd.ingest import IngestJd, JdIngestService
from kerui_recruit.cases.state import refresh_links
from kerui_recruit.search.sync import enqueue_sync


router = APIRouter(prefix="/api/jd", tags=["jd"])


class ImportJdRequest(BaseModel):
    company: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
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


class ImportJdBatchRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=500_000)


class ImportJdBatchResponse(BaseModel):
    imported: list[ImportJdResponse]


@router.post("/import-batch", response_model=ImportJdBatchResponse, status_code=202)
async def import_jd_batch(
    command: ImportJdBatchRequest, request: Request
) -> ImportJdBatchResponse:
    """Import one or more JDs from a single text blob (split then AI parse)."""
    services: AppServices = request.app.state.services
    if services.jd_pipeline is not None:
        chunks = await services.jd_pipeline.split(command.source_text)
    else:
        chunks = split_jd_text(command.source_text)
    imported: list[ImportJdResponse] = []
    with services.session_factory() as session:
        service = JdIngestService(session)
        for index, chunk in enumerate(chunks):
            result = service.ingest(
                IngestJd(company="", title="", source_text=chunk, passive_match=(index == 0))
            )
            imported.append(
                ImportJdResponse(jd_id=result.jd_id, revision_id=result.revision_id)
            )
    return ImportJdBatchResponse(imported=imported)


@router.post("/import-batch-file", response_model=ImportJdBatchResponse, status_code=202)
async def import_jd_batch_file(
    request: Request, file: UploadFile = File(...)
) -> ImportJdBatchResponse:
    """Import one or more JDs from a Word/Excel file (split then AI parse)."""
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

    if services.jd_pipeline is not None:
        chunks = await services.jd_pipeline.split(source_text)
    else:
        chunks = split_jd_text(source_text)
    imported: list[ImportJdResponse] = []
    with services.session_factory() as session:
        service = JdIngestService(session)
        for index, chunk in enumerate(chunks):
            result = service.ingest(
                IngestJd(company="", title="", source_text=chunk, passive_match=(index == 0))
            )
            imported.append(
                ImportJdResponse(jd_id=result.jd_id, revision_id=result.revision_id)
            )
    return ImportJdBatchResponse(imported=imported)


class JdListItem(BaseModel):
    jd_id: str
    revision_id: str
    company: str
    title: str
    status: str
    jd_status: str
    ai_category: str | None
    location: str | None
    min_years: float | None
    parsed_data: dict | None = None
    source_text: str | None = None


@router.get("", response_model=list[JdListItem])
def list_jds(request: Request) -> list[JdListItem]:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        rows = session.execute(
            select(Jd, JdRevision)
            .join(JdRevision, JdRevision.jd_id == Jd.id)
            .where(Jd.deleted_at.is_(None), JdRevision.is_current.is_(True))
            .order_by(Jd.created_at.desc())
        ).all()
    return [
        JdListItem(
            jd_id=jd.id,
            revision_id=revision.id,
            company=jd.company,
            title=jd.title,
            status=revision.status,
            jd_status=jd.status,
            ai_category=revision.ai_category,
            location=revision.location,
            min_years=float(revision.min_years) if revision.min_years is not None else None,
            parsed_data=revision.parsed_data,
            source_text=revision.source_text,
        )
        for jd, revision in rows
    ]


class UpdateJdStatusRequest(BaseModel):
    status: str = Field(pattern="^(OPEN|FILLED|CANCELLED)$")


class JdStatusResponse(BaseModel):
    jd_id: str
    status: str


@router.patch("/{jd_id}/status", response_model=JdStatusResponse)
def update_jd_status(
    jd_id: str, command: UpdateJdStatusRequest, request: Request
) -> JdStatusResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session, session.begin():
        jd = session.get(Jd, jd_id)
        if jd is None:
            raise ApiError(404, "E_JD_NOT_FOUND", "岗位不存在")
        jd.status = command.status
        refresh_links(session, jd_id=jd_id)
        enqueue_sync(session, "jd", jd_id)
    return JdStatusResponse(jd_id=jd_id, status=command.status)


_AI_CATEGORY_ALIASES = {
    "AI": "CORE_AI",
    "AI相关": "AI_RELATED",
    "非AI": "NON_AI",
    "CORE_AI": "CORE_AI",
    "AI_RELATED": "AI_RELATED",
    "NON_AI": "NON_AI",
}


class UpdateJdFieldRequest(BaseModel):
    field: str
    value: Any = None


class UpdateJdFieldResponse(BaseModel):
    jd_id: str
    revision_id: str
    field: str
    value: Any


@router.put("/{jd_id}/field", response_model=UpdateJdFieldResponse)
def update_jd_field(
    jd_id: str, command: UpdateJdFieldRequest, request: Request
) -> UpdateJdFieldResponse:
    """Update an editable JD field (title/company/ai_category) in place."""
    services: AppServices = request.app.state.services
    field = command.field
    with services.session_factory() as session, session.begin():
        jd = session.get(Jd, jd_id)
        if jd is None:
            raise ApiError(404, "E_JD_NOT_FOUND", "岗位不存在")
        revision = session.scalar(
            select(JdRevision).where(
                JdRevision.jd_id == jd_id, JdRevision.is_current.is_(True)
            )
        )
        if revision is None:
            raise ApiError(404, "E_JD_REVISION_NOT_FOUND", "岗位版本不存在")

        parsed = dict(revision.parsed_data or {})
        if field == "title":
            value = str(command.value or "").strip()
            jd.title = value
            parsed["title"] = value
        elif field == "company":
            value = str(command.value or "").strip()
            jd.company = value
            parsed["company"] = value
        elif field == "ai_category":
            value = _AI_CATEGORY_ALIASES.get(str(command.value or "").strip())
            if value is None:
                raise ApiError(422, "E_JD_AI_CATEGORY_INVALID", "AI 分类无效")
            revision.ai_category = value
            parsed["ai_category"] = value
        else:
            raise ApiError(422, "E_JD_FIELD_UNSUPPORTED", "不支持的字段")
        revision.parsed_data = parsed
        enqueue_sync(session, "jd", jd_id)

    return UpdateJdFieldResponse(
        jd_id=jd_id, revision_id=revision.id, field=field, value=value
    )
