from __future__ import annotations

from dataclasses import dataclass, replace
import json
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import Candidate, Jd, JdRevision, MatchResult, MatchRun, ResumeDocument, ResumeRevision
from kerui_recruit.direction.compatibility import direction_compatibility
from kerui_recruit.direction.models import parse_direction_profile
from kerui_recruit.match.jd_index import JdSearchIndex
from kerui_recruit.search.contracts import (
    CandidateFilters,
    SearchHit,
    SearchPage,
)
from kerui_recruit.search.degrees import normalize_degree
from kerui_recruit.search.query import has_skill, normalize_skill
from kerui_recruit.search.live import projection_is_current
from kerui_recruit.search.service import HybridSearchService, _blocking


class MatchEligibilityError(ValueError):
    """Current business entities do not permit starting or recording a match."""


class ReverseMatchUnavailableError(RuntimeError):
    """A reverse-match dependency is unavailable, rather than no jobs matching."""


@dataclass(frozen=True, slots=True)
class MatchDecision:
    passed: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchScore:
    candidate_id: str
    total: float
    breakdown: dict[str, float]
    reason: str = ""
    jd_primary_direction: str | None = None
    candidate_primary_direction: str | None = None
    candidate_direction_source: str | None = None
    direction_status: str | None = None
    direction_explanation: str = ""
    matched_skills: tuple[str, ...] = ()
    missing_skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordedRun:
    run_id: str
    result_ids: dict[str, str]  # candidate_id -> MatchResult.id


@dataclass(frozen=True, slots=True)
class ReverseMatchRecord:
    jd_id: str
    revision_id: str
    company: str
    title: str
    hit: SearchHit
    score: MatchScore | None = None


@dataclass(frozen=True, slots=True)
class _JdContext:
    revision_id: str
    jd_id: str
    source_text: str | None
    min_years: float | None
    highest_degree: str | None
    location: str | None
    parsed_data: dict | None


