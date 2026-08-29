from fastapi import APIRouter, Request

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(request: Request) -> dict:
    services: AppServices = request.app.state.services
    return services.dashboard_service.overview()


@router.get("/by-jd")
def by_jd(request: Request) -> list[dict]:
    services: AppServices = request.app.state.services
    return services.dashboard_service.by_jd()
