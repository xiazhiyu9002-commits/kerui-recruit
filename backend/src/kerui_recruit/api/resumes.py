from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, update

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import Candidate, CandidateContact, ResumeDocument, ResumeRevision
from kerui_recruit.encryption.service import EncryptionService
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


class ResumeRevisionItem(BaseModel):
    revision_id: str
    display_name: str | None
    original_filename: str
    status: str
    is_current: bool
    created_at: datetime


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
        session.flush()
        return ResumeRevisionItem(
            revision_id=revision.id,
            display_name=revision.display_name,
            original_filename=revision.original_filename,
            status=revision.status,
            is_current=revision.is_current,
            created_at=revision.created_at,
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
        session.flush()
        return CandidateContactResponse(
            email=command.email,
            phone=command.phone,
            email_confidence=contact.email_confidence,
            phone_confidence=contact.phone_confidence,
        )
