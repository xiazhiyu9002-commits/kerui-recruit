import { FormEvent, Fragment, MouseEvent as ReactMouseEvent, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { invoke } from "@tauri-apps/api/core";

import "./styles.css";
import "./cases/workflow.css";
import { OrgMindMap } from "./org/OrgMindMap";
import { OrgDetailPanel } from "./org/OrgDetailPanel";
import { CaseDrawer } from "./cases/CaseDrawer";
import { ResumeReviewDrawer } from "./resumes/ResumeReviewDrawer";
import { DirectionEditor } from "./resumes/DirectionEditor";
import { IndexSyncPanel } from "./search/IndexSyncPanel";
import { RemindersPanel } from "./cases/RemindersPanel";
import { LoadingButton, LongTaskProgress } from "./components/Loading";
import type {
  DirectionEvaluationResponse,
  DirectionProfile,
  DirectionProfileDetailResponse,
  DirectionProfileResponse,
  DirectionTaxonomy,
} from "./resumes/direction-types";


async function openExternal(url: string) {
  try {
    await invoke("open_external", { url });
  } catch (error) {
    // 非 http/https 或系统浏览器打开失败时，静默回退为提示。
    console.warn("打开链接失败", error);
  }
}

async function copyLink(url: string) {
  try {
    await navigator.clipboard.writeText(url);
  } catch (error) {
    console.warn("复制链接失败", error);
  }
}


function exportSvgAsPng(svg: SVGSVGElement, filename: string) {
  const width = svg.width.baseVal.value || svg.viewBox.baseVal.width || 800;
  const height = svg.height.baseVal.value || svg.viewBox.baseVal.height || 400;
  const scale = 3; // 3 倍分辨率导出，保证文字清晰
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width * scale));
  clone.setAttribute("height", String(height * scale));
  const xml = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);
  const image = new Image();
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      URL.revokeObjectURL(url);
      return;
    }
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const downloadUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    }, "image/png");
  };
  image.onerror = () => URL.revokeObjectURL(url);
  image.src = url;
}


export interface ImportedResume {
  action: string;
  candidate_id: string | null;
  document_id: string | null;
  revision_id: string | null;
  blob_id: string | null;
  task_id: string | null;
  message?: string;
  conflict_candidate_ids?: string[];
  created_task?: boolean;
}

export interface TaskStatus {
  id: string;
  task_type: string;
  status: string;
  progress: number;
  error_message: string | null;
}

export type TaskAction = "cancel" | "retry" | "pause" | "resume";

export interface CandidateSearchItem {
  candidate_id: string;
  revision_id: string;
  name: string;
  phone: string | null;
  reasons: string[];
  parsed_data: ParsedResumeData | null;
  content: string;
  score: number;
  matched_channels: string[];
  total_years: number | null;
  highest_degree: string | null;
  location: string | null;
  result_id?: string | null;
  original_filename?: string | null;
  jd_primary_direction?: string | null;
  candidate_primary_direction?: string | null;
  candidate_direction_source?: string | null;
  direction_status?: string | null;
  direction_compatibility?: number | null;
  direction_explanation?: string | null;
  matched_skills?: string[];
  missing_skills?: string[];
}

export interface CandidateSearchResult {
  items: CandidateSearchItem[];
  degraded_reasons: string[];
  empty_reason?: string | null;
  status?: string | null;
}

export interface CandidateSearchFilters {
  min_years?: number; max_years?: number; highest_degree?: string;
  degree_exact?: boolean; locations?: string[]; preferred_locations?: string[];
  candidate_status?: string; max_qs_rank?: number; school_level?: string;
  exclude_skills?: string[];
  primary_role_family?: string;
  role_families?: string[];
  business_domains?: string[];
}

export interface SearchDirectionOption {
  code: string;
  label: string;
}

export interface SearchDirectionTaxonomy {
  role_families: SearchDirectionOption[];
  business_domains: SearchDirectionOption[];
}

export interface CandidateListItem {
  candidate_id: string;
  revision_id: string;
  display_name: string;
  total_years: number | null;
  highest_degree: string | null;
  location: string | null;
  status: string;
  revision_status: string | null;
  phone: string | null;
  original_filename: string | null;
  parsed_data: ParsedResumeData | null;
  error_code?: string | null;
  error_message?: string | null;
}

export interface CandidatePage {
  items: CandidateListItem[]; total: number; page: number; page_size: number; has_more: boolean;
}

export interface CandidateContact {
  email: string | null;
  phone: string | null;
  email_confidence: number | null;
  phone_confidence: number | null;
}

export interface ResumeRevision {
  revision_id: string;
  display_name: string | null;
  original_filename: string;
  status: string;
  is_current: boolean;
  created_at: string;
  parsed_data: ParsedResumeData | null;
}

export interface ParsedExperienceData {
  company: string | null;
  title: string | null;
  summary: string;
  industry?: string | null;
}

export interface ParsedProjectData {
  name: string | null;
  summary: string;
  tech_stack?: string | null;
  business_scene?: string | null;
}

export interface ParsedResumeData {
  name?: string | null;
  total_years?: number | null;
  highest_degree?: string | null;
  location?: string | null;
  preferred_location?: string | null;
  school?: string | null;
  school_level?: string | null;
  qs_rank?: number | null;
  graduation_year?: number | null;
  birth_year?: number | null;
  age?: number | null;
  industry?: string | null;
  current_industry?: string | null;
  longest_industry?: string | null;
  tech_direction?: string[];
  business_direction?: string[];
  skills?: string[];
  summary?: string;
  experiences?: ParsedExperienceData[];
  projects?: ParsedProjectData[];
  direction_profile?: DirectionProfile;
}

export interface IndexSyncStatus {
  pending: number;
  failed: number;
  items: { entity_type: string; entity_id: string; status: string; attempts: number; error: string | null }[];
  indexes?: { entity_type: string; compatible: boolean; error: string | null }[];
}

export interface ResumeReview {
  revision_id: string;
  status: string;
  review_required: boolean;
  raw_text: string | null;
  parsed_data: ParsedResumeData | null;
  review_data: ParsedResumeData | null;
  manual_overrides: Record<string, unknown> | null;
  extraction_diagnostics: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
}

export interface ImportedJd {
  jd_id: string;
  revision_id: string;
}

export interface JdParsedData {
  title?: string;
  company?: string;
  department?: string | null;
  location?: string | null;
  salary?: string | null;
  ai_category?: string | null;
  tech_direction?: string[];
  business_direction?: string[];
  industry?: string | null;
  min_years?: number | null;
  highest_degree?: string | null;
  qs_level?: string | null;
  core_duties?: string[];
  required_skills?: string[];
  plus_industry?: string[];
  plus_project_types?: string[];
  summary?: string;
  requirements?: { kind: string; label: string; value: string }[];
}

export interface JdListItem {
  jd_id: string;
  revision_id: string;
  company: string;
  title: string;
  status: string;
  jd_status: string;
  ai_category: string | null;
  location: string | null;
  min_years: number | null;
  parsed_data: JdParsedData | null;
  source_text: string | null;
}

export interface MatchRun {
  run_id: string | null;
  items: CandidateSearchItem[];
  status?: string;
  empty_reason?: string | null;
  degraded_reasons?: string[];
}

export interface BatchMatchResult {
  revision_id: string;
  run_id: string;
  items: CandidateSearchItem[];
}

export type MatchMarkStatus = "未处理" | "保留";

export interface MatchResultItem {
  result_id: string;
  candidate_id: string;
  name: string;
  score: number;
  status: MatchMarkStatus;
  total_years: number | null;
  highest_degree: string | null;
  location: string | null;
  direction_compatibility: number | null;
  jd_primary_direction: string | null;
  candidate_primary_direction: string | null;
  candidate_direction_source: string | null;
  direction_status: string | null;
  direction_explanation: string | null;
  matched_skills: string[];
  missing_skills: string[];
}

export interface MatchResultGroup {
  jd_id: string;
  revision_id: string;
  company: string;
  title: string;
  items: MatchResultItem[];
}

export type JdStatus = "OPEN" | "FILLED" | "CANCELLED";

export interface MatchCandidateItem {
  result_id: string;
  jd_id: string;
  revision_id: string;
  company: string;
  title: string;
  score: number;
  status: MatchMarkStatus;
  case_id: string | null;
  jd_status: string;
  ai_category: string | null;
  parsed_data: JdParsedData | null;
  source_text: string | null;
}

export type MatchDrawerState =
  | { mode: "candidates"; title: string; items: CandidateSearchItem[]; statuses: Record<string, MatchMarkStatus> }
  | { mode: "jds"; title: string; items: MatchCandidateItem[]; statuses: Record<string, MatchMarkStatus> };

export interface DiagnosticsData {
  sqlite_version: string;
  database_path: string;
  database_size_bytes: number;
  counts: Record<string, number>;
  pragmas: Record<string, string>;
}

export interface MappingProject {
  id: string;
  name: string;
  description: string | null;
}

export interface MappingSnapshot {
  id: string;
  label: string;
  is_current: boolean;
}

export interface MappingTreeNode {
  id: string;
  name: string;
  sort_order: number;
  children: MappingTreeNode[];
}

export interface OrgCompany {
  id: string;
  name: string;
}

export interface OrgDepartment {
  id: string;
  company_id: string;
  parent_id: string | null;
  name: string;
  leader_id: string | null;
  leader_report_to: string | null;
  team_size: number | null;
  business_direction: string | null;
  tech_stack: string | null;
  office_location: string | null;
  hc_status: string | null;
  hc_internal_note: string | null;
}

export interface OrgEmployee {
  id: string;
  company_id: string;
  department_id: string | null;
  candidate_id: string | null;
  candidate_name: string | null;
  current_revision_id: string | null;
  name: string;
  title: string | null;
  job_level: string | null;
  report_to: string | null;
  subordinate_count: number | null;
  tenure_years: number | null;
  business_module: string | null;
  status: string | null;
  intention: string | null;
  remark: string | null;
  contact: string | null;
  is_key: boolean;
}

export interface CreateOrgDepartmentInput {
  company_id: string;
  name: string;
  parent_id?: string | null;
  leader_id?: string | null;
  leader_report_to?: string | null;
  team_size?: number | null;
  business_direction?: string | null;
  tech_stack?: string | null;
  office_location?: string | null;
  hc_status?: string | null;
  hc_internal_note?: string | null;
}

export interface CreateOrgEmployeeInput {
  company_id: string;
  name: string;
  department_id?: string | null;
  title?: string | null;
  job_level?: string | null;
  report_to?: string | null;
  subordinate_count?: number | null;
  tenure_years?: number | null;
  business_module?: string | null;
  status?: string | null;
  intention?: string | null;
  remark?: string | null;
  contact?: string | null;
  is_key?: boolean;
}

export type UpdateOrgDepartmentInput = Partial<Omit<CreateOrgDepartmentInput, "company_id">>;
export type UpdateOrgEmployeeInput = Partial<Omit<CreateOrgEmployeeInput, "company_id">>;

export interface OrgTreeNode {
  id: string;
  kind: "company" | "department" | "employee";
  name: string;
  title: string | null;
  job_level: string | null;
  team_size: number | null;
  is_key: boolean;
  children: OrgTreeNode[];
}

export interface OrgImportEmployee {
  name: string;
  alias: string | null;
  title: string | null;
  job_level: string | null;
  report_to_name: string | null;
  department_name: string | null;
  subordinate_count: number | null;
  team_size: number | null;
  remark: string | null;
}

export interface OrgImportDepartment {
  name: string;
  parent_name: string | null;
  leader_name: string | null;
  team_size: number | null;
  business_direction: string | null;
}

export interface OrgImportDraft {
  company_name: string;
  departments: OrgImportDepartment[];
  employees: OrgImportEmployee[];
}

export interface OrgClarificationQuestion {
  question: string;
  field: string | null;
  hint: string | null;
}

export interface OrgParseResult {
  draft: OrgImportDraft | null;
  questions: OrgClarificationQuestion[];
}

export interface BindEmployeeResult {
  employee_id: string;
  matched: boolean;
  candidate_id: string | null;
  candidate_name: string | null;
  name_mismatch: boolean;
  current_revision_id?: string | null;
}

export interface BdLead {
  id: string;
  source: string;
  company_name: string;
  job_title: string | null;
  raw_snippet: string | null;
  url: string | null;
  status: string;
}

export interface BdEvidenceItem {
  claim: string | null;
  quote: string | null;
  source_url: string | null;
}

export interface BdPoolCandidate {
  candidate_id: string;
  name: string;
  phone: string | null;
  revision_id: string;
}

export interface BdAgentLead {
  id: string;
  source: string;
  company_name: string;
  job_title: string | null;
  posted_time: string | null;
  salary_range: string | null;
  level: string | null;
  requirements: string[];
  summary: string | null;
  url: string | null;
  status: string;
  confidence: number | null;
  is_hiring: boolean | null;
  evidence: BdEvidenceItem[];
}

export interface BdAgentQueryResult {
  session_id: string;
  leads: BdAgentLead[];
}

export interface BdProgress {
  stage: string;
  message: string;
}

export interface CaseItem {
  id: string;
  candidate_id: string;
  jd_id: string;
  stage: string;
  note: string | null;
  candidate_name?: string | null;
  company?: string | null;
  jd_title?: string | null;
  can_advance?: boolean;
  blocked_reason?: string | null;
}

export interface CaseActionInput {
  occurred_at?: string;
  note?: string;
  idempotency_key?: string;
}

export interface DashboardFilters {
  company?: string;
  jd_id?: string;
  date_from?: string;
  date_to?: string;
}

export interface CaseRoundItem {
  id: string;
  round_no: number;
  round_name: string;
  round_type: string | null;
  skipped: boolean;
}

export interface CaseEventItem {
  id: string;
  event_type: string;
  case_round_id: string | null;
  round_name: string | null;
  occurred_at: string;
  recorded_at: string;
  result: string | null;
  note: string | null;
  status: string;
}

export interface CaseDetail extends CaseItem {
  rounds: CaseRoundItem[];
  events: CaseEventItem[];
  process_rounds?: { round_no: number; round_name: string; round_type?: string | null }[];
  template_version?: number | null;
}

export interface DashboardOverview {
  recommendation_total: number;
  offer_total: number;
  active_offer_total: number;
  onboarded_total: number;
  candidate_total: number;
  monthly_new_candidates: { month: string; count: number }[];
}

export interface DashboardRound {
  round_key?: string;
  round_no: number;
  round_name: string;
  entered: number;
  judged: number;
  passed: number;
  failed: number;
  pending: number;
  skipped: number;
  exited: number;
  cancelled: number;
  pass_rate: number | null;
}

export interface DashboardByJd {
  jd_id: string;
  company: string;
  title: string;
  recommendation_total: number;
  offer_total: number;
  final_offer_rate: number | null;
  rounds: DashboardRound[];
}

export interface DashboardTrendItem {
  period: string;
  recommendation: number;
  offer: number;
}

export interface ReverseMatchItem {
  jd_id: string;
  revision_id: string;
  company: string;
  title: string;
  score: number;
}

export interface DeletedItem {
  entity_type: string;
  entity_id: string;
  label: string;
  deleted_at: string | null;
}

export interface CorrectionRecord {
  correction_id: string;
  entity_type: string;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  reverted: boolean;
}

export interface VendorPreset {
  key: string;
  label: string;
  base_url: string;
  text_model?: string;
  vision_model?: string;
  embedding_model?: string;
  rerank_model?: string;
}

export interface AppSettings {
  deepseek_api_key?: string;
  deepseek_base_url?: string;
  siliconflow_api_key?: string;
  siliconflow_base_url?: string;
  siliconflow_embedding_model?: string;
  siliconflow_reranker_model?: string;
  tavily_api_key?: string;
  tavily_base_url?: string;
  serpapi_api_key?: string;
  serpapi_base_url?: string;
  text_base_url?: string;
  text_model?: string;
  text_api_key?: string;
  vision_base_url?: string;
  vision_model?: string;
  vision_api_key?: string;
  embedding_base_url?: string;
  embedding_model?: string;
  embedding_api_key?: string;
  rerank_base_url?: string;
  rerank_model?: string;
  rerank_api_key?: string;
  imap_host?: string;
  imap_account?: string;
  imap_auth_code?: string;
  imap_whitelist?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_account?: string;
  smtp_auth_code?: string;
  smtp_ssl?: boolean;
  reminder_to?: string;
}

export interface BackupSnapshot {
  filename: string;
  path: string;
  size_bytes: string;
  created: string;
}

export interface ReminderItem {
  id: string;
  title: string;
  note: string | null;
  remind_at: string;
  dismissed: boolean;
  dismissed_at: string | null;
  case_id?: string | null;
  paused_by_workflow?: boolean;
}

export interface CreateReminderInput {
  title: string;
  remind_at: string;
  note?: string;
  case_id?: string | null;
}

export interface MigrationReport {
  target_root: string;
  files_copied: number;
  files_verified: number;
  candidate_count: number;
  ok: boolean;
}

export interface OnboardingStatus {
  data_root: string;
  llm_enabled: boolean;
  search_enabled: boolean;
  bd_search_enabled: boolean;
  mail_enabled: boolean;
  smtp_enabled: boolean;
  health: Record<string, { status: string; message?: string }>;
}

export interface ProviderCheck {
  name: string;
  ok: boolean;
  message: string;
}

