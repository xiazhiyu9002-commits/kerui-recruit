from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Blob, Candidate, ResumeDocument, ResumeRevision
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.direction.compatibility import direction_compatibility
from kerui_recruit.direction.models import DirectionProfile, build_direction_label
from kerui_recruit.match.service import MatchService, _JdContext, _must_skills, _skill_coverage
from kerui_recruit.search.contracts import SearchHit


def _profile(primary: str, source: str = "LLM", confidence: float = 0.9) -> DirectionProfile:
    return DirectionProfile(status="CONFIDENT", role_families=[
        build_direction_label(primary, source=source, confidence=confidence, is_primary=True),
    ])


def test_must_skills_excludes_tech_and_business_direction():
    ctx = _JdContext(
        revision_id="r", jd_id="j", source_text=None, min_years=None, highest_degree=None, location=None,
        parsed_data={
            "tech_direction": ["后端"],
            "business_direction": ["金融"],
            "required_skills": ["Java", "Spring"],
            "requirements": [{"kind": "MUST", "label": "技能", "value": "MySQL"}],
        },
    )
    skills = _must_skills(ctx)
    assert "后端" not in skills
    assert "金融" not in skills
    assert "Java" in skills
    assert "Spring" in skills
    assert "MySQL" in skills


def test_skill_coverage_uses_full_resume():
    data = {
        "skills": ["Java"],
        "experiences": [{"title": "后端工程师", "summary": "负责风控平台开发"}],
        "projects": [{"tech_stack": "Spring", "summary": "构建微服务"}],
    }
    matched, missing = _skill_coverage(data, ["Java", "风控", "Spring"])
    assert "Java" in matched
    assert "风控" in matched
    assert "Spring" in matched
    assert missing == []


def test_direction_ordering_prefers_exact_match_over_unrelated():
    jd = _profile("BACKEND")
    assert direction_compatibility(jd, _profile("BACKEND")) > direction_compatibility(jd, _profile("AI_ML"))


def test_direction_ordering_domain_specific_cases():
    assert direction_compatibility(_profile("RISK_STRATEGY"), _profile("RISK_STRATEGY")) > \
        direction_compatibility(_profile("RISK_STRATEGY"), _profile("LEGAL"))
    assert direction_compatibility(_profile("AML_COMPLIANCE"), _profile("AML_COMPLIANCE")) > \
        direction_compatibility(_profile("AML_COMPLIANCE"), _profile("SECURITY_ENGINEERING"))
    assert direction_compatibility(_profile("DATA_ENGINEERING"), _profile("DATA_ENGINEERING")) > \
        direction_compatibility(_profile("DATA_ENGINEERING"), _profile("DATA_ANALYSIS"))


def test_direction_unknown_not_hard_excluded():
    assert direction_compatibility(_profile("BACKEND"), DirectionProfile.unknown()) == 0.5


def test_direction_manual_label_participates_in_ranking():
    jd = _profile("BACKEND")
    manual = _profile("BACKEND", source="USER", confidence=1.0)
    assert direction_compatibility(jd, manual) >= direction_compatibility(jd, _profile("BACKEND"))


def test_direction_ordering_slices_limit_after_scoring(tmp_path):
    engine = create_engine_for(tmp_path / "order.sqlite3")
    migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        for number, code in (("1", "AI_ML"), ("2", "BACKEND")):
            cid = f"cand-{number}"
            session.add(Candidate(id=cid, display_name=f"C{number}", status="AVAILABLE"))
            session.add(Blob(id=f"blob-{number}", content_sha256=str(number).zfill(64),
                             suffix=".txt", size_bytes=1, storage_path=f"b{number}"))
            session.flush()
            session.add(ResumeDocument(id=f"doc-{number}", candidate_id=cid))
            session.flush()
            session.add(ResumeRevision(id=f"rev-{number}", document_id=f"doc-{number}",
                                       blob_id=f"blob-{number}", content_sha256=str(number).zfill(64),
                                       original_filename="r.txt", status="READY", is_current=True,
                                       raw_text="x", parsed_data={"direction_profile": _profile(code).model_dump(mode="json")}))
    service = MatchService(session_factory=factory, search_service=None)  # type: ignore[arg-type]
    context = _JdContext(revision_id="jrev", jd_id="jd", source_text=None, min_years=None,
                         highest_degree=None, location=None,
                         parsed_data={"direction_profile": _profile("BACKEND").model_dump(mode="json")})

    def hit(cid: str) -> SearchHit:
        return SearchHit(chunk_id=f"{cid}-0", candidate_id=cid, revision_id=f"rev-{cid[-1]}",
                         content="x", score=1.0, matched_channels=(), total_years=5.0,
                         highest_degree=None, location=None, rerank_score=0.8)

    # rerank 相同，只有方向不同；AI_ML 先传入，方向加权后 BACKEND 应胜出。
    ordered = service._score_and_sort(context, [hit("cand-1"), hit("cand-2")], limit=1)
    assert [h.candidate_id for h in ordered] == ["cand-2"]
