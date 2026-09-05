from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kerui_recruit.search.degrees import DEGREE_ORDER, degrees_at_least


@dataclass(frozen=True, slots=True)
class SearchChunk:
    id: str
    candidate_id: str
    revision_id: str
    content: str
    vector: tuple[float, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None
    candidate_status: str
    qs_rank: int | None = None
    school_level: str | None = None
    preferred_location: str | None = None
    preferred_locations: tuple[str, ...] = ()
    primary_role_family: str | None = None
    role_family_codes: tuple[str, ...] = ()
    direction_confidence: float | None = None
    direction_status: str | None = None
    direction_source: str | None = None
    business_domain_codes: tuple[str, ...] = ()
    leadership_code: str | None = None
    taxonomy_version: str | None = None


# 学历层级：低 -> 高。用于「本科及以上」这类包含式条件（见 search/degrees.py）。
# DEGREE_ORDER 与 degrees_at_least 由 degrees.py 统一维护，这里仅转发。

# 学校等级的重叠关系：985 也是 211，211 也是双一流。
# 要求「211」时应命中 985 与 211；要求「双一流」时命中全部三档。
SCHOOL_LEVEL_EXPAND = {
    "985": ("985",),
    "211": ("211", "985"),
    "双一流": ("双一流", "211", "985"),
    "海外": ("海外",),
    "普通": ("普通",),
}


def school_levels_at_least(level: str | None) -> tuple[str, ...]:
    """Return the school-level values that satisfy a level condition."""
    if level is None:
        return ()
    return SCHOOL_LEVEL_EXPAND.get(level, (level,))


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    min_years: float | None = None
    max_years: float | None = None
    highest_degree: str | None = None  # 语义：最低学历层级
    degree_exact: bool = False  # True 表示「仅该学历」精确限定
    location: str | None = None  # 单值现居地（向后兼容）
    locations: tuple[str, ...] = ()  # 多值现居地（或关系）
    preferred_location: str | None = None  # 求职意向地（单值，向后兼容）
    preferred_locations: tuple[str, ...] = ()  # 多值求职意向地（或关系）
    candidate_status: str | None = "AVAILABLE"
    max_qs_rank: int | None = None
    school_level: str | None = None  # 语义：最低学校等级层级
    exclude_skills: tuple[str, ...] = ()  # 排除技能（召回后硬过滤）
    phone: str | None = None  # 手机号（召回后按规范化指纹精确过滤）
    gender: str | None = None  # 性别（召回后按 男/女 过滤）
    primary_role_family: str | None = None  # 主方向（单选）
    role_family_codes: tuple[str, ...] = ()  # 方向集合（多选，或关系）
    business_domain_codes: tuple[str, ...] = ()  # 业务领域（多选，或关系）

    def degree_values(self) -> tuple[str, ...]:
        if self.highest_degree is None:
            return ()
        if self.degree_exact:
            return (self.highest_degree,)
        return degrees_at_least(self.highest_degree)

    def school_level_values(self) -> tuple[str, ...]:
        return school_levels_at_least(self.school_level)

    def location_values(self) -> tuple[str, ...]:
        values = [self.location] if self.location else []
        values.extend(self.locations)
        return tuple(dict.fromkeys(v for v in values if v))

    def preferred_location_values(self) -> tuple[str, ...]:
        values = [self.preferred_location] if self.preferred_location else []
        values.extend(self.preferred_locations)
        return tuple(dict.fromkeys(v for v in values if v))


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    query_vector: tuple[float, ...]
    filters: CandidateFilters
    limit: int = 20


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    candidate_id: str
    revision_id: str
    content: str
    score: float
    matched_channels: tuple[str, ...]
    total_years: float | None
    highest_degree: str | None
    location: str | None
    qs_rank: int | None = None
    rerank_score: float | None = None  # 重排分（0~1 或原始），与召回分分离
    verified_exclusions: tuple[str, ...] = ()  # Complete index evidence already checked during recall.
    primary_role_family: str | None = None
    role_family_codes: tuple[str, ...] = ()
    direction_confidence: float | None = None
    direction_status: str | None = None
    direction_source: str | None = None
    business_domain_codes: tuple[str, ...] = ()
    leadership_code: str | None = None
    taxonomy_version: str | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[SearchHit, ...]
    degraded_reasons: tuple[str, ...] = ()
    # 区分空结果的根因：no_match（真的没有）/ index_not_ready / service_error
    empty_reason: str | None = None


def resolve_search_status(
    items: tuple | list,
    empty_reason: str | None,
    degraded_reasons: tuple | list,
) -> str:
    """Unify search/match outcome into one of five statuses."""
    if items:
        return "degraded" if degraded_reasons else "success"
    if empty_reason == "index_not_ready":
        return "index_not_ready"
    if empty_reason == "service_error":
        return "service_error"
    if degraded_reasons:
        return "service_error"
    return "no_match"


class SearchIndex(Protocol):
    def upsert(self, chunks: list[SearchChunk]) -> None: ...

    def delete_revision(self, revision_id: str) -> None: ...

    def search(self, request: SearchRequest) -> list[SearchHit]: ...
