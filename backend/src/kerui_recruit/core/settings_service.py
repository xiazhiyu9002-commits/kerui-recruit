from __future__ import annotations

from kerui_recruit.core.settings_store import SettingsStore
from kerui_recruit.encryption.service import EncryptionService


# Fields that may be edited from the settings page.
ALLOWED_FIELDS = frozenset(
    {
        "deepseek_api_key",
        "deepseek_base_url",
        "siliconflow_api_key",
        "siliconflow_base_url",
        "siliconflow_embedding_model",
        "siliconflow_reranker_model",
        "text_base_url",
        "text_model",
        "text_api_key",
        "vision_base_url",
        "vision_model",
        "vision_api_key",
        "embedding_base_url",
        "embedding_model",
        "embedding_api_key",
        "rerank_base_url",
        "rerank_model",
        "rerank_api_key",
        "tavily_api_key",
        "tavily_base_url",
        "serpapi_api_key",
        "serpapi_base_url",
        "imap_host",
        "imap_account",
        "imap_auth_code",
        "imap_whitelist",
        "smtp_host",
        "smtp_port",
        "smtp_account",
        "smtp_auth_code",
        "smtp_ssl",
        "reminder_to",
    }
)

_SENSITIVE_FIELDS = frozenset(
    {
        "deepseek_api_key",
        "siliconflow_api_key",
        "tavily_api_key",
        "serpapi_api_key",
        "imap_auth_code",
        "smtp_auth_code",
        "text_api_key",
        "vision_api_key",
        "embedding_api_key",
        "rerank_api_key",
    }
)


class SettingsService:
    """Read and persist user-editable settings with encrypted secrets."""

    def __init__(
        self,
        store: SettingsStore,
        encryption: EncryptionService,
    ) -> None:
        self.store = store
        self.encryption = encryption

    def get_masked(self) -> dict:
        """Return current settings with sensitive values masked."""
        data = self.store.load()
        result: dict = {}
        for key, value in data.items():
            if key in _SENSITIVE_FIELDS and value:
                try:
                    plain = self.encryption.decrypt(value)
                except Exception:
                    plain = ""
                result[key] = _mask(plain)
            else:
                result[key] = value
        return result

    def update(self, values: dict) -> None:
        """Merge and persist allowed fields; secrets are encrypted at rest."""
        data = self.store.load()
        for key, value in values.items():
            if key not in ALLOWED_FIELDS:
                continue
            if value is None or value == "":
                data.pop(key, None)
            elif key in _SENSITIVE_FIELDS:
                existing = data.get(key)
                if existing:
                    try:
                        if value == _mask(self.encryption.decrypt(existing)):
                            continue
                    except Exception:
                        pass
                data[key] = self.encryption.encrypt(value)
            else:
                data[key] = value
        self.store.save(data)


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}****{secret[-4:]}"
