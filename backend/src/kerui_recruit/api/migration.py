from fastapi import APIRouter, Request
from pydantic import BaseModel

from kerui_recruit.api.services import AppServices
from kerui_recruit.migration.service import MigrationReport

router = APIRouter(prefix="/api/migration", tags=["migration"])


class MigrateRequest(BaseModel):
    target_root: str


class MigrationResponse(BaseModel):
    target_root: str
    files_copied: int
    files_verified: int
    candidate_count: int
    ok: bool


@router.post("", response_model=MigrationResponse)
def migrate_data(command: MigrateRequest, request: Request) -> MigrationResponse:
    services: AppServices = request.app.state.services
    report: MigrationReport = services.migration_service.migrate_to(command.target_root)
    return MigrationResponse(
        target_root=report.target_root,
        files_copied=report.files_copied,
        files_verified=report.files_verified,
        candidate_count=report.candidate_count,
        ok=report.ok,
    )
