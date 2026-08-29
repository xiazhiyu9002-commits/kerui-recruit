from __future__ import annotations

from dataclasses import dataclass

import httpx

from kerui_recruit.core.settings import Settings
from kerui_recruit.jd.structured import JdParser
from kerui_recruit.providers.contracts import EmbeddingProvider, OCRProvider, RerankerProvider
from kerui_recruit.providers.deepseek import DeepSeekJdParser, DeepSeekResumeParser
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


def build_providers(settings: Settings) -> ProviderBundle:
    """Select local (offline) or remote providers from settings.

    The HTTP client is shared across all remote providers and owned by the
    caller, which must close it on shutdown.
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
        )

    client = httpx.AsyncClient()

    ocr: OCRProvider | None = None
    if settings.llm_enabled:
        ocr = OpenAICompatibleOCRProvider(
            api_key=settings.deepseek_api_key.get_secret_value(),
            client=client,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )

    parser: ResumeParser
    jd_parser: JdParser
    if settings.llm_enabled:
        parser = DeepSeekResumeParser(
            api_key=settings.deepseek_api_key.get_secret_value(),
            client=client,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )
        jd_parser = DeepSeekJdParser(
            api_key=settings.deepseek_api_key.get_secret_value(),
            client=client,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )
    else:
        parser = LocalResumeParser()
        jd_parser = LocalJdParser()

    if settings.search_providers_enabled:
        embedding = SiliconFlowEmbeddingProvider(
            api_key=settings.siliconflow_api_key.get_secret_value(),
            client=client,
            base_url=settings.siliconflow_base_url,
            model=settings.siliconflow_embedding_model,
        )
        reranker = SiliconFlowRerankerProvider(
            api_key=settings.siliconflow_api_key.get_secret_value(),
            client=client,
            base_url=settings.siliconflow_base_url,
            model=settings.siliconflow_reranker_model,
        )
        vector_dimension = SiliconFlowEmbeddingProvider.dimension
    else:
        embedding = LocalHashEmbeddingProvider(dimension=LOCAL_VECTOR_DIMENSION)
        reranker = LocalKeywordReranker()
        vector_dimension = LOCAL_VECTOR_DIMENSION

    return ProviderBundle(
        parser=parser,
        jd_parser=jd_parser,
        embedding=embedding,
        reranker=reranker,
        ocr=ocr,
        vector_dimension=vector_dimension,
        http_client=client,
    )