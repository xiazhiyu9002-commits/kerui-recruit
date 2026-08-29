from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.cases.service import CaseService
from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate, CandidateJobCase, Jd, StageEvent
from kerui_recruit.db.session import create_engine_for


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _seed(session_factory: sessionmaker[Session]) -> tuple[str, str]:
    with session_factory() as session:
        candidate = Candidate(display_name="张三")
        jd = Jd(company="某公司", title="Java")
        session.add_all([candidate, jd])
        session.commit()
        return candidate.id, jd.id


def test_create_case_is_idempotent(session_factory: sessionmaker[Session]) -> None:
    candidate_id, jd_id = _seed(session_factory)
    service = CaseService(session_factory=session_factory)

    first = service.create(candidate_id=candidate_id, jd_id=jd_id)
    second = service.create(candidate_id=candidate_id, jd_id=jd_id)

    assert first.id == second.id
    assert first.stage == "待评估"


def test_advance_records_stage_event(session_factory: sessionmaker[Session]) -> None:
    candidate_id, jd_id = _seed(session_factory)
    service = CaseService(session_factory=session_factory)
    case = service.create(candidate_id=candidate_id, jd_id=jd_id)

    advanced = service.advance(case.id, stage="已推荐", note="推荐给客户")
    assert advanced.stage == "已推荐"
    assert advanced.note == "推荐给客户"

    events = service.get_events(case.id)
    assert len(events) == 1
    assert events[0].stage == "已推荐"


def test_undo_rolls_back_stage(session_factory: sessionmaker[Session]) -> None:
    candidate_id, jd_id = _seed(session_factory)
    service = CaseService(session_factory=session_factory)
    case = service.create(candidate_id=candidate_id, jd_id=jd_id)

    service.advance(case.id, stage="已推荐")
    service.advance(case.id, stage="初试")

    undone = service.undo(case.id)
    assert undone.stage == "已推荐"
    assert len(service.get_events(case.id)) == 1


def test_advance_rejects_unknown_stage(session_factory: sessionmaker[Session]) -> None:
    candidate_id, jd_id = _seed(session_factory)
    service = CaseService(session_factory=session_factory)
    case = service.create(candidate_id=candidate_id, jd_id=jd_id)

    with pytest.raises(ValueError, match="Unknown stage"):
        service.advance(case.id, stage="不存在的阶段")


def test_list_cases_filters_by_candidate(session_factory: sessionmaker[Session]) -> None:
    candidate_id, jd_id = _seed(session_factory)
    service = CaseService(session_factory=session_factory)
    service.create(candidate_id=candidate_id, jd_id=jd_id)

    cases = service.list_cases(candidate_id=candidate_id)
    assert len(cases) == 1
    assert cases[0].candidate_id == candidate_id
