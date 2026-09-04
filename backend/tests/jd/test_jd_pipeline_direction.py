from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import JdRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.models import DirectionDecision, DirectionProfile, build_direction_label
from kerui_recruit.jd.ingest import IngestJd, JdIngestService
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.jd.structured import ParsedJd


class FixedJdParser:
    async def parse_jd(self, _text: str) -> ParsedJd:
        return ParsedJd(
            title="后端开发工程师",
            company="示例",
            core_duties=["负责后端服务端开发"],
            required_skills=["Java"],
        )

    async def split_jds(self, text: str) -> list[str]:
        return [text]


class FakeDirectionClassifier:
    def __init__(self, decision: DirectionDecision | None = None):
        self.decision = decision
        self.calls = 0

    async def classify(self, payload) -> DirectionDecision:
        self.calls += 1
        assert self.decision is not None
        return self.decision


def _decision(primary: str = "BACKEND") -> DirectionDecision:
    profile = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(primary, source="LLM", confidence=0.9, is_primary=True),
    ])
    return DirectionDecision(effective_profile=profile, agreement=True, decision_reason="test")


@pytest.mark.asyncio
async def test_jd_pipeline_classifies_direction(tmp_path) -> None:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        ingested = JdIngestService(session).ingest(
            IngestJd(company="某金融", title="Java", source_text="Java 后端")
        )
    classifier = FakeDirectionClassifier(decision=_decision("BACKEND"))
    pipeline = JdPipeline(session_factory=factory, parser=FixedJdParser(), direction_classifier=classifier)
    result = await pipeline.run(ingested.revision_id)
    assert result.status == "READY"
    with Session(engine) as session:
        revision = session.get(JdRevision, ingested.revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
    assert classifier.calls == 1