export interface RecruitmentApi {
  importResume(file: File): Promise<ImportedResume>;
  importFolder(directory: string): Promise<{ imported: ImportedResume[]; skipped: string[]; errors: string[] }>;
  getTask(taskId: string): Promise<TaskStatus>;
  listTasks(): Promise<TaskStatus[]>;
  getTaskStatusBatch(taskIds: string[]): Promise<{ found: TaskStatus[]; missing_ids: string[] }>;
  controlTask(taskId: string, action: TaskAction): Promise<TaskStatus>;
  listResumeRevisions(candidateId: string): Promise<ResumeRevision[]>;
  switchResumeRevision(revisionId: string): Promise<ResumeRevision>;
  reparseResume(revisionId: string, forceOcr: boolean): Promise<{ revision_id: string; task_id: string }>;
  getResumeReview(revisionId: string): Promise<ResumeReview>;
  approveResumeReview(revisionId: string, fields: Record<string, unknown>): Promise<ResumeReview>;
  indexStatus(): Promise<IndexSyncStatus>;
  retryIndexSync(): Promise<IndexSyncStatus>;
  downloadResume(revisionId: string, filename: string): Promise<void>;
  previewResume(revisionId: string): Promise<string>;
  searchCandidates(query: string, filters?: CandidateSearchFilters): Promise<CandidateSearchResult>;
  listCandidates(): Promise<CandidateListItem[]>;
  listCandidatesPage?(page: number, pageSize: number): Promise<CandidatePage>;
  importJd(input: { company: string; title: string; sourceText: string }): Promise<ImportedJd>;
  importJdFile(file: File, company: string, title: string): Promise<ImportedJd>;
  importJdBatch(sourceText: string): Promise<{ imported: ImportedJd[] }>;
  importJdBatchFile(file: File): Promise<{ imported: ImportedJd[] }>;
  listJds(): Promise<JdListItem[]>;
  updateJdStatus(jdId: string, status: string): Promise<{ jd_id: string; status: string }>;
  updateJdField(jdId: string, field: string, value: unknown): Promise<{ jd_id: string; revision_id: string; field: string; value: unknown }>;
  matchJd(revisionId: string, limit?: number): Promise<MatchRun>;
  matchBatch(revisionIds: string[], limit?: number): Promise<{ results: BatchMatchResult[] }>;
  markMatchResult(resultId: string, status: MatchMarkStatus): Promise<{ result_id: string; status: MatchMarkStatus }>;
  listMatchResults(): Promise<{ groups: MatchResultGroup[] }>;
  listMatchResultsForCandidate(candidateId: string): Promise<MatchCandidateItem[]>;
  matchCandidate(candidateId: string): Promise<MatchCandidateItem[]>;
  createCaseFromMatchResult(resultId: string): Promise<{ case_id: string; result_id: string; status: string }>;
  exportMatchJd(revisionId: string): Promise<void>;
  health(): Promise<Record<string, { status: string; message?: string }>>;
  diagnostics(): Promise<DiagnosticsData>;
  exportDiagnostics(): Promise<void>;
  listMappingProjects(): Promise<MappingProject[]>;
  createMappingProject(name: string, description?: string): Promise<MappingProject>;
  buildMappingTree(projectId: string, text: string, label?: string): Promise<MappingSnapshot>;
  listMappingSnapshots(projectId: string): Promise<MappingSnapshot[]>;
  getMappingTree(snapshotId: string): Promise<MappingTreeNode[]>;
  searchBdLeads(query: string, limit?: number): Promise<BdLead[]>;
  searchLeadsForCandidate(candidateId: string, limit?: number): Promise<BdLead[]>;
  updateLeadStatus(leadId: string, status: string, note?: string): Promise<BdLead>;
  runBdAgent(query: string, kind?: string, limit?: number): Promise<BdAgentQueryResult>;
  runBdAgentStream(query: string, kind?: string, limit?: number, onProgress?: (progress: BdProgress) => void): Promise<BdAgentQueryResult>;
  followUpBdAgent(sessionId: string, query: string, limit?: number): Promise<BdAgentQueryResult>;
  lookupPool(leadId: string): Promise<BdPoolCandidate[]>;
  createCase(candidateId: string, jdId: string): Promise<CaseItem>;
  listCases(candidateId?: string, jdId?: string): Promise<CaseItem[]>;
  getCase(caseId: string): Promise<CaseDetail>;
  recommendCase(caseId: string, payload?: CaseActionInput): Promise<CaseEventItem>;
  enterInterview(caseId: string, payload?: CaseActionInput & { round_name?: string; round_type?: string }): Promise<CaseEventItem>;
  recordResult(caseId: string, caseRoundId: string, result: string, payload?: CaseActionInput): Promise<CaseEventItem>;
  passAndAdvance(caseId: string, caseRoundId: string, payload?: CaseActionInput & { next_round_name?: string }): Promise<CaseEventItem[]>;
  offerCase(caseId: string, payload?: CaseActionInput): Promise<CaseEventItem>;
  onboardCase(caseId: string, payload?: CaseActionInput): Promise<CaseEventItem>;
  exitCase(caseId: string, result?: string, payload?: CaseActionInput): Promise<CaseEventItem>;
  voidEvent(eventId: string, payload?: CaseActionInput): Promise<{ deleted: string }>;
  dashboardOverview(filters?: { company?: string; jd_id?: string; date_from?: string; date_to?: string }): Promise<DashboardOverview>;
  dashboardByJd(filters?: { company?: string; jd_id?: string; date_from?: string; date_to?: string }): Promise<DashboardByJd[]>;
  dashboardTrend(granularity: string, filters?: { company?: string; jd_id?: string; date_from?: string; date_to?: string }): Promise<DashboardTrendItem[]>;
  dashboardExport(filters?: { company?: string; jd_id?: string; date_from?: string; date_to?: string }): Promise<void>;
  reverseMatch(candidateId: string): Promise<ReverseMatchItem[]>;
  getCandidateContact(candidateId: string): Promise<CandidateContact>;
  updateCandidateContact(candidateId: string, input: { email: string | null; phone: string | null }): Promise<CandidateContact>;
  updateCandidateField(candidateId: string, field: string, value: unknown): Promise<{ candidate_id: string; revision_id: string; field: string; value: unknown }>;
  listDeleted(): Promise<DeletedItem[]>;
  softDelete(entityType: "candidate" | "jd", entityId: string): Promise<{ entity_type: string; entity_id: string; deleted: boolean }>;
  restoreDeleted(entityType: string, entityId: string): Promise<{ entity_type: string; entity_id: string; deleted: boolean }>;
  applyCorrection(input: { entityType: string; entityId: string; fieldName: string; newValue: string | null; reason?: string }): Promise<CorrectionRecord>;
  undoCorrection(correctionId: string): Promise<CorrectionRecord>;
  exportMappingTree(snapshotId: string): Promise<void>;
  exportMappingTreePdf(snapshotId: string): Promise<void>;
  getDirections(): Promise<SearchDirectionTaxonomy>;
  getSettings(): Promise<AppSettings>;
  getVendors(): Promise<VendorPreset[]>;
  updateSettings(values: Partial<AppSettings>): Promise<AppSettings>;
  testMail(): Promise<{ imap: { ok: boolean; message: string }; smtp: { ok: boolean; message: string } }>;
  syncMail(): Promise<{ ingested: number; revision_ids: string[] }>;
  mailStatus(): Promise<{ configured: boolean; last_uid: number }>;
  getDirectionTaxonomy(): Promise<DirectionTaxonomy>;
  getResumeDirectionProfile(revisionId: string): Promise<DirectionProfileDetailResponse>;
  reevaluateResumeDirection(revisionId: string, expectedProfileVersion?: string): Promise<DirectionEvaluationResponse>;
  saveResumeDirectionProfile(revisionId: string, directionProfile: DirectionProfile, expectedProfileVersion?: string, reason?: string): Promise<DirectionProfileResponse>;
  getJdDirectionProfile(revisionId: string): Promise<DirectionProfileDetailResponse>;
  reevaluateJdDirection(revisionId: string, expectedProfileVersion?: string): Promise<DirectionEvaluationResponse>;
  saveJdDirectionProfile(revisionId: string, directionProfile: DirectionProfile, expectedProfileVersion?: string, reason?: string): Promise<DirectionProfileResponse>;
  exportMatchRun(runId: string): Promise<void>;
  listBackups(): Promise<BackupSnapshot[]>;
  createBackup(label?: string): Promise<{ filename: string; path: string }>;
  restoreBackup(filename: string): Promise<{ restored_from: string; safety_backup: string; restart_required?: boolean; status?: string }>;
  createPortableBackup(targetPath: string, passphrase: string): Promise<{ path: string; same_volume: boolean }>;
  restorePortableBackup(backupPath: string, targetRoot: string, passphrase: string): Promise<{ target_root: string; files_restored: number; files_verified: number; ok: boolean }>;
  listReminders(): Promise<ReminderItem[]>;
  createReminder(input: CreateReminderInput): Promise<ReminderItem>;
  dismissReminder(id: string): Promise<ReminderItem>;
  migrateData(targetRoot: string): Promise<MigrationReport>;
  setDataRoot(path: string): Promise<string>;
  onboardingStatus(): Promise<OnboardingStatus>;
  testProviders(): Promise<ProviderCheck[]>;
  listCompanies(): Promise<OrgCompany[]>;
  createCompany(name: string): Promise<OrgCompany>;
  updateCompany(companyId: string, name: string): Promise<OrgCompany>;
  listDepartments(companyId: string): Promise<OrgDepartment[]>;
  createDepartment(input: CreateOrgDepartmentInput): Promise<OrgDepartment>;
  listEmployees(companyId: string): Promise<OrgEmployee[]>;
  createEmployee(input: CreateOrgEmployeeInput): Promise<OrgEmployee>;
  getOrgTree(companyId: string): Promise<OrgTreeNode>;
  exportOrgInternal(companyId: string): Promise<void>;
  exportOrgClient(companyId: string): Promise<void>;
  exportOrgArchPdf(companyId: string): Promise<void>;
  updateDepartment(departmentId: string, changes: UpdateOrgDepartmentInput): Promise<OrgDepartment>;
  deleteDepartment(departmentId: string): Promise<void>;
  updateEmployee(employeeId: string, changes: UpdateOrgEmployeeInput): Promise<OrgEmployee>;
  deleteEmployee(employeeId: string): Promise<void>;
  deleteCompany(companyId: string): Promise<void>;
  parseOrgImport(text: string): Promise<OrgParseResult>;
  parseOrgWord(file: File): Promise<OrgParseResult>;
  answerOrgImport(text: string, answers: string[]): Promise<OrgParseResult>;
  commitOrgImport(companyId: string, draft: OrgImportDraft, sourceText?: string | null): Promise<{ departments: number; employees: number }>;
  reviseOrgImport(draft: OrgImportDraft, instruction: string): Promise<OrgImportDraft>;
  getCompanySource(companyId: string): Promise<{ company_id: string; source_text: string | null }>;
  bindEmployee(employeeId: string, phone: string, name?: string | null): Promise<BindEmployeeResult>;
}


const navigation = ["人才库", "JD 管理", "数据看板", "Mapping", "BD 助手", "设置", "流程中"];

const CANDIDATE_PAGE_SIZE = 20;

function reviewActionLabel(revisionStatus: string | null | undefined, reviewError: string | null | undefined): string {
  if (revisionStatus === "FAILED" || reviewError) return "解析异常·修正";
  if (revisionStatus === "PENDING_REVIEW") return "待复核·确认入库";
  return "解析与方向";
}

function pageWindow(current: number, totalPages: number): (number | "…")[] {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
  const pages: (number | "…")[] = [1];
  if (current > 3) pages.push("…");
  for (let i = Math.max(2, current - 1); i <= Math.min(totalPages - 1, current + 1); i++) pages.push(i);
  if (current < totalPages - 2) pages.push("…");
  pages.push(totalPages);
  return pages;
}

const STAGES = [
  "待评估", "待联系", "已联系", "有意向", "已推荐",
  "初试", "复试", "终试", "Offer", "入职",
  "客户拒绝", "候选人拒绝", "暂缓", "岗位关闭"
];

const JD_STATUS_OPTIONS: { value: JdStatus; label: string }[] = [
  { value: "OPEN", label: "开放" },
  { value: "FILLED", label: "招满" },
  { value: "CANCELLED", label: "已取消" },
];

const HEALTH_LABELS: Record<string, string> = {
  database: "数据库",
  blob_store: "原件库",
  search: "检索引擎",
  disk: "磁盘空间"
};

const PROVIDER_LABELS: Record<string, string> = {
  llm: "大模型",
  embedding: "向量模型",
  reranker: "重排模型",
  web_search: "网页搜索"
};


function sortLeadsByConfidence(leads: BdAgentLead[]): BdAgentLead[] {
  return [...leads].sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1));
}


function filterOrgTree(
  root: OrgTreeNode,
  search: string,
  filterKind: string,
  filterKey: boolean,
): OrgTreeNode | null {
  const q = search.trim().toLowerCase();
  if (!q && !filterKind && !filterKey) return root;

  function matches(node: OrgTreeNode): boolean {
    if (filterKind && node.kind !== "company" && node.kind !== filterKind) return false;
    if (filterKey && node.kind === "employee" && !node.is_key) return false;
    if (!q) return true;
    const hay = [node.name, node.title, node.job_level].filter(Boolean).join(" ").toLowerCase();
    return hay.includes(q);
  }

  function walk(node: OrgTreeNode): OrgTreeNode | null {
    const children = node.children
      .map(walk)
      .filter((child): child is OrgTreeNode => child !== null);
    if (matches(node) || children.length > 0) {
      return { ...node, children };
    }
    return null;
  }

  return walk(root);
}

function taskLabel(task: TaskStatus): string {
  if (task.status === "SUCCESS") return "解析完成";
  if (task.status === "FAILED" || task.status === "DEAD_LETTER") return "解析失败";
  if (task.status === "PAUSED") return "已暂停";
  if (task.status === "CANCELLED") return "已取消";
  return `解析中 ${task.progress}%`;
}

function jdAiLabel(category: string | null): string {
  if (category === "CORE_AI") return "AI";
  if (category === "AI_RELATED") return "AI相关";
  if (category === "NON_AI") return "非AI";
  return "—";
}

function jdRequirementLabel(parsed: JdParsedData | null): string {
  if (!parsed) return "—";
  const tech = parsed.tech_direction?.join("、") || "";
  const biz = parsed.business_direction?.join("、") || "";
  return [tech ? `技术：${tech}` : "", biz ? `业务：${biz}` : ""].filter(Boolean).join("；") || "—";
}

function directionLabel(profile: DirectionProfile | null | undefined): string {
  if (!profile) return "—";
  const primary = profile.role_families.find((r) => r.is_primary);
  if (!primary) return profile.status === "UNKNOWN" ? "未设置" : "—";
  const source = primary.source === "USER" ? "人工" : primary.source === "RULE" ? "规则" : "AI";
  if (source === "AI") return primary.label;
  return `${primary.label}（${source}）`;
}

function qsBand(rank: number | null | undefined): string {
  if (rank == null) return "";
  if (rank <= 50) return "前50";
  if (rank <= 100) return "前100";
  if (rank <= 150) return "前150";
  if (rank <= 200) return "前200";
  if (rank <= 300) return "前300";
  return "前300之后";
}

function schoolLevelLabel(level: string | null | undefined): string {
  const map: Record<string, string> = {
    "985": "985",
    "211": "211",
    "双一流": "双一流",
    "普通": "普通",
    "海外": "海外",
  };
  return level ? (map[level] ?? level) : "";
}

function degreeLabel(degree: string | null | undefined): string {
  const map: Record<string, string> = {
    "博士": "博士", "硕士": "硕士", "本科": "本科", "大专": "大专",
    "DOCTORATE": "博士", "MASTER": "硕士", "BACHELOR": "本科", "ASSOCIATE": "大专",
  };
  return degree ? (map[degree] ?? degree) : "";
}

function eduLabel(p: ParsedResumeData | null | undefined): string {
  if (!p) return "";
  const year = p.graduation_year ? String(p.graduation_year).slice(-2) : "";
  const levelMap: Record<string, string> = { "985": "9", "211": "2", "双一流": "双", "普通": "普", "海外": "海" };
  const level = p.school_level ? (levelMap[p.school_level] ?? p.school_level) : "";
  const degreeMap: Record<string, string> = {
    "博士": "博", "硕士": "硕", "本科": "本", "大专": "专",
    "DOCTORATE": "博", "MASTER": "硕", "BACHELOR": "本", "ASSOCIATE": "专",
  };
  const degree = p.highest_degree ? (degreeMap[p.highest_degree] ?? p.highest_degree) : "";
  const qs = qsBand(p.qs_rank);
  const core = [year, level + degree].filter(Boolean).join("-");
  return qs ? `${core}+qs${qs}` : core;
}

function splitList(text: string): string[] {
  return text.split(/[、,，/]/).map((s) => s.trim()).filter(Boolean);
}

function copyToClipboard(text: string) {
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text: string) {
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand("copy");
  } catch {
    // ignore
  }
  document.body.removeChild(area);
}

function patchParsed(parsed: ParsedResumeData | null, field: string, value: unknown): ParsedResumeData {
  const next = { ...(parsed ?? {}) } as ParsedResumeData;
  (next as Record<string, unknown>)[field] = value;
  return next;
}

function patchCandidate(item: CandidateListItem, field: string, value: unknown): CandidateListItem {
  const next: CandidateListItem = { ...item, parsed_data: patchParsed(item.parsed_data, field, value) };
  if (field === "name" && value) next.display_name = value as string;
  if (field === "phone") next.phone = (value as string) || null;
  return next;
}

function patchSearchItem(item: CandidateSearchItem, field: string, value: unknown): CandidateSearchItem {
  const next: CandidateSearchItem = { ...item, parsed_data: patchParsed(item.parsed_data, field, value) };
  if (field === "name") next.name = (value as string) || "";
  if (field === "phone") next.phone = (value as string) || null;
  if (field === "total_years") next.total_years = typeof value === "number" ? value : null;
  if (field === "highest_degree") next.highest_degree = (value as string) || null;
  if (field === "location") next.location = (value as string) || null;
  return next;
}

