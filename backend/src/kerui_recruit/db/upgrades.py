from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection


@dataclass(frozen=True, slots=True)
class Upgrade:
    from_version: int
    to_version: int
    apply: Callable[[Connection], None]


def _upgrade_v1_to_v2(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_task_status_updated ON task (status, updated_at)"
    )


DEFAULT_UPGRADES = (Upgrade(1, 2, _upgrade_v1_to_v2),)
