from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from kerui_recruit.tasks.repository import TaskRepository


TaskHandler = Callable[[dict[str, Any]], Awaitable[str | None]]


class TaskWorker:
    def __init__(
        self,
        *,
        repository: TaskRepository,
        worker_id: str,
        queues: tuple[str, ...],
        handlers: Mapping[str, TaskHandler],
    ) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.queues = queues
        self.handlers = handlers

    async def run_once(self) -> bool:
        task = self.repository.claim(self.worker_id, self.queues)
        if task is None:
            return False
        handler = self.handlers.get(task.task_type)
        if handler is None:
            self.repository.fail(
                task.id,
                self.worker_id,
                error_code="E_TASK_HANDLER_MISSING",
                error_message=f"No handler is registered for {task.task_type}",
            )
            return True
        try:
            result_ref = await handler(task.payload)
        except Exception as error:
            self.repository.fail(
                task.id,
                self.worker_id,
                error_code="E_TASK_HANDLER",
                error_message=str(error),
            )
        else:
            self.repository.complete(
                task.id,
                self.worker_id,
                result_ref=result_ref,
            )
        return True
