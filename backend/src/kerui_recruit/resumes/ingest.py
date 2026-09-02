from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kerui_recruit.db.models import (
    Blob,
    Candidate,
    ResumeDocument,
    ResumeRevision,
    TaskRecord,
)
from kerui_recruit.storage.blobs import BlobStore


class UnsupportedResumeType(ValueError):
    code = "E_FILE_TYPE_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class IngestResume:
    filename: str
    content: bytes
    display_name: str | None = None
    candidate_id: str | None = None
    queue_name: str = "batch"
    passive_match: bool = True


@dataclass(frozen=True, slots=True)
class IngestResult:
    candidate_id: str
    document_id: str
    revision_id: str
    blob_id: str
    task_id: str


class ResumeIngestService:
    allowed_suffixes = frozenset({".pdf", ".doc", ".docx"})

    def __init__(self, session: Session, blob_store: BlobStore) -> None:
        self.session = session
        self.blob_store = blob_store

    def ingest(self, command: IngestResume) -> IngestResult:
        suffix = Path(command.filename).suffix.lower()
        if suffix not in self.allowed_suffixes:
            raise UnsupportedResumeType(f"Unsupported resume type: {suffix or 'none'}")

        stored = self.blob_store.put(BytesIO(command.content), suffix)
        try:
            blob = self.session.scalar(
                select(Blob).where(Blob.content_sha256 == stored.sha256)
            )
            if blob is None:
                blob = Blob(
                    content_sha256=stored.sha256,
                    suffix=stored.suffix,
                    size_bytes=stored.size_bytes,
                    storage_path=str(stored.path.relative_to(self.blob_store.root)),
                )
                self.session.add(blob)
                self.session.flush()
            else:
                blob.reference_count += 1

            candidate = self._resolve_candidate(command)
            document = self._resolve_document(candidate)
            self.session.execute(
                update(ResumeRevision)
                .where(ResumeRevision.document_id == document.id)
                .values(is_current=False)
            )
            revision = ResumeRevision(
                document=document,
                blob=blob,
                content_sha256=stored.sha256,
                original_filename=command.filename,
                status="PENDING",
                is_current=True,
            )
            self.session.add(revision)
            self.session.flush()
            task = TaskRecord(
                task_type="PARSE_RESUME",
                queue_name=command.queue_name,
                priority=10,
                payload={
                    "revision_id": revision.id,
                    "passive_match": command.passive_match,
                },
                idempotency_key=f"PARSE_RESUME:{revision.id}:v1",
            )
            self.session.add(task)
            self.session.commit()
            return IngestResult(
                candidate_id=candidate.id,
                document_id=document.id,
                revision_id=revision.id,
                blob_id=blob.id,
                task_id=task.id,
            )
        except Exception:
            self.session.rollback()
            if stored.created:
                stored.path.unlink(missing_ok=True)
            raise

    def _resolve_candidate(self, command: IngestResume) -> Candidate:
        if command.candidate_id:
            candidate = self.session.get(Candidate, command.candidate_id)
            if candidate is None:
                raise LookupError(f"Candidate not found: {command.candidate_id}")
            return candidate
        display_name = command.display_name or Path(command.filename).stem
        candidate = Candidate(display_name=display_name)
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def _resolve_document(self, candidate: Candidate) -> ResumeDocument:
        document = self.session.scalar(
            select(ResumeDocument)
            .where(ResumeDocument.candidate_id == candidate.id)
            .order_by(ResumeDocument.created_at)
            .limit(1)
        )
        if document is not None:
            return document
        document = ResumeDocument(candidate=candidate)
        self.session.add(document)
        self.session.flush()
        return document
