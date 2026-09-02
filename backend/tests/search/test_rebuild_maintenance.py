import importlib
import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Blob, Candidate, Jd, JdRevision, ResumeDocument, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.search.contracts import CandidateFilters
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex


def maintenance():
    name = "kerui_recruit.search.rebuild_maintenance"
    assert importlib.util.find_spec(name) is not None, "safe maintenance rebuild entry point is missing"
    return importlib.import_module(name)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.sqlite3"
    engine = create_engine_for(path)
    migrate(engine)
    factory = sessionmaker(engine)
    with factory() as session, session.begin():
        blob = Blob(content_sha256="a" * 64, suffix=".pdf", size_bytes=1, storage_path="unused")
        candidate = Candidate(display_name="Projection Test")
        session.add(ResumeRevision(document=ResumeDocument(candidate=candidate), blob=blob,
            original_filename="unused.pdf", content_sha256="a" * 64, status="READY", is_current=True,
            parsed_data={"name": "Projection Test", "skills": ["Python"], "preferred_locations": ["广州"]}))
        job = Jd(title="Python engineer", company="Example", status="OPEN")
        session.add(JdRevision(jd=job, source_text="Python backend role", status="READY", is_current=True))
        session.add(Candidate(display_name="not eligible", status="ARCHIVED"))
    engine.dispose()
    old = tmp_path / "old-index"
    old.mkdir()
    (old / "legacy.marker").write_bytes(b"legacy unrebuildable but recoverable")
    return path, old


def test_dry_run_never_creates_or_changes_source_or_old_index(source, tmp_path):
    path, old = source
    before = path.read_bytes()
    result = maintenance().diagnose(path, old, embedding_model="local-hash-v1", dimension=64)
    assert result["mode"] == "dry-run"
    assert result["target_metadata"] == {"embedding_model": "local-hash-v1", "vector_dimension": 64,
                                         "schema_version": "2", "chunk_version": "2"}
    assert result["counts"] == {"candidate": 2, "jd": 1}
    assert result["candidate_index"]["compatibility"] == "missing-metadata-or-empty"
    assert path.read_bytes() == before
    assert sorted(p.name for p in old.iterdir()) == ["legacy.marker"]


@pytest.mark.asyncio
async def test_build_uses_snapshot_and_preserves_old_index(source, tmp_path):
    path, old = source
    before = path.read_bytes()
    output = tmp_path / "staged"
    result = await maintenance().build_offline(path, old, output, app_stopped=True)
    assert result["status"] == "READY_FOR_OFFLINE_SWITCH"
    assert result["validated"] == {"candidate_entities": 1, "candidate_chunks": 1, "jd_entities": 1, "jd_chunks": 1}
    rebuilt = LanceDBSearchIndex(output / "search", vector_dimension=64,
                                embedding_model="local-hash-v1", chunk_version="2")
    assert rebuilt.is_ready()
    assert len(rebuilt.filter_search(CandidateFilters(preferred_locations=("广州",)), 10)) == 1
    assert rebuilt.search_fts("Python", CandidateFilters(), 10)
    assert (output / "search" / "jobs" / "candidate-index-metadata.json").exists()
    assert json.loads((output / "manifest.json").read_text())["status"] == "READY_FOR_OFFLINE_SWITCH"
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM index_sync").fetchone() == (0,)
    assert (old / "legacy.marker").read_bytes() == b"legacy unrebuildable but recoverable"


