from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.mail.ingest import MailIngestService
from kerui_recruit.mail.service import ImapProvider, MailAttachment, MailMessage, MailService
from kerui_recruit.storage.blobs import BlobStore


class FakeImap(ImapProvider):
    def __init__(self, messages: list[MailMessage] | None = None) -> None:
        self.messages = messages or []
        self.marked_read: list[int] = []
        self.connect_count = 0
        self.disconnect_count = 0

    def connect(self) -> None:
        self.connect_count += 1

    def disconnect(self) -> None:
        self.disconnect_count += 1

    def fetch_unread(self, last_uid: int) -> list[MailMessage]:
        return [m for m in self.messages if m.uid > last_uid]

    def mark_read(self, uid: int) -> None:
        self.marked_read.append(uid)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_sync_mailbox_fetches_and_updates_cursor(
    session_factory: sessionmaker[Session],
) -> None:
    fake = FakeImap(
        messages=[
            MailMessage(uid=1, subject="Java 工程师", sender="hr@test.com", body="简历", date="2026-01-01"),
            MailMessage(uid=2, subject="前端工程师", sender="hr@test.com", body="简历", date="2026-01-02"),
        ]
    )
    service = MailService(session_factory=session_factory, imap=fake)
    result = service.sync_mailbox("INBOX")
    assert len(result) == 2
    assert result[0].subject == "Java 工程师"
    assert result[1].subject == "前端工程师"
    assert fake.marked_read == [1, 2]

    # Second sync should fetch nothing (cursor advanced past uid=2)
    result2 = service.sync_mailbox("INBOX")
    assert len(result2) == 0


def test_sync_mailbox_with_subject_filter(
    session_factory: sessionmaker[Session],
) -> None:
    fake = FakeImap(
        messages=[
            MailMessage(uid=1, subject="Java 工程师", sender="hr@test.com", body="...", date="2026-01-01"),
            MailMessage(uid=2, subject="产品经理", sender="hr@test.com", body="...", date="2026-01-02"),
            MailMessage(uid=3, subject="Java 架构师", sender="hr@test.com", body="...", date="2026-01-03"),
        ]
    )
    service = MailService(session_factory=session_factory, imap=fake)
    result = service.sync_mailbox("INBOX", subject_filter="java")
    assert len(result) == 2
    assert all("Java" in m.subject for m in result)


def test_sync_mailbox_filters_by_sender_domain(
    session_factory: sessionmaker[Session],
) -> None:
    fake = FakeImap(
        messages=[
            MailMessage(uid=1, subject="Java", sender="hr@boss.com", body="...", date="2026-01-01"),
            MailMessage(uid=2, subject="Java", sender="hr@liepin.com", body="...", date="2026-01-02"),
            MailMessage(uid=3, subject="Java", sender="hr@other.com", body="...", date="2026-01-03"),
        ]
    )
    service = MailService(session_factory=session_factory, imap=fake)
    result = service.sync_mailbox("INBOX", sender_domains={"boss.com", "liepin.com"})
    assert len(result) == 2
    assert {m.uid for m in result} == {1, 2}


def test_mail_ingest_creates_revision_from_attachment(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    fake = FakeImap(
        messages=[
            MailMessage(
                uid=1,
                subject="简历",
                sender="hr@boss.com",
                body="附件简历",
                date="2026-01-01",
                attachments=(MailAttachment(filename="张三.pdf", content=b"%PDF-1.4 resume"),),
            )
        ]
    )
    mail_service = MailService(session_factory=session_factory, imap=fake)
    blob_store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    ingest = MailIngestService(
        session_factory=session_factory,
        blob_store=blob_store,
        mail_service=mail_service,
    )

    revisions = ingest.poll_and_ingest(sender_domains={"boss.com"})

    assert len(revisions) == 1
    assert revisions[0]
