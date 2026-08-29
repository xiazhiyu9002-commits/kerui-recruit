from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from kerui_recruit.providers.errors import ProviderError, map_http_error


ResultModel = TypeVar("ResultModel", bound=BaseModel)


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        response_model: type[ResultModel],
    ) -> ResultModel:
        try:
            response = await self.http_client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        except httpx.RequestError as error:
            raise ProviderError(
                code="E_API_NETWORK",
                retryable=True,
                user_message="无法连接 API 服务",
            ) from error
        request_id = response.headers.get("x-request-id")
        if response.status_code >= 400:
            raise map_http_error(response.status_code, request_id=request_id)
        try:
            payload: dict[str, Any] = response.json()
            content = payload["choices"][0]["message"]["content"]
            return response_model.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
            raise ProviderError(
                code="E_API_SCHEMA",
                retryable=True,
                user_message="API 返回内容不符合结构要求",
                request_id=request_id,
            ) from error
