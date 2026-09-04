from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.message import Message
from typing import Iterable

from kerui_recruit.mail.service import ImapProvider, MailAttachment, MailMessage

_RESUME_SUFFIXES = (".pdf", ".doc", ".docx")


class ImapLibProvider(ImapProvider):
    """Real IMAP provider backed by the standard library ``imaplib``.

    Fetches unread messages and their resume attachments. The cursor key is the
    server UID so reconnects do not drop or duplicate messages.
    """

    def __init__(
        self,
        *,
        host: str,
        account: str,
        password: str,
        port: int = 993,
        ssl: bool = True,
        mailbox: str = "INBOX",
    ) -> None:
        self.host = host
        self.account = account
        self.password = password
        self.port = port
        self.ssl = ssl
        self.mailbox = mailbox
        self._client: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        if self.ssl:
            self._client = imaplib.IMAP4_SSL(self.host, self.port)
        else:
            self._client = imaplib.IMAP4(self.host, self.port)
        self._client.login(self.account, self.password)
        self._client.select(self.mailbox)

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None

    def fetch_unread(self, last_uid: int) -> list[MailMessage]:
        assert self._client is not None
        _, data = self._client.uid("search", None, f"UID {last_uid + 1}:*")
        uids = data[0].split() if data and data[0] else []
        messages: list[MailMessage] = []
        for uid in uids:
            _, msg_data = self._client.uid("fetch", uid, "(RFC822)")
            raw = _first_bytes(msg_data)
            if raw is None:
                continue
            messages.append(_parse_message(int(uid), raw))
        return messages

    def mark_read(self, uid: int) -> None:
        assert self._client is not None
        self._client.uid("store", str(uid).encode(), "+FLAGS", r"(\Seen)")

    def uidvalidity(self) -> int | None:
        """Return the mailbox UIDVALIDITY, or None when the server omits it.

        Some providers (e.g. QQ Mail) renumber UIDs after deletion; the
        UIDVALIDITY token changes then, letting callers detect stale cursors.
        """
        assert self._client is not None
        for item in self._client.response("UIDVALIDITY") or ():
            text = item.decode("utf-8", "replace") if isinstance(item, bytes) else str(item)
            match = re.search(r"UIDVALIDITY\s+(\d+)", text)
            if match:
                return int(match.group(1))
        return None


def _first_bytes(data: Iterable[object]) -> bytes | None:
    for part in data:
        if isinstance(part, tuple):
            payload = part[1]
            if isinstance(payload, bytes):
                return payload
            if isinstance(payload, str):
                return payload.encode("utf-8", "replace")
    return None


def _parse_message(uid: int, raw: bytes) -> MailMessage:
    msg = email.message_from_bytes(raw)
    subject = str(msg.get("Subject", ""))
    sender = str(msg.get("From", ""))
    date = str(msg.get("Date", ""))
    attachments: list[MailAttachment] = []

    body_parts: list[str] = []
    for part in msg.walk():
        content_disposition = part.get_content_disposition()
        filename = _decode_filename(part.get_filename())
        if filename and _is_resume(filename):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                attachments.append(MailAttachment(filename=filename, content=payload))
        elif part.get_content_type() == "text/plain" and content_disposition != "attachment":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                body_parts.append(payload.decode("utf-8", "replace"))

    return MailMessage(
        uid=uid,
        subject=subject,
        sender=sender,
        body="\n".join(body_parts),
        date=date,
        attachments=tuple(attachments),
    )


def _decode_filename(filename: str | None) -> str:
    """解码 RFC 2047 编码的中文附件名（QQ 邮箱常把文件名编码成 =?utf-8?B?...?=）。"""
    if not filename:
        return ""
    try:
        return str(make_header(decode_header(filename)))
    except Exception:
        return filename


def _is_resume(filename: str) -> bool:
    return filename.lower().endswith(_RESUME_SUFFIXES)
