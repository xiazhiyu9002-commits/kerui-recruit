from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Blob, Candidate, ResumeDocument, ResumeRevision, Jd, JdRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.match.service import MatchService
from kerui_recruit.providers.local import (
    LocalHashEmbeddingProvider,
    LocalKeywordReranker,
)
from kerui_recruit.search.contracts import (
    CandidateFilters,
    SearchChunk,
    SearchHit,
)
from kerui_recruit.search.service import HybridSearchService


class FakeIndex:
    """In-memory index that honors hard filters deterministically."""

    def __init__(self):
        self.chunks: list[SearchChunk] = []

    def upsert(self, chunks: list[SearchChunk]) -> None:
        self.chunks.extend(chunks)

    def delete_revision(self, revision_id: str) -> None:
        self.chunks = [c for c in self.chunks if c.revision_id != revision_id]

    def is_ready(self) -> bool:
        return len(self.chunks) > 0

    def filter_search(self, filters: CandidateFilters, limit: int) -> list[SearchHit]:
        return []

    def search(self, request) -> list[SearchHit]:
        degree_values = request.filters.degree_values()
        filtered = [
            c
            for c in self.chunks
            if (request.filters.min_years is None or (c.total_years or 0) >= request.filters.min_years)
            and (not degree_values or c.highest_degree in degree_values)
        ]
        return [
            SearchHit(
                chunk_id=c.id,
                candidate_id=c.candidate_id,
                revision_id=c.revision_id,
                content=c.content,
                score=1.0,
                matched_channels=("bm25",),
                total_years=c.total_years,
                highest_degree=c.highest_degree,
                location=c.location,
            )
            for c in filtered
        ]


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    # Match results must refer to real, current, eligible SQLite entities.
    with factory.begin() as session:
        for number in (1, 2):
            session.add(Candidate(id=f"cand-{number}", display_name=f"Candidate {number}", status="AVAILABLE"))
            session.add(Blob(id=f"blob-{number}", content_sha256=str(number).zfill(64), suffix=".txt",
                             size_bytes=20, storage_path=f"blob-{number}"))
            session.flush()
            session.add(ResumeDocument(id=f"doc-{number}", candidate_id=f"cand-{number}"))
            session.flush()
            session.add(ResumeRevision(id=f"rev-{number}", document_id=f"doc-{number}", blob_id=f"blob-{number}",
                                       content_sha256=str(number).zfill(64), original_filename=f"resume-{number}.txt",
                                       status="READY", is_current=True, raw_text="Java Python"))
    return factory


@pytest.mark.asyncio
async def test_match_excludes_candidates_below_min_years(session_factory: sessionmaker[Session]) -> None:
    index = FakeIndex()
    index.upsert(
        [
            SearchChunk(
                id="c1",
                candidate_id="cand-1",
                revision_id="rev-1",
                content="Python 金融",
                vector=[0.1],
                total_years=2.0,
                highest_degree="BACHELOR",
                location="北京",
                candidate_status="AVAILABLE",
            ),
            SearchChunk(
                id="c2",
                candidate_id="cand-2",
                revision_id="rev-2",
                content="Python 金融风控",
                vector=[0.1],
                total_years=6.0,
                highest_degree="MASTER",
                location="上海",
                candidate_status="AVAILABLE",
            ),
        ]
    )
    jd = Jd(company="A", title="Java", status="OPEN")
    with session_factory() as session:
        session.add(jd)
        session.commit()
    revision = JdRevision(
        jd_id=jd.id,
        source_text="Java 5年 硕士",
        min_years=Decimal("5.0"),
        highest_degree="MASTER",
        status="READY",
        is_current=True,
        parsed_data={"summary": "Java 金融风控", "tech_direction": ["Java"]},
    )
    with session_factory() as session:
        session.add(revision)
        session.commit()

    service = MatchService(
        session_factory=session_factory,
        search_service=HybridSearchService(
            index=index,
            embedding_provider=LocalHashEmbeddingProvider(dimension=64),
            reranker_provider=LocalKeywordReranker(),
        ),
    )

    page = await service.match_jd(
        revision_id=revision.id,
        candidates=CandidateFilters(min_years=5.0, highest_degree="MASTER"),
        limit=20,
    )

    assert [hit.candidate_id for hit in page.items] == ["cand-2"]


@pytest.mark.asyncio
async def test_match_normalizes_chinese_degree_from_jd(session_factory: sessionmaker[Session]) -> None:
    index = FakeIndex()
    index.upsert(
        [
            SearchChunk(
                id="c1",
                candidate_id="cand-1",
                revision_id="rev-1",
                content="Java 支付",
                vector=[0.1],
                total_years=6.0,
                highest_degree="BACHELOR",
                location="上海",
                candidate_status="AVAILABLE",
            ),
        ]
    )
    jd = Jd(company="A", title="Java", status="OPEN")
    with session_factory() as session:
        session.add(jd)
        session.commit()
    revision = JdRevision(
        jd_id=jd.id,
        source_text="Java 3年 本科",
        highest_degree="本科",
        status="READY",
        is_current=True,
        parsed_data={"summary": "Java 后端", "tech_direction": ["Java"]},
    )
    with session_factory() as session:
        session.add(revision)
        session.commit()

    service = MatchService(
        session_factory=session_factory,
        search_service=HybridSearchService(
            index=index,
            embedding_provider=LocalHashEmbeddingProvider(dimension=64),
            reranker_provider=LocalKeywordReranker(),
        ),
    )

    page = await service.match_jd(revision_id=revision.id, limit=20)

    assert [hit.candidate_id for hit in page.items] == ["cand-1"]