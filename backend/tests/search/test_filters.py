from pathlib import Path

from kerui_recruit.search.contracts import CandidateFilters, SearchChunk, SearchRequest
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex


def test_hard_filters_never_leak_nonmatching_candidates(tmp_path: Path) -> None:
    """Applying hard filters after top-k retrieval can incorrectly leak or omit candidates."""
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=2)
    index.upsert(
        [
            SearchChunk("one", "one", "r1", "Python", (1.0, 0.0), 8, "MASTER", "上海", "AVAILABLE"),
            SearchChunk("two", "two", "r2", "Python", (1.0, 0.0), 3, "MASTER", "上海", "AVAILABLE"),
            SearchChunk("three", "three", "r3", "Python", (1.0, 0.0), 8, "BACHELOR", "上海", "AVAILABLE"),
            SearchChunk("four", "four", "r4", "Python", (1.0, 0.0), 8, "MASTER", "北京", "AVAILABLE"),
        ]
    )

    hits = index.search(
        SearchRequest(
            query="Python",
            query_vector=(1.0, 0.0),
            filters=CandidateFilters(
                min_years=5,
                highest_degree="MASTER",
                location="上海",
                candidate_status="AVAILABLE",
            ),
            limit=100,
        )
    )

    assert [hit.candidate_id for hit in hits] == ["one"]
