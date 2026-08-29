from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.cases.service import CaseService
from kerui_recruit.dashboard.service import DashboardService
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate, Jd
from kerui_recruit.db.session import create_engine_for


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_dashboard_overview_counts_funnel(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        c1 = Candidate(display_name="张三")
        c2 = Candidate(display_name="李四")
        jd = Jd(company="某公司", title="Java", status="OPEN")
        session.add_all([c1, c2, jd])
        session.commit()
        c1_id, c2_id, jd_id = c1.id, c2.id, jd.id

    case_service = CaseService(session_factory=session_factory)
    case1 = case_service.create(candidate_id=c1_id, jd_id=jd_id)
    case2 = case_service.create(candidate_id=c2_id, jd_id=jd_id)
    case_service.advance(case1.id, stage="已推荐")

    dashboard = DashboardService(session_factory=session_factory)
    overview = dashboard.overview()

    assert overview["recommendation_total"] == 1
    assert overview["health"]["candidate_total"] == 2
    assert overview["health"]["open_jd_total"] == 1

    funnel = {item["stage"]: item["count"] for item in overview["funnel"]}
    assert funnel["待评估"] == 1
    assert funnel["已推荐"] == 1


def test_dashboard_by_jd_groups_stage_counts(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = Candidate(display_name="张三")
        jd = Jd(company="某公司", title="Java")
        session.add_all([candidate, jd])
        session.commit()
        candidate_id, jd_id = candidate.id, jd.id

    case_service = CaseService(session_factory=session_factory)
    case = case_service.create(candidate_id=candidate_id, jd_id=jd_id)
    case_service.advance(case.id, stage="初试")

    dashboard = DashboardService(session_factory=session_factory)
    by_jd = dashboard.by_jd()

    assert len(by_jd) == 1
    assert by_jd[0]["company"] == "某公司"
    assert by_jd[0]["title"] == "Java"
    assert by_jd[0]["stage_counts"]["初试"] == 1