function EditableCell({
  value,
  onSave,
}: {
  value: string;
  onSave: (next: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  async function save() {
    if (draft === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } catch {
      // keep editing so the user can retry
    } finally {
      setSaving(false);
    }
  }

  function onContextMenu(event: ReactMouseEvent) {
    event.preventDefault();
    copyToClipboard(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 800);
  }

  if (editing) {
    return (
      <input
        autoFocus
        className="editable-input"
        value={draft}
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void save()}
        onKeyDown={(event) => {
          if (event.key === "Enter") void save();
          if (event.key === "Escape") setEditing(false);
        }}
      />
    );
  }

  return (
    <span
      className={copied ? "editable-cell copied" : "editable-cell"}
      title="双击修改，右键复制"
      onContextMenu={onContextMenu}
      onDoubleClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {value || "—"}
    </span>
  );
}


function renderTrendChart(data: DashboardTrendItem[], ref: RefObject<SVGSVGElement | null>) {
  const width = 720;
  const height = 320;
  const padLeft = 48;
  const padBottom = 48;
  const padTop = 22;
  const padRight = 16;
  const chartWidth = width - padLeft - padRight;
  const chartHeight = height - padTop - padBottom;
  const maxValue = Math.max(1, ...data.map((d) => Math.max(d.recommendation, d.offer)));
  const groupWidth = data.length ? chartWidth / data.length : chartWidth;
  const barWidth = Math.min(40, Math.max(8, groupWidth * 0.3));

  return (
    <svg ref={ref} className="chart-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="推荐量与 offer 量趋势">
      {data.map((d, i) => {
        const cx = padLeft + groupWidth * i + groupWidth / 2;
        const baseline = padTop + chartHeight;
        const recHeight = (d.recommendation / maxValue) * chartHeight;
        const offerHeight = (d.offer / maxValue) * chartHeight;
        return (
          <g key={d.period}>
            <rect x={cx - barWidth - 2} y={baseline - recHeight} width={barWidth} height={recHeight} rx="3" fill="#3b82f6" />
            <rect x={cx + 2} y={baseline - offerHeight} width={barWidth} height={offerHeight} rx="3" fill="#10b981" />
            <text x={cx - barWidth / 2 - 2} y={baseline - recHeight - 4} textAnchor="middle" fontSize="9" fill="#3b82f6">{d.recommendation}</text>
            <text x={cx + barWidth / 2 + 2} y={baseline - offerHeight - 4} textAnchor="middle" fontSize="9" fill="#10b981">{d.offer}</text>
            <text x={cx} y={baseline + 16} textAnchor="middle" fontSize="10" fill="#64748b">{d.period}</text>
          </g>
        );
      })}
      <line x1={padLeft} y1={padTop} x2={padLeft} y2={padTop + chartHeight} stroke="#cbd5e1" />
      <line x1={padLeft} y1={padTop + chartHeight} x2={width - padRight} y2={padTop + chartHeight} stroke="#cbd5e1" />
      <text x={padLeft - 6} y={padTop + 4} textAnchor="end" fontSize="10" fill="#64748b">{maxValue}</text>
      <text x={padLeft - 6} y={padTop + chartHeight} textAnchor="end" fontSize="10" fill="#64748b">0</text>
      <g transform={`translate(${padLeft + 8}, ${height - 16})`}>
        <rect width="10" height="10" fill="#3b82f6" />
        <text x="14" y="9" fontSize="10" fill="#334155">推荐量</text>
        <rect x="64" width="10" height="10" fill="#10b981" />
        <text x="78" y="9" fontSize="10" fill="#334155">offer 量</text>
      </g>
    </svg>
  );
}


function renderPassRateChart(data: DashboardByJd[], ref: RefObject<SVGSVGElement | null>) {
  const labelWidth = 150;
  const barWidth = 360;
  const valueWidth = 70;
  const rowHeight = 24;
  const titleHeight = 22;
  const groupGap = 20;
  const width = labelWidth + barWidth + valueWidth + 24;

  const groups = data
    .filter((jd) => jd.rounds.length > 0)
    .map((jd) => ({
      title: `${jd.company} · ${jd.title}`,
      rows: [
        ...jd.rounds.map((r) => ({ label: r.round_name, value: r.pass_rate, highlight: false })),
        { label: "最终 offer 率", value: jd.final_offer_rate, highlight: true },
      ],
    }));

  let height = 12;
  const layouts = groups.map((g) => {
    const start = height;
    height += titleHeight + g.rows.length * rowHeight + groupGap;
    return { ...g, start };
  });
  height = Math.max(height, 40);

  return (
    <svg ref={ref} className="chart-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="每岗位每轮通过率">
      {layouts.map((g, gi) => (
        <g key={gi}>
          <text x={8} y={g.start + 14} fontSize="12" fontWeight="bold" fill="#0f172a">{g.title}</text>
          {g.rows.map((row, ri) => {
            const ry = g.start + titleHeight + ri * rowHeight;
            const pct = Math.min(1, Math.max(0, row.value ?? 0));
            return (
              <g key={ri}>
                <text x={8} y={ry + 16} fontSize="11" fill="#334155">{row.label}</text>
                <rect x={labelWidth} y={ry + 4} width={barWidth} height={16} rx={3} fill="#e2e8f0" />
                <rect x={labelWidth} y={ry + 4} width={pct * barWidth} height={16} rx={3} fill={row.highlight ? "#f59e0b" : "#6366f1"} />
                <text x={labelWidth + barWidth + 8} y={ry + 16} fontSize="11" fill="#334155">
                  {row.value === null ? "—" : `${(row.value * 100).toFixed(0)}%`}
                </text>
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}


export function App({ api }: { api: RecruitmentApi }) {
  const [activeNav, setActiveNav] = useState(0);

  // 人才库
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CandidateSearchItem[]>([]);
  const [candidates, setCandidates] = useState<CandidateListItem[]>([]);
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const candidateTotalPages = Math.max(1, Math.ceil(candidateTotal / CANDIDATE_PAGE_SIZE));
  const candidateListRef = useRef<HTMLDivElement | null>(null);
  const [searchFilterDraft, setSearchFilterDraft] = useState({
    minYears: "", maxYears: "", degree: "", locations: "", preferredLocations: "",
    schoolLevel: "", maxQsRank: "", excludeSkills: "", direction: "", businessDomains: "",
  });
  const [directions, setDirections] = useState<SearchDirectionTaxonomy | null>(null);
  const [tasks, setTasks] = useState<TaskStatus[]>([]);
  const [folderPath, setFolderPath] = useState("");
  const [batchProgress, setBatchProgress] = useState<{ total: number; waiting: number; running: number; done: number; failed: number; percent: number } | null>(null);
  const [batchTaskIds, setBatchTaskIds] = useState<string[]>([]);
  const [batchTimedOut, setBatchTimedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewName, setPreviewName] = useState("");
  const [searching, setSearching] = useState(false);

  // JD 管理
  const [jdSource, setJdSource] = useState("");
  const [jdResult, setJdResult] = useState<ImportedJd[]>([]);
  const [jds, setJds] = useState<JdListItem[]>([]);
  const [openJdSource, setOpenJdSource] = useState<Record<string, boolean>>({});
  const [jdFilter, setJdFilter] = useState({ title: "", company: "", status: "" });
  const [jdDirectionRevisionId, setJdDirectionRevisionId] = useState<string | null>(null);
  const [candidateDirectionRevisionId, setCandidateDirectionRevisionId] = useState<string | null>(null);

  // 匹配结果抽屉
  const [matchDrawer, setMatchDrawer] = useState<MatchDrawerState | null>(null);
  const [matchCaseIds, setMatchCaseIds] = useState<Record<string, string>>({});
  const [creatingCase, setCreatingCase] = useState(false);
  const creatingCaseRef = useRef(false);

  // 设置 / 健康
  const [health, setHealth] = useState<Record<string, { status: string; message?: string }> | null>(null);

  // 数据看板
  const [diagnostics, setDiagnostics] = useState<DiagnosticsData | null>(null);

  // Mapping（组织架构）
  const [companies, setCompanies] = useState<OrgCompany[]>([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [departments, setDepartments] = useState<OrgDepartment[]>([]);
  const [employees, setEmployees] = useState<OrgEmployee[]>([]);
  const [orgTree, setOrgTree] = useState<OrgTreeNode | null>(null);
  const [selectedOrgNodeId, setSelectedOrgNodeId] = useState<string | null>(null);
  const [orgSearch, setOrgSearch] = useState("");
  const [orgFilterKind, setOrgFilterKind] = useState("");
  const [orgFilterKey, setOrgFilterKey] = useState(false);
  const [pendingEditId, setPendingEditId] = useState<string | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [orgImportText, setOrgImportText] = useState("");
  const [orgImportFileName, setOrgImportFileName] = useState("");
  const [orgImportDraft, setOrgImportDraft] = useState<OrgImportDraft | null>(null);
  const [orgImportQuestions, setOrgImportQuestions] = useState<OrgClarificationQuestion[]>([]);
  const [orgImportAnswers, setOrgImportAnswers] = useState<string[]>([]);
  const [orgImportBusy, setOrgImportBusy] = useState(false);
  const [orgImportMessage, setOrgImportMessage] = useState("");
  const [orgReviseInstruction, setOrgReviseInstruction] = useState("");
  const [orgSource, setOrgSource] = useState<{ companyId: string; text: string | null } | null>(null);
  const undoStackRef = useRef<{ undo: () => Promise<void>; redo: () => Promise<void> }[]>([]);
  const redoStackRef = useRef<{ undo: () => Promise<void>; redo: () => Promise<void> }[]>([]);

  // BD 助手
  const [bdQuery, setBdQuery] = useState("");
  const [bdFollowUp, setBdFollowUp] = useState("");
  const [bdSessionId, setBdSessionId] = useState<string | null>(null);
  const [bdLeads, setBdLeads] = useState<BdAgentLead[]>([]);
  const [bdLoading, setBdLoading] = useState(false);
  const [bdProgress, setBdProgress] = useState<BdProgress | null>(null);
  const [bdPoolByLead, setBdPoolByLead] = useState<Record<string, BdPoolCandidate[]>>({});
  const [bdPoolBusyId, setBdPoolBusyId] = useState<string | null>(null);
  const [collapsedPool, setCollapsedPool] = useState<Record<string, boolean>>({});

  // 看板
  const [dashboard, setDashboard] = useState<DashboardOverview | null>(null);
  const [dashboardByJdData, setDashboardByJdData] = useState<DashboardByJd[]>([]);
  const [dashboardTrend, setDashboardTrend] = useState<DashboardTrendItem[]>([]);
  const [trendGranularity, setTrendGranularity] = useState("month");
  const [dashboardDraft, setDashboardDraft] = useState<DashboardFilters>({});
  const [dashboardFilters, setDashboardFilters] = useState<DashboardFilters>({});
  const [dashboardBusy, setDashboardBusy] = useState(false);
  const dashboardRequest = useRef(0);
  const trendSvgRef = useRef<SVGSVGElement | null>(null);
  const passRateSvgRef = useRef<SVGSVGElement | null>(null);

  // 招聘流程面板
  const [caseDrawer, setCaseDrawer] = useState<CaseDetail | null>(null);
  const [resumeReview, setResumeReview] = useState<ResumeReview | null>(null);
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [caseJdFilter, setCaseJdFilter] = useState("");

  // 回收站
  const [deletedItems, setDeletedItems] = useState<DeletedItem[]>([]);

  // 设置
  const [settings, setSettings] = useState<AppSettings>({});
  const [vendors, setVendors] = useState<VendorPreset[]>([]);
  const [providerChecks, setProviderChecks] = useState<ProviderCheck[]>([]);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [mailTestResult, setMailTestResult] = useState<{ imap: { ok: boolean; message: string }; smtp: { ok: boolean; message: string } } | null>(null);
  const [mailSyncMessage, setMailSyncMessage] = useState("");
  const [mailStatus, setMailStatus] = useState<{ configured: boolean; last_uid: number } | null>(null);
  const [mailWhitelistInput, setMailWhitelistInput] = useState("");
  const [dataRootInput, setDataRootInput] = useState("");
  const [dataRootMessage, setDataRootMessage] = useState("");

  // 备份与恢复
  const [backups, setBackups] = useState<BackupSnapshot[]>([]);
  const [portableBackupPath, setPortableBackupPath] = useState("");
  const [portableRestorePath, setPortableRestorePath] = useState("");
  const [portableRestoreTarget, setPortableRestoreTarget] = useState("");
  const [portablePassphrase, setPortablePassphrase] = useState("");
  const [portableMessage, setPortableMessage] = useState("");
  const [backupBusy, setBackupBusy] = useState(false);
  const [portableBusy, setPortableBusy] = useState(false);

  // 数据迁移
  const [migrationTarget, setMigrationTarget] = useState("");
  const [migrationReport, setMigrationReport] = useState<MigrationReport | null>(null);
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationMessage, setMigrationMessage] = useState("");

  // 启动检查
  const [onboarding, setOnboarding] = useState<OnboardingStatus | null>(null);

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    setNotice(null);
    try {
      const filters: CandidateSearchFilters = {};
      if (searchFilterDraft.minYears !== "") filters.min_years = Number(searchFilterDraft.minYears);
      if (searchFilterDraft.maxYears !== "") filters.max_years = Number(searchFilterDraft.maxYears);
      if (searchFilterDraft.degree) filters.highest_degree = searchFilterDraft.degree;
      if (searchFilterDraft.locations.trim()) filters.locations = splitList(searchFilterDraft.locations);
      if (searchFilterDraft.preferredLocations.trim()) filters.preferred_locations = splitList(searchFilterDraft.preferredLocations);
      if (searchFilterDraft.schoolLevel.trim()) filters.school_level = searchFilterDraft.schoolLevel.trim();
      if (searchFilterDraft.maxQsRank !== "") filters.max_qs_rank = Number(searchFilterDraft.maxQsRank);
      if (searchFilterDraft.excludeSkills.trim()) filters.exclude_skills = splitList(searchFilterDraft.excludeSkills);
      if (searchFilterDraft.direction) filters.primary_role_family = searchFilterDraft.direction;
      if (searchFilterDraft.businessDomains.trim()) filters.business_domains = splitList(searchFilterDraft.businessDomains);
      const response = await api.searchCandidates(query.trim(), filters);
      setResults(response.items);
      if (response.empty_reason === "index_not_ready") {
        setNotice("索引尚未就绪，请先导入并解析简历。");
      } else if (response.empty_reason === "service_error") {
        setError("检索服务暂不可用，请稍后重试。");
      }
      if (response.degraded_reasons.length > 0) {
        setNotice(`部分检索能力降级：${response.degraded_reasons.join("、")}`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "搜索失败，请稍后重试");
    } finally {
      setSearching(false);
    }
  }

  function pollTask(taskId: string) {
    async function run() {
      const deadline = Date.now() + 30_000;
      while (Date.now() < deadline) {
        try {
          const task = await api.getTask(taskId);
          setTasks((current) => [task, ...current.filter((entry) => entry.id !== task.id)]);
          if (task.status === "SUCCESS" || task.status === "FAILED" || task.status === "DEAD_LETTER") {
            if (task.task_type === "PARSE_RESUME") await loadCandidates(1);
            return;
          }
        } catch {
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }
    void run();
  }

  async function loadTasks() {
    setError(null);
    try {
      setTasks(await api.listTasks());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务列表加载失败");
    }
  }

  async function loadCandidates(page = 1) {
    setError(null);
    try {
      if (api.listCandidatesPage) {
        const response = await api.listCandidatesPage(page, CANDIDATE_PAGE_SIZE);
        setCandidates(response.items);
        setCandidatePage(response.page);
        setCandidateTotal(response.total);
      } else {
        const items = await api.listCandidates();
        setCandidates(items);
        setCandidatePage(1);
        setCandidateTotal(items.length);
      }
      candidateListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选人列表加载失败");
    }
  }

  function scrollToCandidateListTop() {
    candidateListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function closeSearchResults() {
    setResults([]);
  }

  function resetSearchAndGoHome() {
    setQuery("");
    setResults([]);
    setSearchFilterDraft({ minYears: "", maxYears: "", degree: "", locations: "", preferredLocations: "", schoolLevel: "", maxQsRank: "", excludeSkills: "", direction: "", businessDomains: "" });
    void loadCandidates(1);
  }

  async function updateCandidateFieldValue(candidateId: string, field: string, value: unknown) {
    setError(null);
    try {
      await api.updateCandidateField(candidateId, field, value);
      setCandidates((list) => list.map((c) => (c.candidate_id === candidateId ? patchCandidate(c, field, value) : c)));
      setResults((list) => list.map((r) => (r.candidate_id === candidateId ? patchSearchItem(r, field, value) : r)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "修改失败");
      throw caught;
    }
  }

  async function forceReparse(revisionId: string) {
    setError(null);
    try {
      const result = await api.reparseResume(revisionId, true);
      const task = await api.getTask(result.task_id);
      setTasks((current) => [task, ...current.filter((entry) => entry.id !== task.id)]);
      pollTask(result.task_id);
      // 完成后刷新候选人列表，让新画像/状态回显。
      const deadline = Date.now() + 120_000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        try {
          const current = await api.getTask(result.task_id);
          if (current.status === "SUCCESS" || current.status === "FAILED" || current.status === "DEAD_LETTER") {
            if (current.status === "SUCCESS") await loadCandidates();
            break;
          }
        } catch {
          break;
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "强制 OCR 重新解析失败");
    }
  }

  async function loadJds() {
    setError(null);
    try {
      setJds(await api.listJds());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JD 列表加载失败");
    }
  }

  async function updateJdStatus(jdId: string, status: string) {
    setError(null);
    try {
      const updated = await api.updateJdStatus(jdId, status);
      setJds((current) =>
        current.map((jd) => (jd.jd_id === updated.jd_id ? { ...jd, jd_status: updated.status } : jd))
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "岗位状态更新失败");
    }
  }

  async function updateJdFieldValue(jdId: string, field: string, value: unknown) {
    setError(null);
    try {
      await api.updateJdField(jdId, field, value);
      await loadJds();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "岗位信息修改失败");
      throw caught;
    }
  }

  async function runJdMatch(jd: JdListItem) {
    setError(null);
    try {
      const result = await api.matchJd(jd.revision_id, 20);
      setMatchDrawer({
        mode: "candidates",
        title: jd.title || "岗位",
        items: result.items,
        statuses: {},
      });
      if (result.items.length === 0) {
        setError("该岗位未匹配到候选人：请确认候选人已导入且解析完成，并满足岗位的年限/学历等硬性要求。");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "匹配失败");
    }
  }

  async function runCandidateMatch(candidateId: string, name: string) {
    setError(null);
    try {
      const items = await api.matchCandidate(candidateId);
      setMatchDrawer({
        mode: "jds",
        title: name || "候选人",
        items,
        statuses: {},
      });
      if (items.length === 0) {
        setError("该候选人未匹配到岗位：请确认已有处于「开放」状态的岗位。");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "匹配失败");
    }
  }

  async function createCaseFromDrawer(resultId: string) {
    if (creatingCaseRef.current) return;
    const existingCaseId = matchCaseIds[resultId];
    if (existingCaseId) { await openCaseDrawer(existingCaseId); return; }
    creatingCaseRef.current = true;
    setCreatingCase(true);
    setError(null);
    try {
      const created = await api.createCaseFromMatchResult(resultId);
      setMatchCaseIds((current) => ({ ...current, [resultId]: created.case_id }));
      setMatchDrawer((current) => current ? {
        ...current,
        statuses: { ...current.statuses, [resultId]: "保留" },
      } : current);
      await openCaseDrawer(created.case_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建流程失败");
    } finally {
      creatingCaseRef.current = false;
      setCreatingCase(false);
    }
  }

  async function openCaseDrawer(caseId: string) {
    setError(null);
    try {
      setCaseDrawer(await api.getCase(caseId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载流程失败");
    }
  }

  async function loadCases(jdId = caseJdFilter) {
    setError(null);
    try {
      setCases(await api.listCases(undefined, jdId || undefined));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载流程列表失败");
    }
  }

  async function deleteJd(jd: JdListItem) {
    setError(null);
    try {
      await api.softDelete("jd", jd.jd_id);
      await loadJds();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除岗位失败");
    }
  }

  function toggleJdSource(revisionId: string) {
    setOpenJdSource((current) => ({ ...current, [revisionId]: !current[revisionId] }));
  }

  async function downloadResumeFile(revisionId: string, filename: string) {
    setError(null);
    try {
      await api.downloadResume(revisionId, filename);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "简历下载失败");
    }
  }

  async function previewResumeFile(revisionId: string, name?: string, filename?: string) {
    setError(null);
    setNotice(null);
    const file = filename || name || "";
    const suffix = file.slice(file.lastIndexOf(".")).toLowerCase();
    if (suffix === ".doc" || suffix === ".docx") {
      setNotice("该简历为 Word 版本，请下载后浏览");
      void downloadResumeFile(revisionId, filename || name || "简历");
      return;
    }
    try {
      const url = await api.previewResume(revisionId);
      setPreviewName(file || "简历预览");
      setPreviewUrl(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "简历预览失败");
    }
  }

  async function openResumeReview(revisionId: string) {
    setError(null);
    try { setResumeReview(await api.getResumeReview(revisionId)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "加载复核资料失败"); }
  }

  function renderCandidateTable(rows: { key: string; candidateId: string; name: string; phone: string | null; revisionId: string; filename: string; parsed: ParsedResumeData | null; revisionStatus?: string | null; reviewError?: string | null }[]) {
    return (
      <table className="candidate-table">
        <thead>
          <tr><th>姓名</th><th>学历</th><th>电话</th><th>行业</th><th>技术方向</th><th>业务方向</th><th>主方向</th><th className="candidate-actions-col">操作</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const p = r.parsed;
            const industry = p?.current_industry || p?.longest_industry
              ? `${p.current_industry ? `最近：${p.current_industry}` : ""}${p.longest_industry ? ` 最长：${p.longest_industry}` : ""}`
              : "—";
            const techValue = p?.tech_direction?.join("、") || "";
            const bizValue = p?.business_direction?.join("、") || "";
            return (
              <Fragment key={r.key}>
                <tr>
                  <td><strong><EditableCell value={r.name} onSave={(next) => updateCandidateFieldValue(r.candidateId, "name", next.trim() || null)} /></strong></td>
                  <td><EditableCell value={degreeLabel(p?.highest_degree) || "—"} onSave={(next) => updateCandidateFieldValue(r.candidateId, "highest_degree", next.trim() || null)} /></td>
                  <td><EditableCell value={r.phone ?? ""} onSave={(next) => updateCandidateFieldValue(r.candidateId, "phone", next.trim() || null)} /></td>
                  <td>{industry}</td>
                  <td><EditableCell value={techValue} onSave={(next) => updateCandidateFieldValue(r.candidateId, "tech_direction", splitList(next))} /></td>
                  <td><EditableCell value={bizValue} onSave={(next) => updateCandidateFieldValue(r.candidateId, "business_direction", splitList(next))} /></td>
                  <td>{directionLabel(p?.direction_profile)}</td>
                  <td className="candidate-actions-col">
                    <div className="row-actions">
                      <span className="row-actions__group">
                        <button className="detail-button" onClick={() => void runCandidateMatch(r.candidateId, r.name)}>匹配</button>
                        <button className="detail-button" onClick={() => void previewResumeFile(r.revisionId, r.name, r.filename)}>查看详情</button>
                        <button className="detail-button" onClick={() => void downloadResumeFile(r.revisionId, r.filename || r.name)}>下载</button>
                      </span>
                      <span className="row-actions__group row-actions__group--right">
                        <button className="detail-button" onClick={() => void forceReparse(r.revisionId)}>强制OCR</button>
                        <button className="detail-button" onClick={() => void openResumeReview(r.revisionId)}>{reviewActionLabel(r.revisionStatus, r.reviewError)}</button>
                      </span>
                    </div>
                  </td>
                </tr>
                <tr>
                  <td colSpan={8}>
                    {p?.experiences && p.experiences.length > 0 && (
                      <div className="candidate-line">
                        <small>工作履历</small>
                        {p.experiences.map((e, i) => {
                          const head = [e.title, e.company].filter(Boolean).join(" @ ");
                          const tail = [e.industry ? `（${e.industry}）` : "", e.summary].filter(Boolean).join("，");
                          return <div key={i}>{[head, tail].filter(Boolean).join("，")}</div>;
                        })}
                      </div>
                    )}
                    {p?.projects && p.projects.length > 0 && (
                      <div className="candidate-line">
                        <small>项目经验</small>
                        {p.projects.map((pr, i) => <div key={i}>{pr.name ?? ""}{pr.tech_stack ? `（${pr.tech_stack}）` : ""}{pr.business_scene ? `，${pr.business_scene}` : ""}</div>)}
                      </div>
                    )}
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
    );
  }

  function renderVirtualCandidateList(rows: { key: string; candidateId: string; name: string; phone: string | null; revisionId: string; filename: string; parsed: ParsedResumeData | null; revisionStatus?: string | null; reviewError?: string | null }[]) {
    if (rows.length === 0) return null;
    return (
      <div className="virtual-list">
        {rows.map((r) => {
          const p = r.parsed;
          const recentIndustry = p?.current_industry || "—";
          const longestIndustry = p?.longest_industry || "—";
          const techValue = p?.tech_direction?.join("、") || "";
          const bizValue = p?.business_direction?.join("、") || "";
          return (
            <div key={r.key} className="virtual-row">
              <div className="virtual-row-main">
                <div className="v-col v-name"><strong><EditableCell value={r.name} onSave={(next) => updateCandidateFieldValue(r.candidateId, "name", next.trim() || null)} /></strong></div>
                <div className="v-col v-edu"><EditableCell value={degreeLabel(p?.highest_degree) || "—"} onSave={(next) => updateCandidateFieldValue(r.candidateId, "highest_degree", next.trim() || null)} /></div>
                <div className="v-col v-phone"><EditableCell value={r.phone ?? ""} onSave={(next) => updateCandidateFieldValue(r.candidateId, "phone", next.trim() || null)} /></div>
                <div className="v-col v-recent">{recentIndustry}</div>
                <div className="v-col v-longest">{longestIndustry}</div>
                <div className="v-col v-actions">
                  <button className="detail-button" disabled={!!r.revisionStatus && r.revisionStatus !== "READY"} onClick={() => void runCandidateMatch(r.candidateId, r.name)}>匹配</button>
                  <button className="detail-button" onClick={() => void previewResumeFile(r.revisionId, r.name, r.filename)}>查看详情</button>
                  <button className="detail-button" onClick={() => void downloadResumeFile(r.revisionId, r.filename || r.name)}>下载</button>
                </div>
              </div>
              <div className="virtual-row-sub">
                <div className="v-col v-tech"><EditableCell value={techValue} onSave={(next) => updateCandidateFieldValue(r.candidateId, "tech_direction", splitList(next))} /></div>
                <div className="v-col v-biz"><EditableCell value={bizValue} onSave={(next) => updateCandidateFieldValue(r.candidateId, "business_direction", splitList(next))} /></div>
                <div className="v-col v-dir">主方向：{directionLabel(p?.direction_profile)}</div>
                <div className="v-col v-actions">
                  <button className="detail-button" onClick={() => void forceReparse(r.revisionId)}>强制OCR</button>
                  <button className="detail-button" onClick={() => void openResumeReview(r.revisionId)}>{reviewActionLabel(r.revisionStatus, r.reviewError)}</button>
                </div>
              </div>
              <div className="virtual-row-detail">
                {r.reviewError && <p className="error-banner">{r.reviewError}</p>}
                {p?.experiences && p.experiences.length > 0 && (
                  <details className="candidate-collapse">
                    <summary>工作履历（{p.experiences.length}）</summary>
                    <div className="candidate-line">
                      {p.experiences.map((e, i) => {
                        const head = [e.title, e.company].filter(Boolean).join(" @ ");
                        const tail = [e.industry ? `（${e.industry}）` : "", e.summary].filter(Boolean).join("，");
                        return <div key={i}>{[head, tail].filter(Boolean).join("，")}</div>;
                      })}
                    </div>
                  </details>
                )}
                {p?.projects && p.projects.length > 0 && (
                  <details className="candidate-collapse">
                    <summary>项目经验（{p.projects.length}）</summary>
                    <div className="candidate-line">
                      {p.projects.map((pr, i) => {
                        const parts = [
                          pr.name,
                          pr.tech_stack ? `技术栈：${pr.tech_stack}` : "",
                          pr.business_scene ? `业务：${pr.business_scene}` : "",
                          pr.summary,
                        ].filter(Boolean);
                        return <div key={i}>{parts.join("，")}</div>;
                      })}
                    </div>
                  </details>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  const resultsTable = useMemo(
    () =>
      results.length === 0
        ? null
        : renderCandidateTable(
            results.map((item) => ({
              key: item.candidate_id,
              candidateId: item.candidate_id,
              name: item.name,
              phone: item.phone,
              revisionId: item.revision_id,
              filename: item.original_filename ?? "",
              parsed: item.parsed_data,
            }))
          ),
    [results]
  );

  const candidatesTable = useMemo(
    () =>
      candidates.length === 0
        ? null
        : renderVirtualCandidateList(
            candidates.map((c) => ({
              key: c.candidate_id,
              candidateId: c.candidate_id,
              name: c.display_name,
              phone: c.phone,
              revisionId: c.revision_id,
              filename: c.original_filename ?? "",
              parsed: c.parsed_data,
              revisionStatus: c.revision_status,
              reviewError: c.error_message || c.error_code,
            }))
          ),
    [candidates]
  );

  async function controlTask(task: TaskStatus, action: TaskAction) {
    setError(null);
    try {
      const updated = await api.controlTask(task.id, action);
      setTasks((current) => [updated, ...current.filter((entry) => entry.id !== updated.id)]);
      if (action === "resume" || action === "retry") pollTask(updated.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务操作失败");
    }
  }

  async function uploadResume(file: File | undefined, files?: FileList | null) {
    const selected = files && files.length > 0 ? Array.from(files) : file ? [file] : [];
    if (selected.length === 0) return;
    setError(null);
    for (const item of selected) {
      try {
        const imported = await api.importResume(item);
        if (imported.task_id) {
          const task = await api.getTask(imported.task_id);
          setTasks((current) => [task, ...current.filter((entry) => entry.id !== task.id)]);
          await loadCandidates(1);
          pollTask(imported.task_id);
        } else if (imported.action === "DUPLICATE_CONFLICT") {
          setError(imported.message || "相同文件已关联到多个候选人，请人工处理");
        } else {
          setNotice(imported.message || "文件已导入过");
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "导入失败，请检查文件");
      }
    }
  }

  async function importFolderPath(event: FormEvent) {
    event.preventDefault();
    if (!folderPath.trim()) return;
    setError(null);
    try {
      const result = await api.importFolder(folderPath.trim());
      const taskIds = result.imported.filter((item) => item.task_id).map((item) => item.task_id as string);
      pollBatchTasks(taskIds, taskIds.length);
      if (result.skipped.length > 0 || result.errors.length > 0) {
        setError(`已导入 ${result.imported.length} 个，跳过 ${result.skipped.length} 个，失败 ${result.errors.length} 个`);
      }
      setFolderPath("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文件夹导入失败");
    }
  }

  const BATCH_CHUNK = 200;
  const BATCH_POLL_MS = 1500;
  const BATCH_TIMEOUT_MS = 300_000;
  const BATCH_TERMINAL = ["SUCCESS", "FAILED", "DEAD_LETTER", "CANCELLED"];

  function summarizeBatch(taskIds: string[], statusMap: Record<string, string>, total: number) {
    let waiting = 0, running = 0, done = 0, failed = 0;
    for (const id of taskIds) {
      const status = statusMap[id];
      if (status === "SUCCESS") done += 1;
      else if (status === "FAILED" || status === "DEAD_LETTER" || status === "CANCELLED") failed += 1;
      else if (status === "RUNNING" || status === "RETRY_WAIT") running += 1;
      else waiting += 1;
    }
    const finished = done + failed;
    return { total, waiting, running, done, failed, percent: total ? Math.round((finished / total) * 100) : 100 };
  }

  async function fetchBatchStatus(taskIds: string[]) {
    const found: TaskStatus[] = [];
    const missing: string[] = [];
    for (let i = 0; i < taskIds.length; i += BATCH_CHUNK) {
      const result = await api.getTaskStatusBatch(taskIds.slice(i, i + BATCH_CHUNK));
      found.push(...result.found);
      missing.push(...result.missing_ids);
    }
    return { found, missing };
  }

  function pollBatchTasks(taskIds: string[], total: number) {
    setBatchTaskIds(taskIds);
    setBatchTimedOut(false);
    void runBatchPolling(taskIds, total);
  }

  async function runBatchPolling(taskIds: string[], total: number) {
    const deadline = Date.now() + BATCH_TIMEOUT_MS;
    const statusMap: Record<string, string> = {};
    while (Date.now() < deadline) {
      try {
        const { found } = await fetchBatchStatus(taskIds);
        for (const task of found) statusMap[task.id] = task.status;
        const summary = summarizeBatch(taskIds, statusMap, total);
        setBatchProgress(summary);
        if (summary.done + summary.failed >= total) {
          setBatchTimedOut(false);
          await loadCandidates();
          return;
        }
      } catch {
        setBatchTimedOut(true);
        setBatchProgress(summarizeBatch(taskIds, statusMap, total));
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, BATCH_POLL_MS));
    }
    setBatchTimedOut(true);
    setBatchProgress(summarizeBatch(taskIds, statusMap, total));
  }

  async function continueBatchPolling() {
    if (batchTaskIds.length === 0 || !batchProgress) return;
    setBatchTimedOut(false);
    await runBatchPolling(batchTaskIds, batchProgress.total);
  }

  async function submitJd(event: FormEvent) {
    event.preventDefault();
    if (!jdSource.trim()) return;
    setError(null);
    try {
      const result = await api.importJdBatch(jdSource.trim());
      setJdResult(result.imported);
      await loadJds();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JD 导入失败");
    }
  }

  async function uploadJd(file: File | undefined) {
    if (!file) return;
    setError(null);
    try {
      const result = await api.importJdBatchFile(file);
      setJdResult(result.imported);
      await loadJds();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JD 文件导入失败");
    }
  }

  async function checkHealth() {
    setError(null);
    try {
      setHealth(await api.health());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "健康检测失败");
    }
  }

  async function loadDiagnostics() {
    setError(null);
    try {
      setDiagnostics(await api.diagnostics());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "诊断信息加载失败");
    }
  }

  async function exportDiagnostics() {
    setError(null);
    try {
      await api.exportDiagnostics();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "诊断信息导出失败");
    }
  }

  async function loadCompanies() {
    setError(null);
    try {
      setCompanies(await api.listCompanies());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "公司列表加载失败");
    }
  }

  async function reloadOrgTree(companyId: string) {
    try {
      const [tree, deps, emps] = await Promise.all([
        api.getOrgTree(companyId),
        api.listDepartments(companyId),
        api.listEmployees(companyId),
      ]);
      setOrgTree(tree);
      setDepartments(deps);
      setEmployees(emps);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "组织数据加载失败");
    }
  }

  async function createCompany(event: FormEvent) {
    event.preventDefault();
    if (!companyName.trim()) return;
    setError(null);
    try {
      const company = await api.createCompany(companyName.trim());
      setCompanies((current) => [...current, company]);
      setCompanyName("");
      setSelectedCompanyId(company.id);
      setSelectedOrgNodeId(null);
      setOrgTree(null);
      setDepartments([]);
      setEmployees([]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建公司失败");
    }
  }

  async function selectCompany(companyId: string) {
    setError(null);
    setSelectedCompanyId(companyId);
    setSelectedOrgNodeId(null);
    await reloadOrgTree(companyId);
  }

  async function addOrgChild(node: OrgTreeNode) {
    if (!selectedCompanyId) return;
    const companyId = selectedCompanyId;
    setError(null);
    try {
      let kind: "department" | "employee";
      let createdId: string;
      let deptArgs: CreateOrgDepartmentInput | null = null;
      let empArgs: CreateOrgEmployeeInput | null = null;
      if (node.kind === "company") {
        deptArgs = { company_id: companyId, name: "新部门" };
        const dept = await api.createDepartment(deptArgs);
        kind = "department";
        createdId = dept.id;
      } else if (node.kind === "department") {
        deptArgs = { company_id: companyId, name: "新部门", parent_id: node.id };
        const dept = await api.createDepartment(deptArgs);
        kind = "department";
        createdId = dept.id;
      } else {
        const emp = employees.find((e) => e.id === node.id);
        empArgs = {
          company_id: companyId,
          department_id: emp?.department_id ?? null,
          name: "新人员",
          report_to: node.id,
        };
        const created = await api.createEmployee(empArgs);
        kind = "employee";
        createdId = created.id;
      }
      await reloadOrgTree(companyId);
      setSelectedOrgNodeId(createdId);
      setPendingEditId(createdId);
      recordUndo({
        undo: async () => {
          if (kind === "department") await api.deleteDepartment(createdId);
          else await api.deleteEmployee(createdId);
          await reloadOrgTree(companyId);
        },
        redo: async () => {
          if (kind === "department" && deptArgs) await api.createDepartment(deptArgs);
          else if (empArgs) await api.createEmployee(empArgs);
          await reloadOrgTree(companyId);
        },
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新增节点失败");
    }
  }

  async function addOrgSibling(node: OrgTreeNode) {
    if (!selectedCompanyId) return;
    const companyId = selectedCompanyId;
    setError(null);
    try {
      let kind: "department" | "employee";
      let createdId: string;
      let deptArgs: CreateOrgDepartmentInput | null = null;
      let empArgs: CreateOrgEmployeeInput | null = null;
      if (node.kind === "department") {
        const dept = departments.find((d) => d.id === node.id);
        deptArgs = { company_id: companyId, name: "新部门", parent_id: dept?.parent_id ?? null };
        const created = await api.createDepartment(deptArgs);
        kind = "department";
        createdId = created.id;
      } else if (node.kind === "employee") {
        const emp = employees.find((e) => e.id === node.id);
        empArgs = {
          company_id: companyId,
          department_id: emp?.department_id ?? null,
          name: "新人员",
          report_to: emp?.report_to ?? null,
        };
        const created = await api.createEmployee(empArgs);
        kind = "employee";
        createdId = created.id;
      } else {
        return;
      }
      await reloadOrgTree(companyId);
      setSelectedOrgNodeId(createdId);
      setPendingEditId(createdId);
      recordUndo({
        undo: async () => {
          if (kind === "department") await api.deleteDepartment(createdId);
          else await api.deleteEmployee(createdId);
          await reloadOrgTree(companyId);
        },
        redo: async () => {
          if (kind === "department" && deptArgs) await api.createDepartment(deptArgs);
          else if (empArgs) await api.createEmployee(empArgs);
          await reloadOrgTree(companyId);
        },
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新增节点失败");
    }
  }

  async function addOrgPerson(node: OrgTreeNode) {
    if (!selectedCompanyId) return;
    const companyId = selectedCompanyId;
    setError(null);
    try {
      let empArgs: CreateOrgEmployeeInput;
      if (node.kind === "department") {
        empArgs = { company_id: companyId, department_id: node.id, name: "新人员" };
      } else if (node.kind === "employee") {
        const sourceEmp = employees.find((e) => e.id === node.id);
        empArgs = { company_id: companyId, department_id: sourceEmp?.department_id ?? null, name: "新人员", report_to: node.id };
      } else {
        return;
      }
      const created = await api.createEmployee(empArgs);
      await reloadOrgTree(companyId);
      setSelectedOrgNodeId(created.id);
      setPendingEditId(created.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新增人员失败");
    }
  }

  async function renameOrgNode(node: OrgTreeNode, name: string) {
    const companyId = selectedCompanyId;
    const oldName = node.name;
    setError(null);
    try {
      if (node.kind === "company") {
        await api.updateCompany(node.id, name);
        setCompanies((current) => current.map((c) => (c.id === node.id ? { ...c, name } : c)));
      } else if (node.kind === "employee") {
        await api.updateEmployee(node.id, { name });
      } else if (node.kind === "department") {
        await api.updateDepartment(node.id, { name });
      }
      if (companyId) await reloadOrgTree(companyId);
      recordUndo({
        undo: async () => {
          if (node.kind === "company") {
            await api.updateCompany(node.id, oldName);
            setCompanies((current) => current.map((c) => (c.id === node.id ? { ...c, name: oldName } : c)));
          } else if (node.kind === "employee") {
            await api.updateEmployee(node.id, { name: oldName });
          } else if (node.kind === "department") {
            await api.updateDepartment(node.id, { name: oldName });
          }
          if (companyId) await reloadOrgTree(companyId);
        },
        redo: async () => {
          if (node.kind === "company") {
            await api.updateCompany(node.id, name);
            setCompanies((current) => current.map((c) => (c.id === node.id ? { ...c, name } : c)));
          } else if (node.kind === "employee") {
            await api.updateEmployee(node.id, { name });
          } else if (node.kind === "department") {
            await api.updateDepartment(node.id, { name });
          }
          if (companyId) await reloadOrgTree(companyId);
        },
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重命名失败");
    }
  }

  async function deleteOrgNode(node: OrgTreeNode) {
    const companyId = selectedCompanyId;
    setError(null);
    try {
      const savedEmployee = node.kind === "employee" ? employees.find((e) => e.id === node.id) ?? null : null;
      const savedDepartment = node.kind === "department" ? departments.find((d) => d.id === node.id) ?? null : null;

      if (node.kind === "employee") await api.deleteEmployee(node.id);
      else if (node.kind === "department") await api.deleteDepartment(node.id);
      setSelectedOrgNodeId(null);
      if (companyId) await reloadOrgTree(companyId);

      recordUndo({
        undo: async () => {
          if (savedEmployee) {
            await api.createEmployee({
              company_id: savedEmployee.company_id,
              name: savedEmployee.name,
              department_id: savedEmployee.department_id,
              title: savedEmployee.title,
              job_level: savedEmployee.job_level,
              report_to: savedEmployee.report_to,
              subordinate_count: savedEmployee.subordinate_count,
              tenure_years: savedEmployee.tenure_years,
              business_module: savedEmployee.business_module,
              status: savedEmployee.status,
              intention: savedEmployee.intention,
              remark: savedEmployee.remark,
              contact: savedEmployee.contact,
              is_key: savedEmployee.is_key,
            });
          } else if (savedDepartment) {
            await api.createDepartment({
              company_id: savedDepartment.company_id,
              name: savedDepartment.name,
              parent_id: savedDepartment.parent_id,
              leader_id: savedDepartment.leader_id,
              leader_report_to: savedDepartment.leader_report_to,
              team_size: savedDepartment.team_size,
              business_direction: savedDepartment.business_direction,
              tech_stack: savedDepartment.tech_stack,
              office_location: savedDepartment.office_location,
              hc_status: savedDepartment.hc_status,
              hc_internal_note: savedDepartment.hc_internal_note,
            });
          }
          if (companyId) await reloadOrgTree(companyId);
        },
        redo: async () => {
          if (node.kind === "employee") await api.deleteEmployee(node.id);
          else if (node.kind === "department") await api.deleteDepartment(node.id);
          if (companyId) await reloadOrgTree(companyId);
        },
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
    }
  }

  async function updateOrgEmployeeField(id: string, changes: UpdateOrgEmployeeInput) {
    setError(null);
    try {
      await api.updateEmployee(id, changes);
      if (selectedCompanyId) await reloadOrgTree(selectedCompanyId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    }
  }

  async function bindOrgEmployee(employeeId: string, phone: string, name: string): Promise<BindEmployeeResult> {
    const result = await api.bindEmployee(employeeId, phone, name);
    if (selectedCompanyId) await reloadOrgTree(selectedCompanyId);
    return result;
  }

  async function updateOrgDepartmentField(id: string, changes: UpdateOrgDepartmentInput) {
    setError(null);
    try {
      await api.updateDepartment(id, changes);
      if (selectedCompanyId) await reloadOrgTree(selectedCompanyId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    }
  }

  async function deleteCompany(companyId: string) {
    setError(null);
    try {
      await api.deleteCompany(companyId);
      setCompanies((current) => current.filter((c) => c.id !== companyId));
      if (selectedCompanyId === companyId) {
        setSelectedCompanyId(null);
        setSelectedOrgNodeId(null);
        setOrgTree(null);
        setDepartments([]);
        setEmployees([]);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除公司失败");
    }
  }

  function applyOrgParseResult(result: OrgParseResult) {
    if (result.draft) setOrgImportDraft(result.draft);
    const questions = result.questions ?? [];
    setOrgImportQuestions(questions);
    setOrgImportAnswers(questions.map(() => ""));
    setOrgImportMessage(questions.length > 0 ? "解析有疑问，请回答下方问题后继续解析" : "解析完成，请核对下方结果后导入");
  }

  async function parseOrgImportText() {
    if (!orgImportText.trim()) return;
    setError(null);
    setOrgImportMessage("");
    setOrgImportBusy(true);
    try {
      applyOrgParseResult(await api.parseOrgImport(orgImportText.trim()));
    } catch (caught) {
      setOrgImportMessage(caught instanceof Error ? caught.message : "解析失败");
    } finally {
      setOrgImportBusy(false);
    }
  }

  async function parseOrgImportFile(file: File) {
    setError(null);
    setOrgImportMessage("");
    setOrgImportBusy(true);
    try {
      applyOrgParseResult(await api.parseOrgWord(file));
      setOrgImportFileName(file.name);
    } catch (caught) {
      setOrgImportMessage(caught instanceof Error ? caught.message : "解析失败");
    } finally {
      setOrgImportBusy(false);
    }
  }

  async function answerOrgImportDraft() {
    if (!orgImportText.trim()) return;
    setError(null);
    setOrgImportMessage("");
    setOrgImportBusy(true);
    try {
      const answers = orgImportAnswers.map((answer) => answer.trim()).filter(Boolean);
      applyOrgParseResult(await api.answerOrgImport(orgImportText.trim(), answers));
    } catch (caught) {
      setOrgImportMessage(caught instanceof Error ? caught.message : "解析失败");
    } finally {
      setOrgImportBusy(false);
    }
  }

  async function commitOrgImport() {
    if (!orgImportDraft) return;
    if (!selectedCompanyId) {
      setOrgImportMessage("请先在左侧「公司」列表选择或新建目标公司，再导入");
      return;
    }
    setError(null);
    setOrgImportMessage("");
    setOrgImportBusy(true);
    try {
      const result = await api.commitOrgImport(selectedCompanyId, orgImportDraft, orgImportText);
      setOrgImportMessage(`已导入 ${result.departments} 个部门、${result.employees} 名人员`);
      setOrgImportDraft(null);
      setOrgImportText("");
      setOrgImportFileName("");
      await reloadOrgTree(selectedCompanyId);
    } catch (caught) {
      setOrgImportMessage(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setOrgImportBusy(false);
    }
  }

  async function reviseOrgImportDraft() {
    if (!orgImportDraft || !orgReviseInstruction.trim()) return;
    setOrgImportBusy(true);
    setOrgImportMessage("");
    try {
      const revised = await api.reviseOrgImport(orgImportDraft, orgReviseInstruction.trim());
      setOrgImportDraft(revised);
      setOrgReviseInstruction("");
      setOrgImportMessage("已按指令修订，请核对后导入");
    } catch (caught) {
      setOrgImportMessage(caught instanceof Error ? caught.message : "修订失败");
    } finally {
      setOrgImportBusy(false);
    }
  }

  async function toggleOrgSource(companyId: string) {
    if (orgSource?.companyId === companyId) {
      setOrgSource(null);
      return;
    }
    setError(null);
    try {
      const result = await api.getCompanySource(companyId);
      setOrgSource({ companyId, text: result.source_text });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取导入原文失败");
    }
  }

  function updateOrgImportCompanyName(value: string) {
    setOrgImportDraft((current) => (current ? { ...current, company_name: value } : current));
  }

  function updateOrgImportDepartment(index: number, field: string, value: string | number | null) {
    setOrgImportDraft((current) => {
      if (!current) return current;
      const departments = [...current.departments];
      departments[index] = { ...departments[index], [field]: value };
      return { ...current, departments };
    });
  }

  function updateOrgImportEmployee(index: number, field: string, value: string | number | null) {
    setOrgImportDraft((current) => {
      if (!current) return current;
      const employees = [...current.employees];
      employees[index] = { ...employees[index], [field]: value };
      return { ...current, employees };
    });
  }

  async function moveOrgNode(source: OrgTreeNode, target: OrgTreeNode) {
    if (!selectedCompanyId) return;
    const companyId = selectedCompanyId;
    setError(null);
    try {
      const sourceEmployee = source.kind === "employee" ? employees.find((e) => e.id === source.id) ?? null : null;
      const sourceDepartment = source.kind === "department" ? departments.find((d) => d.id === source.id) ?? null : null;
      const oldReportTo = sourceEmployee?.report_to ?? null;
      const oldDepartmentId = sourceEmployee?.department_id ?? null;
      const oldParentId = sourceDepartment?.parent_id ?? null;

      if (source.kind === "employee" && target.kind === "employee") {
        await api.updateEmployee(source.id, { report_to: target.id });
      } else if (source.kind === "employee" && target.kind === "department") {
        await api.updateEmployee(source.id, { department_id: target.id });
      } else if (source.kind === "department" && target.kind === "department") {
        await api.updateDepartment(source.id, { parent_id: target.id });
      } else {
        return;
      }
      await reloadOrgTree(companyId);

      recordUndo({
        undo: async () => {
          if (source.kind === "employee") {
            const changes: UpdateOrgEmployeeInput = {};
            if (target.kind === "employee") changes.report_to = oldReportTo;
            else if (target.kind === "department") changes.department_id = oldDepartmentId;
            await api.updateEmployee(source.id, changes);
          } else if (source.kind === "department") {
            await api.updateDepartment(source.id, { parent_id: oldParentId });
          }
          await reloadOrgTree(companyId);
        },
        redo: async () => {
          if (source.kind === "employee" && target.kind === "employee") {
            await api.updateEmployee(source.id, { report_to: target.id });
          } else if (source.kind === "employee" && target.kind === "department") {
            await api.updateEmployee(source.id, { department_id: target.id });
          } else if (source.kind === "department" && target.kind === "department") {
            await api.updateDepartment(source.id, { parent_id: target.id });
          }
          await reloadOrgTree(companyId);
        },
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "移动失败");
    }
  }

  function recordUndo(entry: { undo: () => Promise<void>; redo: () => Promise<void> }) {
    undoStackRef.current.push(entry);
    redoStackRef.current = [];
  }

  async function undo() {
    const entry = undoStackRef.current.pop();
    if (!entry) return;
    setError(null);
    try {
      await entry.undo();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    }
    redoStackRef.current.push(entry);
  }

  async function redo() {
    const entry = redoStackRef.current.pop();
    if (!entry) return;
    setError(null);
    try {
      await entry.redo();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重做失败");
    }
    undoStackRef.current.push(entry);
  }

  async function searchBd(event: FormEvent) {
    event.preventDefault();
    if (!bdQuery.trim()) return;
    setError(null);
    setBdLoading(true);
    setBdProgress(null);
    try {
      const result = await api.runBdAgentStream(bdQuery.trim(), "text", 10, (p) => setBdProgress(p));
      setBdSessionId(result.session_id);
      setBdLeads(sortLeadsByConfidence(result.leads));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "线索搜索失败");
    } finally {
      setBdLoading(false);
      setBdProgress(null);
    }
  }

  async function followUpBd(event: FormEvent) {
    event.preventDefault();
    if (!bdFollowUp.trim() || !bdSessionId) return;
    setError(null);
    setBdLoading(true);
    try {
      const result = await api.followUpBdAgent(bdSessionId, bdFollowUp.trim(), 10);
      setBdLeads((prev) => sortLeadsByConfidence([...prev, ...result.leads]));
      setBdFollowUp("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "追问失败");
    } finally {
      setBdLoading(false);
    }
  }

  async function lookupPool(leadId: string) {
    setError(null);
    setBdPoolBusyId(leadId);
    setCollapsedPool((prev) => ({ ...prev, [leadId]: false }));
    try {
      const matches = await api.lookupPool(leadId);
      setBdPoolByLead((prev) => ({ ...prev, [leadId]: matches }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "反查人才库失败");
    } finally {
      setBdPoolBusyId(null);
    }
  }

  function togglePoolCollapse(leadId: string) {
    setCollapsedPool((prev) => ({ ...prev, [leadId]: !prev[leadId] }));
  }

  async function loadDashboard(filters = dashboardFilters, granularity = trendGranularity) {
    if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
      setError("开始日期不能晚于结束日期");
      return;
    }
    const request = ++dashboardRequest.current;
    setError(null);
    setDashboardBusy(true);
    try {
      const [overview, byJd, trend] = await Promise.all([
        api.dashboardOverview(filters),
        api.dashboardByJd(filters),
        api.dashboardTrend(granularity, filters),
      ]);
      if (request !== dashboardRequest.current) return;
      setDashboardFilters(filters);
      setTrendGranularity(granularity);
      setDashboard(overview);
      setDashboardByJdData(byJd);
      setDashboardTrend(trend);
    } catch (caught) {
      if (request === dashboardRequest.current) setError(caught instanceof Error ? caught.message : "看板加载失败");
    } finally {
      if (request === dashboardRequest.current) setDashboardBusy(false);
    }
  }

  async function reloadTrend(granularity: string) {
    await loadDashboard(dashboardFilters, granularity);
  }

  async function loadDeleted() {
    setError(null);
    try {
      setDeletedItems(await api.listDeleted());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "回收站加载失败");
    }
  }

  async function restoreItem(item: DeletedItem) {
    setError(null);
    try {
      await api.restoreDeleted(item.entity_type, item.entity_id);
      setDeletedItems((current) => current.filter((d) => d.entity_id !== item.entity_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "恢复失败");
    }
  }

  async function loadSettings() {
    setError(null);
    try {
      setSettings(await api.getSettings());
      setVendors(await api.getVendors());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置加载失败");
    }
  }

  async function testProviders() {
    setError(null);
    try {
      setProviderChecks(await api.testProviders());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "API 测试失败");
    }
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setSettings(await api.updateSettings(settings));
      setSettingsMessage("设置已保存，重启应用后生效");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置保存失败");
    }
  }

  async function testMailConfig() {
    setError(null);
    setMailTestResult(null);
    try {
      setMailTestResult(await api.testMail());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "邮箱连接测试失败");
    }
  }

  async function syncMailNow() {
    setError(null);
    setMailSyncMessage("");
    try {
      const result = await api.syncMail();
      setMailSyncMessage(`同步完成：新入库 ${result.ingested} 份简历`);
      await loadMailStatus();
    } catch (caught) {
      setMailSyncMessage(caught instanceof Error ? caught.message : "邮箱同步失败");
    }
  }

  async function loadMailStatus() {
    try {
      setMailStatus(await api.mailStatus());
    } catch {
      setMailStatus(null);
    }
  }

  function addMailWhitelistTag() {
    const tag = mailWhitelistInput.trim();
    if (!tag) return;
    const existing = (settings.imap_whitelist ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    if (!existing.includes(tag)) existing.push(tag);
    setSettings({ ...settings, imap_whitelist: existing.join(",") });
    setMailWhitelistInput("");
  }

  function removeMailWhitelistTag(tag: string) {
    const existing = (settings.imap_whitelist ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    setSettings({ ...settings, imap_whitelist: existing.filter((s) => s !== tag).join(",") });
  }

  async function saveDataRoot() {
    setError(null);
    setDataRootMessage("");
    try {
      await api.setDataRoot(dataRootInput.trim());
      setDataRootMessage("数据目录已保存，重启应用后生效");
    } catch (caught) {
      setDataRootMessage(caught instanceof Error ? caught.message : "数据目录保存失败");
    }
  }

  async function loadBackups() {
    setError(null);
    setBackupBusy(true);
    try {
      setBackups(await api.listBackups());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "备份列表加载失败");
    } finally {
      setBackupBusy(false);
    }
  }

  async function createBackup() {
    setError(null);
    setBackupBusy(true);
    try {
      await api.createBackup();
      setBackups(await api.listBackups());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建备份失败");
    } finally {
      setBackupBusy(false);
    }
  }

  async function restoreBackupItem(filename: string) {
    const confirmed = window.confirm(
      `确认恢复备份 "${filename}" 到当前数据目录？\n恢复将覆盖当前数据，且需要重启应用后生效。`
    );
    if (!confirmed) return;
    setError(null);
    setBackupBusy(true);
    try {
      await api.restoreBackup(filename);
      setBackups(await api.listBackups());
      setPortableMessage("恢复已准备：请从托盘退出后重新启动。重启后会同步搜索索引，期间部分结果暂不可用。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "恢复失败");
    } finally {
      setBackupBusy(false);
    }
  }

  async function createPortableBackup() {
    if (!portableBackupPath.trim() || !portablePassphrase) return;
    setError(null);
    setPortableBusy(true);
    try {
      const result = await api.createPortableBackup(portableBackupPath.trim(), portablePassphrase);
      setPortableMessage(`便携备份已创建：${result.path}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "便携备份创建失败");
    } finally {
      setPortableBusy(false);
    }
  }

  async function restorePortableBackup() {
    if (!portableRestorePath.trim() || !portableRestoreTarget.trim() || !portablePassphrase) return;
    const confirmed = window.confirm(
      `确认从 "${portableRestorePath.trim()}" 恢复到 "${portableRestoreTarget.trim()}"？\n目标目录将被替换；如需在当前应用使用该数据，请重启并切换数据目录。`
    );
    if (!confirmed) return;
    setError(null);
    setPortableBusy(true);
    try {
      const result = await api.restorePortableBackup(
        portableRestorePath.trim(),
        portableRestoreTarget.trim(),
        portablePassphrase
      );
      setPortableMessage(result.ok
        ? `便携备份恢复并校验完成：${result.files_verified} 个文件。请重启应用并切换数据目录后使用。`
        : "便携备份恢复校验未通过");
    } catch (caught) {
      setPortableMessage(caught instanceof Error ? caught.message : "便携备份恢复失败");
    } finally {
      setPortableBusy(false);
    }
  }

  async function migrateData(event: FormEvent) {
    event.preventDefault();
    if (!migrationTarget.trim()) return;
    setError(null);
    setMigrationMessage("");
    setMigrationBusy(true);
    try {
      setMigrationReport(await api.migrateData(migrationTarget.trim()));
      setMigrationMessage("迁移校验通过，请重启应用并切换到新数据目录后生效");
    } catch (caught) {
      setMigrationReport(null);
      setMigrationMessage(caught instanceof Error ? caught.message : "数据迁移失败");
    } finally {
      setMigrationBusy(false);
    }
  }

  async function loadOnboarding() {
    setError(null);
    try {
      setOnboarding(await api.onboardingStatus());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "启动检查失败");
    }
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const meta = event.metaKey || event.ctrlKey;
      if (!meta) return;

      if (event.key === "k" || event.key === "K") {
        event.preventDefault();
        setActiveNav(0);
        return;
      }
      const digit = Number(event.key);
      if (digit >= 1 && digit <= navigation.length) {
        event.preventDefault();
        setActiveNav(digit - 1);
      }
    }

    function onEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setPreviewUrl(null);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keydown", onEscape);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keydown", onEscape);
    };
  }, []);

  useEffect(() => {
    api.getDirections().then(setDirections).catch(() => {});
    api.getVendors().then(setVendors).catch(() => {});
  }, []);

  useEffect(() => {
    if (activeNav === 0) void loadCandidates();
    if (activeNav === 1) void loadJds();
    if (activeNav === 2 || activeNav === 6) void loadJds();
    if (activeNav === 2) void loadDashboard();
    if (activeNav === 6) void loadCases();
  }, [activeNav]);

  const displayOrgTree = useMemo(
    () => (orgTree ? filterOrgTree(orgTree, orgSearch, orgFilterKind, orgFilterKey) : null),
    [orgTree, orgSearch, orgFilterKind, orgFilterKey]
  );

  const selectedOrgNode = useMemo(() => {
    if (!orgTree || !selectedOrgNodeId) return null;
    function find(node: OrgTreeNode): OrgTreeNode | null {
      if (node.id === selectedOrgNodeId) return node;
      for (const child of node.children) {
        const hit = find(child);
        if (hit) return hit;
      }
      return null;
    }
    return find(orgTree);
  }, [orgTree, selectedOrgNodeId]);

  const selectedOrgEmployee = selectedOrgNode?.kind === "employee"
    ? employees.find((e) => e.id === selectedOrgNode.id) ?? null
    : null;
  const selectedOrgDepartment = selectedOrgNode?.kind === "department"
    ? departments.find((d) => d.id === selectedOrgNode.id) ?? null
    : null;

  const filteredJds = jds.filter((jd) => {
    if (jdFilter.title && !(jd.title || "").toLowerCase().includes(jdFilter.title.trim().toLowerCase())) return false;
    if (jdFilter.company && !(jd.company || "").toLowerCase().includes(jdFilter.company.trim().toLowerCase())) return false;
    if (jdFilter.status && jd.jd_status !== jdFilter.status) return false;
    return true;
  });

  return (
    <div className={navCollapsed ? "app-shell nav-collapsed" : "app-shell"}>
      <aside className="navigation" aria-label="主导航">
        <div className="brand">
          <span className="brand-mark">K</span>
          <div><strong>人才库</strong><small>本地招聘工作台</small></div>
        </div>
        <nav>
          {navigation.map((item, index) => (
            <button
              className={index === activeNav ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => setActiveNav(index)}
            >
              <span>{index + 1}</span>{item}
            </button>
          ))}
        </nav>
        <div className="local-status"><i />本机数据 · 已保护</div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <button
            className="nav-toggle"
            aria-label={navCollapsed ? "展开导航" : "收起导航"}
            onClick={() => setNavCollapsed((v) => !v)}
          >
            {navCollapsed ? "»" : "«"}
          </button>
          <div><h1>{navigation[activeNav]}</h1><p>结构化管理与智能匹配候选人</p></div>
          <div className="shortcut-hints" aria-label="系统快捷键">
            <span><kbd>Ctrl K</kbd>搜索</span>
            <span><kbd>Ctrl 1-{navigation.length}</kbd>切换</span>
            <span><kbd>Esc</kbd>取消</span>
          </div>
          {activeNav === 0 && (
            <label className="import-button">
              导入简历
              <input
                aria-label="选择简历文件"
                accept=".pdf,.doc,.docx"
                multiple
                type="file"
                onChange={(event) => void uploadResume(undefined, event.target.files)}
              />
            </label>
          )}
        </header>

        {error && <div className="error-banner" role="alert">{error}</div>}
        {notice && <div className="notice-banner" role="status">{notice}</div>}

        {activeNav === 0 && (
          <>
            <section className="search-panel">
              <form onSubmit={(event) => void submitSearch(event)}>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索人才、技能、公司或自然语言"
                  aria-label="人才搜索"
                />
                <kbd>Ctrl K</kbd>
                <button disabled={searching} type="submit">{searching ? "搜索中" : "搜索"}</button>
              </form>
              <details className="search-filters">
                <summary>精确筛选</summary>
                <div className="search-filter-grid">
                  <label>最低工作年限<input aria-label="最低工作年限" type="number" min="0" max="80" value={searchFilterDraft.minYears} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, minYears: e.target.value })} /></label>
                  <label>最高工作年限<input aria-label="最高工作年限" type="number" min="0" max="80" value={searchFilterDraft.maxYears} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, maxYears: e.target.value })} /></label>
                  <label>学历<select aria-label="最低学历" value={searchFilterDraft.degree} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, degree: e.target.value })}>
                    <option value="">由查询语句决定</option><option value="ASSOCIATE">大专</option><option value="BACHELOR">本科</option><option value="MASTER">硕士</option><option value="DOCTORATE">博士</option>
                  </select></label>
                  <label>现居城市<input aria-label="现居城市" placeholder="上海、苏州" value={searchFilterDraft.locations} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, locations: e.target.value })} /></label>
                  <label>意向城市<input aria-label="意向城市" placeholder="北京、深圳" value={searchFilterDraft.preferredLocations} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, preferredLocations: e.target.value })} /></label>
                  <label>学校等级<input aria-label="学校等级" placeholder="985 / 211" value={searchFilterDraft.schoolLevel} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, schoolLevel: e.target.value })} /></label>
                  <label>QS最高排名<input aria-label="QS最高排名" type="number" min="1" value={searchFilterDraft.maxQsRank} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, maxQsRank: e.target.value })} /></label>
                  <label>排除技能<input aria-label="排除技能" placeholder="外包、PHP" value={searchFilterDraft.excludeSkills} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, excludeSkills: e.target.value })} /></label>
                  <label>主方向<select aria-label="主方向" value={searchFilterDraft.direction} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, direction: e.target.value })}>
                    <option value="">全部方向</option>
                    {(directions?.role_families ?? []).map((rf) => <option key={rf.code} value={rf.code}>{rf.label}</option>)}
                  </select></label>
                  <label>业务领域<input aria-label="业务领域" placeholder="支付、金融/银行" value={searchFilterDraft.businessDomains} onChange={(e) => setSearchFilterDraft({ ...searchFilterDraft, businessDomains: e.target.value })} /></label>
                </div>
                <button type="button" className="detail-button" onClick={() => setSearchFilterDraft({ minYears: "", maxYears: "", degree: "", locations: "", preferredLocations: "", schoolLevel: "", maxQsRank: "", excludeSkills: "", direction: "", businessDomains: "" })}>清除筛选</button>
              </details>
              <form className="folder-import" onSubmit={(event) => void importFolderPath(event)}>
                <input value={folderPath} onChange={(e) => setFolderPath(e.target.value)} placeholder="导入文件夹路径，如 D:\简历库" aria-label="文件夹路径" />
                <button type="submit">导入文件夹</button>
              </form>
              {batchProgress && (
                <div className="batch-progress">
                  <span>
                    解析进度：{batchProgress.percent}%（总数 {batchProgress.total} · 等待 {batchProgress.waiting} · 运行 {batchProgress.running} · 成功 {batchProgress.done} · 失败 {batchProgress.failed}）
                  </span>
                  <progress max={batchProgress.total || 1} value={batchProgress.done + batchProgress.failed} />
                  {batchTimedOut && (
                    <p role="status" className="muted">
                      批次仍在后台运行。{batchTaskIds.length > 0 && (
                        <button type="button" className="detail-button" onClick={() => void continueBatchPolling()}>继续刷新</button>
                      )}
                    </p>
                  )}
                </div>
              )}
            </section>

            <section className="content-grid">
              <div className="results-card" ref={candidateListRef}>
                <div className="section-heading">
                  <h2>候选人</h2>
                  <button className="detail-button" onClick={() => void loadCandidates(1)}>显示候选人</button>
                  {results.length > 0 && (
                    <button className="detail-button" onClick={closeSearchResults}>关闭结果</button>
                  )}
                  <button className="detail-button" onClick={resetSearchAndGoHome}>清空搜索</button>
                  <span>{results.length} 条结果</span>
                </div>
                {results.length === 0 ? (
                  <div className="empty-state"><strong>从一次搜索开始</strong><p>输入技能、经历或自然语言条件查找人才，或点击「显示全部候选人」查看已导入人才。</p></div>
                ) : (
                  resultsTable
                )}
                {candidates.length > 0 && (
                  <>
                    <div className="section-heading"><h3>候选人（共 {candidateTotal} 人）</h3></div>
                    {candidatesTable}
                    <div className="pagination">
                      <button className="detail-button" disabled={candidatePage <= 1} onClick={() => void loadCandidates(candidatePage - 1)}>上一页</button>
                      {pageWindow(candidatePage, candidateTotalPages).map((page, index) =>
                        typeof page === "number" ? (
                          <button
                            key={`page-${page}-${index}`}
                            className={page === candidatePage ? "page-current" : "page-number"}
                            onClick={() => void loadCandidates(page)}
                          >
                            {page}
                          </button>
                        ) : (
                          <span key={`ellipsis-${index}`} className="page-ellipsis">…</span>
                        )
                      )}
                      <button className="detail-button" disabled={candidatePage >= candidateTotalPages} onClick={() => void loadCandidates(candidatePage + 1)}>下一页</button>
                    </div>
                    <div className="pagination-actions">
                      <button className="detail-button" onClick={scrollToCandidateListTop}>回到顶部</button>
                      <button className="detail-button" onClick={resetSearchAndGoHome}>人才库首页</button>
                    </div>
                  </>
                )}
              </div>
            </section>
          </>
        )}

        {activeNav === 1 && (
          <section className="jd-panel">
            <form className="jd-form" onSubmit={(event) => void submitJd(event)}>
              <textarea value={jdSource} onChange={(e) => setJdSource(e.target.value)} placeholder="粘贴 JD 原文…" aria-label="JD 原文" />
              <div className="case-actions">
                <button type="submit">导入并解析</button>
                <label className="import-button">
                  导入 Word / Excel
                  <input
                    aria-label="选择 JD 文件"
                    accept=".doc,.docx,.xls,.xlsx"
                    type="file"
                    onChange={(event) => void uploadJd(event.target.files?.[0])}
                  />
                </label>
              </div>
            </form>
            {jdResult.length > 0 && (
              <div className="jd-result" role="status">
                <strong>导入成功 {jdResult.length} 个岗位</strong>
                {jdResult.map((item) => (
                  <code key={item.revision_id}>{item.revision_id}</code>
                ))}
              </div>
            )}
            <div className="results-card">
              <div className="section-heading">
                <h2>已导入 JD</h2>
                <button className="detail-button" onClick={() => void loadJds()}>刷新列表</button>
              </div>
              <div className="jd-filters">
                <input
                  aria-label="筛选岗位名称"
                  placeholder="筛选岗位"
                  value={jdFilter.title}
                  onChange={(event) => setJdFilter({ ...jdFilter, title: event.target.value })}
                />
                <input
                  aria-label="筛选公司名称"
                  placeholder="筛选公司"
                  value={jdFilter.company}
                  onChange={(event) => setJdFilter({ ...jdFilter, company: event.target.value })}
                />
                <select
                  aria-label="筛选岗位状态"
                  value={jdFilter.status}
                  onChange={(event) => setJdFilter({ ...jdFilter, status: event.target.value })}
                >
                  <option value="">全部状态</option>
                  {JD_STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              {jds.length === 0 ? (
                <p className="muted">暂无 JD，先在上方导入。</p>
              ) : filteredJds.length === 0 ? (
                <p className="muted">没有符合筛选条件的 JD。</p>
              ) : (
                <table>
                  <thead><tr><th>岗位名称</th><th>公司名称</th><th>状态</th><th>岗位要求（技术+业务）</th><th>操作</th></tr></thead>
                  <tbody>
                    {filteredJds.map((jd) => (
                      <Fragment key={jd.revision_id}>
                        <tr>
                          <td><strong><EditableCell value={jd.title || ""} onSave={(next) => updateJdFieldValue(jd.jd_id, "title", next.trim())} /></strong></td>
                          <td><EditableCell value={jd.company || ""} onSave={(next) => updateJdFieldValue(jd.jd_id, "company", next.trim())} /></td>
                          <td>
                            <select
                              aria-label="岗位状态"
                              className={`jd-status-select ${jd.jd_status.toLowerCase()}`}
                              value={jd.jd_status}
                              onChange={(event) => void updateJdStatus(jd.jd_id, event.target.value)}
                            >
                              {JD_STATUS_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              <span style={{ fontSize: 12, color: "#849087" }}>技术</span>
                              <EditableCell value={jd.parsed_data?.tech_direction?.join("、") || ""} onSave={(next) => updateJdFieldValue(jd.jd_id, "tech_direction", splitList(next))} />
                              <span style={{ fontSize: 12, color: "#849087" }}>业务</span>
                              <EditableCell value={jd.parsed_data?.business_direction?.join("、") || ""} onSave={(next) => updateJdFieldValue(jd.jd_id, "business_direction", splitList(next))} />
                            </div>
                          </td>
                          <td>
                            <div className="case-actions">
                              <button className="detail-button" onClick={() => void runJdMatch(jd)}>匹配</button>
                              <button className="detail-button" onClick={() => setJdDirectionRevisionId(jd.revision_id)}>编辑方向</button>
                              <button className="detail-button" onClick={() => toggleJdSource(jd.revision_id)}>
                                {openJdSource[jd.revision_id] ? "收起原文" : "查看详情"}
                              </button>
                              <button className="detail-button danger" onClick={() => void deleteJd(jd)}>删除</button>
                            </div>
                          </td>
                        </tr>
                        {openJdSource[jd.revision_id] && jd.source_text && (
                          <tr>
                            <td colSpan={5}><pre className="jd-source-text">{jd.source_text}</pre></td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        )}

        {activeNav === 2 && (
          <section className="jd-panel">
            <form className="case-filter-bar dashboard-filters" onSubmit={(event) => { event.preventDefault(); void loadDashboard(dashboardDraft); }}>
              <label className="case-filter-field"><span>公司</span><select aria-label="看板公司" value={dashboardDraft.company || ""} onChange={(event) => setDashboardDraft({ ...dashboardDraft, company: event.target.value || undefined, jd_id: undefined })}>
                <option value="">全部公司</option>
                {[...new Set(jds.map((jd) => jd.company))].sort().map((company) => <option key={company}>{company}</option>)}
              </select></label>
              <label className="case-filter-field"><span>岗位</span><select aria-label="看板岗位" value={dashboardDraft.jd_id || ""} onChange={(event) => setDashboardDraft({ ...dashboardDraft, jd_id: event.target.value || undefined })}>
                <option value="">全部岗位</option>
                {jds.filter((jd) => !dashboardDraft.company || jd.company === dashboardDraft.company).map((jd) => <option key={jd.jd_id} value={jd.jd_id}>{jd.company} · {jd.title}</option>)}
              </select></label>
              <label className="case-filter-field"><span>开始日期</span><input aria-label="开始日期" type="date" value={dashboardDraft.date_from || ""} onChange={(event) => setDashboardDraft({ ...dashboardDraft, date_from: event.target.value || undefined })} /></label>
              <label className="case-filter-field"><span>结束日期</span><input aria-label="结束日期" type="date" value={dashboardDraft.date_to || ""} onChange={(event) => setDashboardDraft({ ...dashboardDraft, date_to: event.target.value || undefined })} /></label>
              <button type="submit" className="import-button" disabled={dashboardBusy}>应用筛选</button>
              <button type="button" className="import-button" disabled={dashboardBusy} onClick={() => void loadDashboard()}>刷新看板</button>
              <button type="button" className="detail-button" disabled={dashboardBusy || !dashboard} onClick={() => void api.dashboardExport(dashboardFilters).catch((caught) => setError(caught instanceof Error ? caught.message : "导出失败"))}>导出 Excel</button>
            </form>
            <p className="dashboard-hint">统计按上海自然日；导出和趋势使用最近一次已应用的筛选。{dashboardBusy ? "正在加载…" : ""}</p>
            {dashboard ? (
              <>
                <div className="health-grid">
                  <div className="health-card"><small>候选人总数</small><strong>{dashboard.candidate_total}</strong></div>
                  <div className="health-card"><small>每月新增候选人</small><strong>{dashboard.monthly_new_candidates.length ? dashboard.monthly_new_candidates[dashboard.monthly_new_candidates.length - 1].count : 0}</strong></div>
                  <div className="health-card"><small>推荐总数</small><strong>{dashboard.recommendation_total}</strong></div>
                  <div className="health-card"><small>offer 总数</small><strong>{dashboard.offer_total}</strong></div>
                  <div className="health-card"><small>当前有效 offer</small><strong>{dashboard.active_offer_total}</strong></div>
                  <div className="health-card"><small>已入职人数</small><strong>{dashboard.onboarded_total}</strong></div>
                </div>

                <div className="results-card chart-card">
                  <div className="section-heading">
                    <h2>推荐量 / offer 量趋势</h2>
                    <div className="case-actions">
                      <div className="trend-toggle" role="group" aria-label="趋势粒度">
                        {(["week", "month", "quarter"] as const).map((granularity) => (
                          <button
                            key={granularity}
                            disabled={dashboardBusy}
                            className={trendGranularity === granularity ? "trend-toggle-btn active" : "trend-toggle-btn"}
                            onClick={() => void reloadTrend(granularity)}
                          >
                            {granularity === "week" ? "周" : granularity === "month" ? "月" : "季度"}
                          </button>
                        ))}
                      </div>
                      <button className="detail-button" onClick={() => trendSvgRef.current && exportSvgAsPng(trendSvgRef.current, "趋势图.png")}>导出图片</button>
                    </div>
                  </div>
                  <div className="chart-box">
                    {renderTrendChart(dashboardTrend, trendSvgRef)}
                  </div>
                </div>

                <div className="results-card chart-card">
                  <div className="section-heading">
                    <h2>每岗位每轮通过率</h2>
                    <button className="detail-button" onClick={() => passRateSvgRef.current && exportSvgAsPng(passRateSvgRef.current, "每轮通过率.png")}>导出图片</button>
                  </div>
                  <div className="chart-box">
                    {renderPassRateChart(dashboardByJdData, passRateSvgRef)}
                  </div>
                  {dashboardByJdData.length > 0 && (
                    <table>
                      <thead>
                        <tr>
                          <th>岗位</th>
                          <th>轮次</th>
                          <th>进入</th>
                          <th>通过</th>
                          <th>未通过</th>
                          <th>待反馈</th>
                          <th>通过率</th>
                          <th>最终 offer 率</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dashboardByJdData.flatMap((jd) => {
                          if (jd.rounds.length === 0) {
                            return (
                              <tr key={jd.jd_id}>
                                <td>{jd.company} · {jd.title}</td>
                                <td colSpan={7}>暂无面试数据</td>
                              </tr>
                            );
                          }
                          return jd.rounds.map((round, index) => (
                            <tr key={`${jd.jd_id}-${round.round_key ?? `${round.round_no}-${index}`}`}>
                              {index === 0 && <td rowSpan={jd.rounds.length}>{jd.company} · {jd.title}</td>}
                              <td>{round.round_name}</td>
                              <td>{round.entered}</td>
                              <td>{round.passed}</td>
                              <td>{round.failed}</td>
                              <td>{round.pending}</td>
                              <td>{round.pass_rate === null ? "—" : `${(round.pass_rate * 100).toFixed(1)}%`}</td>
                              {index === 0 && <td rowSpan={jd.rounds.length}>{jd.final_offer_rate === null ? "—" : `${(jd.final_offer_rate * 100).toFixed(1)}%`}</td>}
                            </tr>
                          ));
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              </>
            ) : (
              <div className="empty-state"><strong>加载看板数据</strong><p>点击「刷新看板」查看推荐统计与面试漏斗。</p></div>
            )}
          </section>
        )}

        {activeNav === 6 && (
          <section className="jd-panel">
            <div className="section-heading"><h2>流程列表</h2><button className="detail-button" onClick={() => void loadCases()}>刷新流程</button></div>
            <div className="case-filter-bar">
              <label className="case-filter-field">
                <span>岗位</span>
                <select aria-label="流程岗位" value={caseJdFilter} onChange={(event) => { setCaseJdFilter(event.target.value); void loadCases(event.target.value); }}>
                  <option value="">全部岗位</option>{jds.map((jd) => <option key={jd.jd_id} value={jd.jd_id}>{jd.company} · {jd.title}</option>)}
                </select>
              </label>
              <span className="case-filter-count">共 {cases.length} 条流程</span>
            </div>
            {cases.length === 0 ? <p>暂无招聘流程，可从匹配结果建立流程。</p> : <table><thead><tr><th>候选人</th><th>岗位</th><th>阶段</th><th>操作</th></tr></thead><tbody>
              {cases.map((item) => <tr key={item.id}><td>{item.candidate_name || item.candidate_id}</td><td>{item.company || ""} · {item.jd_title || item.jd_id}</td><td>{item.stage}</td><td><button className="detail-button" onClick={() => void openCaseDrawer(item.id)}>查看流程</button></td></tr>)}
            </tbody></table>}
          </section>
        )}

        {activeNav === 3 && (
          <section className="jd-panel">
            <div className="mapping-help">
              <strong>操作：</strong>Tab 新增子节点（部门→子部门 · 人员→下属）· Enter 新增同级 · 「＋人员」在部门下加人 · 双击/F2 改名 · 拖拽调整层级 · Shift 返回上级 · ←/→ 同级切换 · Space 折叠 · Ctrl+Z 撤销
            </div>

            <div className="mapping-toolbar">
              <form className="jd-form" onSubmit={(event) => void createCompany(event)}>
                <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="公司名称，如：字节跳动" aria-label="公司名称" />
                <button type="submit">新建公司</button>
              </form>
              <button className="import-button" onClick={() => void loadCompanies()}>刷新公司</button>
              {selectedOrgNode && selectedOrgNode.kind !== "company" && (
                <button className="import-button" onClick={() => void addOrgPerson(selectedOrgNode)}>＋人员</button>
              )}
              {selectedCompanyId && (
                <div className="case-actions">
                  <button className="detail-button" onClick={() => void undo()}>撤销</button>
                  <button className="detail-button" onClick={() => void redo()}>重做</button>
                  <button className="detail-button" onClick={() => void api.exportOrgInternal(selectedCompanyId)}>内部 Excel</button>
                  <button className="detail-button" onClick={() => void api.exportOrgClient(selectedCompanyId)}>客户 Excel</button>
                  <button className="detail-button" onClick={() => void api.exportOrgArchPdf(selectedCompanyId)}>架构图 PDF</button>
                </div>
              )}
            </div>

            <div className="case-section">
              <div className="section-heading"><h3>导入组织</h3></div>
              <div className="jd-form">
                <textarea
                  value={orgImportText}
                  onChange={(e) => setOrgImportText(e.target.value)}
                  placeholder="粘贴组织描述文本（如：公司名、部门、人员）"
                  aria-label="组织文本"
                  rows={3}
                />
                <div className="jd-row">
                  <label className="import-button">
                    上传文件导入
                    <input
                      type="file"
                      accept=".txt,.docx"
                      aria-label="导入组织文件"
                      onChange={(e) => { const f = e.target.files?.[0]; if (f) void parseOrgImportFile(f); }}
                    />
                  </label>
                  {orgImportFileName && (
                    <>
                      <span className="muted">{orgImportFileName}</span>
                      <button type="button" className="detail-button" onClick={() => setOrgImportFileName("")}>移除</button>
                    </>
                  )}
                  <button type="button" className="import-button" disabled={orgImportBusy} onClick={() => void parseOrgImportText()}>
                    {orgImportBusy ? "解析中…" : "解析粘贴文本"}
                  </button>
                  {orgImportDraft && (
                    <button type="button" className="import-button" disabled={orgImportBusy} onClick={() => void commitOrgImport()}>
                      确认导入
                    </button>
                  )}
                </div>
              </div>
              {orgImportQuestions.length > 0 && (
                <div className="case-section">
                  <div className="section-heading"><h3>解析疑问</h3></div>
                  {orgImportQuestions.map((q, i) => (
                    <div key={i} className="jd-row" style={{ marginTop: 6 }}>
                      <span className="muted">{q.question}{q.hint ? `（${q.hint}）` : ""}</span>
                      <input
                        value={orgImportAnswers[i] ?? ""}
                        onChange={(e) => setOrgImportAnswers((current) => { const next = [...current]; next[i] = e.target.value; return next; })}
                        placeholder="请回答"
                        aria-label={`解析疑问${i}`}
                      />
                    </div>
                  ))}
                  <div className="jd-row" style={{ marginTop: 6 }}>
                    <button type="button" className="import-button" disabled={orgImportBusy} onClick={() => void answerOrgImportDraft()}>
                      {orgImportBusy ? "解析中…" : "提交回答并继续解析"}
                    </button>
                  </div>
                </div>
              )}
              {orgImportDraft && (
                <div className="case-section org-import-preview">
                  <div className="section-heading">
                    <h3>解析结果（可编辑后导入）</h3>
                    <span className="muted">目标公司：{selectedCompanyId ? (companies.find((c) => c.id === selectedCompanyId)?.name ?? "已选择") : "未选择"}</span>
                  </div>
                  <div className="jd-form" style={{ margin: "0 0 12px" }}>
                    <div className="jd-row">
                      <input
                        value={orgReviseInstruction}
                        onChange={(e) => setOrgReviseInstruction(e.target.value)}
                        placeholder="用一句话修正，如：把「叶程」改名为「贺喜」、合并 A 与 B 部门"
                        aria-label="修正指令"
                      />
                      <button type="button" className="import-button" disabled={orgImportBusy || !orgReviseInstruction.trim()} onClick={() => void reviseOrgImportDraft()}>
                        {orgImportBusy ? "修订中…" : "应用修正"}
                      </button>
                    </div>
                  </div>
                  <label className="org-field">
                    <span className="org-field-label">公司名称</span>
                    <input value={orgImportDraft.company_name} onChange={(e) => updateOrgImportCompanyName(e.target.value)} aria-label="导入公司名称" />
                  </label>

                  <h4>部门（{orgImportDraft.departments.length}）</h4>
                  {orgImportDraft.departments.length === 0 ? (
                    <p className="muted">未识别到部门</p>
                  ) : (
                    orgImportDraft.departments.map((dept, i) => (
                      <div className="case-row" key={i}>
                        <input value={dept.name} onChange={(e) => updateOrgImportDepartment(i, "name", e.target.value)} aria-label={`部门${i}名称`} />
                        <input value={dept.parent_name ?? ""} onChange={(e) => updateOrgImportDepartment(i, "parent_name", e.target.value || null)} placeholder="上级部门" aria-label={`部门${i}上级`} />
                        <input value={dept.leader_name ?? ""} onChange={(e) => updateOrgImportDepartment(i, "leader_name", e.target.value || null)} placeholder="负责人" aria-label={`部门${i}负责人`} />
                        <input value={dept.team_size ?? ""} onChange={(e) => updateOrgImportDepartment(i, "team_size", e.target.value ? Number(e.target.value) : null)} placeholder="人数" type="number" aria-label={`部门${i}人数`} />
                      </div>
                    ))
                  )}

                  <h4>人员（{orgImportDraft.employees.length}）</h4>
                  {orgImportDraft.employees.length === 0 ? (
                    <p className="muted">未识别到人员</p>
                  ) : (
                    orgImportDraft.employees.map((emp, i) => (
                      <div className="case-row" key={i}>
                        <input value={emp.name} onChange={(e) => updateOrgImportEmployee(i, "name", e.target.value)} aria-label={`人员${i}姓名`} />
                        <input value={emp.alias ?? ""} onChange={(e) => updateOrgImportEmployee(i, "alias", e.target.value || null)} placeholder="花名" aria-label={`人员${i}花名`} />
                        <input value={emp.title ?? ""} onChange={(e) => updateOrgImportEmployee(i, "title", e.target.value || null)} placeholder="职位" aria-label={`人员${i}职位`} />
                        <input value={emp.department_name ?? ""} onChange={(e) => updateOrgImportEmployee(i, "department_name", e.target.value || null)} placeholder="部门" aria-label={`人员${i}部门`} />
                        <input value={emp.report_to_name ?? ""} onChange={(e) => updateOrgImportEmployee(i, "report_to_name", e.target.value || null)} placeholder="汇报给" aria-label={`人员${i}汇报人`} />
                      </div>
                    ))
                  )}
                </div>
              )}
              {orgImportMessage && <p role="status" className="muted">{orgImportMessage}</p>}
            </div>

            {companies.length === 0 ? (
              <div className="empty-state"><strong>还没有公司</strong><p>先在上方新建一家公司，再录入部门与人员。</p></div>
            ) : (
              <div className={["mapping-grid", leftCollapsed ? "no-left" : "", rightCollapsed ? "no-right" : ""].join(" ").trim()}>
                {leftCollapsed ? (
                  <button className="mapping-rail" onClick={() => setLeftCollapsed(false)} title="展开左侧">»</button>
                ) : (
                  <div className="mapping-panel">
                    <div className="mapping-panel-head">
                      <h3>公司</h3>
                      <button className="mapping-collapse" onClick={() => setLeftCollapsed(true)} title="收起左侧">«</button>
                    </div>
                    {companies.map((c) => (
                      <div key={c.id} className="case-row">
                        <button
                          className={c.id === selectedCompanyId ? "nav-item active" : "nav-item"}
                          onClick={() => void selectCompany(c.id)}
                        >
                          {c.name}
                        </button>
                        <button className="detail-button" onClick={() => void toggleOrgSource(c.id)}>原文</button>
                        <button className="detail-button" onClick={() => void deleteCompany(c.id)}>删除</button>
                      </div>
                    ))}
                    {orgSource && orgSource.companyId && (
                      <div className="org-source-preview">
                        <div className="section-heading">
                          <strong>导入原文</strong>
                          <button className="detail-button" onClick={() => setOrgSource(null)}>收起</button>
                        </div>
                        {orgSource.text ? (
                          <pre className="jd-source-text">{orgSource.text}</pre>
                        ) : (
                          <p className="muted">该公司尚未保存导入原文。</p>
                        )}
                      </div>
                    )}

                    <h4>搜索</h4>
                    <input value={orgSearch} onChange={(e) => setOrgSearch(e.target.value)} placeholder="姓名 / 岗位 / 职级" aria-label="搜索节点" />

                    <h4>筛选</h4>
                    <select value={orgFilterKind} onChange={(e) => setOrgFilterKind(e.target.value)} aria-label="节点类型">
                      <option value="">全部类型</option>
                      <option value="department">部门</option>
                      <option value="employee">人员</option>
                    </select>
                    <label className="org-filter-key">
                      <input type="checkbox" checked={orgFilterKey} onChange={(e) => setOrgFilterKey(e.target.checked)} /> 仅核心岗位
                    </label>
                  </div>
                )}

                <OrgMindMap
                  tree={displayOrgTree}
                  selectedId={selectedOrgNodeId}
                  onSelect={(node) => setSelectedOrgNodeId(node.id)}
                  onRename={(node, name) => void renameOrgNode(node, name)}
                  onAddChild={(node) => void addOrgChild(node)}
                  onAddSibling={(node) => void addOrgSibling(node)}
                  onDelete={(node) => void deleteOrgNode(node)}
                  onMove={(source, target) => void moveOrgNode(source, target)}
                  onUndo={() => void undo()}
                  onRedo={() => void redo()}
                  pendingEditId={pendingEditId}
                  onPendingEditConsumed={() => setPendingEditId(null)}
                />

                {rightCollapsed ? (
                  <button className="mapping-rail" onClick={() => setRightCollapsed(false)} title="展开右侧">«</button>
                ) : (
                  <OrgDetailPanel
                    node={selectedOrgNode}
                    employee={selectedOrgEmployee}
                    department={selectedOrgDepartment}
                    employees={employees}
                    departments={departments}
                    onUpdateEmployee={(id, changes) => void updateOrgEmployeeField(id, changes)}
                    onUpdateDepartment={(id, changes) => void updateOrgDepartmentField(id, changes)}
                    onDelete={(node) => void deleteOrgNode(node)}
                    onBindEmployee={(id, phone, name) => bindOrgEmployee(id, phone, name)}
                    onPreviewResume={(revisionId, name) => void previewResumeFile(revisionId, name)}
                    onCollapse={() => setRightCollapsed(true)}
                  />
                )}
              </div>
            )}
          </section>
        )}

        {activeNav === 4 && (
          <section className="jd-panel">
            <form className="jd-form" onSubmit={(event) => void searchBd(event)}>
              <input value={bdQuery} onChange={(e) => setBdQuery(e.target.value)} placeholder="输入自然语言需求，如「找上海做大模型算法的公司，最好在招人」" aria-label="BD 深度检索" />
              <LoadingButton type="submit" loading={bdLoading}>深度检索</LoadingButton>
            </form>

            <LongTaskProgress message={bdProgress?.message ?? null} />

            {bdSessionId && (
              <div className="bd-toolbar">
                <form className="jd-form" onSubmit={(event) => void followUpBd(event)}>
                  <input value={bdFollowUp} onChange={(e) => setBdFollowUp(e.target.value)} placeholder="追问：补充或修正检索方向…" aria-label="BD 追问" />
                  <LoadingButton type="submit" loading={bdLoading}>追问</LoadingButton>
                </form>
              </div>
            )}

            {bdLeads.length === 0 ? (
              <div className="empty-state"><strong>暂无线索</strong><p>输入需求开始深度检索，系统会规划搜索、抓取页面并综合出带证据的线索。</p></div>
            ) : (
              <div className="results-card">
                <div className="section-heading"><h2>线索</h2><span>{bdLeads.length} 条</span></div>
                <div className="bd-leads">
                  {bdLeads.map((lead) => (
                    <div key={lead.id} className="bd-lead-card">
                      <div className="bd-lead-head">
                        <button type="button" className="bd-company-link" onClick={() => void lookupPool(lead.id)}>{lead.company_name}</button>
                        <span className="bd-role">{lead.job_title ?? "岗位未知"}</span>
                        {lead.is_hiring === true && <span className="bd-tag bd-tag-ok">在招</span>}
                        {lead.is_hiring === false && <span className="bd-tag bd-tag-bad">未在招</span>}
                        {lead.confidence != null && <span className="bd-tag">置信度 {Math.round(lead.confidence * 100)}%</span>}
                      </div>
                      {(lead.posted_time || lead.salary_range || lead.level) && (
                        <div className="bd-meta">
                          {lead.posted_time && <span className="bd-meta-item">开放时间：{lead.posted_time}</span>}
                          {lead.salary_range && <span className="bd-meta-item">薪资：{lead.salary_range}</span>}
                          {lead.level && <span className="bd-meta-item">职级：{lead.level}</span>}
                        </div>
                      )}
                      {lead.requirements.length > 0 && (
                        <ul className="bd-requirements">
                          {lead.requirements.map((req, index) => <li key={index}>{req}</li>)}
                        </ul>
                      )}
                      {lead.summary && <p className="bd-summary">{lead.summary}</p>}
                      {lead.url && (
                        <div className="bd-link-row">
                          <button type="button" className="detail-button" onClick={() => void openExternal(lead.url as string)}>打开链接</button>
                          <button type="button" className="detail-button" onClick={() => void copyLink(lead.url as string)}>复制链接</button>
                        </div>
                      )}
                      {lead.evidence.length > 0 && (
                        <ul className="bd-evidence">
                          {lead.evidence.map((item, index) => (
                            <li key={index}>
                              {item.claim ? <strong>{item.claim}</strong> : null}
                              {item.quote ? <span>：{item.quote}</span> : null}
                              {item.source_url ? <button type="button" className="bd-source-link" onClick={() => void openExternal(item.source_url as string)}>（来源）</button> : null}
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="bd-pool">
                        <div className="bd-pool-head">
                          <button
                            type="button"
                            className="detail-button"
                            disabled={bdPoolBusyId === lead.id}
                            onClick={() => void lookupPool(lead.id)}
                          >
                            {bdPoolBusyId === lead.id ? "查询中…" : "查人才库"}
                          </button>
                          {(bdPoolByLead[lead.id] ?? []).length > 0 && (
                            <button
                              type="button"
                              className="detail-button"
                              onClick={() => togglePoolCollapse(lead.id)}
                            >
                              {collapsedPool[lead.id] ? "展开" : "收起"}
                            </button>
                          )}
                        </div>
                        {!collapsedPool[lead.id] && (bdPoolByLead[lead.id] ?? []).length > 0 && (
                          <ul className="bd-pool-results">
                            {bdPoolByLead[lead.id].map((c) => (
                              <li key={c.candidate_id}>
                                <span>{c.name}{c.phone ? ` · ${c.phone}` : ""}</span>
                                <span className="bd-pool-actions">
                                  <button
                                    type="button"
                                    className="detail-button"
                                    onClick={() => void previewResumeFile(c.revision_id, c.name)}
                                  >
                                    预览简历
                                  </button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {bdPoolByLead[lead.id] && bdPoolByLead[lead.id].length === 0 && (
                          <p className="muted">人才库中未找到相关候选人</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {activeNav === 5 && (
          <section className="jd-panel">
            <div className="case-section">
              <div className="section-heading">
                <h2>启动检查</h2>
                <button className="import-button" onClick={() => void loadOnboarding()}>运行检查</button>
              </div>
              {onboarding && (
                <div className="health-grid">
                  <div className="health-card"><small>数据目录</small><strong>{onboarding.data_root}</strong></div>
                  <div className="health-card"><small>LLM</small><strong>{onboarding.llm_enabled ? "已配置" : "未配置"}</strong></div>
                  <div className="health-card"><small>向量/重排</small><strong>{onboarding.search_enabled ? "已配置" : "本地"}</strong></div>
                  <div className="health-card"><small>BD 搜索</small><strong>{onboarding.bd_search_enabled ? "已配置" : "未配置"}</strong></div>
                  {Object.entries(onboarding.health).map(([name, component]) => (
                    <div key={name} className="health-card">
                      <small>{HEALTH_LABELS[name] ?? name}</small>
                      <strong className={component.status === "healthy" ? "ok" : "bad"}>{component.status === "healthy" ? "正常" : "异常"}</strong>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <form className="jd-form" onSubmit={(event) => void saveSettings(event)}>
              <div className="section-heading">
                <h2>模型 API 配置</h2>
                <div className="case-actions">
                  <button type="button" className="import-button" onClick={() => void loadSettings()}>加载</button>
                  <button type="button" className="import-button" onClick={() => void testProviders()}>测试 API</button>
                  <button type="submit">保存设置</button>
                </div>
              </div>

              <div className="jd-row">
                <input value={settings.deepseek_api_key ?? ""} onChange={(e) => setSettings({ ...settings, deepseek_api_key: e.target.value })} placeholder="DeepSeek API Key" aria-label="DeepSeek API Key" />
              </div>
              <div className="section-heading" style={{ marginTop: 12 }}><h3>文本 / 视觉模型</h3></div>
              <div className="jd-row">
                <select
                  aria-label="文本供应商"
                  value=""
                  onChange={(e) => {
                    const vendor = vendors.find((v) => v.key === e.target.value);
                    if (vendor) setSettings({ ...settings, text_base_url: vendor.base_url, text_model: vendor.text_model || undefined });
                  }}
                >
                  <option value="">文本供应商预设</option>
                  {vendors.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
                </select>
                <input value={settings.text_api_key ?? ""} onChange={(e) => setSettings({ ...settings, text_api_key: e.target.value })} placeholder="文本 API Key" aria-label="文本 API Key" />
              </div>
              <div className="jd-row">
                <input value={settings.text_base_url ?? ""} onChange={(e) => setSettings({ ...settings, text_base_url: e.target.value })} placeholder="文本 Base URL" aria-label="文本 Base URL" />
                <input value={settings.text_model ?? ""} onChange={(e) => setSettings({ ...settings, text_model: e.target.value })} placeholder="文本模型" aria-label="文本模型" />
              </div>
              <div className="jd-row">
                <select
                  aria-label="视觉供应商"
                  value=""
                  onChange={(e) => {
                    const vendor = vendors.find((v) => v.key === e.target.value);
                    if (vendor) setSettings({ ...settings, vision_base_url: vendor.base_url, vision_model: vendor.vision_model || undefined });
                  }}
                >
                  <option value="">视觉供应商预设</option>
                  {vendors.filter((v) => v.vision_model).map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
                </select>
                <input value={settings.vision_api_key ?? ""} onChange={(e) => setSettings({ ...settings, vision_api_key: e.target.value })} placeholder="视觉 API Key" aria-label="视觉 API Key" />
              </div>
              <div className="jd-row">
                <input value={settings.vision_base_url ?? ""} onChange={(e) => setSettings({ ...settings, vision_base_url: e.target.value })} placeholder="视觉 Base URL" aria-label="视觉 Base URL" />
                <input value={settings.vision_model ?? ""} onChange={(e) => setSettings({ ...settings, vision_model: e.target.value })} placeholder="视觉模型" aria-label="视觉模型" />
              </div>
              <div className="jd-row">
                <input value={settings.siliconflow_api_key ?? ""} onChange={(e) => setSettings({ ...settings, siliconflow_api_key: e.target.value })} placeholder="SiliconFlow API Key（Embedding / Rerank）" aria-label="SiliconFlow API Key" />
                <input value={settings.tavily_api_key ?? ""} onChange={(e) => setSettings({ ...settings, tavily_api_key: e.target.value })} placeholder="Tavily API Key" aria-label="Tavily API Key" />
              </div>
              <div className="jd-row">
                <input value={settings.serpapi_api_key ?? ""} onChange={(e) => setSettings({ ...settings, serpapi_api_key: e.target.value })} placeholder="SerpApi API Key（Tavily 备选）" aria-label="SerpApi API Key" />
              </div>
              <div className="section-heading" style={{ marginTop: 12 }}><h3>邮箱（IMAP 收件 + SMTP 发件）</h3></div>
              <div className="jd-row">
                <select
                  aria-label="邮箱预设"
                  value=""
                  onChange={(e) => {
                    const host = e.target.value;
                    if (host) setSettings({ ...settings, imap_host: host, smtp_host: host.replace("imap.", "smtp.") });
                  }}
                >
                  <option value="">邮箱预设</option>
                  <option value="imap.qq.com">QQ 邮箱</option>
                  <option value="imap.163.com">163 邮箱</option>
                </select>
              </div>
              <div className="jd-row">
                <input value={settings.imap_host ?? ""} onChange={(e) => setSettings({ ...settings, imap_host: e.target.value })} placeholder="IMAP 主机" aria-label="IMAP 主机" />
                <input value={settings.imap_account ?? ""} onChange={(e) => setSettings({ ...settings, imap_account: e.target.value })} placeholder="IMAP 账号" aria-label="IMAP 账号" />
              </div>
              <div className="jd-row">
                <input value={settings.imap_auth_code ?? ""} onChange={(e) => setSettings({ ...settings, imap_auth_code: e.target.value })} placeholder="IMAP 授权码" aria-label="IMAP 授权码" />
                <input value={settings.smtp_host ?? ""} onChange={(e) => setSettings({ ...settings, smtp_host: e.target.value })} placeholder="SMTP 主机" aria-label="SMTP 主机" />
              </div>
              <div className="jd-row">
                <input value={settings.smtp_port ?? ""} onChange={(e) => setSettings({ ...settings, smtp_port: e.target.value ? Number(e.target.value) : undefined })} placeholder="SMTP 端口" aria-label="SMTP 端口" type="number" />
                <input value={settings.smtp_account ?? ""} onChange={(e) => setSettings({ ...settings, smtp_account: e.target.value })} placeholder="SMTP 账号" aria-label="SMTP 账号" />
              </div>
              <div className="jd-row">
                <input value={settings.smtp_auth_code ?? ""} onChange={(e) => setSettings({ ...settings, smtp_auth_code: e.target.value })} placeholder="SMTP 授权码" aria-label="SMTP 授权码" />
                <input value={settings.reminder_to ?? ""} onChange={(e) => setSettings({ ...settings, reminder_to: e.target.value })} placeholder="提醒收件人邮箱" aria-label="提醒收件人邮箱" />
              </div>
              <div className="jd-row">
                <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={settings.smtp_ssl !== false} onChange={(e) => setSettings({ ...settings, smtp_ssl: e.target.checked })} />
                  SMTP SSL
                </label>
              </div>
              <p className="muted">QQ/163 邮箱需在邮箱设置中开启 IMAP/SMTP，并使用「授权码」作为密码，而非登录密码。</p>
              <div className="jd-row" style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                {(settings.imap_whitelist ?? "").split(",").map((s) => s.trim()).filter(Boolean).map((tag) => (
                  <span key={tag} className="bd-tag" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                    {tag}
                    <button type="button" className="bd-source-link" onClick={() => removeMailWhitelistTag(tag)}>×</button>
                  </span>
                ))}
              </div>
              <div className="jd-row">
                <input value={mailWhitelistInput} onChange={(e) => setMailWhitelistInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addMailWhitelistTag(); } }} placeholder="添加发件人白名单（域名或完整邮箱）" aria-label="添加发件人白名单" />
                <button type="button" className="detail-button" onClick={addMailWhitelistTag}>添加</button>
              </div>
              <div className="jd-row">
                <button type="button" className="detail-button" onClick={() => void testMailConfig()}>连接测试</button>
                <button type="button" className="detail-button" onClick={() => void syncMailNow()}>立即同步</button>
                <button type="button" className="detail-button" onClick={() => void loadMailStatus()}>刷新同步状态</button>
              </div>
              {mailTestResult && (
                <div className="health-grid">
                  <div className="health-card"><small>IMAP</small><strong>{mailTestResult.imap.ok ? "正常" : "异常"}：{mailTestResult.imap.message}</strong></div>
                  <div className="health-card"><small>SMTP</small><strong>{mailTestResult.smtp.ok ? "正常" : "异常"}：{mailTestResult.smtp.message}</strong></div>
                </div>
              )}
              {mailSyncMessage && <p className="muted">{mailSyncMessage}</p>}
              {mailStatus && (
                <p className="muted">邮箱已{mailStatus.configured ? "配置" : "未配置"} · 已同步收件 UID：{mailStatus.last_uid}</p>
              )}
              {settingsMessage && <p className="muted">{settingsMessage}</p>}
              {providerChecks.length > 0 && (
                <div className="health-grid">
                  {providerChecks.map((check) => (
                    <div className="health-card" key={check.name}>
                      <strong>{PROVIDER_LABELS[check.name] ?? check.name}：{check.message}</strong>
                    </div>
                  ))}
                </div>
              )}
            </form>

            <div className="section-heading" style={{ marginTop: 20 }}><h2>数据目录</h2></div>
            <div className="jd-row" style={{ marginTop: 12 }}>
              <input value={dataRootInput} onChange={(e) => setDataRootInput(e.target.value)} placeholder="数据目录绝对路径（留空使用默认）" aria-label="数据目录" />
              <button type="button" className="import-button" onClick={() => void saveDataRoot()}>设置数据目录</button>
            </div>
            {dataRootMessage && <p className="muted">{dataRootMessage}</p>}

            <IndexSyncPanel api={api} />
            <RemindersPanel api={api} onOpenCase={(caseId) => void openCaseDrawer(caseId)} />

            <div className="section-heading" style={{ marginTop: 20 }}>
              <h2>健康检测台</h2>
              <div className="case-actions">
                <button className="import-button" onClick={() => void checkHealth()}>运行检测</button>
                <button className="import-button" onClick={() => void exportDiagnostics()}>导出诊断信息</button>
              </div>
            </div>
            {health && (
              <div className="health-grid">
                {Object.entries(health).map(([name, component]) => (
                  <div key={name} className="health-card">
                    <small>{HEALTH_LABELS[name] ?? name}</small>
                    <strong className={component.status === "healthy" ? "ok" : "bad"}>{component.status === "healthy" ? "正常" : "异常"}</strong>
                    {component.message && <p>{component.message}</p>}
                  </div>
                ))}
              </div>
            )}

            <div className="case-section">
              <div className="section-heading">
                <h2>回收站</h2>
                <button className="import-button" onClick={() => void loadDeleted()}>加载回收站</button>
              </div>
              {deletedItems.length === 0 ? (
                <p className="muted">暂无已删除的候选人或岗位</p>
              ) : (
                <div className="case-events">
                  {deletedItems.map((item) => (
                    <div key={`${item.entity_type}-${item.entity_id}`} className="case-row">
                      <div>
                        <strong>{item.label}</strong>
                        <small>{item.entity_type === "candidate" ? "候选人" : "岗位"}</small>
                      </div>
                      <button className="detail-button" onClick={() => void restoreItem(item)}>恢复</button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="case-section">
              <div className="section-heading">
                <h2>备份与恢复</h2>
                <div className="case-actions">
                  <button className="import-button" disabled={backupBusy} onClick={() => void loadBackups()}>加载备份</button>
                  <button className="import-button" disabled={backupBusy} onClick={() => void createBackup()}>{backupBusy ? "备份中…" : "立即备份"}</button>
                </div>
              </div>
              {backups.length === 0 ? (
                <p className="muted">暂无备份快照</p>
              ) : (
                <div className="case-events">
                  {backups.map((b) => (
                    <div key={b.filename} className="case-row">
                      <div>
                        <strong>{b.filename}</strong>
                        <small>{b.created}</small>
                      </div>
                      <button className="detail-button" disabled={backupBusy} onClick={() => void restoreBackupItem(b.filename)}>恢复</button>
                    </div>
                  ))}
                </div>
              )}
              <div className="jd-form" style={{ marginTop: 16 }}>
                <input
                  value={portableBackupPath}
                  onChange={(event) => setPortableBackupPath(event.target.value)}
                  placeholder="便携备份文件路径"
                  aria-label="便携备份路径"
                />
                <input
                  value={portablePassphrase}
                  onChange={(event) => setPortablePassphrase(event.target.value)}
                  placeholder="加密口令"
                  aria-label="便携备份口令"
                  type="password"
                />
                <button type="button" disabled={portableBusy} onClick={() => void createPortableBackup()}>{portableBusy ? "创建中…" : "创建加密便携备份"}</button>
                <div className="jd-row">
                  <input
                    value={portableRestorePath}
                    onChange={(event) => setPortableRestorePath(event.target.value)}
                    placeholder="待恢复的便携备份文件"
                    aria-label="便携备份恢复文件"
                  />
                  <input
                    value={portableRestoreTarget}
                    onChange={(event) => setPortableRestoreTarget(event.target.value)}
                    placeholder="恢复目标目录"
                    aria-label="便携备份恢复目录"
                  />
                </div>
                <button type="button" disabled={portableBusy} onClick={() => void restorePortableBackup()}>{portableBusy ? "恢复中…" : "恢复便携备份"}</button>
                {portableMessage && <p role="status">{portableMessage}</p>}
              </div>
            </div>

            <div className="case-section">
              <div className="section-heading"><h2>数据迁移</h2></div>
              <form className="jd-form" onSubmit={(event) => void migrateData(event)}>
                <input value={migrationTarget} onChange={(e) => setMigrationTarget(e.target.value)} placeholder="新数据目录（绝对路径）" aria-label="迁移目标目录" />
                <button type="submit" disabled={migrationBusy}>{migrationBusy ? "迁移中…" : "复制并校验"}</button>
              </form>
              {migrationReport && (
                <div className="case-events">
                  <div className="case-row">
                    <div>
                      <strong>{migrationReport.ok ? "迁移校验通过" : "迁移校验未通过"}</strong>
                      <small>{migrationReport.target_root} · {migrationReport.files_verified}/{migrationReport.files_copied} 文件 · {migrationReport.candidate_count} 候选人</small>
                    </div>
                  </div>
                </div>
              )}
              {migrationMessage && <p role="status" className="muted">{migrationMessage}</p>}
            </div>
          </section>
        )}
      </main>

      {jdDirectionRevisionId && (
        <div className="match-drawer-backdrop" onClick={() => setJdDirectionRevisionId(null)}>
          <aside className="match-drawer" role="dialog" aria-modal="true" aria-label="编辑岗位方向" onClick={(e) => e.stopPropagation()}>
            <div className="match-drawer-header">
              <div><h2>编辑岗位方向</h2><small>{jdDirectionRevisionId}</small></div>
              <button className="detail-button" onClick={() => setJdDirectionRevisionId(null)}>关闭</button>
            </div>
            <div className="match-drawer-body">
              <DirectionEditor api={api} kind="jd" revisionId={jdDirectionRevisionId} onCancel={() => setJdDirectionRevisionId(null)} />
            </div>
          </aside>
        </div>
      )}

      {candidateDirectionRevisionId && (
        <div className="match-drawer-backdrop" onClick={() => setCandidateDirectionRevisionId(null)}>
          <aside className="match-drawer" role="dialog" aria-modal="true" aria-label="编辑候选人方向" onClick={(e) => e.stopPropagation()}>
            <div className="match-drawer-header">
              <div><h2>编辑候选人方向</h2><small>{candidateDirectionRevisionId}</small></div>
              <button className="detail-button" onClick={() => setCandidateDirectionRevisionId(null)}>关闭</button>
            </div>
            <div className="match-drawer-body">
              <DirectionEditor api={api} kind="resume" revisionId={candidateDirectionRevisionId} onCancel={() => setCandidateDirectionRevisionId(null)} />
            </div>
          </aside>
        </div>
      )}

      {matchDrawer && (
        <div className="match-drawer-backdrop" onClick={() => setMatchDrawer(null)}>
          <aside className="match-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="match-drawer-header">
              <div>
                <h2>{matchDrawer.title}</h2>
                <small>{matchDrawer.items.length} 条匹配</small>
              </div>
              <button className="detail-button" onClick={() => setMatchDrawer(null)}>关闭</button>
            </div>
            <div className="match-drawer-body">
              {matchDrawer.items.length === 0 ? (
                <div className="empty-state">
                  <strong>暂无匹配</strong>
                  <p>没有满足条件的匹配结果。</p>
                </div>
              ) : matchDrawer.mode === "candidates" ? (
                <table className="drawer-table">
                  <thead><tr><th>姓名</th><th>学历</th><th>电话</th><th>行业</th><th>技术方向</th><th>业务方向</th><th>操作</th></tr></thead>
                  <tbody>
                    {matchDrawer.items.map((item) => {
                      const p = item.parsed_data;
                      const status = matchDrawer.statuses[item.result_id || ""] ?? "未处理";
                      const industry = p?.current_industry || p?.longest_industry
                        ? `${p.current_industry ? `最近：${p.current_industry}` : ""}${p.longest_industry ? ` 最长：${p.longest_industry}` : ""}`
                        : "—";
                      const tech = p?.tech_direction?.join("、") || "";
                      const biz = p?.business_direction?.join("、") || "";
                      return (
                        <Fragment key={item.candidate_id}>
                          <tr>
                            <td><strong>{item.name}</strong></td>
                            <td>{eduLabel(p) || "—"}</td>
                            <td>{item.phone || "—"}</td>
                            <td>{industry}</td>
                            <td>{tech || "—"}</td>
                            <td>{biz || "—"}</td>
                            <td>
                              <div className="case-actions">
                                <button className="detail-button" onClick={() => void previewResumeFile(item.revision_id, item.name, item.original_filename ?? "")}>查看详情</button>
                                <button className="detail-button" onClick={() => void downloadResumeFile(item.revision_id, item.original_filename ?? item.name)}>下载</button>
                                <button className="detail-button" onClick={() => setCandidateDirectionRevisionId(item.revision_id)}>方向不匹配</button>
                                <button className="detail-button" disabled={creatingCase || !item.result_id} onClick={() => void createCaseFromDrawer(item.result_id || "")}>{matchCaseIds[item.result_id || ""] ? "查看流程" : "建流程"}</button>
                                {status !== "未处理" && <span className="match-status">{status}</span>}
                              </div>
                              {(item.candidate_primary_direction || item.direction_explanation) && (
                                <div className="candidate-line">
                                  <small>方向：{item.candidate_primary_direction ?? "—"}{item.candidate_direction_source ? `（${item.candidate_direction_source}）` : ""} · {item.direction_explanation ?? ""}</small>
                                </div>
                              )}
                            </td>
                          </tr>
                          {(p?.experiences?.length || p?.projects?.length) ? (
                            <tr>
                              <td colSpan={7}>
                                {p.experiences && p.experiences.length > 0 && (
                                  <div className="candidate-line">
                                    <small>工作履历</small>
                                    {p.experiences.map((e, i) => {
                                      const head = [e.title, e.company].filter(Boolean).join(" @ ");
                                      const tail = [e.industry ? `（${e.industry}）` : "", e.summary].filter(Boolean).join("，");
                                      return <div key={i}>{[head, tail].filter(Boolean).join("，")}</div>;
                                    })}
                                  </div>
                                )}
                                {p.projects && p.projects.length > 0 && (
                                  <div className="candidate-line">
                                    <small>项目经验</small>
                                    {p.projects.map((pr, i) => (
                                      <div key={i}>{pr.name ?? ""}{pr.tech_stack ? `（${pr.tech_stack}）` : ""}{pr.business_scene ? `，${pr.business_scene}` : ""}</div>
                                    ))}
                                  </div>
                                )}
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                <table className="drawer-table">
                  <thead><tr><th>岗位名称</th><th>公司名称</th><th>状态</th><th>AI/非AI</th><th>岗位要求（技术+业务）</th><th>操作</th></tr></thead>
                  <tbody>
                    {matchDrawer.items.map((item) => {
                      const status = matchDrawer.statuses[item.result_id] ?? "未处理";
                      return (
                        <Fragment key={item.jd_id}>
                          <tr>
                            <td><strong>{item.title}</strong></td>
                            <td>{item.company}</td>
                            <td>{JD_STATUS_OPTIONS.find((o) => o.value === item.jd_status)?.label ?? item.jd_status}</td>
                            <td>{jdAiLabel(item.ai_category)}</td>
                            <td>{jdRequirementLabel(item.parsed_data)}</td>
                            <td>
                              <div className="case-actions">
                                <button className="detail-button" disabled={creatingCase || (!item.case_id && item.jd_status !== "OPEN")} onClick={() => item.case_id ? void openCaseDrawer(item.case_id) : void createCaseFromDrawer(item.result_id)}>{item.case_id || matchCaseIds[item.result_id] ? "查看流程" : "建流程"}</button>
                                {status !== "未处理" && <span className="match-status">{status}</span>}
                              </div>
                            </td>
                          </tr>
                          {item.source_text && (
                            <tr><td colSpan={6}><pre className="jd-source-text">{item.source_text}</pre></td></tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </aside>
        </div>
      )}

      {caseDrawer && <CaseDrawer key={caseDrawer.id} api={api} initialCase={caseDrawer} onClose={() => setCaseDrawer(null)} onUpdated={(detail) => { setCaseDrawer(detail); setCases((items) => items.map((item) => item.id === detail.id ? detail : item)); }} />}
      {resumeReview && <ResumeReviewDrawer key={resumeReview.revision_id} api={api} initialReview={resumeReview} onClose={() => setResumeReview(null)} onApproved={() => void loadCandidates()} onForceReparse={(revisionId) => { setResumeReview(null); void forceReparse(revisionId); }} />}

      {previewUrl && (
        <div className="preview-overlay" onClick={() => { URL.revokeObjectURL(previewUrl); setPreviewUrl(null); }}>
          <div className="preview-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <span>{previewName}</span>
              <button className="detail-button" onClick={() => { URL.revokeObjectURL(previewUrl); setPreviewUrl(null); }}>关闭</button>
            </div>
            <iframe src={previewUrl} title={previewName} className="preview-frame" />
          </div>
        </div>
      )}
    </div>
  );
}
