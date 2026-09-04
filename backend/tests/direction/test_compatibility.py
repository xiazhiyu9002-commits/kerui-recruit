from __future__ import annotations

from kerui_recruit.direction.compatibility import direction_compatibility
from kerui_recruit.direction.models import DirectionProfile, build_direction_label


def _profile(primary: str | None, codes: tuple[str, ...], confidence: float = 1.0, source: str = "USER") -> DirectionProfile:
    if primary is None:
        return DirectionProfile.unknown()
    labels = [build_direction_label(c, source=source, confidence=confidence, is_primary=(c == primary)) for c in codes]
    return DirectionProfile(status="CONFIDENT", role_families=labels)


def test_same_primary_is_one():
    assert direction_compatibility(_profile("BACKEND", ("BACKEND",)), _profile("BACKEND", ("BACKEND",))) == 1.0


def test_jd_primary_hits_candidate_secondary():
    jd = _profile("BACKEND", ("BACKEND", "AI_ML"))
    cand = _profile("AI_ML", ("AI_ML", "BACKEND"))
    assert direction_compatibility(jd, cand) == 0.85


def test_unknown_is_half():
    assert direction_compatibility(_profile("BACKEND", ("BACKEND",)), DirectionProfile.unknown()) == 0.5


def test_adjacency_backend_data_engineering():
    score = direction_compatibility(_profile("BACKEND", ("BACKEND",)), _profile("DATA_ENGINEERING", ("DATA_ENGINEERING",)))
    assert score == 0.70


def test_adjacency_sales_bd():
    score = direction_compatibility(_profile("SALES", ("SALES",)), _profile("BD", ("BD",)))
    assert score == 0.75


def test_unrelated_low_score_contracts_toward_half():
    jd = _profile("RISK_STRATEGY", ("RISK_STRATEGY",), confidence=0.5, source="LLM")
    cand = _profile("LEGAL", ("LEGAL",), confidence=0.5, source="LLM")
    score = direction_compatibility(jd, cand)
    assert 0.1 < score < 0.5
