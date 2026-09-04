from __future__ import annotations

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import IndexSyncRecord, JdRevision, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.models import DirectionProfile, build_direction_label
from kerui_recruit.jd.ingest import IngestJd, JdIngestService
from kerui_recruit.match.jd_index import JdSearchIndex
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.search.contracts import CandidateFilters, SearchChunk
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.sync import IndexSyncService, enqueue_sync
from kerui_recruit.storage.blobs import BlobStore


def _chunk(**overrides) -> SearchChunk:
    data = dict(
        id="c1:r1", candidate_id="c1", revision_id="r1", content="后端工程师",
        vector=(1.0, 2.0, 3.0, 4.0), total_years=5.0, highest_degree="硕士",
        location="北京", candidate_status="AVAILABLE",
        primary_role_family="BACKEND", role_family_codes=("BACKEND", "AI_ML"),
        direction_confidence=0.9, direction_status="CONFIDENT", direction_source="LLM",
        business_domain_codes=("PAYMENTS",), leadership_code="IC",
        taxonomy_version="career-direction-v1",
    )
    data.update(overrides)
    return SearchChunk(**data)


class FailingEmbeddingProvider:
    def __init__(self):
        self.calls = 0

    async def embed_documents(self, texts):
        self.calls += 1
        raise AssertionError("METADATA sync must not call embedding")

    async def embed_query(self, text):
        self.calls += 1
        raise AssertionError("METADATA sync must not call embedding")


def test_index_direction_fields_roundtrip(tmp_path) -> None:
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=4, embedding_model="local-hash-v1")
    index.upsert([_chunk()])
    hits = index.filter_search(CandidateFilters(), limit=10)
    assert hits[0].primary_role_family == "BACKEND"
    assert hits[0].role_family_codes == ("BACKEND", "AI_ML")
    assert hits[0].business_domain_codes == ("PAYMENTS",)
    assert hits[0].direction_source == "LLM"


def test_update_candidate_direction_preserves_vector(tmp_path) -> None:
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=4, embedding_model="local-hash-v1")
    index.upsert([_chunk()])
    before = index.get_revision_chunks("r1")[0]["vector"]
    index.update_candidate_direction("c1", primary_role_family="AI_ML", role_family_codes=["AI_ML"],
                                     direction_status="UNCERTAIN", direction_source="USER")
    after = index.get_revision_chunks("r1")[0]
    assert after["vector"] == before
    assert after["primary_role_family"] == "AI_ML"
    assert after["direction_source"] == "USER"


@pytest.mark.asyncio
async def test_metadata_sync_does_not_call_embedding(tmp_path) -> None:
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Resume")
    content = pdf.tobytes()
    pdf.close()
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(
            IngestResume(filename="张三.pdf", content=content)
        )
        revision = session.get(ResumeRevision, ingested.revision_id)
        profile = DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
        ]).model_dump(mode="json")
        revision.parsed_data = {"direction_profile": profile}
        revision.status = "READY"
        session.commit()

    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=4, embedding_model="local-hash-v1")
    index.upsert([_chunk(id=f"{ingested.revision_id}:0", candidate_id=ingested.candidate_id,
                         revision_id=ingested.revision_id)])
    failing = FailingEmbeddingProvider()
    sync = IndexSyncService(session_factory=factory, index=index, embedding_provider=failing)

    with factory() as session:
        revision = session.get(ResumeRevision, ingested.revision_id)
        new_profile = DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("AI_ML", source="USER", confidence=1.0, is_primary=True),
        ]).model_dump(mode="json")
        revision.parsed_data = {"direction_profile": new_profile}
        enqueue_sync(session, "candidate", ingested.candidate_id, mode="METADATA")
        session.commit()

    completed = await sync.run_once(force=True)
    assert completed == 1, sync.status()
    assert failing.calls == 0
    hits = index.filter_search(CandidateFilters(), limit=10)
    assert hits[0].primary_role_family == "AI_ML"


@pytest.mark.asyncio
async def test_metadata_sync_missing_index_row_upgrades_to_full(tmp_path) -> None:
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Resume")
    content = pdf.tobytes()
    pdf.close()
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(IngestResume(filename="a.pdf", content=content))
        revision = session.get(ResumeRevision, ingested.revision_id)
        profile = DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
        ]).model_dump(mode="json")
        revision.parsed_data = {"direction_profile": profile}
        revision.status = "READY"
        session.commit()

    # 索引为空（不插入任何 chunk），模拟索引行缺失。
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=4, embedding_model="local-hash-v1")
    sync = IndexSyncService(session_factory=factory, index=index, embedding_provider=FailingEmbeddingProvider())

    with factory() as session:
        enqueue_sync(session, "candidate", ingested.candidate_id, mode="METADATA")
        session.commit()

    # METADATA 遇到索引行缺失：不得 SYNCED，必须升级 FULL 且 PENDING，applied_version 不推进。
    completed = await sync.run_once(force=True)
    assert completed == 0
    with factory() as session:
        job = session.scalar(select(IndexSyncRecord))
        assert job.requested_mode == "FULL"
        assert job.status == "PENDING"
        assert job.applied_version == 0


def test_update_candidate_direction_returns_false_when_row_missing(tmp_path) -> None:
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=4, embedding_model="local-hash-v1")
    index.upsert([_chunk()])
    assert index.update_candidate_direction("does-not-exist", primary_role_family="AI_ML") is False
    assert index.update_candidate_direction("c1", primary_role_family="AI_ML") is True


@pytest.mark.asyncio
async def test_jd_metadata_sync_does_not_call_embedding(tmp_path) -> None:
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        ingested = JdIngestService(session).ingest(
            IngestJd(company="某金融", title="Java", source_text="Java 后端")
        )
        revision = session.get(JdRevision, ingested.revision_id)
        profile = DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("BACKEND", source="LLM", confidence=0.9, is_primary=True),
        ]).model_dump(mode="json")
        revision.parsed_data = {"direction_profile": profile}
        revision.status = "READY"
        session.commit()

    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=4, embedding_model="local-hash-v1")
    jd_index = JdSearchIndex(tmp_path / "search" / "jobs", vector_dimension=4, embedding_model="local-hash-v1")
    jd_index.upsert(jd_id=ingested.jd_id, revision_id=ingested.revision_id,
                    content="Java 后端", vector=(1.0, 2.0, 3.0, 4.0))
    failing = FailingEmbeddingProvider()
    sync = IndexSyncService(session_factory=factory, index=index, embedding_provider=failing, jd_index=jd_index)

    with factory() as session:
        revision = session.get(JdRevision, ingested.revision_id)
        new_profile = DirectionProfile(status="CONFIDENT", role_families=[
            build_direction_label("RISK_STRATEGY", source="USER", confidence=1.0, is_primary=True),
        ]).model_dump(mode="json")
        revision.parsed_data = {"direction_profile": new_profile}
        enqueue_sync(session, "jd", ingested.jd_id, mode="METADATA")
        session.commit()

    completed = await sync.run_once(force=True)
    assert completed == 1, sync.status()
    assert failing.calls == 0

