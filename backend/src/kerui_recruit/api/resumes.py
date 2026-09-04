import asyncio
import re
from dataclasses import asdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, update

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.base import new_id
from kerui_recruit.db.models import (
    Candidate,
    CandidateContact,
    ResumeDocument,
    ResumeRevision,
    TaskRecord,
)
from kerui_recruit.encryption.service import EncryptionService
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.resumes.extract import LegacyDocConversionError, convert_doc_to_pdf
from kerui_recruit.resumes.pipeline import build_chunk_contents_from_dict
from kerui_recruit.resumes.normalize import normalize_resume
from kerui_recruit.duplicates.service import normalize_email, normalize_phone
from kerui_recruit.resumes.structured import ParsedResume
from kerui_recruit.resumes.validity import check_parsed_resume
from kerui_recruit.search.sync import enqueue_sync
from kerui_recruit.search.contracts import SearchChunk
from kerui_recruit.tasks.repository import TaskSpec


router = APIRouter(prefix="/api/resumes", tags=["resumes"])


class ImportResumeResponse(BaseModel):
    action: str
    candidate_id: str | None
    document_id: str | None
    revision_id: str | None
    blob_id: str | None
    task_id: str | None
    message: str = ""
    conflict_candidate_ids: list[str] = Field(default_factory=list)
    created_task: bool = False


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
            IngestResume(filename=filename, content=content, queue_name="interactive")
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

    files: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ResumeIngestService.allowed_suffixes:
            skipped.append(path.name)
            continue
        files.append(path)

    # 批量入库时只让第一个候选人触发被动匹配，其余按需通过"匹配"按钮处理。
    for index, path in enumerate(files):
        try:
            content = path.read_bytes()
            if len(content) > 30 * 1024 * 1024:
                errors.append(f"{path.name}: 文件超过 30MB")
                continue
            with services.session_factory() as session:
                result = ResumeIngestService(session, services.blob_store).ingest(
                    IngestResume(
                        filename=path.name,
                        content=content,
                        queue_name="normal",
                        passive_match=(index == 0),
                    )
                )
            if result.action == "ALREADY_IMPORTED":
                skipped.append(path.name)
            elif result.action == "DUPLICATE_CONFLICT":
                errors.append(f"{path.name}: 相同文件已关联到多个候选人")
            else:
                imported.append(ImportResumeResponse(**asdict(result)))
        except Exception as exc:  # noqa: BLE001 - report per-file failures
            errors.append(f"{path.name}: {exc}")
    return ImportFolderResponse(imported=imported, skipped=skipped, errors=errors)


class CandidateListItem(BaseModel):
    candidate_id: str
    revision_id: str
    display_name: str
    total_years: float | None
    highest_degree: str | None
    location: str | None
    status: str
    revision_status: str | None
    phone: str | None
    original_filename: str | None
    parsed_data: dict | None
    error_code: str | None = None
    error_message: str | None = None


class CandidatePage(BaseModel):
    items: list[CandidateListItem]
    total: int
    page: int
    page_size: int
    has_more: bool


def _candidate_rows(services: AppServices, *, offset: int | None = None, limit: int | None = None):
    latest_revision = (
        select(ResumeRevision.id)
        .join(ResumeDocument, ResumeRevision.document_id == ResumeDocument.id)
        .where(ResumeDocument.candidate_id == Candidate.id, ResumeRevision.is_current.is_(True))
        .order_by(ResumeRevision.created_at.desc(), ResumeRevision.id.desc())
        .limit(1).correlate(Candidate).scalar_subquery()
    )
    stmt = (select(Candidate, ResumeRevision, CandidateContact).select_from(Candidate)
            .join(ResumeRevision, ResumeRevision.id == latest_revision)
            .outerjoin(CandidateContact, CandidateContact.candidate_id == Candidate.id)
            .where(Candidate.deleted_at.is_(None))
            .order_by(Candidate.created_at.desc(), Candidate.id.desc()))
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    with services.session_factory() as session:
        return session.execute(stmt).all()


