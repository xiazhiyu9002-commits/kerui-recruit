from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker


class SoftDeleteService:
    """Soft-delete and restore for Candidate and JD entities."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def soft_delete(self, entity_type: str, entity_id: str) -> None:
        with self.session_factory() as session:
            entity = _lookup(session, entity_type, entity_id)
            entity.deleted_at = datetime.now(timezone.utc)
            session.commit()

    def restore(self, entity_type: str, entity_id: str) -> None:
        with self.session_factory() as session:
            entity = _lookup(session, entity_type, entity_id)
            entity.deleted_at = None
            session.commit()

    def is_deleted(self, entity_type: str, entity_id: str) -> bool:
        with self.session_factory() as session:
            entity = _lookup(session, entity_type, entity_id)
            return entity.deleted_at is not None

    def list_deleted(self) -> list[dict]:
        """List soft-deleted candidates and JDs for the recycle bin."""
        from sqlalchemy import select

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