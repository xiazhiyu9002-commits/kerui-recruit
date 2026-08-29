from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices
from kerui_recruit.jd.ingest import IngestJd, JdIngestService


router = APIRouter(prefix="/api/jd", tags=["jd"])


class ImportJdRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    source_text: str = Field(min_length=1, max_length=100_000)


class ImportJdResponse(BaseModel):
    jd_id: str
    revision_id: str


@router.post("/import", response_model=ImportJdResponse, status_code=202)
async def import_jd(command: ImportJdRequest, request: Request) -> ImportJdResponse:
    services: AppServices = request.app.state.services
    with services.session_factory() as session:
        result = JdIngestService(session).ingest(
            IngestJd(company=command.company, title=command.title, source_text=command.source_text)
        )
    return ImportJdResponse(jd_id=result.jd_id, revision_id=result.revision_id)