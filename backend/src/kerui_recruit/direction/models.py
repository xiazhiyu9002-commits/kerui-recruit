from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from kerui_recruit.direction.taxonomy import (
    TAXONOMY_VERSION,
    domain_label,
    is_valid_domain_code,
    is_valid_leadership_code,
    is_valid_role_code,
    leadership_label,
    role_label,
)

CLASSIFIER_VERSION = "direction-classifier-v1"

# DirectionDecision.outcome 取值：明确区分 LLM 成功方向 / 成功但 UNKNOWN / 各类失败。
OUTCOME_SUCCESS_DIRECTION = "SUCCESS_DIRECTION"
OUTCOME_SUCCESS_UNKNOWN = "SUCCESS_UNKNOWN"
OUTCOME_SCHEMA_FAILURE = "SCHEMA_FAILURE"
OUTCOME_RATE_LIMIT = "RATE_LIMIT"
OUTCOME_NETWORK_FAILURE = "NETWORK_UPSTREAM_FAILURE"
OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"
OUTCOME_PROVIDER_DISABLED = "PROVIDER_DISABLED"

_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _validate_evidence_items(value: list[str]) -> list[str]:
    """共享的确定性 evidence 校验：最多 3 条、每条 ≤120 字符、拒绝手机号/邮箱。"""
    if len(value) > 3:
        raise ValueError("evidence 每标签最多 3 条")
    for item in value:
        if len(item) > 120:
            raise ValueError("evidence 每条最多 120 字符")
        if _PHONE_RE.search(item):
            raise ValueError("evidence 不允许包含手机号")
        if _EMAIL_RE.search(item):
            raise ValueError("evidence 不允许包含邮箱")
    return value


class DirectionLabel(BaseModel):
    code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(pattern="^(RULE|LLM|USER)$")
    evidence: list[str] = Field(default_factory=list)
    is_primary: bool = False

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, value: list[str]) -> list[str]:
        return _validate_evidence_items(value)

    @model_validator(mode="after")
    def _normalize_user_confidence(self) -> "DirectionLabel":
        if self.source == "USER":
            self.confidence = 1.0
        return self


class LeadershipLabel(BaseModel):
    code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(pattern="^(RULE|LLM|USER)$")
    evidence: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, value: list[str]) -> list[str]:
        return _validate_evidence_items(value)

    @model_validator(mode="after")
    def _normalize_user_confidence(self) -> "LeadershipLabel":
        if self.source == "USER":
            self.confidence = 1.0
        return self


class BusinessDomainLabel(BaseModel):
    code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(pattern="^(RULE|LLM|USER)$")
    evidence: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, value: list[str]) -> list[str]:
        return _validate_evidence_items(value)

    @model_validator(mode="after")
    def _normalize_user_confidence(self) -> "BusinessDomainLabel":
        if self.source == "USER":
            self.confidence = 1.0
        return self


class DirectionProfile(BaseModel):
    taxonomy_version: str = TAXONOMY_VERSION
    classifier_version: str = CLASSIFIER_VERSION
    status: str = Field(pattern="^(CONFIDENT|UNCERTAIN|UNKNOWN)$")
    role_families: list[DirectionLabel] = Field(default_factory=list)
    leadership: LeadershipLabel | None = None
    business_domains: list[BusinessDomainLabel] = Field(default_factory=list)
    specialties: list[str] = Field(default_factory=list)

    @field_validator("role_families")
    @classmethod
    def _validate_role_families(cls, value: list[DirectionLabel]) -> list[DirectionLabel]:
        if len(value) > 3:
            raise ValueError("role_families 最多 3 个")
        for item in value:
            if not is_valid_role_code(item.code):
                raise ValueError(f"非法职业方向编码: {item.code}")
        primaries = [item for item in value if item.is_primary]
        if value and len(primaries) != 1:
            raise ValueError("有方向时必须恰好一个主方向")
        return value

    @field_validator("leadership")
    @classmethod
    def _validate_leadership(cls, value: LeadershipLabel | None) -> LeadershipLabel | None:
        if value is not None and not is_valid_leadership_code(value.code):
            raise ValueError(f"非法管理属性编码: {value.code}")
        return value

    @field_validator("business_domains")
    @classmethod
    def _validate_domains(cls, value: list[BusinessDomainLabel]) -> list[BusinessDomainLabel]:
        for item in value:
            if not is_valid_domain_code(item.code):
                raise ValueError(f"非法业务领域编码: {item.code}")
        return value

    @field_validator("specialties")
    @classmethod
    def _validate_specialties(cls, value: list[str]) -> list[str]:
        if len(value) > 10:
            raise ValueError("specialties 最多 10 项")
        return value

    @classmethod
    def unknown(cls) -> "DirectionProfile":
        return cls(status="UNKNOWN")

    @property
    def primary_role_code(self) -> str | None:
        for item in self.role_families:
            if item.is_primary:
                return item.code
        return None

    @property
    def all_role_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.role_families)

    @property
    def dominant_source(self) -> str | None:
        sources = [item.source for item in self.role_families]
        for source in ("USER", "LLM", "RULE"):
            if source in sources:
                return source
        return None

    @property
    def is_manual(self) -> bool:
        return self.dominant_source == "USER"


