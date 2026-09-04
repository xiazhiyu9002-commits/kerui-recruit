from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

from kerui_recruit.backup.portable import (
    PortableBackupService,
    PortableRestoreError,
    _derive_key,
    is_same_volume,
)
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


def _encrypt_zip(tmp_path: Path, passphrase: str, entries: dict[str, bytes]) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    salt = os.urandom(16)
    encrypted = Fernet(_derive_key(passphrase, salt)).encrypt(buffer.getvalue())
    path = tmp_path / "crafted.krbackup"
    path.write_bytes(salt + encrypted)
    return path


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
    assert list(tmp_path.glob(".target.staging-*")) == []
    assert list(tmp_path.glob(".target.rollback-*")) == []


def test_portable_backup_rejects_wrong_passphrase(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    backup = service.create(tmp_path / "backup", PASSPHRASE)
    target = tmp_path / "target"

    with pytest.raises(PortableRestoreError) as error:
        service.restore(backup, target, "wrong passphrase")

    assert error.value.code == "E_BACKUP_DECRYPT_FAILED"
    assert not target.exists()


def test_portable_backup_truncated_archive_does_not_modify_target(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    backup = service.create(tmp_path / "backup", PASSPHRASE)
    payload = backup.read_bytes()
    truncated = tmp_path / "truncated.krbackup"
    truncated.write_bytes(payload[: len(payload) - 8])
    target = tmp_path / "target"

    with pytest.raises(PortableRestoreError):
        service.restore(truncated, target, PASSPHRASE)

    assert not target.exists()


def test_portable_backup_missing_manifest_does_not_modify_target(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    backup = _encrypt_zip(tmp_path, PASSPHRASE, {"blobs/a.bin": b"hello"})
    target = tmp_path / "target"

    with pytest.raises(PortableRestoreError) as error:
        service.restore(backup, target, PASSPHRASE)

    assert error.value.code == "E_BACKUP_MANIFEST_MISSING"
    assert not target.exists()


def test_portable_backup_hash_mismatch_does_not_modify_target(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    manifest = json.dumps({"files": {"blobs/a.bin": "deadbeef"}})
    backup = _encrypt_zip(
        tmp_path,
        PASSPHRASE,
        {"manifest.json": manifest.encode("utf-8"), "blobs/a.bin": b"hello"},
    )
    target = tmp_path / "target"

    with pytest.raises(PortableRestoreError) as error:
        service.restore(backup, target, PASSPHRASE)

    assert error.value.code == "E_BACKUP_HASH_MISMATCH"
    assert not target.exists()


def test_portable_backup_path_traversal_rejected(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    manifest = json.dumps({"files": {"db/recruit.sqlite3": hashlib.sha256(b"x").hexdigest()}})
    backup = _encrypt_zip(
        tmp_path,
        PASSPHRASE,
        {
            "manifest.json": manifest.encode("utf-8"),
            "../evil.txt": b"evil",
            "db/recruit.sqlite3": b"x",
        },
    )
    target = tmp_path / "target"

    with pytest.raises(PortableRestoreError) as error:
        service.restore(backup, target, PASSPHRASE)

    assert error.value.code == "E_BACKUP_PATH_TRAVERSAL"
    assert not target.exists()
    assert not (tmp_path / "evil.txt").exists()


def test_portable_backup_promote_failure_restores_original_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("original")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "new.txt").write_text("new")

    def _fail_replace(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _fail_replace)

    with pytest.raises(PortableRestoreError) as error:
        PortableBackupService._promote(staging, target)

    assert error.value.code == "E_BACKUP_PROMOTE_FAILED"
    assert (target / "keep.txt").read_text() == "original"
    assert not (target / "new.txt").exists()


def test_portable_backup_success_database_readable(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    backup = service.create(tmp_path / "backup", PASSPHRASE)
    target = tmp_path / "target"

    service.restore(backup, target, PASSPHRASE)

    with sqlite3.connect(f"file:{(target / 'db' / 'recruit.sqlite3').as_posix()}?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 1


def test_portable_backup_temp_dirs_cleaned_after_failure(
    tmp_path: Path, current_root: Path
) -> None:
    _seed(current_root)
    service = PortableBackupService(current_root=current_root)
    backup = _encrypt_zip(tmp_path, PASSPHRASE, {"blobs/a.bin": b"hello"})
    target = tmp_path / "target"

    with pytest.raises(PortableRestoreError):
        service.restore(backup, target, PASSPHRASE)

    assert list(tmp_path.glob(".target.staging-*")) == []
    assert list(tmp_path.glob(".target.rollback-*")) == []


def test_is_same_volume_detects_same_directory(tmp_path: Path) -> None:
    assert is_same_volume(tmp_path / "current", tmp_path / "target") is True


def test_is_same_volume_handles_non_existent_target(tmp_path: Path) -> None:
    assert is_same_volume(tmp_path / "current", tmp_path / "does" / "not" / "exist") is True
