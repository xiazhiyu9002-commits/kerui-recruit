from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import JdRevision, JdRequirement
from kerui_recruit.jd.structured import JdParser


@dataclass(frozen=True, slots=True)
class JdPipelineResult:
    jd_id: str
    revision_id: str
    status: str


class JdPipeline:
    def __init__(self, *, session_factory: sessionmaker[Session], parser: JdParser) -> None:
        self.session_factory = session_factory
        self.parser = parser

    async def run(self, revision_id: str) -> JdPipelineResult:
        parsed = await self.parser.parse_jd(self._source_text(revision_id))
        with self.session_factory() as session:
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                raise LookupError(f"Jd revision not found: {revision_id}")
            revision.status = "PROCESSING"
            session.commit()

            revision.parsed_data = parsed.model_dump(mode="json")
            revision.ai_category = parsed.ai_category
            revision.highest_degree = parsed.highest_degree
            revision.min_years = (
                None if parsed.min_years is None else _decimal(parsed.min_years)
            )
            revision.location = parsed.location
            revision.requirements = [
                JdRequirement(kind=req.kind, label=req.label, value=req.value)
                for req in parsed.requirements
            ]
            revision.status = "READY"
            session.commit()
            return JdPipelineResult(
                jd_id=revision.jd_id,
                revision_id=revision.id,
                status="READY",
            )

    def _source_text(self, revision_id: str) -> str:
        with self.session_factory() as session:
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                raise LookupError(f"Jd revision not found: {revision_id}")
            return revision.source_text or ""


def _decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)