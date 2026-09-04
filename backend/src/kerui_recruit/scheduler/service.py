from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.backup.service import BackupService
from kerui_recruit.mail.ingest import MailIngestService
from kerui_recruit.mail.resume_gate import ResumeGate
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
    """Background automation: reminder checks and mail polling.

    Runs a lightweight periodic loop (no external scheduler dependency) that
    surfaces due reminders and ingests resumes from the agent mailbox. Passive
    matching is triggered on ingest instead of by this loop. Individual jobs
    never crash the loop.
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
        sender_domains: set[str] | None = None,
        resume_gate: ResumeGate | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.match_service = match_service
        self.reminder_service = reminder_service
        self.mail_ingest_service = mail_ingest_service
        self.reminder_mail_service = reminder_mail_service
        self.backup_service = backup_service
        self.soft_delete_service = soft_delete_service
        self.sender_domains = sender_domains
        self.resume_gate = resume_gate

    async def reverse_match_candidate(
        self, candidate_id: str, *, limit: int = 20
    ) -> list[ReverseMatch]:
        if self.match_service is None:
            return []
        records = await self.match_service.reverse_match_candidate(
            candidate_id, limit=limit
        )
        return [
            ReverseMatch(
                jd_id=record.jd_id,
                revision_id=record.revision_id,
                company=record.company,
                title=record.title,
                score=(record.score.total if record.score is not None
                       else self.match_service.score(record.revision_id, record.hit).total),
            )
            for record in records
        ]

    def due_reminders(self) -> list:
        if self.reminder_service is None:
            return []
        return self.reminder_service.list_due()

    def poll_mail(self) -> list[str]:
        """Ingest resumes from the agent mailbox. Returns new revision ids."""
        if self.mail_ingest_service is None:
            return []
        return self.mail_ingest_service.poll_and_ingest(
            sender_domains=self.sender_domains,
            resume_gate=self.resume_gate,
        )

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
            for name, operation in (
                ("mail_ingest", self.poll_mail),
                ("reminder_mail", self.send_reminder_mail),
                ("backup", self.backup_tick),
                ("recycle_bin", self.purge_recycle_bin),
            ):
                try:
                    # IMAP/SMTP, SQLite backup and filesystem deletion are all
                    # blocking integrations. Keep them off FastAPI's event loop.
                    await asyncio.to_thread(operation)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Scheduler job %s failed: %s", name, type(error).__name__
                    )
            await asyncio.sleep(interval_seconds)
