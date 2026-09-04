"""本地规则引擎：独立判断职业方向，不访问网络与数据库。

规则不负责第一版主判，只负责提取独立信号、校验 LLM、发现冲突与兜底。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from kerui_recruit.direction.models import (
    BusinessDomainLabel,
    LeadershipLabel,
    RuleCandidate,
    RuleClassification,
)
from kerui_recruit.direction.taxonomy import (
    ROLE_FAMILIES,
    domain_label,
    leadership_label,
    role_label,
)

# 通用词单独不能形成强规则，单独出现时只给极低权重且不映射到任何方向。
GENERIC_SKILLS: frozenset[str] = frozenset({
    "python", "sql", "java", "docker", "linux", "excel",
    "数据分析", "合规", "风险", "项目管理", "系统设计",
})

# 强关联技能：能对方向提供弱支持（0.5 分），但单独不能定方向。
SKILL_HINTS: dict[str, tuple[str, ...]] = {
    "AI_ML": ("pytorch", "tensorflow", "transformer", "大模型", "深度学习", "机器学习"),
    "DATA_ENGINEERING": ("spark", "flink", "hive", "数仓", "etl", "数据管道"),
    "DATA_ANALYSIS": ("tableau", "powerbi", "数据可视化", "abtest", "ab测试"),
    "DEVOPS": ("kubernetes", "k8s", "terraform", "ci/cd", "ansible"),
    "FRONTEND": ("react", "vue", "typescript", "webpack"),
    "MOBILE": ("flutter", "swift", "kotlin", "react-native"),
    "BACKEND": ("spring", "django", "fastapi", "grpc", "微服务"),
    "EMBEDDED_HARDWARE": ("嵌入式", "单片机", "fpga", "rtos"),
    "SECURITY_ENGINEERING": ("渗透", "攻防", "安全", "漏洞"),
}

_LEADERSHIP_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EXECUTIVE", ("ceo", "cto", "cfo", "vp", "总裁", "创始人", "合伙人", "首席", "总经理")),
    ("DEPARTMENT_HEAD", ("总监", "负责人", "主管", "部长", "部门经理", "head of")),
    ("TEAM_LEAD", ("经理", "组长", "team lead", "团队负责人", "lead")),
)

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "PAYMENTS": ("支付", "第三方支付", "收单"),
    "AML": ("反洗钱", "aml", "kyc", "制裁"),
    "FINANCE_BANKING": ("银行", "金融", "证券", "保险", "信贷"),
    "ECOMMERCE": ("电商", "电子商务", "零售电商"),
    "ENTERPRISE_SOFTWARE": ("企业服务", "企业软件", "saas", "to b"),
    "INTERNET_CONSUMER": ("互联网", "消费互联网", "社交", "短视频", "直播"),
    "MANUFACTURING": ("制造", "工业", "工厂", "供应链"),
    "HEALTHCARE": ("医疗", "健康", "医药", "医院"),
}


@dataclass(slots=True)
class RuleInput:
    recent_title: str = ""
    recent_duties: str = ""
    history_titles: tuple[str, ...] = ()
    project_summaries: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    industry: str = ""
    business_scene: str = ""


@dataclass(slots=True)
class _Accum:
    scores: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    matched_rules: set[str] = field(default_factory=set)


_ALIAS_INDEX: dict[str, str] = {}
for _rf in ROLE_FAMILIES:
    for _alias in _rf.aliases:
        _ALIAS_INDEX[_alias.casefold()] = _rf.code


def _add(accum: _Accum, code: str, weight: float, evidence: str, rule_id: str) -> None:
    accum.scores[code] = accum.scores.get(code, 0.0) + weight
    accum.evidence.setdefault(code, []).append(evidence)
    accum.matched_rules.add(rule_id)


def _match_aliases(text: str) -> Iterable[tuple[str, str]]:
    if not text:
        return
    lowered = text.casefold()
    for alias, code in _ALIAS_INDEX.items():
        if alias in lowered:
            yield code, alias


def classify(payload: RuleInput) -> RuleClassification:
    accum = _Accum()

    def scan(text: str, weight: float, field_name: str, rule_id: str) -> None:
        for code, alias in _match_aliases(text):
            _add(accum, code, weight, f"{field_name}:{alias}", rule_id)

    scan(payload.recent_title, 5.0, "title", "rule_title")
    scan(payload.recent_duties, 3.0, "duty", "rule_duty")
    for title in payload.history_titles:
        scan(title, 2.0, "history", "rule_history")
    for summary in payload.project_summaries:
        scan(summary, 1.5, "project", "rule_project")
    for skill in payload.skills:
        lowered = skill.casefold()
        if lowered in {g.casefold() for g in GENERIC_SKILLS}:
            continue
        for code, hints in SKILL_HINTS.items():
            if any(hint.casefold() in lowered for hint in hints):
                _add(accum, code, 0.5, f"skill:{skill}", "rule_skill")

    ranked = sorted(accum.scores.items(), key=lambda item: -item[1])
    candidates: list[RuleCandidate] = []
    for code, score in ranked[:3]:
        if score <= 0:
            continue
        candidates.append(RuleCandidate(
            code=code,
            label=role_label(code) or code,
            confidence=_calibrate(score),
            evidence=accum.evidence[code][:3],
        ))

    conflicts = _detect_conflicts(candidates)
    fallback = _fallback_eligible(payload, candidates, conflicts, accum)
    leadership = _classify_leadership(payload.recent_title)
    domains = _classify_domains(payload)

    if candidates:
        candidates[0] = RuleCandidate(
            code=candidates[0].code,
            label=candidates[0].label,
            confidence=candidates[0].confidence,
            evidence=candidates[0].evidence,
            is_primary=True,
        )

    reason_parts: list[str] = []
    if fallback:
        reason_parts.append("规则具备兜底资格")
    elif candidates:
        reason_parts.append("规则信号不足或不满足兜底资格")
    else:
        reason_parts.append("规则无可靠结果")
    if conflicts:
        reason_parts.append(f"冲突:{';'.join(conflicts)}")

    return RuleClassification(
        role_candidates=candidates,
        leadership_candidate=leadership,
        domain_candidates=domains,
        matched_rule_ids=sorted(accum.matched_rules),
        evidence=[e for ev in accum.evidence.values() for e in ev][:10],
        conflicts=conflicts,
        fallback_eligible=fallback,
        decision_reason="；".join(reason_parts),
    )


def _calibrate(score: float) -> float:
    # 分数映射到 0~1，规则置信度保守上限 0.8。
    return round(min(0.8, score / 10.0), 4)


def _detect_conflicts(candidates: list[RuleCandidate]) -> list[str]:
    # 区分「风险/安全/合规/法务」易混方向：多个高置信候选且分差很小时视为冲突。
    if len(candidates) < 2:
        return []
    top, second = candidates[0], candidates[1]
    if top.confidence - second.confidence < 0.1:
        return [f"{top.code} 与 {second.code} 规则信号接近"]
    return []


def _fallback_eligible(
    payload: RuleInput,
    candidates: list[RuleCandidate],
    conflicts: list[str],
    accum: _Accum,
) -> bool:
    if not candidates or conflicts:
        return False
    top = candidates[0]
    if top.confidence < 0.4:
        return False
    # 最近职位名称必须明确命中。
    title_hit = any(alias for alias, code in _ALIAS_INDEX.items()
                    if code == top.code and alias in payload.recent_title.casefold())
    if not title_hit:
        return False
    # 最近职责支持同一方向。
    duty_hit = any(alias for alias, code in _ALIAS_INDEX.items()
                   if code == top.code and alias in payload.recent_duties.casefold())
    if not duty_hit:
        return False
    # 第一方向明显高于第二方向。
    if len(candidates) > 1 and top.confidence - candidates[1].confidence < 0.15:
        return False
    # 证据至少来自两个不同字段。
    fields = {ev.split(":", 1)[0] for ev in accum.evidence.get(top.code, [])}
    if len(fields) < 2:
        return False
    return True


def _classify_leadership(title: str) -> LeadershipLabel | None:
    if not title:
        return None
    lowered = title.casefold()
    for code, keywords in _LEADERSHIP_KEYWORDS:
        if any(k in lowered for k in keywords):
            return LeadershipLabel(code=code, label=leadership_label(code) or code,
                                   confidence=0.7, source="RULE")
    return None


def _classify_domains(payload: RuleInput) -> list[BusinessDomainLabel]:
    text = " ".join(part for part in (
        payload.recent_duties, payload.industry, payload.business_scene,
    ) if part).casefold()
    domains: list[BusinessDomainLabel] = []
    for code, keywords in _DOMAIN_KEYWORDS.items():
        if any(k.casefold() in text for k in keywords):
            domains.append(BusinessDomainLabel(code=code, label=domain_label(code) or code,
                                               confidence=0.7, source="RULE"))
    return domains[:5]
