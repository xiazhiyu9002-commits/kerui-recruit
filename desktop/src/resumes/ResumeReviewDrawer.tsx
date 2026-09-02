import { useRef, useState } from "react";
import type { RecruitmentApi, ResumeReview } from "../App";

export function ResumeReviewDrawer({ api, initialReview, onClose, onApproved }: {
  api: RecruitmentApi; initialReview: ResumeReview; onClose: () => void; onApproved: () => void;
}) {
  const [review, setReview] = useState(initialReview);
  const initialFields = { ...initialReview.review_data, ...initialReview.parsed_data, ...initialReview.manual_overrides };
  const [fields, setFields] = useState<Record<string, unknown>>(initialFields);
  const [skillsText, setSkillsText] = useState(Array.isArray(initialFields.skills) ? initialFields.skills.join("、") : "");
  const [advanced, setAdvanced] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  async function approve() {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const payload = advanced === null ? fields : JSON.parse(advanced);
      if (!payload || Array.isArray(payload) || typeof payload !== "object") throw new Error("完整资料必须是 JSON 对象");
      const result = await api.approveResumeReview(review.revision_id, payload);
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
      <div className="match-drawer-header"><div><h2>简历复核</h2><small>{review.status === "READY" ? "已入库" : "待复核"} · {review.revision_id}</small></div><button className="detail-button" disabled={busy} onClick={close}>关闭</button></div>
      <div className="match-drawer-body">
        <p>草稿不会自动覆盖已确认资料。请对照原文核实，确认后才提交入库。</p>
        {review.error_message && <p>{review.error_message}</p>}
        {error && <p role="alert">{error}</p>}
        {approved && <p role="status">复核已通过</p>}
        <details open><summary>原始简历正文</summary><pre style={{ whiteSpace: "pre-wrap" }}>{review.raw_text || "暂无可用正文"}</pre></details>
        <details><summary>已确认资料</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(review.parsed_data, null, 2)}</pre></details>
        <details><summary>机器草稿（未确认）</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(review.review_data, null, 2)}</pre></details>
        <details><summary>提取诊断与 OCR 路由</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(review.extraction_diagnostics, null, 2)}</pre></details>
        <form onSubmit={(event) => { event.preventDefault(); void approve(); }}>
          <fieldset disabled={busy || approved || review.status === "PROCESSING"} style={{ border: 0, padding: 0 }}>
            {advanced === null ? <>
              <label>姓名<input aria-label="复核姓名" value={String(fields.name || "")} onChange={(event) => changeField("name", event.target.value)} /></label>
              <label>技能<input aria-label="复核技能" value={skillsText} onChange={(event) => { setSkillsText(event.target.value); changeField("skills", event.target.value.split(/[、,，]/).map((value) => value.trim()).filter(Boolean)); }} /></label>
              <label>摘要<textarea aria-label="复核摘要" rows={5} value={String(fields.summary || "")} onChange={(event) => changeField("summary", event.target.value)} /></label>
              <button type="button" className="detail-button" onClick={() => setAdvanced(JSON.stringify(fields, null, 2))}>编辑完整结构化资料</button>
            </> : <label>完整资料（JSON）<textarea aria-label="复核完整资料" rows={18} value={advanced} onChange={(event) => setAdvanced(event.target.value)} /></label>}
            <button type="submit" className="import-button">确认复核并入库</button>
          </fieldset>
        </form>
      </div>
    </aside>
  </div>;
}
