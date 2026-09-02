from __future__ import annotations

import asyncio
import time

from kerui_recruit.providers.contracts import EmbeddingProvider, RerankerProvider
from kerui_recruit.search.contracts import (
    CandidateFilters,
    SearchPage,
    SearchRequest,
)
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex, SEARCH_DEADLINE
from kerui_recruit.search.query import has_skill


# Threads cannot be forcibly stopped by cancelling an asyncio waiter. Keep a
# shared, bounded pool and retain each permit until the actual native call ends.
from concurrent.futures import ThreadPoolExecutor
import threading

_SEARCH_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="kerui-search")
_SEARCH_SLOTS = threading.BoundedSemaphore(8)


async def _until(task, deadline):
    if task.done():
        return task.result()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        task.cancel()
        raise TimeoutError()
    try:
        done, _ = await asyncio.wait({task}, timeout=remaining)
    except asyncio.CancelledError:
        task.cancel()
        raise
    if task in done:
        return task.result()
    task.cancel()
    raise TimeoutError()


async def _blocking(function, *args, deadline):
    while not _SEARCH_SLOTS.acquire(blocking=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        await asyncio.sleep(min(.005, remaining))
    if time.monotonic() >= deadline:
        _SEARCH_SLOTS.release()
        raise TimeoutError()
    try:
        def invoke():
            token = SEARCH_DEADLINE.set(deadline)
            try:
                return function(*args)
            finally:
                SEARCH_DEADLINE.reset(token)
        future = _SEARCH_POOL.submit(invoke)
    except BaseException:
        _SEARCH_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _SEARCH_SLOTS.release())
    return await _until(asyncio.wrap_future(future), deadline)


