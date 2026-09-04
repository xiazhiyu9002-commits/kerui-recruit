"""方向回填正式 CLI。

用法示例：
    python -m kerui_recruit.direction.backfill_cli --data-root <path> preflight
    python -m kerui_recruit.direction.backfill_cli --data-root <path> dry-run
    python -m kerui_recruit.direction.backfill_cli --data-root <path> rules-only
    python -m kerui_recruit.direction.backfill_cli --data-root <path> full
    python -m kerui_recruit.direction.backfill_cli --data-root <path> resume
    python -m kerui_recruit.direction.backfill_cli --data-root <path> status
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.backfill import (
    LOCK_FILENAME,
    STATE_FILENAME,
    DirectionBackfillService,
)
from kerui_recruit.direction.classifier import DirectionClassifier
from kerui_recruit.providers.factory import build_providers
from kerui_recruit.sidecar import RuntimeArgs, build_settings


def _build_service(data_root: Path, *, concurrency: int, max_retries: int,
                   entity_types: tuple[str, ...]) -> tuple[DirectionBackfillService, object]:
    args = RuntimeArgs(host="127.0.0.1", port=43127, token="0" * 64, data_root=data_root)
    settings = build_settings(args)
    providers = build_providers(settings)
    classifier = DirectionClassifier(providers.direction_llm)
    engine = create_engine_for(data_root / "db" / "recruit.sqlite3")
    factory = sessionmaker(engine, expire_on_commit=False)
    service = DirectionBackfillService(
        factory, classifier, concurrency=concurrency, max_retries=max_retries,
        state_dir=data_root / "config",
    )
    return service, providers


def _print_stats(stats) -> None:
    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))


async def _run(command: str, data_root: Path, *, concurrency: int, max_retries: int,
               entity_types: tuple[str, ...], batch_size: int, max_items: int | None) -> int:
    service, providers = _build_service(
        data_root, concurrency=concurrency, max_retries=max_retries, entity_types=entity_types)
    try:
        if command == "preflight":
            print(json.dumps(service.preflight(), ensure_ascii=False, indent=2))
            return 0
        if command == "status":
            state_path = data_root / "config" / STATE_FILENAME
            lock_path = data_root / "config" / LOCK_FILENAME
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
            lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else None
            print(json.dumps({"state": state, "lock": lock}, ensure_ascii=False, indent=2))
            return 0
        mode = {"dry-run": "dry-run", "rules-only": "rules-only", "full": "full", "resume": "resume"}[command]
        stats = await service.run(entity_types=entity_types, mode=mode,
                                  batch_size=batch_size, max_items=max_items)
        _print_stats(stats)
        for warning in DirectionBackfillService.distribution_warnings(stats):
            print(f"WARNING: {warning}")
        return 0
    finally:
        if providers.http_client is not None:
            await providers.http_client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kerui_recruit.direction.backfill_cli")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--entity-type", action="append", choices=["resume_revision", "jd_revision"],
                        default=None)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("command", choices=["preflight", "dry-run", "rules-only", "full", "resume", "status"])
    options = parser.parse_args(argv)

    entity_types = tuple(options.entity_type) if options.entity_type else ("resume_revision", "jd_revision")
    return asyncio.run(_run(
        options.command, options.data_root, concurrency=options.concurrency,
        max_retries=options.max_retries, entity_types=entity_types,
        batch_size=options.batch_size, max_items=options.max_items,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
