import { invoke } from "@tauri-apps/api/core";

import type {
  CandidateSearchResult,
  ImportedResume,
  RecruitmentApi,
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