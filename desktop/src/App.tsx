import { FormEvent, useEffect, useState } from "react";

import "./styles.css";


export interface ImportedResume {
  candidate_id: string;
  document_id: string;
  revision_id: string;
  blob_id: string;
  task_id: string;
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
  content: string;
  score: number;
  matched_channels: string[];
  total_years: number | null;
  highest_degree: string | null;
  location: string | null;
  result_id?: string | null;
}

export interface CandidateSearchResult {
  items: CandidateSearchItem[];
  degraded_reasons: string[];
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
}

export interface ImportedJd {
  jd_id: string;
  revision_id: string;
}

export interface MatchRun {
  run_id: string;
  items: CandidateSearchItem[];
}

export interface BatchMatchResult {
  revision_id: string;
  run_id: string;
  items: CandidateSearchItem[];
}

export type MatchMarkStatus = "未处理" | "保留" | "短名单" | "排除";

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

export interface BdLead {
  id: string;
  source: string;
  company_name: string;
  job_title: string | null;
  raw_snippet: string | null;
  url: string | null;
  status: string;
}

export interface CaseItem {
  id: string;
  candidate_id: string;
  jd_id: string;
  stage: string;
  note: string | null;
}

export interface StageEventItem {
  id: string;
  stage: string;
  note: string | null;
}

