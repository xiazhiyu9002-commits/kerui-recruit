import { invoke } from "@tauri-apps/api/core";

import type {
  AppSettings,
  BackupSnapshot,
  BdAgentQueryResult,
  BdLead,
  BdProgress,
  CandidateContact,
  CandidateListItem,
  CandidatePage,
  CandidateSearchFilters,
  CandidateSearchResult,
  CaseItem,
  CaseActionInput,
  CaseDetail,
  CaseEventItem,
  CaseRoundItem,
  CorrectionRecord,
  DashboardByJd,
  DashboardOverview,
  DashboardTrendItem,
  DeletedItem,
  DiagnosticsData,
  ImportedResume,
  CreateReminderInput,
  IndexSyncStatus,
  JdListItem,
  MappingProject,
  MappingSnapshot,
  MappingTreeNode,
  MatchCandidateItem,
  MatchMarkStatus,
  MatchResultGroup,
  MigrationReport,
  OnboardingStatus,
  CreateOrgDepartmentInput,
  CreateOrgEmployeeInput,
  UpdateOrgDepartmentInput,
  UpdateOrgEmployeeInput,
  OrgCompany,
  OrgDepartment,
  OrgEmployee,
  OrgTreeNode,
  ProviderCheck,
  RecruitmentApi,
  ReminderItem,
  ReverseMatchItem,
  ResumeRevision,
  ResumeReview,
  TaskAction,
  TaskStatus
} from "../App";


export interface RuntimeConfig {
  apiBaseUrl: string;
  sessionToken: string;
}

interface ApiError {
  message?: string;
  detail?: string;
}

class ApiRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export interface DashboardQuery {
  company?: string;
  jd_id?: string;
  date_from?: string;
  date_to?: string;
}

