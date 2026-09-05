from kerui_recruit.api.search import CandidateSearchRequest
import httpx
import pytest
from kerui_recruit.main import create_app
from tests.api.test_local_api import build_services, make_pdf_bytes


def test_filter_only_request_accepts_empty_query():
    command = CandidateSearchRequest(query="", filters={"highest_degree": "MASTER"})
    assert command.query == ""
    assert command.filters.highest_degree == "MASTER"


@pytest.mark.asyncio
async def test_filter_only_http_search_returns_matching_current_candidates(tmp_path):
    services, pipeline = build_services(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(services)), base_url="http://local",
                                  headers={"X-Kerui-Session": "test-token"}) as client:
        imported = await client.post("/api/resumes/import", files={"file": ("synthetic.pdf", make_pdf_bytes(), "application/pdf")})
        revision = imported.json()["revision_id"]
        await pipeline.run(revision)
        await services.index_sync_service.run_once(force=True)
        response = await client.post("/api/search/candidates", json={"query": "", "filters": {"highest_degree": "MASTER", "locations": ["上海"]}})
        assert response.status_code == 200
        assert [item["revision_id"] for item in response.json()["items"]] == [revision]
        excluded = await client.post("/api/search/candidates", json={"query": "", "filters": {"locations": ["北京"]}})
        assert excluded.status_code == 200
        assert excluded.json()["items"] == []
