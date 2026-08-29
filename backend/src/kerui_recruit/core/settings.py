from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

from kerui_recruit.core.paths import AppPaths


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_root: Path
    session_token: SecretStr

    # External AI providers. When both keys are absent the runtime uses
    # deterministic local providers so the app works fully offline.
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    siliconflow_api_key: SecretStr | None = None
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "BAAI/bge-m3"
    siliconflow_reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Optional web search provider for BD lead discovery.
    tavily_api_key: SecretStr | None = None
    tavily_base_url: str = "https://api.tavily.com"

    # Optional agent mailbox for passive resume ingestion.
    imap_host: str | None = None
    imap_account: str | None = None
    imap_auth_code: SecretStr | None = None
    imap_whitelist: str | None = None  # 逗号分隔的发件人域名白名单

    # Optional SMTP for sending reminders.
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_account: str | None = None
    smtp_auth_code: SecretStr | None = None
    smtp_ssl: bool = True
    reminder_to: str | None = None

    @property
    def paths(self) -> AppPaths:
        return AppPaths.from_root(self.data_root)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def search_providers_enabled(self) -> bool:
        return bool(self.siliconflow_api_key)

    @property
    def bd_search_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.imap_host and self.imap_account and self.imap_auth_code)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_account and self.smtp_auth_code and self.reminder_to)

    @property
    def imap_whitelist_domains(self) -> set[str] | None:
        if not self.imap_whitelist:
            return None
        return {d.strip().lower() for d in self.imap_whitelist.split(",") if d.strip()}