from dataclasses import asdict
import json
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from kerui_recruit.api.services import AppServices
from kerui_recruit.db.models import Candidate, CandidateContact, IndexSyncRecord, ResumeDocument, ResumeRevision
from kerui_recruit.direction.taxonomy import BUSINESS_DOMAIN_LABELS, ROLE_FAMILIES
from kerui_recruit.duplicates.service import normalize_phone
from kerui_recruit.resumes.normalize import normalize_gender
from kerui_recruit.search.contracts import CandidateFilters, resolve_search_status
from kerui_recruit.search.degrees import normalize_degree
from kerui_recruit.search.query import has_skill, parse_query
from kerui_recruit.search.service import _blocking


router = APIRouter(prefix="/api/search", tags=["search"])


class CandidateFiltersRequest(BaseModel):
    min_years: float | None = Field(default=None, ge=0, le=80)
    max_years: float | None = Field(default=None, ge=0, le=80)
    highest_degree: str | None = None
    degree_exact: bool = False
    location: str | None = None
    locations: list[str] = Field(default_factory=list)
    preferred_location: str | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    candidate_status: str | None = "AVAILABLE"
    max_qs_rank: int | None = Field(default=None, ge=1)
    school_level: str | None = None
    exclude_skills: list[str] = Field(default_factory=list)
    phone: str | None = None
    gender: str | None = None
    primary_role_family: str | None = None
    role_families: list[str] = Field(default_factory=list)
    business_domains: list[str] = Field(default_factory=list)


class CandidateSearchRequest(BaseModel):
    query: str = Field(default="", max_length=2_000)
    filters: CandidateFiltersRequest = Field(default_factory=CandidateFiltersRequest)
    limit: int = Field(default=20, ge=1, le=100)


