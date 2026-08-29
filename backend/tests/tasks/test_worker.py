from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import TaskRecord
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.tasks.repository import TaskRepository, TaskSpec
from kerui_recruit.tasks.worker import TaskWorker


@pytest.mark.asyncio
async def test_worker_executes_registered_handler_and_completes_task(tmp_path: Path) -> None:
    """A claimed task must reach SUCCESS with the handler's durable result reference."""
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = TaskRepository(
        factory,
        clock=lambda: datetime(2026, 8, 29, tzinfo=timezone.utc),
        lease_duration=timedelta(minutes=5),
    )
    task_id = repo.enqueue(
        TaskSpec("EXPORT", "export", 10, {"format": "xlsx"}, "export:one")
    )

    async def export_handler(payload: dict[str, str]) -> str:
        assert payload == {"format": "xlsx"}
        return "exports/result.xlsx"

    worker = TaskWorker(
        repository=repo,
        worker_id="worker-1",
        queues=("export",),
        handlers={"EXPORT": export_handler},
    )

    assert await worker.run_once() is True
    assert await worker.run_once() is False
    with factory() as session:
        task = session.get(TaskRecord, task_id)
        assert task is not None
        assert task.status == "SUCCESS"
        assert task.result_ref == "exports/result.xlsx"


@pytest.mark.asyncio
async def test_worker_failure_schedules_a_durable_retry(tmp_path: Path) -> None:
    """A transient handler crash must release its lease and remain retryable."""
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = TaskRepository(
        factory,
        clock=lambda: datetime(2026, 8, 29, tzinfo=timezone.utc),
        lease_duration=timedelta(minutes=5),
    )
    task_id = repo.enqueue(
        TaskSpec("EXPORT", "export", 10, {"format": "xlsx"}, "export:failure")
    )

    async def failing_handler(payload: dict[str, str]) -> str:
        raise RuntimeError(f"cannot export {payload['format']}")

    worker = TaskWorker(
        repository=repo,
        worker_id="worker-1",
        queues=("export",),
        handlers={"EXPORT": failing_handler},
    )

    assert await worker.run_once() is True
    with factory() as session:
        task = session.get(TaskRecord, task_id)
        assert task is not None
        assert task.status == "RETRY_WAIT"
        assert task.error_code == "E_TASK_HANDLER"
        assert task.next_retry_at is not None
        assert task.lease_owner is None
