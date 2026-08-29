from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Jd, JdRevision
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


class FakeIndex:
    """In-memory index that honors hard filters deterministically."""

    def __init__(self):
        self.chunks: list[SearchChunk] = []

    def upsert(self, chunks: list[SearchChunk]) -> None:
        self.chunks.extend(chunks)

    def delete_revision(self, revision_id: str) -> None:
        self.chunks = [c for c in self.chunks if c.revision_id != revision_id]

    def search(self, request) -> list[SearchHit]:
        filtered = [
            c
            for c in self.chunks
            if (request.filters.min_years is None or (c.total_years or 0) >= request.filters.min_years)
            and (request.filters.highest_degree is None or c.highest_degree == request.filters.highest_degree)
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
    return sessionmaker(engine, expire_on_commit=False)


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
    jd = Jd(company="A", title="Java")
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
        index=index,
        embedding_provider=LocalHashEmbeddingProvider(dimension=64),
        reranker_provider=LocalKeywordReranker(),
    )

    page = await service.match_jd(
        revision_id=revision.id,
        candidates=CandidateFilters(min_years=5.0, highest_degree="MASTER"),
        limit=20,
    )

    assert [hit.candidate_id for hit in page.items] == ["cand-2"]