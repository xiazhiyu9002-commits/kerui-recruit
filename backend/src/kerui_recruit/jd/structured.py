from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class ParsedJdRequirement(BaseModel):
    kind: str = Field(pattern="^(MUST|PLUS|EXCLUDE)$")
    label: str
    value: str


class ParsedJd(BaseModel):
    title: str
    company: str = ""
    department: str | None = None
    location: str | None = None
    salary: str | None = None
    ai_category: str | None = Field(default=None, pattern="^(CORE_AI|AI_RELATED|NON_AI)$")
    tech_direction: list[str] = Field(default_factory=list)
    business_direction: list[str] = Field(default_factory=list)
    industry: str | None = None
    min_years: float | None = Field(default=None, ge=0, le=80)
    highest_degree: str | None = None
    qs_level: str | None = None
    core_duties: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    plus_industry: list[str] = Field(default_factory=list)
    plus_project_types: list[str] = Field(default_factory=list)
    summary: str = ""
    requirements: list[ParsedJdRequirement] = Field(default_factory=list)


class JdParser(Protocol):
    async def parse_jd(self, text: str) -> ParsedJd: ...
    async def split_jds(self, text: str) -> list[str]: ...