from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class RerankerProvider(Protocol):
    async def rerank(self, query: str, documents: list[str]) -> list[int]: ...


class OCRProvider(Protocol):
    async def extract(self, content: bytes, filename: str) -> str: ...
