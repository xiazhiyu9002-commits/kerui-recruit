from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from kerui_recruit.core.settings import Settings
from kerui_recruit.db.models import Candidate
from kerui_recruit.runtime import create_runtime_app


@pytest.fixture
def app(tmp_path: Path):
    settings = Settings(
        data_root=tmp_path / "data",
        session_token=SecretStr("launch-token"),
    )
    return create_runtime_app(settings)


def _headers() -> dict[str, str]:
    return {"X-Kerui-Session": "launch-token"}


def _seed_jd(client: TestClient) -> str:
    imported = client.post(
        "/api/jd/import",
        json={"company": "某公司", "title": "Java 后端", "source_text": "Java 3年 本科"},
        headers=_headers(),
    )
    return imported.json()["jd_id"]


def test_case_advance_and_dashboard(app, tmp_path: Path) -> None:
    with TestClient(app) as client:
        services = app.state.services
        with services.session_factory() as session:
            candidate = Candidate(display_name="张三")
            session.add(candidate)
            session.commit()
            candidate_id = candidate.id

        jd_id = _seed_jd(client)

        created = client.post(
            "/api/case",
            json={"candidate_id": candidate_id, "jd_id": jd_id},
            headers=_headers(),
        )
        assert created.status_code == 200
        case_id = created.json()["id"]
        assert created.json()["stage"] == "待评估"

        advanced = client.post(
            f"/api/case/{case_id}/advance",
            json={"stage": "已推荐", "note": "推荐给客户"},
            headers=_headers(),
        )
        assert advanced.status_code == 200
        assert advanced.json()["stage"] == "已推荐"

        events = client.get(f"/api/case/{case_id}/events", headers=_headers())
        assert events.status_code == 200
        assert events.json()[0]["stage"] == "已推荐"

        overview = client.get("/api/dashboard/overview", headers=_headers())
        assert overview.status_code == 200
        assert overview.json()["recommendation_total"] == 1

        by_jd = client.get("/api/dashboard/by-jd", headers=_headers())
        assert by_jd.status_code == 200
        assert len(by_jd.json()) == 1
        assert by_jd.json()[0]["stage_counts"]["已推荐"] == 1
