from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.backup.portable import PortableBackupService
from kerui_recruit.backup.service import BackupService
from kerui_recruit.bd_agent.agent import BdAgent
from kerui_recruit.bd_search.service import BdSearchService
from kerui_recruit.cases.service import CaseService
from kerui_recruit.core.settings import Settings
from kerui_recruit.core.settings_service import SettingsService
from kerui_recruit.correction.service import CorrectionService
from kerui_recruit.dashboard.service import DashboardService
from kerui_recruit.diagnostics.service import DiagnosticsService
from kerui_recruit.encryption.service import EncryptionService
from kerui_recruit.export.service import ExportService
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.mapping.service import MappingService
from kerui_recruit.match.service import MatchService
from kerui_recruit.migration.service import MigrationService
from kerui_recruit.org.service import OrgService
from kerui_recruit.providers.connectivity import ProviderConnectivityService
from kerui_recruit.reminders.service import ReminderService
from kerui_recruit.scheduler.service import SchedulerService
from kerui_recruit.search.service import HybridSearchService
if TYPE_CHECKING:
    from kerui_recruit.search.sync import IndexSyncService
from kerui_recruit.soft_delete.service import SoftDeleteService
from kerui_recruit.storage.blobs import BlobStore
from kerui_recruit.tasks.repository import TaskRepository


@dataclass(frozen=True, slots=True)
class AppServices:
    settings: Settings
    session_factory: sessionmaker[Session]
    blob_store: BlobStore
    task_repository: TaskRepository
    search_service: HybridSearchService
    match_service: MatchService | None = None
    jd_pipeline: JdPipeline | None = None
    export_service: ExportService | None = None
    correction_service: CorrectionService | None = None
    soft_delete_service: SoftDeleteService | None = None
    backup_service: BackupService | None = None
    portable_backup_service: PortableBackupService | None = None
    diagnostics_service: DiagnosticsService | None = None
    mapping_service: MappingService | None = None
    reminder_service: ReminderService | None = None
    org_service: OrgService | None = None
    bd_search_service: BdSearchService | None = None
    bd_agent: BdAgent | None = None
    encryption_service: EncryptionService | None = None
    case_service: CaseService | None = None
    dashboard_service: DashboardService | None = None
    scheduler_service: SchedulerService | None = None
    settings_service: SettingsService | None = None
    migration_service: MigrationService | None = None
    provider_connectivity: ProviderConnectivityService | None = None
    index_sync_service: "IndexSyncService | None" = None
