from __future__ import annotations

import pytest
from pydantic import ValidationError

from kerui_recruit.direction.models import (
    BusinessDomainLabel,
    DirectionLabel,
    DirectionLLMOutput,
    DirectionProfile,
    LeadershipLabel,
    build_direction_label,
    parse_direction_profile,
)


def test_unknown_profile_has_no_direction():
    profile = DirectionProfile.unknown()
    assert profile.status == "UNKNOWN"
    assert profile.role_families == []
    assert profile.primary_role_code is None


def test_max_three_role_families():
    labels = [build_direction_label(c, source="LLM", confidence=0.5, is_primary=(i == 0))
              for i, c in enumerate(["BACKEND", "AI_ML", "DATA_ENGINEERING", "DEVOPS"])]
    with pytest.raises(ValidationError):
        DirectionProfile(status="CONFIDENT", role_families=labels)


def test_exactly_one_primary_when_direction_exists():
    labels = [
        build_direction_label("BACKEND", source="LLM", confidence=0.8, is_primary=False),
        build_direction_label("AI_ML", source="LLM", confidence=0.7, is_primary=False),
    ]
    with pytest.raises(ValidationError, match="恰好一个主方向"):
        DirectionProfile(status="CONFIDENT", role_families=labels)


def test_invalid_role_code_rejected():
    label = DirectionLabel(code="BAD", label="bad", confidence=0.5, source="LLM", is_primary=True)
    with pytest.raises(ValidationError, match="非法职业方向编码"):
        DirectionProfile(status="CONFIDENT", role_families=[label])


def test_evidence_limits():
    with pytest.raises(ValidationError):
        build_direction_label(
            "BACKEND", source="LLM", confidence=0.5, is_primary=True,
            evidence=["e1", "e2", "e3", "e4"],
        )
    with pytest.raises(ValidationError):
        build_direction_label(
            "BACKEND", source="LLM", confidence=0.5, is_primary=True,
            evidence=["x" * 121],
        )


def test_evidence_rejects_phone_and_email():
    with pytest.raises(ValidationError, match="手机号"):
        build_direction_label(
            "BACKEND", source="LLM", confidence=0.5, is_primary=True,
            evidence=["联系 13812345678"],
        )
    with pytest.raises(ValidationError, match="邮箱"):
        build_direction_label(
            "BACKEND", source="LLM", confidence=0.5, is_primary=True,
            evidence=["联系 hr@example.com"],
        )


def test_leadership_evidence_validation():
    with pytest.raises(ValidationError, match="最多 3 条"):
        LeadershipLabel(code="TEAM_LEAD", label="x", confidence=0.8, source="LLM",
                        evidence=["a", "b", "c", "d"])
    with pytest.raises(ValidationError, match="手机号"):
        LeadershipLabel(code="TEAM_LEAD", label="x", confidence=0.8, source="LLM",
                        evidence=["13812345678"])
    with pytest.raises(ValidationError, match="120"):
        LeadershipLabel(code="TEAM_LEAD", label="x", confidence=0.8, source="LLM",
                        evidence=["x" * 121])


def test_domain_evidence_validation():
    with pytest.raises(ValidationError, match="邮箱"):
        BusinessDomainLabel(code="FINANCE", label="x", confidence=0.8, source="LLM",
                            evidence=["hr@example.com"])
    with pytest.raises(ValidationError, match="120"):
        BusinessDomainLabel(code="FINANCE", label="x", confidence=0.8, source="LLM",
                            evidence=["x" * 121])


def test_user_source_confidence_normalized_to_one():
    label = DirectionLabel(code="BACKEND", label="后端开发", confidence=0.3, source="USER", is_primary=True)
    assert label.confidence == 1.0


def test_primary_role_code_property():
    profile = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("BACKEND", source="LLM", confidence=0.8, is_primary=True),
        build_direction_label("AI_ML", source="LLM", confidence=0.6, is_primary=False),
    ])
    assert profile.primary_role_code == "BACKEND"
    assert profile.all_role_codes == ("BACKEND", "AI_ML")
    assert profile.dominant_source == "LLM"
    assert not profile.is_manual


def test_manual_profile_detected():
    profile = DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label("BACKEND", source="USER", confidence=1.0, is_primary=True),
    ])
    assert profile.is_manual


def test_parse_direction_profile_safe_on_missing_or_invalid():
    assert parse_direction_profile(None).status == "UNKNOWN"
    assert parse_direction_profile({}).status == "UNKNOWN"
    assert parse_direction_profile({"status": "CONFIDENT"}).status == "CONFIDENT"
    assert parse_direction_profile({"status": "BOGUS"}).status == "UNKNOWN"


def test_llm_output_primary_must_exist_in_role_families():
    from kerui_recruit.direction.models import DirectionLLMRoleFamily
    with pytest.raises(ValidationError, match="primary_role_code"):
        DirectionLLMOutput(
            primary_role_code="BACKEND",
            role_family_codes=[DirectionLLMRoleFamily(code="AI_ML", self_confidence=0.9)],
        )
