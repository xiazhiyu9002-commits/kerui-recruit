from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import TaskRecord


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskResponse(BaseModel):
    id: str
    task_type: str
    queue_name: str
    status: str
    progress: int
    payload: dict[str, Any]
    result_ref: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[TaskResponse])
def list_tasks(request: Request) -> list[TaskResponse]:
    services: AppServices = request.app.state.services
    tasks = services.task_repository.list()
    return [TaskResponse.model_validate(task, from_attributes=True) for task in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, request: Request) -> TaskResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            raise ApiError(404, "E_TASK_NOT_FOUND", "任务不存在")
        return TaskResponse.model_validate(task, from_attributes=True)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(task_id: str, request: Request) -> TaskResponse:
    services: AppServices = request.app.state.services
    try:
        services.task_repository.cancel(task_id)
    except LookupError:
        raise ApiError(404, "E_TASK_NOT_FOUND", "任务不存在")
    with services.session_factory() as session:
        return TaskResponse.model_validate(session.get(TaskRecord, task_id), from_attributes=True)


@router.post("/{task_id}/retry", response_model=TaskResponse)
def retry_task(task_id: str, request: Request) -> TaskResponse:
    services: AppServices = request.app.state.services
    try:
        services.task_repository.retry(task_id)
    except LookupError:
        raise ApiError(404, "E_TASK_NOT_FOUND", "任务不存在")
    with services.session_factory() as session:
        return TaskResponse.model_validate(session.get(TaskRecord, task_id), from_attributes=True)


@router.post("/{task_id}/pause", response_model=TaskResponse)
def pause_task(task_id: str, request: Request) -> TaskResponse:
    services: AppServices = request.app.state.services
    try:
        services.task_repository.pause(task_id)
    except LookupError:
        raise ApiError(404, "E_TASK_NOT_FOUND", "任务不存在")
    with services.session_factory() as session:
        return TaskResponse.model_validate(session.get(TaskRecord, task_id), from_attributes=True)


@router.post("/{task_id}/resume", response_model=TaskResponse)
def resume_task(task_id: str, request: Request) -> TaskResponse:
    services: AppServices = request.app.state.services
    try:
        services.task_repository.resume(task_id)
    except LookupError:
        raise ApiError(404, "E_TASK_NOT_FOUND", "任务不存在")
    with services.session_factory() as session:
        return TaskResponse.model_validate(session.get(TaskRecord, task_id), from_attributes=True)
