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
  api: RecruitmentApi; initialReview: ResumeReview; onClose: () => void; onApproved: () => void; onForceReparse?: (revisionId: string) => Promise<void>;
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
  const [dirty, setDirty] = useState(false);
  const [discardAction, setDiscardAction] = useState<"close" | "reparse" | null>(null);
  const [gender, setGender] = useState(initialFields.gender ? String(initialFields.gender) : "");
  const [savingGender, setSavingGender] = useState(false);
  const [genderMessage, setGenderMessage] = useState<string | null>(null);
  async function forceReparse() {
    if (!onForceReparse || lock.current) return;
    if (dirty) { setDiscardAction("reparse"); return; }
    await runReparse();
  }
  async function runReparse() {
    if (!onForceReparse || lock.current) return;
    lock.current = true;
    setReparsing(true);
    setError(null);
    try {
      await onForceReparse(review.revision_id);
      const updated = await api.getResumeReview(review.revision_id);
      const next = { ...updated.parsed_data, ...updated.review_data, ...updated.manual_overrides };
      setReview(updated);
      setFields(next);
      setSkillsText(Array.isArray(next.skills) ? (next.skills as string[]).join("、") : "");
      setDirty(false);
      setApproved(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重新解析失败，请重试。");
    } finally { lock.current = false; setReparsing(false); }
  }
  async function approve() {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api.approveResumeReview(review.revision_id, fields);
      setReview(result);
      setDirty(false);
      if (result.status === "READY" && !result.review_required) {
        setApproved(true);
        onApproved();
      } else setError(result.error_message || "资料仍需复核，尚未入库");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复核失败");
    } finally { lock.current = false; setBusy(false); }
  }
  async function saveGender() {
    if (lock.current) return;
    lock.current = true;
    setSavingGender(true);
    setGenderMessage(null);
    try {
      await api.updateCandidateField(review.candidate_id, "gender", gender || null);
      setFields((current) => ({ ...current, gender: gender || null }));
      setGenderMessage("性别已保存");
    } catch (caught) {
      setGenderMessage(caught instanceof Error ? caught.message : "性别保存失败");
    } finally { lock.current = false; setSavingGender(false); }
  }
  const changeField = (key: string, value: unknown) => { setDirty(true); setFields((current) => ({ ...current, [key]: value })); };
  const close = () => { if (busy || reparsing) return; if (dirty) setDiscardAction("close"); else onClose(); };
  return <div className="match-drawer-backdrop" onClick={close}>
    <aside className="match-drawer workflow-drawer" role="dialog" aria-modal="true" aria-label="简历复核" onClick={(event) => event.stopPropagation()}>
      <div className="match-drawer-header"><div><h2>简历复核</h2><small>{review.status === "READY" ? "已入库" : "待复核"} · {review.revision_id}</small></div><div className="case-actions">{onForceReparse && <button className="detail-button" disabled={busy || reparsing} onClick={() => void forceReparse()}>{reparsing ? "解析中…" : "强制OCR"}</button>}<button className="detail-button" disabled={busy} onClick={close}>关闭</button></div></div>
      <div className="match-drawer-body">
        {discardAction && <div role="alert" className="review-notice">
          <p>有尚未提交的修改，请选择继续编辑或放弃修改。</p>
          <button type="button" onClick={() => setDiscardAction(null)}>继续编辑</button>
          <button type="button" onClick={() => {
            const action = discardAction;
            setDiscardAction(null);
            if (action === "close") onClose(); else void runReparse();
          }}>{discardAction === "close" ? "放弃修改并关闭" : "放弃修改并重新解析"}</button>
        </div>}
        <p className="muted">草稿不会自动覆盖已确认资料。请对照原文核实，确认后才提交入库。</p>
        {review.error_message && <p className="review-notice">{review.error_message}</p>}
        {error && <p className="review-notice review-notice--error" role="alert">{error}</p>}
        {approved && <p className="review-notice review-notice--ok" role="status">复核已通过</p>}
        <details open><summary>原始简历正文</summary><pre style={{ whiteSpace: "pre-wrap" }}>{review.raw_text || "暂无可用正文"}</pre></details>
        <details open><summary>职业方向</summary><DirectionEditor api={api} kind="resume" revisionId={review.revision_id} /></details>
        <form onSubmit={(event) => { event.preventDefault(); void approve(); }}>
          <fieldset disabled={busy || reparsing || approved || review.status === "PROCESSING"} style={{ border: 0, padding: 0 }}>
            <label>姓名<input aria-label="复核姓名" value={String(fields.name || "")} onChange={(event) => changeField("name", event.target.value)} /></label>
            <label>学历<select aria-label="复核学历" value={String(fields.highest_degree || "")} onChange={(event) => changeField("highest_degree", event.target.value || null)}>
              {DEGREE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select></label>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 10, margin: "8px 0" }}>
              <label style={{ flex: 1 }}>性别<select aria-label="复核性别" value={gender} onChange={(event) => setGender(event.target.value)}>
                <option value="">未知</option>
                <option value="男">男</option>
                <option value="女">女</option>
              </select></label>
              <button type="button" className="detail-button" disabled={savingGender || busy || reparsing} onClick={() => void saveGender()}>{savingGender ? "保存中…" : "单独保存性别"}</button>
              {genderMessage && <span style={{ color: genderMessage === "性别已保存" ? "#1e6849" : "#b3261e", fontSize: 12, whiteSpace: "nowrap" }}>{genderMessage}</span>}
            </div>
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
