import asyncio
import time
from dataclasses import replace

import pytest

from kerui_recruit.providers.fakes import FakeRerankerProvider
from kerui_recruit.search.contracts import CandidateFilters, SearchChunk
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex
from kerui_recruit.search.observer import InMemorySearchObserver
from kerui_recruit.search.service import HybridSearchService


def chunk(cid, number=0, content="Python", **kwargs):
    return SearchChunk(f"{cid}-{number}", cid, f"r-{cid}", content, (1., 0.), 5,
                       "MASTER", "上海", "AVAILABLE", **kwargs)


class Embedding:
    async def embed_query(self, text):
        return [1., 0.]


class SlowEmbedding:
    async def embed_query(self, text):
        await asyncio.sleep(5)


def service(index, timeout=2, embedding=None):
    return HybridSearchService(index=index, embedding_provider=embedding or Embedding(),
                               reranker_provider=FakeRerankerProvider(), search_timeout=timeout)


def test_complete_evidence_reads_more_than_default_ten_rows(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a", i, "Java" if i == 25 else "Python") for i in range(26)])
    assert len(index.get_candidate_chunk_contents(["a"])["a"]) == 26


@pytest.mark.asyncio
async def test_chunk_heavy_candidate_does_not_consume_candidate_limit(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a", i) for i in range(420)] + [chunk("b")])
    page = await service(index).search("", CandidateFilters(), limit=2)
    assert {hit.candidate_id for hit in page.items} == {"a", "b"}
    assert {row["candidate_id"] for row in index.search_vector((1., 0.), CandidateFilters(), 2)} == {"a", "b"}


@pytest.mark.asyncio
async def test_observer_none_matches_results_and_injected_observer_collects_phases(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a", 0, "Java 后端"), chunk("b", 0, "Python 算法")])
    svc = service(index)
    baseline = await svc.search("Java", CandidateFilters(), limit=5)
    observer = InMemorySearchObserver()
    observed = await svc.search("Java", CandidateFilters(), limit=5, observer=observer)
    # observer=None 与注入 observer 的结果完全一致。
    assert [h.candidate_id for h in baseline.items] == [h.candidate_id for h in observed.items]
    # 注入 observer 后才采集阶段耗时，且覆盖正式代码路径的单调时钟分段。
    assert observer.events > 0
    assert {"fts", "embedding", "vector", "fusion", "rerank", "direction_boost"} <= set(observer.phases)


def test_all_preferred_locations_are_searchable_without_matching_current_city(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    assert "preferred_locations" in SearchChunk.__dataclass_fields__
    index.upsert([chunk("a", preferred_locations=("深圳", "广州")),
                  chunk("b", preferred_locations=("北京",))])
    hits = index.filter_search(CandidateFilters(preferred_locations=("广州",)), 10)
    assert [hit.candidate_id for hit in hits] == ["a"]


@pytest.mark.asyncio
async def test_missing_complete_evidence_fails_closed(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    index.get_candidate_chunk_contents = lambda ids: {}
    page = await service(index).search("", CandidateFilters(exclude_skills=("Java",)), limit=2)
    assert page.items == ()
    assert "EXCLUSION_UNVERIFIED" in page.degraded_reasons
    assert page.empty_reason == "service_error"


@pytest.mark.asyncio
async def test_evidence_read_obeys_same_deadline(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    def slow_evidence(ids):
        time.sleep(.35)
        return {"a": ["Python"]}
    index.get_candidate_chunk_contents = slow_evidence
    started = time.monotonic()
    page = await service(index, .06).search("", CandidateFilters(exclude_skills=("Java",)), limit=2)
    assert time.monotonic() - started < .22
    assert page.items == ()
    assert "EXCLUSION_UNVERIFIED" in page.degraded_reasons


@pytest.mark.asyncio
async def test_slow_fts_gets_no_extra_budget_after_embedding_timeout(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    original = index.search_fts
    def slow_fts(*args):
        time.sleep(.35)
        return original(*args)
    index.search_fts = slow_fts
    started = time.monotonic()
    page = await service(index, .06, SlowEmbedding()).search("Python", CandidateFilters(), limit=2)
    assert time.monotonic() - started < .22
    assert page.items == ()


def test_model_metadata_blocks_mixing_and_preserves_existing_rows(tmp_path):
    import inspect
    assert "embedding_model" in inspect.signature(LanceDBSearchIndex).parameters
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2, embedding_model="model-a")
    index.upsert([chunk("a")])
    incompatible = LanceDBSearchIndex(tmp_path, vector_dimension=2, embedding_model="model-b")
    assert not incompatible.is_ready()
    with pytest.raises(ValueError, match="incompatible"):
        incompatible.upsert([chunk("b")])
    assert index.warmup() == 1


def test_replace_candidate_removes_old_revision_and_projection_updates_preserve_vector(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a"), chunk("b")])
    assert hasattr(index, "replace_candidate")
    index.replace_candidate([replace(chunk("a", 1), revision_id="new")])
    assert index.get_revision_chunks("r-a") == []
    index.update_candidate_filters("a", candidate_status="ON_HOLD")
    assert [h.candidate_id for h in index.filter_search(CandidateFilters(), 10)] == ["b"]
    assert list(index.get_revision_chunks("new")[0]["vector"]) == [1., 0.]
    index.delete_candidate("a")
    assert index.get_revision_chunks("new") == []


@pytest.mark.asyncio
async def test_verified_fts_exclusions_survive_embedding_timeout(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a"), chunk("b", content="Java Python")])
    page = await service(index, .15, SlowEmbedding()).search("Python", CandidateFilters(exclude_skills=("Java",)), limit=2)
    assert [hit.candidate_id for hit in page.items] == ["a"]
    assert "EMBEDDING_UNAVAILABLE" in page.degraded_reasons


@pytest.mark.asyncio
async def test_cancelled_outer_search_cancels_provider_child(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    finished = asyncio.Event()
    class EmbeddingChild:
        async def embed_query(self, text):
            try:
                await asyncio.sleep(5)
            finally:
                finished.set()
    await service(index, .08, EmbeddingChild()).search("Python", CandidateFilters(), limit=2)
    await asyncio.sleep(.02)
    assert finished.is_set()


def test_old_metadata_missing_index_is_not_migrated_or_deleted(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    (tmp_path / "candidate-index-metadata.json").unlink()
    assert not index.is_ready()
    with pytest.raises(ValueError, match="incompatible"):
        index.upsert([chunk("b")])
    assert index.database.open_table(index.table_name).count_rows() == 1


@pytest.mark.parametrize("changed", [{"vector_dimension": 3}, {"schema_version": "9"}, {"chunk_version": "2"}])
def test_all_index_contract_changes_require_explicit_rebuild(tmp_path, changed):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    settings = {"vector_dimension": 2, **changed}
    assert not LanceDBSearchIndex(tmp_path, **settings).is_ready()


@pytest.mark.asyncio
async def test_provider_ignoring_cancellation_cannot_accumulate_without_bound(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a")])
    release = asyncio.Event()
    active = 0
    peak = 0
    class StubbornEmbedding:
        async def embed_query(self, text):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            try:
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            finally:
                active -= 1
            return [1., 0.]
    search = service(index, .06, StubbornEmbedding())
    try:
        for _ in range(12):
            await search.search("Python", CandidateFilters(), limit=2)
        assert peak <= 8
    finally:
        release.set()
        await asyncio.sleep(.02)


def test_preferred_location_projection_update_replaces_old_choices(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a", preferred_location="北京", preferred_locations=("北京", "上海"))])
    index.update_candidate_filters("a", preferred_location="广州")
    assert [hit.candidate_id for hit in index.filter_search(CandidateFilters(preferred_locations=("广州",)), 10)] == ["a"]
    assert index.filter_search(CandidateFilters(preferred_locations=("北京", "上海")), 10) == []


@pytest.mark.asyncio
async def test_timed_out_candidate_scan_does_not_start_more_native_queries(tmp_path):
    index = LanceDBSearchIndex(tmp_path, vector_dimension=2)
    index.upsert([chunk("a", i) for i in range(420)] + [chunk("b")])
    original = index._candidate_rows
    calls = 0
    class SlowBuilder:
        def __init__(self, builder):
            self.builder = builder
        def limit(self, limit):
            self.builder = self.builder.limit(limit)
            return self
        def to_list(self):
            nonlocal calls
            calls += 1
            time.sleep(.07)
            return self.builder.to_list()
    index._candidate_rows = lambda builder, count, limit, filters: original(SlowBuilder(builder), count, limit, filters)
    page = await service(index, .04).search("", CandidateFilters(), limit=2)
    assert not page.items
    await asyncio.sleep(.45)
    assert calls == 1  # Existing native call can finish, but later scan pages must not start.
