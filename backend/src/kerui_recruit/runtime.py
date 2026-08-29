from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from kerui_recruit.api.services import AppServices
from kerui_recruit.core.settings import Settings
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.main import create_app
from kerui_recruit.match.service import MatchService
from kerui_recruit.providers.factory import ProviderBundle, build_providers
from kerui_recruit.resumes.pipeline import ResumePipeline
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.service import HybridSearchService
from kerui_recruit.storage.blobs import BlobStore
from kerui_recruit.tasks.repository import TaskRepository
from kerui_recruit.tasks.worker import TaskWorker


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    services: AppServices
    pipeline: ResumePipeline
    worker: TaskWorker
    providers: ProviderBundle


def build_runtime(settings: Settings) -> RuntimeComponents:
    settings.paths.ensure()
    engine = create_engine_for(settings.paths.database)
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    blob_store = BlobStore(settings.paths.blobs, settings.paths.temp)

    providers = build_providers(settings)
    index = LanceDBSearchIndex(
        settings.paths.search,
        vector_dimension=providers.vector_dimension,
    )
    repository = TaskRepository(factory)
    search_service = HybridSearchService(
        index=index,
        embedding_provider=providers.embedding,
        reranker_provider=providers.reranker,
    )
    match_service = MatchService(
        session_factory=factory,
        index=index,
        embedding_provider=providers.embedding,
        reranker_provider=providers.reranker,
    )
    jd_pipeline = JdPipeline(session_factory=factory, parser=providers.jd_parser)

    services = AppServices(
        settings=settings,
        session_factory=factory,
        blob_store=blob_store,
        task_repository=repository,
        search_service=search_service,
        match_service=match_service,
        jd_pipeline=jd_pipeline,
    )
    pipeline = ResumePipeline(
        session_factory=factory,
        blob_store=blob_store,
        parser=providers.parser,
        embedding_provider=providers.embedding,
        search_index=index,
    )

    async def parse_resume(payload: dict[str, Any]) -> str:
        result = await pipeline.run(str(payload["revision_id"]))
        return result.revision_id

    worker = TaskWorker(
        repository=repository,
        worker_id=f"desktop-{uuid4()}",
        queues=("interactive", "batch"),
        handlers={"PARSE_RESUME": parse_resume},
    )
    return RuntimeComponents(services=services, pipeline=pipeline, worker=worker, providers=providers)


def create_runtime_app(settings: Settings) -> FastAPI:
    runtime = build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.services.task_repository.recover_expired_leases()
        worker_task = asyncio.create_task(_worker_loop(runtime.worker))
        try:
            yield
        finally:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
            if runtime.providers.http_client is not None:
                await runtime.providers.http_client.aclose()

    return create_app(runtime.services, lifespan=lifespan)


async def _worker_loop(worker: TaskWorker) -> None:
    while True:
        worked = await worker.run_once()
        if not worked:
            await asyncio.sleep(0.25)
