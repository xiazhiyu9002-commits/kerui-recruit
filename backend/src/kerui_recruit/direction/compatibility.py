from __future__ import annotations

from kerui_recruit.direction.models import DirectionProfile

COMPATIBILITY_VERSION = "direction-compatibility-v1"

# 相邻关系：职业方向之间允许的软性相邻，用于方向兼容分。
ADJACENCY: dict[frozenset[str], float] = {
    frozenset(("BACKEND", "DATA_ENGINEERING")): 0.70,
    frozenset(("BACKEND", "DEVOPS")): 0.65,
    frozenset(("AI_ML", "DATA_ENGINEERING")): 0.75,
    frozenset(("AI_ML", "DATA_ANALYSIS")): 0.70,
    frozenset(("DATA_ANALYSIS", "RISK_STRATEGY")): 0.70,
    frozenset(("RISK_STRATEGY", "AML_COMPLIANCE")): 0.65,
    frozenset(("SALES", "BD")): 0.75,
    frozenset(("SALES", "PRE_SALES")): 0.65,
    frozenset(("SALES", "SALES_OPS")): 0.55,
    frozenset(("OPERATIONS", "CUSTOMER_SUCCESS")): 0.70,
    frozenset(("PRODUCT", "PROJECT_MANAGEMENT")): 0.65,
    frozenset(("PRE_SALES", "DELIVERY_IMPLEMENTATION")): 0.70,
}


def direction_compatibility(jd: DirectionProfile, candidate: DirectionProfile) -> float:
    """返回 0~1 的方向兼容分；UNKNOWN 方向按 0.5 处理。"""
    jd_primary = jd.primary_role_code
    cand_primary = candidate.primary_role_code
    if jd_primary is None or cand_primary is None:
        return 0.5
    raw = _raw_score(jd_primary, cand_primary, set(jd.all_role_codes), set(candidate.all_role_codes))
    jd_conf = _primary_confidence(jd)
    cand_conf = _primary_confidence(candidate)
    return round(0.5 + (raw - 0.5) * min(jd_conf, cand_conf), 4)


def _raw_score(jd_primary: str, cand_primary: str, jd_codes: set[str], cand_codes: set[str]) -> float:
    if jd_primary == cand_primary:
        return 1.0
    if jd_primary in cand_codes:
        return 0.85
    if cand_primary in jd_codes:
        return 0.85
    direct = ADJACENCY.get(frozenset((jd_primary, cand_primary)))
    if direct is not None:
        return direct
    best = None
    for jc in jd_codes:
        for cc in cand_codes:
            adj = ADJACENCY.get(frozenset((jc, cc)))
            if adj is not None and (best is None or adj > best):
                best = adj
    return best if best is not None else 0.10


def _primary_confidence(profile: DirectionProfile) -> float:
    for role in profile.role_families:
        if role.is_primary:
            return role.confidence
    return 0.5
