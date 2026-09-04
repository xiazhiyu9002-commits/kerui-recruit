from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import MailCursor
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.mail.ingest import MailIngestService
from kerui_recruit.mail.service import ImapProvider, MailAttachment, MailMessage, MailService
from kerui_recruit.storage.blobs import BlobStore


class FakeImap(ImapProvider):
    def __init__(
        self,
        messages: list[MailMessage] | None = None,
        *,
        uidvalidity: int | None = None,
    ) -> None:
        self.messages = messages or []
        self.marked_read: list[int] = []
        self.connect_count = 0
        self.disconnect_count = 0
        self._uidvalidity = uidvalidity

    def connect(self) -> None:
        self.connect_count += 1

    def disconnect(self) -> None:
        self.disconnect_count += 1

    def fetch_unread(self, last_uid: int) -> list[MailMessage]:
        return [m for m in self.messages if m.uid > last_uid]

    def mark_read(self, uid: int) -> None:
        self.marked_read.append(uid)

    def uidvalidity(self) -> int | None:
        return self._uidvalidity


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


def test_sync_mailbox_resets_cursor_on_uidvalidity_change(
    session_factory: sessionmaker[Session],
) -> None:
    # 第一次同步：记录 uidvalidity=100，游标推进到 uid=2。
    first = FakeImap(
        messages=[
            MailMessage(uid=1, subject="简历A", sender="hr@test.com", body="...", date="2026-01-01"),
            MailMessage(uid=2, subject="简历B", sender="hr@test.com", body="...", date="2026-01-02"),
        ],
        uidvalidity=100,
    )
    service = MailService(session_factory=session_factory, imap=first)
    assert len(service.sync_mailbox("INBOX")) == 2

    # 第二次同步：服务商重排 UID（uidvalidity 变为 200，最大 UID 回退到 1）。
    # 旧游标 last_uid=2 会漏掉新邮件，必须检测变化后重置重新拉取。
    second = FakeImap(
        messages=[
            MailMessage(uid=1, subject="重排后简历", sender="hr@test.com", body="...", date="2026-01-03"),
        ],
        uidvalidity=200,
    )
    service2 = MailService(session_factory=session_factory, imap=second)
    result = service2.sync_mailbox("INBOX")
    assert [m.uid for m in result] == [1]


def test_sync_mailbox_resets_stale_cursor_without_stored_uidvalidity(
    session_factory: sessionmaker[Session],
) -> None:
    # 升级前的旧数据：last_uid 很大但无 uidvalidity，需保守重置避免漏拉。
    with session_factory() as session:
        session.add(MailCursor(mailbox="INBOX", last_uid=1099))
        session.commit()

    fake = FakeImap(
        messages=[
            MailMessage(uid=609, subject="简历", sender="hr@test.com", body="...", date="2026-01-01"),
        ],
        uidvalidity=300,
    )
    service = MailService(session_factory=session_factory, imap=fake)
    result = service.sync_mailbox("INBOX")
    assert [m.uid for m in result] == [609]


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


def test_sync_mailbox_filters_by_full_email_and_prefixed_domain(
    session_factory: sessionmaker[Session],
) -> None:
    fake = FakeImap(
        messages=[
            MailMessage(uid=1, subject="小号简历", sender="3504014884@qq.com", body="...", date="2026-01-01"),
            MailMessage(uid=2, subject="boss通知", sender="hr@notice.bosszhipin.com", body="...", date="2026-01-02"),
            MailMessage(uid=3, subject="其他QQ", sender="other@qq.com", body="...", date="2026-01-03"),
            MailMessage(uid=4, subject="其他", sender="x@y.com", body="...", date="2026-01-04"),
        ]
    )
    service = MailService(session_factory=session_factory, imap=fake)
    result = service.sync_mailbox("INBOX", sender_domains={"3504014884@qq.com", "@notice.bosszhipin.com"})
    assert {m.uid for m in result} == {1, 2}


def test_sync_mailbox_advances_cursor_past_non_whitelisted_mail(
    session_factory: sessionmaker[Session],
) -> None:
    # 非白名单邮件 UID 更大时，游标也应推进到它，避免每次轮询反复拉取。
    fake = FakeImap(
        messages=[
            MailMessage(uid=1, subject="白名单简历", sender="hr@boss.com", body="...", date="2026-01-01"),
            MailMessage(uid=2, subject="营销邮件", sender="spam@other.com", body="...", date="2026-01-02"),
        ]
    )
    service = MailService(session_factory=session_factory, imap=fake)
    result = service.sync_mailbox("INBOX", sender_domains={"boss.com"})

    # 只交付白名单邮件
    assert [m.uid for m in result] == [1]
    # 但两封都被标记已读（非白名单也被消费，避免重复拉取）
    assert fake.marked_read == [1, 2]

    # 第二次同步：游标已推进到 2，不再重复拉取非白名单邮件
    result2 = service.sync_mailbox("INBOX", sender_domains={"boss.com"})
    assert len(result2) == 0


def test_decode_filename_handles_rfc2047_resume_name() -> None:
    import base64

    from kerui_recruit.mail.imap_provider import _decode_filename

    encoded = "=?utf-8?B?" + base64.b64encode("简历.pdf".encode("utf-8")).decode() + "?="
    assert _decode_filename(encoded) == "简历.pdf"
    assert _decode_filename("plain.pdf") == "plain.pdf"
    assert _decode_filename(None) == ""


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