def _candidate_items(services: AppServices, rows) -> list[CandidateListItem]:
    encryption = services.encryption_service
    return [CandidateListItem(
        candidate_id=candidate.id, revision_id=revision.id, display_name=candidate.display_name,
        total_years=float(candidate.total_years) if candidate.total_years is not None else None,
        highest_degree=candidate.highest_degree, location=(revision.parsed_data or {}).get("location"),
        status=candidate.status, revision_status=revision.status,
        phone=(encryption.decrypt(contact.phone_encrypted)
               if encryption is not None and contact is not None and contact.phone_encrypted else None),
        original_filename=revision.original_filename, parsed_data=revision.parsed_data,
        error_code=revision.error_code, error_message=revision.error_message,
    ) for candidate, revision, contact in rows]


@router.get("/candidates", response_model=list[CandidateListItem])
def list_candidates(request: Request) -> list[CandidateListItem]:
    services: AppServices = request.app.state.services
    return _candidate_items(services, _candidate_rows(services))


@router.get("/candidates/page", response_model=CandidatePage)
def list_candidate_page(request: Request, page: int = 1, page_size: int = 100) -> CandidatePage:
    if page < 1 or page_size < 1 or page_size > 200:
        raise ApiError(422, "E_PAGE_INVALID", "页码必须大于0，每页不能超过200条")
    services: AppServices = request.app.state.services
    has_current = select(ResumeRevision.id).join(ResumeDocument).where(
        ResumeDocument.candidate_id == Candidate.id, ResumeRevision.is_current.is_(True)).exists()
    with services.session_factory() as session:
        total = int(session.scalar(select(func.count()).select_from(Candidate).where(
            Candidate.deleted_at.is_(None), has_current)) or 0)
    rows = _candidate_rows(services, offset=(page - 1) * page_size, limit=page_size)
    return CandidatePage(items=_candidate_items(services, rows), total=total, page=page,
                         page_size=page_size, has_more=page * page_size < total)


class ResumeRevisionItem(BaseModel):
    revision_id: str
    display_name: str | None
    original_filename: str
    status: str
    is_current: bool
    created_at: datetime
    parsed_data: dict | None = None
    error_code: str | None = None
    error_message: str | None = None


@router.get("/candidate/{candidate_id}/revisions", response_model=list[ResumeRevisionItem])
def list_revisions(candidate_id: str, request: Request) -> list[ResumeRevisionItem]:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        revisions = session.scalars(
            select(ResumeRevision)
            .join(ResumeDocument, ResumeDocument.id == ResumeRevision.document_id)
            .where(ResumeDocument.candidate_id == candidate_id)
            .order_by(ResumeRevision.created_at.desc())
        ).all()
    return [
        ResumeRevisionItem(
            revision_id=r.id,
            display_name=r.display_name,
            original_filename=r.original_filename,
            status=r.status,
            is_current=r.is_current,
            created_at=r.created_at,
            parsed_data=r.parsed_data,
            error_code=r.error_code,
            error_message=r.error_message,
        )
        for r in revisions
    ]


@router.post("/revisions/{revision_id}/switch", response_model=ResumeRevisionItem)
def switch_revision(revision_id: str, request: Request) -> ResumeRevisionItem:
    services: AppServices = request.app.state.services
    with services.session_factory() as session, session.begin():
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        session.execute(
            update(ResumeRevision)
            .where(ResumeRevision.document_id == revision.document_id)
            .values(is_current=False)
        )
        revision.is_current = True
        candidate = revision.document.candidate
        if revision.status == "READY":
            for field in ("name", "total_years", "highest_degree"):
                _sync_candidate_columns(candidate, field, (revision.parsed_data or {}).get(field))
        enqueue_sync(session, "candidate", candidate.id)
        session.flush()
        return ResumeRevisionItem(
            revision_id=revision.id,
            display_name=revision.display_name,
            original_filename=revision.original_filename,
            status=revision.status,
            is_current=revision.is_current,
            created_at=revision.created_at,
            parsed_data=revision.parsed_data,
        )


