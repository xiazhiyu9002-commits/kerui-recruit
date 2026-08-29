from __future__ import annotations

from collections.abc import Callable
from typing import AsyncContextManager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kerui_recruit.api.auth import valid_session
from kerui_recruit.api.backup import router as backup_router
from kerui_recruit.api.bd_search import router as bd_search_router
from kerui_recruit.api.cases import router as cases_router
from kerui_recruit.api.correction import router as correction_router
from kerui_recruit.api.dashboard import router as dashboard_router
from kerui_recruit.api.diagnostics import router as diagnostics_router
from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.jd import router as jd_router
from kerui_recruit.api.mapping import router as mapping_router
from kerui_recruit.api.match import router as match_router
from kerui_recruit.api.reminders import router as reminders_router
from kerui_recruit.api.resumes import router as resumes_router
from kerui_recruit.api.search import router as search_router
from kerui_recruit.api.services import AppServices
from kerui_recruit.api.settings import router as settings_router
from kerui_recruit.api.soft_delete import router as soft_delete_router
from kerui_recruit.api.tasks import router as tasks_router
from kerui_recruit.health.service import HealthService
from kerui_recruit.resumes.ingest import UnsupportedResumeType


Lifespan = Callable[[FastAPI], AsyncContextManager[None]]


def create_app(
    services: AppServices | None = None,
    *,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="KeRui Recruit", version="0.1.0", lifespan=lifespan)
    if services is not None:
        app.state.services = services

    @app.middleware("http")
    async def local_session_guard(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        if request.url.path.startswith("/api/"):
            if services is None or not valid_session(request, services):
                return JSONResponse(
                    status_code=401,
                    content={
                        "code": "E_LOCAL_SESSION",
                        "message": "本地会话无效，请重新启动应用",
                        "request_id": request_id,
                        "details": None,
                    },
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": error.code,
                "message": error.message,
                "request_id": request.state.request_id,
                "details": None,
            },
        )

    @app.exception_handler(UnsupportedResumeType)
    async def handle_unsupported_resume(
        request: Request,
        error: UnsupportedResumeType,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=415,
            content={
                "code": error.code,
                "message": "仅支持 PDF、DOC 和 DOCX 简历",
                "request_id": request.state.request_id,
                "details": None,
            },
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    if services is not None:
        @app.get("/health/ready")
        def ready() -> dict[str, str]:
            return {"status": "ready"}

        @app.get("/health/checks")
        def checks() -> dict[str, dict]:
            return HealthService(services).check()

        app.include_router(resumes_router)
        app.include_router(tasks_router)
        app.include_router(search_router)
        app.include_router(jd_router)
        app.include_router(match_router)
        app.include_router(backup_router)
        app.include_router(correction_router)
        app.include_router(diagnostics_router)
        app.include_router(mapping_router)
        app.include_router(reminders_router)
        app.include_router(bd_search_router)
        app.include_router(soft_delete_router)
        app.include_router(cases_router)
        app.include_router(dashboard_router)
        app.include_router(settings_router)

    return app
