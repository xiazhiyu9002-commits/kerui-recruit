from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParsedExperience(BaseModel):
    company: str | None = None
    title: str | None = None
    summary: str | None = ""
    industry: str | None = None


class ParsedProject(BaseModel):
    name: str | None = None
    summary: str | None = ""
    tech_stack: str | list[str] | None = None
    business_scene: str | list[str] | None = None


class ParsedResume(BaseModel):
    name: str | None = None
    total_years: float | None = Field(default=None, ge=0, le=80)
    highest_degree: str | None = None
    location: str | None = None
    preferred_location: str | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    school: str | None = None
    school_level: str | None = None
    qs_rank: int | None = Field(default=None, ge=1)
    graduation_year: int | None = Field(default=None, ge=1900, le=2100)
    birth_year: int | None = Field(default=None, ge=1950, le=2015)
    gender: str | None = None
    industry: str | None = None
    current_industry: str | None = None
    longest_industry: str | None = None
    tech_direction: list[str] = Field(default_factory=list)
    business_direction: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    summary: str | None = ""
    experiences: list[ParsedExperience] = Field(default_factory=list)
    projects: list[ParsedProject] = Field(default_factory=list)


class NormalizedExperience(BaseModel):
    model_config = ConfigDict(frozen=True)

    company: str | None
    title: str | None
    summary: str
    industry: str | None = None


class NormalizedProject(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None
    summary: str
    tech_stack: str | None = None
    business_scene: str | None = None


class NormalizedResume(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None
    total_years: Decimal | None
    highest_degree: str | None
    location: str | None
    preferred_location: str | None = None
    preferred_locations: tuple[str, ...] = ()
    school: str | None = None
    school_level: str | None = None
    qs_rank: int | None = None
    graduation_year: int | None = None
    birth_year: int | None = None
    age: int | None = None
    gender: str | None = None
    industry: str | None = None
    current_industry: str | None = None
    longest_industry: str | None = None
    tech_direction: tuple[str, ...] = ()
    business_direction: tuple[str, ...] = ()
    skills: tuple[str, ...]
    summary: str
    experiences: tuple[NormalizedExperience, ...]
    projects: tuple[NormalizedProject, ...]


class ResumeParser(Protocol):
    async def parse_resume(self, text: str) -> ParsedResume: ...


def build_direction_input(resume: NormalizedResume):
    """从标准化简历构建方向分类输入（仅结构化字段，不含全文与联系方式）。"""
    from kerui_recruit.direction.classifier import DirectionClassificationInput

    experiences = resume.experiences or ()
    recent = experiences[0] if experiences else None
    return DirectionClassificationInput(
        recent_title=(recent.title or "") if recent else "",
        recent_duties=(recent.summary or "") if recent else (resume.summary or ""),
        history_titles=tuple(e.title for e in experiences[1:] if e.title),
        project_summaries=tuple(_project_text(p) for p in (resume.projects or ())),
        skills=resume.skills,
        industry=resume.current_industry or resume.industry or "",
        business_scene=" ".join(p.business_scene for p in (resume.projects or ()) if p.business_scene),
    )


def _project_text(project: NormalizedProject) -> str:
    return " ".join(x for x in (project.name, project.tech_stack, project.business_scene, project.summary) if x)
