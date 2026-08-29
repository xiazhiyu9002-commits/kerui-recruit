from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import uvicorn
from pydantic import SecretStr

from kerui_recruit.core.settings import Settings
from kerui_recruit.runtime import create_runtime_app


@dataclass(frozen=True, slots=True)
class RuntimeArgs:
    host: str
    port: int
    token: str
    data_root: Path


def parse_runtime_args(arguments: Sequence[str] | None = None) -> RuntimeArgs:
    parser = argparse.ArgumentParser(prog="kerui-recruit-sidecar")
    parser.add_argument("--port", required=True, type=int, choices=range(1024, 65536))
    parser.add_argument("--token", required=True)
    parser.add_argument("--data-root", required=True, type=Path)
    parsed = parser.parse_args(arguments)
    if len(parsed.token) < 64:
        parser.error("--token must contain at least 256 bits encoded as hexadecimal")
    return RuntimeArgs(
        host="127.0.0.1",
        port=parsed.port,
        token=parsed.token,
        data_root=parsed.data_root.expanduser().resolve(strict=False),
    )


def _secret(name: str) -> SecretStr | None:
    value = os.environ.get(name)
    return SecretStr(value) if value else None


def build_settings(options: RuntimeArgs) -> Settings:
    return Settings(
        data_root=options.data_root,
        session_token=options.token,
        deepseek_api_key=_secret("DEEPSEEK_API_KEY"),
        deepseek_base_url=os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ),
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        siliconflow_api_key=_secret("SILICONFLOW_API_KEY"),
        siliconflow_base_url=os.environ.get(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        ),
        siliconflow_embedding_model=os.environ.get(
            "SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-m3"
        ),
        siliconflow_reranker_model=os.environ.get(
            "SILICONFLOW_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
        ),
    )


def main(arguments: Sequence[str] | None = None) -> None:
    options = parse_runtime_args(arguments)
    settings = build_settings(options)
    uvicorn.run(
        create_runtime_app(settings),
        host=options.host,
        port=options.port,
        access_log=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
