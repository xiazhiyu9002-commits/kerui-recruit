from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from kerui_recruit.jd.structured import ParsedJd
from kerui_recruit.providers.openai_compatible import OpenAICompatibleClient
from kerui_recruit.resumes.structured import ParsedResume

_RESUME_PARSE_PROMPT = """你是资深招聘顾问，负责把简历原文解析为结构化 JSON。

输出一个 JSON 对象，字段如下：
- name：姓名；
- total_years：总工作年限，数字。按最早一段工作的起始年月到"至今"（当前时间）计算总年数，四舍五入到 0.5 年（如 2020.07 至今约 6.0）；
- highest_degree：最高学历（博士/硕士/本科/大专）。可从"本科/学士/硕士/博士"等字样，或从入学与毕业年份（如 2016-2020 通常为本科）推断；
- birth_year：出生年份数字，从"出生年月/出生日期"提取，无法判断填 null；
- location：现居地/所在地城市；
- preferred_location：期望工作城市，无法判断填 null；
- school：毕业院校名称；
- school_level：学校等级，取 985 / 211 / 双一流 / 普通 / 海外 之一，无法判断填 null；
- qs_rank：QS 排名数字，无法确定填 null；
- graduation_year：毕业年份数字；
- industry：候选人主要行业（如 互联网/金融/制造）；
- current_industry：最近一份工作所属行业；
- longest_industry：任职年限最长的那份工作所属行业；
- tech_direction：技术方向标准词数组（如 Go、微服务架构、前端开发、系统架构、机器学习），从工作与项目内容提炼；
- business_direction：业务方向标准词数组（如 直播生态、开放平台、电商交易、安全风控），从工作与项目内容提炼；
- skills：具体技能词数组（编程语言、框架、中间件等），不要填"数据结构、操作系统"这类课程名或软技能；
- summary：用一两句话概括候选人的核心工作方向与专长（基于工作经历和项目提炼，不要照抄自我评价）；
- experiences：工作经历数组，每项含 company（公司名）、title（职位）、industry（该段工作所属行业）、summary（该段工作做了什么，可概括多个项目点）；
- projects：项目经历数组，每项含 name（项目名）、tech_stack（技术栈，如 Go/微服务）、business_scene（业务场景一句话）、summary（项目职责或成果）。

规则：
- 优先从原文提取，允许对年限、学历、行业做合理推断；
- 同一段工作下的多个项目点，应拆成独立的 projects 条目，同时 experiences 的 summary 概括该段整体；
- 未出现且无法推断的字段填 null，方向/技能/经历列表可为空数组；
- 只输出 JSON 对象，不要输出 markdown 代码块或任何多余文字。

简历原文：
{resume_text}"""


class DeepSeekResumeParser:
    """Parse resumes into :class:`ParsedResume` using DeepSeek's JSON mode."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
    ) -> None:
        self._llm = OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            http_client=client,
        )

    async def parse_resume(self, text: str) -> ParsedResume:
        return await self._llm.complete_json(
            messages=[
                {
                    "role": "user",
                    "content": _RESUME_PARSE_PROMPT.format(resume_text=text),
                }
            ],
            response_model=ParsedResume,
        )


_JD_PARSE_PROMPT = """你是资深招聘顾问，负责把 JD 解析为可检索结构。

任务：根据 JD 原文输出 JSON 对象，字段如下：
- title：岗位名称；
- company：公司名（原文未提填空字符串）；
- department：部门（可空）；
- location：工作地点（可空）；
- salary：薪资范围（可空）；
- ai_category：AI 分类，三选一 CORE_AI（职责核心是模型/算法/训练/推理/LLM/数据科学）、AI_RELATED（与 AI 产品协作但非核心）、NON_AI（其他）；
- tech_direction：技术方向词数组；
- business_direction：业务方向词数组；
- industry：行业；
- min_years：最低相关年限，数字（无法判断填 null）；
- highest_degree：最低学历（博士/硕士/本科/大专）；
- qs_level：QS 排名等级要求，如 前50/前100/前200/不限（无法判断填 null）；
- core_duties：核心职责数组，每条写成"动词+宾语+指标"的短句（如"负责推荐系统召回，提升点击率20%"）；
- required_skills：必需技能数组（编程语言、框架、中间件等硬技能）；
- plus_industry：加分场景-行业背景数组（如 金融/电商/广告）；
- plus_project_types：加分场景-项目类型数组（如 高并发交易系统/大模型应用）；
- summary：岗位最核心要求一句话，不超过 60 字；
- requirements：数组，每项含 kind（MUST 必备 / PLUS 加分 / EXCLUDE 排除）、label（如 技能/学历/行业/地点/证书）、value（具体值）。

规则：必须/优先/排除分别识别，不能把加分当必须；没有证据填 null 或空；只输出 JSON 对象，不要 markdown。

JD 原文：
{jd_text}"""


class DeepSeekJdParser:
    """Parse JDs into :class:`ParsedJd` using DeepSeek's JSON mode."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
    ) -> None:
        self._llm = OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            http_client=client,
        )

    async def parse_jd(self, text: str) -> ParsedJd:
        return await self._llm.complete_json(
            messages=[
                {"role": "user", "content": _JD_PARSE_PROMPT.format(jd_text=text)}
            ],
            response_model=ParsedJd,
        )

    async def split_jds(self, text: str) -> list[str]:
        result = await self._llm.complete_json(
            messages=[
                {"role": "user", "content": _JD_SPLIT_PROMPT.format(jd_text=text)}
            ],
            response_model=JdSplit,
        )
        chunks = [chunk.strip() for chunk in result.chunks if chunk.strip()]
        return chunks or [text.strip()]


_JD_SPLIT_PROMPT = """你是招聘系统，负责把一段可能包含多个岗位的 JD 文本拆分成独立的 JD。

任务：把原文中每一个独立岗位的 JD 拆出来，按顺序返回一个 JSON 对象：
{{"chunks": ["<第一个 JD 的原文>", "<第二个 JD 的原文>", ...]}}

规则：
- 原文可能是纯文本、或从 Word/Excel 提取出的文字，可能包含一个或多个岗位；
- 每个 chunk 只保留该岗位相关的原文（可含标题/职责/要求等），不要改写、不要总结、不要遗漏；
- 如果原文只有一个岗位，返回仅含一个元素的数组；
- 只输出 JSON 对象，不要 markdown 代码块或任何多余文字。

JD 原文：
{jd_text}"""


class JdSplit(BaseModel):
    chunks: list[str] = Field(default_factory=list)