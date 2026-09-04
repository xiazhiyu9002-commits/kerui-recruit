from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from kerui_recruit.backup.service import _validate_sqlite
from kerui_recruit.core.paths import AppPaths

_BACKUP_DIRS = ("db", "search", "blobs", "config")
_SALT_SIZE = 16
_KDF_ITERATIONS = 600_000
_DATABASE_NAME = "recruit.sqlite3"


class PortableRestoreError(RuntimeError):
    """Restore failure carrying a stable machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PortableRestoreReport:
    target_root: str
    files_restored: int
    files_verified: int
    ok: bool


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def is_same_volume(left: Path, right: Path) -> bool:
    """Return True when two paths live on the same storage volume.

    On Windows the drive letter decides; elsewhere the device number of the
    deepest existing ancestor decides (so a not-yet-created target still works).
    """
    left = left.absolute()
    right = right.absolute()
    if os.name == "nt":
        return left.drive.casefold() == right.drive.casefold()
    try:
        return _device(left) == _device(right)
    except OSError:
        return True


def _device(path: Path) -> int:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate.stat().st_dev


class PortableBackupService:
    """Create an encrypted portable backup and restore it to a new directory.

    The backup bundles a consistent SQLite snapshot, search projection, blobs
    and config into one passphrase-encrypted ``.krbackup`` archive together with
    a SHA-256 manifest. Restore decrypts, extracts into a staging directory,
    verifies every file hash and the SQLite integrity, and only then promotes
    the staging directory into place with a rollback safety net.
    """

    def __init__(self, *, current_root: Path) -> None:
        self.current_root = current_root

    def create(self, target_path: Path, passphrase: str) -> Path:
        target_path = target_path.with_suffix(".krbackup")
        archive = self._build_archive()
        salt = os.urandom(_SALT_SIZE)
        encrypted = Fernet(_derive_key(passphrase, salt)).encrypt(archive)
        target_path.write_bytes(salt + encrypted)
        return target_path

    def restore(
        self,
        backup_path: Path,
        target_root: Path,
        passphrase: str,
    ) -> PortableRestoreReport:
        target = self._resolve_target(target_root)
        if not backup_path.exists():
            raise PortableRestoreError("E_BACKUP_NOT_FOUND", "备份文件不存在")

        payload = backup_path.read_bytes()
        if len(payload) <= _SALT_SIZE:
            raise PortableRestoreError("E_BACKUP_CORRUPT", "备份文件损坏或格式不正确")
        salt, encrypted = payload[:_SALT_SIZE], payload[_SALT_SIZE:]
        try:
            archive = Fernet(_derive_key(passphrase, salt)).decrypt(encrypted)
        except InvalidToken as error:
            raise PortableRestoreError(
                "E_BACKUP_DECRYPT_FAILED", "备份密码错误或备份文件已损坏"
            ) from error

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.staging-{uuid4().hex[:8]}"
        staging.mkdir()

        try:
            expected = self._extract_and_validate(archive, staging)
            self._promote(staging, target)
        except PortableRestoreError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except Exception as error:  # noqa: BLE001 - surface as readable restore error
            shutil.rmtree(staging, ignore_errors=True)
            raise PortableRestoreError(
                "E_BACKUP_RESTORE_FAILED", f"恢复失败：{error}"
            ) from error

        files_restored = len(expected)
        return PortableRestoreReport(
            target_root=str(target),
            files_restored=files_restored,
            files_verified=files_restored,
            ok=True,
        )

    def _build_archive(self) -> bytes:
        source = AppPaths.from_root(self.current_root)
        manifest: dict[str, str] = {}
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in _BACKUP_DIRS:
                directory = source.root / name
                if not directory.exists():
                    continue
                for path in sorted(directory.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(source.root).as_posix()
                    if name == "db" and path.name in (
                        f"{_DATABASE_NAME}-wal",
                        f"{_DATABASE_NAME}-shm",
                    ):
                        # WAL/SHM are live journal state; the consistent snapshot
                        # below already contains the checkpointed database.
                        continue
                    if name == "db" and path.name == _DATABASE_NAME:
                        data = _snapshot_sqlite(path)
                    else:
                        data = path.read_bytes()
                    manifest[relative] = hashlib.sha256(data).hexdigest()
                    archive.writestr(relative, data)
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "created": datetime.now(timezone.utc).isoformat(),
                        "files": manifest,
                    },
                    ensure_ascii=False,
                ),
            )
        return buffer.getvalue()

    def _extract_and_validate(self, archive: bytes, staging: Path) -> dict[str, str]:
        expected = self._read_manifest(archive)
        with zipfile.ZipFile(io.BytesIO(archive), "r") as source:
            for info in source.infolist():
                if info.is_dir() or info.filename == "manifest.json":
                    continue
                destination = self._safe_join(staging, info.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(info))

        actual: dict[str, str] = {}
        for path in staging.rglob("*"):
            if path.is_file():
                relative = path.relative_to(staging).as_posix()
                actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

        if set(actual.keys()) != set(expected.keys()):
            missing = sorted(set(expected.keys()) - set(actual.keys()))
            undeclared = sorted(set(actual.keys()) - set(expected.keys()))
            raise PortableRestoreError(
                "E_BACKUP_FILE_MISMATCH",
                "备份文件清单不一致"
                + (f"，缺失：{missing}" if missing else "")
                + (f"，多余：{undeclared}" if undeclared else ""),
            )
        for relative, digest in expected.items():
            if actual.get(relative) != digest:
                raise PortableRestoreError(
                    "E_BACKUP_HASH_MISMATCH", f"文件哈希校验失败：{relative}"
                )

        database = staging / "db" / _DATABASE_NAME
        if database.exists():
            try:
                _validate_sqlite(database)
            except ValueError as error:
                raise PortableRestoreError("E_BACKUP_DB_INVALID", str(error)) from error

        return expected

    @staticmethod
    def _read_manifest(archive: bytes) -> dict[str, str]:
        with zipfile.ZipFile(io.BytesIO(archive), "r") as source:
            try:
                manifest_bytes = source.read("manifest.json")
            except KeyError as error:
                raise PortableRestoreError(
                    "E_BACKUP_MANIFEST_MISSING", "备份缺少 manifest.json"
                ) from error
        try:
            payload = json.loads(manifest_bytes.decode("utf-8"))
            files = payload["files"]
            if not isinstance(files, dict) or not files:
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise PortableRestoreError(
                "E_BACKUP_MANIFEST_INVALID", "备份 manifest 格式不合法"
            ) from error
        return files

    @staticmethod
    def _safe_join(staging: Path, name: str) -> Path:
        root = staging.resolve()
        destination = (staging / name).resolve()
        try:
            relative = destination.relative_to(root)
        except ValueError as error:
            raise PortableRestoreError(
                "E_BACKUP_PATH_TRAVERSAL", f"备份包含非法路径：{name}"
            ) from error
        if relative.as_posix() in ("", ".", ".."):
            raise PortableRestoreError(
                "E_BACKUP_PATH_TRAVERSAL", f"备份包含非法路径：{name}"
            )
        return destination

    @staticmethod
    def _resolve_target(target_root: Path) -> Path:
        if not str(target_root).strip():
            raise PortableRestoreError("E_BACKUP_INVALID_TARGET", "恢复目标路径为空")
        try:
            return target_root.expanduser().resolve()
        except (OSError, ValueError, RuntimeError) as error:
            raise PortableRestoreError("E_BACKUP_INVALID_TARGET", "恢复目标路径无法解析") from error

    @staticmethod
    def _promote(staging: Path, target: Path) -> None:
        rollback = target.parent / f".{target.name}.rollback-{uuid4().hex[:8]}"
        moved_aside = False
        try:
            if target.exists():
                target.rename(rollback)
                moved_aside = True
            os.replace(staging, target)
        except OSError as error:
            if moved_aside and rollback.exists() and not target.exists():
                rollback.rename(target)
            raise PortableRestoreError(
                "E_BACKUP_PROMOTE_FAILED", f"恢复目录替换失败：{error}"
            ) from error
        if moved_aside:
            shutil.rmtree(rollback, ignore_errors=True)


def _snapshot_sqlite(path: Path) -> bytes:
    """Take a consistent SQLite snapshot via the online backup API."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "snapshot.sqlite3"
        with closing(sqlite3.connect(path)) as source_connection:
            with closing(sqlite3.connect(target)) as target_connection:
                source_connection.backup(target_connection)
        return target.read_bytes()