class ReparseResumeRequest(BaseModel):
    force_ocr: bool = True


class ReparseResumeResponse(BaseModel):
    revision_id: str
    task_id: str


@router.post(
    "/revisions/{revision_id}/reparse",
    response_model=ReparseResumeResponse,
    status_code=202,
)
def reparse_resume(
    revision_id: str,
    command: ReparseResumeRequest,
    request: Request,
) -> ReparseResumeResponse:
    """对既有简历版本创建一次强制 OCR 重新解析任务（幂等）。

    复用已有原件与候选人身份，不要求重新上传；同一版本重复点击返回同一任务，
    不会被文件去重逻辑拦截。
    """
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        force_ocr = bool(command.force_ocr)
        key = f"REPARSE_RESUME:{revision_id}:{force_ocr}"
        latest = session.scalar(select(TaskRecord).where(
            TaskRecord.idempotency_key.like(key + "%")
        ).order_by(TaskRecord.created_at.desc()).limit(1))
        if latest is not None:
            key = (f"{key}:{latest.id}" if latest.status in ("SUCCESS", "CANCELLED")
                   else latest.idempotency_key)
        task_id = services.task_repository.enqueue(
            TaskSpec(
                task_type="PARSE_RESUME",
                queue_name="interactive",
                priority=10,
                payload={"revision_id": revision_id, "force_ocr": force_ocr},
                idempotency_key=key,
            )
        )
    # 同名任务已失败终态时重新入队，支持失败后再次点击重试；进行中的任务保持幂等。
    with services.session_factory() as session:
        existing = session.get(TaskRecord, task_id)
        needs_retry = existing is not None and existing.status in ("FAILED", "DEAD_LETTER")
    if needs_retry:
        services.task_repository.retry(task_id)
    return ReparseResumeResponse(revision_id=revision_id, task_id=task_id)


class ResumeReviewRequest(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)


def _review_response(revision: ResumeRevision) -> dict:
    return {
        "revision_id": revision.id, "status": revision.status,
        "review_required": revision.status != "READY",
        "raw_text": revision.raw_text,
        "parsed_data": revision.parsed_data, "review_data": revision.review_data,
        "manual_overrides": revision.manual_overrides or {},
        "extraction_diagnostics": revision.extraction_diagnostics or {},
        "error_code": revision.error_code, "error_message": revision.error_message,
    }


@router.get("/revisions/{revision_id}/review")
def get_resume_review(revision_id: str, request: Request) -> dict:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        return _review_response(revision)


@router.post("/revisions/{revision_id}/review")
async def approve_resume_review(revision_id: str, command: ResumeReviewRequest, request: Request) -> dict:
    services: AppServices = request.app.state.services
    unknown = set(command.fields) - set(ParsedResume.model_fields) - {"age", "direction_profile", "direction_diagnostics"}
    if unknown:
        raise ApiError(422, "E_INVALID_RESUME_FIELD", "包含不支持的简历字段")
    with services.session_factory() as session, session.begin():
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        if revision.status == "PROCESSING":
            raise ApiError(409, "E_RESUME_PROCESSING", "解析进行中，请完成后复核")
        overrides = {**(revision.manual_overrides or {}),
                     **{field: _coerce_field(field, value) for field, value in command.fields.items()}}
        data = {**(revision.review_data or {}), **(revision.parsed_data or {}), **overrides}
        try:
            parsed = ParsedResume.model_validate(data)
        except ValidationError as error:
            raise ApiError(422, "E_INVALID_RESUME_FIELD", "简历字段格式不正确") from error
        validity = check_parsed_resume(parsed, revision.raw_text or "")
        if not validity.ok:
            raise ApiError(422, "E_PENDING_REVIEW", "至少补充有效教育、技能或工作经历后确认复核")
        normalized = normalize_resume(parsed)
        revision.manual_overrides = overrides
        revision.parsed_data = {**normalized.model_dump(mode="json"), **overrides}
        revision.status = "READY"
        revision.parse_version = "resume-schema-v1:manual-review"
        revision.error_code = None
        revision.error_message = None
        candidate = revision.document.candidate
        candidate_id = candidate.id
        if revision.is_current:
            for field in ("name", "total_years", "highest_degree"):
                _sync_candidate_columns(candidate, field, revision.parsed_data.get(field))
            if candidate.status == "PENDING_REVIEW":
                candidate.status = "AVAILABLE"
            enqueue_sync(session, "candidate", candidate_id)
        response = _review_response(revision)
        is_current = revision.is_current
    if is_current and services.index_sync_service is None:
        await _reindex_embedded(services, candidate_id, revision_id)
    return response


