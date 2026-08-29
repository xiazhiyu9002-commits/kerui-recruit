from __future__ import annotations

import httpx
import pytest

from kerui_recruit.providers.siliconflow import (
    SiliconFlowEmbeddingProvider,
    SiliconFlowRerankerProvider,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://test",
    )


@pytest.mark.asyncio
async def test_embedding_parses_sorted_vectors_and_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert body["model"] == "BAAI/bge-m3"
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [2.0, 2.0]},
                    {"index": 0, "embedding": [1.0, 1.0]},
                ]
            },
        )

    provider = SiliconFlowEmbeddingProvider(
        api_key="test-key", client=_client(handler)
    )
    vectors = await provider.embed_documents(["a", "b"])

    assert vectors == [[1.0, 1.0], [2.0, 2.0]]
    assert provider.dimension == 1024


@pytest.mark.asyncio
async def test_reranker_orders_by_relevance_score() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rerank")
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.1},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": 0.5},
                ]
            },
        )

    provider = SiliconFlowRerankerProvider(
        api_key="test-key", client=_client(handler)
    )
    order = await provider.rerank("q", ["a", "b", "c"])

    assert order == [1, 2, 0]


@pytest.mark.asyncio
async def test_embedding_maps_http_error_to_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    provider = SiliconFlowEmbeddingProvider(
        api_key="test-key", client=_client(handler)
    )
    with pytest.raises(Exception) as caught:
        await provider.embed_query("hello")

    assert caught.value.code == "E_API_RATE_LIMIT"
    assert caught.value.retryable is True