export interface DashboardOverview {
  recommendation_total: number;
  funnel: { stage: string; count: number }[];
  health: {
    candidate_total: number;
    ready_total: number;
    parse_failed: number;
    recent_30d: number;
    open_jd_total: number;
  };
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

export interface AppSettings {
  deepseek_api_key?: string;
  deepseek_base_url?: string;
  deepseek_model?: string;
  siliconflow_api_key?: string;
  siliconflow_base_url?: string;
  siliconflow_embedding_model?: string;
  siliconflow_reranker_model?: string;
  tavily_api_key?: string;
  tavily_base_url?: string;
  serpapi_api_key?: string;
  serpapi_base_url?: string;
  imap_host?: string;
  imap_account?: string;
  imap_auth_code?: string;
  imap_whitelist?: string;
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
  controlTask(taskId: string, action: TaskAction): Promise<TaskStatus>;
  listResumeRevisions(candidateId: string): Promise<ResumeRevision[]>;
  switchResumeRevision(revisionId: string): Promise<ResumeRevision>;
  searchCandidates(query: string): Promise<CandidateSearchResult>;
  importJd(input: { company: string; title: string; sourceText: string }): Promise<ImportedJd>;
  importJdFile(file: File, company: string, title: string): Promise<ImportedJd>;
  matchJd(revisionId: string, limit?: number): Promise<MatchRun>;
  matchBatch(revisionIds: string[], limit?: number): Promise<{ results: BatchMatchResult[] }>;
  markMatchResult(resultId: string, status: MatchMarkStatus): Promise<{ result_id: string; status: MatchMarkStatus }>;
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
  createCase(candidateId: string, jdId: string): Promise<CaseItem>;
  listCases(candidateId?: string): Promise<CaseItem[]>;
  advanceCase(caseId: string, stage: string, note?: string): Promise<CaseItem>;
  undoCase(caseId: string): Promise<CaseItem>;
  getCaseEvents(caseId: string): Promise<StageEventItem[]>;
  dashboardOverview(): Promise<DashboardOverview>;
  dashboardByJd(): Promise<{ jd_id: string; company: string; title: string; stage_counts: Record<string, number> }[]>;
  reverseMatch(candidateId: string): Promise<ReverseMatchItem[]>;
  getCandidateContact(candidateId: string): Promise<CandidateContact>;
  updateCandidateContact(candidateId: string, input: { email: string | null; phone: string | null }): Promise<CandidateContact>;
  listDeleted(): Promise<DeletedItem[]>;
  softDelete(entityType: "candidate" | "jd", entityId: string): Promise<{ entity_type: string; entity_id: string; deleted: boolean }>;
  restoreDeleted(entityType: string, entityId: string): Promise<{ entity_type: string; entity_id: string; deleted: boolean }>;
  applyCorrection(input: { entityType: string; entityId: string; fieldName: string; newValue: string | null; reason?: string }): Promise<CorrectionRecord>;
  undoCorrection(correctionId: string): Promise<CorrectionRecord>;
  exportMappingTree(snapshotId: string): Promise<void>;
  exportMappingTreePdf(snapshotId: string): Promise<void>;
  getSettings(): Promise<AppSettings>;
  updateSettings(values: Partial<AppSettings>): Promise<AppSettings>;
  exportMatchRun(runId: string): Promise<void>;
  listBackups(): Promise<BackupSnapshot[]>;
  createBackup(label?: string): Promise<{ filename: string; path: string }>;
  restoreBackup(filename: string): Promise<{ restored_from: string; safety_backup: string }>;
  createPortableBackup(targetPath: string, passphrase: string): Promise<{ path: string; same_volume: boolean }>;
  restorePortableBackup(backupPath: string, targetRoot: string, passphrase: string): Promise<{ target_root: string; files_restored: number; files_verified: number; ok: boolean }>;
  listReminders(): Promise<ReminderItem[]>;
  createReminder(input: { title: string; remind_at: string; note?: string }): Promise<ReminderItem>;
  dismissReminder(id: string): Promise<ReminderItem>;
  migrateData(targetRoot: string): Promise<MigrationReport>;
  setDataRoot(path: string): Promise<string>;
  onboardingStatus(): Promise<OnboardingStatus>;
  testProviders(): Promise<ProviderCheck[]>;
}


const navigation = ["人才库", "JD 管理", "人岗匹配", "数据看板", "Mapping", "BD 助手", "设置"];

const STAGES = [
  "待评估", "待联系", "已联系", "有意向", "已推荐",
  "初试", "复试", "终试", "Offer", "入职",
  "客户拒绝", "候选人拒绝", "暂缓", "岗位关闭"
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


function taskLabel(task: TaskStatus): string {
  if (task.status === "SUCCESS") return "解析完成";
  if (task.status === "FAILED" || task.status === "DEAD_LETTER") return "解析失败";
  if (task.status === "PAUSED") return "已暂停";
  if (task.status === "CANCELLED") return "已取消";
  return `解析中 ${task.progress}%`;
}


export function App({ api }: { api: RecruitmentApi }) {
  const [activeNav, setActiveNav] = useState(0);

  // 人才库
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CandidateSearchItem[]>([]);
  const [selected, setSelected] = useState<CandidateSearchItem | null>(null);
  const [tasks, setTasks] = useState<TaskStatus[]>([]);
  const [folderPath, setFolderPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  // JD 管理
  const [jdCompany, setJdCompany] = useState("");
  const [jdTitle, setJdTitle] = useState("");
  const [jdSource, setJdSource] = useState("");
  const [jdResult, setJdResult] = useState<ImportedJd | null>(null);

  // 人岗匹配
  const [matchRevision, setMatchRevision] = useState("");
  const [matchRun, setMatchRun] = useState<MatchRun | null>(null);
  const [batchRevisions, setBatchRevisions] = useState("");
  const [batchMatchCount, setBatchMatchCount] = useState<number | null>(null);
  const [matchMarks, setMatchMarks] = useState<Record<string, MatchMarkStatus>>({});

  // 设置 / 健康
  const [health, setHealth] = useState<Record<string, { status: string; message?: string }> | null>(null);

  // 数据看板
  const [diagnostics, setDiagnostics] = useState<DiagnosticsData | null>(null);

  // Mapping
  const [projects, setProjects] = useState<MappingProject[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<MappingSnapshot[]>([]);
  const [mappingText, setMappingText] = useState("");
  const [mappingLabel, setMappingLabel] = useState("");
  const [tree, setTree] = useState<MappingTreeNode[]>([]);

  // BD 助手
  const [bdQuery, setBdQuery] = useState("");
  const [bdLeads, setBdLeads] = useState<BdLead[]>([]);

  // 看板
  const [dashboard, setDashboard] = useState<DashboardOverview | null>(null);

  // 招聘流程（候选人详情）
  const [selectedCases, setSelectedCases] = useState<CaseItem[]>([]);
  const [caseEvents, setCaseEvents] = useState<StageEventItem[]>([]);
  const [reverseMatches, setReverseMatches] = useState<ReverseMatchItem[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [selectedContact, setSelectedContact] = useState<CandidateContact | null>(null);
  const [resumeRevisions, setResumeRevisions] = useState<ResumeRevision[]>([]);
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [correctedName, setCorrectedName] = useState("");
  const [lastCorrectionId, setLastCorrectionId] = useState<string | null>(null);
  const [correctionMessage, setCorrectionMessage] = useState("");

  // 回收站
  const [deletedItems, setDeletedItems] = useState<DeletedItem[]>([]);

  // 设置
  const [settings, setSettings] = useState<AppSettings>({});
  const [providerChecks, setProviderChecks] = useState<ProviderCheck[]>([]);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [dataRootInput, setDataRootInput] = useState("");
  const [dataRootMessage, setDataRootMessage] = useState("");

  // 备份与恢复
  const [backups, setBackups] = useState<BackupSnapshot[]>([]);
  const [portableBackupPath, setPortableBackupPath] = useState("");
  const [portableRestorePath, setPortableRestorePath] = useState("");
  const [portableRestoreTarget, setPortableRestoreTarget] = useState("");
  const [portablePassphrase, setPortablePassphrase] = useState("");
  const [portableMessage, setPortableMessage] = useState("");

  // 提醒
  const [reminders, setReminders] = useState<ReminderItem[]>([]);
  const [reminderTitle, setReminderTitle] = useState("");
  const [reminderAt, setReminderAt] = useState("");

  // 数据迁移
  const [migrationTarget, setMigrationTarget] = useState("");
  const [migrationReport, setMigrationReport] = useState<MigrationReport | null>(null);

  // 启动检查
  const [onboarding, setOnboarding] = useState<OnboardingStatus | null>(null);

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const response = await api.searchCandidates(query.trim());
      setResults(response.items);
      setSelected(null);
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
        const task = await api.getTask(imported.task_id);
        setTasks((current) => [task, ...current.filter((entry) => entry.id !== task.id)]);
        pollTask(imported.task_id);
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
      for (const imported of result.imported) {
        const task = await api.getTask(imported.task_id);
        setTasks((current) => [task, ...current.filter((entry) => entry.id !== task.id)]);
        pollTask(imported.task_id);
      }
      if (result.skipped.length > 0 || result.errors.length > 0) {
        setError(`已导入 ${result.imported.length} 个，跳过 ${result.skipped.length} 个，失败 ${result.errors.length} 个`);
      }
      setFolderPath("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文件夹导入失败");
    }
  }

  async function submitJd(event: FormEvent) {
    event.preventDefault();
    if (!jdTitle.trim() || !jdSource.trim()) return;
    setError(null);
    try {
      const result = await api.importJd({
        company: jdCompany.trim(),
        title: jdTitle.trim(),
        sourceText: jdSource.trim()
      });
      setJdResult(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JD 导入失败");
    }
  }

  async function uploadJd(file: File | undefined) {
    if (!file) return;
    setError(null);
    try {
      setJdResult(await api.importJdFile(file, jdCompany.trim(), jdTitle.trim()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JD 文件导入失败");
    }
  }

  async function runMatch(event: FormEvent) {
    event.preventDefault();
    if (!matchRevision.trim()) return;
    setError(null);
    try {
      const result = await api.matchJd(matchRevision.trim(), 20);
      setMatchRun(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "匹配失败");
    }
  }

  async function runBatchMatch(event: FormEvent) {
    event.preventDefault();
    const revisionIds = batchRevisions.split(/[\s,，]+/).map((id) => id.trim()).filter(Boolean);
    if (revisionIds.length === 0) return;
    setError(null);
    try {
      const response = await api.matchBatch(revisionIds, 20);
      setBatchMatchCount(response.results.length);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批量匹配失败");
    }
  }

  async function markMatch(resultId: string, status: MatchMarkStatus) {
    setError(null);
    try {
      const marked = await api.markMatchResult(resultId, status);
      setMatchMarks((current) => ({ ...current, [marked.result_id]: marked.status }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "匹配结果标记失败");
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

  async function loadProjects() {
    setError(null);
    try {
      setProjects(await api.listMappingProjects());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目列表加载失败");
    }
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!projectName.trim()) return;
    setError(null);
    try {
      const project = await api.createMappingProject(projectName.trim());
      setProjects((current) => [project, ...current]);
      setProjectName("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建项目失败");
    }
  }

  async function selectProject(projectId: string) {
    setError(null);
    setSelectedProjectId(projectId);
    try {
      setSnapshots(await api.listMappingSnapshots(projectId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "快照加载失败");
    }
  }

  async function buildTree(event: FormEvent) {
    event.preventDefault();
    if (!selectedProjectId || !mappingText.trim()) return;
    setError(null);
    try {
      const snapshot = await api.buildMappingTree(
        selectedProjectId,
        mappingText,
        mappingLabel.trim()
      );
      setSnapshots((current) => [snapshot, ...current]);
      setTree(await api.getMappingTree(snapshot.id));
      setMappingText("");
      setMappingLabel("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "建树失败");
    }
  }

  async function loadTree(snapshotId: string) {
    setError(null);
    try {
      setTree(await api.getMappingTree(snapshotId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "树加载失败");
    }
  }

  async function searchBd(event: FormEvent) {
    event.preventDefault();
    if (!bdQuery.trim()) return;
    setError(null);
    try {
      setBdLeads(await api.searchBdLeads(bdQuery.trim(), 20));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "线索搜索失败");
    }
  }

  async function loadDashboard() {
    setError(null);
    try {
      setDashboard(await api.dashboardOverview());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "看板加载失败");
    }
  }

  async function openCandidateDetail(item: CandidateSearchItem) {
    setSelected(item);
    setActiveCaseId(null);
    setCaseEvents([]);
    setSelectedContact(null);
    setResumeRevisions([]);
    setCorrectedName("");
    setLastCorrectionId(null);
    setCorrectionMessage("");
    setError(null);
    try {
      setSelectedCases(await api.listCases(item.candidate_id));
      setReverseMatches(await api.reverseMatch(item.candidate_id));
      const contact = await api.getCandidateContact(item.candidate_id);
      setSelectedContact(contact);
      setContactEmail(contact.email ?? "");
      setContactPhone(contact.phone ?? "");
      setResumeRevisions(await api.listResumeRevisions(item.candidate_id));
    } catch {
      // 详情抽屉仍可打开，即使流程数据加载失败。
    }
  }

  async function switchResumeRevision(revisionId: string) {
    setError(null);
    try {
      const current = await api.switchResumeRevision(revisionId);
      setResumeRevisions((revisions) => revisions.map((revision) => ({
        ...revision,
        is_current: revision.revision_id === current.revision_id
      })));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "简历版本切换失败");
    }
  }

  async function correctCandidateName() {
    if (!selected || !correctedName.trim()) return;
    setError(null);
    try {
      const correction = await api.applyCorrection({
        entityType: "candidate",
        entityId: selected.candidate_id,
        fieldName: "display_name",
        newValue: correctedName.trim(),
        reason: "用户在候选人详情中更正姓名"
      });
      setLastCorrectionId(correction.correction_id);
      setCorrectionMessage("更正已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "资料更正失败");
    }
  }

  async function undoCandidateCorrection() {
    if (!lastCorrectionId) return;
    setError(null);
    try {
      await api.undoCorrection(lastCorrectionId);
      setLastCorrectionId(null);
      setCorrectionMessage("更正已撤销");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销更正失败");
    }
  }

  async function deleteSelectedCandidate() {
    if (!selected) return;
    setError(null);
    try {
      await api.softDelete("candidate", selected.candidate_id);
      setResults((items) => items.filter((item) => item.candidate_id !== selected.candidate_id));
      setSelected(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "移入回收站失败");
    }
  }

  async function saveContact() {
    if (!selected) return;
    setError(null);
    try {
      const updated = await api.updateCandidateContact(selected.candidate_id, {
        email: contactEmail.trim() || null,
        phone: contactPhone.trim() || null
      });
      setSelectedContact(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "联系方式保存失败");
    }
  }

  async function loadCaseEvents(caseId: string) {
    setActiveCaseId(caseId);
    setError(null);
    try {
      setCaseEvents(await api.getCaseEvents(caseId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "流程记录加载失败");
    }
  }

  async function advanceStage(caseId: string, stage: string) {
    setError(null);
    try {
      const updated = await api.advanceCase(caseId, stage);
      setSelectedCases((current) =>
        current.map((c) => (c.id === updated.id ? updated : c))
      );
      await loadCaseEvents(caseId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "推进失败");
    }
  }

  async function undoStage(caseId: string) {
    setError(null);
    try {
      const updated = await api.undoCase(caseId);
      setSelectedCases((current) =>
        current.map((c) => (c.id === updated.id ? updated : c))
      );
      await loadCaseEvents(caseId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    }
  }

  async function createCaseFromReverse(match: ReverseMatchItem) {
    if (!selected) return;
    setError(null);
    try {
      const created = await api.createCase(selected.candidate_id, match.jd_id);
      setSelectedCases((current) =>
        current.some((c) => c.id === created.id) ? current : [created, ...current]
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建流程失败");
    }
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

  async function exportMatch(runId: string) {
    setError(null);
    try {
      await api.exportMatchRun(runId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导出失败");
    }
  }

  async function loadBackups() {
    setError(null);
    try {
      setBackups(await api.listBackups());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "备份列表加载失败");
    }
  }

  async function createBackup() {
    setError(null);
    try {
      await api.createBackup();
      setBackups(await api.listBackups());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建备份失败");
    }
  }

  async function restoreBackupItem(filename: string) {
    setError(null);
    try {
      await api.restoreBackup(filename);
      setBackups(await api.listBackups());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "恢复失败");
    }
  }

  async function createPortableBackup() {
    if (!portableBackupPath.trim() || !portablePassphrase) return;
    setError(null);
    try {
      const result = await api.createPortableBackup(portableBackupPath.trim(), portablePassphrase);
      setPortableMessage(`便携备份已创建：${result.path}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "便携备份创建失败");
    }
  }

  async function restorePortableBackup() {
    if (!portableRestorePath.trim() || !portableRestoreTarget.trim() || !portablePassphrase) return;
    setError(null);
    try {
      const result = await api.restorePortableBackup(
        portableRestorePath.trim(),
        portableRestoreTarget.trim(),
        portablePassphrase
      );
      setPortableMessage(result.ok
        ? `便携备份恢复并校验完成：${result.files_verified} 个文件`
        : "便携备份恢复校验未通过");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "便携备份恢复失败");
    }
  }

  async function loadReminders() {
    setError(null);
    try {
      setReminders(await api.listReminders());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提醒加载失败");
    }
  }

  async function createReminderItem(event: FormEvent) {
    event.preventDefault();
    if (!reminderTitle.trim() || !reminderAt.trim()) return;
    setError(null);
    try {
      const created = await api.createReminder({
        title: reminderTitle.trim(),
        remind_at: reminderAt,
        note: ""
      });
      setReminders((current) => [created, ...current]);
      setReminderTitle("");
      setReminderAt("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建提醒失败");
    }
  }

  async function dismissReminderItem(id: string) {
    setError(null);
    try {
      await api.dismissReminder(id);
      setReminders((current) => current.filter((r) => r.id !== id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "处理提醒失败");
    }
  }

  async function migrateData(event: FormEvent) {
    event.preventDefault();
    if (!migrationTarget.trim()) return;
    setError(null);
    try {
      setMigrationReport(await api.migrateData(migrationTarget.trim()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据迁移失败");
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
        setSelected(null);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keydown", onEscape);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keydown", onEscape);
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="navigation" aria-label="主导航">
        <div className="brand">
          <span className="brand-mark">K</span>
          <div><strong>科锐人才库</strong><small>本地招聘工作台</small></div>
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
          <div><h1>{navigation[activeNav]}</h1><p>结构化管理与智能匹配候选人</p></div>
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
              <div className="quick-filters">
                <button>工作年限</button><button>学历</button><button>地点</button><button>学校等级</button>
              </div>
              <form className="folder-import" onSubmit={(event) => void importFolderPath(event)}>
                <input value={folderPath} onChange={(e) => setFolderPath(e.target.value)} placeholder="导入文件夹路径，如 D:\简历库" aria-label="文件夹路径" />
                <button type="submit">导入文件夹</button>
              </form>
            </section>

            <section className="content-grid">
              <div className="results-card">
                <div className="section-heading"><h2>候选人</h2><span>{results.length} 条结果</span></div>
                {results.length === 0 ? (
                  <div className="empty-state"><strong>从一次搜索开始</strong><p>输入技能、经历或自然语言条件查找人才。</p></div>
                ) : (
                  <table>
                    <thead><tr><th>匹配证据</th><th>经验</th><th>学历</th><th>地点</th><th /></tr></thead>
                    <tbody>
                      {results.map((item) => (
                        <tr key={item.candidate_id}>
                          <td><strong>{item.content}</strong><small>{item.matched_channels.join(" + ")}</small></td>
                          <td>{item.total_years ?? "—"} 年</td>
                          <td>{item.highest_degree ?? "待核验"}</td>
                          <td>{item.location ?? "待核验"}</td>
                          <td><button className="detail-button" onClick={() => void openCandidateDetail(item)}>查看详情</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <aside className="task-center" aria-label="任务中心">
                <div className="section-heading">
                  <h2>任务中心</h2>
                  <button className="detail-button" onClick={() => void loadTasks()}>刷新任务</button>
                </div>
                {tasks.length === 0 ? <p className="muted">暂无后台任务</p> : tasks.map((task) => (
                  <article key={task.id}>
                    <strong>{taskLabel(task)}</strong><code>{task.id}</code>
                    <progress max="100" value={task.progress} />
                    <div className="case-actions">
                      {(["PENDING", "QUEUED", "RETRY_WAIT"] as const).includes(task.status as "PENDING" | "QUEUED" | "RETRY_WAIT") && (
                        <button className="detail-button" onClick={() => void controlTask(task, "pause")}>暂停</button>
                      )}
                      {task.status === "PAUSED" && (
                        <button className="detail-button" onClick={() => void controlTask(task, "resume")}>继续</button>
                      )}
                      {(task.status === "FAILED" || task.status === "DEAD_LETTER") && (
                        <button className="detail-button" onClick={() => void controlTask(task, "retry")}>重试</button>
                      )}
                      {!["SUCCESS", "CANCELLED", "DEAD_LETTER"].includes(task.status) && (
                        <button className="detail-button" onClick={() => void controlTask(task, "cancel")}>取消</button>
                      )}
                    </div>
                  </article>
                ))}
              </aside>
            </section>
          </>
        )}

        {activeNav === 1 && (
          <section className="jd-panel">
            <form className="jd-form" onSubmit={(event) => void submitJd(event)}>
              <div className="jd-row">
                <input value={jdCompany} onChange={(e) => setJdCompany(e.target.value)} placeholder="公司名称" aria-label="JD 公司" />
                <input value={jdTitle} onChange={(e) => setJdTitle(e.target.value)} placeholder="岗位名称" aria-label="JD 岗位" />
              </div>
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
            {jdResult && (
              <div className="jd-result" role="status">
                <strong>导入成功</strong>
                <code>{jdResult.revision_id}</code>
              </div>
            )}
          </section>
        )}

        {activeNav === 2 && (
          <section className="jd-panel">
            <form className="jd-form" onSubmit={(event) => void runMatch(event)}>
              <input value={matchRevision} onChange={(e) => setMatchRevision(e.target.value)} placeholder="JD 版本 ID" aria-label="匹配 JD 版本" />
              <button type="submit">开始匹配</button>
            </form>
            <form className="jd-form" onSubmit={(event) => void runBatchMatch(event)}>
              <textarea
                value={batchRevisions}
                onChange={(event) => setBatchRevisions(event.target.value)}
                placeholder="每行一个 JD 版本 ID"
                aria-label="批量 JD 版本"
              />
              <button type="submit">批量匹配</button>
            </form>
            {batchMatchCount !== null && <p role="status">已完成 {batchMatchCount} 个 JD 的批量匹配</p>}
            {matchRun && (
              <div className="results-card">
                <div className="section-heading">
                  <h2>匹配结果</h2>
                  <span>{matchRun.items.length} 人</span>
                  <button className="detail-button" onClick={() => void exportMatch(matchRun.run_id)}>导出 Excel</button>
                </div>
                {matchRun.items.length === 0 ? (
                  <div className="empty-state"><strong>暂无匹配候选人</strong></div>
                ) : (
                  <table>
                    <thead><tr><th>候选人</th><th>得分</th><th>经验</th><th>学历</th><th>处理</th></tr></thead>
                    <tbody>
                      {matchRun.items.map((item) => (
                        <tr key={item.candidate_id}>
                          <td><strong>{item.content}</strong></td>
                          <td>{item.score.toFixed(3)}</td>
                          <td>{item.total_years ?? "—"} 年</td>
                          <td>{item.highest_degree ?? "待核验"}</td>
                          <td>
                            {item.result_id ? (
                              <div className="case-actions">
                                {matchMarks[item.result_id] && <span>{matchMarks[item.result_id]}</span>}
                                <button className="detail-button" onClick={() => void markMatch(item.result_id!, "短名单")}>加入短名单</button>
                                <button className="detail-button" onClick={() => void markMatch(item.result_id!, "排除")}>排除</button>
                              </div>
                            ) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </section>
        )}

        {activeNav === 3 && (
          <section className="jd-panel">
            <div className="section-heading"><h2>招聘看板</h2><button className="import-button" onClick={() => void loadDashboard()}>刷新看板</button></div>
            {dashboard ? (
              <>
                <div className="health-grid">
                  <div className="health-card"><small>推荐总数</small><strong>{dashboard.recommendation_total}</strong></div>
                  <div className="health-card"><small>候选人总数</small><strong>{dashboard.health.candidate_total}</strong></div>
                  <div className="health-card"><small>已解析简历</small><strong>{dashboard.health.ready_total}</strong></div>
                  <div className="health-card"><small>解析失败</small><strong>{dashboard.health.parse_failed}</strong></div>
                  <div className="health-card"><small>近30天新增</small><strong>{dashboard.health.recent_30d}</strong></div>
                  <div className="health-card"><small>开放岗位</small><strong>{dashboard.health.open_jd_total}</strong></div>
                </div>

                {dashboard.funnel.length > 0 && (
                  <div className="results-card">
                    <div className="section-heading"><h2>面试漏斗</h2></div>
                    <div className="funnel-bars">
                      {dashboard.funnel.map((item) => (
                        <div key={item.stage} className="funnel-bar">
                          <span>{item.stage}</span>
                          <div className="funnel-track"><div className="funnel-fill" style={{ width: `${Math.max(4, item.count * 20)}px` }} /></div>
                          <strong>{item.count}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="empty-state"><strong>加载看板数据</strong><p>点击「刷新看板」查看推荐统计与面试漏斗。</p></div>
            )}
          </section>
        )}

        {activeNav === 4 && (
          <section className="jd-panel">
            <form className="jd-form" onSubmit={(event) => void createProject(event)}>
              <div className="jd-row">
                <input value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="项目名称，如：互联网公司图谱" aria-label="项目名称" />
                <button type="submit">新建项目</button>
              </div>
            </form>
            <button className="import-button" onClick={() => void loadProjects()}>刷新项目</button>

            {projects.length > 0 && (
              <div className="mapping-layout">
                <div className="mapping-projects">
                  <div className="section-heading"><h2>项目</h2></div>
                  {projects.map((p) => (
                    <button
                      key={p.id}
                      className={p.id === selectedProjectId ? "nav-item active" : "nav-item"}
                      onClick={() => void selectProject(p.id)}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
                {selectedProjectId && (
                  <div className="mapping-editor">
                    <form className="jd-form" onSubmit={(event) => void buildTree(event)}>
                      <input value={mappingLabel} onChange={(e) => setMappingLabel(e.target.value)} placeholder="快照标签（可选）" aria-label="快照标签" />
                      <textarea value={mappingText} onChange={(e) => setMappingText(e.target.value)} placeholder={"用缩进表示层级：\n字节跳动\n  技术部\n    后端组\n腾讯"} aria-label="建树文本" />
                      <button type="submit">生成组织树</button>
                    </form>
                    {snapshots.length > 0 && (
                      <div className="mapping-snapshots">
                        <div className="section-heading"><h2>快照</h2></div>
                        {snapshots.map((s) => (
                          <div key={s.id} className="case-row">
                            <button className="nav-item" onClick={() => void loadTree(s.id)}>
                              {s.label}{s.is_current ? "（当前）" : ""}
                            </button>
                            <button className="detail-button" onClick={() => void api.exportMappingTree(s.id)}>Excel</button>
                            <button className="detail-button" onClick={() => void api.exportMappingTreePdf(s.id)}>PDF</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {tree.length > 0 && (
              <div className="results-card">
                <div className="section-heading"><h2>组织树</h2></div>
                <MappingTreeView nodes={tree} />
              </div>
            )}
          </section>
        )}

        {activeNav === 5 && (
          <section className="jd-panel">
            <form className="jd-form" onSubmit={(event) => void searchBd(event)}>
              <input value={bdQuery} onChange={(e) => setBdQuery(e.target.value)} placeholder="搜索：如「Java 工程师 招聘 上海」" aria-label="BD 搜索" />
              <button type="submit">搜索线索</button>
            </form>
            {bdLeads.length === 0 ? (
              <div className="empty-state"><strong>暂无线索</strong><p>输入关键词搜索潜在客户与招聘需求。</p></div>
            ) : (
              <div className="results-card">
                <div className="section-heading"><h2>线索</h2><span>{bdLeads.length} 条</span></div>
                <table>
                  <thead><tr><th>公司</th><th>岗位</th><th>来源</th><th>状态</th></tr></thead>
                  <tbody>
                    {bdLeads.map((lead) => (
                      <tr key={lead.id}>
                        <td><strong>{lead.company_name}</strong></td>
                        <td>{lead.job_title ?? "—"}</td>
                        <td>{lead.source}</td>
                        <td>{lead.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {activeNav === 6 && (
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
                <input value={settings.deepseek_model ?? ""} onChange={(e) => setSettings({ ...settings, deepseek_model: e.target.value })} placeholder="DeepSeek 模型" aria-label="DeepSeek 模型" />
              </div>
              <div className="jd-row">
                <input value={settings.siliconflow_api_key ?? ""} onChange={(e) => setSettings({ ...settings, siliconflow_api_key: e.target.value })} placeholder="SiliconFlow API Key" aria-label="SiliconFlow API Key" />
                <input value={settings.tavily_api_key ?? ""} onChange={(e) => setSettings({ ...settings, tavily_api_key: e.target.value })} placeholder="Tavily API Key" aria-label="Tavily API Key" />
              </div>
              <div className="jd-row">
                <input value={settings.serpapi_api_key ?? ""} onChange={(e) => setSettings({ ...settings, serpapi_api_key: e.target.value })} placeholder="SerpApi API Key（Tavily 备选）" aria-label="SerpApi API Key" />
                <input value={settings.imap_host ?? ""} onChange={(e) => setSettings({ ...settings, imap_host: e.target.value })} placeholder="IMAP 主机" aria-label="IMAP 主机" />
              </div>
              <div className="jd-row">
                <input value={settings.imap_account ?? ""} onChange={(e) => setSettings({ ...settings, imap_account: e.target.value })} placeholder="IMAP 账号" aria-label="IMAP 账号" />
                <input value={settings.imap_auth_code ?? ""} onChange={(e) => setSettings({ ...settings, imap_auth_code: e.target.value })} placeholder="IMAP 授权码" aria-label="IMAP 授权码" />
              </div>
              <div className="jd-row">
                <input value={settings.imap_whitelist ?? ""} onChange={(e) => setSettings({ ...settings, imap_whitelist: e.target.value })} placeholder="发件人白名单（逗号分隔）" aria-label="发件人白名单" />
              </div>
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
                <h2>提醒管理</h2>
                <button className="import-button" onClick={() => void loadReminders()}>加载提醒</button>
              </div>
              <form className="jd-form" onSubmit={(event) => void createReminderItem(event)}>
                <div className="jd-row">
                  <input value={reminderTitle} onChange={(e) => setReminderTitle(e.target.value)} placeholder="提醒内容" aria-label="提醒内容" />
                  <input value={reminderAt} onChange={(e) => setReminderAt(e.target.value)} type="datetime-local" aria-label="提醒时间" />
                </div>
                <button type="submit">添加提醒</button>
              </form>
              {reminders.length === 0 ? (
                <p className="muted">暂无待处理提醒</p>
              ) : (
                <div className="case-events">
                  {reminders.map((r) => (
                    <div key={r.id} className="case-row">
                      <div>
                        <strong>{r.title}</strong>
                        <small>{r.remind_at}</small>
                      </div>
                      <button className="detail-button" onClick={() => void dismissReminderItem(r.id)}>完成</button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="case-section">
              <div className="section-heading">
                <h2>备份与恢复</h2>
                <div className="case-actions">
                  <button className="import-button" onClick={() => void loadBackups()}>加载备份</button>
                  <button className="import-button" onClick={() => void createBackup()}>立即备份</button>
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
                      <button className="detail-button" onClick={() => void restoreBackupItem(b.filename)}>恢复</button>
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
                <button type="button" onClick={() => void createPortableBackup()}>创建加密便携备份</button>
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
                <button type="button" onClick={() => void restorePortableBackup()}>恢复便携备份</button>
                {portableMessage && <p role="status">{portableMessage}</p>}
              </div>
            </div>

            <div className="case-section">
              <div className="section-heading"><h2>数据迁移</h2></div>
              <form className="jd-form" onSubmit={(event) => void migrateData(event)}>
                <input value={migrationTarget} onChange={(e) => setMigrationTarget(e.target.value)} placeholder="新数据目录（绝对路径）" aria-label="迁移目标目录" />
                <button type="submit">复制并校验</button>
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
            </div>
          </section>
        )}
      </main>

      {selected && (
        <aside className="detail-drawer" aria-label="候选人详情">
          <button className="close" aria-label="关闭详情" onClick={() => setSelected(null)}>×</button>
          <span className="eyebrow">候选人详情</span>
          <h2>{selected.content}</h2>
          <div className="fact-grid">
            <div><small>相关经验</small><strong>{selected.total_years ?? "—"} 年经验</strong></div>
            <div><small>最高学历</small><strong>{selected.highest_degree ?? "待核验"}</strong></div>
            <div><small>当前地点</small><strong>{selected.location ?? "待核验"}</strong></div>
            <div><small>融合得分</small><strong>{selected.score.toFixed(3)}</strong></div>
          </div>

          <section className="case-section" aria-label="资料更正">
            <h3>资料更正</h3>
            <div className="contact-form">
              <label>
                显示名称
                <input
                  value={correctedName}
                  onChange={(event) => setCorrectedName(event.target.value)}
                  placeholder="输入更正后的姓名"
                  aria-label="候选人显示名称"
                />
              </label>
              <div className="case-actions">
                <button className="detail-button" onClick={() => void correctCandidateName()}>保存名称更正</button>
                {lastCorrectionId && <button className="detail-button" onClick={() => void undoCandidateCorrection()}>撤销本次更正</button>}
                <button className="detail-button" onClick={() => void deleteSelectedCandidate()}>移入回收站</button>
              </div>
              {correctionMessage && <p role="status">{correctionMessage}</p>}
            </div>
          </section>

          <section className="case-section" aria-label="联系方式">
            <h3>联系方式</h3>
            <div className="contact-form">
              <label>
                邮箱
                <input
                  value={contactEmail}
                  onChange={(event) => setContactEmail(event.target.value)}
                  placeholder="candidate@example.com"
                  aria-label="候选人邮箱"
                />
              </label>
              <label>
                手机
                <input
                  value={contactPhone}
                  onChange={(event) => setContactPhone(event.target.value)}
                  placeholder="13800138000"
                  aria-label="候选人手机"
                />
              </label>
              <button className="detail-button" onClick={() => void saveContact()}>保存联系方式</button>
            </div>
          </section>

          <section className="case-section" aria-label="简历版本">
            <h3>简历版本</h3>
            {resumeRevisions.length === 0 ? (
              <p className="muted">暂无版本记录</p>
            ) : resumeRevisions.map((revision) => (
              <div className="case-row" key={revision.revision_id}>
                <div>
                  <strong>{revision.original_filename}</strong>
                  <small>{revision.display_name ?? "未命名"} · {revision.status}</small>
                </div>
                {revision.is_current ? (
                  <span className="ok">当前版本</span>
                ) : (
                  <button className="detail-button" onClick={() => void switchResumeRevision(revision.revision_id)}>设为当前版本</button>
                )}
              </div>
            ))}
          </section>

          {reverseMatches.length > 0 && (
            <section className="case-section" aria-label="潜在匹配岗位">
              <h3>潜在匹配岗位</h3>
              {reverseMatches.map((match) => (
                <div key={match.jd_id} className="case-row">
                  <div>
                    <strong>{match.title}</strong>
                    <small>{match.company} · 得分 {match.score.toFixed(3)}</small>
                  </div>
                  <button className="detail-button" onClick={() => void createCaseFromReverse(match)}>建流程</button>
                </div>
              ))}
            </section>
          )}

          <section className="case-section" aria-label="招聘流程">
            <h3>招聘流程</h3>
            {selectedCases.length === 0 ? (
              <p className="muted">暂无进行中的流程</p>
            ) : (
              selectedCases.map((caseItem) => (
                <div key={caseItem.id} className="case-row">
                  <div>
                    <strong>{caseItem.stage}</strong>
                    <small>{caseItem.note ?? ""}</small>
                  </div>
                  <div className="case-actions">
                    <select
                      aria-label="推进阶段"
                      value={caseItem.stage}
                      onChange={(event) => void advanceStage(caseItem.id, event.target.value)}
                    >
                      {STAGES.map((stage) => (
                        <option key={stage} value={stage}>{stage}</option>
                      ))}
                    </select>
                    <button className="detail-button" onClick={() => void loadCaseEvents(caseItem.id)}>记录</button>
                    <button className="detail-button" onClick={() => void undoStage(caseItem.id)}>撤销</button>
                  </div>
                </div>
              ))
            )}

            {activeCaseId && caseEvents.length > 0 && (
              <div className="case-events">
                {caseEvents.map((event) => (
                  <div key={event.id}>
                    <strong>{event.stage}</strong>
                    {event.note && <span> · {event.note}</span>}
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      )}
    </div>
  );
}


function MappingTreeView({ nodes }: { nodes: MappingTreeNode[] }) {
  if (nodes.length === 0) return null;
  return (
    <ul className="mapping-tree">
      {nodes.map((node) => (
        <li key={node.id}>
          <span>{node.name}</span>
          {node.children.length > 0 && <MappingTreeView nodes={node.children} />}
        </li>
      ))}
    </ul>
  );
}
