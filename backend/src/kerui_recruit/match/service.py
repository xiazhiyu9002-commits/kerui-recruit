from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import JdRevision, MatchResult, MatchRun
from kerui_recruit.providers.contracts import EmbeddingProvider, RerankerProvider
from kerui_recruit.search.contracts import (
    CandidateFilters,
    SearchHit,
    SearchIndex,
    SearchPage,
    SearchRequest,
)


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


@dataclass(frozen=True, slots=True)
class RecordedRun:
    run_id: str
    result_ids: dict[str, str]  # candidate_id -> MatchResult.id


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
    """Run JD-driven candidate matching over the hybrid search index.

    The JD's hard requirements become pre-filters; its summary and directional
    terms form the retrieval query. Reuses the hybrid search service for the
    retrieval + rerank path.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        index: SearchIndex,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider,
    ) -> None:
        self.session_factory = session_factory
        self.index = index
        self.embedding_provider = embedding_provider
        self.reranker_provider = reranker_provider

    async def match_jd(
        self,
        *,
        revision_id: str,
        candidates: CandidateFilters | None = None,
        limit: int = 20,
    ) -> SearchPage:
        revision = self._revision(revision_id)

        query_text = _query_text(revision)
        filters = _hard_filter(revision, candidates)

        query_vector = await self.embedding_provider.embed_query(query_text)
        hits = self.index.search(
            SearchRequest(
                query=query_text,
                query_vector=tuple(query_vector),
                filters=filters,
                limit=max(limit, 100),
            )
        )
        if not hits:
            return SearchPage(items=())
        try:
            order = await self.reranker_provider.rerank(
                query_text,
                [hit.content for hit in hits[:100]],
            )
        except Exception:
            return SearchPage(items=tuple(hits[:limit]))
        reranked = [hits[index] for index in order if 0 <= index < len(hits)]
        return SearchPage(items=tuple(reranked[:limit]))

    def score(self, revision_id: str, hit: SearchHit) -> MatchScore:
        """Produce a transparent, sub-scored match result for one candidate."""
        revision = self._revision(revision_id)
        must_skills = _must_skills(revision)
        matched = [skill for skill in must_skills if skill in hit.content]
        skill_score = (len(matched) / len(must_skills)) if must_skills else 0.0
        year_score = 1.0 if _meets_years(revision, hit) else 0.0
        total = round(hit.score * 0.6 + skill_score * 0.3 + year_score * 0.1, 4)
        return MatchScore(
            candidate_id=hit.candidate_id,
            total=total,
            breakdown={
                "relevance": round(hit.score, 4),
                "skill_coverage": round(skill_score, 4),
                "years": year_score,
            },
            reason=_build_reason(revision, hit, matched, must_skills, total),
        )

    def record_run(self, *, revision_id: str, hits) -> RecordedRun:
        """Persist an immutable match_run snapshot with sub-scored results."""
        context = self._revision(revision_id)
        result_ids: dict[str, str] = {}
        with self.session_factory() as session:
            run = MatchRun(
                trigger="JD_MATCH",
                jd_revision_id=revision_id,
                query_text=_query_text(context),
            )
            session.add(run)
            session.flush()
            for hit in hits:
                score = self.score(revision_id, hit)
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

    def _revision(self, revision_id: str) -> _JdContext:
        with self.session_factory() as session:
            revision = session.get(JdRevision, revision_id)
            if revision is None:
                raise LookupError(f"Jd revision not found: {revision_id}")
            return _JdContext(
                revision_id=revision.id,
                jd_id=revision.jd_id,
                source_text=revision.source_text,
                min_years=None if revision.min_years is None else float(revision.min_years),
                highest_degree=revision.highest_degree,
                location=revision.location,
                parsed_data=revision.parsed_data,
            )


def _query_text(revision: _JdContext) -> str:
    parsed = revision.parsed_data or {}
    summary = parsed.get("summary") or revision.source_text or ""
    tech = " ".join(parsed.get("tech_direction", []))
    business = " ".join(parsed.get("business_direction", []))
    return " ".join(part for part in (summary, tech, business) if part)


def _hard_filter(
    revision: _JdContext,
    provided: CandidateFilters | None,
) -> CandidateFilters:
    base = provided if provided is not None else CandidateFilters()
    min_years = base.min_years
    highest_degree = base.highest_degree
    location = base.location
    if revision.min_years is not None:
        min_years = revision.min_years
    if revision.highest_degree:
        highest_degree = revision.highest_degree
    if revision.location:
        location = revision.location
    return CandidateFilters(
        min_years=min_years,
        highest_degree=highest_degree,
        location=location,
        candidate_status=base.candidate_status,
    )


def _must_skills(revision: _JdContext) -> list[str]:
    parsed = revision.parsed_data or {}
    skills = list(parsed.get("tech_direction", []))
    for req in parsed.get("requirements", []):
        if req.get("kind") == "MUST" and req.get("label") in ("技能", "skill"):
            skills.append(req["value"])
    return skills


def _meets_years(revision: _JdContext, hit: SearchHit) -> bool:
    if revision.min_years is None:
        return True
    return (hit.total_years or 0) >= revision.min_years


def _build_reason(
    revision: _JdContext,
    hit: SearchHit,
    matched: list[str],
    must_skills: list[str],
    total: float,
) -> str:
    """Compose a deterministic, evidence-based explanation for a match."""
    parts: list[str] = []
    if revision.min_years is not None:
        years = hit.total_years or 0
        verdict = "满足" if years >= revision.min_years else "不满足"
        parts.append(f"相关经验 {years:g} 年 {verdict} {revision.min_years:g} 年要求")
    if must_skills:
        parts.append(f"必备技能覆盖 {len(matched)}/{len(must_skills)}")
    parts.append(f"融合得分 {total}")
    return "；".join(parts)