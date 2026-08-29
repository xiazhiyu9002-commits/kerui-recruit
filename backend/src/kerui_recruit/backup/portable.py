from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from kerui_recruit.core.paths import AppPaths

_BACKUP_DIRS = ("db", "search", "blobs", "config")
_SALT_SIZE = 16
_KDF_ITERATIONS = 600_000


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

    The backup bundles the SQLite database, search projection, blobs and config
    into one passphrase-encrypted ``.krbackup`` archive together with a SHA-256
    manifest. Restore decrypts with the passphrase, then verifies every file
    hash against the manifest before reporting success.
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
        payload = backup_path.read_bytes()
        salt, encrypted = payload[:_SALT_SIZE], payload[_SALT_SIZE:]
        archive = Fernet(_derive_key(passphrase, salt)).decrypt(encrypted)

        target = AppPaths.from_root(target_root)
        expected: dict[str, str] = {}
        files_restored = 0

        with zipfile.ZipFile(io.BytesIO(archive), "r") as source:
            for info in source.infolist():
                if info.is_dir():
                    continue
                if info.filename == "manifest.json":
                    expected = json.loads(source.read(info).decode("utf-8"))["files"]
                    continue
                destination = target.root / info.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(info))
                files_restored += 1

        files_verified = sum(
            1
            for relative, digest in expected.items()
            if (target.root / relative).exists()
            and hashlib.sha256((target.root / relative).read_bytes()).hexdigest() == digest
        )
        return PortableRestoreReport(
            target_root=str(target.root),
            files_restored=files_restored,
            files_verified=files_verified,
            ok=files_restored > 0 and files_restored == files_verified == len(expected),
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
                    manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                    archive.write(path, arcname=relative)
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
