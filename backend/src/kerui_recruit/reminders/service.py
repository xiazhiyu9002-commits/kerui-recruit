from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import Reminder


class ReminderService:
    """Create, list, and dismiss reminders."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(
        self,
        *,
        title: str,
        remind_at: datetime,
        note: str | None = None,
    ) -> Reminder:
        with self.session_factory() as session:
            reminder = Reminder(title=title, remind_at=remind_at, note=note)
            session.add(reminder)
            session.commit()
            return reminder

    def list_pending(self) -> list[Reminder]:
        with self.session_factory() as session:
            return (
                session.scalars(
                    select(Reminder)
                    .where(Reminder.dismissed == False)
                    .order_by(Reminder.remind_at.asc())
                )
                .all()
            )

    def list_due(self) -> list[Reminder]:
        """Reminders whose remind_at is in the past and not dismissed."""
        with self.session_factory() as session:
            return (
                session.scalars(
                    select(Reminder)
                    .where(
                        Reminder.dismissed == False,
                        Reminder.remind_at <= datetime.now(timezone.utc),
                    )
                    .order_by(Reminder.remind_at.asc())
                )
                .all()
            )

    def dismiss(self, reminder_id: str) -> Reminder:
        with self.session_factory() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                raise LookupError(f"Reminder not found: {reminder_id}")
            reminder.dismissed = True
            reminder.dismissed_at = datetime.now(timezone.utc)
            session.commit()
            return reminder