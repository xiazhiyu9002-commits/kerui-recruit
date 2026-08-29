from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/reminders", tags=["reminders"])


class CreateReminderRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    remind_at: datetime
    note: str | None = None


class ReminderResponse(BaseModel):
    id: str
    title: str
    note: str | None
    remind_at: str
    dismissed: bool
    dismissed_at: str | None


@router.get("", response_model=list[ReminderResponse])
def list_pending(request: Request) -> list[ReminderResponse]:
    services: AppServices = request.app.state.services
    return [_reminder_to_response(r) for r in services.reminder_service.list_pending()]


@router.get("/due", response_model=list[ReminderResponse])
def list_due(request: Request) -> list[ReminderResponse]:
    services: AppServices = request.app.state.services
    return [_reminder_to_response(r) for r in services.reminder_service.list_due()]


@router.post("", response_model=ReminderResponse)
def create_reminder(command: CreateReminderRequest, request: Request) -> ReminderResponse:
    services: AppServices = request.app.state.services
    reminder = services.reminder_service.create(
        title=command.title,
        remind_at=command.remind_at,
        note=command.note,
    )
    return _reminder_to_response(reminder)


@router.post("/{reminder_id}/dismiss", response_model=ReminderResponse)
def dismiss_reminder(reminder_id: str, request: Request) -> ReminderResponse:
    services: AppServices = request.app.state.services
    return _reminder_to_response(services.reminder_service.dismiss(reminder_id))


def _reminder_to_response(r) -> ReminderResponse:
    return ReminderResponse(
        id=r.id,
        title=r.title,
        note=r.note,
        remind_at=r.remind_at.isoformat(),
        dismissed=r.dismissed,
        dismissed_at=r.dismissed_at.isoformat() if r.dismissed_at else None,
    )