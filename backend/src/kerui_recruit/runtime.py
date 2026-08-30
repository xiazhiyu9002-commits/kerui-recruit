from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from kerui_recruit.api.services import AppServices
from kerui_recruit.backup.portable import PortableBackupService
from kerui_recruit.backup.service import BackupService
from kerui_recruit.bd_search.service import BdSearchService
from kerui_recruit.cases.service import CaseService
from kerui_recruit.core.settings import Settings
from kerui_recruit.core.settings_service import SettingsService
from kerui_recruit.core.settings_store import SettingsStore
from kerui_recruit.correction.service import CorrectionService
from kerui_recruit.dashboard.service import DashboardService
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.diagnostics.service import DiagnosticsService
from kerui_recruit.encryption.service import EncryptionService
from kerui_recruit.export.service import ExportService
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.main import create_app
from kerui_recruit.mail.imap_provider import ImapLibProvider
from kerui_recruit.mail.ingest import MailIngestService
from kerui_recruit.mail.sender import MailSender
from kerui_recruit.mail.service import MailService
from kerui_recruit.mapping.service import MappingService
from kerui_recruit.match.service import MatchService
from kerui_recruit.migration.service import MigrationService
from kerui_recruit.providers.factory import ProviderBundle, build_providers
from kerui_recruit.providers.connectivity import ProviderConnectivityService
from kerui_recruit.providers.leads import DeepSeekLeadExtractor
from kerui_recruit.providers.websearch import (
    NullWebSearchProvider,
    SerpApiWebSearchProvider,
    TavilyWebSearchProvider,
)
from kerui_recruit.reminders.mail_service import ReminderMailService
from kerui_recruit.reminders.service import ReminderService
from kerui_recruit.resumes.pipeline import ResumePipeline
from kerui_recruit.scheduler.service import SchedulerService
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.service import HybridSearchService
from kerui_recruit.soft_delete.service import SoftDeleteService
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

    export_service = ExportService(session_factory=factory)
    correction_service = CorrectionService(session_factory=factory)
    soft_delete_service = SoftDeleteService(session_factory=factory)
    backup_service = BackupService(
        session_factory=factory,
        engine=engine,
        database_path=settings.paths.database,
        backup_dir=settings.paths.backups,
    )
    portable_backup_service = PortableBackupService(
        current_root=settings.paths.root,
    )
    diagnostics_service = DiagnosticsService(
        session_factory=factory,
        database_path=settings.paths.database,
    )
    mapping_service = MappingService(session_factory=factory)
    reminder_service = ReminderService(session_factory=factory)
    encryption_service = EncryptionService(
        key_path=str(settings.paths.config / "encryption.key"),
    )
    if settings.tavily_api_key:
        web_search_provider = TavilyWebSearchProvider(
            api_key=settings.tavily_api_key.get_secret_value(),
            base_url=settings.tavily_base_url,
        )
    elif settings.serpapi_api_key:
        web_search_provider = SerpApiWebSearchProvider(
            api_key=settings.serpapi_api_key.get_secret_value(),
            base_url=settings.serpapi_base_url,
        )
    else:
        web_search_provider = NullWebSearchProvider()
    lead_extractor = (
        DeepSeekLeadExtractor(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )
        if settings.llm_enabled
        else None
    )
    bd_search_service = BdSearchService(
        session_factory=factory,
        search_provider=web_search_provider,
        encryption=encryption_service,
        extractor=lead_extractor,
    )
    case_service = CaseService(session_factory=factory)
    dashboard_service = DashboardService(session_factory=factory)

    mail_ingest_service = None
    if settings.mail_enabled:
        mail_provider = ImapLibProvider(
            host=settings.imap_host,  # type: ignore[arg-type]
            account=settings.imap_account,  # type: ignore[arg-type]
            password=settings.imap_auth_code.get_secret_value(),  # type: ignore[union-attr]
        )
        mail_service = MailService(session_factory=factory, imap=mail_provider)
        mail_ingest_service = MailIngestService(
            session_factory=factory,
            blob_store=blob_store,
            mail_service=mail_service,
        )

    reminder_mail_service = None
    if settings.smtp_enabled:
        mail_sender = MailSender(
            host=settings.smtp_host,  # type: ignore[arg-type]
            account=settings.smtp_account,  # type: ignore[arg-type]
            password=settings.smtp_auth_code.get_secret_value(),  # type: ignore[union-attr]
            port=settings.smtp_port,
            ssl=settings.smtp_ssl,
        )
        reminder_mail_service = ReminderMailService(
            reminder_service=reminder_service,
            mail_sender=mail_sender,
            to=settings.reminder_to,
        )

    scheduler_service = SchedulerService(
        session_factory=factory,
        match_service=match_service,
        reminder_service=reminder_service,
        mail_ingest_service=mail_ingest_service,
        reminder_mail_service=reminder_mail_service,
        backup_service=backup_service,
        soft_delete_service=soft_delete_service,
    )

    settings_service = SettingsService(
        store=SettingsStore(settings.paths.config / "settings.json"),
        encryption=encryption_service,
    )
    migration_service = MigrationService(
        session_factory=factory,
        current_root=settings.paths.root,
    )

    services = AppServices(
        settings=settings,
        session_factory=factory,
        blob_store=blob_store,
        task_repository=repository,
        search_service=search_service,
        match_service=match_service,
        jd_pipeline=jd_pipeline,
        export_service=export_service,
        correction_service=correction_service,
        soft_delete_service=soft_delete_service,
        backup_service=backup_service,
        portable_backup_service=portable_backup_service,
        diagnostics_service=diagnostics_service,
        mapping_service=mapping_service,
        reminder_service=reminder_service,
        bd_search_service=bd_search_service,
        encryption_service=encryption_service,
        case_service=case_service,
        dashboard_service=dashboard_service,
        scheduler_service=scheduler_service,
        settings_service=settings_service,
        migration_service=migration_service,
        provider_connectivity=ProviderConnectivityService(
            settings=settings,
            providers=providers,
            web_search=web_search_provider,
        ),
    )
    pipeline = ResumePipeline(
        session_factory=factory,
        blob_store=blob_store,
        parser=providers.parser,
        embedding_provider=providers.embedding,
        ocr_provider=providers.ocr,
        search_index=index,
        encryption_service=encryption_service,
    )

    async def parse_resume(payload: dict[str, Any]) -> str:
        result = await pipeline.run(str(payload["revision_id"]))
        return result.revision_id

    worker = TaskWorker(
        repository=repository,
        worker_id=f"desktop-{uuid4()}",
        queues=("interactive", "normal", "batch", "export"),
        handlers={"PARSE_RESUME": parse_resume},
    )
    return RuntimeComponents(services=services, pipeline=pipeline, worker=worker, providers=providers)


def create_runtime_app(settings: Settings) -> FastAPI:
    runtime = build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.services.task_repository.recover_expired_leases()
        runtime.services.search_service.warmup()
        worker_task = asyncio.create_task(_worker_loop(runtime.worker))
        scheduler_task = asyncio.create_task(
            runtime.services.scheduler_service.run_forever(interval_seconds=300)
        )
        try:
            yield
        finally:
            worker_task.cancel()
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
            with suppress(asyncio.CancelledError):
                await scheduler_task
            if runtime.providers.http_client is not None:
                await runtime.providers.http_client.aclose()

    return create_app(runtime.services, lifespan=lifespan)


async def _worker_loop(worker: TaskWorker) -> None:
    while True:
        worked = await worker.run_once()
        # Local parsers and embeddings may complete without a network await.
        # Always yield after a claimed task so a large batch cannot starve API
        # responses and desktop health checks on the same event loop.
        await asyncio.sleep(0 if worked else 0.25)
