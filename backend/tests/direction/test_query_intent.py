from __future__ import annotations

from kerui_recruit.direction.query_intent import detect


def test_java_backend():
    intent = detect("Java后端")
    assert intent.matched is True
    assert intent.role_code == "BACKEND"


def test_payment_risk_strategy():
    intent = detect("支付风控策略")
    assert intent.role_code == "RISK_STRATEGY"
    assert "PAYMENTS" in intent.domain_codes


def test_aml_investigation():
    intent = detect("反洗钱调查")
    assert intent.role_code == "AML_COMPLIANCE"
    assert "AML" in intent.domain_codes


def test_data_warehouse():
    intent = detect("数据仓库开发")
    assert intent.role_code == "DATA_ENGINEERING"


def test_presales_solution():
    intent = detect("售前解决方案")
    assert intent.role_code == "PRE_SALES"


def test_python_alone_no_intent():
    assert detect("Python").matched is False


def test_generic_words_no_intent():
    assert detect("风险").matched is False
    assert detect("合规").matched is False
    assert detect("安全").matched is False
