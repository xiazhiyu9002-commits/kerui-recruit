from __future__ import annotations

from dataclasses import dataclass


@dataclass(eq=False)
class ProviderError(RuntimeError):
    code: str
    retryable: bool
    user_message: str
    request_id: str | None = None

    def __str__(self) -> str:
        suffix = f" ({self.request_id})" if self.request_id else ""
        return f"{self.code}: {self.user_message}{suffix}"


_STATUS_ERRORS: dict[int, tuple[str, bool, str]] = {
    400: ("E_API_FORMAT", False, "请求格式不正确"),
    401: ("E_API_AUTH", False, "API 密钥无效或无权限"),
    402: ("E_API_BALANCE", False, "API 账户余额不足"),
    422: ("E_API_PARAMETERS", False, "API 请求参数不正确"),
    429: ("E_API_RATE_LIMIT", True, "API 调用频率达到上限"),
    500: ("E_API_UPSTREAM", True, "API 服务暂时异常"),
    503: ("E_API_BUSY", True, "API 服务繁忙"),
}


def map_http_error(status: int, *, request_id: str | None = None) -> ProviderError:
    code, retryable, message = _STATUS_ERRORS.get(
        status,
        ("E_API_HTTP", status >= 500, f"API 返回 HTTP {status}"),
    )
    return ProviderError(
        code=code,
        retryable=retryable,
        user_message=message,
        request_id=request_id,
    )
