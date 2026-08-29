from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import BdLead, Candidate, ResumeRevision
from kerui_recruit.encryption.service import EncryptionService


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    source: str
    raw_content: str | None = None


class WebSearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[WebSearchResult]: ...


@dataclass(frozen=True, slots=True)
class LeadInfo:
    company: str | None
    job_title: str | None


class LeadExtractor(Protocol):
    def extract(
        self, title: str, snippet: str, raw_content: str | None = None
    ) -> LeadInfo: ...


class RegexLeadExtractor:
    """Deterministic fallback that extracts company/job from regex patterns."""

    def extract(
        self, title: str, snippet: str, raw_content: str | None = None
    ) -> LeadInfo:
        text = raw_content or snippet
        return LeadInfo(
            company=_extract_company(title, text),
            job_title=_extract_job_title(title, text),
        )


class BdSearchService:
    """Search the web for BD leads and persist them with encrypted PII."""

    _CACHE_TTL_SECONDS = 7 * 24 * 3600  # 同关键词 7 天内不重复查询

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        search_provider: WebSearchProvider,
        encryption: EncryptionService,
        extractor: LeadExtractor | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.search_provider = search_provider
        self.encryption = encryption
        self.extractor = extractor or RegexLeadExtractor()
        self._recent_searches: dict[str, float] = {}

    def search_leads(self, query: str, limit: int = 10) -> list[BdLead]:
        enhanced = _enhance_query(query)
        cached = self._recent_searches.get(enhanced)
        if cached is not None and (time.time() - cached) < self._CACHE_TTL_SECONDS:
            return self._existing_leads(enhanced)

        existing = self._existing_leads(enhanced)
        if existing:
            self._recent_searches[enhanced] = time.time()
            return existing

        results = self.search_provider.search(enhanced, limit=limit)
        leads = []
        with self.session_factory() as session:
            for r in results:
                info = self.extractor.extract(r.title, r.snippet, r.raw_content)
                lead = BdLead(
                    source=r.source,
                    query=enhanced,
                    company_name=self.encryption.encrypt(info.company or r.title),
                    job_title=self.encryption.encrypt(info.job_title) if info.job_title else None,
                    raw_snippet=r.snippet,
                    url=r.url,
                    status="新线索",
                )
                session.add(lead)
                leads.append(lead)
            session.commit()
        self._recent_searches[enhanced] = time.time()
        return leads

    def search_leads_for_candidate(
        self, candidate_id: str, limit: int = 10
    ) -> list[BdLead]:
        """以人找岗：从候选人技能/城市生成搜索式并检索线索."""
        queries = self.build_search_queries(candidate_id)
        merged: list[BdLead] = []
        seen: set[str] = set()
        for query in queries:
            for lead in self.search_leads(query, limit=limit):
                if lead.id not in seen:
                    seen.add(lead.id)
                    merged.append(lead)
        return merged

    def build_search_queries(self, candidate_id: str, max_queries: int = 3) -> list[str]:
        """Generate search queries from a candidate's skills and location."""
        with self.session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                raise LookupError(f"Candidate not found: {candidate_id}")

            revision = session.scalars(
                select(ResumeRevision)
                .where(
                    ResumeRevision.document.has(candidate_id=candidate_id),
                    ResumeRevision.is_current.is_(True),
                )
                .order_by(ResumeRevision.created_at.desc())
            ).first()

        parsed = (revision.parsed_data or {}) if revision is not None else {}
        skills = list(parsed.get("skills", []))[:3]
        location = parsed.get("location")
        summary = parsed.get("summary", "")

        queries: list[str] = []
        if skills:
            queries.append(" ".join(skills) + " 招聘")
        if summary:
            queries.append(summary[:40] + " 招聘")
        if location and skills:
            queries.append(f"{location} {' '.join(skills)} 招聘")
        if not queries:
            queries = ["技术 招聘"]
        return queries[:max_queries]

    def update_status(self, lead_id: str, status: str, note: str | None = None) -> BdLead:
        if status not in ("新线索", "已联系", "已定级", "已存档"):
            raise ValueError(f"Unknown lead status: {status}")

        with self.session_factory() as session:
            lead = session.get(BdLead, lead_id)
            if lead is None:
                raise LookupError(f"BdLead not found: {lead_id}")
            lead.status = status
            if note is not None:
                lead.note = note
            session.commit()
            return lead

    def _existing_leads(self, query: str) -> list[BdLead]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(BdLead).where(
                        BdLead.query == query,
                        BdLead.deleted_at.is_(None),
                    )
                ).all()
            )


# --- Query enhancement ---

_QUERY_SUFFIX = " 招聘 公司直招 官网"
_QUERY_INTENT_KEYWORDS = ("招聘", "直招", "官网", "careers", "社招", "jobs", "加入")


def _enhance_query(query: str) -> str:
    """Append a recruitment intent so results hit company career pages.

    Aggregator pages (e.g. liepin lists) rarely name a single company, which
    defeats company extraction. Nudging the query toward company career pages
    yields richer, single-company content.
    """
    if any(keyword in query for keyword in _QUERY_INTENT_KEYWORDS):
        return query
    return f"{query}{_QUERY_SUFFIX}"


# --- Regex-based extractors ---

_COMPANY_PATTERNS = re.compile(
    r"([\u4e00-\u9fff\w]+"
    r"(?:有限公司|股份公司|集团|科技|网络|信息|数据|软件|咨询|投资|金融|银行|保险|"
    r"Inc\.?|Ltd\.?|LLC|Corp\.?|Co\.?|Limited|Corporation))",
    re.IGNORECASE,
)

_JOB_PATTERNS = re.compile(
    r"([\u4e00-\u9fff\w]+"
    r"(?:工程师|经理|总监|主管|架构师|设计师|分析师|专员|顾问|代表|"
    r"Engineer|Manager|Director|Lead|Architect|Designer|Analyst|Specialist|Consultant))",
    re.IGNORECASE,
)


def _extract_company(title: str, snippet: str) -> str | None:
    text = f"{title} {snippet}"
    matches = _COMPANY_PATTERNS.findall(text)
    return matches[0] if matches else None


def _extract_job_title(title: str, snippet: str) -> str | None:
    text = f"{title} {snippet}"
    matches = _JOB_PATTERNS.findall(text)
    return matches[0] if matches else None