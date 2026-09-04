from __future__ import annotations

from kerui_recruit.direction.models import QueryDirectionIntent
from kerui_recruit.search.contracts import SearchHit
from kerui_recruit.search.service import _apply_direction_boost


def _hit(candidate_id: str, primary: str | None) -> SearchHit:
    return SearchHit(
        chunk_id=candidate_id, candidate_id=candidate_id, revision_id=candidate_id,
        content="x", score=0.0, matched_channels=(), total_years=None, highest_degree=None,
        location=None, primary_role_family=primary,
        role_family_codes=(primary,) if primary else (),
    )


def test_direction_boost_moves_51st_into_top50():
    hits = [_hit(f"c{i}", "BACKEND" if i == 50 else "FRONTEND") for i in range(60)]
    intent = QueryDirectionIntent(role_code="BACKEND", matched=True)
    boosted = _apply_direction_boost(hits, intent)
    assert any(h.candidate_id == "c50" for h in boosted[:50])


def test_no_intent_keeps_order():
    hits = [_hit(f"c{i}", "FRONTEND") for i in range(60)]
    boosted = _apply_direction_boost(hits, QueryDirectionIntent(matched=False))
    assert boosted == hits


def test_unknown_direction_gets_neutral():
    hits = [_hit(f"c{i}", None) for i in range(5)]
    intent = QueryDirectionIntent(role_code="BACKEND", matched=True)
    boosted = _apply_direction_boost(hits, intent)
    assert len(boosted) == 5
