from __future__ import annotations

import io

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import Candidate, MappingNode, MatchResult, MatchRun


class ExportService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def export_match_run(self, run_id: str) -> bytes:
        with self.session_factory() as session:
            run = session.get(MatchRun, run_id)
            if run is None:
                raise LookupError(f"MatchRun not found: {run_id}")
            results = session.scalars(
                select(MatchResult).where(MatchResult.run_id == run_id)
            ).all()

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "匹配结果"
            sheet.append(["候选人", "总分", "处理状态", "推荐理由"])

            for result in results:
                candidate = session.get(Candidate, result.candidate_id)
                name = candidate.display_name if candidate else result.candidate_id
                sheet.append(
                    [name, float(result.total_score or 0), result.status, result.reason or ""]
                )

            buffer = io.BytesIO()
            workbook.save(buffer)
            return buffer.getvalue()

    def export_mapping_tree(self, snapshot_id: str) -> bytes:
        """Flatten an org-tree snapshot into an Excel sheet."""
        with self.session_factory() as session:
            nodes = session.scalars(
                select(MappingNode)
                .where(MappingNode.snapshot_id == snapshot_id)
                .order_by(MappingNode.sort_order)
            ).all()

        if not nodes:
            raise LookupError(f"Mapping snapshot not found or empty: {snapshot_id}")

        node_map = {node.id: node for node in nodes}

        def depth(node: MappingNode) -> int:
            level = 0
            current = node
            while current.parent_id and current.parent_id in node_map:
                level += 1
                current = node_map[current.parent_id]
            return level

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "组织架构"
        sheet.append(["层级", "节点名称", "父节点"])

        for node in nodes:
            parent = node_map[node.parent_id].name if node.parent_id else ""
            sheet.append([depth(node), node.name, parent])

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()