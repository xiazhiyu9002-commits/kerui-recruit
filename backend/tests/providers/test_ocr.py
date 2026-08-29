from __future__ import annotations

import base64
import json

import httpx
import pymupdf
import pytest

from kerui_recruit.providers.ocr import OpenAICompatibleOCRProvider, rasterize_pdf


def _blank_pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "scanned resume")
    payload = document.tobytes()
    document.close()
    return payload


def test_rasterize_pdf_returns_one_png_per_page() -> None:
    images = rasterize_pdf(_blank_pdf_bytes())
    assert len(images) == 1
    assert images[0].startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_extract_posts_vision_request_and_returns_text() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "张三 本科 6年"}}]},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://test"
    )
    provider = OpenAICompatibleOCRProvider(
        api_key="test-key",
        client=client,
        base_url="https://test",
        model="vision-model",
    )

    result = await provider.extract(_blank_pdf_bytes(), "resume.pdf")

    assert result == "张三 本科 6年"
    assert captured["body"]["model"] == "vision-model"
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["type"] == "text"
    image_url = content[1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(image_url.split(",", 1)[1])
    assert decoded.startswith(b"\x89PNG")
