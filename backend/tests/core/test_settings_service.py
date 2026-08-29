import json
from pathlib import Path

from kerui_recruit.core.settings_service import SettingsService
from kerui_recruit.core.settings_store import SettingsStore
from kerui_recruit.encryption.service import EncryptionService


def test_settings_update_and_masked_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    encryption = EncryptionService(key_path=str(tmp_path / "encryption.key"))
    service = SettingsService(store=store, encryption=encryption)

    service.update(
        {
            "deepseek_api_key": "sk-secret-key-123456",
            "deepseek_model": "deepseek-v4-flash",
            "tavily_base_url": "https://api.tavily.com",
        }
    )

    masked = service.get_masked()
    assert masked["deepseek_model"] == "deepseek-v4-flash"
    assert masked["deepseek_api_key"] != "sk-secret-key-123456"
    assert "sk-" in masked["deepseek_api_key"]
    assert masked["tavily_base_url"] == "https://api.tavily.com"


def test_secrets_are_encrypted_at_rest(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    encryption = EncryptionService(key_path=str(tmp_path / "encryption.key"))
    service = SettingsService(store=store, encryption=encryption)

    service.update({"tavily_api_key": "tvly-secret-key"})

    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["tavily_api_key"] != "tvly-secret-key"
    # 解密后应能还原。
    assert encryption.decrypt(raw["tavily_api_key"]) == "tvly-secret-key"
