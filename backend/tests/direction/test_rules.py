from __future__ import annotations

from kerui_recruit.direction.rules import RuleInput, classify


def test_payment_risk_strategy():
    result = classify(RuleInput(
        recent_title="风控策略专家",
        recent_duties="负责支付交易风险策略、规则设计及效果监控",
    ))
    assert result.role_candidates[0].code == "RISK_STRATEGY"


def test_aml_kyc():
    result = classify(RuleInput(
        recent_title="反洗钱合规专家",
        recent_duties="负责AML/KYC反洗钱调查与制裁筛查",
    ))
    assert result.role_candidates[0].code == "AML_COMPLIANCE"


def test_penetration_attack():
    result = classify(RuleInput(
        recent_title="安全工程师",
        recent_duties="负责渗透测试与攻防演练",
    ))
    assert result.role_candidates[0].code == "SECURITY_ENGINEERING"


def test_contract_litigation():
    result = classify(RuleInput(
        recent_title="法务经理",
        recent_duties="负责合同审核与诉讼管理",
    ))
    assert result.role_candidates[0].code == "LEGAL"


def test_python_alone_is_not_ai():
    result = classify(RuleInput(skills=("python",)))
    assert all(c.code != "AI_ML" for c in result.role_candidates)


def test_docker_alone_is_not_devops():
    result = classify(RuleInput(skills=("docker",)))
    assert all(c.code != "DEVOPS" for c in result.role_candidates)


def test_compliance_alone_is_not_aml():
    result = classify(RuleInput(skills=("合规",)))
    assert all(c.code != "AML_COMPLIANCE" for c in result.role_candidates)


def test_leadership_does_not_replace_direction():
    result = classify(RuleInput(
        recent_title="后端开发经理",
        recent_duties="负责后端服务端开发",
    ))
    assert result.role_candidates[0].code == "BACKEND"
    assert result.leadership_candidate is not None
    assert result.leadership_candidate.code == "TEAM_LEAD"


def test_conflict_detection():
    result = classify(RuleInput(
        recent_title="风控与反洗钱专家",
        recent_duties="负责风控策略与反洗钱调查",
    ))
    assert result.conflicts, "应检测到两个方向信号接近的冲突"


def test_fallback_eligible():
    result = classify(RuleInput(
        recent_title="后端开发工程师",
        recent_duties="负责后端服务端开发与系统设计",
        history_titles=("后端开发",),
    ))
    assert result.role_candidates[0].code == "BACKEND"
    assert result.fallback_eligible is True


def test_generic_skill_alone_no_direction():
    result = classify(RuleInput(skills=("python", "sql", "java", "docker", "linux")))
    assert result.role_candidates == []