@router.get("/revisions/{revision_id}/download")
def download_resume(revision_id: str, request: Request) -> FileResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        path = services.blob_store.root / revision.blob.storage_path
        filename = revision.original_filename
    if not path.exists():
        raise ApiError(404, "E_BLOB_NOT_FOUND", "原始文件不存在")
    import mimetypes
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, filename=filename, media_type=media_type)


@router.get("/revisions/{revision_id}/preview")
def preview_resume(revision_id: str, request: Request) -> FileResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        path = services.blob_store.root / revision.blob.storage_path
        filename = revision.original_filename
    if not path.exists():
        raise ApiError(404, "E_BLOB_NOT_FOUND", "原始文件不存在")

    suffix = Path(filename).suffix.lower()
    if suffix in (".doc", ".docx"):
        try:
            pdf_path = convert_doc_to_pdf(path)
        except LegacyDocConversionError as error:
            raise ApiError(422, "E_PREVIEW_UNSUPPORTED", str(error))
        return FileResponse(
            pdf_path,
            filename=Path(filename).stem + ".pdf",
            media_type="application/pdf",
            content_disposition_type="inline",
        )

    import mimetypes
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(
        path,
        filename=filename,
        media_type=media_type,
        content_disposition_type="inline",
    )


class CandidateContactResponse(BaseModel):
    email: str | None
    phone: str | None
    email_confidence: float | None
    phone_confidence: float | None


class CandidateContactUpdate(BaseModel):
    email: str | None = None
    phone: str | None = None


def _decrypt_contact(
    contact: CandidateContact | None,
    encryption: EncryptionService | None,
) -> CandidateContactResponse:
    email = (
        encryption.decrypt(contact.email_encrypted)
        if contact is not None and contact.email_encrypted and encryption is not None
        else None
    )
    phone = (
        encryption.decrypt(contact.phone_encrypted)
        if contact is not None and contact.phone_encrypted and encryption is not None
        else None
    )
    return CandidateContactResponse(
        email=email,
        phone=phone,
        email_confidence=contact.email_confidence if contact is not None else None,
        phone_confidence=contact.phone_confidence if contact is not None else None,
    )


@router.get("/candidate/{candidate_id}/contact", response_model=CandidateContactResponse)
def get_candidate_contact(candidate_id: str, request: Request) -> CandidateContactResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        contact = session.scalar(
            select(CandidateContact).where(CandidateContact.candidate_id == candidate_id)
        )
    return _decrypt_contact(contact, services.encryption_service)


