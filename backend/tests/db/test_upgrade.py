from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Connection, inspect, select, text
from sqlalchemy.orm import Session

from kerui_recruit.db import models as _models
from kerui_recruit.db.base import Base
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.db.upgrades import Upgrade


def _create_version_one_database(path: Path) -> None:
    engine = create_engine_for(path)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_models.SchemaVersion(version=1))
        session.add(_models.Candidate(display_name="升级保留样本"))
        session.commit()
    engine.dispose()


def test_migrate_upgrades_v1_to_v2_after_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "recruit.sqlite3"
    _create_version_one_database(database)
    engine = create_engine_for(database)

    migrate(engine)

    with Session(engine) as session:
        versions = list(session.scalars(select(_models.SchemaVersion.version)))
        candidate = session.scalar(select(_models.Candidate))
    indexes = {index["name"] for index in inspect(engine).get_indexes("task")}
    snapshots = list(tmp_path.glob("recruit.pre-v1-to-v2*.sqlite3"))
    assert versions == [1, 2]
    assert candidate is not None and candidate.display_name == "升级保留样本"
    assert "ix_task_status_updated" in indexes
    assert len(snapshots) == 1 and snapshots[0].stat().st_size > 0


def test_failed_upgrade_rolls_back_schema_and_version(tmp_path: Path) -> None:
    database = tmp_path / "recruit.sqlite3"
    _create_version_one_database(database)
    engine = create_engine_for(database)

    def failing_upgrade(connection: Connection) -> None:
        connection.execute(text("CREATE TABLE should_rollback (id INTEGER PRIMARY KEY)"))
        raise RuntimeError("forced upgrade failure")

    with pytest.raises(RuntimeError, match="forced upgrade failure"):
        migrate(
            engine,
            target_version=2,
            upgrades=(Upgrade(1, 2, failing_upgrade),),
        )

    with Session(engine) as session:
        versions = list(session.scalars(select(_models.SchemaVersion.version)))
    assert versions == [1]
    assert "should_rollback" not in inspect(engine).get_table_names()
