from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParsedExperience(BaseModel):
    company: str
    title: str
    summary: str = ""


class ParsedProject(BaseModel):
    name: str
    summary: str = ""


class ParsedResume(BaseModel):
    name: str
    total_years: float | None = Field(default=None, ge=0, le=80)
    highest_degree: str | None = None
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    summary: str = ""
    experiences: list[ParsedExperience] = Field(default_factory=list)
    projects: list[ParsedProject] = Field(default_factory=list)


class NormalizedExperience(BaseModel):
    model_config = ConfigDict(frozen=True)

    company: str
    title: str
    summary: str


class NormalizedProject(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    summary: str


class NormalizedResume(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    total_years: Decimal | None
    highest_degree: str | None
    location: str | None
    skills: tuple[str, ...]
    summary: str
    experiences: tuple[NormalizedExperience, ...]
    projects: tuple[NormalizedProject, ...]


class ResumeParser(Protocol):
    async def parse_resume(self, text: str) -> ParsedResume: ...
