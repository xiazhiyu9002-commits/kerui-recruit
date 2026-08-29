from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import sessionmaker

from kerui_recruit.backup.portable import PortableBackupService, is_same_volume
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate
from kerui_recruit.db.session import create_engine_for

PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def current_root(tmp_path: Path) -> Path:
    root = tmp_path / "current"
    (root / "db").mkdir(parents=True)
    (root / "blobs").mkdir(parents=True)
    (root / "search").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    return root


def _seed(current_root: Path) -> None:
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


def test_portable_backup_encrypts_and_round_trips(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)

    backup = service.create(tmp_path / "backup", PASSPHRASE)
    assert backup.suffix == ".krbackup"
    assert backup.exists()

    target = tmp_path / "target"
    report = service.restore(backup, target, PASSPHRASE)

    assert report.ok is True
    assert report.files_restored == report.files_verified
    assert (target / "blobs" / "a.bin").read_bytes() == b"hello"
    assert (target / "search" / "index.bin").read_bytes() == b"world"
    assert (target / "config" / "settings.json").read_text() == "{}"
    assert (target / "db" / "recruit.sqlite3").exists()


def test_portable_backup_rejects_wrong_passphrase(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    backup = service.create(tmp_path / "backup", PASSPHRASE)

    with pytest.raises(InvalidToken):
        service.restore(backup, tmp_path / "target", "wrong passphrase")


def test_is_same_volume_detects_same_directory(tmp_path: Path) -> None:
    assert is_same_volume(tmp_path / "current", tmp_path / "target") is True


def test_is_same_volume_handles_non_existent_target(tmp_path: Path) -> None:
    assert is_same_volume(tmp_path / "current", tmp_path / "does" / "not" / "exist") is True
