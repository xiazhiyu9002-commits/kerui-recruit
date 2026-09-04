from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kerui_recruit.direction import rules
from kerui_recruit.direction.models import (
    BusinessDomainLabel,
    DirectionDecision,
    DirectionLabel,
    DirectionLLMOutput,
    DirectionProfile,
    LeadershipLabel,
    OUTCOME_NETWORK_FAILURE,
    OUTCOME_PROVIDER_DISABLED,
    OUTCOME_RATE_LIMIT,
    OUTCOME_SCHEMA_FAILURE,
    OUTCOME_SUCCESS_DIRECTION,
    OUTCOME_SUCCESS_UNKNOWN,
    OUTCOME_VALIDATION_FAILURE,
    RuleClassification,
    build_domain_label,
    build_direction_label,
    build_leadership_label,
)
from kerui_recruit.direction.rules import RuleInput


@dataclass(frozen=True, slots=True)
class DirectionClassificationInput:
    recent_title: str = ""
    recent_duties: str = ""
    history_titles: tuple[str, ...] = ()
    project_summaries: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    industry: str = ""
    business_scene: str = ""


@dataclass(frozen=True, slots=True)
class DirectionProviderResult:
    """Provider 返回的分类结果，携带并发安全的调用统计。

    output 为 None 表示未得到可用结果；llm_attempts 统计真实 HTTP 模型调用次数，
    schema_repair_attempts 统计因 E_API_SCHEMA 触发的格式修复重试次数。
    """
    output: DirectionLLMOutput | None
    llm_attempts: int
    schema_repair_attempts: int
    success: bool
    error_code: str | None


class DirectionLLMProvider(Protocol):
    """方向分类 LLM Provider。只返回编码、证据与自报置信度。"""

    async def classify_direction(self, payload: DirectionClassificationInput) -> DirectionProviderResult: ...