class MatchService:
    """JD-driven candidate matching, reusing the unified hybrid search service."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        search_service: HybridSearchService,
        jd_index: JdSearchIndex | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.search_service = search_service
        self.jd_index = jd_index
        self.reverse_search = (HybridSearchService(
            index=jd_index.index, embedding_provider=search_service.embedding_provider,
            reranker_provider=search_service.reranker_provider, search_timeout=search_service.search_timeout)
            if jd_index else None)

    async def match_jd(
        self,
        *,
        revision_id: str,
        candidates: CandidateFilters | None = None,
        limit: int = 20,
    ) -> SearchPage:
        deadline = time.monotonic() + self.search_service.search_timeout
        if not await _blocking(self._jd_eligible, revision_id, deadline=deadline):
            return SearchPage(items=(), empty_reason="jd_not_eligible")
        revision = await _blocking(self._revision, revision_id, deadline=deadline)
        query_text = _query_text(revision)
        filters = _hard_filter(revision, candidates)
        pool_limit = min(max(limit * 5, 100), 300)
        page = await self.search_service.search(
            query_text,
            filters,
            limit=pool_limit,
            deadline=deadline - min(.25, max(0., deadline - time.monotonic()) * .1),
        )
        try:
            hits = await _blocking(self._eligible_hits, revision_id, page.items, deadline=deadline)
        except Exception:
            return SearchPage(items=(), empty_reason="service_error", degraded_reasons=(*page.degraded_reasons, "LIVE_VALIDATION_UNAVAILABLE"))
        try:
            scored = await _blocking(self._score_and_sort, revision, hits, limit, deadline=deadline)
        except Exception:
            scored = hits[:limit]
        return replace(page, items=tuple(scored), empty_reason=page.empty_reason if scored else (page.empty_reason or "no_match"))

    def score(self, revision_id: str, hit: SearchHit) -> MatchScore:
        """Produce a transparent, sub-scored match result for one candidate.

        Scores are kept in a consistent 0~1 scale: relevance (rerank), business
        (skill coverage + years). The raw RRF recall score is never added to
        0~1 sub-scores by nominal weight.
        """
        data = self._candidate_parsed_data([hit.candidate_id]).get(hit.candidate_id, {})
        return self._score_context(self._revision(revision_id), hit, data)

    def _score_context(self, revision: _JdContext, hit: SearchHit, candidate_data: dict | None = None) -> MatchScore:
        candidate_data = candidate_data or {}
        must_skills = _must_skills(revision)
        matched, missing = _skill_coverage(candidate_data, must_skills)
        skill_score = (len(matched) / len(must_skills)) if must_skills else 0.0
        year_score = 1.0 if _meets_years(revision, hit) else 0.0

        jd_profile = parse_direction_profile((revision.parsed_data or {}).get("direction_profile"))
        cand_profile = parse_direction_profile(candidate_data.get("direction_profile"))
        dir_score = direction_compatibility(jd_profile, cand_profile)

        components = {
            "relevance": hit.rerank_score if hit.rerank_score is not None else 0.0,
            "skill_coverage": skill_score,
            "direction_compatibility": dir_score,
            "years": year_score,
        }
        if hit.rerank_score is not None:
            weights = {"relevance": 0.35, "skill_coverage": 0.25, "direction_compatibility": 0.30, "years": 0.10}
            rerank_available = 1
        else:
            weights = {"skill_coverage": 0.45, "direction_compatibility": 0.40, "years": 0.15}
            rerank_available = 0
        if not must_skills:
            weights.pop("skill_coverage", None)
        if revision.min_years is None:
            weights.pop("years", None)
        total_weight = sum(weights.values())
        total = round(sum(components[k] * w for k, w in weights.items()) / total_weight, 4) if total_weight else 0.0
        breakdown = {k: round(components[k], 4) for k in weights}
        breakdown["rerank_available"] = rerank_available
        breakdown["jd_primary_direction"] = jd_profile.primary_role_code
        breakdown["candidate_primary_direction"] = cand_profile.primary_role_code
        breakdown["candidate_direction_source"] = cand_profile.dominant_source
        breakdown["direction_status"] = cand_profile.status
        breakdown["direction_explanation"] = _direction_explanation(jd_profile, cand_profile, dir_score)
        breakdown["matched_skills"] = matched
        breakdown["missing_skills"] = missing

        return MatchScore(
            candidate_id=hit.candidate_id,
            total=total,
            breakdown=breakdown,
            reason=_build_reason(revision, hit, matched, must_skills, total, rerank_available),
            jd_primary_direction=jd_profile.primary_role_code,
            candidate_primary_direction=cand_profile.primary_role_code,
            candidate_direction_source=cand_profile.dominant_source,
            direction_status=cand_profile.status,
            direction_explanation=_direction_explanation(jd_profile, cand_profile, dir_score),
            matched_skills=tuple(matched),
            missing_skills=tuple(missing),
        )

    def _candidate_parsed_data(self, candidate_ids: list[str]) -> dict[str, dict]:
        if not candidate_ids:
            return {}
        with self.session_factory() as session:
            revisions = session.scalars(select(ResumeRevision).join(ResumeDocument).where(
                ResumeDocument.candidate_id.in_(list(candidate_ids)),
                ResumeRevision.is_current.is_(True),
                ResumeRevision.status == "READY")).all()
            return {rev.document.candidate_id: (rev.parsed_data or {}) for rev in revisions}

    def _score_and_sort(self, revision: _JdContext, hits: list[SearchHit], limit: int) -> list[SearchHit]:
        data_map = self._candidate_parsed_data([hit.candidate_id for hit in hits])
        scored = [(hit, self._score_context(revision, hit, data_map.get(hit.candidate_id, {}))) for hit in hits]
        scored.sort(key=lambda pair: -pair[1].total)
        return [hit for hit, _ in scored[:limit]]

    def record_run(self, *, revision_id: str, hits) -> RecordedRun:
        """Persist an immutable match_run snapshot with sub-scored results."""
        result_ids: dict[str, str] = {}
        hits = list(hits)
        data_map = self._candidate_parsed_data([hit.candidate_id for hit in hits])
        with self.session_factory() as session:
            self._assert_record_eligible(session, {revision_id}, hits)
            context = self._context(session.get(JdRevision, revision_id))
            run = MatchRun(
                trigger="JD_MATCH",
                jd_revision_id=revision_id,
                query_text=_query_text(context),
            )
            session.add(run)
            session.flush()
            for hit in hits:
                score = self._score_context(context, hit, data_map.get(hit.candidate_id, {}))
                result = MatchResult(
                    run=run,
                    candidate_id=hit.candidate_id,
                    resume_revision_id=hit.revision_id,
                    jd_revision_id=revision_id,
                    total_score=score.total,
                    score_breakdown=score.breakdown,
                    reason=score.reason,
                    status="未处理",
                )
                session.add(result)
                session.flush()
                result_ids[hit.candidate_id] = result.id
            session.commit()
            return RecordedRun(run_id=run.id, result_ids=result_ids)

    async def match_and_record(
        self,
        *,
        revision_id: str,
        limit: int = 20,
    ) -> RecordedRun:
        """Run a JD-driven match and persist the immutable run snapshot."""
        page = await self.match_jd(revision_id=revision_id, limit=limit)
        return self.record_run(revision_id=revision_id, hits=page.items)

    async def reverse_match_candidate(
        self,
        candidate_id: str,
        *,
        limit: int = 20,
    ) -> list[ReverseMatchRecord]:
        """Embed one candidate representation and directly retrieve current job representations."""
        deadline = time.monotonic() + self.search_service.search_timeout
        try:
            candidate = await _blocking(self._candidate_representation, candidate_id, deadline=deadline)
            if candidate is None:
                return []
            if not await _blocking(self._has_eligible_jobs, deadline=deadline):
                return []
            if not await _blocking(self._has_eligible_jobs, True, deadline=deadline):
                raise ReverseMatchUnavailableError("JD index is awaiting synchronization")
            if self.reverse_search is None:
                raise ReverseMatchUnavailableError("JD index is not configured")
            if not await _blocking(self.jd_index.is_ready, deadline=deadline):
                raise ReverseMatchUnavailableError("JD index is empty or incompatible")
            page = await self.reverse_search.search(
                candidate[0].content, CandidateFilters(), limit=max(limit, 100),
                deadline=deadline - min(.25, max(0., deadline - time.monotonic()) * .1))
            if not page.items and (page.degraded_reasons or page.empty_reason == "index_not_ready"):
                raise ReverseMatchUnavailableError("JD index is unavailable or search timed out")
            return await _blocking(self._reverse_records, candidate, page.items, limit, deadline=deadline)
        except TimeoutError as error:
            raise ReverseMatchUnavailableError("JD index search timed out") from error

    def _has_eligible_jobs(self, require_current_projection=False):
        with self.session_factory() as session:
            statement = select(JdRevision.id).join(Jd, Jd.id == JdRevision.jd_id).where(
                JdRevision.is_current.is_(True), JdRevision.status == "READY",
                Jd.status == "OPEN", Jd.deleted_at.is_(None))
            if require_current_projection:
                statement = statement.where(projection_is_current("jd", Jd.id))
            return session.scalar(statement.limit(1)) is not None

    def _candidate_representation(self, candidate_id):
        with self.session_factory() as session:
            candidate = session.scalar(select(Candidate).where(Candidate.id == candidate_id,
                                       projection_is_current("candidate", Candidate.id)))
            if candidate is None or candidate.deleted_at or candidate.status != "AVAILABLE":
                return None
            revisions = session.scalars(
                select(ResumeRevision).join(ResumeDocument, ResumeDocument.id == ResumeRevision.document_id)
                .where(ResumeDocument.candidate_id == candidate_id, ResumeRevision.is_current.is_(True))
                .order_by(ResumeRevision.created_at.desc(), ResumeRevision.id.desc())
            ).all()
            if not revisions or any(revision.status != "READY" or not revision.raw_text for revision in revisions):
                return None
            content = "\n".join(revision.raw_text + "\n" + json.dumps(revision.parsed_data or {}, ensure_ascii=False)
                                for revision in revisions)
            parsed = revisions[0].parsed_data or {}
            preferred = set()
            for revision in revisions:
                data = revision.parsed_data or {}
                preferred.update(data.get("preferred_locations") or ())
                if data.get("preferred_location"):
                    preferred.add(data["preferred_location"])
            hit = SearchHit(chunk_id=f"candidate:{candidate_id}", candidate_id=candidate_id,
                            revision_id=revisions[0].id, content=content, score=0., matched_channels=(),
                            total_years=float(candidate.total_years) if candidate.total_years is not None else parsed.get("total_years"),
                            highest_degree=candidate.highest_degree or parsed.get("highest_degree"), location=parsed.get("location"))
            return hit, preferred

    def _reverse_records(self, candidate, job_hits, limit):
        source, preferred = candidate
        current_candidate = self._candidate_representation(source.candidate_id)
        if current_candidate is None or current_candidate != candidate:
            return []
        source_data = self._candidate_parsed_data([source.candidate_id]).get(source.candidate_id, {})
        with self.session_factory() as session:
            rows = session.execute(
                select(JdRevision, Jd.company, Jd.title)
                .join(Jd, Jd.id == JdRevision.jd_id)
                .where(JdRevision.id.in_({hit.revision_id for hit in job_hits}),
                       Jd.status == "OPEN", Jd.deleted_at.is_(None), projection_is_current("jd", Jd.id),
                       JdRevision.is_current.is_(True), JdRevision.status == "READY")
            ).all()
            jobs = {(revision.jd_id, revision.id): (revision, company, title) for revision, company, title in rows}
            records = []
            for recalled in job_hits:
                row = jobs.get((recalled.candidate_id, recalled.revision_id))
                if row is None:
                    continue
                revision, company, title = row
                context = self._context(revision)
                filters = _hard_filter(context, None)
                if filters.min_years is not None and (source.total_years is None or source.total_years < filters.min_years):
                    continue
                if filters.degree_values() and normalize_degree(source.highest_degree) not in filters.degree_values():
                    continue
                if context.location and context.location not in {source.location, *preferred}:
                    continue
                exclusions = [requirement.get("value", "") for requirement in (context.parsed_data or {}).get("requirements", [])
                              if requirement.get("kind") == "EXCLUDE" and requirement.get("label") in ("技能", "skill")]
                if any(has_skill(source.content, skill) for skill in exclusions):
                    continue
                hit = replace(source, score=recalled.score, matched_channels=recalled.matched_channels,
                              rerank_score=recalled.rerank_score)
                score = self._score_context(context, hit, source_data)
                records.append(ReverseMatchRecord(revision.jd_id, revision.id, company, title, hit, score))
            return sorted(records, key=lambda record: (-record.score.total, -record.hit.score, record.jd_id))[:limit]

    def _jd_eligible(self, revision_id):
        with self.session_factory() as session:
            return session.scalar(select(JdRevision.id).join(Jd, Jd.id == JdRevision.jd_id).where(
                JdRevision.id == revision_id, JdRevision.is_current.is_(True), JdRevision.status == "READY",
                Jd.status == "OPEN", Jd.deleted_at.is_(None), projection_is_current("jd", Jd.id))) is not None

    def _eligible_hits(self, revision_id, hits):
        if not self._jd_eligible(revision_id) or not hits:
            return []
        with self.session_factory() as session:
            valid = set(session.execute(select(Candidate.id, ResumeRevision.id)
                .join(ResumeDocument, ResumeDocument.candidate_id == Candidate.id)
                .join(ResumeRevision, ResumeRevision.document_id == ResumeDocument.id)
                .where(Candidate.id.in_({hit.candidate_id for hit in hits}),
                       ResumeRevision.id.in_({hit.revision_id for hit in hits}),
                       Candidate.deleted_at.is_(None), Candidate.status == "AVAILABLE", projection_is_current("candidate", Candidate.id),
                       ResumeRevision.is_current.is_(True), ResumeRevision.status == "READY")).all())
            return [hit for hit in hits if (hit.candidate_id, hit.revision_id) in valid]

    def record_reverse_run(
        self,
        *,
        candidate_id: str,
        records: list[ReverseMatchRecord],
    ) -> RecordedRun:
        """Persist a candidate-driven reverse match as a run snapshot."""
        result_ids: dict[str, str] = {}
        with self.session_factory() as session:
            if any(record.hit.candidate_id != candidate_id for record in records):
                raise MatchEligibilityError("Candidate is not eligible for these records")
            self._assert_record_eligible(session, {record.revision_id for record in records}, [record.hit for record in records])
            run = MatchRun(trigger="REVERSE_MATCH", jd_revision_id=None)
            session.add(run)
            session.flush()
            for record in records:
                score = self.score(record.revision_id, record.hit)
                result = MatchResult(
                    run=run,
                    candidate_id=candidate_id,
                    resume_revision_id=record.hit.revision_id,
                    jd_revision_id=record.revision_id,
                    total_score=score.total,
                    score_breakdown=score.breakdown,
                    reason=score.reason,
                    status="未处理",
                )
                session.add(result)
                session.flush()
                result_ids[record.revision_id] = result.id
            session.commit()
            return RecordedRun(run_id=run.id, result_ids=result_ids)

    def _revision(self, revision_id: str) -> _JdContext:
        with self.session_factory() as session:
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                raise LookupError(f"Jd revision not found: {revision_id}")
            return self._context(revision)

    @staticmethod
    def _context(revision) -> _JdContext:
        return _JdContext(
            revision_id=revision.id,
            jd_id=revision.jd_id,
            source_text=revision.source_text,
            min_years=None if revision.min_years is None else float(revision.min_years),
            highest_degree=revision.highest_degree,
            location=revision.location,
            parsed_data=revision.parsed_data,
        )

    @staticmethod
    def _assert_record_eligible(session, revision_ids, hits):
        valid_jobs = set(session.scalars(select(JdRevision.id).join(Jd, Jd.id == JdRevision.jd_id).where(
            JdRevision.id.in_(revision_ids), JdRevision.is_current.is_(True), JdRevision.status == "READY",
            Jd.status == "OPEN", Jd.deleted_at.is_(None), projection_is_current("jd", Jd.id))).all())
        if valid_jobs != revision_ids:
            raise MatchEligibilityError("JD is not eligible for matching")
        valid_people = set(session.execute(select(Candidate.id, ResumeRevision.id)
            .join(ResumeDocument, ResumeDocument.candidate_id == Candidate.id)
            .join(ResumeRevision, ResumeRevision.document_id == ResumeDocument.id)
            .where(Candidate.id.in_({hit.candidate_id for hit in hits}), Candidate.status == "AVAILABLE",
                   Candidate.deleted_at.is_(None), projection_is_current("candidate", Candidate.id), ResumeRevision.id.in_({hit.revision_id for hit in hits}),
                   ResumeRevision.status == "READY", ResumeRevision.is_current.is_(True))).all())
        if any((hit.candidate_id, hit.revision_id) not in valid_people for hit in hits):
            raise MatchEligibilityError("Candidate revision is not eligible for matching")


def _query_text(revision: _JdContext) -> str:
    parsed = revision.parsed_data or {}
    summary = parsed.get("summary") or revision.source_text or ""
    tech = " ".join(parsed.get("tech_direction", []))
    business = " ".join(parsed.get("business_direction", []))
    required = " ".join(parsed.get("required_skills", []))
    must_values = " ".join(
        req.get("value", "")
        for req in parsed.get("requirements", [])
        if req.get("kind") == "MUST"
    )
    return " ".join(
        part for part in (summary, tech, business, required, must_values) if part
    )


def _hard_filter(
    revision: _JdContext,
    provided: CandidateFilters | None,
) -> CandidateFilters:
    """JD 硬条件覆盖到 provided 之上，保留 provided 的其余字段（多地点/排除等）。"""
    base = provided if provided is not None else CandidateFilters()
    if revision.min_years is not None:
        base = replace(base, min_years=revision.min_years)
    if revision.highest_degree:
        base = replace(base, highest_degree=normalize_degree(revision.highest_degree))
    if revision.location:
        base = replace(base, location=revision.location)
    return base


def _must_skills(revision: _JdContext) -> list[str]:
    parsed = revision.parsed_data or {}
    skills = [normalize_skill(s) for s in parsed.get("required_skills", [])]
    for req in parsed.get("requirements", []):
        if req.get("kind") == "MUST" and req.get("label") in ("技能", "skill"):
            skills.append(normalize_skill(req["value"]))
    # 去重保序
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        key = skill.casefold()
        if skill and key not in seen:
            seen.add(key)
            result.append(skill)
    return result


def _skill_text(candidate_data: dict) -> str:
    parts: list[str] = []
    for key in ("skills", "tech_direction", "business_direction"):
        value = candidate_data.get(key) or []
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.extend(str(v) for v in value if v)
    for exp in candidate_data.get("experiences") or []:
        if isinstance(exp, dict):
            parts.append(str(exp.get("title") or ""))
            parts.append(str(exp.get("summary") or ""))
    for proj in candidate_data.get("projects") or []:
        if isinstance(proj, dict):
            parts.append(str(proj.get("tech_stack") or ""))
            parts.append(str(proj.get("summary") or ""))
    return " ".join(p for p in parts if p)


def _skill_coverage(candidate_data: dict, must_skills: list[str]) -> tuple[list[str], list[str]]:
    if not must_skills:
        return [], []
    text = _skill_text(candidate_data)
    matched = [skill for skill in must_skills if has_skill(text, skill)]
    return matched, [skill for skill in must_skills if skill not in matched]


def _meets_years(revision: _JdContext, hit: SearchHit) -> bool:
    if revision.min_years is None:
        return True
    return (hit.total_years or 0) >= revision.min_years


def _direction_explanation(jd_profile, cand_profile, dir_score: float) -> str:
    jp = jd_profile.primary_role_code
    cp = cand_profile.primary_role_code
    if jp is None or cp is None:
        return "方向未知"
    if jp == cp:
        return f"方向一致（{jp}）"
    return f"JD {jp} vs 候选人 {cp}，兼容 {dir_score}"


def _build_reason(
    revision: _JdContext,
    hit: SearchHit,
    matched: list[str],
    must_skills: list[str],
    total: float,
    rerank_available: int,
) -> str:
    """Compose a deterministic, evidence-based explanation for a match."""
    parts: list[str] = []
    if revision.min_years is not None:
        years = hit.total_years or 0
        verdict = "满足" if years >= revision.min_years else "不满足"
        parts.append(f"相关经验 {years:g} 年 {verdict} {revision.min_years:g} 年要求")
    if must_skills:
        parts.append(f"必备技能覆盖 {len(matched)}/{len(must_skills)}")
    if not rerank_available:
        parts.append("相关性模型不可用，业务分排序")
    parts.append(f"综合得分 {total}")
    return "；".join(parts)
