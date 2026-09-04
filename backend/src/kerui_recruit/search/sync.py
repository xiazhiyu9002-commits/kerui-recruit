"""Durable index work is enqueued in the same transaction as business changes."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, select, update

from kerui_recruit.db.models import Candidate, IndexSyncRecord, Jd, JdRevision, ResumeDocument, ResumeRevision
from kerui_recruit.direction.models import parse_direction_profile
from kerui_recruit.search.contracts import SearchChunk


def _direction_fields(parsed_data: dict | None) -> dict:
    profile = parse_direction_profile((parsed_data or {}).get("direction_profile"))
    if profile.status == "UNKNOWN" or not profile.role_families:
        return {
            "primary_role_family": None,
            "role_family_codes": [],
            "direction_confidence": None,
            "direction_status": profile.status,
            "direction_source": None,
            "business_domain_codes": [],
            "leadership_code": None,
            "taxonomy_version": profile.taxonomy_version,
        }
    confidence = next((r.confidence for r in profile.role_families if r.is_primary), None)
    return {
        "primary_role_family": profile.primary_role_code,
        "role_family_codes": list(profile.all_role_codes),
        "direction_confidence": confidence,
        "direction_status": profile.status,
        "direction_source": profile.dominant_source,
        "business_domain_codes": [d.code for d in profile.business_domains],
        "leadership_code": profile.leadership.code if profile.leadership else None,
        "taxonomy_version": profile.taxonomy_version,
    }


def enqueue_sync(session: Session, entity_type: str, entity_id: str, mode: str = "FULL") -> None:
    if entity_type not in ("candidate", "jd"):
        raise ValueError("Unsupported index entity")
    if mode not in ("FULL", "METADATA"):
        raise ValueError("Unsupported sync mode")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 计算最终模式：FULL 总是 FULL；METADATA 只有在「不存在待处理 FULL」时才保持 METADATA。
    # 待处理判断必须用 requested_version > applied_version，不能只看 requested_mode。
    existing = session.scalar(select(IndexSyncRecord).where(
        IndexSyncRecord.entity_type == entity_type, IndexSyncRecord.entity_id == entity_id))
    final_mode = mode
    if mode == "METADATA" and existing is not None \
            and existing.requested_version > existing.applied_version \
            and existing.requested_mode == "FULL":
        final_mode = "FULL"
    stmt = insert(IndexSyncRecord).values(entity_type=entity_type, entity_id=entity_id,
        requested_mode=final_mode, requested_version=1, applied_version=0, status="PENDING", attempts=0)
    set_values: dict = {"requested_version": IndexSyncRecord.requested_version + 1,
                        "requested_mode": final_mode, "status": "PENDING",
                        "next_attempt_at": None, "last_error": None, "updated_at": now}
    session.execute(stmt.on_conflict_do_update(index_elements=["entity_type", "entity_id"],
        set_=set_values))


class IndexSyncService:
    """Coalesced, retryable projection with optimistic generation checks.

    Embedding runs outside the SQLite write lock. Publication checks the outbox
    generation under BEGIN IMMEDIATE so an older asynchronous completion cannot
    acknowledge or overwrite a newer committed business change.
    """

    def __init__(self, *, session_factory, index, embedding_provider, jd_index=None):
        self.session_factory = session_factory
        self.index = index
        self.embedding_provider = embedding_provider
        self.jd_index = jd_index
        self._run_lock = asyncio.Lock()

    async def run_once(self, *, batch_size: int = 25, force: bool = False,
                       entity_type: str | None = None, entity_id: str | None = None) -> int:
        async with self._run_lock:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with self.session_factory() as session:
                stmt = select(IndexSyncRecord).where(IndexSyncRecord.requested_version > IndexSyncRecord.applied_version)
                if entity_type is not None:
                    stmt = stmt.where(IndexSyncRecord.entity_type == entity_type)
                if entity_id is not None:
                    stmt = stmt.where(IndexSyncRecord.entity_id == entity_id)
                if not force:
                    stmt = stmt.where(or_(IndexSyncRecord.next_attempt_at.is_(None), IndexSyncRecord.next_attempt_at <= now))
                jobs = [(r.id, r.entity_type, r.entity_id, r.requested_version, r.requested_mode) for r in session.scalars(
                    stmt.order_by(IndexSyncRecord.updated_at, IndexSyncRecord.id).limit(batch_size))]
            completed = 0
            for job_id, kind, entity_id, generation, mode in jobs:
                try:
                    if mode == "METADATA":
                        applied = await asyncio.to_thread(self._publish_metadata, job_id, kind, entity_id, generation)
                        completed += int(applied)
                        continue
                    snapshot = await asyncio.to_thread(self._snapshot, kind, entity_id)
                    target = self.index if kind == "candidate" else self.jd_index
                    if target is None:
                        raise RuntimeError("Index consumer is not configured")
                    underlying = getattr(target, "index", target)
                    if snapshot is not None:
                        if hasattr(underlying, "is_compatible") and not underlying.is_compatible():
                            raise RuntimeError("Index version requires rebuild")
                        texts = snapshot["contents"]
                        cached = []
                        for revision_id in dict.fromkeys(snapshot["revision_ids"]):
                            cached.extend(await asyncio.to_thread(underlying.get_revision_chunks, revision_id))
                        by_content = {row["content"]: row["vector"] for row in cached}
                        missing = [text for text in texts if text not in by_content]
                        if missing:
                            vectors = await asyncio.wait_for(self.embedding_provider.embed_documents(missing), timeout=60)
                            if len(vectors) != len(missing):
                                raise ValueError("Embedding response count mismatch")
                            by_content.update(zip(missing, vectors))
                        snapshot["vectors"] = [by_content[text] for text in texts]
                    applied = await asyncio.to_thread(self._publish, job_id, kind, entity_id, generation, snapshot)
                    completed += int(applied)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    await asyncio.to_thread(self._failed, job_id, generation, error)
            return completed

    def _snapshot(self, kind, entity_id):
        with self.session_factory() as session:
            if kind == "candidate":
                candidate = session.get(Candidate, entity_id)
                if candidate is None or candidate.deleted_at is not None or candidate.status in ("ARCHIVED", "PENDING_REVIEW"):
                    return None
                revisions = list(session.scalars(select(ResumeRevision).join(ResumeDocument).where(
                    ResumeDocument.candidate_id == entity_id, ResumeRevision.is_current.is_(True),
                    ResumeRevision.status == "READY").order_by(ResumeRevision.created_at.desc(), ResumeRevision.id.desc())))
                if not revisions:
                    return None
                from kerui_recruit.resumes.pipeline import build_chunk_contents_from_dict
                contents, revision_ids, chunk_fields = [], [], []
                preferred = set()
                for revision in revisions:
                    data = dict(revision.parsed_data or {})
                    locations = data.get("preferred_locations") or data.get("preferred_location") or []
                    if isinstance(locations, str):
                        from kerui_recruit.search.query import parse_query
                        locations = parse_query("期望" + locations).filters.preferred_locations or (locations,)
                    preferred.update(locations)
                    for content in build_chunk_contents_from_dict(data):
                        if not content.strip():
                            continue
                        contents.append(content)
                        revision_ids.append(revision.id)
                        chunk_fields.append({"total_years": float(candidate.total_years) if candidate.total_years is not None else data.get("total_years"),
                            "highest_degree": candidate.highest_degree or data.get("highest_degree"),
                            "location": data.get("location"), "candidate_status": candidate.status,
                            "qs_rank": data.get("qs_rank"), "school_level": data.get("school_level")})
                if not contents:
                    return None
                direction = _direction_fields(dict(revisions[0].parsed_data or {}))
                for fields in chunk_fields:
                    fields["preferred_locations"] = tuple(sorted(preferred))
                    fields.update(direction)
                return {"revision_ids": revision_ids, "contents": contents, "chunk_fields": chunk_fields}
            jd = session.get(Jd, entity_id)
            if jd is None or jd.deleted_at is not None or jd.status != "OPEN":
                return None
            revision = session.scalar(select(JdRevision).where(JdRevision.jd_id == entity_id,
                JdRevision.is_current.is_(True), JdRevision.status == "READY")
                .order_by(JdRevision.created_at.desc()).limit(1))
            if revision is None:
                return None
            content = " ".join((jd.company, jd.title, revision.source_text or "",
                                json.dumps(revision.parsed_data or {}, ensure_ascii=False)))
            return {"revision_ids": [revision.id], "contents": [content], "fields": {
                "company": jd.company, "title": jd.title, "min_years": float(revision.min_years) if revision.min_years is not None else None,
                "highest_degree": revision.highest_degree, "location": revision.location,
                **_direction_fields(revision.parsed_data)}}

    def _publish(self, job_id, kind, entity_id, generation, snapshot):
        with self.session_factory() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                job = session.get(IndexSyncRecord, job_id)
                if job is None or job.requested_version != generation or job.applied_version >= generation:
                    session.rollback()
                    return False
                if kind == "candidate":
                    if snapshot is None:
                        self.index.delete_candidate(entity_id)
                    else:
                        chunks = [SearchChunk(id=f"{revision_id}:{i}", candidate_id=entity_id,
                            revision_id=revision_id, content=content, vector=tuple(vector), **fields)
                            for i, (revision_id, content, vector, fields) in enumerate(zip(snapshot["revision_ids"],
                                snapshot["contents"], snapshot["vectors"], snapshot["chunk_fields"]))]
                        self.index.replace_candidate(chunks)
                elif snapshot is None:
                    self.jd_index.delete_jd(entity_id)
                else:
                    self.jd_index.upsert(jd_id=entity_id, revision_id=snapshot["revision_ids"][0],
                        content=snapshot["contents"][0], vector=snapshot["vectors"][0], **snapshot["fields"])
                job.applied_version = generation
                job.status, job.last_error, job.next_attempt_at = "SYNCED", None, None
                session.commit()
                return True
            except BaseException:
                session.rollback()
                raise

    def _direction_snapshot(self, kind, entity_id):
        with self.session_factory() as session:
            if kind == "candidate":
                candidate = session.get(Candidate, entity_id)
                if candidate is None or candidate.deleted_at is not None or candidate.status in ("ARCHIVED", "PENDING_REVIEW"):
                    return None
                revision = session.scalar(select(ResumeRevision).join(ResumeDocument).where(
                    ResumeDocument.candidate_id == entity_id, ResumeRevision.is_current.is_(True),
                    ResumeRevision.status == "READY").order_by(ResumeRevision.created_at.desc()).limit(1))
                if revision is None:
                    return None
                return _direction_fields(revision.parsed_data)
            jd = session.get(Jd, entity_id)
            if jd is None or jd.deleted_at is not None or jd.status != "OPEN":
                return None
            revision = session.scalar(select(JdRevision).where(JdRevision.jd_id == entity_id,
                JdRevision.is_current.is_(True), JdRevision.status == "READY")
                .order_by(JdRevision.created_at.desc()).limit(1))
            if revision is None:
                return None
            return _direction_fields(revision.parsed_data)

    def _publish_metadata(self, job_id, kind, entity_id, generation):
        """METADATA 同步：只更新方向字段，保留 vector/content，不调用 embedding。"""
        with self.session_factory() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                job = session.get(IndexSyncRecord, job_id)
                if job is None or job.requested_version != generation or job.applied_version >= generation:
                    session.rollback()
                    return False
                fields = self._direction_snapshot(kind, entity_id)
                target = self.index if kind == "candidate" else self.jd_index
                underlying = getattr(target, "index", target)
                if fields is None:
                    # 业务实体已删除/归档/关闭/无 READY：删除可能存在的索引行并完成同步。
                    underlying.delete_candidate(entity_id)
                    job.applied_version = generation
                    job.status, job.last_error, job.next_attempt_at = "SYNCED", None, None
                    session.commit()
                    return True
                if not underlying.update_candidate_direction(entity_id, **fields):
                    # 索引行缺失但业务实体仍有效：升级为 FULL、恢复 PENDING，
                    # 不推进 applied_version，下次用同一实体做完整发布，避免假成功。
                    job.requested_mode = "FULL"
                    job.status = "PENDING"
                    job.last_error = None
                    job.next_attempt_at = None
                    session.commit()
                    return False
                job.applied_version = generation
                job.status, job.last_error, job.next_attempt_at = "SYNCED", None, None
                session.commit()
                return True
            except BaseException:
                session.rollback()
                raise

    def _failed(self, job_id, generation, error):
        with self.session_factory() as session, session.begin():
            job = session.get(IndexSyncRecord, job_id)
            if job is None or job.requested_version != generation:
                return
            job.attempts += 1
            job.status = "RETRY_WAIT"
            # No raw provider payload, resume text or credentials in diagnostics.
            job.last_error = type(error).__name__
            job.next_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=min(300, 2 ** min(job.attempts, 8)))

    def status(self):
        with self.session_factory() as session:
            pending = IndexSyncRecord.requested_version > IndexSyncRecord.applied_version
            total = session.scalar(select(func.count()).select_from(IndexSyncRecord).where(pending))
            failed = session.scalar(select(func.count()).select_from(IndexSyncRecord).where(pending, IndexSyncRecord.status == "RETRY_WAIT"))
            jobs = list(session.scalars(select(IndexSyncRecord).where(pending)
                .order_by(IndexSyncRecord.updated_at, IndexSyncRecord.id).limit(100)))
            indexes = []
            for kind, target in (("candidate", self.index), ("jd", self.jd_index)):
                underlying = getattr(target, "index", target)
                indexes.append({"entity_type": kind, "compatible": bool(underlying and underlying.is_compatible()),
                    "error": underlying.compatibility_error if underlying else "Index is not configured"})
            return {"pending": total, "failed": failed, "indexes": indexes,
                    "items": [{"entity_type": j.entity_type, "entity_id": j.entity_id,
                               "status": j.status, "attempts": j.attempts, "error": j.last_error} for j in jobs]}

    def retry_pending(self):
        with self.session_factory() as session, session.begin():
            session.execute(update(IndexSyncRecord).where(IndexSyncRecord.requested_version > IndexSyncRecord.applied_version)
                .values(status="PENDING", next_attempt_at=None, last_error=None))
        return self.status()

    async def run_forever(self, *, interval_seconds: float = 1.0):
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logging.getLogger(__name__).warning("Index sync cycle failed: %s", type(error).__name__)
            await asyncio.sleep(interval_seconds)
