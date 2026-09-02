from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices


router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateSettingsRequest(BaseModel):
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    siliconflow_api_key: str | None = None
    siliconflow_base_url: str | None = None
    siliconflow_embedding_model: str | None = None
    siliconflow_reranker_model: str | None = None
    tavily_api_key: str | None = None
    tavily_base_url: str | None = None
    serpapi_api_key: str | None = None
    serpapi_base_url: str | None = None
    imap_host: str | None = None
    imap_account: str | None = None
    imap_auth_code: str | None = None
    imap_whitelist: str | None = None


@router.get("")
def get_settings(request: Request) -> dict:
    services: AppServices = request.app.state.services
    return services.settings_service.get_masked()


@router.put("")
def update_settings(command: UpdateSettingsRequest, request: Request) -> dict:
    services: AppServices = request.app.state.services
    services.settings_service.update(command.model_dump(exclude_none=True))
    return services.settings_service.get_masked()
