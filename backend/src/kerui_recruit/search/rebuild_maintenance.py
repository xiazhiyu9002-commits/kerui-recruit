"""Offline, staged index rebuilding. The active database/index are never written.

Run with ``python -m kerui_recruit.search.rebuild_maintenance --help``.
Default operation is a read-only diagnosis; no provider is instantiated.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from kerui_recruit.core.settings_store import SettingsStore
from kerui_recruit.db.migrate import SCHEMA_VERSION
from kerui_recruit.db.models import Candidate, IndexSyncRecord, Jd
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.encryption.service import EncryptionService
from kerui_recruit.match.jd_index import JdSearchIndex
from kerui_recruit.providers.local import LocalHashEmbeddingProvider
from kerui_recruit.providers.siliconflow import SiliconFlowEmbeddingProvider
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.sync import IndexSyncService, enqueue_sync


def _readonly(database: Path) -> sqlite3.Connection:
    path = database.expanduser().resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _metadata(model: str, dimension: int) -> dict:
    if dimension < 1:
        raise ValueError("dimension must be positive")
    return {"schema_version": "2", "embedding_model": model,
            "vector_dimension": dimension, "chunk_version": "2"}


def _execution_supported(model: str, dimension: int) -> bool:
    if model == "local-hash-v1":
        return dimension == 64
    return dimension == SiliconFlowEmbeddingProvider.dimension


def _siliconflow_api_key(database: Path) -> str | None:
    """Resolve the SiliconFlow API key from the environment or stored settings.

    Stored keys live in ``<data-root>/config/settings.json`` and are encrypted
    with the AES key in ``<data-root>/config/encryption.key``. Never log either.
    """
    env_key = os.environ.get("SILICONFLOW_API_KEY")
    if env_key:
        return env_key
    config_dir = database.parent.parent / "config"
    data = SettingsStore(config_dir / "settings.json").load()
    value = data.get("siliconflow_api_key") if data else None
    if not value:
        return None
    key_path = config_dir / "encryption.key"
    if not key_path.is_file():
        return None
    try:
        return EncryptionService(key_path=str(key_path)).decrypt(value)
    except Exception:
        return None


def _build_embedding_provider(model: str, dimension: int, database: Path):
    """Return ``(provider, http_client)`` for the requested embedding model.

    The local provider owns no network client. The remote provider shares an
    ``httpx.AsyncClient`` that the caller must close after the build finishes.
    """
    if model == "local-hash-v1":
        if dimension != 64:
            raise ValueError("local-hash-v1 requires vector dimension 64")
        return LocalHashEmbeddingProvider(dimension=dimension), None
    if dimension != SiliconFlowEmbeddingProvider.dimension:
        raise ValueError(
            f"Remote embedding dimension must be {SiliconFlowEmbeddingProvider.dimension}, got {dimension}"
        )
    api_key = _siliconflow_api_key(database)
    if not api_key:
        raise ValueError(
            "SiliconFlow API key is required for remote index rebuild; "
            "set SILICONFLOW_API_KEY or configure it in the application settings"
        )
    client = httpx.AsyncClient()
    provider = SiliconFlowEmbeddingProvider(
        api_key=api_key,
        client=client,
        base_url=os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        model=model,
    )
    return provider, client


def _inspect_metadata(root: Path, expected: dict) -> dict:
    # Do not instantiate LanceDBSearchIndex here: its constructor creates paths.
    path = root / "candidate-index-metadata.json"
    if not path.is_file():
        return {"metadata": None, "compatibility": "missing-metadata-or-empty"}
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"metadata": None, "compatibility": "invalid-metadata"}
    return {"metadata": actual, "compatibility": (
        "metadata-matches-physical-schema-not-checked" if actual == expected else "rebuild-required")}


def diagnose(database: Path, index_root: Path, *, embedding_model: str, dimension: int) -> dict:
    expected = _metadata(embedding_model, dimension)
    with closing(_readonly(database)) as source:
        version = source.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        counts = {table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("candidate", "jd")}
    return {"mode": "dry-run", "database_schema_version": version,
            "database_schema_supported": version == SCHEMA_VERSION,
            "counts": counts, "target_metadata": expected,
            "candidate_index": _inspect_metadata(index_root, expected),
            "jd_index": _inspect_metadata(index_root / "jobs", expected),
            "execution_supported": _execution_supported(embedding_model, dimension),
            "warning": "Metadata comparison only; active index was not opened or modified. "
                       "Execution supports local-hash-v1/64 and SiliconFlow-served remote embeddings; "
                       "a remote rebuild reads the SiliconFlow API key from the environment or stored settings."}


def _manifest(output: Path, data: dict) -> None:
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output / "manifest.json")


def _projected_ids(index: LanceDBSearchIndex) -> set[str]:
    if not index.warmup():
        return set()
    table = index.database.open_table(index.table_name)
    return {row["candidate_id"] for row in
            table.search(None).select(["candidate_id"]).limit(None).to_list()}


async def build_offline(database: Path, index_root: Path, output: Path, *,
                        app_stopped: bool, embedding_provider=None,
                        embedding_model: str = "local-hash-v1", dimension: int = 64) -> dict:
    """Build a separate projection; never promote or migrate source.

    ``embedding_provider`` is dependency injection for verification. When it is
    omitted the local provider is used; a remote model must be supplied with its
    own provider (and HTTP client) by the caller, matching ``embedding_model``
    and ``dimension``.
    """
    if not app_stopped:
        raise ValueError("Application must be stopped through build and manual switch")
    if embedding_provider is None and embedding_model != "local-hash-v1":
        raise ValueError("A remote embedding model requires an injected embedding provider")
    database = database.expanduser().resolve(strict=True)
    index_root, output = index_root.resolve(), output.resolve()
    if (output == index_root or output.is_relative_to(index_root) or
            index_root.is_relative_to(output) or database.is_relative_to(output)):
        raise ValueError("Output must not overlap the active database or index paths")
    if output.exists():
        raise ValueError("Output already exists; select a new staging directory")
    diagnostic = diagnose(database, index_root, embedding_model=embedding_model, dimension=dimension)
    if not diagnostic["database_schema_supported"]:
        raise ValueError("Source SQLite schema requires the application's separate migration workflow")
    output.mkdir(parents=True, exist_ok=False)
    state = {"status": "BUILDING", "source_database": str(database), "active_index": str(index_root),
             "started_at": datetime.now(timezone.utc).isoformat(),
             "metadata": diagnostic["target_metadata"], "automatic_switch": False}
    _manifest(output, state)
    engine = None
    try:
        with closing(_readonly(database)) as source:
            version_before = source.execute("PRAGMA data_version").fetchone()[0]
            snapshot_path = output / "source-snapshot.sqlite3"
            with closing(sqlite3.connect(snapshot_path)) as snapshot:
                source.backup(snapshot)
            engine = create_engine_for(snapshot_path)
            factory = sessionmaker(engine, expire_on_commit=False)
            index = LanceDBSearchIndex(output / "search", vector_dimension=dimension,
                                       embedding_model=embedding_model, chunk_version="2")
            jobs = JdSearchIndex(output / "search" / "jobs", vector_dimension=dimension,
                                 embedding_model=embedding_model, chunk_version="2")
            sync = IndexSyncService(session_factory=factory, index=index, jd_index=jobs,
                                    embedding_provider=embedding_provider or LocalHashEmbeddingProvider(dimension=dimension))
            with factory() as session, session.begin():
                entities = [("candidate", value) for value in session.scalars(select(Candidate.id))]
                entities.extend(("jd", value) for value in session.scalars(select(Jd.id)))
                # Only the isolated snapshot's queue is rewritten. Source tasks
                # and outbox acknowledgements must never be copied back.
                session.execute(delete(IndexSyncRecord))
                for kind, entity_id in entities:
                    enqueue_sync(session, kind, entity_id)
            expected_ids = {"candidate": set(), "jd": set()}
            expected_chunks = {"candidate": 0, "jd": 0}
            for kind, entity_id in entities:
                snapshot = sync._snapshot(kind, entity_id)
                if snapshot is not None:
                    expected_ids[kind].add(entity_id)
                    expected_chunks[kind] += len(snapshot["contents"])
            stalled_cycles = 0
            while sync.status()["pending"]:
                completed = await sync.run_once(batch_size=25, force=True)
                status = sync.status()
                # Remote providers can fail transiently (429/timeout). With
                # force=True those entities are retried immediately; only abort
                # after consecutive no-progress cycles so a single blip does not
                # discard the whole staged build.
                if status["pending"] and not completed:
                    stalled_cycles += 1
                    if stalled_cycles >= 5:
                        raise RuntimeError("Staged index build failed; source and old index were not replaced")
                else:
                    stalled_cycles = 0
            validated = {}
            for kind, target in (("candidate", index), ("jd", jobs.index)):
                target.optimize_pending()
                if not target.is_compatible():
                    raise RuntimeError("Staged index metadata validation failed")
                if target.warmup() != expected_chunks[kind] or _projected_ids(target) != expected_ids[kind]:
                    raise RuntimeError("Staged index entity/chunk validation failed")
                validated[f"{kind}_entities"] = len(expected_ids[kind])
                validated[f"{kind}_chunks"] = expected_chunks[kind]
            if source.execute("PRAGMA data_version").fetchone()[0] != version_before:
                raise RuntimeError("Source database changed during build; staged index must not be switched")
        state.update(status="READY_FOR_OFFLINE_SWITCH", validated=validated,
                     completed_at=datetime.now(timezone.utc).isoformat(),
                     instruction="Keep application stopped. Preserve the complete old search directory; "
                                 "move staged search (including jobs) into its place, then restart with the "
                                 "matching embedding model configured. Never restore the snapshot over the live database.")
        _manifest(output, state)
        return state
    except BaseException as error:
        # Only internal maintenance errors reach this point; provider payloads
        # and resume bodies are already suppressed by the sync layer.
        state.update(status="FAILED", error_type=type(error).__name__, error_message=str(error))
        _manifest(output, state)
        raise
    finally:
        if engine is not None:
            engine.dispose()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--index-root", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dimension", required=True, type=int)
    parser.add_argument("--execute", action="store_true", help="Build separate staging output (default: diagnosis only)")
    parser.add_argument("--app-stopped", action="store_true", help="Confirm application remains closed until manual switch")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.execute:
            if args.output is None:
                raise ValueError("--output is required for execution")
            provider, http_client = _build_embedding_provider(args.model, args.dimension, args.database)

            async def _run() -> dict:
                # Close the shared client in the same event loop that ran the
                # build; closing it from a fresh loop raises and would wrongly
                # mask a successful build as a failure.
                try:
                    return await build_offline(
                        args.database, args.index_root, args.output, app_stopped=args.app_stopped,
                        embedding_provider=provider, embedding_model=args.model, dimension=args.dimension)
                finally:
                    if http_client is not None:
                        await http_client.aclose()

            result = asyncio.run(_run())
        else:
            result = diagnose(args.database, args.index_root, embedding_model=args.model, dimension=args.dimension)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        # Do not print provider payloads, SQL parameters, resume bodies or secrets.
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__,
                          "instruction": "No index was switched. Check inputs, shutdown status and staging manifest."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
