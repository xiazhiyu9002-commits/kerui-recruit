from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.reminders.service import ReminderService


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_create_and_list_reminders(session_factory: sessionmaker[Session]) -> None:
    service = ReminderService(session_factory=session_factory)
    now = datetime.now(timezone.utc)
    service.create(title="联系候选人张三", remind_at=now + timedelta(hours=1), note="电话沟通")
    service.create(title="发送offer给李四", remind_at=now + timedelta(days=2))

    pending = service.list_pending()
    assert len(pending) == 2
    assert pending[0].title == "联系候选人张三"
    assert pending[1].title == "发送offer给李四"


def test_list_due_returns_only_past_reminders(session_factory: sessionmaker[Session]) -> None:
    service = ReminderService(session_factory=session_factory)
    now = datetime.now(timezone.utc)
    due = service.create(title="过期提醒", remind_at=now - timedelta(hours=1))
    service.create(title="未来提醒", remind_at=now + timedelta(days=1))

    due_list = service.list_due()
    assert len(due_list) == 1
    assert due_list[0].title == "过期提醒"


def test_dismiss_reminder(session_factory: sessionmaker[Session]) -> None:
    service = ReminderService(session_factory=session_factory)
    r = service.create(title="测试提醒", remind_at=datetime.now(timezone.utc))

    dismissed = service.dismiss(r.id)
    assert dismissed.dismissed is True
    assert dismissed.dismissed_at is not None

    pending = service.list_pending()
    assert len(pending) == 0