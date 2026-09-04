from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from kerui_recruit.api.search import router
from kerui_recruit.db.base import Base
from kerui_recruit.db.models import Blob, Candidate, CandidateContact, ResumeDocument, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.providers.fakes import FakeRerankerProvider
from kerui_recruit.search.contracts import SearchChunk, SearchPage
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.service import HybridSearchService


class Embedding:
    async def embed_query(self, text):
        return [1., 0.]


def setup_app(tmp_path, count=1):
    engine = create_engine_for(tmp_path / "test.sqlite")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    index = LanceDBSearchIndex(tmp_path / "index", vector_dimension=2)
    with factory.begin() as session:
        for number in range(count):
            cid = f"c{number}"
            session.add(Candidate(id=cid, display_name=cid, status="AVAILABLE"))
            session.add(Blob(id=f"b{number}", content_sha256=str(number).zfill(64), suffix=".txt", size_bytes=6,
                             storage_path=f"blob-{number}", reference_count=1))
            session.flush()
            session.add(ResumeDocument(id=f"d{number}", candidate_id=cid))
            session.flush()
            session.add(ResumeRevision(id=f"r{number}", document_id=f"d{number}", blob_id=f"b{number}",
                                       content_sha256=str(number).zfill(64), original_filename=f"{number}.txt",
                                       status="READY", is_current=True, raw_text="Python"))
    index.upsert([SearchChunk(f"chunk{n}", f"c{n}", f"r{n}", "Python", (1., 0.), 5,
                             "MASTER", "上海", "AVAILABLE", preferred_location="广州") for n in range(count)])
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(session_factory=factory, encryption_service=None,
        search_service=HybridSearchService(index=index, embedding_provider=Embedding(),
                                          reranker_provider=FakeRerankerProvider()))
    return app, factory, engine


async def post(app, **payload):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.post("/api/search/candidates", json=payload)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.mark.asyncio
async def test_http_explicit_filters_override_whole_location_group_and_false_values(tmp_path):
    app, _, _ = setup_app(tmp_path)
    captured = []
    class Capture:
        search_timeout = 4.5
        async def search(self, query, filters, **kwargs):
            captured.append(filters)
            return SearchPage(items=())
    app.state.services.search_service = Capture()
    await post(app, query="仅本科 上海或北京 意向深圳或杭州", filters={
        "degree_exact": False, "locations": ["广州"], "preferred_locations": ["成都", "武汉"]})
    filters = captured[0]
    assert filters.degree_exact is False
    assert filters.location_values() == ("广州",)
    assert filters.preferred_location_values() == ("成都", "武汉")


@pytest.mark.asyncio
async def test_http_explicit_empty_and_null_filters_clear_parsed_conditions(tmp_path):
    app, _, _ = setup_app(tmp_path)
    captured = []
    class Capture:
        search_timeout = 4.5
        async def search(self, query, filters, **kwargs):
            captured.append(filters)
            return SearchPage(items=())
    app.state.services.search_service = Capture()
    await post(app, query="上海 意向深圳 本科 排除Java", filters={
        "locations": [], "preferred_locations": [], "highest_degree": None, "exclude_skills": []})
    filters = captured[0]
    assert filters.location_values() == ()
    assert filters.preferred_location_values() == ()
    assert filters.highest_degree is None
    assert filters.exclude_skills == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["deleted", "status", "revision_old", "revision_failed", "wrong_owner"])
async def test_http_rejects_stale_projection_against_live_sqlite(tmp_path, invalid):
    app, factory, _ = setup_app(tmp_path, 2)
    with factory.begin() as session:
        candidate = session.get(Candidate, "c0")
        revision = session.get(ResumeRevision, "r0")
        if invalid == "deleted":
            candidate.deleted_at = datetime.now(timezone.utc)
        elif invalid == "status":
            candidate.status = "ON_HOLD"
        elif invalid == "revision_old":
            revision.is_current = False
        elif invalid == "revision_failed":
            revision.status = "FAILED"
        else:
            revision.document_id = "d1"
    result = await post(app, query="Python")
    assert [item["candidate_id"] for item in result["items"]] == ["c1"]


@pytest.mark.asyncio
async def test_http_hydration_uses_bounded_batch_queries(tmp_path):
    app, _, engine = setup_app(tmp_path, 25)
    statements = []
    @event.listens_for(engine, "before_cursor_execute")
    def count_queries(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    result = await post(app, query="Python", limit=25)
    assert len(result["items"]) == 25
    assert len(statements) <= 3


@pytest.mark.asyncio
async def test_http_exclusion_verifies_all_current_documents_not_only_indexed_evidence(tmp_path):
    app, factory, _ = setup_app(tmp_path)
    with factory.begin() as session:
        session.add(ResumeDocument(id="extra-doc", candidate_id="c0"))
        session.flush()
        session.add(ResumeRevision(id="extra-revision", document_id="extra-doc", blob_id="b0",
                                   content_sha256="extra", original_filename="extra.txt", status="READY",
                                   is_current=True, raw_text="Java legacy project"))
    result = await post(app, query="Python 排除Java")
    assert result["items"] == []


@pytest.mark.asyncio
async def test_http_missing_current_exclusion_evidence_is_explicitly_unverified(tmp_path):
    app, factory, _ = setup_app(tmp_path)
    with factory.begin() as session:
        session.get(ResumeRevision, "r0").raw_text = None
    result = await post(app, query="Python 排除Java")
    assert result["items"] == []
    assert "EXCLUSION_UNVERIFIED" in result["degraded_reasons"]
    assert result["empty_reason"] == "service_error"


@pytest.mark.asyncio
async def test_http_pending_projection_never_returns_stale_same_revision_filters(tmp_path):
    app, factory, _ = setup_app(tmp_path)
    from kerui_recruit.search.sync import enqueue_sync
    with factory.begin() as session:
        session.get(Candidate, "c0").total_years = 1
        enqueue_sync(session, "candidate", "c0")
    result = await post(app, query="Python", filters={"min_years": 5})
    assert result["items"] == []


@pytest.mark.asyncio
async def test_http_dedup_candidates_sharing_contact_fingerprint(tmp_path):
    app, factory, _ = setup_app(tmp_path, 2)
    with factory.begin() as session:
        session.add(CandidateContact(candidate_id="c0", phone_fingerprint="13800138000"))
        session.add(CandidateContact(candidate_id="c1", phone_fingerprint="13800138000"))
    result = await post(app, query="Python")
    assert [item["candidate_id"] for item in result["items"]] == ["c0"]
