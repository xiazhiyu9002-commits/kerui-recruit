from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.core.settings import Settings
from kerui_recruit.jd.pipeline import JdPipeline
from kerui_recruit.match.service import MatchService
from kerui_recruit.search.service import HybridSearchService
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