@pytest.mark.asyncio
async def test_remote_build_uses_injected_provider_and_writes_remote_metadata(source, tmp_path):
    from kerui_recruit.providers.fakes import FakeEmbeddingProvider
    path, old = source
    output = tmp_path / "staged-remote"
    result = await maintenance().build_offline(path, old, output, app_stopped=True,
        embedding_provider=FakeEmbeddingProvider(dimension=1024),
        embedding_model="BAAI/bge-m3", dimension=1024)
    assert result["status"] == "READY_FOR_OFFLINE_SWITCH"
    assert result["validated"] == {"candidate_entities": 1, "candidate_chunks": 1,
                                   "jd_entities": 1, "jd_chunks": 1}
    rebuilt = LanceDBSearchIndex(output / "search", vector_dimension=1024,
                                 embedding_model="BAAI/bge-m3", chunk_version="2")
    assert rebuilt.is_ready()
    assert len(rebuilt.filter_search(CandidateFilters(preferred_locations=("广州",)), 10)) == 1
    metadata = json.loads((output / "search" / "candidate-index-metadata.json").read_text())
    assert metadata == {"schema_version": "2", "embedding_model": "BAAI/bge-m3",
                        "vector_dimension": 1024, "chunk_version": "2"}


@pytest.mark.asyncio
async def test_remote_build_requires_injected_provider(source, tmp_path):
    path, old = source
    with pytest.raises(ValueError, match="injected embedding provider"):
        await maintenance().build_offline(path, old, tmp_path / "remote-no-provider",
                                          app_stopped=True, embedding_model="BAAI/bge-m3", dimension=1024)


@pytest.mark.asyncio
async def test_failed_build_cannot_be_promoted(source, tmp_path):
    path, old = source
    class FailureEmbedding:
        async def embed_documents(self, texts):
            raise RuntimeError("controlled offline failure")
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="failed"):
        await maintenance().build_offline(path, old, output, app_stopped=True, embedding_provider=FailureEmbedding())
    assert json.loads((output / "manifest.json").read_text())["status"] == "FAILED"
    assert (old / "legacy.marker").exists()


@pytest.mark.asyncio
async def test_build_requires_shutdown_and_cannot_write_inside_old_index(source, tmp_path):
    path, old = source
    with pytest.raises(ValueError, match="stopped"):
        await maintenance().build_offline(path, old, tmp_path / "not-created", app_stopped=False)
    with pytest.raises(ValueError, match="overlap"):
        await maintenance().build_offline(path, old, old / "staging", app_stopped=True)
    assert not (tmp_path / "not-created").exists()


@pytest.mark.asyncio
async def test_source_write_during_build_invalidates_ready_manifest(source, tmp_path):
    from kerui_recruit.providers.local import LocalHashEmbeddingProvider
    path, old = source
    class ChangingSourceEmbedding(LocalHashEmbeddingProvider):
        async def embed_documents(self, texts):
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE candidate SET display_name='changed while rebuilding'")
            return await super().embed_documents(texts)
    output = tmp_path / "changed"
    with pytest.raises(RuntimeError, match="changed during build"):
        await maintenance().build_offline(path, old, output, app_stopped=True,
                                           embedding_provider=ChangingSourceEmbedding(dimension=64))
    assert json.loads((output / "manifest.json").read_text())["status"] == "FAILED"
    assert (old / "legacy.marker").exists()


def test_cli_diagnosis_supports_remote_and_execution_requires_credentials(source, tmp_path, capsys, monkeypatch):
    path, old = source
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    command = ["--database", str(path), "--index-root", str(old), "--model", "BAAI/bge-m3", "--dimension", "1024"]
    assert maintenance().main(command) == 0
    diagnostic = json.loads(capsys.readouterr().out)
    assert diagnostic["mode"] == "dry-run" and diagnostic["execution_supported"] is True
    output = tmp_path / "remote-not-created"
    assert maintenance().main(command + ["--execute", "--app-stopped", "--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"
    assert not output.exists()


@pytest.mark.asyncio
async def test_rebuild_refuses_to_migrate_source_schema(source, tmp_path):
    path, old = source
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE schema_version SET version=6")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="separate migration"):
        await maintenance().build_offline(path, old, tmp_path / "old-schema", app_stopped=True)
    assert path.read_bytes() == before
    assert not (tmp_path / "old-schema").exists()