class HybridSearchService:
    """One deadline covers readiness, retrieval, full evidence and reranking."""

    def __init__(self, *, index: LanceDBSearchIndex,
                 embedding_provider: EmbeddingProvider, reranker_provider: RerankerProvider,
                 search_timeout: float = 4.5) -> None:
        self.index = index
        self.embedding_provider = embedding_provider
        self.reranker_provider = reranker_provider
        self.search_timeout = search_timeout
        self._provider_tasks: set[asyncio.Task] = set()

    async def _provider(self, function, *args, deadline):
        if len(self._provider_tasks) >= 8 or time.monotonic() >= deadline:
            raise TimeoutError("Provider concurrency budget exhausted")
        task = asyncio.create_task(function(*args))
        self._provider_tasks.add(task)
        def completed(done):
            self._provider_tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Retrieve errors even when a timed-out caller has left.
        task.add_done_callback(completed)
        return await _until(task, deadline)

    def warmup(self) -> int:
        return self.index.warmup()

    def optimize_pending(self) -> bool:
        return self.index.optimize_pending()

    def is_ready(self) -> bool:
        return self.index.is_ready()

    async def search(self, query: str, filters: CandidateFilters, *, limit: int,
                     deadline: float | None = None) -> SearchPage:
        budget = min(deadline, time.monotonic() + self.search_timeout) if deadline is not None else time.monotonic() + self.search_timeout
        degraded: list[str] = []
        try:
            ready = await _blocking(self.index.is_ready, deadline=budget)
        except TimeoutError:
            return SearchPage(items=(), empty_reason="service_error", degraded_reasons=("TIMEOUT",))
        except Exception:
            return SearchPage(items=(), empty_reason="service_error", degraded_reasons=("SEARCH_UNAVAILABLE",))
        if not ready:
            return SearchPage(items=(), empty_reason="index_not_ready")

        if not query.strip():
            try:
                hits = await _blocking(self.index.filter_search, filters, limit, deadline=budget)
            except Exception as exc:
                reason = "EXCLUSION_UNVERIFIED" if filters.exclude_skills else "SEARCH_UNAVAILABLE"
                return SearchPage(items=(), empty_reason="service_error", degraded_reasons=(reason,))
        elif hasattr(self.index, "search_fts") and hasattr(self.index, "fuse"):
            hits = await self._parallel_retrieve(query, filters, limit, budget, degraded)
        else:
            hits = await self._legacy_retrieve(query, filters, limit, budget, degraded)

        hits = await self._apply_exclusion(hits, filters.exclude_skills, budget, degraded)
        if not hits:
            return SearchPage(items=(), degraded_reasons=tuple(dict.fromkeys(degraded)),
                              empty_reason="service_error" if degraded else "no_match")
        if query.strip():
            if time.monotonic() < budget:
                try:
                    contents = [hit.content for hit in hits[:100]]
                    if hasattr(self.reranker_provider, "rerank_scored"):
                        scored = await self._provider(self.reranker_provider.rerank_scored, query, contents, deadline=budget)
                        hits = _apply_rerank_scored(hits, scored)
                    else:
                        order = await self._provider(self.reranker_provider.rerank, query, contents, deadline=budget)
                        hits = _apply_rerank_order(hits, order)
                except Exception:
                    degraded.append("RERANKER_UNAVAILABLE")
            else:
                degraded.append("TIMEOUT")
        return SearchPage(items=tuple(hits[:limit]), degraded_reasons=tuple(dict.fromkeys(degraded)))

    async def _parallel_retrieve(self, query, filters, limit, budget, degraded):
        fts = asyncio.create_task(_blocking(self.index.search_fts, query, filters, max(limit, 100), deadline=budget))

        async def semantic():
            try:
                vector = await self._provider(self.embedding_provider.embed_query, query, deadline=budget)
            except Exception:
                degraded.append("EMBEDDING_UNAVAILABLE")
                return []
            try:
                return await _blocking(self.index.search_vector, tuple(vector), filters, max(limit, 100), deadline=budget)
            except Exception:
                degraded.append("VECTOR_UNAVAILABLE")
                return []

        vector_task = asyncio.create_task(semantic())
        try:
            done, pending = await asyncio.wait({fts, vector_task}, timeout=max(0., budget - time.monotonic()))
            # Inspect completed work only. A slow channel receives no grace period.
            rows = []
            for task, reason in ((fts, "FTS_UNAVAILABLE"), (vector_task, "EMBEDDING_UNAVAILABLE")):
                if task.done() and not task.cancelled():
                    try:
                        rows.append(task.result())
                    except Exception:
                        degraded.append(reason)
                        rows.append([])
                else:
                    task.cancel()
                    degraded.append(reason)
                    rows.append([])
            return self.index.fuse(rows[0], rows[1], max(limit, 100))
        finally:
            for task in (fts, vector_task):
                if not task.done():
                    task.cancel()

    async def _legacy_retrieve(self, query, filters, limit, budget, degraded):
        vector = ()
        try:
            vector = tuple(await self._provider(self.embedding_provider.embed_query, query, deadline=budget))
        except Exception:
            degraded.append("EMBEDDING_UNAVAILABLE")
        try:
            return await _blocking(self.index.search, SearchRequest(query=query, query_vector=vector,
                                   filters=filters, limit=max(limit, 100)), deadline=budget)
        except Exception:
            degraded.append("SEARCH_UNAVAILABLE")
            return []

    async def _apply_exclusion(self, hits, exclude_skills, budget, degraded):
        if not exclude_skills or not hits:
            return hits
        pending = [hit for hit in hits if not set(exclude_skills).issubset(hit.verified_exclusions)]
        if not pending:
            return hits
        try:
            contents = await _blocking(self.index.get_candidate_chunk_contents,
                                      list({hit.candidate_id for hit in pending}), deadline=budget)
        except Exception:
            degraded.append("EXCLUSION_UNVERIFIED")
            return []
        verified = []
        for hit in hits:
            if set(exclude_skills).issubset(hit.verified_exclusions):
                verified.append(hit)
                continue
            evidence = contents.get(hit.candidate_id)
            if not evidence:
                degraded.append("EXCLUSION_UNVERIFIED")
            elif not any(has_skill(content, skill) for content in evidence for skill in exclude_skills):
                verified.append(hit)
        return verified


def _apply_rerank_scored(hits, scored) -> list:
    """用模型真实相关性分数重排；校验 index、去重、补齐缺失项。"""
    score_map = {index: score for index, score in scored if isinstance(index, int)}
    order = [index for index, _ in sorted(scored, key=lambda item: item[1], reverse=True)]
    seen: set[int] = set()
    reordered: list = []
    for index in order:
        if index < 0 or index >= len(hits):
            continue
        if index in seen:
            continue
        seen.add(index)
        reordered.append(_with_rerank_score(hits[index], score_map.get(index, 0.0)))
    for index, hit in enumerate(hits):
        if index not in seen:
            reordered.append(hit)
    return reordered


def _apply_rerank_order(hits, order) -> list:
    """无真实相关性分数的降级重排：仅按顺序，不伪造 rerank_score。"""
    seen: set[int] = set()
    reordered: list = []
    for index in order:
        if not isinstance(index, int):
            continue
        if index < 0 or index >= len(hits):
            continue
        if index in seen:
            continue
        seen.add(index)
        reordered.append(hits[index])
    for index, hit in enumerate(hits):
        if index not in seen:
            reordered.append(hit)
    return reordered


def _dedupe_candidates(hits, limit: int) -> list:
    """按候选人去重后计数、截断。"""
    seen: set[str] = set()
    result: list = []
    for hit in hits:
        if hit.candidate_id in seen:
            continue
        seen.add(hit.candidate_id)
        result.append(hit)
        if len(result) >= limit:
            break
    return result


def _with_rerank_score(hit, score: float):
    from dataclasses import replace

    return replace(hit, rerank_score=round(score, 6))
