import { invoke } from "@tauri-apps/api/core";

import type {
  AppSettings,
  BdLead,
  CandidateSearchResult,
  CaseItem,
  DashboardOverview,
  DeletedItem,
  DiagnosticsData,
  ImportedResume,
  MappingProject,
  MappingSnapshot,
  MappingTreeNode,
  RecruitmentApi,
  ReverseMatchItem,
  StageEventItem,
  TaskStatus
} from "../App";


export interface RuntimeConfig {
  apiBaseUrl: string;
  sessionToken: string;
}

interface ApiError {
  message?: string;
}


export class ApiClient implements RecruitmentApi {
  private readonly baseUrl: string;

  constructor(
    baseUrl: string,
    private readonly sessionToken: string,
    private readonly fetcher: typeof fetch = fetch
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

  getTask(taskId: string): Promise<TaskStatus> {
    return this.request<TaskStatus>(`/api/tasks/${encodeURIComponent(taskId)}`);
  }

  searchCandidates(query: string): Promise<CandidateSearchResult> {
    return this.request<CandidateSearchResult>("/api/search/candidates", {
      body: JSON.stringify({ query, limit: 50 }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
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

  health() {
    return this.request<Record<string, { status: string; message?: string }>>(
      "/health/checks"
    );
  }

  diagnostics() {
    return this.request<DiagnosticsData>("/api/diagnostics");
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

  createCase(candidateId: string, jdId: string) {
    return this.request<CaseItem>("/api/case", {
      body: JSON.stringify({ candidate_id: candidateId, jd_id: jdId }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  listCases(candidateId?: string) {
    const query = candidateId ? `?candidate_id=${encodeURIComponent(candidateId)}` : "";
    return this.request<CaseItem[]>(`/api/case${query}`);
  }

  advanceCase(caseId: string, stage: string, note?: string) {
    return this.request<CaseItem>(`/api/case/${encodeURIComponent(caseId)}/advance`, {
      body: JSON.stringify({ stage, note }),
      headers: { "Content-Type": "application/json" },
      method: "POST"
    });
  }

  undoCase(caseId: string) {
    return this.request<CaseItem>(`/api/case/${encodeURIComponent(caseId)}/undo`, {
      method: "POST"
    });
  }

  getCaseEvents(caseId: string) {
    return this.request<StageEventItem[]>(
      `/api/case/${encodeURIComponent(caseId)}/events`
    );
  }

  dashboardOverview() {
    return this.request<DashboardOverview>("/api/dashboard/overview");
  }

  dashboardByJd() {
    return this.request<{ jd_id: string; company: string; title: string; stage_counts: Record<string, number> }[]>(
      "/api/dashboard/by-jd"
    );
  }

  reverseMatch(candidateId: string) {
    return this.request<ReverseMatchItem[]>(
      `/api/match/reverse/${encodeURIComponent(candidateId)}`
    );
  }

  listDeleted() {
    return this.request<DeletedItem[]>("/api/soft-delete/list");
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

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("X-Kerui-Session", this.sessionToken);
    const response = await this.fetcher(`${this.baseUrl}${path}`, { ...init, headers });
    const payload = await response.json() as T | ApiError;
    if (!response.ok) {
      throw new Error((payload as ApiError).message ?? "本机服务请求失败，请稍后重试");
    }
    return payload as T;
  }
}


export async function createRuntimeApi(): Promise<RecruitmentApi> {
  const config = await invoke<RuntimeConfig>("runtime_config");
  return new ApiClient(config.apiBaseUrl, config.sessionToken);
}