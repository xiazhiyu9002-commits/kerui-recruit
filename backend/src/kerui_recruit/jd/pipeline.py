from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import JdRevision, JdRequirement
from kerui_recruit.direction.classifier import DirectionClassifier
from kerui_recruit.direction.models import DirectionDecision, build_direction_diagnostics
from kerui_recruit.jd.structured import JdParser, build_jd_direction_input
from kerui_recruit.search.sync import enqueue_sync


@dataclass(frozen=True, slots=True)
class JdPipelineResult:
    jd_id: str
    revision_id: str
    status: str


class JdPipeline:
    def __init__(self, *, session_factory: sessionmaker[Session], parser: JdParser,
                 direction_classifier: DirectionClassifier | None = None) -> None:
        self.session_factory = session_factory
        self.parser = parser
        self.direction_classifier = direction_classifier

    async def run(self, revision_id: str) -> JdPipelineResult:
        with self.session_factory() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                raise LookupError(f"Jd revision not found: {revision_id}")
            source_text = revision.source_text
            previous_ready = revision.status == "READY"
            revision.status = "PROCESSING"
            session.commit()

        try:
            # Never hold the SQLite write lock across an external provider await.
            parsed = await self.parser.parse_jd(source_text or "")
            direction_decision, has_manual_direction = await self._classify_direction(revision_id, parsed)
            with self.session_factory() as session:
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                revision = session.get(JdRevision, revision_id)
                if revision is None:
                    raise LookupError(f"Jd revision not found: {revision_id}")
                if revision.source_text != source_text or revision.status != "PROCESSING":
                    raise RuntimeError("JD source or state changed during parsing; result discarded")
                data = parsed.model_dump(mode="json")
                # Explicit/imported titles and companies are authoritative. A
                # parser may fill missing labels, but cannot erase human edits.
                if revision.is_current:
                    revision.jd.company = revision.jd.company or parsed.company
                    revision.jd.title = revision.jd.title or parsed.title
                    data.update(company=revision.jd.company, title=revision.jd.title)
                if has_manual_direction:
                    data["direction_profile"] = (revision.manual_overrides or {}).get("direction_profile")
                elif direction_decision is not None:
                    data["direction_profile"] = direction_decision.effective_profile.model_dump(mode="json")
                if direction_decision is not None:
                    review_data = dict(revision.review_data or {})
                    review_data["direction_profile"] = direction_decision.effective_profile.model_dump(mode="json")
                    review_data["direction_diagnostics"] = _direction_diagnostics(direction_decision)
                    revision.review_data = review_data
                revision.parsed_data = data
                revision.ai_category = parsed.ai_category
                revision.highest_degree = parsed.highest_degree
                revision.min_years = None if parsed.min_years is None else _decimal(parsed.min_years)
                revision.location = parsed.location
                revision.requirements = [
                    JdRequirement(kind=req.kind, label=req.label, value=req.value)
                    for req in parsed.requirements
                ]
                revision.status = "READY"
                enqueue_sync(session, "jd", revision.jd_id)
                session.commit()
                return JdPipelineResult(jd_id=revision.jd_id, revision_id=revision.id, status="READY")
        except BaseException:
            with self.session_factory() as session, session.begin():
                revision = session.get(JdRevision, revision_id)
                if revision is not None and revision.status == "PROCESSING" and revision.source_text == source_text:
                    revision.status = "READY" if previous_ready else "FAILED"
                    enqueue_sync(session, "jd", revision.jd_id)
            raise

    async def _classify_direction(self, revision_id: str, parsed) -> tuple[DirectionDecision | None, bool]:
        with self.session_factory() as session:
            revision = session.get(JdRevision, revision_id)
            manual = dict(revision.manual_overrides or {})
        if manual.get("direction_profile"):
            return None, True
        if self.direction_classifier is None:
            return None, False
        try:
            decision = await self.direction_classifier.classify(build_jd_direction_input(parsed))
            return decision, False
        except Exception:
            return None, False

    def _source_text(self, revision_id: str) -> str:
        with self.session_factory() as session:
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                raise LookupError(f"Jd revision not found: {revision_id}")
            return revision.source_text or ""

    async def split(self, text: str) -> list[str]:
        """Split a possibly multi-JD text blob into individual JD chunks."""
        return await self.parser.split_jds(text)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _direction_diagnostics(decision: DirectionDecision) -> dict:
    return build_direction_diagnostics(decision)
