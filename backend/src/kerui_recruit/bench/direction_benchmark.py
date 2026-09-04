"""方向性能基准：真实经过 HybridSearchService.search()，asyncio 并发 + QPS 限流 + observer。

合成环境使用本地哈希向量与关键词重排，绝不调用远程方向 LLM；所有写入只落到
临时数据库与临时索引。运行：
``python -m kerui_recruit.bench.direction_benchmark --candidates 100000 --queries 200``
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Blob, Candidate, Jd, JdRevision, ResumeDocument, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.models import DirectionProfile, build_direction_label
from kerui_recruit.match.service import MatchService
from kerui_recruit.providers.local import LocalHashEmbeddingProvider, LocalKeywordReranker
from kerui_recruit.search.contracts import CandidateFilters, SearchChunk
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.observer import InMemorySearchObserver
from kerui_recruit.search.service import HybridSearchService

_ROLE_CODES = (
    "BACKEND", "AI_ML", "DATA_ENGINEERING", "DATA_ANALYSIS", "SECURITY_ENGINEERING",
    "RISK_STRATEGY", "AML_COMPLIANCE", "LEGAL", "DEVOPS", "SALES", "BD", "PRE_SALES",
    "SALES_OPS", "OPERATIONS", "CUSTOMER_SUCCESS", "PRODUCT", "PROJECT_MANAGEMENT",
    "DELIVERY_IMPLEMENTATION",
)
_STATUSES = ("CONFIDENT", "CONFIDENT", "CONFIDENT", "UNCERTAIN", "UNKNOWN")
_SOURCES = ("LLM", "RULE", "USER")


def _profile(code: str, source: str, status: str, confidence: float) -> DirectionProfile:
    if status == "UNKNOWN":
        return DirectionProfile.unknown()
    return DirectionProfile(status=status, role_families=[
        build_direction_label(code, source=source, confidence=confidence, is_primary=True),
    ])


def _chunk(candidate_id: str, revision_id: str, index: int, code: str, content: str, vector: tuple[float, ...]) -> SearchChunk:
    return SearchChunk(
        id=f"{candidate_id}:{index}", candidate_id=candidate_id, revision_id=revision_id,
        content=content, vector=vector, total_years=5.0, highest_degree="MASTER",
        location="上海", candidate_status="AVAILABLE",
        primary_role_family=code, role_family_codes=(code,), direction_confidence=0.9,
        direction_status="CONFIDENT", direction_source="LLM", taxonomy_version="career-direction-v1",
    )


@dataclass
class DirectionBenchmarkReport:
    candidate_count: int
    chunk_count: int
    query_count: int
    concurrency: int
    configured_qps: float
    actual_qps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    error_rate: float
    search_service_ms: float
    embedding_ms: float
    fts_ms: float
    vector_ms: float
    fusion_ms: float
    rerank_ms: float
    direction_boost_ms: float
    external_provider_calls: int
    synthetic: bool
    embedding_model: str
    vector_dimension: int
    direction_enabled: bool
    peak_concurrency: int
    match_jd_items: int

    def to_json(self) -> dict:
        return self.__dict__


class DirectionBenchmark:
    def __init__(self, vector_dimension: int = 64) -> None:
        self.embedding = LocalHashEmbeddingProvider(dimension=vector_dimension)
        self.reranker = LocalKeywordReranker()
        self.vector_dimension = vector_dimension

    async def run(self, *, candidate_count: int, query_count: int, concurrency: int, qps: float) -> DirectionBenchmarkReport:
        root = Path(tempfile.mkdtemp(prefix="kerui-direction-bench-"))
        engine = create_engine_for(root / "bench.sqlite3")
        migrate(engine)
        factory = sessionmaker(engine, expire_on_commit=False)

        candidates: list[tuple[str, str, str]] = []
        chunks: list[SearchChunk] = []
        with factory.begin() as session:
            for i in range(candidate_count):
                code = _ROLE_CODES[i % len(_ROLE_CODES)]
                source = _SOURCES[i % len(_SOURCES)]
                status = _STATUSES[i % len(_STATUSES)]
                candidate_id = f"cand-{i:08d}"
                revision_id = f"rev-{i:08d}"
                candidates.append((candidate_id, revision_id, code))
                session.add(Candidate(id=candidate_id, display_name=f"C{i}", status="AVAILABLE"))
                session.add(Blob(id=f"blob-{i}", content_sha256=str(i).zfill(64), suffix=".txt",
                                 size_bytes=10, storage_path=f"blob-{i}"))
                session.flush()
                session.add(ResumeDocument(id=f"doc-{i}", candidate_id=candidate_id))
                session.flush()
                profile = _profile(code, source, status, 0.9)
                session.add(ResumeRevision(id=revision_id, document_id=f"doc-{i}", blob_id=f"blob-{i}",
                                           content_sha256=str(i).zfill(64), original_filename="r.txt",
                                           status="READY", is_current=True, raw_text=f"{code} 工程师",
                                           parsed_data={"direction_profile": profile.model_dump(mode="json")}))
            session.flush()
            # 在独立短事务内构造 chunk（向量由本地哈希确定性生成，不调远程 embedding）。
        for i, (candidate_id, revision_id, code) in enumerate(candidates):
            for chunk_index in range(3):
                content = f"{code} {candidate_id} 负责核心系统 {chunk_index}"
                vector = tuple(self.embedding._embed(content))
                chunks.append(_chunk(candidate_id, revision_id, chunk_index, code, content, vector))

        with factory.begin() as session:
            jd = Jd(title="后端工程师", company="Bench", status="OPEN")
            session.add(jd)
            session.flush()
            jd_rev = JdRevision(jd=jd, source_text="后端 工程师", status="READY", is_current=True,
                                parsed_data={"direction_profile": _profile("BACKEND", "LLM", "CONFIDENT", 0.9).model_dump(mode="json"),
                                             "required_skills": ["Python"], "summary": "后端开发"})
            session.add(jd_rev)
            session.flush()
            jd_revision_id = jd_rev.id

        index = LanceDBSearchIndex(root / "search", vector_dimension=self.vector_dimension,
                                   embedding_model="local-hash-v1", chunk_version="2")
        index.upsert(chunks)
        index.optimize_pending()
        search_service = HybridSearchService(index=index, embedding_provider=self.embedding,
                                             reranker_provider=self.reranker)
        search_service.warmup()

        # 真实经过 MatchService.match_jd() 的正式逻辑（方向加权打分 + 排序 + limit）。
        match_service = MatchService(session_factory=factory, search_service=search_service)
        match_page = await match_service.match_jd(revision_id=jd_revision_id, limit=20)
        match_jd_items = len(match_page.items)

        queries = [f"{_ROLE_CODES[i % len(_ROLE_CODES)]} 工程师 {i}" for i in range(query_count)]

        latencies: list[float] = []
        errors = 0
        observers: list[InMemorySearchObserver] = []
        semaphore = asyncio.Semaphore(concurrency)
        rate_lock = asyncio.Lock()
        last_start = [0.0]
        active = 0
        peak = 0

        async def rate_limited():
            async with rate_lock:
                now = time.monotonic()
                interval = 1.0 / qps if qps > 0 else 0.0
                wait = last_start[0] + interval - now
                if wait > 0:
                    await asyncio.sleep(wait)
                last_start[0] = time.monotonic()

        async def one(query: str):
            nonlocal errors, active, peak
            observer = InMemorySearchObserver()
            started = time.monotonic()
            async with semaphore:
                active += 1
                peak = max(peak, active)
                try:
                    await rate_limited()
                    try:
                        await search_service.search(query, CandidateFilters(), limit=20, observer=observer)
                    except Exception:
                        errors += 1
                        return
                finally:
                    active -= 1
            latencies.append((time.monotonic() - started) * 1000)
            observers.append(observer)

        started_at = time.monotonic()
        await asyncio.gather(*(one(q) for q in queries))
        elapsed = time.monotonic() - started_at

        actual_qps = len(queries) / elapsed if elapsed > 0 else 0.0
        latencies.sort()

        def pct(fraction: float) -> float:
            if not latencies:
                return 0.0
            i = max(0, min(len(latencies) - 1, round((len(latencies) - 1) * fraction)))
            return round(latencies[i], 2)

        def phase_avg(name: str) -> float:
            values = [p for obs in observers for p in obs.phases.get(name, [])]
            return round(sum(values) / len(values), 2) if values else 0.0

        engine.dispose()
        return DirectionBenchmarkReport(
            candidate_count=candidate_count, chunk_count=len(chunks), query_count=len(queries),
            concurrency=concurrency, configured_qps=qps, actual_qps=round(actual_qps, 2),
            p50_ms=pct(0.50), p95_ms=pct(0.95), p99_ms=pct(0.99),
            max_ms=round(latencies[-1], 2) if latencies else 0.0,
            error_rate=round(errors / max(1, len(queries)), 4),
            search_service_ms=phase_avg("fusion"), embedding_ms=phase_avg("embedding"),
            fts_ms=phase_avg("fts"), vector_ms=phase_avg("vector"), fusion_ms=phase_avg("fusion"),
            rerank_ms=phase_avg("rerank"), direction_boost_ms=phase_avg("direction_boost"),
            external_provider_calls=0, synthetic=True, embedding_model="local-hash-v1",
            vector_dimension=self.vector_dimension, direction_enabled=True,
            peak_concurrency=peak,
            match_jd_items=match_jd_items,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kerui-direction-benchmark")
    parser.add_argument("--candidates", type=int, default=100_000)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--qps", type=float, default=0)
    options = parser.parse_args(argv)
    report = asyncio.run(DirectionBenchmark().run(
        candidate_count=options.candidates, query_count=options.queries,
        concurrency=options.concurrency, qps=options.qps))
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
