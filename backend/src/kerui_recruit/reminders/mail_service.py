from __future__ import annotations

from kerui_recruit.mail.sender import MailSender
from kerui_recruit.reminders.service import ReminderService


class ReminderMailService:
    """Send due reminders as email and dismiss them."""

    def __init__(
        self,
        *,
        reminder_service: ReminderService,
        mail_sender: MailSender | None,
        to: str | None,
    ) -> None:
        self.reminder_service = reminder_service
        self.mail_sender = mail_sender
        self.to = to

    def send_due_reminders(self) -> list[str]:
        """Send all due reminders and dismiss them. Returns sent reminder ids."""
        if self.mail_sender is None or not self.to:
            return []

        due = self.reminder_service.list_due()
        sent: list[str] = []
        for reminder in due:
            self.mail_sender.send(
                to=self.to,
                subject=reminder.title,
                body=reminder.note or reminder.title,
            )
            self.reminder_service.dismiss(reminder.id)
            sent.append(reminder.id)
        return sent
