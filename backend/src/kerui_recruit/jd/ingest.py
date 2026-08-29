from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from kerui_recruit.db.models import Jd, JdRevision


@dataclass(frozen=True, slots=True)
class IngestJd:
    company: str
    title: str
    source_text: str


@dataclass(frozen=True, slots=True)
class JdIngestResult:
    jd_id: str
    revision_id: str


class JdIngestService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest(self, command: IngestJd) -> JdIngestResult:
        jd = Jd(company=command.company, title=command.title)
        self.session.add(jd)
        self.session.flush()
        revision = JdRevision(
            jd=jd,
            revision_no=1,
            source_text=command.source_text,
            status="PENDING",
            is_current=True,
        )
        self.session.add(revision)
        self.session.commit()
        return JdIngestResult(jd_id=jd.id, revision_id=revision.id)