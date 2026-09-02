from __future__ import annotations

from kerui_recruit.resumes.quality import analyze_text
from kerui_recruit.resumes.structured import ParsedExperience, ParsedResume
from kerui_recruit.resumes.validity import check_parsed_resume


def _source() -> str:
    return (
        "张三\n工作经历：某科技公司 风控工程师，负责支付风控平台研发，"
        "使用 Python 构建高并发交易系统。\n教育经历：某大学 计算机科学与技术 本科。"
    )


def _repetitive_resume() -> str:
    # 真实简历常有多段工作经历措辞重复，不应被误判为水印。
    duties = "对接各海外支付渠道及国际卡组织合规风控要求，包括但不限于基于渠道要求设计风控模型和规则。"
    return (
        "蒲雪 女 13926242131\n"
        "教育经历 云南大学 软件工程 本科\n"
        "工作经历\n"
        f"2022.07 - 至今 广州某科技 风控策略经理\n工作内容:\n1、{duties}\n2、合规风控并举，精准描绘用户画像。\n"
        f"2021.09 - 2022.07 广州某网络 资深风控运营\n工作内容:\n1、{duties}\n2、负责支付渠道的项目对接。\n"
        f"2019.12 - 2021.09 某支付公司 风控经理\n工作内容:\n1、{duties}\n2、负责反洗钱及合规管理。\n"
    )


def test_repetitive_resume_text_is_meaningful() -> None:
    """有重复措辞的真实简历不得被当作水印（dominant_ratio 低、repeated_ratio 高）。"""
    quality = analyze_text(_repetitive_resume())

    assert quality.meaningful is True
    assert quality.dominant_ratio < 0.5
    assert quality.repeated_ratio > 0.6


def test_nearly_empty_json_with_content_source_requires_review() -> None:
    result = check_parsed_resume(ParsedResume(), _source())

    assert result.ok is False
    assert result.error_code == "E_PENDING_REVIEW"


def test_nearly_empty_json_with_empty_source_is_structured_empty() -> None:
    result = check_parsed_resume(ParsedResume(), "")

    assert result.ok is False
    assert result.error_code == "E_STRUCTURED_EMPTY"


def test_watermark_source_with_empty_parsed_is_not_pending_review() -> None:
    watermark = "机密-内部资料-禁止外传-CONFIDENTIAL\n" * 8
    result = check_parsed_resume(ParsedResume(), watermark)

    assert result.ok is False
    assert result.error_code == "E_STRUCTURED_EMPTY"


def test_fresh_grad_without_experience_passes() -> None:
    parsed = ParsedResume(
        name="张三",
        highest_degree="本科",
        school="某大学",
        skills=["Python"],
    )

    result = check_parsed_resume(parsed, _source())

    assert result.ok is True


def test_anonymous_resume_with_experience_passes() -> None:
    parsed = ParsedResume(
        skills=["Java"],
        experiences=[ParsedExperience(company="某公司", title="工程师")],
    )

    result = check_parsed_resume(parsed, _source())

    assert result.ok is True


def test_valid_full_resume_passes() -> None:
    parsed = ParsedResume(
        name="张三",
        total_years=5,
        highest_degree="硕士",
        skills=["Python", "金融风控"],
        summary="金融科技后端工程师",
        experiences=[ParsedExperience(company="示例科技", title="后端工程师")],
    )

    result = check_parsed_resume(parsed, _source())

    assert result.ok is True
