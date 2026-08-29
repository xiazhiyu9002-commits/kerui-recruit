from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.migration.service import MigrationService


@pytest.fixture
def current_root(tmp_path: Path) -> Path:
    root = tmp_path / "current"
    (root / "db").mkdir(parents=True)
    (root / "blobs").mkdir(parents=True)
    (root / "search").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    return root


def test_migrate_to_copies_and_verifies(
    tmp_path: Path, current_root: Path
) -> None:
    engine = create_engine_for(current_root / "db" / "recruit.sqlite3")
    migrate(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(Candidate(display_name="张三"))
        session.commit()
    engine.dispose()

    (current_root / "blobs" / "a.bin").write_bytes(b"hello")
    (current_root / "search" / "index.bin").write_bytes(b"world")
    (current_root / "config" / "settings.json").write_text("{}")

    service = MigrationService(
        session_factory=session_factory,
        current_root=current_root,
    )
    target = tmp_path / "target"

    report = service.migrate_to(str(target))

    assert report.ok is True
    assert report.candidate_count == 1
    assert report.files_copied == report.files_verified
    assert (target / "blobs" / "a.bin").read_bytes() == b"hello"
    assert (target / "search" / "index.bin").read_bytes() == b"world"
    assert (target / "config" / "settings.json").read_text() == "{}"
