from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/soft-delete", tags=["soft_delete"])


class SoftDeleteRequest(BaseModel):
    entity_type: str = Field(pattern="^(candidate|jd)$")
    entity_id: str = Field(min_length=1)


class SoftDeleteResponse(BaseModel):
    entity_type: str
    entity_id: str
    deleted: bool


class DeletedItem(BaseModel):
    entity_type: str
    entity_id: str
    label: str
    deleted_at: str | None


@router.post("", response_model=SoftDeleteResponse)
def soft_delete(command: SoftDeleteRequest, request: Request) -> SoftDeleteResponse:
    services: AppServices = request.app.state.services
    services.soft_delete_service.soft_delete(command.entity_type, command.entity_id)
    return SoftDeleteResponse(
        entity_type=command.entity_type,
        entity_id=command.entity_id,
        deleted=True,
    )


@router.get("/list", response_model=list[DeletedItem])
def list_deleted(request: Request) -> list[DeletedItem]:
    services: AppServices = request.app.state.services
    return [DeletedItem(**item) for item in services.soft_delete_service.list_deleted()]


@router.post("/restore", response_model=SoftDeleteResponse)
def restore(command: SoftDeleteRequest, request: Request) -> SoftDeleteResponse:
    services: AppServices = request.app.state.services
    services.soft_delete_service.restore(command.entity_type, command.entity_id)
    return SoftDeleteResponse(
        entity_type=command.entity_type,
        entity_id=command.entity_id,
        deleted=False,
    )
