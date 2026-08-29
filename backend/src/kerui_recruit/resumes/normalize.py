from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from kerui_recruit.resumes.structured import (
    NormalizedExperience,
    NormalizedProject,
    NormalizedResume,
    ParsedResume,
)


_DEGREE_MAP = {
    "博士": "DOCTORATE",
    "phd": "DOCTORATE",
    "硕士": "MASTER",
    "master": "MASTER",
    "本科": "BACHELOR",
    "学士": "BACHELOR",
    "bachelor": "BACHELOR",
    "大专": "ASSOCIATE",
    "专科": "ASSOCIATE",
    "associate": "ASSOCIATE",
}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _unique_skills(skills: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        cleaned = _clean(skill)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def normalize_resume(parsed: ParsedResume) -> NormalizedResume:
    degree = _clean(parsed.highest_degree)
    normalized_degree = _DEGREE_MAP.get(degree.casefold(), degree.upper()) if degree else None
    years = (
        Decimal(str(parsed.total_years)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if parsed.total_years is not None
        else None
    )
    return NormalizedResume(
        name=_clean(parsed.name) or "待核验",
        total_years=years,
        highest_degree=normalized_degree,
        location=_clean(parsed.location),
        school=_clean(parsed.school),
        qs_rank=parsed.qs_rank,
        graduation_year=parsed.graduation_year,
        industry=_clean(parsed.industry),
        skills=_unique_skills(parsed.skills),
        summary=_clean(parsed.summary) or "",
        experiences=tuple(
            NormalizedExperience(
                company=_clean(experience.company) or "待核验",
                title=_clean(experience.title) or "待核验",
                summary=_clean(experience.summary) or "",
            )
            for experience in parsed.experiences
        ),
        projects=tuple(
            NormalizedProject(
                name=_clean(project.name) or "待核验",
                summary=_clean(project.summary) or "",
            )
            for project in parsed.projects
        ),
    )
