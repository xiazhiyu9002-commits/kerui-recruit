from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import uvicorn

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


def main(arguments: Sequence[str] | None = None) -> None:
    options = parse_runtime_args(arguments)
    settings = Settings(data_root=options.data_root, session_token=options.token)
    uvicorn.run(
        create_runtime_app(settings),
        host=options.host,
        port=options.port,
        access_log=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
