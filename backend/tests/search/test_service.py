import asyncio
from pathlib import Path

import pytest

from kerui_recruit.providers.errors import ProviderError
from kerui_recruit.providers.fakes import FakeRerankerProvider
from kerui_recruit.search.contracts import CandidateFilters, SearchChunk
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.service import HybridSearchService


class FixedQueryEmbedding:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        assert text
        return [1.0, 0.0]


class FailingReranker:
    async def rerank(self, query: str, documents: list[str]) -> list[int]:
        raise ProviderError("E_API_BUSY", True, "busy")


def seed_index(tmp_path: Path) -> LanceDBSearchIndex:
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=2)
    index.upsert(
        [
            SearchChunk("a1", "a", "r1", "Java payment", (1.0, 0.0), 5, "MASTER", "上海", "AVAILABLE"),
            SearchChunk("b1", "b", "r2", "finance platform", (0.9, 0.1), 5, "MASTER", "上海", "AVAILABLE"),
        ]
    )
    return index


@pytest.mark.asyncio
async def test_service_embeds_query_and_reranks_retrieved_candidates(tmp_path: Path) -> None:
    """Skipping query embedding or reranking must change this evidence-based order."""
    service = HybridSearchService(
        index=seed_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=FakeRerankerProvider(),
    )

    page = await service.search("finance Java", CandidateFilters(), limit=20)

    assert [item.candidate_id for item in page.items] == ["a", "b"]
    assert page.degraded_reasons == ()


@pytest.mark.asyncio
async def test_service_returns_rrf_results_when_reranker_is_unavailable(tmp_path: Path) -> None:
    """A reranker outage must degrade search instead of making talent data unavailable."""
    service = HybridSearchService(
        index=seed_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=FailingReranker(),
    )

    page = await service.search("Java finance", CandidateFilters(), limit=20)

    assert [item.candidate_id for item in page.items] == ["a", "b"]
    assert page.degraded_reasons == ("RERANKER_UNAVAILABLE",)


class ScoredReranker:
    """返回明确的非排名相关性分数（0.07 / 0.02），用于断言精确传递。"""

    async def rerank_scored(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        scores = [0.07, 0.02]
        return [(index, scores[index]) for index in range(min(len(documents), len(scores)))]


def seed_multi_chunk_index(tmp_path: Path) -> LanceDBSearchIndex:
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=2)
    index.upsert(
        [
            SearchChunk("a1", "a", "r1", "Java 支付", (1.0, 0.0), 5, "MASTER", "上海", "AVAILABLE"),
            SearchChunk("a2", "a", "r1", "Python 风控", (0.9, 0.1), 5, "MASTER", "上海", "AVAILABLE"),
            SearchChunk("b1", "b", "r2", "Go 后端", (0.0, 1.0), 3, "BACHELOR", "北京", "AVAILABLE"),
        ]
    )
    return index


@pytest.mark.asyncio
async def test_pure_filter_dedupes_by_candidate(tmp_path: Path) -> None:
    service = HybridSearchService(
        index=seed_multi_chunk_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=FakeRerankerProvider(),
    )

    page = await service.search("", CandidateFilters(highest_degree="MASTER"), limit=10)

    # 候选 a 有 2 个 chunk，去重后只应出现一次。
    assert [h.candidate_id for h in page.items] == ["a"]


@pytest.mark.asyncio
async def test_pure_filter_excludes_skill(tmp_path: Path) -> None:
    service = HybridSearchService(
        index=seed_multi_chunk_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=FakeRerankerProvider(),
    )

    page = await service.search("", CandidateFilters(exclude_skills=("Java",)), limit=10)

    # 排除 Java 后，只剩 b（含 Java 的 a 被排除）。
    assert [h.candidate_id for h in page.items] == ["b"]


@pytest.mark.asyncio
async def test_rerank_scored_uses_model_score(tmp_path: Path) -> None:
    service = HybridSearchService(
        index=seed_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=ScoredReranker(),
    )

    page = await service.search("finance Java", CandidateFilters(), limit=20)

    # 模型分数应是真实分（非排名伪装），且重排后 a 在前。
    assert [h.candidate_id for h in page.items] == ["a", "b"]
    assert page.items[0].rerank_score == 0.07
    assert page.items[1].rerank_score == 0.02


class SlowEmbedding:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        await asyncio.sleep(10)
        return [1.0, 0.0]


@pytest.mark.asyncio
async def test_fts_returned_when_embedding_times_out(tmp_path: Path) -> None:
    service = HybridSearchService(
        index=seed_index(tmp_path),
        embedding_provider=SlowEmbedding(),
        reranker_provider=FakeRerankerProvider(),
        search_timeout=0.1,
    )

    page = await service.search("Java finance", CandidateFilters(), limit=20)

    # 全文已成功，Embedding 超时，仍返回全文结果（不返回空）。
    assert {h.candidate_id for h in page.items} == {"a", "b"}
    assert "EMBEDDING_UNAVAILABLE" in page.degraded_reasons


@pytest.mark.asyncio
async def test_preferred_location_filter_projects_and_filters(tmp_path: Path) -> None:
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=2)
    index.upsert(
        [
            SearchChunk("a1", "a", "r1", "Java", (1.0, 0.0), 5, "MASTER", "上海", "AVAILABLE", preferred_location="深圳"),
            SearchChunk("b1", "b", "r2", "Go", (0.0, 1.0), 3, "BACHELOR", "北京", "AVAILABLE", preferred_location="广州"),
        ]
    )
    service = HybridSearchService(
        index=index,
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=FakeRerankerProvider(),
    )

    page = await service.search("", CandidateFilters(preferred_locations=("深圳",)), limit=10)

    assert [h.candidate_id for h in page.items] == ["a"]


class SlowReranker:
    async def rerank(self, query: str, documents: list[str]) -> list[int]:
        await asyncio.sleep(10)
        return list(range(len(documents)))


@pytest.mark.asyncio
async def test_slow_reranker_keeps_fused_result(tmp_path: Path) -> None:
    service = HybridSearchService(
        index=seed_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=SlowReranker(),
        search_timeout=0.1,
    )

    page = await service.search("Java finance", CandidateFilters(), limit=20)

    # 重排超时，仍返回融合结果并标记降级。
    assert {h.candidate_id for h in page.items} == {"a", "b"}
    assert "RERANKER_UNAVAILABLE" in page.degraded_reasons


@pytest.mark.asyncio
async def test_concurrent_searches_do_not_corrupt_results(tmp_path: Path) -> None:
    service = HybridSearchService(
        index=seed_index(tmp_path),
        embedding_provider=FixedQueryEmbedding(),
        reranker_provider=FakeRerankerProvider(),
    )

    pages = await asyncio.gather(
        *[service.search("Java finance", CandidateFilters(), limit=20) for _ in range(5)]
    )

    for page in pages:
        assert {h.candidate_id for h in page.items} == {"a", "b"}
