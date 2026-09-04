from __future__ import annotations

import pymupdf
import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.models import DirectionDecision, DirectionProfile, build_direction_label
from kerui_recruit.providers.fakes import FakeEmbeddingProvider
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.resumes.pipeline import ResumePipeline
from kerui_recruit.resumes.structured import ParsedExperience, ParsedResume
from kerui_recruit.storage.blobs import BlobStore


class FixedResumeParser:
    async def parse_resume(self, _text: str) -> ParsedResume:
        return ParsedResume(
            name="张三",
            total_years=5,
            highest_degree="硕士",
            skills=["Java", "Spring"],
            summary="后端工程师",
            experiences=[ParsedExperience(company="示例科技", title="后端开发工程师", summary="负责后端服务端开发")],
        )


def make_pdf_bytes() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Backend Engineer Resume")
    content = pdf.tobytes()
    pdf.close()
    return content


class FakeDirectionClassifier:
    def __init__(self, decision: DirectionDecision | None = None, error: Exception | None = None):
        self.decision = decision
        self.error = error
        self.calls = 0

    async def classify(self, payload) -> DirectionDecision:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision


def _decision(primary: str = "BACKEND") -> DirectionDecision:
    profile = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(primary, source="LLM", confidence=0.9, is_primary=True),
    ])
    return DirectionDecision(effective_profile=profile, agreement=True, decision_reason="test")


def _setup(tmp_path):
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(
            IngestResume(filename="张三.pdf", content=make_pdf_bytes())
        )
    return engine, factory, store, ingested


@pytest.mark.asyncio
async def test_pipeline_classifies_direction(tmp_path) -> None:
    engine, factory, store, ingested = _setup(tmp_path)
    classifier = FakeDirectionClassifier(decision=_decision("BACKEND"))
    pipeline = ResumePipeline(
        session_factory=factory, blob_store=store, parser=FixedResumeParser(),
        embedding_provider=FakeEmbeddingProvider(dimension=16), direction_classifier=classifier,
    )
    result = await pipeline.run(ingested.revision_id)
    assert result.status == "READY"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, ingested.revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert revision.review_data["direction_profile"]["role_families"][0]["code"] == "BACKEND"
        assert "direction_diagnostics" in revision.review_data
    assert classifier.calls == 1


@pytest.mark.asyncio
async def test_pipeline_skips_llm_with_manual_override(tmp_path) -> None:
    engine, factory, store, ingested = _setup(tmp_path)
    manual = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("AI_ML", source="USER", confidence=1.0, is_primary=True),
    ]).model_dump(mode="json")
    with factory() as session:
        revision = session.get(ResumeRevision, ingested.revision_id)
        revision.manual_overrides = {"direction_profile": manual}
        session.commit()
    classifier = FakeDirectionClassifier(decision=_decision("BACKEND"))
    pipeline = ResumePipeline(
        session_factory=factory, blob_store=store, parser=FixedResumeParser(),
        embedding_provider=FakeEmbeddingProvider(dimension=16), direction_classifier=classifier,
    )
    result = await pipeline.run(ingested.revision_id)
    assert result.status == "READY"
    assert classifier.calls == 0
    with Session(engine) as session:
        revision = session.get(ResumeRevision, ingested.revision_id)
        assert revision.parsed_data["direction_profile"]["role_families"][0]["code"] == "AI_ML"
        assert revision.parsed_data["direction_profile"]["role_families"][0]["source"] == "USER"


@pytest.mark.asyncio
async def test_pipeline_direction_not_in_chunk_content(tmp_path) -> None:
    engine, factory, store, ingested = _setup(tmp_path)
    classifier = FakeDirectionClassifier(decision=_decision("BACKEND"))
    pipeline = ResumePipeline(
        session_factory=factory, blob_store=store, parser=FixedResumeParser(),
        embedding_provider=FakeEmbeddingProvider(dimension=16), direction_classifier=classifier,
    )
    result = await pipeline.run(ingested.revision_id)
    assert result.status == "READY"
    for chunk in result.chunks:
        assert "direction_profile" not in chunk.content