@router.put("/candidate/{candidate_id}/contact", response_model=CandidateContactResponse)
def update_candidate_contact(
    candidate_id: str,
    command: CandidateContactUpdate,
    request: Request,
) -> CandidateContactResponse:
    services: AppServices = request.app.state.services
    encryption = services.encryption_service
    if encryption is None:
        raise ApiError(500, "E_ENCRYPTION_UNAVAILABLE", "加密服务不可用")
    with services.session_factory() as session, session.begin():
        candidate = session.get(Candidate, candidate_id)
        if candidate is None:
            raise ApiError(404, "E_CANDIDATE_NOT_FOUND", "候选人不存在")
        contact = session.scalar(
            select(CandidateContact).where(CandidateContact.candidate_id == candidate_id)
        )
        if contact is None:
            contact = CandidateContact(candidate=candidate)
            session.add(contact)
        contact.email_encrypted = encryption.encrypt(command.email) if command.email else None
        contact.phone_encrypted = encryption.encrypt(command.phone) if command.phone else None
        contact.email_confidence = 1.0 if command.email else None
        contact.phone_confidence = 1.0 if command.phone else None
        contact.email_fingerprint = normalize_email(command.email)
        contact.phone_fingerprint = normalize_phone(command.phone)
        contact.manual_fields = ["email", "phone"]
        session.flush()
        return CandidateContactResponse(
            email=command.email,
            phone=command.phone,
            email_confidence=contact.email_confidence,
            phone_confidence=contact.phone_confidence,
        )


# 字段修改对索引的影响分类：
# - 影响向量内容（需重新 embedding + 重建索引）
# - 仅影响索引过滤元数据（无需重建向量，只更新索引里的对应列）
# - 仅影响数据库（不改索引）
_VECTOR_CONTENT_FIELDS = frozenset({
    "name", "summary", "highest_degree", "total_years", "school",
    "qs_rank", "graduation_year", "industry", "skills",
    "experiences", "projects", "tech_direction", "business_direction", "current_industry", "longest_industry",
})
_METADATA_ONLY_FIELDS = frozenset({"location", "school_level", "preferred_location", "preferred_locations"})
_CONTACT_FIELDS = frozenset({"email", "phone"})
_LIST_FIELDS = frozenset({"tech_direction", "business_direction", "skills", "preferred_locations"})
_INT_FIELDS = frozenset({"qs_rank", "graduation_year", "birth_year", "age"})


