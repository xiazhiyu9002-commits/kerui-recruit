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


def test_batch_match_multiple_jds(client: TestClient) -> None:
    first = client.post(
        "/api/jd/import",
        json={"company": "某金融", "title": "Java 后端", "source_text": "Java 3年 本科 金融"},
        headers=_headers(),
    ).json()
    second = client.post(
        "/api/jd/import",
        json={"company": "某科技", "title": "算法工程师", "source_text": "Python 算法 大模型"},
        headers=_headers(),
    ).json()

    batch = client.post(
        "/api/match/batch",
        json={"revision_ids": [first["revision_id"], second["revision_id"]], "limit": 20},
        headers=_headers(),
    )

    assert batch.status_code == 200
    results = batch.json()["results"]
    assert len(results) == 2
    assert {r["revision_id"] for r in results} == {first["revision_id"], second["revision_id"]}
    assert all(r["run_id"] for r in results)