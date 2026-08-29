from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from kerui_recruit.db.base import Base
from kerui_recruit.db import models as _models

SCHEMA_VERSION = 1


def migrate(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _apply_schema_version(engine)


def _apply_schema_version(engine: Engine) -> None:
    """Record the current schema version and reject a newer database.

    This is a lightweight version guard for the pre-1.0 release; Alembic-style
    migrations can build on it once multiple schema versions ship.
    """
    with Session(engine) as session:
        current = session.scalars(
            select(_models.SchemaVersion).order_by(_models.SchemaVersion.version.desc())
        ).first()
        if current is None:
            session.add(_models.SchemaVersion(version=SCHEMA_VERSION))
            session.commit()
        elif current.version > SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库 schema 版本 {current.version} 高于当前支持的 {SCHEMA_VERSION}"
            )
