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