def _coerce_field(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in _LIST_FIELDS:
        if isinstance(value, str):
            return [s.strip() for s in re.split(r"[、,，/]", value) if s.strip()]
        if isinstance(value, list):
            return [s.strip() for s in value if isinstance(s, str) and s.strip()]
        return value
    if field in _INT_FIELDS:
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field == "total_years":
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _sync_candidate_columns(candidate: Candidate, field: str, value: Any) -> None:
    if field == "name":
        if value:
            candidate.display_name = value
    elif field == "total_years":
        candidate.total_years = (
            Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if value is not None
            else None
        )
    elif field == "highest_degree":
        candidate.highest_degree = value


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _reindex_embedded(services: AppServices, candidate_id: str, revision_id: str) -> None:
    with services.session_factory() as session:
        revision = session.get(ResumeRevision, revision_id)
        if revision is None:
            return
        parsed = revision.parsed_data or {}
    contents = build_chunk_contents_from_dict(parsed)
    vectors = await services.search_service.embedding_provider.embed_documents(contents)
    chunks = [
        SearchChunk(
            id=new_id(),
            candidate_id=candidate_id,
            revision_id=revision_id,
            content=content,
            vector=tuple(vector),
            total_years=_to_float(parsed.get("total_years")),
            highest_degree=parsed.get("highest_degree"),
            location=parsed.get("location"),
            candidate_status="AVAILABLE",
            qs_rank=parsed.get("qs_rank"),
            school_level=parsed.get("school_level"),
            preferred_location=parsed.get("preferred_location"),
            preferred_locations=tuple(parsed.get("preferred_locations") or []),
        )
        for content, vector in zip(contents, vectors, strict=True)
    ]
    index = services.search_service.index
    await asyncio.to_thread(index.delete_revision, revision_id)
    await asyncio.to_thread(index.upsert, list(chunks))


def _reindex_metadata(services: AppServices, revision_id: str, field: str, value: Any) -> None:
    index = services.search_service.index
    rows = index.get_revision_chunks(revision_id)
    if not rows:
        return
    updated = []
    for row in rows:
        data = dict(row)
        data[field] = value
        updated.append(
            SearchChunk(
                id=data["id"],
                candidate_id=data["candidate_id"],
                revision_id=data["revision_id"],
                content=data["content"],
                vector=tuple(float(x) for x in data["vector"]),
                total_years=data.get("total_years"),
                highest_degree=data.get("highest_degree"),
                location=data.get("location"),
                candidate_status=data.get("candidate_status", "AVAILABLE"),
                qs_rank=data.get("qs_rank"),
                school_level=data.get("school_level"),
                preferred_location=data.get("preferred_location"),
                preferred_locations=tuple(data.get("preferred_locations") or []),
            )
        )
    index.delete_revision(revision_id)
    index.upsert(updated)


class CandidateFieldUpdate(BaseModel):
    field: str
    value: Any = None


@router.put("/candidate/{candidate_id}/field")
async def update_candidate_field(
    candidate_id: str,
    command: CandidateFieldUpdate,
    request: Request,
) -> dict:
    services: AppServices = request.app.state.services
    field = command.field
    value = command.value

    if field in _CONTACT_FIELDS:
        encryption = services.encryption_service
        if encryption is None:
            raise ApiError(500, "E_ENCRYPTION_UNAVAILABLE", "加密服务不可用")
        with services.session_factory() as session, session.begin():
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                raise ApiError(404, "E_CANDIDATE_NOT_FOUND", "候选人不存在")
            contact = session.scalar(
                select(CandidateContact).where(CandidateContact.candidate_id == candidate_id)
            )
            if contact is None:
                contact = CandidateContact(candidate=candidate)
                session.add(contact)
            if field == "phone":
                contact.phone_encrypted = encryption.encrypt(value) if value else None
                contact.phone_confidence = 1.0 if value else None
                contact.phone_fingerprint = normalize_phone(value)
            else:
                contact.email_encrypted = encryption.encrypt(value) if value else None
                contact.email_confidence = 1.0 if value else None
                contact.email_fingerprint = normalize_email(value)
            contact.manual_fields = sorted(set(contact.manual_fields or []) | {field})
            session.flush()
        return {"candidate_id": candidate_id, "field": field, "value": value}

    if field not in ParsedResume.model_fields and field != "age":
        raise ApiError(422, "E_INVALID_RESUME_FIELD", "不支持的简历字段")

    with services.session_factory() as session:
        candidate = session.get(Candidate, candidate_id)
        if candidate is None:
            raise ApiError(404, "E_CANDIDATE_NOT_FOUND", "候选人不存在")
        revision = session.scalar(
            select(ResumeRevision)
            .join(ResumeDocument, ResumeDocument.id == ResumeRevision.document_id)
            .where(
                ResumeDocument.candidate_id == candidate_id,
                ResumeRevision.is_current.is_(True),
            )
        )
        if revision is None:
            raise ApiError(404, "E_REVISION_NOT_FOUND", "简历版本不存在")
        revision_id = revision.id
        parsed = dict(revision.parsed_data or {})
        parsed[field] = _coerce_field(field, value)
        try:
            ParsedResume.model_validate(parsed)
        except ValidationError as error:
            raise ApiError(422, "E_INVALID_RESUME_FIELD", "简历字段格式不正确") from error
        revision.parsed_data = parsed
        revision.manual_overrides = {**(revision.manual_overrides or {}), field: parsed[field]}
        _sync_candidate_columns(candidate, field, parsed[field])
        ready = revision.status == "READY"
        enqueue_sync(session, "candidate", candidate_id)
        session.commit()

    if ready and services.index_sync_service is None and field in _VECTOR_CONTENT_FIELDS:
        await _reindex_embedded(services, candidate_id, revision_id)
    elif ready and services.index_sync_service is None and field in _METADATA_ONLY_FIELDS:
        _reindex_metadata(services, revision_id, field, parsed[field])

    return {
        "candidate_id": candidate_id,
        "revision_id": revision_id,
        "field": field,
        "value": parsed[field],
    }
