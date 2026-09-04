from __future__ import annotations

import pytest

from kerui_recruit.bench.direction_benchmark import DirectionBenchmark


@pytest.mark.asyncio
async def test_direction_benchmark_completes_and_reports_metrics():
    report = await DirectionBenchmark().run(
        candidate_count=40, query_count=10, concurrency=4, qps=0)

    assert report.candidate_count == 40
    assert report.chunk_count == 120
    assert report.query_count == 10
    assert report.synthetic is True
    assert report.external_provider_calls == 0
    assert report.error_rate == 0.0
    assert report.actual_qps > 0
    assert report.direction_enabled is True
    assert report.embedding_model == "local-hash-v1"
    assert report.match_jd_items > 0


@pytest.mark.asyncio
async def test_direction_benchmark_concurrency_reaches_limit():
    report = await DirectionBenchmark().run(
        candidate_count=40, query_count=20, concurrency=5, qps=0)

    # 无 QPS 限流时，并发上限就是 Semaphore 值；20 个任务会立刻占满 5 个槽。
    assert report.peak_concurrency == 5


@pytest.mark.asyncio
async def test_direction_benchmark_qps_limits_throughput():
    report = await DirectionBenchmark().run(
        candidate_count=40, query_count=10, concurrency=10, qps=10)

    # 10 个请求在 qps=10 下至少需要 9 个间隔（0.9s），实际吞吐应被限流到 ~10。
    assert report.actual_qps <= 15
    assert report.peak_concurrency <= 10
