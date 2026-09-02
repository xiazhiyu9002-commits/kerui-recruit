from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import Company, Department, Employee


_DEPARTMENT_FIELDS = frozenset({
    "name", "parent_id", "leader_id", "leader_report_to", "team_size",
    "business_direction", "tech_stack", "office_location", "hc_status",
    "hc_internal_note",
})

_EMPLOYEE_FIELDS = frozenset({
    "name", "department_id", "title", "job_level", "report_to",
    "subordinate_count", "tenure_years", "business_module", "status",
    "intention", "remark", "contact", "is_key",
})

_KEY_TITLE_KEYWORDS = ("负责人", "组长", "总监", "经理", "主管", "VP", "CTO", "CEO")


@dataclass
class OrgTreeNode:
    id: str
    kind: str  # "company" | "department" | "employee"
    name: str
    title: str | None = None
    job_level: str | None = None
    team_size: int | None = None
    leader_name: str | None = None
    is_key: bool = False
    folded: int = 0
    children: list[OrgTreeNode] = field(default_factory=list)


def _apply_changes(entity, changes: dict) -> None:
    for key, value in changes.items():
        setattr(entity, key, value)


class OrgService:
    """Structured company / department / employee org chart.

    Complements the legacy text-based :class:`MappingService` with a real
    relational model: a department tree plus employees that carry reporting
    relationships and sensitive, export-filtered fields.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    # --- Company ---------------------------------------------------------

    def create_company(self, *, name: str) -> Company:
        with self.session_factory() as session:
            company = Company(name=name)
            session.add(company)
            session.commit()
            return company

    def list_companies(self) -> list[Company]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(Company).order_by(Company.created_at.asc())
                ).all()
            )

    def delete_company(self, company_id: str) -> None:
        with self.session_factory() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise LookupError(f"Company not found: {company_id}")
            session.delete(company)
            session.commit()

    def update_company(self, company_id: str, *, name: str) -> Company:
        with self.session_factory() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise LookupError(f"Company not found: {company_id}")
            company.name = name
            session.commit()
            return company

    # --- Department ------------------------------------------------------

    def create_department(
        self,
        *,
        company_id: str,
        name: str,
        parent_id: str | None = None,
        leader_id: str | None = None,
        leader_report_to: str | None = None,
        team_size: int | None = None,
        business_direction: str | None = None,
        tech_stack: str | None = None,
        office_location: str | None = None,
        hc_status: str | None = None,
        hc_internal_note: str | None = None,
    ) -> Department:
        with self.session_factory() as session:
            if session.get(Company, company_id) is None:
                raise LookupError(f"Company not found: {company_id}")
            if parent_id is not None and session.get(Department, parent_id) is None:
                raise LookupError(f"Parent department not found: {parent_id}")

            department = Department(
                company_id=company_id,
                parent_id=parent_id,
                name=name,
                leader_id=leader_id,
                leader_report_to=leader_report_to,
                team_size=team_size,
                business_direction=business_direction,
                tech_stack=tech_stack,
                office_location=office_location,
                hc_status=hc_status,
                hc_internal_note=hc_internal_note,
            )
            session.add(department)
            session.commit()
            return department

    def list_departments(self, company_id: str) -> list[Department]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(Department)
                    .where(Department.company_id == company_id)
                    .order_by(Department.created_at.asc())
                ).all()
            )

    def update_department(self, department_id: str, **changes) -> Department:
        with self.session_factory() as session:
            department = session.get(Department, department_id)
            if department is None:
                raise LookupError(f"Department not found: {department_id}")
            _apply_changes(department, {k: v for k, v in changes.items() if k in _DEPARTMENT_FIELDS})
            session.commit()
            return department

    def delete_department(self, department_id: str) -> None:
        with self.session_factory() as session:
            department = session.get(Department, department_id)
            if department is None:
                raise LookupError(f"Department not found: {department_id}")
            session.delete(department)
            session.commit()

    # --- Employee --------------------------------------------------------

    def create_employee(
        self,
        *,
        company_id: str,
        name: str,
        department_id: str | None = None,
        title: str | None = None,
        job_level: str | None = None,
        report_to: str | None = None,
        subordinate_count: int | None = None,
        tenure_years: Decimal | None = None,
        business_module: str | None = None,
        status: str | None = None,
        intention: str | None = None,
        remark: str | None = None,
        contact: str | None = None,
        is_key: bool = False,
    ) -> Employee:
        with self.session_factory() as session:
            if session.get(Company, company_id) is None:
                raise LookupError(f"Company not found: {company_id}")
            if department_id is not None:
                department = session.get(Department, department_id)
                if department is None or department.company_id != company_id:
                    raise LookupError(f"Department not found: {department_id}")

            employee = Employee(
                company_id=company_id,
                department_id=department_id,
                name=name,
                title=title,
                job_level=job_level,
                report_to=report_to,
                subordinate_count=subordinate_count,
                tenure_years=tenure_years,
                business_module=business_module,
                status=status,
                intention=intention,
                remark=remark,
                contact=contact,
                is_key=is_key,
            )
            session.add(employee)
            session.commit()
            return employee

    def list_employees(self, company_id: str) -> list[Employee]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(Employee)
                    .where(Employee.company_id == company_id)
                    .order_by(Employee.created_at.asc())
                ).all()
            )

    def update_employee(self, employee_id: str, **changes) -> Employee:
        with self.session_factory() as session:
            employee = session.get(Employee, employee_id)
            if employee is None:
                raise LookupError(f"Employee not found: {employee_id}")
            _apply_changes(employee, {k: v for k, v in changes.items() if k in _EMPLOYEE_FIELDS})
            session.commit()
            return employee

    def delete_employee(self, employee_id: str) -> None:
        with self.session_factory() as session:
            employee = session.get(Employee, employee_id)
            if employee is None:
                raise LookupError(f"Employee not found: {employee_id}")
            session.delete(employee)
            session.commit()

    # --- Flat export rows ------------------------------------------------

    def flat_rows(self, company_id: str) -> list[dict[str, object]]:
        """Return one resolved dict per employee, denormalised for export."""
        with self.session_factory() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise LookupError(f"Company not found: {company_id}")

            departments = list(
                session.scalars(
                    select(Department).where(Department.company_id == company_id)
                ).all()
            )
            employees = list(
                session.scalars(
                    select(Employee).where(Employee.company_id == company_id)
                ).all()
            )

        dept_by_id = {d.id: d for d in departments}
        name_by_id = {e.id: e.name for e in employees}

        subordinate_counts: dict[str, int] = {}
        dept_sizes: dict[str, int] = {}
        for employee in employees:
            if employee.report_to:
                subordinate_counts[employee.report_to] = subordinate_counts.get(employee.report_to, 0) + 1
            if employee.department_id:
                dept_sizes[employee.department_id] = dept_sizes.get(employee.department_id, 0) + 1

        rows: list[dict[str, object]] = []
        for employee in employees:
            path = self._department_path(dept_by_id, employee.department_id)
            department = dept_by_id.get(employee.department_id) if employee.department_id else None

            def dept_text(field: str) -> str:
                return (getattr(department, field) or "") if department else ""

            rows.append(
                {
                    "company": company.name,
                    "top_department": path[0] if path else "",
                    "sub_department": " / ".join(path[1:]),
                    "name": employee.name,
                    "title": employee.title or "",
                    "job_level": employee.job_level or "",
                    "report_to_name": name_by_id.get(employee.report_to, ""),
                    "subordinate_count": employee.subordinate_count if employee.subordinate_count is not None else subordinate_counts.get(employee.id, 0),
                    "tenure_years": self._format_tenure(employee.tenure_years),
                    "business_module": employee.business_module or "",
                    "status": employee.status or "",
                    "intention": employee.intention or "",
                    "remark": employee.remark or "",
                    "contact": employee.contact or "",
                    "hc_status": dept_text("hc_status"),
                    "hc_internal_note": dept_text("hc_internal_note"),
                    "team_size": (department.team_size if department.team_size is not None else dept_sizes.get(department.id, 0)) if department else None,
                    "business_direction": dept_text("business_direction"),
                    "tech_stack": dept_text("tech_stack"),
                    "office_location": dept_text("office_location"),
                    "leader_name": name_by_id.get(department.leader_id, "") if department else "",
                    "leader_report_to_name": name_by_id.get(department.leader_report_to, "") if department else "",
                }
            )
        return rows

    def arch_lines(self, company_id: str) -> list[tuple[int, str]]:
        """Return ``(depth, label)`` lines for the filtered architecture chart.

        Non-key subordinates are folded into a ``+N`` marker so the chart stays
        readable while the full detail lives in the Excel export.
        """
        with self.session_factory() as session:
            if session.get(Company, company_id) is None:
                raise LookupError(f"Company not found: {company_id}")
            departments = list(
                session.scalars(
                    select(Department).where(Department.company_id == company_id)
                ).all()
            )
            employees = list(
                session.scalars(
                    select(Employee).where(Employee.company_id == company_id)
                ).all()
            )

        by_id = {e.id: e for e in employees}
        leader_ids = {d.leader_id for d in departments if d.leader_id}

        def is_key(employee: Employee) -> bool:
            if employee.is_key:
                return True
            if employee.id in leader_ids:
                return True
            return bool(employee.title) and any(
                keyword in employee.title for keyword in _KEY_TITLE_KEYWORDS
            )

        children: dict[str, list[Employee]] = {}
        roots: list[Employee] = []
        for employee in employees:
            if employee.report_to and employee.report_to in by_id:
                children.setdefault(employee.report_to, []).append(employee)
            else:
                roots.append(employee)

        def count_all(employee: Employee) -> int:
            total = 0
            for child in children.get(employee.id, []):
                total += 1 + count_all(child)
            return total

        def label(employee: Employee) -> str:
            extra = "、".join(x for x in (employee.title, employee.job_level) if x)
            return f"{employee.name}（{extra}）" if extra else employee.name

        lines: list[tuple[int, str]] = []

        def emit(employee: Employee, depth: int) -> None:
            lines.append((depth, label(employee)))
            folded = 0
            for child in children.get(employee.id, []):
                if is_key(child):
                    emit(child, depth + 1)
                else:
                    folded += 1 + count_all(child)
            if folded:
                lines.append((depth + 1, f"+{folded}"))

        for root in roots:
            emit(root, 0)

        return lines

    def build_tree(self, company_id: str) -> OrgTreeNode:
        """Build a unified company/department/employee tree for the mind-map.

        Departments form a tree via ``parent_id``; employees attach to their
        department (or the company root when unassigned) and then follow the
        ``report_to`` chain.
        """
        with self.session_factory() as session:
            company = session.get(Company, company_id)
            if company is None:
                raise LookupError(f"Company not found: {company_id}")
            departments = list(
                session.scalars(
                    select(Department).where(Department.company_id == company_id)
                ).all()
            )
            employees = list(
                session.scalars(
                    select(Employee).where(Employee.company_id == company_id)
                ).all()
            )

        emp_by_id = {e.id: e for e in employees}

        children_map: dict[str, list[Employee]] = {}
        roots_by_dept: dict[str, list[Employee]] = {}
        for employee in employees:
            if employee.report_to and employee.report_to in emp_by_id:
                children_map.setdefault(employee.report_to, []).append(employee)
            elif employee.department_id:
                roots_by_dept.setdefault(employee.department_id, []).append(employee)

        dept_by_parent: dict[str | None, list[Department]] = {}
        for department in departments:
            dept_by_parent.setdefault(department.parent_id, []).append(department)

        dept_sizes: dict[str, int] = {}
        for employee in employees:
            if employee.department_id:
                dept_sizes[employee.department_id] = dept_sizes.get(employee.department_id, 0) + 1

        def build_employee(employee: Employee) -> OrgTreeNode:
            node = OrgTreeNode(
                id=employee.id,
                kind="employee",
                name=employee.name,
                title=employee.title,
                job_level=employee.job_level,
                is_key=employee.is_key,
            )
            for subordinate in children_map.get(employee.id, []):
                node.children.append(build_employee(subordinate))
            return node

        def build_department(department: Department) -> OrgTreeNode:
            leader = emp_by_id.get(department.leader_id) if department.leader_id else None
            node = OrgTreeNode(
                id=department.id,
                kind="department",
                name=department.name,
                team_size=department.team_size if department.team_size is not None else dept_sizes.get(department.id, 0),
                leader_name=leader.name if leader is not None else None,
            )
            for child_dept in dept_by_parent.get(department.id, []):
                node.children.append(build_department(child_dept))

            added: set[str] = set()
            if leader is not None and (not leader.report_to or leader.report_to not in emp_by_id):
                node.children.append(build_employee(leader))
                added.add(leader.id)

            for employee in roots_by_dept.get(department.id, []):
                if employee.id not in added:
                    node.children.append(build_employee(employee))
                    added.add(employee.id)
            return node

        root = OrgTreeNode(id=company.id, kind="company", name=company.name)
        for department in dept_by_parent.get(None, []):
            root.children.append(build_department(department))

        # Unassigned employees with no reporting line hang off the company root.
        for employee in employees:
            if not employee.department_id and (not employee.report_to or employee.report_to not in emp_by_id):
                root.children.append(build_employee(employee))

        return root

    def build_arch_tree(self, company_id: str) -> OrgTreeNode:
        """Return a department-only tree for the architecture chart.

        Individual employees are not shown as separate nodes; the leader name
        is carried on each department node and inlined into its label by the
        PDF renderer (``名称-负责人``).
        """
        tree = self.build_tree(company_id)

        def filter_node(node: OrgTreeNode) -> OrgTreeNode:
            result = OrgTreeNode(
                id=node.id,
                kind=node.kind,
                name=node.name,
                title=node.title,
                job_level=node.job_level,
                team_size=node.team_size,
                leader_name=node.leader_name,
                is_key=node.is_key,
            )
            for child in node.children:
                if child.kind == "department":
                    result.children.append(filter_node(child))
            return result

        return filter_node(tree)

    @staticmethod
    def _department_path(
        dept_by_id: dict[str, Department],
        department_id: str | None,
    ) -> list[str]:
        path: list[str] = []
        current_id = department_id
        while current_id:
            department = dept_by_id.get(current_id)
            if department is None:
                break
            path.append(department.name)
            current_id = department.parent_id
        path.reverse()
        return path

    @staticmethod
    def _format_tenure(value: Decimal | None) -> object:
        if value is None:
            return None
        normalized = value.normalize()
        if normalized == normalized.to_integral():
            return int(normalized)
        return float(normalized)
