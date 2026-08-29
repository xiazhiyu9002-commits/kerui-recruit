from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import Candidate, CandidateJobCase, Jd, ResumeRevision


# Stages that count as "已经推荐出去"（过了「已推荐」门槛）。
_RECOMMENDED_STAGES = ("已推荐", "初试", "复试", "终试", "Offer", "入职")


class DashboardService:
    """Aggregate recruitment metrics for the dashboard.

    Metrics are derived from the candidate-JD relationship (cases), not from
    a candidate's global status, per the design spec.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def overview(self) -> dict:
        with self.session_factory() as session:
            # Funnel: count cases per stage.
            stage_rows = session.execute(
                select(CandidateJobCase.stage, func.count())
                .where(CandidateJobCase.deleted_at.is_(None))
                .group_by(CandidateJobCase.stage)
            ).all()
            funnel = [{"stage": stage, "count": count} for stage, count in stage_rows]

            recommendation_total = sum(
                count for stage, count in stage_rows if stage in _RECOMMENDED_STAGES
            )

            # Talent-pool health.
            candidate_total = session.scalar(
                select(func.count()).select_from(Candidate).where(Candidate.deleted_at.is_(None))
            )
            ready_total = session.scalar(
                select(func.count()).select_from(ResumeRevision).where(ResumeRevision.status == "READY")
            )
            parse_failed = session.scalar(
                select(func.count()).select_from(ResumeRevision).where(ResumeRevision.status == "FAILED")
            )
            recent_30d = session.scalar(
                select(func.count())
                .select_from(Candidate)
                .where(
                    Candidate.deleted_at.is_(None),
                    Candidate.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
                )
            )
            open_jd_total = session.scalar(
                select(func.count())
                .select_from(Jd)
                .where(Jd.deleted_at.is_(None), Jd.status == "OPEN")
            )

            return {
                "recommendation_total": recommendation_total,
                "funnel": funnel,
                "health": {
                    "candidate_total": candidate_total or 0,
                    "ready_total": ready_total or 0,
                    "parse_failed": parse_failed or 0,
                    "recent_30d": recent_30d or 0,
                    "open_jd_total": open_jd_total or 0,
                },
            }

    def by_jd(self) -> list[dict]:
        """Per-JD stage counts for the funnel drill-down."""
        with self.session_factory() as session:
            rows = session.execute(
                select(CandidateJobCase.jd_id, CandidateJobCase.stage, func.count())
                .where(CandidateJobCase.deleted_at.is_(None))
                .group_by(CandidateJobCase.jd_id, CandidateJobCase.stage)
            ).all()

            jds = {
                jd.id: jd
                for jd in session.scalars(select(Jd).where(Jd.deleted_at.is_(None))).all()
            }

            grouped: dict[str, dict] = {}
            for jd_id, stage, count in rows:
                jd = jds.get(jd_id)
                bucket = grouped.setdefault(
                    jd_id,
                    {
                        "jd_id": jd_id,
                        "company": jd.company if jd else "",
                        "title": jd.title if jd else "",
                        "stage_counts": {},
                    },
                )
                bucket["stage_counts"][stage] = count

            return list(grouped.values())
