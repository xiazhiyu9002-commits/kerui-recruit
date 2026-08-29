import json

import httpx
import pytest

from kerui_recruit.providers.deepseek import DeepSeekJdParser
from kerui_recruit.jd.structured import ParsedJd, ParsedJdRequirement


@pytest.mark.asyncio
async def test_deepseek_jd_parser_maps_json_to_parsed_jd() -> None:
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
                                    "title": "Java 后端工程师",
                                    "company": "某金融科技",
                                    "department": "支付",
                                    "location": "北京",
                                    "salary": "30-50K",
                                    "ai_category": "AI_RELATED",
                                    "tech_direction": ["Java", "Spring"],
                                    "business_direction": ["金融支付"],
                                    "industry": "金融",
                                    "min_years": 3.0,
                                    "highest_degree": "本科",
                                    "summary": "负责支付系统后端开发",
                                    "requirements": [
                                        {"kind": "MUST", "label": "技能", "value": "Java"},
                                        {"kind": "PLUS", "label": "行业", "value": "金融"},
                                    ],
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
    parser = DeepSeekJdParser(api_key="test-key", client=client)

    result = await parser.parse_jd("某金融科技招聘 Java 后端，3年，本科，金融支付")

    assert isinstance(result, ParsedJd)
    assert result.title == "Java 后端工程师"
    assert result.min_years == 3.0
    assert result.ai_category == "AI_RELATED"
    assert result.requirements[0] == ParsedJdRequirement(
        kind="MUST", label="技能", value="Java"
    )