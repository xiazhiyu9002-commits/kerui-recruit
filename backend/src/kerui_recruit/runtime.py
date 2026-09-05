from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from kerui_recruit.api.services import AppServices
from kerui_recruit.backup.portable import PortableBackupService
from kerui_recruit.backup.service import BackupService, apply_pending_restore, finalize_pending_restore
from kerui_recruit.bd_agent.agent import BdAgent
from kerui_recruit.bd_agent.evidence import EvidenceExtractor
from kerui_recruit.bd_agent.fetcher import JinaReaderFetcher
from kerui_recruit.bd_agent.planner import QueryPlanner
from kerui_recruit.bd_agent.synthesis import SynthesisGenerator
from kerui_recruit.bd_search.service import BdSearchService
from kerui_recruit.cases.service import CaseService
from kerui_recruit.core.settings import Settings
from kerui_recruit.core.settings_service import SettingsService
from kerui_recruit.core.settings_store import SettingsStore
from kerui_recruit.correction.service import CorrectionService
from kerui_recruit.daily_followup.service import DailyFollowupService
from kerui_recruit.dashboard.service import DashboardService
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.classifier import DirectionClassifier
from kerui_recruit.direction.evaluation import DirectionEvaluationService
from kerui_recruit.direction.service import DirectionService
from kerui_recruit.diagnostics.service import DiagnosticsService
from kerui_recruit.encryption.service import EncryptionService
from kerui_recruit.export.service import ExportService
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.main import create_app
from kerui_recruit.mail.imap_provider import ImapLibProvider
from kerui_recruit.mail.ingest import MailIngestService
from kerui_recruit.mail.resume_gate import ResumeGate
from kerui_recruit.mail.sender import MailSender
from kerui_recruit.mail.service import MailService
from kerui_recruit.mapping.service import MappingService
from kerui_recruit.match.service import MatchService
from kerui_recruit.migration.service import MigrationService
from kerui_recruit.org.binding import OrgBindingService
from kerui_recruit.org.import_parser import DeepSeekOrgImportParser
from kerui_recruit.org.service import OrgService
from kerui_recruit.duplicates.service import DuplicateReportService, MergePlanService
from kerui_recruit.providers.factory import ProviderBundle, build_providers
from kerui_recruit.providers.connectivity import ProviderConnectivityService
from kerui_recruit.providers.leads import DeepSeekLeadExtractor
from kerui_recruit.providers.openai_compatible import OpenAICompatibleClient
from kerui_recruit.providers.websearch import (
    NullWebSearchProvider,
    SerpApiWebSearchProvider,
    TavilyWebSearchProvider,
)
from kerui_recruit.reminders.mail_service import ReminderMailService
from kerui_recruit.reminders.service import ReminderService
from kerui_recruit.resumes.backfill import backfill_contact_fingerprints
from kerui_recruit.resumes.pipeline import ResumePipeline
from kerui_recruit.scheduler.service import SchedulerService
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.service import HybridSearchService
from kerui_recruit.soft_delete.service import SoftDeleteService
from kerui_recruit.storage.blobs import BlobStore
from kerui_recruit.tasks.repository import TaskRepository, TaskSpec
from kerui_recruit.tasks.worker import TaskWorker


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    services: AppServices
    pipeline: ResumePipeline
    worker: TaskWorker
    providers: ProviderBundle


