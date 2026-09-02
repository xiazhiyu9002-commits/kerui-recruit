from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from kerui_recruit.api.services import AppServices
from kerui_recruit.org.export import export_arch_pdf, export_client, export_internal


router = APIRouter(prefix="/api/org", tags=["org"])


class CreateCompanyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateCompanyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CompanyResponse(BaseModel):
    id: str
    name: str


class CreateDepartmentRequest(BaseModel):
    company_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = None
    leader_id: str | None = None
    leader_report_to: str | None = None
    team_size: int | None = None
    business_direction: str | None = None
    tech_stack: str | None = None
    office_location: str | None = None
    hc_status: str | None = None
    hc_internal_note: str | None = None


class DepartmentResponse(BaseModel):
    id: str
    company_id: str
    parent_id: str | None
    name: str
    leader_id: str | None
    leader_report_to: str | None
    team_size: int | None
    business_direction: str | None
    tech_stack: str | None
    office_location: str | None
    hc_status: str | None
    hc_internal_note: str | None


class CreateEmployeeRequest(BaseModel):
    company_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    department_id: str | None = None
    title: str | None = None
    job_level: str | None = None
    report_to: str | None = None
    subordinate_count: int | None = None
    tenure_years: Decimal | None = None
    business_module: str | None = None
    status: str | None = None
    intention: str | None = None
    remark: str | None = None
    contact: str | None = None
    is_key: bool = False


class EmployeeResponse(BaseModel):
    id: str
    company_id: str
    department_id: str | None
    name: str
    title: str | None
    job_level: str | None
    report_to: str | None
    subordinate_count: int | None
    tenure_years: Decimal | None
    business_module: str | None
    status: str | None
    intention: str | None
    remark: str | None
    contact: str | None
    is_key: bool


class UpdateDepartmentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: str | None = None
    leader_id: str | None = None
    leader_report_to: str | None = None
    team_size: int | None = None
    business_direction: str | None = None
    tech_stack: str | None = None
    office_location: str | None = None
    hc_status: str | None = None
    hc_internal_note: str | None = None


class UpdateEmployeeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    department_id: str | None = None
    title: str | None = None
    job_level: str | None = None
    report_to: str | None = None
    subordinate_count: int | None = None
    tenure_years: Decimal | None = None
    business_module: str | None = None
    status: str | None = None
    intention: str | None = None
    remark: str | None = None
    contact: str | None = None
    is_key: bool | None = None


class TreeNodeResponse(BaseModel):
    id: str
    kind: str
    name: str
    title: str | None = None
    job_level: str | None = None
    team_size: int | None = None
    is_key: bool = False
    children: list[TreeNodeResponse] = []


@router.post("/companies", response_model=CompanyResponse)
def create_company(command: CreateCompanyRequest, request: Request) -> CompanyResponse:
    services: AppServices = request.app.state.services
    company = services.org_service.create_company(name=command.name)
    return CompanyResponse(id=company.id, name=company.name)


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(request: Request) -> list[CompanyResponse]:
    services: AppServices = request.app.state.services
    companies = services.org_service.list_companies()
    return [CompanyResponse(id=c.id, name=c.name) for c in companies]


@router.post("/departments", response_model=DepartmentResponse)
def create_department(command: CreateDepartmentRequest, request: Request) -> DepartmentResponse:
    services: AppServices = request.app.state.services
    department = services.org_service.create_department(
        company_id=command.company_id,
        name=command.name,
        parent_id=command.parent_id,
        leader_id=command.leader_id,
        leader_report_to=command.leader_report_to,
        team_size=command.team_size,
        business_direction=command.business_direction,
        tech_stack=command.tech_stack,
        office_location=command.office_location,
        hc_status=command.hc_status,
        hc_internal_note=command.hc_internal_note,
    )
    return _department_to_response(department)


@router.get("/companies/{company_id}/departments", response_model=list[DepartmentResponse])
def list_departments(company_id: str, request: Request) -> list[DepartmentResponse]:
    services: AppServices = request.app.state.services
    departments = services.org_service.list_departments(company_id)
    return [_department_to_response(d) for d in departments]


@router.post("/employees", response_model=EmployeeResponse)
def create_employee(command: CreateEmployeeRequest, request: Request) -> EmployeeResponse:
    services: AppServices = request.app.state.services
    employee = services.org_service.create_employee(
        company_id=command.company_id,
        name=command.name,
        department_id=command.department_id,
        title=command.title,
        job_level=command.job_level,
        report_to=command.report_to,
        subordinate_count=command.subordinate_count,
        tenure_years=command.tenure_years,
        business_module=command.business_module,
        status=command.status,
        intention=command.intention,
        remark=command.remark,
        contact=command.contact,
        is_key=command.is_key,
    )
    return _employee_to_response(employee)


