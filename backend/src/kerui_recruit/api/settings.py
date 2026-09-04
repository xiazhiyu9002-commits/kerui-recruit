import smtplib

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.errors import ApiError
from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import MailCursor
from kerui_recruit.mail.imap_provider import ImapLibProvider
from kerui_recruit.providers.vendors import VENDORS


router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateSettingsRequest(BaseModel):
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    siliconflow_api_key: str | None = None
    siliconflow_base_url: str | None = None
    siliconflow_embedding_model: str | None = None
    siliconflow_reranker_model: str | None = None
    text_base_url: str | None = None
    text_model: str | None = None
    text_api_key: str | None = None
    vision_base_url: str | None = None
    vision_model: str | None = None
    vision_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    rerank_base_url: str | None = None
    rerank_model: str | None = None
    rerank_api_key: str | None = None
    tavily_api_key: str | None = None
    tavily_base_url: str | None = None
    serpapi_api_key: str | None = None
    serpapi_base_url: str | None = None
    imap_host: str | None = None
    imap_account: str | None = None
    imap_auth_code: str | None = None
    imap_whitelist: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_account: str | None = None
    smtp_auth_code: str | None = None
    smtp_ssl: bool | None = None
    reminder_to: str | None = None


@router.get("")
def get_settings(request: Request) -> dict:
    services: AppServices = request.app.state.services
    return services.settings_service.get_masked()


@router.get("/vendors")
def list_vendors() -> list[dict]:
    return [
        {
            "key": vendor.key,
            "label": vendor.label,
            "base_url": vendor.base_url,
            "text_model": vendor.text_model,
            "vision_model": vendor.vision_model,
            "embedding_model": vendor.embedding_model,
            "rerank_model": vendor.rerank_model,
        }
        for vendor in VENDORS.values()
    ]


@router.put("")
def update_settings(command: UpdateSettingsRequest, request: Request) -> dict:
    services: AppServices = request.app.state.services
    services.settings_service.update(command.model_dump(exclude_none=True))
    return services.settings_service.get_masked()


@router.post("/mail/test")
def test_mail(request: Request) -> dict:
    """Probe IMAP/SMTP connectivity with the currently configured credentials."""
    services: AppServices = request.app.state.services
    settings = services.settings
    results: dict[str, dict] = {}

    if settings.mail_enabled:
        try:
            provider = ImapLibProvider(
                host=settings.imap_host,  # type: ignore[arg-type]
                account=settings.imap_account,  # type: ignore[arg-type]
                password=settings.imap_auth_code.get_secret_value(),  # type: ignore[union-attr]
            )
            provider.connect()
            provider.disconnect()
            results["imap"] = {"ok": True, "message": "IMAP 连接成功"}
        except Exception as error:
            results["imap"] = {"ok": False, "message": f"IMAP 连接失败：{error}"}
    else:
        results["imap"] = {"ok": False, "message": "未配置 IMAP"}

    smtp_ready = bool(settings.smtp_host and settings.smtp_account and settings.smtp_auth_code)
    if smtp_ready:
        try:
            server = (
                smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)
                if settings.smtp_ssl
                else smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            )
            try:
                server.login(settings.smtp_account, settings.smtp_auth_code.get_secret_value())  # type: ignore[union-attr]
            finally:
                server.quit()
            results["smtp"] = {"ok": True, "message": "SMTP 连接成功"}
        except Exception as error:
            results["smtp"] = {"ok": False, "message": f"SMTP 连接失败：{error}"}
    else:
        results["smtp"] = {"ok": False, "message": "未配置 SMTP"}

    return results


@router.post("/mail/sync")
def sync_mail(request: Request) -> dict:
    services: AppServices = request.app.state.services
    scheduler = services.scheduler_service
    if scheduler is None or scheduler.mail_ingest_service is None:
        raise ApiError(503, "E_MAIL_UNAVAILABLE", "邮箱未配置，无法同步")
    try:
        revision_ids = scheduler.poll_mail()
    except Exception as error:
        raise ApiError(502, "E_MAIL_SYNC_FAILED", f"同步失败：{error}") from error
    return {"ingested": len(revision_ids), "revision_ids": revision_ids}


@router.get("/mail/status")
def mail_status(request: Request) -> dict:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        cursor = session.query(MailCursor).filter_by(mailbox="INBOX").one_or_none()
    return {
        "configured": services.settings.mail_enabled,
        "last_uid": cursor.last_uid if cursor is not None else 0,
    }
