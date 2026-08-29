from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import MailCursor


@dataclass(frozen=True, slots=True)
class MailAttachment:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class MailMessage:
    uid: int
    subject: str
    sender: str
    body: str
    date: str
    attachments: tuple[MailAttachment, ...] = ()


class ImapProvider(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def fetch_unread(self, last_uid: int) -> list[MailMessage]: ...

    def mark_read(self, uid: int) -> None: ...


class MailService:
    """Idempotent IMAP email fetcher with cursor tracking."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        imap: ImapProvider,
    ) -> None:
        self.session_factory = session_factory
        self.imap = imap

    def sync_mailbox(
        self,
        mailbox: str,
        *,
        subject_filter: str | None = None,
        sender_domains: set[str] | None = None,
    ) -> list[MailMessage]:
        with self.session_factory() as session:
            cursor = session.query(MailCursor).filter_by(mailbox=mailbox).one_or_none()
            if cursor is None:
                cursor = MailCursor(mailbox=mailbox, last_uid=0)
                session.add(cursor)
                session.commit()

        self.imap.connect()
        try:
            messages = self.imap.fetch_unread(cursor.last_uid)
        finally:
            self.imap.disconnect()

        if subject_filter:
            pattern = subject_filter.lower()
            messages = [m for m in messages if pattern in m.subject.lower()]

        if sender_domains:
            messages = [
                m for m in messages if _sender_domain(m.sender) in sender_domains
            ]

        with self.session_factory() as session:
            cursor = session.query(MailCursor).filter_by(mailbox=mailbox).one()
            for msg in messages:
                self.imap.connect()
                try:
                    self.imap.mark_read(msg.uid)
                finally:
                    self.imap.disconnect()
                if msg.uid > cursor.last_uid:
                    cursor.last_uid = msg.uid
            session.commit()

        return messages

    def reset_cursor(self, mailbox: str) -> None:
        with self.session_factory() as session:
            cursor = session.query(MailCursor).filter_by(mailbox=mailbox).one_or_none()
            if cursor is not None:
                cursor.last_uid = 0
                session.commit()


_EMAIL_RE = re.compile(r"[\w.+-]+@([\w.-]+)")


def _sender_domain(sender: str) -> str:
    match = _EMAIL_RE.search(sender)
    return match.group(1).lower() if match else ""
