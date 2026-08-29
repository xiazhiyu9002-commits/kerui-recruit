from __future__ import annotations

from sqlalchemy import text

from kerui_recruit.api.services import AppServices


class HealthService:
    def __init__(self, services: AppServices) -> None:
        self.services = services

    def check(self) -> dict[str, dict]:
        report: dict[str, dict] = {}

        try:
            with self.services.session_factory() as session:
                session.execute(text("SELECT 1"))
            report["database"] = {"status": "healthy"}
        except Exception:
            report["database"] = {"status": "unhealthy", "message": "数据库连接失败"}

        try:
            self.services.blob_store.root.mkdir(parents=True, exist_ok=True)
            report["blob_store"] = {"status": "healthy"}
        except Exception:
            report["blob_store"] = {"status": "unhealthy", "message": "原件库不可用"}

        try:
            self.services.search_service.index
            report["search"] = {"status": "healthy"}
        except Exception:
            report["search"] = {"status": "unhealthy", "message": "检索引擎不可用"}

        return report