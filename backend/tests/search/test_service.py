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
