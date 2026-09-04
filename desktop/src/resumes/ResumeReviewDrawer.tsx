import { useRef, useState } from "react";
import type { RecruitmentApi, ResumeReview } from "../App";
import { DirectionEditor } from "./DirectionEditor";

const DEGREE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "未知" },
  { value: "ASSOCIATE", label: "大专" },
  { value: "BACHELOR", label: "本科" },
  { value: "MASTER", label: "硕士" },
  { value: "DOCTORATE", label: "博士" },
];

export function ResumeReviewDrawer({ api, initialReview, onClose, onApproved, onForceReparse }: {
  api: RecruitmentApi; initialReview: ResumeReview; onClose: () => void; onApproved: () => void; onForceReparse?: (revisionId: string) => void;
}) {
  const [review, setReview] = useState(initialReview);
  const initialFields = { ...initialReview.review_data, ...initialReview.parsed_data, ...initialReview.manual_overrides };
  const [fields, setFields] = useState<Record<string, unknown>>(initialFields);
  const [skillsText, setSkillsText] = useState(Array.isArray(initialFields.skills) ? (initialFields.skills as string[]).join("、") : "");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [reparsing, setReparsing] = useState(false);
  async function forceReparse() {
    if (!onForceReparse || reparsing) return;
    setReparsing(true);
    try { onForceReparse(review.revision_id); }
    finally { setReparsing(false); }
  }
  async function approve() {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api.approveResumeReview(review.revision_id, fields);
      setReview(result);
      if (result.status === "READY" && !result.review_required) {
        setApproved(true);
        onApproved();
      } else setError(result.error_message || "资料仍需复核，尚未入库");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复核失败");
    } finally { lock.current = false; setBusy(false); }
  }
  const changeField = (key: string, value: unknown) => setFields((current) => ({ ...current, [key]: value }));
  const close = () => { if (!busy) onClose(); };
  return <div className="match-drawer-backdrop" onClick={close}>
    <aside className="match-drawer workflow-drawer" role="dialog" aria-modal="true" aria-label="简历复核" onClick={(event) => event.stopPropagation()}>
      <div className="match-drawer-header"><div><h2>简历复核</h2><small>{review.status === "READY" ? "已入库" : "待复核"} · {review.revision_id}</small></div><div className="case-actions">{onForceReparse && <button className="detail-button" disabled={busy || reparsing} onClick={() => void forceReparse()}>{reparsing ? "解析中…" : "强制OCR"}</button>}<button className="detail-button" disabled={busy} onClick={close}>关闭</button></div></div>
      <div className="match-drawer-body">
        <p className="muted">草稿不会自动覆盖已确认资料。请对照原文核实，确认后才提交入库。</p>
        {review.error_message && <p className="review-notice">{review.error_message}</p>}
        {error && <p className="review-notice review-notice--error" role="alert">{error}</p>}
        {approved && <p className="review-notice review-notice--ok" role="status">复核已通过</p>}
        <details open><summary>原始简历正文</summary><pre style={{ whiteSpace: "pre-wrap" }}>{review.raw_text || "暂无可用正文"}</pre></details>
        <details open><summary>职业方向</summary><DirectionEditor api={api} kind="resume" revisionId={review.revision_id} /></details>
        <form onSubmit={(event) => { event.preventDefault(); void approve(); }}>
          <fieldset disabled={busy || approved || review.status === "PROCESSING"} style={{ border: 0, padding: 0 }}>
            <label>姓名<input aria-label="复核姓名" value={String(fields.name || "")} onChange={(event) => changeField("name", event.target.value)} /></label>
            <label>学历<select aria-label="复核学历" value={String(fields.highest_degree || "")} onChange={(event) => changeField("highest_degree", event.target.value || null)}>
              {DEGREE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select></label>
            <label>工作年限<input aria-label="复核工作年限" type="number" min="0" step="0.1" value={String(fields.total_years ?? "")} onChange={(event) => changeField("total_years", event.target.value ? Number(event.target.value) : null)} /></label>
            <label>行业<input aria-label="复核行业" value={String(fields.current_industry || "")} onChange={(event) => changeField("current_industry", event.target.value)} /></label>
            <label>技能<input aria-label="复核技能" value={skillsText} onChange={(event) => { setSkillsText(event.target.value); changeField("skills", event.target.value.split(/[、,，]/).map((value) => value.trim()).filter(Boolean)); }} /></label>
            <label>摘要<textarea aria-label="复核摘要" rows={5} value={String(fields.summary || "")} onChange={(event) => changeField("summary", event.target.value)} /></label>
            <button type="submit" className="import-button">确认复核并入库</button>
          </fieldset>
        </form>
        <details><summary>高级诊断</summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify({ parsed_data: review.parsed_data, review_data: review.review_data, extraction_diagnostics: review.extraction_diagnostics }, null, 2)}</pre>
        </details>
      </div>
    </aside>
  </div>;
}