function _dashQuery(filters?: DashboardQuery): string {
  if (!filters) return "";
  const parts: string[] = [];
  if (filters.company) parts.push(`company=${encodeURIComponent(filters.company)}`);
  if (filters.jd_id) parts.push(`jd_id=${encodeURIComponent(filters.jd_id)}`);
  if (filters.date_from) parts.push(`date_from=${encodeURIComponent(filters.date_from)}`);
  if (filters.date_to) parts.push(`date_to=${encodeURIComponent(filters.date_to)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}


export class ApiClient implements RecruitmentApi {
  private readonly baseUrl: string;

  constructor(
    baseUrl: string,
    private readonly sessionToken: string,
    private readonly fetcher: typeof fetch = fetch.bind(globalThis)
  ) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  importResume(file: File): Promise<ImportedResume> {
    const form = new FormData();
    form.append("file", file);
    return this.request<ImportedResume>("/api/resumes/import", {
      body: form,
      method: "POST"
    });
  }

  importFolder(directory: string) {
    return this.request<{ imported: ImportedResume[]; skipped: string[]; errors: string[] }>(
      "/api/resumes/import-folder",
      {
        body: JSON.stringify({ directory }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  onboardingStatus() {
    return this.request<OnboardingStatus>("/api/onboarding/status");
  }

  testProviders() {
    return this.request<ProviderCheck[]>("/api/onboarding/test-providers", {
      method: "POST"
    });
  }

  getTask(taskId: string): Promise<TaskStatus> {
    return this.request<TaskStatus>(`/api/tasks/${encodeURIComponent(taskId)}`);
  }

  listTasks(): Promise<TaskStatus[]> {
    return this.request<TaskStatus[]>("/api/tasks");
  }

  controlTask(taskId: string, action: TaskAction): Promise<TaskStatus> {
    return this.request<TaskStatus>(
      `/api/tasks/${encodeURIComponent(taskId)}/${action}`,
      { method: "POST" }
    );
  }

  listResumeRevisions(candidateId: string): Promise<ResumeRevision[]> {
    return this.request<ResumeRevision[]>(
      `/api/resumes/candidate/${encodeURIComponent(candidateId)}/revisions`
    );
  }

  switchResumeRevision(revisionId: string): Promise<ResumeRevision> {
    return this.request<ResumeRevision>(
      `/api/resumes/revisions/${encodeURIComponent(revisionId)}/switch`,
      { method: "POST" }
    );
  }

  reparseResume(revisionId: string, forceOcr: boolean): Promise<{ revision_id: string; task_id: string }> {
    return this.request<{ revision_id: string; task_id: string }>(
      `/api/resumes/revisions/${encodeURIComponent(revisionId)}/reparse`,
      {
        body: JSON.stringify({ force_ocr: forceOcr }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  async downloadResume(revisionId: string, filename: string) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(
      `${this.baseUrl}/api/resumes/revisions/${encodeURIComponent(revisionId)}/download`,
      { headers }
    );
    if (!response.ok) throw new Error("下载失败");
    const blob = await response.blob();
    this.triggerDownload(blob, filename);
  }

  async previewResume(revisionId: string): Promise<string> {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(
      `${this.baseUrl}/api/resumes/revisions/${encodeURIComponent(revisionId)}/preview`,
      { headers }
    );
    if (!response.ok) throw new Error("预览失败");
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  }

  searchCandidates(query: string, filters?: CandidateSearchFilters): Promise<CandidateSearchResult> {
    return this.request<CandidateSearchResult>("/api/search/candidates", {
      body: JSON.stringify({ query, limit: 50, ...(filters && Object.keys(filters).length ? { filters } : {}) }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  listCandidates(): Promise<CandidateListItem[]> {
    return this.request<CandidateListItem[]>("/api/resumes/candidates");
  }

  async listCandidatesPage(page: number, pageSize: number): Promise<CandidatePage> {
    try {
      return await this.request<CandidatePage>(
        `/api/resumes/candidates/page?page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(pageSize)}`
      );
    } catch (error) {
      if (!(error instanceof ApiRequestError) || error.status !== 404) throw error;
      // Transitional compatibility for a desktop frontend that reloads before
      // its already-running sidecar has restarted with the paging endpoint.
      const items = await this.listCandidates();
      const start = Math.max(0, (page - 1) * pageSize);
      return {
        items: items.slice(start, start + pageSize),
        total: items.length,
        page,
        page_size: pageSize,
        has_more: start + pageSize < items.length,
      };
    }
  }

  importJd(input: { company: string; title: string; sourceText: string }) {
    return this.request<{ jd_id: string; revision_id: string }>("/api/jd/import", {
      body: JSON.stringify({
        company: input.company,
        title: input.title,
        source_text: input.sourceText
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  importJdFile(file: File, company: string, title: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("company", company);
    form.append("title", title);
    return this.request<{ jd_id: string; revision_id: string }>("/api/jd/import-file", {
      body: form,
      method: "POST"
    });
  }

  importJdBatch(sourceText: string) {
    return this.request<{ imported: { jd_id: string; revision_id: string }[] }>(
      "/api/jd/import-batch",
      {
        body: JSON.stringify({ source_text: sourceText }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  importJdBatchFile(file: File) {
    const form = new FormData();
    form.append("file", file);
    return this.request<{ imported: { jd_id: string; revision_id: string }[] }>(
      "/api/jd/import-batch-file",
      { body: form, method: "POST" }
    );
  }

  listJds(): Promise<JdListItem[]> {
    return this.request<JdListItem[]>("/api/jd");
  }

  updateJdStatus(jdId: string, status: string) {
    return this.request<{ jd_id: string; status: string }>(
      `/api/jd/${encodeURIComponent(jdId)}/status`,
      {
        body: JSON.stringify({ status }),
        headers: { "Content-Type": "application/json" },
        method: "PATCH"
      }
    );
  }

  updateJdField(jdId: string, field: string, value: unknown) {
    return this.request<{ jd_id: string; revision_id: string; field: string; value: unknown }>(
      `/api/jd/${encodeURIComponent(jdId)}/field`,
      {
        body: JSON.stringify({ field, value }),
        headers: { "Content-Type": "application/json" },
        method: "PUT"
      }
    );
  }

  matchJd(revisionId: string, limit = 20) {
    return this.request<{ run_id: string; items: CandidateSearchResult["items"] }>(
      "/api/match/jd",
      {
        body: JSON.stringify({ revision_id: revisionId, limit }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  matchBatch(revisionIds: string[], limit = 20) {
    return this.request<{ results: { revision_id: string; run_id: string; items: CandidateSearchResult["items"] }[] }>(
      "/api/match/batch",
      {
        body: JSON.stringify({ revision_ids: revisionIds, limit }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  markMatchResult(resultId: string, status: MatchMarkStatus) {
    return this.request<{ result_id: string; status: MatchMarkStatus }>(
      `/api/match/result/${encodeURIComponent(resultId)}/mark`,
      {
        body: JSON.stringify({ status }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  listMatchResults() {
    return this.request<{ groups: MatchResultGroup[] }>("/api/match/results");
  }

  listMatchResultsForCandidate(candidateId: string) {
    return this.request<MatchCandidateItem[]>(
      `/api/match/candidate/${encodeURIComponent(candidateId)}`
    );
  }

  matchCandidate(candidateId: string) {
    return this.request<MatchCandidateItem[]>(
      `/api/match/candidate/${encodeURIComponent(candidateId)}`,
      { method: "POST" }
    );
  }

  createCaseFromMatchResult(resultId: string) {
    return this.request<{ case_id: string; result_id: string; status: string }>(
      `/api/match/result/${encodeURIComponent(resultId)}/create-case`,
      { method: "POST" }
    );
  }

  async exportMatchJd(revisionId: string) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(
      `${this.baseUrl}/api/match/jd/${encodeURIComponent(revisionId)}/export`,
      { headers }
    );
    if (!response.ok) throw new Error("导出失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `match_${revisionId}.xlsx`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  health() {
    return this.request<Record<string, { status: string; message?: string }>>(
      "/health/checks"
    );
  }

  diagnostics() {
    return this.request<DiagnosticsData>("/api/diagnostics");
  }

  async exportDiagnostics() {
    await this.download("/api/diagnostics/export", "diagnostics.json");
  }

  listMappingProjects() {
    return this.request<MappingProject[]>("/api/mapping/projects");
  }

  createMappingProject(name: string, description?: string) {
    return this.request<MappingProject>("/api/mapping/projects", {
      body: JSON.stringify({ name, description }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  buildMappingTree(projectId: string, text: string, label = "") {
    return this.request<MappingSnapshot>(
      `/api/mapping/projects/${encodeURIComponent(projectId)}/build-from-text`,
      {
        body: JSON.stringify({ text, label }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  listMappingSnapshots(projectId: string) {
    return this.request<MappingSnapshot[]>(
      `/api/mapping/projects/${encodeURIComponent(projectId)}/snapshots`
    );
  }

  getMappingTree(snapshotId: string) {
    return this.request<MappingTreeNode[]>(
      `/api/mapping/snapshots/${encodeURIComponent(snapshotId)}/tree`
    );
  }

  listCompanies() {
    return this.request<OrgCompany[]>("/api/org/companies");
  }

  createCompany(name: string) {
    return this.request<OrgCompany>("/api/org/companies", {
      body: JSON.stringify({ name }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  updateCompany(companyId: string, name: string) {
    return this.request<OrgCompany>(
      `/api/org/companies/${encodeURIComponent(companyId)}`,
      {
        body: JSON.stringify({ name }),
        headers: { "Content-Type": "application/json" },
        method: "PATCH"
      }
    );
  }

  listDepartments(companyId: string) {
    return this.request<OrgDepartment[]>(
      `/api/org/companies/${encodeURIComponent(companyId)}/departments`
    );
  }

  createDepartment(input: CreateOrgDepartmentInput) {
    return this.request<OrgDepartment>("/api/org/departments", {
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  listEmployees(companyId: string) {
    return this.request<OrgEmployee[]>(
      `/api/org/companies/${encodeURIComponent(companyId)}/employees`
    );
  }

  getOrgTree(companyId: string) {
    return this.request<OrgTreeNode>(
      `/api/org/companies/${encodeURIComponent(companyId)}/tree`
    );
  }

  createEmployee(input: CreateOrgEmployeeInput) {
    return this.request<OrgEmployee>("/api/org/employees", {
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  async exportOrgInternal(companyId: string) {
    await this.download(
      `/api/org/companies/${encodeURIComponent(companyId)}/export`,
      `org_internal_${companyId}.xlsx`
    );
  }

  async exportOrgClient(companyId: string) {
    await this.download(
      `/api/org/companies/${encodeURIComponent(companyId)}/export-client`,
      `org_client_${companyId}.xlsx`
    );
  }

  async exportOrgArchPdf(companyId: string) {
    await this.download(
      `/api/org/companies/${encodeURIComponent(companyId)}/export-pdf`,
      `org_arch_${companyId}.pdf`
    );
  }

  updateDepartment(departmentId: string, changes: UpdateOrgDepartmentInput) {
    return this.request<OrgDepartment>(
      `/api/org/departments/${encodeURIComponent(departmentId)}`,
      {
        body: JSON.stringify(changes),
        headers: { "Content-Type": "application/json" },
        method: "PATCH"
      }
    );
  }

  async deleteDepartment(departmentId: string) {
    await this.request<{ deleted: boolean }>(
      `/api/org/departments/${encodeURIComponent(departmentId)}`,
      { method: "DELETE" }
    );
  }

  updateEmployee(employeeId: string, changes: UpdateOrgEmployeeInput) {
    return this.request<OrgEmployee>(
      `/api/org/employees/${encodeURIComponent(employeeId)}`,
      {
        body: JSON.stringify(changes),
        headers: { "Content-Type": "application/json" },
        method: "PATCH"
      }
    );
  }

  async deleteEmployee(employeeId: string) {
    await this.request<{ deleted: boolean }>(
      `/api/org/employees/${encodeURIComponent(employeeId)}`,
      { method: "DELETE" }
    );
  }

  async deleteCompany(companyId: string) {
    await this.request<{ deleted: boolean }>(
      `/api/org/companies/${encodeURIComponent(companyId)}`,
      { method: "DELETE" }
    );
  }

  searchBdLeads(query: string, limit = 10) {
    return this.request<BdLead[]>("/api/bd/search", {
      body: JSON.stringify({ query, limit }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  searchLeadsForCandidate(candidateId: string, limit = 10) {
    return this.request<BdLead[]>("/api/bd/search-for-candidate", {
      body: JSON.stringify({ candidate_id: candidateId, limit }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  updateLeadStatus(leadId: string, status: string, note?: string) {
    return this.request<BdLead>(`/api/bd/${encodeURIComponent(leadId)}/status`, {
      body: JSON.stringify({ status, note }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  runBdAgent(query: string, kind = "text", limit = 10) {
    return this.request<BdAgentQueryResult>("/api/bd/agent/query", {
      body: JSON.stringify({ query, kind, limit }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  async runBdAgentStream(
    query: string,
    kind = "text",
    limit = 10,
    onProgress?: (progress: BdProgress) => void
  ) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    headers.set("Content-Type", "application/json");
    const response = await this.fetcher(`${this.baseUrl}/api/bd/agent/query-stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ query, kind, limit })
    });
    if (!response.ok) throw new Error("检索失败");
    if (!response.body) throw new Error("浏览器不支持流式响应");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result: BdAgentQueryResult | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        const data = JSON.parse(raw) as
          | (BdProgress & { type: "progress" })
          | (BdAgentQueryResult & { type: "result" });
        if (data.type === "progress" && onProgress) {
          onProgress({ stage: data.stage, message: data.message });
        } else if (data.type === "result") {
          result = data as BdAgentQueryResult;
        }
      }
    }

    if (!result) throw new Error("未收到检索结果");
    return result;
  }

  followUpBdAgent(sessionId: string, query: string, limit = 10) {
    return this.request<BdAgentQueryResult>(
      `/api/bd/agent/session/${encodeURIComponent(sessionId)}/follow-up`,
      {
        body: JSON.stringify({ query, limit }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  indexStatus() {
    return this.request<IndexSyncStatus>("/api/search/index-status");
  }

  retryIndexSync() {
    return this.request<IndexSyncStatus>("/api/search/index-retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  }

  getResumeReview(revisionId: string) {
    return this.request<ResumeReview>(`/api/resumes/revisions/${encodeURIComponent(revisionId)}/review`);
  }

  approveResumeReview(revisionId: string, fields: Record<string, unknown>) {
    return this.request<ResumeReview>(`/api/resumes/revisions/${encodeURIComponent(revisionId)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields }),
    });
  }

  createCase(candidateId: string, jdId: string) {
    return this.request<CaseItem>("/api/case", {
      body: JSON.stringify({ candidate_id: candidateId, jd_id: jdId }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  listCases(candidateId?: string, jdId?: string) {
    const query = new URLSearchParams();
    if (candidateId) query.set("candidate_id", candidateId);
    if (jdId) query.set("jd_id", jdId);
    return this.request<CaseItem[]>(`/api/case${query.size ? `?${query}` : ""}`);
  }

  getCase(caseId: string) {
    return this.request<CaseDetail>(`/api/case/${encodeURIComponent(caseId)}`);
  }

  recommendCase(caseId: string, payload: CaseActionInput = {}) {
    return this.request<CaseEventItem>(`/api/case/${encodeURIComponent(caseId)}/recommend`, {
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  enterInterview(caseId: string, payload: CaseActionInput & { round_name?: string; round_type?: string } = {}) {
    return this.request<CaseEventItem>(`/api/case/${encodeURIComponent(caseId)}/enter-interview`, {
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  recordResult(caseId: string, caseRoundId: string, result: string, payload: CaseActionInput = {}) {
    return this.request<CaseEventItem>(`/api/case/${encodeURIComponent(caseId)}/result`, {
      body: JSON.stringify({ ...payload, case_round_id: caseRoundId, result }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  passAndAdvance(caseId: string, caseRoundId: string, payload: CaseActionInput & { next_round_name?: string } = {}) {
    return this.request<CaseEventItem[]>(`/api/case/${encodeURIComponent(caseId)}/pass-and-advance`, {
      body: JSON.stringify({ ...payload, case_round_id: caseRoundId }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  offerCase(caseId: string, payload: CaseActionInput = {}) {
    return this.request<CaseEventItem>(`/api/case/${encodeURIComponent(caseId)}/offer`, {
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  onboardCase(caseId: string, payload: CaseActionInput = {}) {
    return this.request<CaseEventItem>(`/api/case/${encodeURIComponent(caseId)}/onboard`, {
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  exitCase(caseId: string, result?: string, payload: CaseActionInput = {}) {
    return this.request<CaseEventItem>(`/api/case/${encodeURIComponent(caseId)}/exit`, {
      body: JSON.stringify({ ...payload, result: result ?? null }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  voidEvent(eventId: string, payload: CaseActionInput = {}) {
    return this.request<{ deleted: string }>(`/api/case/event/${encodeURIComponent(eventId)}/void`, {
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  dashboardOverview(filters?: DashboardQuery) {
    return this.request<DashboardOverview>(`/api/dashboard/overview${_dashQuery(filters)}`);
  }

  dashboardByJd(filters?: DashboardQuery) {
    return this.request<DashboardByJd[]>(`/api/dashboard/by-jd${_dashQuery(filters)}`);
  }

  dashboardTrend(granularity: string, filters?: DashboardQuery) {
    const base = `/api/dashboard/trend?granularity=${encodeURIComponent(granularity)}`;
    const extra = _dashQuery(filters);
    return this.request<DashboardTrendItem[]>(
      extra ? `${base}&${extra.slice(1)}` : base
    );
  }

  async dashboardExport(filters?: DashboardQuery) {
    await this.download(`/api/dashboard/export${_dashQuery(filters)}`, "dashboard.xlsx");
  }

  reverseMatch(candidateId: string) {
    return this.request<ReverseMatchItem[]>(
      `/api/match/reverse/${encodeURIComponent(candidateId)}`
    );
  }

  getCandidateContact(candidateId: string) {
    return this.request<CandidateContact>(
      `/api/resumes/candidate/${encodeURIComponent(candidateId)}/contact`
    );
  }

  updateCandidateContact(candidateId: string, input: { email: string | null; phone: string | null }) {
    return this.request<CandidateContact>(
      `/api/resumes/candidate/${encodeURIComponent(candidateId)}/contact`,
      {
        body: JSON.stringify(input),
        headers: { "Content-Type": "application/json" },
        method: "PUT"
      }
    );
  }

  updateCandidateField(candidateId: string, field: string, value: unknown) {
    return this.request<{ candidate_id: string; revision_id: string; field: string; value: unknown }>(
      `/api/resumes/candidate/${encodeURIComponent(candidateId)}/field`,
      {
        body: JSON.stringify({ field, value }),
        headers: { "Content-Type": "application/json" },
        method: "PUT"
      }
    );
  }

  listDeleted() {
    return this.request<DeletedItem[]>("/api/soft-delete/list");
  }

  softDelete(entityType: "candidate" | "jd", entityId: string) {
    return this.request<{ entity_type: string; entity_id: string; deleted: boolean }>(
      "/api/soft-delete",
      {
        body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  restoreDeleted(entityType: string, entityId: string) {
    return this.request<{ entity_type: string; entity_id: string; deleted: boolean }>(
      "/api/soft-delete/restore",
      {
        body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  applyCorrection(input: { entityType: string; entityId: string; fieldName: string; newValue: string | null; reason?: string }) {
    return this.request<CorrectionRecord>("/api/correction/apply", {
      body: JSON.stringify({
        entity_type: input.entityType,
        entity_id: input.entityId,
        field_name: input.fieldName,
        new_value: input.newValue,
        reason: input.reason
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  undoCorrection(correctionId: string) {
    return this.request<CorrectionRecord>(
      `/api/correction/${encodeURIComponent(correctionId)}/undo`,
      { method: "POST" }
    );
  }

  async exportMappingTree(snapshotId: string) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(
      `${this.baseUrl}/api/mapping/snapshots/${encodeURIComponent(snapshotId)}/export`,
      { headers }
    );
    if (!response.ok) {
      throw new Error("导出失败");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `mapping_${snapshotId}.xlsx`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async exportMappingTreePdf(snapshotId: string) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(
      `${this.baseUrl}/api/mapping/snapshots/${encodeURIComponent(snapshotId)}/export-pdf`,
      { headers }
    );
    if (!response.ok) {
      throw new Error("导出失败");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `mapping_${snapshotId}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  getSettings() {
    return this.request<AppSettings>("/api/settings");
  }

  updateSettings(values: Partial<AppSettings>) {
    return this.request<AppSettings>("/api/settings", {
      body: JSON.stringify(values),
      headers: { "Content-Type": "application/json" },
      method: "PUT"
    });
  }

  async exportMatchRun(runId: string) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(
      `${this.baseUrl}/api/match/run/${encodeURIComponent(runId)}/export`,
      { headers }
    );
    if (!response.ok) {
      throw new Error("导出失败");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `match_${runId}.xlsx`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  listBackups() {
    return this.request<BackupSnapshot[]>("/api/backup/snapshots");
  }

  createBackup(label = "") {
    return this.request<{ filename: string; path: string }>("/api/backup/snapshots", {
      body: JSON.stringify({ label }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  restoreBackup(filename: string) {
    return this.request<{ restored_from: string; safety_backup: string; restart_required?: boolean; status?: string }>(
      `/api/backup/restore/${encodeURIComponent(filename)}`,
      { method: "POST" }
    );
  }

  createPortableBackup(targetPath: string, passphrase: string) {
    return this.request<{ path: string; same_volume: boolean }>("/api/backup/portable", {
      body: JSON.stringify({ target_path: targetPath, passphrase }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  restorePortableBackup(backupPath: string, targetRoot: string, passphrase: string) {
    return this.request<{ target_root: string; files_restored: number; files_verified: number; ok: boolean }>(
      "/api/backup/portable/restore",
      {
        body: JSON.stringify({ backup_path: backupPath, target_root: targetRoot, passphrase }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      }
    );
  }

  listReminders() {
    return this.request<ReminderItem[]>("/api/reminders");
  }

  createReminder(input: CreateReminderInput) {
    return this.request<ReminderItem>("/api/reminders", {
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  dismissReminder(id: string) {
    return this.request<ReminderItem>(
      `/api/reminders/${encodeURIComponent(id)}/dismiss`,
      { method: "POST" }
    );
  }

  migrateData(targetRoot: string) {
    return this.request<MigrationReport>("/api/migration", {
      body: JSON.stringify({ target_root: targetRoot }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  async setDataRoot(path: string) {
    return invoke<string>("set_data_root", { path });
  }

  private async download(path: string, filename: string) {
    const headers = new Headers();
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(`${this.baseUrl}${path}`, { headers });
    if (!response.ok) throw new Error("导出失败");
    const blob = await response.blob();
    this.triggerDownload(blob, filename);
  }

  private triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    // 用户选择「另存为」目录时原生对话框可能停留较久，blob URL 需在此期间保持有效，
    // 过早 revoke 会导致浏览器报「无法下载，没有权限」。延长到 60 秒再释放。
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(`${this.baseUrl}${path}`, { ...init, headers });
    const payload = await response.json() as T | ApiError;
    if (!response.ok) {
      const apiError = payload as ApiError;
      throw new ApiRequestError(
        apiError.message ?? apiError.detail ?? "本机服务请求失败，请稍后重试",
        response.status,
      );
    }
    return payload as T;
  }
}


export async function createRuntimeApi(): Promise<RecruitmentApi> {
  let config: RuntimeConfig;
  try {
    config = await invoke<RuntimeConfig>("runtime_config");
  } catch {
    // Browser/Playwright fallback: reach a locally-run sidecar via env vars.
    config = {
      apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:43127",
      sessionToken: import.meta.env.VITE_SESSION_TOKEN ?? "0".repeat(64)
    };
  }
  return new ApiClient(config.apiBaseUrl, config.sessionToken);
}
