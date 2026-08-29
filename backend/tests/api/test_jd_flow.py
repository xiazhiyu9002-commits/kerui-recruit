from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kerui_recruit.core.settings import Settings
from kerui_recruit.runtime import create_runtime_app
from pydantic import SecretStr


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        data_root=tmp_path / "data",
        session_token=SecretStr("launch-token"),
    )
    app = create_runtime_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _headers() -> dict[str, str]:
    return {"X-Kerui-Session": "launch-token"}


def test_jd_import_and_match_round_trip(client: TestClient) -> None:
    imported = client.post(
        "/api/jd/import",
        json={"company": "某金融", "title": "Java 后端", "source_text": "Java 3年 本科 金融"},
        headers=_headers(),
    )
    assert imported.status_code == 202
    body = imported.json()
    assert body["jd_id"]

    match = client.post(
        "/api/match/jd",
        json={"revision_id": body["revision_id"], "limit": 20},
        headers=_headers(),
    )
    assert match.status_code == 200