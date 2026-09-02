from __future__ import annotations

from datetime import datetime
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


def _join_value(value: str | list[str] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return " / ".join(str(v).strip() for v in value if str(v).strip()) or None
    return _clean(value)


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


def _compute_age(birth_year: int | None, graduation_year: int | None) -> int | None:
    current_year = datetime.now().year
    if birth_year is not None:
        return current_year - birth_year
    if graduation_year is not None:
        return current_year - graduation_year + 22
    return None


def normalize_resume(parsed: ParsedResume) -> NormalizedResume:
    degree = _clean(parsed.highest_degree)
    normalized_degree = _DEGREE_MAP.get(degree.casefold(), degree.upper()) if degree else None
    years = (
        Decimal(str(parsed.total_years)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if parsed.total_years is not None
        else None
    )
    age = _compute_age(parsed.birth_year, parsed.graduation_year)
    return NormalizedResume(
        name=_clean(parsed.name),
        total_years=years,
        highest_degree=normalized_degree,
        location=_clean(parsed.location),
        preferred_location=_clean(parsed.preferred_location),
        preferred_locations=_unique_skills(parsed.preferred_locations),
        school=_clean(parsed.school),
        school_level=_clean(parsed.school_level),
        qs_rank=parsed.qs_rank,
        graduation_year=parsed.graduation_year,
        birth_year=parsed.birth_year,
        age=age,
        industry=_clean(parsed.industry),
        current_industry=_clean(parsed.current_industry),
        longest_industry=_clean(parsed.longest_industry),
        tech_direction=_unique_skills(parsed.tech_direction),
        business_direction=_unique_skills(parsed.business_direction),
        skills=_unique_skills(parsed.skills),
        summary=_clean(parsed.summary) or "",
        experiences=tuple(
            NormalizedExperience(
                company=_clean(experience.company),
                title=_clean(experience.title),
                summary=_clean(experience.summary) or "",
                industry=_clean(experience.industry),
            )
            for experience in parsed.experiences
        ),
        projects=tuple(
            NormalizedProject(
                name=_clean(project.name),
                summary=_clean(project.summary) or "",
                tech_stack=_join_value(project.tech_stack),
                business_scene=_join_value(project.business_scene),
            )
            for project in parsed.projects
        ),
    )
