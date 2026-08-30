from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import CorrectionLog


_CORRECTABLE_FIELDS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"display_name", "status", "total_years", "highest_degree"}),
    "jd": frozenset({"company", "title", "status", "priority"}),
    "jd_revision": frozenset({"source_text"}),
    "resume_revision": frozenset({"display_name"}),
}


class CorrectionService:
    """Append-only correction log with undo support.

    Every field mutation is recorded so users can revert individual
    corrections later.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def apply_correction(
        self,
        *,
        entity_type: str,
        entity_id: str,
        field_name: str,
        new_value: str | None,
        reason: str | None = None,
    ) -> CorrectionLog:
        _validate_field(entity_type, field_name)
        with self.session_factory() as session:
            old_value = self._current_value(session, entity_type, entity_id, field_name)

            log = CorrectionLog(
                entity_type=entity_type,
                entity_id=entity_id,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
            )
            session.add(log)
            self._set_field(session, entity_type, entity_id, field_name, new_value)
            session.commit()
            return log

    def undo_correction(self, correction_id: str) -> CorrectionLog:
        with self.session_factory() as session:
            log = session.get(CorrectionLog, correction_id)
            if log is None:
                raise LookupError(f"CorrectionLog not found: {correction_id}")
            if log.reverted:
                raise ValueError(f"Correction already reverted: {correction_id}")

            self._set_field(
                session, log.entity_type, log.entity_id, log.field_name, log.old_value
            )
            log.reverted = True
            log.reverted_at = datetime.now(timezone.utc)
            session.commit()
            return log

    @staticmethod
    def _current_value(
        session: Session, entity_type: str, entity_id: str, field_name: str
    ) -> str | None:
        entity = _lookup(session, entity_type, entity_id)
        val = getattr(entity, field_name, None)
        return str(val) if val is not None else None

    @staticmethod
    def _set_field(
        session: Session,
        entity_type: str,
        entity_id: str,
        field_name: str,
        value: Any,
    ) -> None:
        entity = _lookup(session, entity_type, entity_id)
        setattr(entity, field_name, value)


def _lookup(session: Session, entity_type: str, entity_id: str) -> Any:
    from kerui_recruit.db.models import Candidate, Jd, JdRevision, ResumeRevision

    cls_map: dict[str, type] = {
        "candidate": Candidate,
        "jd": Jd,
        "jd_revision": JdRevision,
        "resume_revision": ResumeRevision,
    }
    cls = cls_map.get(entity_type)
    if cls is None:
        raise ValueError(f"Unknown entity type: {entity_type}")
    entity = session.get(cls, entity_id)
    if entity is None:
        raise LookupError(f"{entity_type} not found: {entity_id}")
    return entity


def _validate_field(entity_type: str, field_name: str) -> None:
    if field_name not in _CORRECTABLE_FIELDS.get(entity_type, frozenset()):
        raise ValueError(f"{entity_type}.{field_name} cannot be corrected")
