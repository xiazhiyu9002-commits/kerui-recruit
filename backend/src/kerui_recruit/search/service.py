from __future__ import annotations

from kerui_recruit.providers.contracts import EmbeddingProvider, RerankerProvider
from kerui_recruit.providers.errors import ProviderError
from kerui_recruit.search.contracts import (
    CandidateFilters,
    SearchPage,
    SearchRequest,
)
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex


class HybridSearchService:
    def __init__(
        self,
        *,
        index: LanceDBSearchIndex,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider,
    ) -> None:
        self.index = index
        self.embedding_provider = embedding_provider
        self.reranker_provider = reranker_provider

    def warmup(self) -> int:
        """Preload the index and return the number of indexed chunks."""
        return self.index.warmup()

    async def search(
        self,
        query: str,
        filters: CandidateFilters,
        *,
        limit: int,
    ) -> SearchPage:
        query_vector = await self.embedding_provider.embed_query(query)
        hits = self.index.search(
            SearchRequest(
                query=query,
                query_vector=tuple(query_vector),
                filters=filters,
                limit=max(limit, 100),
            )
        )
        if not hits:
            return SearchPage(items=())
        try:
            order = await self.reranker_provider.rerank(
                query,
                [hit.content for hit in hits[:100]],
            )
        except ProviderError:
            return SearchPage(
                items=tuple(hits[:limit]),
                degraded_reasons=("RERANKER_UNAVAILABLE",),
            )
        reranked = [hits[index] for index in order if 0 <= index < len(hits)]
        return SearchPage(items=tuple(reranked[:limit]))
