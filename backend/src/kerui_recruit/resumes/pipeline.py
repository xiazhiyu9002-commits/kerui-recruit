from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.base import new_id
from kerui_recruit.db.models import Candidate, ResumeRevision
from kerui_recruit.providers.contracts import EmbeddingProvider, OCRProvider
from kerui_recruit.resumes.extract import extract_text
from kerui_recruit.resumes.normalize import normalize_resume
from kerui_recruit.resumes.structured import NormalizedResume, ResumeParser
from kerui_recruit.search.contracts import SearchChunk, SearchIndex
from kerui_recruit.storage.blobs import BlobStore


_DEGREE_SHORT = {
    "博士": "博",
    "硕士": "硕",
    "本科": "本",
    "大专": "专",
    "PhD": "博",
    "Master": "硕",
    "Bachelor": "本",
}


def build_display_name(resume: NormalizedResume, suffix: str) -> str:
    """Generate a human-readable resume display name from parsed fields."""
    parts: list[str] = [resume.name or "未知"]
    if resume.total_years is not None:
        parts.append(f"{int(resume.total_years)}年")
    degree = resume.highest_degree or ""
    if degree:
        parts.append(_DEGREE_SHORT.get(degree, degree))
    skills = list(resume.skills)[:2]
    if skills:
        parts.append("+".join(skills))
    return "-".join(parts) + suffix


@dataclass(frozen=True, slots=True)
class PipelineResult:
    candidate_id: str
    revision_id: str
    status: str
    chunks: tuple[SearchChunk, ...]


class ResumePipeline:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        blob_store: BlobStore,
        parser: ResumeParser,
        embedding_provider: EmbeddingProvider,
        ocr_provider: OCRProvider | None = None,
        search_index: SearchIndex | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.blob_store = blob_store
        self.parser = parser
        self.embedding_provider = embedding_provider
        self.ocr_provider = ocr_provider
        self.search_index = search_index

    async def run(self, revision_id: str) -> PipelineResult:
        with self.session_factory() as session:
            revision = session.get(ResumeRevision, revision_id)
            if revision is None:
                raise LookupError(f"Resume revision not found: {revision_id}")
            revision.status = "PROCESSING"
            candidate_id = revision.document.candidate_id
            source_path = self.blob_store.root / revision.blob.storage_path
            original_filename = revision.original_filename
            session.commit()

        extracted = extract_text(source_path)
        if extracted.requires_ocr:
            if self.ocr_provider is None:
                raise RuntimeError("E_OCR_REQUIRED")
            source_text = await self.ocr_provider.extract(
                source_path.read_bytes(),
                original_filename,
            )
        else:
            source_text = extracted.text
        parsed = await self.parser.parse_resume(source_text)
        normalized = normalize_resume(parsed)
        contents = self._build_chunk_contents(normalized)
        vectors = await self.embedding_provider.embed_documents(contents)
        chunks = tuple(
            SearchChunk(
                id=new_id(),
                candidate_id=candidate_id,
                revision_id=revision_id,
                content=content,
                vector=tuple(vector),
                total_years=(
                    float(normalized.total_years) if normalized.total_years else None
                ),
                highest_degree=normalized.highest_degree,
                location=normalized.location,
                candidate_status="AVAILABLE",
            )
            for content, vector in zip(contents, vectors, strict=True)
        )
        if self.search_index is not None:
            self.search_index.delete_revision(revision_id)
            self.search_index.upsert(list(chunks))

        with self.session_factory() as session, session.begin():
            revision = session.get(ResumeRevision, revision_id)
            if revision is None:
                raise LookupError(f"Resume revision not found: {revision_id}")
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                raise LookupError(f"Candidate not found: {candidate_id}")
            candidate.display_name = normalized.name
            candidate.total_years = normalized.total_years
            candidate.highest_degree = normalized.highest_degree
            candidate.status = "AVAILABLE"
            revision.raw_text = source_text
            revision.parsed_data = normalized.model_dump(mode="json")
            revision.parse_version = "resume-schema-v1"
            revision.status = "READY"
            revision.display_name = build_display_name(
                normalized, Path(revision.original_filename).suffix.lower()
            )
        return PipelineResult(
            candidate_id=candidate_id,
            revision_id=revision_id,
            status="READY",
            chunks=chunks,
        )

    @staticmethod
    def _build_chunk_contents(resume: NormalizedResume) -> list[str]:
        profile = " ".join(
            value
            for value in (
                resume.name,
                resume.summary,
                resume.highest_degree or "",
                str(resume.total_years or ""),
                " ".join(resume.skills),
            )
            if value
        )
        contents = [profile]
        contents.extend(
            f"{experience.title} {experience.company} {experience.summary}".strip()
            for experience in resume.experiences
        )
        contents.extend(
            f"{project.name} {project.summary}".strip() for project in resume.projects
        )
        return contents
