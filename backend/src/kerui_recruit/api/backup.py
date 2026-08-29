from fastapi import APIRouter, Request
from pydantic import BaseModel

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/backup", tags=["backup"])


class SnapshotItem(BaseModel):
    filename: str
    path: str
    size_bytes: str
    created: str


class CreateSnapshotRequest(BaseModel):
    label: str = ""


class CreateSnapshotResponse(BaseModel):
    filename: str
    path: str


class RestoreResponse(BaseModel):
    restored_from: str
    safety_backup: str


@router.get("/snapshots", response_model=list[SnapshotItem])
def list_snapshots(request: Request) -> list[SnapshotItem]:
    services: AppServices = request.app.state.services
    return [SnapshotItem(**s) for s in services.backup_service.list_snapshots()]


@router.post("/snapshots", response_model=CreateSnapshotResponse)
def create_snapshot(command: CreateSnapshotRequest, request: Request) -> CreateSnapshotResponse:
    services: AppServices = request.app.state.services
    path = services.backup_service.create_snapshot(label=command.label)
    return CreateSnapshotResponse(filename=path.name, path=str(path))


@router.post("/restore/{filename}", response_model=RestoreResponse)
def restore_snapshot(filename: str, request: Request) -> RestoreResponse:
    services: AppServices = request.app.state.services
    safety = services.backup_service.restore_snapshot(filename)
    return RestoreResponse(restored_from=filename, safety_backup=str(safety))