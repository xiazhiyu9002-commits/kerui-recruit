from __future__ import annotations

import re
from dataclasses import dataclass, replace

from kerui_recruit.search.contracts import CandidateFilters


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    keywords: str
    filters: CandidateFilters


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

_LOCATIONS = (
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "成都",
    "南京",
    "武汉",
    "苏州",
    "西安",
    "重庆",
    "天津",
)

_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*年(?:以上|及以上)?")
_QS_RE = re.compile(r"QS\s*(?:前|排名|前)?\s*(\d+)", re.IGNORECASE)


def parse_query(text: str) -> ParsedQuery:
    """Extract hard conditions from natural language and keep the rest as keywords.

    Implements the rule-first query understanding from spec 7.1: years, degree,
    location, school tier (QS) and status are recognized deterministically so
    hard filters apply even when the LLM provider is unavailable.
    """
    filters = CandidateFilters()

    years_match = _YEARS_RE.search(text)
    if years_match:
        filters = replace(filters, min_years=float(years_match.group(1)))

    qs_match = _QS_RE.search(text)
    if qs_match:
        filters = replace(filters, max_qs_rank=int(qs_match.group(1)))

    degree = _match_degree(text)
    if degree:
        filters = replace(filters, highest_degree=degree)

    location = next((item for item in _LOCATIONS if item in text), None)
    if location:
        filters = replace(filters, location=location)

    keywords = _strip_conditions(text)
    return ParsedQuery(keywords=keywords, filters=filters)


def _match_degree(text: str) -> str | None:
    folded = text.casefold()
    for token, normalized in sorted(
        _DEGREE_MAP.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if token.casefold() in folded:
            return normalized
    return None


def _strip_conditions(text: str) -> str:
    cleaned = _YEARS_RE.sub(" ", text)
    cleaned = _QS_RE.sub(" ", cleaned)
    for token in _DEGREE_MAP:
        cleaned = re.sub(re.escape(token), " ", cleaned, flags=re.IGNORECASE)
    for location in _LOCATIONS:
        cleaned = cleaned.replace(location, " ")
    return " ".join(cleaned.split())
