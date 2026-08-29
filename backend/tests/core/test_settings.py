from pathlib import Path

from kerui_recruit.core.settings import Settings


def test_settings_resolve_paths_without_exposing_session_token(tmp_path: Path) -> None:
    """A serialized setting must not leak the desktop session token."""
    settings = Settings(data_root=tmp_path / "data", session_token="top-secret")

    assert settings.paths.database == tmp_path / "data" / "db" / "recruit.sqlite3"
    assert "top-secret" not in str(settings)
    assert settings.session_token.get_secret_value() == "top-secret"