class DirectionLLMRoleFamily(BaseModel):
    code: str
    self_confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class DirectionLLMDomain(BaseModel):
    code: str
    self_confidence: float = Field(ge=0.0, le=1.0)


class DirectionLLMOutput(BaseModel):
    """LLM 原始返回：仅编码、证据与自报置信度。

    label、source、版本与最终校准置信度全部由后端生成。
    """

    primary_role_code: str | None = None
    role_family_codes: list[DirectionLLMRoleFamily] = Field(default_factory=list)
    leadership_code: str | None = None
    business_domains: list[DirectionLLMDomain] = Field(default_factory=list)
    is_unknown: bool = False

    @model_validator(mode="after")
    def _validate_primary(self) -> "DirectionLLMOutput":
        if not self.is_unknown and self.role_family_codes:
            codes = {item.code for item in self.role_family_codes}
            if self.primary_role_code is not None and self.primary_role_code not in codes:
                raise ValueError("primary_role_code 必须存在于 role_family_codes")
        return self


class RuleCandidate(BaseModel):
    code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    is_primary: bool = False


class RuleClassification(BaseModel):
    role_candidates: list[RuleCandidate] = Field(default_factory=list)
    leadership_candidate: LeadershipLabel | None = None
    domain_candidates: list[BusinessDomainLabel] = Field(default_factory=list)
    matched_rule_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    fallback_eligible: bool = False
    decision_reason: str = ""


class DirectionDecision(BaseModel):
    effective_profile: DirectionProfile
    llm_profile: DirectionProfile | None = None
    rule_profile: RuleClassification | None = None
    agreement: bool = False
    conflicts: list[str] = Field(default_factory=list)
    used_rule_fallback: bool = False
    llm_error_code: str | None = None
    decision_reason: str = ""
    outcome: str = OUTCOME_SUCCESS_DIRECTION
    # 并发安全的 LLM 调用统计（随单次 classify() 返回）。
    llm_attempts: int = 0
    llm_schema_repair_attempts: int = 0
    llm_successes: int = 0
    llm_failures: int = 0


class QueryDirectionIntent(BaseModel):
    role_code: str | None = None
    leadership_code: str | None = None
    domain_codes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    matched: bool = False


def parse_direction_profile(data: Any) -> DirectionProfile:
    """安全解析旧数据中的 direction_profile，缺失或非法时返回 UNKNOWN。"""
    if not data:
        return DirectionProfile.unknown()
    try:
        return DirectionProfile.model_validate(data)
    except ValidationError:
        return DirectionProfile.unknown()


def build_direction_label(code: str, *, source: str, confidence: float, is_primary: bool, evidence: list[str] | None = None) -> DirectionLabel:
    return DirectionLabel(
        code=code,
        label=role_label(code) or code,
        confidence=confidence,
        source=source,
        evidence=evidence or [],
        is_primary=is_primary,
    )


def build_leadership_label(code: str, *, source: str, confidence: float, evidence: list[str] | None = None) -> LeadershipLabel:
    return LeadershipLabel(
        code=code,
        label=leadership_label(code) or code,
        confidence=confidence,
        source=source,
        evidence=evidence or [],
    )


def build_domain_label(code: str, *, source: str, confidence: float) -> BusinessDomainLabel:
    return BusinessDomainLabel(
        code=code,
        label=domain_label(code) or code,
        confidence=confidence,
        source=source,
    )


def build_direction_diagnostics(decision: DirectionDecision) -> dict:
    """构造写入 review_data.direction_diagnostics 的完整字段（不含任何 PII）。"""
    profile = decision.effective_profile
    rule = decision.rule_profile
    llm = decision.llm_profile

    rule_profile = {
        "primary_code": rule.role_candidates[0].code if rule and rule.role_candidates else None,
        "candidates": [
            {"code": c.code, "label": c.label, "confidence": c.confidence, "is_primary": c.is_primary}
            for c in (rule.role_candidates if rule else [])
        ],
        "matched_rule_ids": list(rule.matched_rule_ids) if rule else [],
        "conflicts": list(rule.conflicts) if rule else [],
    }
    primary = next((i for i in llm.role_families if i.is_primary), None) if llm else None
    llm_profile = {
        "primary_code": llm.primary_role_code if llm else None,
        "role_codes": list(llm.all_role_codes) if llm else [],
        "status": llm.status if llm else None,
        "confidence": primary.confidence if primary else None,
    }
    return {
        "taxonomy_version": profile.taxonomy_version,
        "classifier_version": profile.classifier_version,
        "agreement": decision.agreement,
        "conflicts": decision.conflicts,
        "used_rule_fallback": decision.used_rule_fallback,
        "llm_error_code": decision.llm_error_code,
        "decision_reason": decision.decision_reason,
        "outcome": decision.outcome,
        "llm_attempts": decision.llm_attempts,
        "llm_successes": decision.llm_successes,
        "llm_failures": decision.llm_failures,
        "rule_profile": rule_profile,
        "llm_profile": llm_profile,
    }
