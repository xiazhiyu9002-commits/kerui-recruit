from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.mail.resume_gate import ResumeGate
from kerui_recruit.mail.service import MailService
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.storage.blobs import BlobStore


class MailIngestService:
    """Pull resumes from the agent mailbox and feed them into the ingest pipeline."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        blob_store: BlobStore,
        mail_service: MailService | None,
    ) -> None:
        self.session_factory = session_factory
        self.blob_store = blob_store
        self.mail_service = mail_service

    def poll_and_ingest(
        self,
        *,
        mailbox: str = "INBOX",
        sender_domains: set[str] | None = None,
        resume_gate: ResumeGate | None = None,
    ) -> list[str]:
        """Fetch unread mail and ingest its resume attachments. Returns revision ids."""
        if self.mail_service is None:
            return []

        messages = self.mail_service.sync_mailbox(
            mailbox,
            sender_domains=sender_domains,
        )

        ingested: list[str] = []
        for message in messages:
            if resume_gate is not None:
                filenames = [attachment.filename for attachment in message.attachments]
                try:
                    if not resume_gate.is_resume(
                        subject=message.subject,
                        body=message.body,
                        attachment_filenames=filenames,
                    ):
                        continue
                except Exception:
                    # 大模型判断失败时不阻断入库，回退到按附件后缀处理。
                    pass
            for attachment in message.attachments:
                with self.session_factory() as session:
                    result = ResumeIngestService(session, self.blob_store).ingest(
                        IngestResume(filename=attachment.filename, content=attachment.content)
                    )
                    ingested.append(result.revision_id)
        return ingested
