from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.migrate import migrate
from kerui_recruit.db.models import MappingNode, MappingProject, MappingSnapshot, MatchResult, MatchRun
from kerui_recruit.db.session import create_engine_for
from kerui_recruit.export.service import ExportService


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine_for(tmp_path / "recruit.sqlite3")
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_export_match_run_to_xlsx(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        run = MatchRun(trigger="JD_MATCH", query_text="Java")
        session.add(run)
        session.flush()
        session.add(
            MatchResult(
                run=run, candidate_id="cand-1", total_score=0.95, reason="Java 5年", status="未处理"
            )
        )
        session.commit()
        run_id = run.id

    data = ExportService(session_factory).export_match_run(run_id)

    assert data.startswith(b"PK")  # xlsx（zip 容器）魔数


def test_export_mapping_tree_to_xlsx(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        project = MappingProject(name="互联网公司图谱")
        session.add(project)
        session.flush()
        snapshot = MappingSnapshot(project_id=project.id, label="v1", is_current=True)
        session.add(snapshot)
        session.flush()
        root = MappingNode(snapshot_id=snapshot.id, parent_id=None, name="字节跳动", sort_order=0)
        session.add(root)
        session.flush()
        session.add(
            MappingNode(snapshot_id=snapshot.id, parent_id=root.id, name="技术部", sort_order=1)
        )
        session.commit()
        snapshot_id = snapshot.id

    data = ExportService(session_factory).export_mapping_tree(snapshot_id)

    assert data.startswith(b"PK")  # xlsx（zip 容器）魔数