def build_runtime(settings: Settings) -> RuntimeComponents:
    settings.paths.ensure()
    restore_report = apply_pending_restore(
        database_path=settings.paths.database,
        search_dir=settings.paths.search,
        backup_dir=settings.paths.backups,
    )
    engine = create_engine_for(settings.paths.database)
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    if restore_report is not None:
        from kerui_recruit.db.models import Candidate, Jd, TaskRecord
        from kerui_recruit.search.sync import enqueue_sync
        with factory() as restore_session, restore_session.begin():
            # The restored outbox described the older index.  Increment every
            # entity generation so the new empty projection is republished.
            for candidate_id in restore_session.scalars(select(Candidate.id)):
                enqueue_sync(restore_session, "candidate", candidate_id)
            for jd_id in restore_session.scalars(select(Jd.id)):
                enqueue_sync(restore_session, "jd", jd_id)
            for task in restore_session.scalars(select(TaskRecord).where(TaskRecord.status == "RUNNING")):
                task.status = "QUEUED"
                task.lease_owner = None
                task.lease_expires_at = None
        finalize_pending_restore(restore_report)
    from kerui_recruit.cases.state import reconcile_legacy_workflow_state
    reconcile_legacy_workflow_state(factory)
    blob_store = BlobStore(settings.paths.blobs, settings.paths.temp)

    providers = build_providers(settings)
    from kerui_recruit.match.jd_index import JdSearchIndex
    from kerui_recruit.search.sync import IndexSyncService
    embedding_model = settings.siliconflow_embedding_model if settings.search_providers_enabled else "local-hash-v1"
    index = LanceDBSearchIndex(
        settings.paths.search,
        vector_dimension=providers.vector_dimension,
        embedding_model=embedding_model,
        chunk_version="2",
    )
    jd_index = JdSearchIndex(settings.paths.search / "jobs", vector_dimension=providers.vector_dimension,
        embedding_model=embedding_model, chunk_version="2")
    index_sync_service = IndexSyncService(session_factory=factory, index=index,
        embedding_provider=providers.embedding, jd_index=jd_index)
    repository = TaskRepository(factory)
    search_service = HybridSearchService(
        index=index,
        embedding_provider=providers.embedding,
        reranker_provider=providers.reranker,
    )
    match_service = MatchService(
        session_factory=factory,
        search_service=search_service,
        jd_index=jd_index,
    )
    direction_classifier = DirectionClassifier(providers.direction_llm)
    jd_pipeline = JdPipeline(session_factory=factory, parser=providers.jd_parser,
                              direction_classifier=direction_classifier)

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
    org_service = OrgService(session_factory=factory)
    encryption_service = EncryptionService(
        key_path=str(settings.paths.config / "encryption.key"),
    )
    backfill_contact_fingerprints(factory, encryption_service)
    org_binding_service = OrgBindingService(
        session_factory=factory,
        encryption=encryption_service,
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
    # 文本能力路由（与 factory.build_providers 保持一致）：text_* > deepseek_* > siliconflow_*。
    if settings.text_api_key is not None:
        text_key = settings.text_api_key
        text_url = settings.text_base_url or settings.deepseek_base_url
        text_model = settings.text_model or settings.deepseek_model
    elif settings.deepseek_api_key is not None:
        text_key = settings.deepseek_api_key
        text_url = settings.deepseek_base_url
        text_model = settings.deepseek_model
    else:
        text_key = settings.siliconflow_api_key
        text_url = settings.siliconflow_base_url
        text_model = settings.siliconflow_text_model

    llm_client = None
    if text_key is not None and providers.http_client is not None:
        llm_client = OpenAICompatibleClient(
            base_url=text_url,
            api_key=text_key.get_secret_value(),
            model=text_model,
            http_client=providers.http_client,
        )
    org_import_parser = None
    if text_key is not None and providers.http_client is not None:
        org_import_parser = DeepSeekOrgImportParser(
            api_key=text_key.get_secret_value(),
            client=providers.http_client,
            base_url=text_url,
            model=text_model,
        )
    bd_agent = BdAgent(
        session_factory=factory,
        search_provider=web_search_provider,
        fetcher=JinaReaderFetcher(client=providers.http_client),
        encryption=encryption_service,
        planner=QueryPlanner(llm_client) if llm_client else None,
        evidence_extractor=EvidenceExtractor(reranker=providers.reranker),
        synthesizer=SynthesisGenerator(llm_client) if llm_client else None,
        fallback=bd_search_service,
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
    daily_followup_service = None
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
        if settings.daily_followup_enabled:
            daily_followup_service = DailyFollowupService(
                session_factory=factory,
                mail_sender=mail_sender,
                to=settings.reminder_to,
            )

    resume_gate = None
    if text_key is not None:
        resume_gate = ResumeGate(
            base_url=text_url,
            api_key=text_key.get_secret_value(),
            model=text_model,
        )

    scheduler_service = SchedulerService(
        session_factory=factory,
        match_service=match_service,
        reminder_service=reminder_service,
        mail_ingest_service=mail_ingest_service,
        reminder_mail_service=reminder_mail_service,
        backup_service=backup_service,
        soft_delete_service=soft_delete_service,
        sender_domains=settings.imap_whitelist_domains,
        resume_gate=resume_gate,
        daily_followup_service=daily_followup_service,
    )

    settings_service = SettingsService(
        store=SettingsStore(settings.paths.config / "settings.json"),
        encryption=encryption_service,
    )
    migration_service = MigrationService(
        session_factory=factory,
        current_root=settings.paths.root,
    )
    duplicates_service = DuplicateReportService(
        session_factory=factory,
        encryption=encryption_service,
        exports_dir=settings.paths.exports,
    )
    merge_plan_service = MergePlanService(session_factory=factory)
    direction_service = DirectionService(session_factory=factory)
    direction_evaluation_service = DirectionEvaluationService(
        session_factory=factory,
        classifier=direction_classifier,
        direction_service=direction_service,
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
        org_service=org_service,
        org_import_parser=org_import_parser,
        org_binding_service=org_binding_service,
        bd_search_service=bd_search_service,
        bd_agent=bd_agent,
        encryption_service=encryption_service,
        case_service=case_service,
        dashboard_service=dashboard_service,
        scheduler_service=scheduler_service,
        settings_service=settings_service,
        migration_service=migration_service,
        duplicates_service=duplicates_service,
        merge_plan_service=merge_plan_service,
        provider_connectivity=ProviderConnectivityService(
            settings=settings,
            providers=providers,
            web_search=web_search_provider,
        ),
        index_sync_service=index_sync_service,
        direction_service=direction_service,
        direction_evaluation_service=direction_evaluation_service,
    )
    pipeline = ResumePipeline(
        session_factory=factory,
        blob_store=blob_store,
        parser=providers.parser,
        embedding_provider=providers.embedding,
        ocr_provider=providers.ocr,
        search_index=None,
        defer_indexing=True,
        encryption_service=encryption_service,
        direction_classifier=direction_classifier,
    )

    async def parse_resume(payload: dict[str, Any]) -> str:
        result = await pipeline.run(
            str(payload["revision_id"]),
            force_ocr=bool(payload.get("force_ocr", False)),
        )
        await index_sync_service.run_once(entity_type="candidate", entity_id=result.candidate_id)
        if payload.get("passive_match") and services.match_service is not None:
            repository.enqueue(TaskSpec(task_type="MATCH_CANDIDATE", queue_name="normal", priority=10,
                payload={"candidate_id": result.candidate_id},
                idempotency_key=f"passive-candidate:{result.revision_id}"))
        return result.revision_id

    async def parse_jd(payload: dict[str, Any]) -> str:
        result = await jd_pipeline.run(str(payload["revision_id"]))
        await index_sync_service.run_once(entity_type="jd", entity_id=result.jd_id)
        if payload.get("passive_match") and services.match_service is not None:
            repository.enqueue(TaskSpec(task_type="MATCH_JD", queue_name="normal", priority=10,
                payload={"revision_id": result.revision_id},
                idempotency_key=f"passive-jd:{result.revision_id}"))
        return result.revision_id

    async def match_candidate(payload: dict[str, Any]) -> str | None:
        candidate_id = str(payload["candidate_id"])
        records = await match_service.reverse_match_candidate(candidate_id)
        return match_service.record_reverse_run(candidate_id=candidate_id, records=records).run_id

    async def match_job(payload: dict[str, Any]) -> str | None:
        # Matching retries are separate from parsing and visible in the task list.
        return (await match_service.match_and_record(revision_id=str(payload["revision_id"]))).run_id

    worker = TaskWorker(
        repository=repository,
        worker_id=f"desktop-{uuid4()}",
        queues=("interactive", "normal", "batch", "export"),
        handlers={"PARSE_RESUME": parse_resume, "PARSE_JD": parse_jd,
                  "MATCH_CANDIDATE": match_candidate, "MATCH_JD": match_job},
    )
    return RuntimeComponents(services=services, pipeline=pipeline, worker=worker, providers=providers)


def create_runtime_app(settings: Settings) -> FastAPI:
    runtime = build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.services.task_repository.recover_expired_leases()
        runtime.services.search_service.warmup()
        worker_task = asyncio.create_task(
            _worker_after_index_maintenance(
                runtime.worker,
                runtime.services.search_service,
            )
        )
        lease_recovery_task = asyncio.create_task(
            _lease_recovery_loop(runtime.services.task_repository)
        )
        scheduler_task = asyncio.create_task(
            runtime.services.scheduler_service.run_forever(interval_seconds=300)
        )
        index_sync_task = asyncio.create_task(runtime.services.index_sync_service.run_forever())
        try:
            yield
        finally:
            worker_task.cancel()
            lease_recovery_task.cancel()
            scheduler_task.cancel()
            index_sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
            with suppress(asyncio.CancelledError):
                await lease_recovery_task
            with suppress(asyncio.CancelledError):
                await scheduler_task
            with suppress(asyncio.CancelledError):
                await index_sync_task
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


async def _worker_after_index_maintenance(
    worker: TaskWorker,
    search_service: HybridSearchService,
    *,
    concurrency: int = 8,
) -> None:
    try:
        await asyncio.to_thread(search_service.optimize_pending)
    except Exception:
        # The index is a rebuildable projection. A maintenance failure must not
        # stop durable SQLite tasks from continuing on the next worker cycle.
        pass
    loops = [asyncio.create_task(_worker_loop(worker)) for _ in range(concurrency)]
    await asyncio.gather(*loops)


async def _lease_recovery_loop(
    repository: TaskRepository,
    *,
    interval_seconds: float = 30,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(repository.recover_expired_leases)
