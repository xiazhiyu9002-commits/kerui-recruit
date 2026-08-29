from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate, Jd, JdRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.match.service import MatchService
from kerui_recruit.providers.local import LocalHashEmbeddingProvider, LocalKeywordReranker
from kerui_recruit.scheduler.service import SchedulerService
from kerui_recruit.search.contracts import SearchChunk, SearchHit


class FakeIndex:
    def __init__(self, chunks: list[SearchChunk]) -> None:
        self.chunks = chunks

    def upsert(self, chunks: list[SearchChunk]) -> None:
        self.chunks.extend(chunks)

    def delete_revision(self, revision_id: str) -> None:
        self.chunks = [c for c in self.chunks if c.revision_id != revision_id]

    def search(self, request) -> list[SearchHit]:
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
            for c in self.chunks
        ]


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_reverse_match_candidate_finds_open_jds(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = Candidate(display_name="张三", status="AVAILABLE")
        jd = Jd(company="某公司", title="Java", status="OPEN")
        session.add_all([candidate, jd])
        session.commit()
        revision = JdRevision(
            jd_id=jd.id,
            source_text="Java 3年",
            status="READY",
            is_current=True,
            parsed_data={"summary": "Java 后端", "tech_direction": ["Java"]},
        )
        session.add(revision)
        session.commit()
        candidate_id, revision_id = candidate.id, revision.id

    index = FakeIndex(
        [
            SearchChunk(
                id="c1",
                candidate_id=candidate_id,
                revision_id="rev-1",
                content="Java 后端工程师",
                vector=[0.1],
                total_years=4.0,
                highest_degree="BACHELOR",
                location="上海",
                candidate_status="AVAILABLE",
            )
        ]
    )
    match_service = MatchService(
        session_factory=session_factory,
        index=index,
        embedding_provider=LocalHashEmbeddingProvider(dimension=64),
        reranker_provider=LocalKeywordReranker(),
    )
    scheduler = SchedulerService(
        session_factory=session_factory,
        match_service=match_service,
        reminder_service=None,
    )

    matches = await scheduler.reverse_match_candidate(candidate_id)

    assert len(matches) == 1
    assert matches[0].jd_id == jd.id
    assert matches[0].company == "某公司"
    assert matches[0].title == "Java"
