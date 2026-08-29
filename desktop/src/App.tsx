import { FormEvent, useState } from "react";

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

export interface CandidateSearchItem {
  candidate_id: string;
  revision_id: string;
  content: string;
  score: number;
  matched_channels: string[];
  total_years: number | null;
  highest_degree: string | null;
  location: string | null;
}

export interface CandidateSearchResult {
  items: CandidateSearchItem[];
  degraded_reasons: string[];
}

export interface RecruitmentApi {
  importResume(file: File): Promise<ImportedResume>;
  getTask(taskId: string): Promise<TaskStatus>;
  searchCandidates(query: string): Promise<CandidateSearchResult>;
}


const navigation = ["人才库", "JD 管理", "人岗匹配", "数据看板", "Mapping", "BD 助手", "设置"];


function taskLabel(task: TaskStatus): string {
  if (task.status === "SUCCESS") return "解析完成";
  if (task.status === "FAILED" || task.status === "DEAD_LETTER") return "解析失败";
  return `解析中 ${task.progress}%`;
}


export function App({ api }: { api: RecruitmentApi }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CandidateSearchItem[]>([]);
  const [selected, setSelected] = useState<CandidateSearchItem | null>(null);
  const [tasks, setTasks] = useState<TaskStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

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

  async function uploadResume(file: File | undefined) {
    if (!file) return;
    setError(null);
    try {
      const imported = await api.importResume(file);
      const task = await api.getTask(imported.task_id);
      setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导入失败，请检查文件");
    }
  }

  return (
    <div className="app-shell">
      <aside className="navigation" aria-label="主导航">
        <div className="brand">
          <span className="brand-mark">K</span>
          <div><strong>科锐人才库</strong><small>本地招聘工作台</small></div>
        </div>
        <nav>
          {navigation.map((item, index) => (
            <button className={index === 0 ? "nav-item active" : "nav-item"} key={item}>
              <span>{index + 1}</span>{item}
            </button>
          ))}
        </nav>
        <div className="local-status"><i />本机数据 · 已保护</div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><h1>人才库</h1><p>结构化管理与智能匹配候选人</p></div>
          <label className="import-button">
            导入简历
            <input
              aria-label="选择简历文件"
              accept=".pdf,.doc,.docx"
              type="file"
              onChange={(event) => void uploadResume(event.target.files?.[0])}
            />
          </label>
        </header>

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
        </section>

        {error && <div className="error-banner" role="alert">{error}</div>}

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
                      <td><button className="detail-button" onClick={() => setSelected(item)}>查看详情</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <aside className="task-center" aria-label="任务中心">
            <div className="section-heading"><h2>任务中心</h2><span>{tasks.length}</span></div>
            {tasks.length === 0 ? <p className="muted">暂无后台任务</p> : tasks.map((task) => (
              <article key={task.id}>
                <strong>{taskLabel(task)}</strong><code>{task.id}</code>
                <progress max="100" value={task.progress} />
              </article>
            ))}
          </aside>
        </section>
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
        </aside>
      )}
    </div>
  );
}
