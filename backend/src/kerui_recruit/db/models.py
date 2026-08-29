from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kerui_recruit.db.base import Base, IdMixin


class Candidate(IdMixin, Base):
    __tablename__ = "candidate"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_REVIEW','AVAILABLE','ON_HOLD','ARCHIVED')",
            name="ck_candidate_status",
        ),
        Index("ix_candidate_active", "deleted_at", "status"),
    )

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", nullable=False)
    total_years: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    highest_degree: Mapped[str | None] = mapped_column(String(32))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    documents: Mapped[list[ResumeDocument]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )


class ResumeDocument(IdMixin, Base):
    __tablename__ = "resume_document"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate: Mapped[Candidate] = relationship(back_populates="documents")
    revisions: Mapped[list[ResumeRevision]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class Blob(IdMixin, Base):
    __tablename__ = "blob"

    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    suffix: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    reference_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revisions: Mapped[list[ResumeRevision]] = relationship(back_populates="blob")


class ResumeRevision(IdMixin, Base):
    __tablename__ = "resume_revision"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','READY','FAILED')",
            name="ck_resume_revision_status",
        ),
        Index("ix_resume_revision_current", "document_id", "is_current"),
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey("resume_document.id", ondelete="CASCADE"),
        nullable=False,
    )
    blob_id: Mapped[str] = mapped_column(ForeignKey("blob.id"), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parse_version: Mapped[str | None] = mapped_column(String(100))
    document: Mapped[ResumeDocument] = relationship(back_populates="revisions")
    blob: Mapped[Blob] = relationship(back_populates="revisions")


class TaskRecord(IdMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','QUEUED','RUNNING','RETRY_WAIT','SUCCESS','FAILED','CANCELLED','DEAD_LETTER')",
            name="ck_task_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_task_idempotency_key"),
        Index("ix_task_claim", "status", "queue_name", "priority", "created_at"),
    )

    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(512))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    events: Mapped[list[TaskEvent]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskEvent(IdMixin, Base):
    __tablename__ = "task_event"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    task: Mapped[TaskRecord] = relationship(back_populates="events")


class Jd(IdMixin, Base):
    __tablename__ = "jd"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','OPEN','PAUSED','FILLED','CANCELLED','ARCHIVED')",
            name="ck_jd_status",
        ),
        Index("ix_jd_active", "deleted_at", "status"),
    )

    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revisions: Mapped[list[JdRevision]] = relationship(
        back_populates="jd",
        cascade="all, delete-orphan",
    )


class JdRevision(IdMixin, Base):
    __tablename__ = "jd_revision"
    __table_args__ = (
        CheckConstraint(
            "ai_category IN ('CORE_AI','AI_RELATED','NON_AI') OR ai_category IS NULL",
            name="ck_jd_revision_ai_category",
        ),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','READY','FAILED')",
            name="ck_jd_revision_status",
        ),
        Index("ix_jd_revision_current", "jd_id", "is_current"),
    )

    jd_id: Mapped[str] = mapped_column(
        ForeignKey("jd.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_text: Mapped[str | None] = mapped_column(Text)
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ai_category: Mapped[str | None] = mapped_column(String(24))
    highest_degree: Mapped[str | None] = mapped_column(String(32))
    min_years: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    location: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    jd: Mapped[Jd] = relationship(back_populates="revisions")
    requirements: Mapped[list[JdRequirement]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
    )


class JdRequirement(IdMixin, Base):
    __tablename__ = "jd_requirement"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('MUST','PLUS','EXCLUDE')",
            name="ck_jd_requirement_kind",
        ),
    )

    revision_id: Mapped[str] = mapped_column(
        ForeignKey("jd_revision.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    revision: Mapped[JdRevision] = relationship(back_populates="requirements")


class CandidateJobCase(IdMixin, Base):
    __tablename__ = "candidate_job_case"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('待评估','待联系','已联系','有意向','已推荐','初试','复试','终试','Offer','入职','客户拒绝','候选人拒绝','暂缓','岗位关闭')",
            name="ck_case_stage",
        ),
        Index("ix_case_candidate", "candidate_id"),
        Index("ix_case_jd", "jd_id"),
    )

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"),
        nullable=False,
    )
    jd_id: Mapped[str] = mapped_column(
        ForeignKey("jd.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(24), default="待评估", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    candidate: Mapped[Candidate] = relationship()
    jd: Mapped[Jd] = relationship()
    events: Mapped[list[StageEvent]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )


class StageEvent(IdMixin, Base):
    __tablename__ = "stage_event"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('待评估','待联系','已联系','有意向','已推荐','初试','复试','终试','Offer','入职','客户拒绝','候选人拒绝','暂缓','岗位关闭')",
            name="ck_stage_event_stage",
        ),
    )

    case_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_job_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    case: Mapped[CandidateJobCase] = relationship(back_populates="events")


class MatchRun(IdMixin, Base):
    __tablename__ = "match_run"

    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    jd_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("jd_revision.id", ondelete="SET NULL"),
        index=True,
    )
    query_text: Mapped[str | None] = mapped_column(Text)
    index_generation: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    results: Mapped[list[MatchResult]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class MatchResult(IdMixin, Base):
    __tablename__ = "match_result"
    __table_args__ = (
        CheckConstraint(
            "status IN ('未处理','保留','短名单','排除')",
            name="ck_match_result_status",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("match_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_job_case.id", ondelete="SET NULL")
    )
    resume_revision_id: Mapped[str | None] = mapped_column(String(36))
    jd_revision_id: Mapped[str | None] = mapped_column(String(36))
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="未处理", nullable=False)
    run: Mapped[MatchRun] = relationship(back_populates="results")


class CorrectionLog(IdMixin, Base):
    __tablename__ = "correction_log"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    reverted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MappingProject(IdMixin, Base):
    __tablename__ = "mapping_project"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    snapshots: Mapped[list[MappingSnapshot]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class MappingSnapshot(IdMixin, Base):
    __tablename__ = "mapping_snapshot"
    __table_args__ = (
        Index("ix_mapping_snapshot_current", "project_id", "is_current"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("mapping_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    project: Mapped[MappingProject] = relationship(back_populates="snapshots")
    nodes: Mapped[list[MappingNode]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class MappingNode(IdMixin, Base):
    __tablename__ = "mapping_node"

    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("mapping_snapshot.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("mapping_node.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    snapshot: Mapped[MappingSnapshot] = relationship(back_populates="nodes")
    children: Mapped[list[MappingNode]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys=[parent_id],
    )
    parent: Mapped[MappingNode | None] = relationship(
        back_populates="children",
        remote_side="MappingNode.id",
    )


class MailCursor(IdMixin, Base):
    __tablename__ = "mail_cursor"

    mailbox: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    last_uid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Reminder(IdMixin, Base):
    __tablename__ = "reminder"
    __table_args__ = (
        Index("ix_reminder_due", "remind_at", "dismissed"),
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BdLead(IdMixin, Base):
    __tablename__ = "bd_lead"
    __table_args__ = (
        CheckConstraint(
            "status IN ('新线索','已联系','已定级','已存档')",
            name="ck_bd_lead_status",
        ),
        Index("ix_bd_lead_status", "status"),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str | None] = mapped_column(String(500), index=True)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(500))
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    raw_snippet: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="新线索", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