@router.get("/companies/{company_id}/employees", response_model=list[EmployeeResponse])
def list_employees(company_id: str, request: Request) -> list[EmployeeResponse]:
    services: AppServices = request.app.state.services
    employees = services.org_service.list_employees(company_id)
    return [_employee_to_response(e) for e in employees]


@router.get("/companies/{company_id}/tree", response_model=TreeNodeResponse)
def get_tree(company_id: str, request: Request) -> TreeNodeResponse:
    services: AppServices = request.app.state.services
    return _tree_to_response(services.org_service.build_tree(company_id))


@router.get("/companies/{company_id}/export")
def export_internal_xlsx(company_id: str, request: Request) -> Response:
    services: AppServices = request.app.state.services
    rows = services.org_service.flat_rows(company_id)
    payload = export_internal(rows)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="org_internal_{company_id}.xlsx"'},
    )


@router.get("/companies/{company_id}/export-client")
def export_client_xlsx(company_id: str, request: Request) -> Response:
    services: AppServices = request.app.state.services
    rows = services.org_service.flat_rows(company_id)
    payload = export_client(rows)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="org_client_{company_id}.xlsx"'},
    )


@router.get("/companies/{company_id}/export-pdf")
def export_arch(
    company_id: str,
    request: Request,
    orientation: str = "vertical",
    watermark: str = "",
) -> Response:
    services: AppServices = request.app.state.services
    root = services.org_service.build_arch_tree(company_id)
    payload = export_arch_pdf(root, orientation=orientation, watermark=watermark)
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="org_arch_{company_id}.pdf"'},
    )


@router.patch("/departments/{department_id}", response_model=DepartmentResponse)
def update_department(department_id: str, command: UpdateDepartmentRequest, request: Request) -> DepartmentResponse:
    services: AppServices = request.app.state.services
    department = services.org_service.update_department(
        department_id, **command.model_dump(exclude_unset=True)
    )
    return _department_to_response(department)


@router.delete("/departments/{department_id}")
def delete_department(department_id: str, request: Request) -> dict:
    services: AppServices = request.app.state.services
    services.org_service.delete_department(department_id)
    return {"deleted": True}


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse)
def update_employee(employee_id: str, command: UpdateEmployeeRequest, request: Request) -> EmployeeResponse:
    services: AppServices = request.app.state.services
    employee = services.org_service.update_employee(
        employee_id, **command.model_dump(exclude_unset=True)
    )
    return _employee_to_response(employee)


@router.delete("/employees/{employee_id}")
def delete_employee(employee_id: str, request: Request) -> dict:
    services: AppServices = request.app.state.services
    services.org_service.delete_employee(employee_id)
    return {"deleted": True}


@router.patch("/companies/{company_id}", response_model=CompanyResponse)
def update_company(company_id: str, command: UpdateCompanyRequest, request: Request) -> CompanyResponse:
    services: AppServices = request.app.state.services
    company = services.org_service.update_company(company_id, name=command.name)
    return CompanyResponse(id=company.id, name=company.name)


@router.delete("/companies/{company_id}")
def delete_company(company_id: str, request: Request) -> dict:
    services: AppServices = request.app.state.services
    services.org_service.delete_company(company_id)
    return {"deleted": True}


def _department_to_response(department) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        company_id=department.company_id,
        parent_id=department.parent_id,
        name=department.name,
        leader_id=department.leader_id,
        leader_report_to=department.leader_report_to,
        team_size=department.team_size,
        business_direction=department.business_direction,
        tech_stack=department.tech_stack,
        office_location=department.office_location,
        hc_status=department.hc_status,
        hc_internal_note=department.hc_internal_note,
    )


def _employee_to_response(employee) -> EmployeeResponse:
    return EmployeeResponse(
        id=employee.id,
        company_id=employee.company_id,
        department_id=employee.department_id,
        name=employee.name,
        title=employee.title,
        job_level=employee.job_level,
        report_to=employee.report_to,
        subordinate_count=employee.subordinate_count,
        tenure_years=employee.tenure_years,
        business_module=employee.business_module,
        status=employee.status,
        intention=employee.intention,
        remark=employee.remark,
        contact=employee.contact,
        is_key=employee.is_key,
    )


def _tree_to_response(node) -> TreeNodeResponse:
    return TreeNodeResponse(
        id=node.id,
        kind=node.kind,
        name=node.name,
        title=node.title,
        job_level=node.job_level,
        team_size=node.team_size,
        is_key=node.is_key,
        children=[_tree_to_response(child) for child in node.children],
    )
