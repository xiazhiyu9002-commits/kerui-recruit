from __future__ import annotations

import httpx

from kerui_recruit.providers.errors import ProviderError, map_http_error


class SiliconFlowEmbeddingProvider:
    """BGE-M3 embeddings served through SiliconFlow's OpenAI-compatible API."""

    dimension = 1024

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "BAAI/bge-m3",
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = await self._embed(texts)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "input": texts,
                    "encoding_format": "float",
                },
            )
        except httpx.RequestError as error:
            raise ProviderError(
                code="E_API_NETWORK",
                retryable=True,
                user_message="无法连接 Embedding 服务",
            ) from error
        if response.status_code >= 400:
            raise map_http_error(response.status_code)
        try:
            payload = response.json()
            data = sorted(payload["data"], key=lambda item: item["index"])
            return [item["embedding"] for item in data]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(
                code="E_API_SCHEMA",
                retryable=True,
                user_message="Embedding 返回内容不符合结构要求",
            ) from error


class SiliconFlowRerankerProvider:
    """BGE-reranker-v2-m3 served through SiliconFlow's rerank endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "BAAI/bge-reranker-v2-m3",
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def rerank(self, query: str, documents: list[str]) -> list[int]:
        if not documents:
            return []
        try:
            response = await self.client.post(
                f"{self.base_url}/rerank",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                },
            )
        except httpx.RequestError as error:
            raise ProviderError(
                code="E_API_NETWORK",
                retryable=True,
                user_message="无法连接 Reranker 服务",
            ) from error
        if response.status_code >= 400:
            raise map_http_error(response.status_code)
        try:
            payload = response.json()
            results = sorted(
                payload["results"],
                key=lambda item: item.get("relevance_score", 0.0),
                reverse=True,
            )
            order = [item["index"] for item in results]
            seen: set[int] = set()
            return [index for index in order if not (index in seen or seen.add(index))]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(
                code="E_API_SCHEMA",
                retryable=True,
                user_message="Reranker 返回内容不符合结构要求",
            ) from error