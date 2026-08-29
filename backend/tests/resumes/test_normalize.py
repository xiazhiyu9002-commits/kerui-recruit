from decimal import Decimal

from kerui_recruit.resumes.normalize import normalize_resume
from kerui_recruit.resumes.structured import ParsedExperience, ParsedResume


def test_resume_normalization_trims_deduplicates_and_maps_enums() -> None:
    """Unnormalized provider spellings would split filters and corrupt matching."""
    normalized = normalize_resume(
        ParsedResume(
            name=" 张三 ",
            total_years=5.04,
            highest_degree="硕士",
            skills=["Python", "python", " 金融风控 "],
            summary="  金融科技后端工程师  ",
            experiences=[
                ParsedExperience(company=" 示例科技 ", title=" 后端工程师 ", summary=" 风控 ")
            ],
        )
    )

    assert normalized.name == "张三"
    assert normalized.total_years == Decimal("5.0")
    assert normalized.highest_degree == "MASTER"
    assert normalized.skills == ("Python", "金融风控")
    assert normalized.summary == "金融科技后端工程师"
    assert normalized.experiences[0].company == "示例科技"
