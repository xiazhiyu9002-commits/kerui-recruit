from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from kerui_recruit.core.paths import AppPaths

_BACKUP_DIRS = ("db", "search", "blobs", "config")


@dataclass(frozen=True, slots=True)
class PortableRestoreReport:
    target_root: str
    files_restored: int
    files_verified: int
    ok: bool


class PortableBackupService:
    """Create a single-file portable backup and restore it to a new directory.

    The backup bundles the SQLite database, search projection, blobs and config
    into one ``.krbackup`` archive together with a SHA-256 manifest. Restore
    verifies every file hash against the manifest before reporting success.
    """

    def __init__(self, *, current_root: Path) -> None:
        self.current_root = current_root

    def create(self, target_path: Path) -> Path:
        target_path = target_path.with_suffix(".krbackup")
        source = AppPaths.from_root(self.current_root)
        manifest: dict[str, str] = {}

        with zipfile.ZipFile(
            target_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
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
        return target_path

    def restore(self, backup_path: Path, target_root: Path) -> PortableRestoreReport:
        target = AppPaths.from_root(target_root)
        expected: dict[str, str] = {}
        files_restored = 0

        with zipfile.ZipFile(backup_path, "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.filename == "manifest.json":
                    expected = json.loads(archive.read(info).decode("utf-8"))["files"]
                    continue
                archive.extract(info, target.root)
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
