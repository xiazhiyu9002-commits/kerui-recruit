from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.backup.service import BackupService
from kerui_recruit.db.models import Candidate, CandidateJobCase, Jd, JdRevision
from kerui_recruit.mail.ingest import MailIngestService
from kerui_recruit.match.service import MatchService
from kerui_recruit.reminders.mail_service import ReminderMailService
from kerui_recruit.reminders.service import ReminderService
from kerui_recruit.soft_delete.service import SoftDeleteService


@dataclass(frozen=True, slots=True)
class ReverseMatch:
    jd_id: str
    revision_id: str
    company: str
    title: str
    score: float


class SchedulerService:
    """Background automation: reverse matching, reminder checks and mail polling.

    Runs a lightweight periodic loop (no external scheduler dependency) that
    reverse-matches freshly available candidates against open JDs, surfaces due
    reminders and ingests resumes from the agent mailbox. Individual jobs never
    crash the loop.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        match_service: MatchService | None,
        reminder_service: ReminderService | None,
        mail_ingest_service: MailIngestService | None = None,
        reminder_mail_service: ReminderMailService | None = None,
        backup_service: BackupService | None = None,
        soft_delete_service: SoftDeleteService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.match_service = match_service
        self.reminder_service = reminder_service
        self.mail_ingest_service = mail_ingest_service
        self.reminder_mail_service = reminder_mail_service
        self.backup_service = backup_service
        self.soft_delete_service = soft_delete_service

    async def reverse_match_candidate(
        self, candidate_id: str, *, limit: int = 20
    ) -> list[ReverseMatch]:
        if self.match_service is None:
            return []

        with self.session_factory() as session:
            rows = session.execute(
                select(JdRevision, Jd.company, Jd.title)
                .join(Jd, Jd.id == JdRevision.jd_id)
                .where(
                    Jd.status == "OPEN",
                    Jd.deleted_at.is_(None),
                    JdRevision.is_current.is_(True),
                )
            ).all()

        matches: list[ReverseMatch] = []
        for revision, company, title in rows:
            page = await self.match_service.match_jd(
                revision_id=revision.id,
                limit=limit,
            )
            for hit in page.items:
                if hit.candidate_id == candidate_id:
                    matches.append(
                        ReverseMatch(
                            jd_id=revision.jd_id,
                            revision_id=revision.id,
                            company=company,
                            title=title,
                            score=hit.score,
                        )
                    )
                    break
        return sorted(matches, key=lambda m: m.score, reverse=True)

    async def reverse_match_available(self) -> dict[str, list[ReverseMatch]]:
        """Reverse-match AVAILABLE candidates that have no open case yet."""
        with self.session_factory() as session:
            candidates = session.scalars(
                select(Candidate).where(
                    Candidate.status == "AVAILABLE",
                    Candidate.deleted_at.is_(None),
                )
            ).all()
            cased_candidate_ids = set(
                session.scalars(
                    select(CandidateJobCase.candidate_id).where(
                        CandidateJobCase.deleted_at.is_(None)
                    )
                ).all()
            )

        results: dict[str, list[ReverseMatch]] = {}
        for candidate in candidates:
            if candidate.id in cased_candidate_ids:
                continue
            matches = await self.reverse_match_candidate(candidate.id)
            if matches:
                results[candidate.id] = matches
        return results

    def due_reminders(self) -> list:
        if self.reminder_service is None:
            return []
        return self.reminder_service.list_due()

    def poll_mail(self) -> list[str]:
        """Ingest resumes from the agent mailbox. Returns new revision ids."""
        if self.mail_ingest_service is None:
            return []
        return self.mail_ingest_service.poll_and_ingest()

    def send_reminder_mail(self) -> list[str]:
        """Send due reminders as email. Returns sent reminder ids."""
        if self.reminder_mail_service is None:
            return []
        return self.reminder_mail_service.send_due_reminders()

    def backup_tick(self) -> None:
        """Create a daily snapshot (once per UTC day) and apply retention."""
        if self.backup_service is None:
            return
        today = datetime.now(timezone.utc).date()
        has_today = any(
            datetime.fromtimestamp(
                snapshot.stat().st_mtime, tz=timezone.utc
            ).date() == today
            for snapshot in self.backup_service.backup_dir.glob("backup_*.sqlite3")
        )
        if not has_today:
            self.backup_service.create_snapshot(label="daily")
        self.backup_service.prune()

    def purge_recycle_bin(self) -> None:
        """Permanently remove recycle-bin items older than the retention window."""
        if self.soft_delete_service is None:
            return
        self.soft_delete_service.purge_expired()

    async def run_forever(self, *, interval_seconds: int = 300) -> None:
        while True:
            try:
                await self.reverse_match_available()
            except Exception:
                # A single failed tick must not stop background automation.
                pass
            try:
                self.poll_mail()
            except Exception:
                pass
            try:
                self.send_reminder_mail()
            except Exception:
                pass
            try:
                self.backup_tick()
            except Exception:
                pass
            try:
                self.purge_recycle_bin()
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)
