from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Jd, JdRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.jd.ingest import JdIngestService, IngestJd, JdIngestResult
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.providers.local import LocalJdParser


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return Session(engine)


def test_ingest_creates_jd_and_revision(session: Session) -> None:
    result = JdIngestService(session).ingest(
        IngestJd(company="某金融科技", title="Java 后端工程师", source_text="Java 3年 本科 金融")
    )

    assert isinstance(result, JdIngestResult)
    jd = session.scalars(select(Jd)).one()
    assert jd.company == "某金融科技"
    assert jd.status == "DRAFT"
    assert jd.revisions[0].status == "PENDING"


@pytest.mark.asyncio
async def test_pipeline_parses_jd_into_revision(session: Session) -> None:
    ingested = JdIngestService(session).ingest(
        IngestJd(company="某金融", title="Java", source_text="Java 后端 3年 本科 北京 金融支付")
    )
    pipeline = JdPipeline(session=session, parser=LocalJdParser())

    result = await pipeline.run(ingested.revision_id)

    assert result.status == "READY"
    revision = session.get(JdRevision, ingested.revision_id)
    assert revision.parsed_data is not None
    assert revision.status == "READY"