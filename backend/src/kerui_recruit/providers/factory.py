from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from kerui_recruit.core.settings import Settings
from kerui_recruit.direction.classifier import DirectionLLMProvider
from kerui_recruit.jd.structured import JdParser
from kerui_recruit.providers.contracts import EmbeddingProvider, OCRProvider, RerankerProvider
from kerui_recruit.providers.deepseek import DeepSeekJdParser, DeepSeekResumeParser
from kerui_recruit.providers.direction import OpenAICompatibleDirectionProvider
from kerui_recruit.providers.ocr import OpenAICompatibleOCRProvider
from kerui_recruit.providers.local import (
    LocalHashEmbeddingProvider,
    LocalJdParser,
    LocalKeywordReranker,
    LocalResumeParser,
)
from kerui_recruit.providers.siliconflow import (
    SiliconFlowEmbeddingProvider,
    SiliconFlowRerankerProvider,
)
from kerui_recruit.resumes.structured import ResumeParser

LOCAL_VECTOR_DIMENSION = 64


@dataclass(slots=True)
class ProviderBundle:
    parser: ResumeParser
    jd_parser: JdParser
    embedding: EmbeddingProvider
    reranker: RerankerProvider
    ocr: OCRProvider | None
    vector_dimension: int
    http_client: httpx.AsyncClient | None
    direction_llm: DirectionLLMProvider | None = None


def build_providers(settings: Settings) -> ProviderBundle:
    """Build providers with per-capability routing.

    Each capability (text / vision / embedding / rerank) resolves its own
    ``base_url``/``model``/``api_key``, falling back to the legacy aggregate
    keys (DeepSeek for text/vision, SiliconFlow for embedding/rerank) when the
    per-capability override is absent. A capability with no key falls back to a
    deterministic local provider.
    """
    if not settings.llm_enabled and not settings.search_providers_enabled:
        return ProviderBundle(
            parser=LocalResumeParser(),
            jd_parser=LocalJdParser(),
            embedding=LocalHashEmbeddingProvider(dimension=LOCAL_VECTOR_DIMENSION),
            reranker=LocalKeywordReranker(),
            ocr=None,
            vector_dimension=LOCAL_VECTOR_DIMENSION,
            http_client=None,
            direction_llm=None,
        )

    client = httpx.AsyncClient()

    text = _resolve_capability(
        settings.text_base_url, settings.text_model, settings.text_api_key,
        settings.deepseek_base_url, settings.deepseek_model, settings.deepseek_api_key,
    )
    if text is None:
        # 文本模型回退到 SiliconFlow，使一个 SiliconFlow key 同时覆盖文本 + embedding/rerank。
        text = _resolve_capability(
            None, None, None,
            settings.siliconflow_base_url, settings.siliconflow_text_model, settings.siliconflow_api_key,
        )
    vision = _resolve_capability(
        settings.vision_base_url, settings.vision_model, settings.vision_api_key,
        settings.deepseek_base_url, settings.deepseek_vision_model, settings.deepseek_api_key,
    )
    if vision is None:
        vision = _resolve_capability(
            None, None, None,
            settings.siliconflow_base_url, settings.siliconflow_vision_model, settings.siliconflow_api_key,
        )
    # embedding / rerank 固定走 SiliconFlow，忽略 embedding_*/rerank_* 能力路由覆盖。
    embedding = _resolve_capability(
        None, None, None,
        settings.siliconflow_base_url, settings.siliconflow_embedding_model, settings.siliconflow_api_key,
    )
    rerank = _resolve_capability(
        None, None, None,
        settings.siliconflow_base_url, settings.siliconflow_reranker_model, settings.siliconflow_api_key,
    )

    ocr: OCRProvider | None = None
    if vision is not None:
        url, model, key = vision
        ocr = OpenAICompatibleOCRProvider(
            api_key=key,
            client=client,
            base_url=url,
            model=model,
        )

    parser: ResumeParser
    jd_parser: JdParser
    if text is not None:
        url, model, key = text
        parser = DeepSeekResumeParser(
            api_key=key,
            client=client,
            base_url=url,
            model=model,
        )
        jd_parser = DeepSeekJdParser(
            api_key=key,
            client=client,
            base_url=url,
            model=model,
        )
    else:
        parser = LocalResumeParser()
        jd_parser = LocalJdParser()

    if embedding is not None:
        url, model, key = embedding
        embedding_provider = SiliconFlowEmbeddingProvider(
            api_key=key,
            client=client,
            base_url=url,
            model=model,
        )
        vector_dimension = SiliconFlowEmbeddingProvider.dimension
    else:
        embedding_provider = LocalHashEmbeddingProvider(dimension=LOCAL_VECTOR_DIMENSION)
        vector_dimension = LOCAL_VECTOR_DIMENSION

    if rerank is not None:
        url, model, key = rerank
        reranker = SiliconFlowRerankerProvider(
            api_key=key,
            client=client,
            base_url=url,
            model=model,
        )
    else:
        reranker = LocalKeywordReranker()

    direction_llm: DirectionLLMProvider | None = None
    if text is not None:
        url, model, key = text
        direction_llm = OpenAICompatibleDirectionProvider(
            base_url=url,
            api_key=key,
            model=model,
            http_client=client,
        )

    return ProviderBundle(
        parser=parser,
        jd_parser=jd_parser,
        embedding=embedding_provider,
        reranker=reranker,
        ocr=ocr,
        vector_dimension=vector_dimension,
        http_client=client,
        direction_llm=direction_llm,
    )


def _resolve_capability(
    base_url: str | None,
    model: str | None,
    api_key: SecretStr | None,
    fallback_base: str,
    fallback_model: str,
    fallback_key: SecretStr | None,
) -> tuple[str, str, str] | None:
    """Resolve one capability to ``(base_url, model, api_key)`` or ``None``."""
    key = api_key or fallback_key
    if key is None:
        return None
    return (
        base_url or fallback_base,
        model or fallback_model,
        key.get_secret_value(),
    )