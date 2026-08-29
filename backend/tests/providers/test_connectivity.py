from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from kerui_recruit.core.settings import Settings
from kerui_recruit.providers.connectivity import ProviderConnectivityService
from kerui_recruit.providers.factory import ProviderBundle, build_providers
from kerui_recruit.providers.local import (
    LocalHashEmbeddingProvider,
    LocalKeywordReranker,
    LocalResumeParser,
)


@pytest.mark.asyncio
async def test_connectivity_reports_local_offline_mode(tmp_path: Path) -> None:
    settings = Settings(data_root=tmp_path / "data", session_token=SecretStr("token"))
    service = ProviderConnectivityService(
        settings=settings,
        providers=build_providers(settings),
    )

    checks = await service.check()
    by_name = {check.name: check for check in checks}

    assert by_name["llm"].ok is True
    assert "本地" in by_name["llm"].message
    assert by_name["embedding"].ok is True
    assert by_name["reranker"].ok is True
    assert by_name["web_search"].ok is True
    assert by_name["web_search"].message == "未配置"


@pytest.mark.asyncio
async def test_connectivity_reports_failure_for_broken_llm(tmp_path: Path) -> None:
    class FailingParser:
        async def parse_resume(self, text: str):
            raise RuntimeError("boom")

    settings = Settings(
        data_root=tmp_path / "data",
        session_token=SecretStr("token"),
        deepseek_api_key=SecretStr("key"),
    )
    providers = ProviderBundle(
        parser=FailingParser(),
        jd_parser=LocalResumeParser(),
        embedding=LocalHashEmbeddingProvider(dimension=64),
        reranker=LocalKeywordReranker(),
        ocr=None,
        vector_dimension=64,
        http_client=None,
    )
    service = ProviderConnectivityService(settings=settings, providers=providers)

    checks = await service.check()
    by_name = {check.name: check for check in checks}

    assert by_name["llm"].ok is False
    assert by_name["llm"].message == "调用失败"
