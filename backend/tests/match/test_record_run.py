from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Jd, JdRevision, MatchResult, MatchRun
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.match.service import MatchService
from kerui_recruit.providers.local import (
    LocalHashEmbeddingProvider,
    LocalKeywordReranker,
)
from kerui_recruit.search.contracts import SearchHit


class FakeIndex:
    def search(self, request) -> list[SearchHit]:
        return []


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_record_run_persists_snapshot(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        jd = Jd(company="A", title="Java")
        session.add(jd)
        session.commit()
        revision = JdRevision(
            jd_id=jd.id,
            source_text="Java 5年",
            min_years=Decimal("5.0"),
            status="READY",
            is_current=True,
            parsed_data={"summary": "Java 金融", "tech_direction": ["Java"]},
        )
        session.add(revision)
        session.commit()

        service = MatchService(
            session_factory=session_factory,
            index=FakeIndex(),
            embedding_provider=LocalHashEmbeddingProvider(dimension=64),
            reranker_provider=LocalKeywordReranker(),
        )
        run_id = service.record_run(
            revision_id=revision.id,
            hits=[
                SearchHit(
                    chunk_id="c1",
                    candidate_id="cand-1",
                    revision_id="rev-1",
                    content="Java 支付",
                    score=0.9,
                    matched_channels=("bm25",),
                    total_years=6.0,
                    highest_degree="MASTER",
                    location="上海",
                )
            ],
        )

    with session_factory() as session:
        run = session.get(MatchRun, run_id)
        assert run is not None
        assert run.trigger == "JD_MATCH"
        result = session.scalars(select(MatchResult)).one()
        assert result.candidate_id == "cand-1"
        assert result.total_score is not None