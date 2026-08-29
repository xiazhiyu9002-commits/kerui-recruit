from __future__ import annotations

import json

import httpx
import pytest

from kerui_recruit.providers.deepseek import DeepSeekResumeParser
from kerui_recruit.resumes.structured import ParsedResume


@pytest.mark.asyncio
async def test_deepseek_parser_maps_json_to_parsed_resume() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "name": "张三",
                                    "total_years": 6.0,
                                    "highest_degree": "硕士",
                                    "location": "上海",
                                    "skills": ["Python", "Java"],
                                    "summary": "金融风控",
                                    "experiences": [
                                        {"company": "A", "title": "工程师", "summary": "支付"}
                                    ],
                                    "projects": [{"name": "P", "summary": "结算"}],
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://test"
    )
    parser = DeepSeekResumeParser(api_key="test-key", client=client)

    result = await parser.parse_resume("张三 6年 硕士 Python")

    assert isinstance(result, ParsedResume)
    assert result.name == "张三"
    assert result.total_years == 6.0
    assert result.skills == ["Python", "Java"]
    assert result.experiences[0].company == "A"