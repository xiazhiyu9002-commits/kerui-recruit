from __future__ import annotations

import httpx

from kerui_recruit.jd.structured import ParsedJd
from kerui_recruit.providers.openai_compatible import OpenAICompatibleClient
from kerui_recruit.resumes.structured import ParsedResume

_RESUME_PARSE_PROMPT = """你是招聘顾问的结构化简历解析器。

任务：仅依据给定简历原文，返回符合 JSON Schema 的数据。

必须提取：姓名、总年限、最高学历、所在地、毕业院校、QS 排名、毕业年份、行业、技能清单、核心摘要、工作经历、项目经验。

规则：
- 只能提取原文明确出现的信息；未知字段填 null（技能和经历列表可为空数组）；
- 学历用中文原文（如 博士/硕士/本科/大专）或英文（PhD/Master/Bachelor），不要翻译；
- 总年限输出数字（如 6.0），无法判断填 null；
- 毕业院校（school）填学校名称；QS 排名（qs_rank）填数字，无法判断填 null；
- 毕业年份（graduation_year）填数字年份，无法判断填 null；
- 行业（industry）填候选人所处行业（如 互联网/金融/制造），无法判断填 null；
- 技能清单只输出原文出现的具体技能词，不编造；
- 工作经历每项提取 company、title、summary 三个字段；
- 项目经历每项提取 name、summary 两个字段；
- 只输出 JSON 对象，不要输出任何多余文字或 markdown 代码块。

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