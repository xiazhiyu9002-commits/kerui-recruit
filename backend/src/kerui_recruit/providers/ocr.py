from __future__ import annotations

import base64
import io

import httpx
import pymupdf

from kerui_recruit.providers.errors import ProviderError, map_http_error

_OCR_PROMPT = "请完整提取图片中的文字，保留原始排版与换行，不要总结、翻译或补充内容。"

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}


def rasterize_pdf(content: bytes) -> list[bytes]:
    """Render each PDF page to a PNG image for vision-based OCR."""
    images: list[bytes] = []
    with pymupdf.open(stream=io.BytesIO(content), filetype="pdf") as document:
        for page in document:
            images.append(page.get_pixmap(dpi=150).tobytes("png"))
    return images


class OpenAICompatibleOCRProvider:
    """Vision-model OCR for scanned resumes via an OpenAI-compatible API."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def extract(self, content: bytes, filename: str) -> str:
        if _mime_for(filename) == "application/pdf":
            images = rasterize_pdf(content)
        else:
            images = [content]
        texts = [await self._extract_image(image, filename) for image in images]
        return "\n".join(text.strip() for text in texts if text.strip())

    async def _extract_image(self, image: bytes, filename: str) -> str:
        mime = _mime_for(filename)
        if mime == "application/pdf":
            mime = "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": _OCR_PROMPT},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                    "temperature": 0,
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        except httpx.RequestError as error:
            raise ProviderError(
                code="E_API_NETWORK",
                retryable=True,
                user_message="无法连接 OCR 服务",
            ) from error
        if response.status_code >= 400:
            raise map_http_error(response.status_code)
        try:
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(
                code="E_API_SCHEMA",
                retryable=True,
                user_message="OCR 服务返回内容不符合结构要求",
            ) from error


def _mime_for(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "pdf":
        return "application/pdf"
    return _IMAGE_MIME.get(f".{suffix}", "application/octet-stream")
