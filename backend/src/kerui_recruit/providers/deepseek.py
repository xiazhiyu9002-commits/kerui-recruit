from __future__ import annotations

import httpx

from kerui_recruit.providers.openai_compatible import OpenAICompatibleClient
from kerui_recruit.resumes.structured import ParsedResume

_RESUME_PARSE_PROMPT = """你是招聘顾问的结构化简历解析器。

任务：仅依据给定简历原文，返回符合 JSON Schema 的数据。

必须提取：姓名、总年限、最高学历、所在地、技能清单、核心摘要、工作经历、项目经验。

规则：
- 只能提取原文明确出现的信息；未知字段填 null（技能和经历列表可为空数组）；
- 学历用中文原文（如 博士/硕士/本科/大专）或英文（PhD/Master/Bachelor），不要翻译；
- 总年限输出数字（如 6.0），无法判断填 null；
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