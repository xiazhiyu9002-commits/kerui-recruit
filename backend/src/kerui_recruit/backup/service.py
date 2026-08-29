from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


class BackupService:
    """Snapshot the SQLite database to a timestamped backup file."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        engine: Engine,
        database_path: Path,
        backup_dir: Path,
    ) -> None:
        self.session_factory = session_factory
        self.engine = engine
        self.database_path = database_path
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, label: str = "") -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_label = label.replace(" ", "_").replace("/", "_") if label else "auto"
        filename = f"backup_{timestamp}_{safe_label}.sqlite3"
        target = self.backup_dir / filename

        self._checkpoint()
        shutil.copy2(self.database_path, target)
        return target

    def list_snapshots(self) -> list[dict[str, str]]:
        snapshots = []
        for file in sorted(self.backup_dir.glob("backup_*.sqlite3"), reverse=True):
            stat = file.stat()
            snapshots.append(
                {
                    "filename": file.name,
                    "path": str(file),
                    "size_bytes": str(stat.st_size),
                    "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
        return snapshots

    def restore_snapshot(self, filename: str) -> Path:
        source = self.backup_dir / filename
        if not source.exists():
            raise FileNotFoundError(f"Backup not found: {filename}")

        # Backup current before restoring
        safety = self.create_snapshot(label="pre_restore")

        self._checkpoint()
        # Dispose all pooled connections so they pick up the restored file
        self.engine.dispose()

        # Remove WAL/SHM files from old database
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.database_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()

        shutil.copy2(source, self.database_path)
        return safety

    def _checkpoint(self) -> None:
        with self.session_factory() as session:
            conn = session.connection()
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            session.commit()