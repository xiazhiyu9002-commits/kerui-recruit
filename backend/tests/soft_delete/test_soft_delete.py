from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import Candidate, Jd
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.soft_delete.service import SoftDeleteService


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_soft_delete_candidate_sets_deleted_at(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = Candidate(display_name="张三")
        session.add(candidate)
        session.commit()
        cid = candidate.id

    service = SoftDeleteService(session_factory=session_factory)
    service.soft_delete("candidate", cid)

    with session_factory() as session:
        c = session.get(Candidate, cid)
        assert c.deleted_at is not None


def test_restore_candidate_clears_deleted_at(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = Candidate(display_name="张三")
        session.add(candidate)
        session.commit()
        cid = candidate.id

    service = SoftDeleteService(session_factory=session_factory)
    service.soft_delete("candidate", cid)
    service.restore("candidate", cid)

    with session_factory() as session:
        c = session.get(Candidate, cid)
        assert c.deleted_at is None


def test_is_deleted_returns_true_after_soft_delete(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = Candidate(display_name="张三")
        session.add(candidate)
        session.commit()
        cid = candidate.id

    service = SoftDeleteService(session_factory=session_factory)
    assert service.is_deleted("candidate", cid) is False
    service.soft_delete("candidate", cid)
    assert service.is_deleted("candidate", cid) is True
    service.restore("candidate", cid)
    assert service.is_deleted("candidate", cid) is False


def test_soft_delete_jd_sets_deleted_at(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        jd = Jd(company="某公司", title="Java")
        session.add(jd)
        session.commit()
        jid = jd.id

    service = SoftDeleteService(session_factory=session_factory)
    service.soft_delete("jd", jid)

    with session_factory() as session:
        j = session.get(Jd, jid)
        assert j.deleted_at is not None


def test_list_deleted_returns_soft_deleted_items(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = Candidate(display_name="张三")
        jd = Jd(company="某公司", title="Java")
        session.add_all([candidate, jd])
        session.commit()
        cid, jid = candidate.id, jd.id

    service = SoftDeleteService(session_factory=session_factory)
    service.soft_delete("candidate", cid)
    service.soft_delete("jd", jid)

    items = service.list_deleted()
    assert len(items) == 2

    by_type = {item["entity_type"]: item for item in items}
    assert by_type["candidate"]["label"] == "张三"
    assert by_type["jd"]["label"] == "某公司 - Java"