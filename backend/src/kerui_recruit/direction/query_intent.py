from __future__ import annotations

from kerui_recruit.direction.models import QueryDirectionIntent
from kerui_recruit.direction.taxonomy import ROLE_FAMILIES

# 方向意图关键词（职位/职责类），通用词不在此列。
_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {rf.code: rf.aliases for rf in ROLE_FAMILIES}

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "PAYMENTS": ("支付", "第三方支付", "收单"),
    "AML": ("反洗钱", "aml", "kyc", "制裁"),
    "FINANCE_BANKING": ("银行", "金融", "证券", "保险", "信贷"),
    "ECOMMERCE": ("电商", "电子商务"),
    "ENTERPRISE_SOFTWARE": ("企业服务", "企业软件", "saas", "to b"),
    "INTERNET_CONSUMER": ("互联网", "社交", "短视频", "直播"),
    "MANUFACTURING": ("制造", "工业", "工厂", "供应链"),
    "HEALTHCARE": ("医疗", "健康", "医药", "医院"),
}


def detect(query: str) -> QueryDirectionIntent:
    """本地识别搜索词中的方向意图，不调用 LLM。"""
    if not query or not query.strip():
        return QueryDirectionIntent(matched=False)
    lowered = query.casefold()
    role_scores: dict[str, int] = {}
    for code, aliases in _ROLE_KEYWORDS.items():
        hits = sum(1 for alias in aliases if alias.casefold() in lowered)
        if hits:
            role_scores[code] = hits
    domain_codes = [code for code, keywords in _DOMAIN_KEYWORDS.items()
                    if any(k.casefold() in lowered for k in keywords)]
    if not role_scores and not domain_codes:
        return QueryDirectionIntent(matched=False)
    top_code = max(role_scores, key=role_scores.get) if role_scores else None
    confidence = min(0.9, 0.5 + 0.15 * max(role_scores.values())) if role_scores else 0.5
    return QueryDirectionIntent(
        role_code=top_code,
        domain_codes=domain_codes,
        confidence=round(confidence, 4),
        matched=True,
    )
