from __future__ import annotations

from kerui_recruit.bd_search.service import LeadInfo
from kerui_recruit.providers.leads import DeepSeekLeadExtractor


class _JsonResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeClient:
    def __init__(self, response: _JsonResponse) -> None:
        self.response = response
        self.captured_json: dict | None = None

    def post(self, url: str, *, headers: dict, json: dict, timeout) -> _JsonResponse:
        self.captured_json = json
        return self.response

    def close(self) -> None:
        return None


class _ErrorResponse:
    def raise_for_status(self) -> None:
        raise RuntimeError("boom")

    def json(self) -> dict:
        return {}


class _ErrorClient:
    def post(self, url: str, *, headers: dict, json: dict, timeout):
        return _ErrorResponse()

    def close(self) -> None:
        return None


def test_deepseek_extractor_maps_company_and_job() -> None:
    client = _FakeClient(
        _JsonResponse('{"company": "字节跳动科技有限公司", "job_title": "高级 Java 工程师"}')
    )
    extractor = DeepSeekLeadExtractor(api_key="test-key", client=client)  # type: ignore[arg-type]

    info = extractor.extract("字节跳动科技有限公司 — 高级 Java 工程师", "招聘高级 Java 工程师")

    assert info == LeadInfo(company="字节跳动科技有限公司", job_title="高级 Java 工程师")
    # Prompt must request JSON-only structured output.
    assert client.captured_json is not None
    assert client.captured_json["response_format"] == {"type": "json_object"}
    assert client.captured_json["temperature"] == 0


def test_deepseek_extractor_falls_back_on_error() -> None:
    extractor = DeepSeekLeadExtractor(api_key="test-key", client=_ErrorClient())  # type: ignore[arg-type]

    info = extractor.extract("腾讯科技（深圳）有限公司 前端开发工程师", "招聘前端开发工程师")

    # Regex fallback should still extract something meaningful.
    assert info.company is not None
    assert "腾讯" in info.company


def test_deepseek_extractor_falls_back_on_empty_result() -> None:
    client = _FakeClient(_JsonResponse('{"company": null, "job_title": null}'))
    extractor = DeepSeekLeadExtractor(api_key="test-key", client=client)  # type: ignore[arg-type]

    info = extractor.extract("阿里云计算有限公司 招聘 Java 高级工程师", "阿里云计算有限公司")

    assert info.company is not None
    assert "阿里" in info.company
