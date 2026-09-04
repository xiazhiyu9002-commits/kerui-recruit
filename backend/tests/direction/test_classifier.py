from __future__ import annotations

import asyncio

from kerui_recruit.direction.classifier import DirectionClassificationInput, DirectionClassifier, DirectionProviderResult
from kerui_recruit.direction.models import (
    DirectionLLMDomain,
    DirectionLLMOutput,
    DirectionLLMRoleFamily,
)


class FakeLLM:
    def __init__(self, output: DirectionLLMOutput | None = None, error: Exception | None = None):
        self.output = output
        self.error = error
        self.calls = 0

    async def classify_direction(self, payload: DirectionClassificationInput) -> DirectionProviderResult:
        self.calls += 1
        if self.error is not None:
            return DirectionProviderResult(output=None, llm_attempts=1,
                                           schema_repair_attempts=0, success=False,
                                           error_code=type(self.error).__name__)
        assert self.output is not None
        return DirectionProviderResult(output=self.output, llm_attempts=1,
                                       schema_repair_attempts=0, success=True, error_code=None)


def _backend_input(**overrides) -> DirectionClassificationInput:
    data = dict(
        recent_title="后端开发工程师",
        recent_duties="负责后端服务端开发",
        history_titles=("后端开发",),
        skills=("java", "spring"),
        industry="互联网",
        business_scene="支付",
    )
    data.update(overrides)
    return DirectionClassificationInput(**data)


def _llm(primary: str, *codes: str, self_confidence: float = 0.9, is_unknown: bool = False) -> DirectionLLMOutput:
    role = [DirectionLLMRoleFamily(code=c, self_confidence=self_confidence, evidence=[f"负责{c}方向工作"]) for c in codes]
    return DirectionLLMOutput(primary_role_code=primary, role_family_codes=role, is_unknown=is_unknown)


def _run(provider, payload) -> object:
    return asyncio.run(DirectionClassifier(provider).classify(payload))


def test_llm_success_rule_agreement():
    decision = _run(FakeLLM(output=_llm("BACKEND", "BACKEND")), _backend_input())
    assert decision.agreement is True
    profile = decision.effective_profile
    assert profile.primary_role_code == "BACKEND"
    assert profile.status == "CONFIDENT"
    assert profile.role_families[0].source == "LLM"
    assert profile.role_families[0].label == "后端开发"


def test_llm_success_rule_no_result():
    payload = DirectionClassificationInput(recent_title="工程师", recent_duties="负责一些日常工作")
    decision = _run(FakeLLM(output=_llm("BACKEND", "BACKEND")), payload)
    assert decision.agreement is False
    assert decision.effective_profile.primary_role_code == "BACKEND"
    assert decision.effective_profile.role_families[0].source == "LLM"


def test_llm_success_rule_conflict_uncertain():
    decision = _run(FakeLLM(output=_llm("AI_ML", "AI_ML")), _backend_input())
    assert decision.agreement is False
    assert decision.effective_profile.status == "UNCERTAIN"
    assert decision.effective_profile.primary_role_code == "AI_ML"
    assert decision.effective_profile.role_families[0].confidence <= 0.65


def test_llm_failure_rule_fallback():
    decision = _run(FakeLLM(error=RuntimeError("timeout")), _backend_input())
    assert decision.used_rule_fallback is True
    assert decision.llm_error_code == "RuntimeError"
    assert decision.effective_profile.primary_role_code == "BACKEND"
    assert decision.effective_profile.role_families[0].source == "RULE"


def test_all_failed_unknown():
    payload = DirectionClassificationInput(recent_title="工程师", recent_duties="负责一些日常工作")
    decision = _run(FakeLLM(error=RuntimeError("timeout")), payload)
    assert decision.used_rule_fallback is False
    assert decision.effective_profile.status == "UNKNOWN"
    assert decision.effective_profile.primary_role_code is None


def test_llm_invalid_code_falls_back():
    output = DirectionLLMOutput(
        primary_role_code="BAD",
        role_family_codes=[DirectionLLMRoleFamily(code="BAD", self_confidence=0.9)],
    )
    decision = _run(FakeLLM(output=output), _backend_input())
    assert decision.used_rule_fallback is True


def test_llm_unknown_falls_back_to_rule():
    decision = _run(FakeLLM(output=DirectionLLMOutput(is_unknown=True)), _backend_input())
    assert decision.used_rule_fallback is True
    assert decision.effective_profile.primary_role_code == "BACKEND"


def test_llm_unknown_and_no_rule_result_is_unknown():
    payload = DirectionClassificationInput(recent_title="工程师", recent_duties="负责一些日常工作")
    decision = _run(FakeLLM(output=DirectionLLMOutput(is_unknown=True)), payload)
    assert decision.effective_profile.status == "UNKNOWN"


def test_llm_output_carries_no_label_source_version():
    fields = DirectionLLMOutput.model_fields
    assert "label" not in fields
    assert "source" not in fields
    assert "taxonomy_version" not in fields
    assert "classifier_version" not in fields


def test_llm_attempts_counted_on_success():
    decision = _run(FakeLLM(output=_llm("BACKEND", "BACKEND")), _backend_input())
    assert decision.llm_attempts == 1
    assert decision.llm_schema_repair_attempts == 0
    assert decision.llm_successes == 1
    assert decision.llm_failures == 0


def test_llm_attempts_counted_on_failure():
    decision = _run(FakeLLM(error=RuntimeError("timeout")), _backend_input())
    assert decision.llm_attempts == 1
    assert decision.llm_successes == 0
    assert decision.llm_failures == 1


def test_llm_success_unknown_not_counted_as_failure():
    decision = _run(FakeLLM(output=DirectionLLMOutput(is_unknown=True)), _backend_input())
    assert decision.llm_error_code is None
    assert decision.llm_successes == 1
    assert decision.llm_failures == 0
    assert decision.outcome == "SUCCESS_UNKNOWN"
    assert "无法判断" in decision.decision_reason