class DirectionClassifier:
    """规则与 LLM 独立判断并融合：LLM 主判，规则校验/冲突检测/兜底。"""

    def __init__(self, llm_provider: DirectionLLMProvider | None) -> None:
        self.llm_provider = llm_provider

    async def classify(self, payload: DirectionClassificationInput) -> DirectionDecision:
        rule_input = RuleInput(
            recent_title=payload.recent_title,
            recent_duties=payload.recent_duties,
            history_titles=payload.history_titles,
            project_summaries=payload.project_summaries,
            skills=payload.skills,
            industry=payload.industry,
            business_scene=payload.business_scene,
        )
        rule_profile = rules.classify(rule_input)

        llm_profile: DirectionProfile | None = None
        llm_error_code: str | None = None
        llm_attempts = 0
        llm_schema_repair = 0
        explicit_unknown = False
        if self.llm_provider is not None:
            result = await self.llm_provider.classify_direction(payload)
            llm_attempts = result.llm_attempts
            llm_schema_repair = result.schema_repair_attempts
            if result.success and result.output is not None:
                if result.output.is_unknown:
                    explicit_unknown = True
                else:
                    try:
                        llm_profile = self._llm_profile(result.output)
                    except Exception as error:  # noqa: BLE001 - 非法编码等转换为校验失败
                        llm_error_code = type(error).__name__
                    if llm_profile is None:
                        llm_error_code = "E_DIRECTION_VALIDATION"
            else:
                llm_error_code = result.error_code

        if llm_profile is not None:
            decision = self._fuse_llm(llm_profile, rule_profile)
            outcome = OUTCOME_SUCCESS_DIRECTION
            llm_successes, llm_failures = 1, 0
        elif explicit_unknown:
            decision = self._fuse_fallback(rule_profile, None, llm_unknown=True)
            outcome = OUTCOME_SUCCESS_UNKNOWN
            llm_successes, llm_failures = 1, 0
        elif self.llm_provider is None:
            decision = self._fuse_fallback(rule_profile, None)
            outcome = OUTCOME_PROVIDER_DISABLED
            llm_successes, llm_failures = 0, 0
        else:
            decision = self._fuse_fallback(rule_profile, llm_error_code)
            outcome = _failure_outcome(llm_error_code)
            llm_successes, llm_failures = 0, 1

        return decision.model_copy(update={
            "llm_attempts": llm_attempts,
            "llm_schema_repair_attempts": llm_schema_repair,
            "llm_successes": llm_successes,
            "llm_failures": llm_failures,
            "outcome": outcome,
        })

    def classify_rules_only(self, payload: DirectionClassificationInput) -> DirectionDecision:
        """仅规则分类，不调用 LLM。用于 rules-only 回填模式。"""
        rule_input = RuleInput(
            recent_title=payload.recent_title,
            recent_duties=payload.recent_duties,
            history_titles=payload.history_titles,
            project_summaries=payload.project_summaries,
            skills=payload.skills,
            industry=payload.industry,
            business_scene=payload.business_scene,
        )
        rule_profile = rules.classify(rule_input)
        return self._fuse_fallback(rule_profile, None)

    def _fuse_llm(self, llm_profile: DirectionProfile, rule_profile: RuleClassification) -> DirectionDecision:
        rule_primary = rule_profile.role_candidates[0].code if rule_profile.role_candidates else None
        llm_primary = llm_profile.primary_role_code

        agreement = bool(rule_primary and rule_primary == llm_primary)
        conflicts = list(rule_profile.conflicts)
        if rule_primary and llm_primary and rule_primary != llm_primary:
            conflicts.append(f"规则主方向 {rule_primary} 与 LLM 主方向 {llm_primary} 不一致")

        profile = llm_profile
        if agreement:
            profile = self._with_status(profile, "CONFIDENT")
            profile = self._scale_confidence(profile, boost=True)
            reason = "LLM 成功，规则一致"
        elif not rule_profile.role_candidates:
            # 规则没有可靠结果：按证据完整度定状态，不因规则没命中否定 LLM。
            if self._evidence_complete(profile):
                profile = self._with_status(profile, "CONFIDENT")
            else:
                profile = self._with_status(profile, "UNCERTAIN")
            reason = "LLM 成功，规则无可靠结果"
        else:
            # 冲突：仍采用 LLM 作为机器结果，标记 UNCERTAIN，置信度不超过 0.65。
            profile = self._with_status(profile, "UNCERTAIN")
            profile = self._scale_confidence(profile, cap=0.65)
            reason = "LLM 成功，规则冲突"
        return DirectionDecision(
            effective_profile=profile,
            llm_profile=llm_profile,
            rule_profile=rule_profile,
            agreement=agreement,
            conflicts=conflicts,
            used_rule_fallback=False,
            decision_reason=reason,
        )

    def _fuse_fallback(self, rule_profile: RuleClassification, llm_error_code: str | None,
                       llm_unknown: bool = False) -> DirectionDecision:
        prefix = "LLM 成功但无法判断" if llm_unknown else "LLM 失败"
        if rule_profile.fallback_eligible and rule_profile.role_candidates:
            profile = self._rule_profile(rule_profile)
            profile = self._with_status(profile, "CONFIDENT")
            return DirectionDecision(
                effective_profile=profile,
                rule_profile=rule_profile,
                used_rule_fallback=True,
                llm_error_code=llm_error_code,
                decision_reason=f"{prefix}，规则兜底",
            )
        return DirectionDecision(
            effective_profile=DirectionProfile.unknown(),
            rule_profile=rule_profile,
            used_rule_fallback=False,
            llm_error_code=llm_error_code,
            decision_reason=f"{prefix}且规则无兜底资格",
        )

    def _llm_profile(self, raw: DirectionLLMOutput) -> DirectionProfile | None:
        if raw.is_unknown or not raw.role_family_codes:
            return None
        role_families: list[DirectionLabel] = []
        for item in raw.role_family_codes:
            role_families.append(build_direction_label(
                item.code,
                source="LLM",
                confidence=item.self_confidence,
                is_primary=(item.code == raw.primary_role_code),
                evidence=item.evidence[:3],
            ))
        leadership = None
        if raw.leadership_code:
            leadership = build_leadership_label(raw.leadership_code, source="LLM", confidence=0.8)
        domains = [build_domain_label(item.code, source="LLM", confidence=item.self_confidence)
                   for item in raw.business_domains]
        return DirectionProfile(
            status="CONFIDENT",
            role_families=role_families,
            leadership=leadership,
            business_domains=domains,
        )

    @staticmethod
    def _rule_profile(rule: RuleClassification) -> DirectionProfile:
        role_families = [
            DirectionLabel(code=c.code, label=c.label, confidence=c.confidence,
                           source="RULE", evidence=c.evidence[:3], is_primary=c.is_primary)
            for c in rule.role_candidates
        ]
        leadership: LeadershipLabel | None = rule.leadership_candidate
        domains: list[BusinessDomainLabel] = rule.domain_candidates
        return DirectionProfile(
            status="UNCERTAIN",
            role_families=role_families,
            leadership=leadership,
            business_domains=domains,
        )

    @staticmethod
    def _with_status(profile: DirectionProfile, status: str) -> DirectionProfile:
        return profile.model_copy(update={"status": status})

    @staticmethod
    def _scale_confidence(profile: DirectionProfile, *, boost: bool = False, cap: float | None = None) -> DirectionProfile:
        updated: list[DirectionLabel] = []
        for item in profile.role_families:
            confidence = item.confidence
            if boost:
                confidence = min(1.0, confidence + 0.05)
            if cap is not None:
                confidence = min(confidence, cap)
            updated.append(item.model_copy(update={"confidence": round(confidence, 4)}))
        return profile.model_copy(update={"role_families": updated})

    @staticmethod
    def _evidence_complete(profile: DirectionProfile) -> bool:
        if not profile.role_families:
            return False
        primary = next((i for i in profile.role_families if i.is_primary), None)
        return primary is not None and bool(primary.evidence) and primary.confidence >= 0.7


def _failure_outcome(error_code: str | None) -> str:
    """把 provider 错误码映射到 typed outcome。"""
    if error_code == "E_API_RATE_LIMIT":
        return OUTCOME_RATE_LIMIT
    if error_code in ("E_API_NETWORK", "E_API_UPSTREAM", "E_API_BUSY"):
        return OUTCOME_NETWORK_FAILURE
    if error_code == "E_API_SCHEMA":
        return OUTCOME_SCHEMA_FAILURE
    return OUTCOME_VALIDATION_FAILURE
