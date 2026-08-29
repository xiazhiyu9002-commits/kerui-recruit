from pathlib import Path

import pymupdf
import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.providers.fakes import FakeEmbeddingProvider
from kerui_recruit.resumes.ingest import IngestResume, ResumeIngestService
from kerui_recruit.resumes.pipeline import ResumePipeline
from kerui_recruit.resumes.structured import ParsedExperience, ParsedResume
from kerui_recruit.storage.blobs import BlobStore


class FixedResumeParser:
    async def parse_resume(self, text: str) -> ParsedResume:
        assert "Python Finance" in text
        return ParsedResume(
            name="张三",
            total_years=5,
            highest_degree="硕士",
            skills=["Python", "金融风控"],
            summary="金融科技后端工程师",
            experiences=[
                ParsedExperience(
                    company="示例科技",
                    title="后端工程师",
                    summary="负责 Python 风控平台",
                )
            ],
        )


class FixedOCRProvider:
    async def extract(self, content: bytes, filename: str) -> str:
        assert content.startswith(b"%PDF")
        assert filename.endswith(".pdf")
        return "Python Finance Resume recovered by OCR"


def make_pdf_bytes() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Python Finance Resume with five years")
    content = pdf.tobytes()
    pdf.close()
    return content


def make_blank_pdf_bytes() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()
    return content


@pytest.mark.asyncio
async def test_pipeline_persists_facts_and_builds_embedded_search_chunks(
    tmp_path: Path,
) -> None:
    """A parse task must atomically leave both usable facts and searchable content."""
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(
            IngestResume(filename="张三.pdf", content=make_pdf_bytes(), display_name="待解析")
        )
    pipeline = ResumePipeline(
        session_factory=factory,
        blob_store=store,
        parser=FixedResumeParser(),
        embedding_provider=FakeEmbeddingProvider(dimension=16),
    )

    result = await pipeline.run(ingested.revision_id)

    assert result.status == "READY"
    assert len(result.chunks) >= 2
    assert all(len(chunk.vector) == 16 for chunk in result.chunks)
    with Session(engine) as session:
        candidate = session.get(Candidate, ingested.candidate_id)
        revision = session.get(ResumeRevision, ingested.revision_id)
        assert candidate is not None
        assert candidate.display_name == "张三"
        assert str(candidate.total_years) == "5.0"
        assert candidate.highest_degree == "MASTER"
        assert revision is not None
        assert revision.status == "READY"
        assert revision.parsed_data["skills"] == ["Python", "金融风控"]


@pytest.mark.asyncio
async def test_pipeline_uses_ocr_provider_for_a_scanned_pdf(tmp_path: Path) -> None:
    """A scan without a text layer must be OCRed instead of silently indexing emptiness."""
    engine = create_engine_for(tmp_path / "db" / "recruit.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = BlobStore(tmp_path / "blobs", tmp_path / "temp")
    with factory() as session:
        ingested = ResumeIngestService(session, store).ingest(
            IngestResume(filename="扫描简历.pdf", content=make_blank_pdf_bytes())
        )
    pipeline = ResumePipeline(
        session_factory=factory,
        blob_store=store,
        parser=FixedResumeParser(),
        embedding_provider=FakeEmbeddingProvider(dimension=16),
        ocr_provider=FixedOCRProvider(),
    )

    result = await pipeline.run(ingested.revision_id)

    assert result.status == "READY"
    with Session(engine) as session:
        revision = session.get(ResumeRevision, ingested.revision_id)
        assert revision is not None
        assert revision.raw_text == "Python Finance Resume recovered by OCR"
