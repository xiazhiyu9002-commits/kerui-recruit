from pathlib import Path

from kerui_recruit.search.contracts import CandidateFilters, SearchChunk, SearchRequest
from kerui_recruit.search.lancedb_index import LanceDBSearchIndex


def chunk(
    candidate_id: str,
    content: str,
    vector: tuple[float, float],
    *,
    revision_id: str = "revision-1",
    total_years: float = 5,
    degree: str = "BACHELOR",
) -> SearchChunk:
    return SearchChunk(
        id=f"chunk-{candidate_id}",
        candidate_id=candidate_id,
        revision_id=revision_id,
        content=content,
        vector=vector,
        total_years=total_years,
        highest_degree=degree,
        location="上海",
        candidate_status="AVAILABLE",
    )


def test_hybrid_search_combines_keyword_and_semantic_evidence(tmp_path: Path) -> None:
    """Removing either retrieval channel must change and degrade the expected ranking."""
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=2)
    index.upsert(
        [
            chunk("a", "Java payment platform", (1.0, 0.0)),
            chunk("b", "financial settlement platform", (0.9, 0.1)),
            chunk("c", "graphic design", (0.0, 1.0)),
        ]
    )

    hits = index.search(
        SearchRequest(
            query="Java finance",
            query_vector=(1.0, 0.0),
            filters=CandidateFilters(),
            limit=20,
        )
    )

    assert [hit.candidate_id for hit in hits[:2]] == ["a", "b"]
    assert hits[0].matched_channels == ("bm25", "vector")


def test_deleting_a_revision_removes_all_of_its_chunks(tmp_path: Path) -> None:
    """An obsolete resume revision must never remain searchable after replacement."""
    index = LanceDBSearchIndex(tmp_path / "search", vector_dimension=2)
    index.upsert([chunk("a", "Python", (1.0, 0.0), revision_id="old")])

    index.delete_revision("old")
    hits = index.search(
        SearchRequest("Python", (1.0, 0.0), CandidateFilters(), limit=20)
    )

    assert hits == []
