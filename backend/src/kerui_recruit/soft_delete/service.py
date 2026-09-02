from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from kerui_recruit.cases.state import refresh_links
from kerui_recruit.search.sync import enqueue_sync


class SoftDeleteService:
    """Soft-delete, restore and expiry purge for Candidate and JD entities."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def soft_delete(self, entity_type: str, entity_id: str) -> None:
        with self.session_factory() as session:
            entity = _lookup(session, entity_type, entity_id)
            entity.deleted_at = datetime.now(timezone.utc)
            enqueue_sync(session, entity_type, entity_id)
            refresh_links(session, **{f"{entity_type}_id": entity_id})
            session.commit()

    def restore(self, entity_type: str, entity_id: str) -> None:
        with self.session_factory() as session:
            entity = _lookup(session, entity_type, entity_id)
            entity.deleted_at = None
            enqueue_sync(session, entity_type, entity_id)
            refresh_links(session, **{f"{entity_type}_id": entity_id})
            session.commit()

    def is_deleted(self, entity_type: str, entity_id: str) -> bool:
        with self.session_factory() as session:
            entity = _lookup(session, entity_type, entity_id)
            return entity.deleted_at is not None

    def list_deleted(self) -> list[dict]:
        """List soft-deleted candidates and JDs for the recycle bin."""
        from kerui_recruit.db.models import Candidate, Jd

        with self.session_factory() as session:
            candidates = session.scalars(
                select(Candidate).where(Candidate.deleted_at.is_not(None))
            ).all()
            jds = session.scalars(
                select(Jd).where(Jd.deleted_at.is_not(None))
            ).all()

        items: list[dict] = []
        for candidate in candidates:
            items.append(
                {
                    "entity_type": "candidate",
                    "entity_id": candidate.id,
                    "label": candidate.display_name,
                    "deleted_at": candidate.deleted_at.isoformat() if candidate.deleted_at else None,
                }
            )
        for jd in jds:
            items.append(
                {
                    "entity_type": "jd",
                    "entity_id": jd.id,
                    "label": f"{jd.company} - {jd.title}",
                    "deleted_at": jd.deleted_at.isoformat() if jd.deleted_at else None,
                }
            )
        return items

    def purge_expired(self, *, retention_days: int = 30) -> int:
        """Permanently delete soft-deleted entities older than the retention."""
        from kerui_recruit.db.models import Candidate, Jd

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        removed = 0
        with self.session_factory() as session, session.begin():
            jds = session.scalars(
                select(Jd).where(Jd.deleted_at.is_not(None), Jd.deleted_at < cutoff)
            ).all()
            for jd in jds:
                enqueue_sync(session, "jd", jd.id)
                session.delete(jd)
                removed += 1

            candidates = session.scalars(
                select(Candidate).where(
                    Candidate.deleted_at.is_not(None),
                    Candidate.deleted_at < cutoff,
                )
            ).all()
            for candidate in candidates:
                enqueue_sync(session, "candidate", candidate.id)
                for document in candidate.documents:
                    for revision in document.revisions:
                        blob = revision.blob
                        if blob is not None:
                            blob.reference_count -= 1
                            if blob.reference_count <= 0:
                                session.delete(blob)
                session.delete(candidate)
                removed += 1
        return removed


def _lookup(session: Session, entity_type: str, entity_id: str) -> Any:
    from kerui_recruit.db.models import Candidate, Jd

    cls_map: dict[str, type] = {
        "candidate": Candidate,
        "jd": Jd,
    }
    cls = cls_map.get(entity_type)
    if cls is None:
        raise ValueError(f"Unsupported entity type for soft-delete: {entity_type}")
    entity = session.get(cls, entity_id)
    if entity is None:
        raise LookupError(f"{entity_type} not found: {entity_id}")
    return entity
