import asyncio
from pathlib import Path

from pydantic import SecretStr

from kerui_recruit.core.settings import Settings
from kerui_recruit.providers.deepseek import DeepSeekResumeParser
from kerui_recruit.providers.factory import LOCAL_VECTOR_DIMENSION, build_providers
from kerui_recruit.providers.local import (
    LocalHashEmbeddingProvider,
    LocalKeywordReranker,
    LocalResumeParser,
)
from kerui_recruit.providers.siliconflow import SiliconFlowEmbeddingProvider


def _close(bundle) -> None:
    if bundle.http_client is not None:
        asyncio.run(bundle.http_client.aclose())


def _settings(**overrides) -> Settings:
    return Settings(
        data_root=Path("/tmp/kerui"),
        session_token=SecretStr("a" * 64),
        **overrides,
    )


def test_no_keys_selects_local_providers() -> None:
    bundle = build_providers(_settings())

    assert isinstance(bundle.parser, LocalResumeParser)
    assert isinstance(bundle.embedding, LocalHashEmbeddingProvider)
    assert isinstance(bundle.reranker, LocalKeywordReranker)
    assert bundle.vector_dimension == LOCAL_VECTOR_DIMENSION
    assert bundle.http_client is None


def test_keys_select_remote_providers_with_1024_dimension() -> None:
    bundle = build_providers(
        _settings(
            deepseek_api_key=SecretStr("ds-key"),
            siliconflow_api_key=SecretStr("sf-key"),
        )
    )

    assert isinstance(bundle.embedding, SiliconFlowEmbeddingProvider)
    assert bundle.vector_dimension == 1024
    assert bundle.http_client is not None
    _close(bundle)


def test_llm_only_keeps_local_search_providers() -> None:
    bundle = build_providers(_settings(deepseek_api_key=SecretStr("ds-key")))

    assert isinstance(bundle.parser, DeepSeekResumeParser)
    assert isinstance(bundle.embedding, LocalHashEmbeddingProvider)
    assert bundle.vector_dimension == LOCAL_VECTOR_DIMENSION
    _close(bundle)