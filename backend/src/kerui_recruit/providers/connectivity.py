from __future__ import annotations

from dataclasses import dataclass

from kerui_recruit.core.settings import Settings
from kerui_recruit.providers.factory import ProviderBundle
from kerui_recruit.providers.websearch import WebSearchProvider


@dataclass(frozen=True, slots=True)
class ProviderCheck:
    name: str
    ok: bool
    message: str


class ProviderConnectivityService:
    """Probe configured providers with minimal calls for the first-run wizard."""

    def __init__(
        self,
        settings: Settings,
        providers: ProviderBundle,
        web_search: WebSearchProvider | None = None,
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._web_search = web_search

    async def check(self) -> list[ProviderCheck]:
        return [
            await self._check_llm(),
            await self._check_embedding(),
            await self._check_reranker(),
            self._check_web_search(),
        ]

    async def _check_llm(self) -> ProviderCheck:
        if not self._settings.llm_enabled:
            return ProviderCheck("llm", True, "本地离线解析模式")
        try:
            await self._providers.parser.parse_resume("测试")
            return ProviderCheck("llm", True, "可用")
        except Exception:
            return ProviderCheck("llm", False, "调用失败")

    async def _check_embedding(self) -> ProviderCheck:
        if not self._settings.search_providers_enabled:
            return ProviderCheck("embedding", True, "本地哈希嵌入模式")
        try:
            await self._providers.embedding.embed_query("测试")
            return ProviderCheck("embedding", True, "可用")
        except Exception:
            return ProviderCheck("embedding", False, "调用失败")

    async def _check_reranker(self) -> ProviderCheck:
        if not self._settings.search_providers_enabled:
            return ProviderCheck("reranker", True, "本地关键词重排模式")
        try:
            await self._providers.reranker.rerank("测试", ["测试"])
            return ProviderCheck("reranker", True, "可用")
        except Exception:
            return ProviderCheck("reranker", False, "调用失败")

    def _check_web_search(self) -> ProviderCheck:
        if not self._settings.bd_search_enabled:
            return ProviderCheck("web_search", True, "未配置")
        if self._web_search is None:
            return ProviderCheck("web_search", False, "供应商不可用")
        try:
            self._web_search.search("测试", limit=1)
            return ProviderCheck("web_search", True, "可用")
        except Exception:
            return ProviderCheck("web_search", False, "调用失败")
