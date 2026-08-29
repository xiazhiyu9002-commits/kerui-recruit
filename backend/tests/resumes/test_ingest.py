from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Blob, Candidate, ResumeRevision, TaskRecord
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.resumes.ingest import (
    IngestResume,
    ResumeIngestService,
    UnsupportedResumeType,
)
from kerui_recruit.storage.blobs import BlobStore


def make_service(tmp_path: Path) -> tuple[ResumeIngestService, Session]:
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    session = Session(engine)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    return ResumeIngestService(session, store), session


def test_ingest_reuses_blob_but_creates_a_new_resume_version(tmp_path: Path) -> None:
    """A new upload must preserve version history without duplicating bytes."""
    service, session = make_service(tmp_path)
    with session:
        first = service.ingest(
            IngestResume(filename="张三.pdf", content=b"same", display_name="张三")
        )
        second = service.ingest(
            IngestResume(
                filename="张三-更新.pdf",
                content=b"same",
                candidate_id=first.candidate_id,
            )
        )

        assert first.blob_id == second.blob_id
        assert first.revision_id != second.revision_id
        assert session.scalar(select(func.count()).select_from(Blob)) == 1
        assert session.get(Blob, first.blob_id).reference_count == 2
        revisions = session.scalars(
            select(ResumeRevision).order_by(ResumeRevision.created_at)
        ).all()
        assert [revision.is_current for revision in revisions] == [False, True]
        assert session.scalar(select(func.count()).select_from(TaskRecord)) == 2


def test_ingest_creates_candidate_and_pending_parse_task(tmp_path: Path) -> None:
    """An accepted original must always have a recoverable fact row and task."""
    service, session = make_service(tmp_path)
    with session:
        result = service.ingest(
            IngestResume(filename="李四.docx", content=b"docx", display_name="李四")
        )

        candidate = session.get(Candidate, result.candidate_id)
        task = session.get(TaskRecord, result.task_id)
        assert candidate is not None and candidate.display_name == "李四"
        assert task is not None and task.status == "PENDING"
        assert task.payload == {"revision_id": result.revision_id}


def test_unsupported_file_type_is_rejected_before_writing(tmp_path: Path) -> None:
    """Unsupported executable content must never enter the original store."""
    service, session = make_service(tmp_path)
    with session, pytest.raises(UnsupportedResumeType) as error:
        service.ingest(IngestResume(filename="payload.exe", content=b"bad"))

    assert error.value.code == "E_FILE_TYPE_UNSUPPORTED"
    assert list((tmp_path / "blobs").rglob("*.*")) == []
