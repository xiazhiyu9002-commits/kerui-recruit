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

    def uidvalidity(self) -> int | None: ...


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
            last_uid = cursor.last_uid
            stored_uidvalidity = cursor.uidvalidity

        current_uidvalidity: int | None = None
        self.imap.connect()
        try:
            current_uidvalidity = self.imap.uidvalidity()
            # UIDVALIDITY 变化或首次缺失（旧游标）时，UID 可能已被服务商重排，
            # 旧的 last_uid 不再可信，重置后重新拉取整箱。
            if current_uidvalidity is not None and stored_uidvalidity != current_uidvalidity:
                last_uid = 0
            messages = self.imap.fetch_unread(last_uid)
        finally:
            self.imap.disconnect()

        if subject_filter:
            pattern = subject_filter.lower()
            messages = [m for m in messages if pattern in m.subject.lower()]

        if sender_domains:
            allowed = {d.strip().lstrip("@").lower() for d in sender_domains}
            messages = [
                m for m in messages if _matches_sender(m.sender, allowed)
            ]

        with self.session_factory() as session:
            cursor = session.query(MailCursor).filter_by(mailbox=mailbox).one()
            if current_uidvalidity is not None:
                cursor.uidvalidity = current_uidvalidity
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
_FULL_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+")


def _sender_domain(sender: str) -> str:
    match = _EMAIL_RE.search(sender)
    return match.group(1).lower() if match else ""


def _sender_email(sender: str) -> str:
    match = _FULL_EMAIL_RE.search(sender)
    return match.group(0).lower() if match else ""


def _matches_sender(sender: str, allowed: set[str]) -> bool:
    """白名单可同时接受完整邮箱地址或发件域名。"""
    return _sender_email(sender) in allowed or _sender_domain(sender) in allowed
