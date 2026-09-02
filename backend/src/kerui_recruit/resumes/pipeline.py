from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.base import new_id
from kerui_recruit.db.models import Candidate, CandidateContact, ResumeRevision
from kerui_recruit.encryption.service import EncryptionService
from kerui_recruit.providers.contracts import EmbeddingProvider, OCRProvider
from kerui_recruit.providers.errors import ProviderError
from kerui_recruit.resumes.extract import (
    ExtractedText,
    extract_contact,
    extract_text,
)
from kerui_recruit.resumes.normalize import normalize_resume
from kerui_recruit.resumes.quality import (
    DOMINANT_FRAGMENT_RATIO,
    analyze_text,
)
from kerui_recruit.resumes.structured import NormalizedResume, ParsedResume, ResumeParser
from kerui_recruit.resumes.validity import check_parsed_resume
from kerui_recruit.search.contracts import SearchChunk, SearchIndex
from kerui_recruit.storage.blobs import BlobStore

logger = logging.getLogger(__name__)


_DEGREE_SHORT = {
    "博士": "博",
    "硕士": "硕",
    "本科": "本",
    "大专": "专",
    "PhD": "博",
    "Master": "硕",
    "Bachelor": "本",
}


class PipelineFailure(RuntimeError):
    """解析流水线的可分类失败；``code`` 会被任务与修订版本记录。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


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
        defer_indexing: bool = False,
        encryption_service: EncryptionService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.blob_store = blob_store
        self.parser = parser
        self.embedding_provider = embedding_provider
        self.ocr_provider = ocr_provider
        self.search_index = search_index
        self.defer_indexing = defer_indexing
        self.encryption_service = encryption_service

    async def run(self, revision_id: str, *, force_ocr: bool = False) -> PipelineResult:
        with self.session_factory() as session:
            revision = session.get(ResumeRevision, revision_id)
            if revision is None:
                raise LookupError(f"Resume revision not found: {revision_id}")
            previous_ready = revision.status == "READY"
            candidate_id = revision.document.candidate_id
            source_path = self.blob_store.root / revision.blob.storage_path
            original_filename = revision.original_filename
            candidate_status = revision.document.candidate.status
            revision.status = "PROCESSING"
            session.commit()

        try:
            content = await asyncio.to_thread(source_path.read_bytes)
            extracted = await asyncio.to_thread(extract_text, source_path)
            diagnostics = {
                "page_count": extracted.page_count, "forced_ocr": force_ocr,
                "pages": [dict(
                    {key: value for key, value in asdict(page).items() if key != "text"},
                    route="ocr" if force_ocr or page.needs_ocr else "direct",
                ) for page in extracted.pages],
            }
            self._persist_evidence(revision_id, diagnostics, extracted.text, previous_ready)
            source_text = await self._resolve_source_text(
                content, original_filename, extracted, force_ocr
            )
            self._persist_evidence(revision_id, diagnostics, source_text, previous_ready)
            contact = extract_contact(source_text)
            parsed = await self.parser.parse_resume(source_text)
            with self.session_factory() as session, session.begin():
                revision = session.get(ResumeRevision, revision_id)
                revision.review_data = parsed.model_dump(mode="json")
                overrides = dict(revision.manual_overrides or {})
                parsed = ParsedResume.model_validate({
                    **parsed.model_dump(mode="json"), **overrides,
                })
            validity = check_parsed_resume(parsed, source_text)
            if not validity.ok:
                raise PipelineFailure(validity.error_code or "E_STRUCTURED_EMPTY", validity.reason)
            normalized = normalize_resume(parsed)
            # Age is a derived display field rather than a ParsedResume field;
            # preserve explicit human values, including an intentional clear.
            if "age" in overrides:
                normalized = normalized.model_copy(update={"age": overrides["age"]})
            contents = self._build_chunk_contents(normalized)
            # The runtime delegates embedding to the durable index outbox. A
            # provider outage must not discard a successfully parsed revision.
            vectors = [] if self.defer_indexing else await self.embedding_provider.embed_documents(contents)
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
                    candidate_status=("AVAILABLE" if candidate_status == "PENDING_REVIEW" else candidate_status),
                    qs_rank=normalized.qs_rank,
                    school_level=normalized.school_level,
                    preferred_location=normalized.preferred_location,
                    preferred_locations=normalized.preferred_locations,
                )
                for content, vector in zip([] if self.defer_indexing else contents, vectors, strict=True)
            )
            self._persist_ready(
                revision_id,
                candidate_id,
                original_filename,
                normalized,
                contact,
                source_text,
                overrides,
            )
            if self.search_index is not None:
                def update_search_projection() -> None:
                    self.search_index.delete_revision(revision_id)
                    self.search_index.upsert(list(chunks))

                await asyncio.to_thread(update_search_projection)
        except asyncio.CancelledError:
            # The worker may cancel while extraction/OCR/provider code is
            # awaiting. Compensate the already committed PROCESSING state so
            # the revision can be reviewed or explicitly reparsed.
            self._mark_failed(
                revision_id,
                "E_TASK_CANCELLED",
                "解析任务已取消，可重新发起解析",
                previous_ready,
            )
            raise
        except PipelineFailure as failure:
            self._mark_failed(revision_id, failure.code, failure.message, previous_ready)
            raise
        except ProviderError as error:
            self._mark_failed(revision_id, error.code, error.user_message, previous_ready)
            raise
        except Exception as error:  # noqa: BLE001 - record a categorized extraction failure
            self._mark_failed(
                revision_id,
                "E_EXTRACTION_FAILED",
                str(error)[:2_000] or "文档提取失败",
                previous_ready,
            )
            raise

        return PipelineResult(
            candidate_id=candidate_id,
            revision_id=revision_id,
            status="READY",
            chunks=chunks,
        )

    async def _resolve_source_text(
        self,
        content: bytes,
        filename: str,
        extracted: ExtractedText,
        force_ocr: bool,
    ) -> str:
        """按页决定是否需要 OCR，并在页序合并后返回正文。

        普通页面保留直接提取结果，异常页面用 OCR 替换，来源信息写入日志，
        避免把水印当正文、也避免重复拼接两套正文。
        """
        pages = extracted.pages
        if not pages:
            return extracted.text

        if force_ocr:
            ocr_indexes = list(range(len(pages)))
        else:
            ocr_indexes = [page.page_index for page in pages if page.needs_ocr]

        for page in pages:
            if page.needs_ocr:
                logger.info(
                    "resume page %s needs OCR: %s (valid=%s repeated=%.0f%% dominant=%.0f%%)",
                    page.page_index + 1,
                    page.reason,
                    page.valid_char_count,
                    page.repeated_ratio * 100,
                    page.dominant_ratio * 100,
                )

        if not ocr_indexes:
            return extracted.text

        if self.ocr_provider is None:
            raise PipelineFailure(
                "E_OCR_REQUIRED",
                "该文件需要 OCR 识别，但尚未配置 OCR 服务，无法继续解析",
            )

        ocr_texts = await self._ocr_pages(content, filename, ocr_indexes)
        if len(ocr_texts) != len(ocr_indexes):
            raise PipelineFailure("E_OCR_INCOMPLETE", "OCR 返回页数不完整，请人工复核")
        ocr_map: dict[int, str] = {}
        for index, text in zip(ocr_indexes, ocr_texts, strict=True):
            self._validate_ocr_page(index, text)
            ocr_map[index] = text

        merged: list[str] = []
        for page in pages:
            text = ocr_map.get(page.page_index, page.text)
            if text.strip():
                merged.append(text)
        return "\n".join(merged)

    async def _ocr_pages(
        self,
        content: bytes,
        filename: str,
        page_indexes: list[int],
    ) -> list[str]:
        if hasattr(self.ocr_provider, "extract_pages"):
            return await self.ocr_provider.extract_pages(content, filename, page_indexes)
        # Legacy providers must receive the requested page only: reusing the
        # whole document for each page duplicates and misorders resume evidence.
        results = []
        with pymupdf.open(stream=content, filetype="pdf") as document:
            for index in page_indexes:
                with pymupdf.open() as single:
                    single.insert_pdf(document, from_page=index, to_page=index)
                    page_content = single.tobytes()
                results.append(await self.ocr_provider.extract(page_content, filename))
        return results

    @staticmethod
    def _validate_ocr_page(page_index: int, text: str) -> None:
        if not text or not text.strip():
            raise PipelineFailure("E_OCR_EMPTY", f"第 {page_index + 1} 页 OCR 未识别到文字")
        quality = analyze_text(text)
        if quality.valid_char_count == 0 or quality.dominant_ratio >= DOMINANT_FRAGMENT_RATIO:
            raise PipelineFailure(
                "E_OCR_LOW_QUALITY",
                f"第 {page_index + 1} 页 OCR 结果没有有效正文或仍以重复水印为主，请人工复核",
            )

    def _persist_ready(
        self,
        revision_id: str,
        candidate_id: str,
        original_filename: str,
        normalized: NormalizedResume,
        contact,
        source_text: str,
        expected_overrides: dict,
    ) -> None:
        with self.session_factory() as session, session.begin():
            revision = session.get(ResumeRevision, revision_id)
            if revision is None:
                raise LookupError(f"Resume revision not found: {revision_id}")
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                raise LookupError(f"Candidate not found: {candidate_id}")
            if (revision.manual_overrides or {}) != expected_overrides:
                raise PipelineFailure(
                    "E_REPARSE_CONFLICT", "解析期间有人工修改，已保留人工修订，请重新解析", retryable=True,
                )
            if revision.is_current:
                candidate.display_name = normalized.name or Path(original_filename).stem
                candidate.total_years = normalized.total_years
                candidate.highest_degree = normalized.highest_degree
                if candidate.status == "PENDING_REVIEW":
                    candidate.status = "AVAILABLE"
            if revision.is_current and self.encryption_service is not None and (contact.email or contact.phone):
                existing = session.scalar(
                    select(CandidateContact).where(
                        CandidateContact.candidate_id == candidate_id
                    )
                )
                if existing is None:
                    existing = CandidateContact(candidate=candidate)
                    session.add(existing)
                manual_fields = existing.manual_fields or []
                if "email" not in manual_fields and existing.email_confidence != 1.0:
                    existing.email_encrypted = (
                        self.encryption_service.encrypt(contact.email)
                        if contact.email else None
                    )
                    existing.email_confidence = 0.9 if contact.email else None
                if "phone" not in manual_fields and existing.phone_confidence != 1.0:
                    existing.phone_encrypted = (
                        self.encryption_service.encrypt(contact.phone)
                        if contact.phone else None
                    )
                    existing.phone_confidence = 0.9 if contact.phone else None
            revision.raw_text = source_text
            revision.parsed_data = normalized.model_dump(mode="json")
            revision.parse_version = "resume-schema-v1"
            revision.status = "READY"
            revision.error_code = None
            revision.error_message = None
            revision.display_name = build_display_name(
                normalized, Path(revision.original_filename).suffix.lower()
            )
            if revision.is_current:
                from kerui_recruit.search.sync import enqueue_sync
                enqueue_sync(session, "candidate", candidate.id)

    def _persist_evidence(self, revision_id: str, diagnostics: dict, text: str, previous_ready: bool) -> None:
        with self.session_factory() as session, session.begin():
            revision = session.get(ResumeRevision, revision_id)
            revision.extraction_diagnostics = {**diagnostics, "source_text": text}
            if not previous_ready:
                revision.raw_text = text

    def _mark_failed(
        self,
        revision_id: str,
        code: str,
        message: str,
        previous_ready: bool,
    ) -> None:
        with self.session_factory() as session, session.begin():
            revision = session.get(ResumeRevision, revision_id)
            if revision is None:
                return
            if previous_ready:
                # 重新解析失败：保留上一次有效画像与索引，仅由任务记录本次失败。
                revision.status = "READY"
                revision.error_code = None
                revision.error_message = None
            else:
                revision.status = "FAILED"
                revision.error_code = code
                revision.error_message = message[:2_000]
                candidate = revision.document.candidate
                if revision.is_current and candidate.status == "AVAILABLE":
                    candidate.status = "PENDING_REVIEW"
                    from kerui_recruit.search.sync import enqueue_sync
                    enqueue_sync(session, "candidate", candidate.id)
            revision.extraction_diagnostics = {
                **(revision.extraction_diagnostics or {}),
                "last_error": {"code": code, "message": message[:2_000]},
            }

    @staticmethod
    def _build_chunk_contents(resume: NormalizedResume) -> list[str]:
        return build_chunk_contents_from_dict(resume.model_dump())


def build_chunk_contents_from_dict(data: dict) -> list[str]:
    """Build search-index chunk contents from a normalized resume dict.

    This is the single source of truth for what enters the vector/embedding
    index. Keep it in sync with the fields the pipeline exposes when editing.
    """
    skills = _as_list(data.get("skills"))
    tech = _as_list(data.get("tech_direction"))
    business = _as_list(data.get("business_direction"))
    profile = " ".join(
        value
        for value in (
            data.get("name"),
            data.get("summary"),
            data.get("highest_degree") or "",
            str(data.get("total_years") or ""),
            data.get("school") or "",
            f"QS{data.get('qs_rank')}" if data.get("qs_rank") else "",
            str(data.get("graduation_year") or ""),
            data.get("industry") or "",
            data.get("current_industry") or "",
            data.get("longest_industry") or "",
            " ".join(str(skill) for skill in skills),
            f"技术方向:{' '.join(tech)}" if tech else "",
            f"业务方向:{' '.join(business)}" if business else "",
        )
        if value
    )
    contents = [profile]
    for experience in data.get("experiences") or []:
        parts = [
            experience.get("title"),
            experience.get("company"),
            experience.get("industry"),
            experience.get("summary"),
        ]
        contents.append(" ".join(str(p) for p in parts if p).strip())
    for project in data.get("projects") or []:
        parts = [
            project.get("name"),
            project.get("tech_stack"),
            project.get("business_scene"),
            project.get("summary"),
        ]
        contents.append(" ".join(str(p) for p in parts if p).strip())
    return contents


def _as_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    return [str(value)]
