from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "career-direction-v1"


@dataclass(frozen=True, slots=True)
class RoleFamily:
    code: str
    label: str
    aliases: tuple[str, ...] = ()


# 强关联别名用于规则引擎的「职位名称/职责」匹配（不含通用词）。通用词
# （Python/SQL/Java/Docker/Linux/Excel/数据分析/合规/风险/项目管理/系统设计）
# 单独不能形成高置信结论，因此不放进来，由 rules.py 的 GENERIC_SKILLS 单独处理。
ROLE_FAMILIES: tuple[RoleFamily, ...] = (
    # 业务与增长
    RoleFamily("SALES", "销售", ("销售", "大客户销售", "渠道销售", "直销", "电销", "客户经理")),
    RoleFamily("BD", "商务拓展", ("商务拓展", "商务bd", "业务拓展", "商务合作", "商务bd拓展")),
    RoleFamily("MARKETING", "市场/品牌/投放", ("市场", "品牌", "投放", "营销", "广告投放", "增长营销")),
    RoleFamily("OPERATIONS", "运营", ("用户运营", "内容运营", "活动运营", "产品运营", "运营")),
    RoleFamily("PRE_SALES", "售前/解决方案", ("售前", "解决方案", "方案架构", "售前顾问", "方案")),
    RoleFamily("SALES_OPS", "销售支持/销售运营", ("销售运营", "销售支持", "销售管理", "销售策略")),
    RoleFamily("CUSTOMER_SUCCESS", "客户成功", ("客户成功", "客户成功经理")),
    # 技术研发
    RoleFamily("BACKEND", "后端开发", ("后端", "后台", "服务端", "服务端开发", "后端开发")),
    RoleFamily("FRONTEND", "前端开发", ("前端", "web前端", "前端开发", "页面开发")),
    RoleFamily("MOBILE", "移动端开发", ("移动端", "ios开发", "android开发", "安卓开发", "客户端开发", "移动开发")),
    RoleFamily("QA", "测试/质量保障", ("测试", "质量保障", "自动化测试", "测试开发", "测试工程师")),
    RoleFamily("DEVOPS", "运维/SRE/DevOps", ("运维", "sre", "devops", "云原生", "基础设施", "系统运维", "kubernetes", "k8s")),
    RoleFamily("AI_ML", "算法/机器学习/大模型", ("算法", "机器学习", "深度学习", "大模型", "llm", "nlp", "计算机视觉", "推荐算法", "aigc", "模型训练")),
    RoleFamily("DATA_ENGINEERING", "数据开发/数仓/ETL", ("数据开发", "数仓", "数据仓库", "etl", "大数据开发", "数据平台", "spark", "flink", "hive")),
    RoleFamily("DATA_ANALYSIS", "数据分析/商业分析", ("数据分析", "商业分析", "bi分析师", "经营分析", "数据运营")),
    RoleFamily("SECURITY_ENGINEERING", "网络/信息安全工程", ("信息安全", "网络安全", "渗透", "攻防", "安全工程", "安全研发", "安全运营")),
    RoleFamily("EMBEDDED_HARDWARE", "硬件/嵌入式/驱动", ("嵌入式", "驱动开发", "硬件", "单片机", "fpga", "rtos", "固件")),
    # 产品、设计和交付
    RoleFamily("PRODUCT", "产品经理", ("产品经理", "产品总监", "产品策划")),
    RoleFamily("UI_DESIGN", "UI/视觉设计", ("ui设计", "视觉设计", "界面设计")),
    RoleFamily("UX_DESIGN", "UX/交互设计", ("ux设计", "交互设计", "交互", "用户体验")),
    RoleFamily("INDUSTRIAL_DESIGN", "工业设计", ("工业设计", "结构设计")),
    RoleFamily("PROJECT_MANAGEMENT", "项目管理", ("项目管理", "项目经理", "pmo")),
    RoleFamily("DELIVERY_IMPLEMENTATION", "实施/交付", ("实施工程师", "交付工程师", "实施", "交付")),
    # 风险和合规
    RoleFamily("RISK_STRATEGY", "风控策略/反欺诈/信用风险策略", ("风控", "反欺诈", "信用风险", "风险策略", "风控策略", "风控模型")),
    RoleFamily("AML_COMPLIANCE", "反洗钱/KYC/制裁/监管合规", ("反洗钱", "aml", "kyc", "制裁", "监管合规")),
    # 职能
    RoleFamily("HR", "人力资源", ("人力资源", "hrbp", "招聘", "人事", "员工关系")),
    RoleFamily("FINANCE", "财务", ("财务", "会计", "财务分析", "出纳", "金融财务")),
    RoleFamily("LEGAL", "法务/合同/诉讼/知识产权", ("法务", "合同", "诉讼", "知识产权", "专利")),
    RoleFamily("ADMIN", "行政", ("行政专员", "行政助理", "行政")),
    RoleFamily("PROCUREMENT", "采购", ("采购经理", "采购", "供应链采购")),
)

ROLE_FAMILY_BY_CODE: dict[str, RoleFamily] = {rf.code: rf for rf in ROLE_FAMILIES}

LEADERSHIP_LABELS: dict[str, str] = {
    "IC": "专业岗位",
    "TEAM_LEAD": "团队负责人",
    "DEPARTMENT_HEAD": "部门负责人",
    "EXECUTIVE": "高管",
}

BUSINESS_DOMAIN_LABELS: dict[str, str] = {
    "PAYMENTS": "支付",
    "AML": "反洗钱",
    "FINANCE_BANKING": "金融/银行",
    "ECOMMERCE": "电商",
    "ENTERPRISE_SOFTWARE": "企业软件",
    "INTERNET_CONSUMER": "互联网消费",
    "MANUFACTURING": "制造",
    "HEALTHCARE": "医疗健康",
    "OTHER": "其他",
}


def role_codes() -> tuple[str, ...]:
    return tuple(ROLE_FAMILY_BY_CODE)


def role_label(code: str) -> str | None:
    rf = ROLE_FAMILY_BY_CODE.get(code)
    return rf.label if rf else None


def is_valid_role_code(code: str) -> bool:
    return code in ROLE_FAMILY_BY_CODE


def leadership_label(code: str) -> str | None:
    return LEADERSHIP_LABELS.get(code)


def is_valid_leadership_code(code: str) -> bool:
    return code in LEADERSHIP_LABELS


def domain_label(code: str) -> str | None:
    return BUSINESS_DOMAIN_LABELS.get(code)


def is_valid_domain_code(code: str) -> bool:
    return code in BUSINESS_DOMAIN_LABELS
