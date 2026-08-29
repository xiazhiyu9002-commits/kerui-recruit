from __future__ import annotations

import httpx
from pydantic import BaseModel

from kerui_recruit.bd_search.service import LeadExtractor, LeadInfo, RegexLeadExtractor


class ParsedLead(BaseModel):
    company: str | None = None
    job_title: str | None = None


_LEAD_EXTRACT_PROMPT = """你是招聘领域的线索提取器。

任务：从给定网页的标题和正文中，提取「招聘公司名」和「岗位名称」。

规则：
- company：发布该招聘岗位的公司名；若正文中未明确出现公司名，填 null；
- job_title：岗位名称（如「高级 Java 开发工程师」）；若未出现，填 null；
- 不要臆造，只提取原文明确出现的信息；
- 只输出 JSON 对象，不要输出 markdown 代码块或多余文字。

标题：{title}
正文：{body}"""


class DeepSeekLeadExtractor:
    """Extract company/job from web results using DeepSeek JSON mode.

    Falls back to :class:`RegexLeadExtractor` when the LLM call fails or
    returns nothing, so BD search never breaks on provider errors.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client
        self._fallback = RegexLeadExtractor()

    def extract(
        self, title: str, snippet: str, raw_content: str | None = None
    ) -> LeadInfo:
        body = (raw_content or snippet)[:4000]
        try:
            client = self._client or httpx.Client(timeout=30.0)
            try:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": _LEAD_EXTRACT_PROMPT.format(
                                    title=title, body=body
                                ),
                            }
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                    },
                    timeout=httpx.Timeout(60.0, connect=10.0),
                )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                parsed = ParsedLead.model_validate_json(content)
            finally:
                if self._client is None:
                    client.close()

            if not parsed.company and not parsed.job_title:
                return self._fallback.extract(title, snippet, raw_content)
            return LeadInfo(company=parsed.company, job_title=parsed.job_title)
        except Exception:
            return self._fallback.extract(title, snippet, raw_content)
