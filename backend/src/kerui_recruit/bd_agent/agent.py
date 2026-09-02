from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.bd_agent.evidence import EvidenceDoc, EvidenceExtractor, RankedChunk
from kerui_recruit.bd_agent.fetcher import WebFetcher
from kerui_recruit.bd_agent.planner import QueryPlanner
from kerui_recruit.bd_agent.synthesis import SynthesisGenerator, SynthesisResult
from kerui_recruit.bd_search.service import BdSearchService, WebSearchProvider
from kerui_recruit.db.models import BdEvidence, BdLead, BdSearchSession
from kerui_recruit.encryption.service import EncryptionService


@dataclass(frozen=True, slots=True)
class AgentResult:
    session_id: str
    leads: list[BdLead]


class BdAgent:
    """Orchestrate the multi-step deep BD search: plan -> search -> fetch ->
    rank evidence -> synthesize cited leads, with a round/query budget and a
    graceful fallback to the simple search when the LLM is unavailable."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        search_provider: WebSearchProvider,
        fetcher: WebFetcher,
        encryption: EncryptionService,
        planner: QueryPlanner | None = None,
        evidence_extractor: EvidenceExtractor | None = None,
        synthesizer: SynthesisGenerator | None = None,
        fallback: BdSearchService | None = None,
        max_rounds: int = 3,
        max_queries: int = 8,
    ) -> None:
        self.session_factory = session_factory
        self.search_provider = search_provider
        self.fetcher = fetcher
        self.encryption = encryption
        self.planner = planner
        self.evidence_extractor = evidence_extractor or EvidenceExtractor()
        self.synthesizer = synthesizer
        self.fallback = fallback
        self.max_rounds = max_rounds
        self.max_queries = max_queries

    async def run(
        self,
        query: str,
        kind: str = "text",
        limit: int = 10,
        progress: asyncio.Queue | None = None,
    ) -> AgentResult:
        if self.planner is None or self.synthesizer is None:
            await self._emit(progress, "degraded", "未配置 LLM，使用基础搜索")
            return self._run_fallback(query, limit)

        await self._emit(progress, "planning", "正在规划搜索式…")
        session_id = self._create_session(query, kind)
        return await self._run_query(query, session_id, limit, progress)

    async def follow_up(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        progress: asyncio.Queue | None = None,
    ) -> AgentResult:
        if self.planner is None or self.synthesizer is None:
            await self._emit(progress, "degraded", "未配置 LLM，使用基础搜索")
            return self._run_fallback(query, limit)
        if not self._session_exists(session_id):
            raise LookupError(f"BdSearchSession not found: {session_id}")
        return await self._run_query(query, session_id, limit, progress)

    # --- internals ---

    async def _emit(
        self, progress: asyncio.Queue | None, stage: str, message: str
    ) -> None:
        if progress is not None:
            await progress.put({"stage": stage, "message": message})

    async def _run_query(
        self,
        query: str,
        session_id: str,
        limit: int,
        progress: asyncio.Queue | None,
    ) -> AgentResult:
        queries = await self.planner.plan(query)  # type: ignore[union-attr]
        await self._emit(progress, "planned", f"规划出 {len(queries)} 条搜索式")
        seen_queries: set[str] = set()
        docs_by_url: dict[str, EvidenceDoc] = {}

        for _round in range(self.max_rounds):
            await self._emit(progress, "searching", f"第 {_round + 1} 轮搜索中…")
            round_docs = await self._search_and_fetch(queries, limit, seen_queries)
            for doc in round_docs:
                docs_by_url.setdefault(doc.source_url, doc)

            await self._emit(progress, "fetched", f"已抓取 {len(docs_by_url)} 个页面")
            chunks = await self.evidence_extractor.extract(query, list(docs_by_url.values()))
            await self._emit(progress, "ranking", f"重排出 {len(chunks)} 个证据片段")
            synthesis = await self.synthesizer.synthesize(query, chunks)  # type: ignore[union-attr]
            await self._emit(progress, "synthesized", f"综合出 {len(synthesis.leads)} 条线索")
            leads = self._persist(session_id, query, synthesis)

            if not self._should_continue(synthesis, _round, queries):
                await self._emit(progress, "done", "完成")
                return AgentResult(session_id=session_id, leads=leads)
            queries = synthesis.follow_up_queries or []

        await self._emit(progress, "done", "完成")
        return AgentResult(session_id=session_id, leads=[])

    async def _search_and_fetch(
        self,
        queries: list[str],
        limit: int,
        seen_queries: set[str],
    ) -> list[EvidenceDoc]:
        docs: list[EvidenceDoc] = []
        for query in queries:
            if query in seen_queries or len(seen_queries) >= self.max_queries:
                continue
            seen_queries.add(query)
            results = await asyncio.to_thread(
                self.search_provider.search, query, limit
            )
            for result in results:
                content = result.raw_content
                if not content:
                    content = await self.fetcher.fetch(result.url)
                if not content:
                    content = result.snippet
                docs.append(
                    EvidenceDoc(
                        source_url=result.url,
                        title=result.title,
                        content=content,
                    )
                )
        return docs

    def _should_continue(
        self,
        synthesis: SynthesisResult,
        round_index: int,
        queries: list[str],
    ) -> bool:
        if round_index >= self.max_rounds - 1:
            return False
        if not synthesis.needs_more_search:
            return False
        return bool(synthesis.follow_up_queries)

    def _persist(
        self,
        session_id: str,
        query: str,
        synthesis: SynthesisResult,
    ) -> list[BdLead]:
        leads: list[BdLead] = []
        with self.session_factory() as session:
            for item in synthesis.leads:
                company = item.company or "未识别公司"
                lead = BdLead(
                    source="agent",
                    query=query,
                    company_name=self.encryption.encrypt(company),
                    job_title=(
                        self.encryption.encrypt(item.job_title)
                        if item.job_title
                        else None
                    ),
                    raw_snippet=item.summary,
                    url=(item.evidence[0].source_url if item.evidence else None),
                    status="新线索",
                    confidence=item.confidence,
                    is_hiring=item.is_hiring,
                    session_id=session_id,
                    synthesized_json=item.model_dump(),
                    posted_time=item.posted_time,
                    salary_range=item.salary_range,
                    level=item.level,
                    requirements=item.requirements or None,
                )
                session.add(lead)
                session.flush()
                for evidence in item.evidence:
                    lead.evidence.append(
                        BdEvidence(
                            claim=evidence.claim,
                            quote=evidence.quote,
                            source_url=evidence.source_url,
                            relevance_score=None,
                        )
                    )
                leads.append(lead)
            session.commit()
        return leads

    def _create_session(self, query: str, kind: str) -> str:
        with self.session_factory() as session:
            search_session = BdSearchSession(query=query, kind=kind)
            session.add(search_session)
            session.commit()
            return search_session.id

    def _session_exists(self, session_id: str) -> bool:
        with self.session_factory() as session:
            return session.get(BdSearchSession, session_id) is not None

    def _run_fallback(self, query: str, limit: int) -> AgentResult:
        if self.fallback is None:
            return AgentResult(session_id="", leads=[])
        leads = self.fallback.search_leads(query, limit)
        return AgentResult(session_id="", leads=leads)
