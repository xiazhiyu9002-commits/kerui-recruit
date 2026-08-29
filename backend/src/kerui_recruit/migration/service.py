from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.core.paths import AppPaths

_COPY_DIRS = ("db", "search", "blobs", "config")


@dataclass(frozen=True, slots=True)
class MigrationReport:
    target_root: str
    files_copied: int
    files_verified: int
    candidate_count: int
    ok: bool


class MigrationService:
    """Copy the local data directory to a new location with hash verification.

    The copy is side-effect free on the source; the caller switches the active
    data root after a successful report and restarts the application.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        current_root: Path,
    ) -> None:
        self.session_factory = session_factory
        self.current_root = current_root

    def migrate_to(self, target_root: str) -> MigrationReport:
        target = AppPaths.from_root(Path(target_root))
        source = AppPaths.from_root(self.current_root)

        source_manifest = self._manifest(source.root)
        self._copy_essential_dirs(source.root, target.root)
        target_manifest = self._manifest(target.root)

        files_copied = len(source_manifest)
        files_verified = sum(
            1
            for path, digest in source_manifest.items()
            if target_manifest.get(path) == digest
        )
        candidate_count = self._count_candidates()

        return MigrationReport(
            target_root=str(target.root),
            files_copied=files_copied,
            files_verified=files_verified,
            candidate_count=candidate_count,
            ok=files_copied > 0 and files_copied == files_verified,
        )

    def _copy_essential_dirs(self, source_root: Path, target_root: Path) -> None:
        for name in _COPY_DIRS:
            source = source_root / name
            target = target_root / name
            if not source.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

    @staticmethod
    def _manifest(root: Path) -> dict[str, str]:
        manifest: dict[str, str] = {}
        for path in root.rglob("*"):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest[str(path.relative_to(root))] = digest
        return manifest

    def _count_candidates(self) -> int:
        with self.session_factory() as session:
            result = session.execute(text("SELECT COUNT(*) FROM candidate"))
            return int(result.scalar_one())
