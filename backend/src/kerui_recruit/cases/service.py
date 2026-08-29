from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import CandidateJobCase, StageEvent


STAGES = (
    "待评估",
    "待联系",
    "已联系",
    "有意向",
    "已推荐",
    "初试",
    "复试",
    "终试",
    "Offer",
    "入职",
    "客户拒绝",
    "候选人拒绝",
    "暂缓",
    "岗位关闭",
)


class CaseService:
    """Manage the candidate-JD recruitment pipeline.

    A case is the stable entity that carries a candidate through the funnel.
    Every stage change appends an immutable :class:`StageEvent`.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, *, candidate_id: str, jd_id: str, note: str | None = None) -> CandidateJobCase:
        with self.session_factory() as session:
            existing = session.scalars(
                select(CandidateJobCase).where(
                    CandidateJobCase.candidate_id == candidate_id,
                    CandidateJobCase.jd_id == jd_id,
                    CandidateJobCase.deleted_at.is_(None),
                )
            ).one_or_none()
            if existing is not None:
                return existing

            case = CandidateJobCase(
                candidate_id=candidate_id,
                jd_id=jd_id,
                stage="待评估",
                note=note,
            )
            session.add(case)
            session.commit()
            return case

    def advance(
        self,
        case_id: str,
        *,
        stage: str,
        note: str | None = None,
    ) -> CandidateJobCase:
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")

        with self.session_factory() as session:
            case = session.get(CandidateJobCase, case_id)
            if case is None:
                raise LookupError(f"Case not found: {case_id}")

            case.stage = stage
            if note is not None:
                case.note = note
            session.add(StageEvent(case_id=case_id, stage=stage, note=note))
            session.commit()
            return case

    def undo(self, case_id: str) -> CandidateJobCase:
        """Roll back the most recent stage change."""
        with self.session_factory() as session:
            case = session.get(CandidateJobCase, case_id)
            if case is None:
                raise LookupError(f"Case not found: {case_id}")

            events = session.scalars(
                select(StageEvent)
                .where(StageEvent.case_id == case_id)
                .order_by(StageEvent.created_at.asc(), StageEvent.id.asc())
            ).all()

            if not events:
                return case

            latest = events[-1]
            session.delete(latest)
            case.stage = events[-2].stage if len(events) > 1 else "待评估"
            session.commit()
            return case

    def list_cases(
        self,
        *,
        candidate_id: str | None = None,
        jd_id: str | None = None,
    ) -> list[CandidateJobCase]:
        with self.session_factory() as session:
            stmt = select(CandidateJobCase).where(CandidateJobCase.deleted_at.is_(None))
            if candidate_id is not None:
                stmt = stmt.where(CandidateJobCase.candidate_id == candidate_id)
            if jd_id is not None:
                stmt = stmt.where(CandidateJobCase.jd_id == jd_id)
            return list(session.scalars(stmt.order_by(CandidateJobCase.created_at.desc())).all())

    def get_events(self, case_id: str) -> list[StageEvent]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(StageEvent)
                    .where(StageEvent.case_id == case_id)
                    .order_by(StageEvent.created_at.asc())
                ).all()
            )
