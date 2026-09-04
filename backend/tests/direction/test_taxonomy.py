from __future__ import annotations

import pytest

from kerui_recruit.direction import taxonomy


def test_role_codes_are_unique():
    codes = taxonomy.role_codes()
    assert len(codes) == len(set(codes))


def test_every_role_family_has_label_and_aliases():
    for code in taxonomy.role_codes():
        assert taxonomy.role_label(code), code
        rf = taxonomy.ROLE_FAMILY_BY_CODE[code]
        assert rf.aliases, code


def test_known_role_labels():
    assert taxonomy.role_label("BACKEND") == "后端开发"
    assert taxonomy.role_label("RISK_STRATEGY") == "风控策略/反欺诈/信用风险策略"
    assert taxonomy.role_label("AML_COMPLIANCE") == "反洗钱/KYC/制裁/监管合规"
    assert taxonomy.role_label("SECURITY_ENGINEERING") == "网络/信息安全工程"
    assert taxonomy.role_label("LEGAL") == "法务/合同/诉讼/知识产权"


def test_is_valid_role_code():
    assert taxonomy.is_valid_role_code("AI_ML")
    assert not taxonomy.is_valid_role_code("NOT_A_DIRECTION")


def test_leadership_labels():
    assert taxonomy.is_valid_leadership_code("IC")
    assert taxonomy.is_valid_leadership_code("EXECUTIVE")
    assert not taxonomy.is_valid_leadership_code("BACKEND")
    assert taxonomy.leadership_label("TEAM_LEAD") == "团队负责人"


def test_domain_labels():
    assert taxonomy.is_valid_domain_code("PAYMENTS")
    assert not taxonomy.is_valid_domain_code("BACKEND")
    assert taxonomy.domain_label("AML") == "反洗钱"