class CandidateSearchItem(BaseModel):
    candidate_id: str
    revision_id: str
    name: str
    phone: str | None
    reasons: list[str]
    parsed_data: dict | None
    content: str
    score: float
    matched_channels: tuple[str, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None
    qs_rank: int | None = None
    original_filename: str | None = None


class CandidateSearchResponse(BaseModel):
    items: list[CandidateSearchItem]
    degraded_reasons: list[str]
    empty_reason: str | None = None
    status: str = "success"


@router.get("/directions")
def list_directions() -> dict:
    return {
        "role_families": [{"code": rf.code, "label": rf.label} for rf in ROLE_FAMILIES],
        "business_domains": [{"code": code, "label": label} for code, label in BUSINESS_DOMAIN_LABELS.items()],
    }


@router.post("/candidates", response_model=CandidateSearchResponse)
async def search_candidates(
    command: CandidateSearchRequest,
    request: Request,
) -> CandidateSearchResponse:
    services: AppServices = request.app.state.services
    deadline = time.monotonic() + getattr(services.search_service, "search_timeout", 4.5)
    parsed = parse_query(command.query)
    filters = _merge_filters(parsed.filters, command.filters)
    # Reserve a small part of the same budget for checking current SQLite facts.
    remaining = max(0., deadline - time.monotonic())
    # 手机号/性别在召回之后按当前事实做精确二次校验；若只取前 limit 名，
    # 命中对象可能根本不在前 limit 名内而被漏掉，因此扩大召回量。
    recall_limit = command.limit
    if filters.phone or filters.gender:
        recall_limit = max(command.limit * 10, 200)
    page = await services.search_service.search(
        parsed.keywords, filters, limit=recall_limit,
        deadline=deadline - min(.25, remaining * .1),
    )
    if not page.items:
        return CandidateSearchResponse(
            items=[], degraded_reasons=list(page.degraded_reasons), empty_reason=page.empty_reason,
            status=resolve_search_status((), page.empty_reason, page.degraded_reasons),
        )
    try:
        items, validation_reasons = await _blocking(_hydrate_hits, services, page.items, parsed.keywords, filters, deadline=deadline)
    except Exception:
        return CandidateSearchResponse(
            items=[], degraded_reasons=list(page.degraded_reasons) + ["LIVE_VALIDATION_UNAVAILABLE"],
            empty_reason="service_error", status="service_error",
        )
    items = items[:command.limit]
    degraded = list(dict.fromkeys((*page.degraded_reasons, *validation_reasons)))
    empty_reason = page.empty_reason if items else ("service_error" if degraded else "no_match")
    return CandidateSearchResponse(
        items=items, degraded_reasons=degraded, empty_reason=empty_reason,
        status=resolve_search_status(items, empty_reason, degraded),
    )


def _hydrate_hits(services, hits, query, filters):
    """Batch join current business facts; a projection is never proof of eligibility."""
    items = []
    degraded = []
    seen_sha: set[str] = set()
    seen_candidates: set[str] = set()
    seen_identity: set[tuple[str, str]] = set()
    with services.session_factory() as session:
        pending = set(session.scalars(select(IndexSyncRecord.entity_id).where(
            IndexSyncRecord.entity_type == "candidate",
            IndexSyncRecord.entity_id.in_({hit.candidate_id for hit in hits}),
            IndexSyncRecord.requested_version > IndexSyncRecord.applied_version)).all())
        if pending:
            degraded.append("INDEX_SYNC_PENDING")
        rows = session.execute(
            select(Candidate, ResumeRevision, CandidateContact)
            .join(ResumeDocument, ResumeDocument.candidate_id == Candidate.id)
            .join(ResumeRevision, ResumeRevision.document_id == ResumeDocument.id)
            .outerjoin(CandidateContact, CandidateContact.candidate_id == Candidate.id)
            .where(Candidate.id.in_({hit.candidate_id for hit in hits}),
                   ResumeRevision.id.in_({hit.revision_id for hit in hits}),
                   Candidate.deleted_at.is_(None), Candidate.id.not_in(pending), ResumeRevision.is_current.is_(True),
                   ResumeRevision.status == "READY")
        ).all()
        current = {(candidate.id, revision.id): (candidate, revision, contact)
                   for candidate, revision, contact in rows}
        excluded: set[str] = set()
        if filters.exclude_skills:
            evidence_rows = session.execute(
                select(ResumeDocument.candidate_id, ResumeRevision)
                .join(ResumeRevision, ResumeRevision.document_id == ResumeDocument.id)
                .where(ResumeDocument.candidate_id.in_({candidate.id for candidate, _, _ in rows}),
                       ResumeRevision.is_current.is_(True))
            ).all()
            for candidate_id, revision in evidence_rows:
                if revision.status != "READY" or not revision.raw_text:
                    excluded.add(candidate_id)
                    degraded.append("EXCLUSION_UNVERIFIED")
                elif any(has_skill(revision.raw_text + "\n" + json.dumps(revision.parsed_data or {}, ensure_ascii=False), skill)
                         for skill in filters.exclude_skills):
                    excluded.add(candidate_id)
        for hit in hits:
            record = current.get((hit.candidate_id, hit.revision_id))
            if record is None or hit.candidate_id in seen_candidates or hit.candidate_id in excluded:
                continue
            candidate, revision, contact = record
            if filters.candidate_status and candidate.status != filters.candidate_status:
                continue
            identity_keys = [
                ("phone", contact.phone_fingerprint) if contact and contact.phone_fingerprint else None,
                ("email", contact.email_fingerprint) if contact and contact.email_fingerprint else None,
            ]
            identity_keys = [key for key in identity_keys if key]
            if any(key in seen_identity for key in identity_keys):
                continue
            seen_identity.update(identity_keys)
            sha = revision.content_sha256
            if sha and sha in seen_sha:
                continue
            if sha:
                seen_sha.add(sha)
            seen_candidates.add(candidate.id)
            encryption = services.encryption_service
            phone = (encryption.decrypt(contact.phone_encrypted)
                     if encryption and contact and contact.phone_encrypted else None)
            if filters.phone:
                normalized = normalize_phone(filters.phone)
                if not normalized or not _phone_matches(phone, contact, normalized):
                    continue
            if filters.gender:
                parsed_gender = normalize_gender((revision.parsed_data or {}).get("gender"))
                if parsed_gender != normalize_gender(filters.gender):
                    continue
            items.append(CandidateSearchItem(
                candidate_id=candidate.id, revision_id=revision.id, name=candidate.display_name,
                phone=phone, reasons=_build_reasons(query, hit), parsed_data=revision.parsed_data,
                content=hit.content, score=hit.score, matched_channels=hit.matched_channels,
                total_years=hit.total_years, highest_degree=hit.highest_degree, location=hit.location,
                qs_rank=hit.qs_rank, original_filename=revision.original_filename))
    return items, degraded


def _phone_matches(phone: str | None, contact, normalized: str) -> bool:
    """手机号精确匹配：规范化后必须完全一致。"""
    if contact is not None and contact.phone_fingerprint and normalized == contact.phone_fingerprint:
        return True
    if phone and normalized == normalize_phone(phone):
        return True
    return False


def _build_reasons(query: str, hit) -> list[str]:
    reasons: list[str] = []
    if hit.matched_channels:
        reasons.append("匹配通道：" + "、".join(hit.matched_channels))
    terms = [term for term in query.split() if term and term in hit.content]
    if terms:
        reasons.append("关键词命中：" + "、".join(terms[:3]))
    facts = []
    if hit.total_years is not None:
        facts.append(f"{hit.total_years:g}年经验")
    if hit.highest_degree:
        facts.append(hit.highest_degree)
    if hit.location:
        facts.append(hit.location)
    if facts:
        reasons.append("背景：" + "、".join(facts))
    return reasons[:3]


def _merge_filters(parsed: CandidateFilters, explicit: CandidateFiltersRequest | CandidateFilters) -> CandidateFilters:
    """Supplied form values win, including false, null and empty collections."""
    merged = asdict(parsed)
    if isinstance(explicit, CandidateFiltersRequest):
        overrides = explicit.model_dump(exclude_unset=True)
    else:
        defaults = asdict(CandidateFilters())
        overrides = {key: value for key, value in asdict(explicit).items() if value != defaults[key]}
    for single, multiple in (("location", "locations"), ("preferred_location", "preferred_locations")):
        if single in overrides or multiple in overrides:
            merged[single], merged[multiple] = None, ()
    if "highest_degree" in overrides and overrides["highest_degree"]:
        overrides["highest_degree"] = normalize_degree(overrides["highest_degree"])
    if "highest_degree" in overrides and "degree_exact" not in overrides:
        merged["degree_exact"] = False
    if "role_families" in overrides:
        overrides["role_family_codes"] = tuple(overrides.pop("role_families") or ())
    if "business_domains" in overrides:
        overrides["business_domain_codes"] = tuple(overrides.pop("business_domains") or ())
    merged.update(overrides)
    for key in ("locations", "preferred_locations", "exclude_skills"):
        merged[key] = tuple(merged[key] or ())
    return CandidateFilters(**merged)
