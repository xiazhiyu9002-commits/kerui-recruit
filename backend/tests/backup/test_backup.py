from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.backup.service import BackupService
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate
from kerui_recruit.db.session import create_engine_for


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return engine


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def test_create_and_list_snapshots(
    tmp_path: Path,
    engine: Engine,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(Candidate(display_name="张三"))
        session.commit()

    service = BackupService(
        session_factory=session_factory,
        engine=engine,
        database_path=tmp_path / "recruit.sqlite3",
        backup_dir=tmp_path / "backups",
    )

    snapshot = service.create_snapshot(label="测试备份")
    assert snapshot.exists()
    assert "测试备份" in snapshot.name

    snapshots = service.list_snapshots()
    assert len(snapshots) >= 1
    assert snapshots[0]["filename"] == snapshot.name


def test_restore_snapshot(
    tmp_path: Path,
    engine: Engine,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(Candidate(display_name="刘备"))
        session.commit()

    service = BackupService(
        session_factory=session_factory,
        engine=engine,
        database_path=tmp_path / "recruit.sqlite3",
        backup_dir=tmp_path / "backups",
    )
    snapshot = service.create_snapshot(label="before_add")

    # Add a second candidate, then restore
    with session_factory() as session:
        session.add(Candidate(display_name="曹操"))
        session.commit()

    service.restore_snapshot(snapshot.name)

    with session_factory() as session:
        from sqlalchemy import select
        names = session.scalars(select(Candidate.display_name)).all()
        assert "刘备" in names
        assert "曹操" not in names