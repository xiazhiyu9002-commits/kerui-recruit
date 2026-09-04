import { useEffect, useMemo, useState } from "react";
import type { RecruitmentApi } from "../App";
import type {
  BusinessDomainLabel,
  DirectionLabel,
  DirectionProfile,
  DirectionTaxonomy,
  LeadershipLabel,
} from "./direction-types";

interface DirectionEditorProps {
  api: RecruitmentApi;
  kind: "resume" | "jd";
  revisionId: string;
  onSaved?: (response: { profile_version: string; correction_id: string | null }) => void;
  onCancel?: () => void;
}

function unknownProfile(): DirectionProfile {
  return {
    taxonomy_version: "career-direction-v1",
    classifier_version: "direction-classifier-v1",
    status: "UNKNOWN",
    role_families: [],
    leadership: null,
    business_domains: [],
    specialties: [],
  };
}

function sourceLabel(source: string): string {
  if (source === "RULE") return "规则";
  if (source === "LLM") return "模型";
  if (source === "USER") return "人工";
  return source;
}

export function DirectionEditor({ api, kind, revisionId, onSaved, onCancel }: DirectionEditorProps) {
  const [taxonomy, setTaxonomy] = useState<DirectionTaxonomy | null>(null);
  const [profile, setProfile] = useState<DirectionProfile>(unknownProfile());
  const [machineProfile, setMachineProfile] = useState<DirectionProfile>(unknownProfile());
  const [manualProfile, setManualProfile] = useState<DirectionProfile | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [latestActiveCorrectionId, setLatestActiveCorrectionId] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<string>("未知");
  const [scoringImpact, setScoringImpact] = useState<{ weight: number; description: string } | null>(null);
  const [primaryCode, setPrimaryCode] = useState<string>("");
  const [secondaryCodes, setSecondaryCodes] = useState<string[]>([]);
  const [leadershipCode, setLeadershipCode] = useState<string>("");
  const [domainCodes, setDomainCodes] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [reevaluating, setReevaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const applyProfile = (effective: DirectionProfile, versionValue: string | null) => {
    setProfile(effective);
    setVersion(versionValue);
    setPrimaryCode(effective.role_families.find((r) => r.is_primary)?.code ?? "");
    setSecondaryCodes(effective.role_families.filter((r) => !r.is_primary).map((r) => r.code));
    setLeadershipCode(effective.leadership?.code ?? "");
    setDomainCodes(effective.business_domains.map((d) => d.code));
  };

  const load = async () => {
    setError(null);
    try {
      const [tax, resp] = await Promise.all([
        api.getDirectionTaxonomy(),
        kind === "resume" ? api.getResumeDirectionProfile(revisionId) : api.getJdDirectionProfile(revisionId),
      ]);
      setTaxonomy(tax);
      setMachineProfile(resp.machine_profile);
      setManualProfile(resp.manual_profile);
      setLatestActiveCorrectionId(resp.latest_active_correction_id);
      setSyncStatus(resp.sync_status ?? "未知");
      setScoringImpact(resp.scoring_impact ?? null);
      applyProfile(resp.direction_profile, resp.profile_version);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载方向信息失败");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revisionId, kind]);

  const roleOptions = useMemo(() => taxonomy?.role_families ?? [], [taxonomy]);

  const toggleSecondary = (code: string) => {
    if (code === primaryCode) return;
    setSecondaryCodes((prev) => {
      if (prev.includes(code)) return prev.filter((c) => c !== code);
      if (prev.length >= 2) return prev;
      return [...prev, code];
    });
  };

  const toggleDomain = (code: string) => {
    setDomainCodes((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  };

  const buildProfile = (): DirectionProfile => {
    const roleFamilies: DirectionLabel[] = [];
    if (primaryCode) {
      roleFamilies.push({ code: primaryCode, label: roleOptions.find((r) => r.code === primaryCode)?.label ?? primaryCode, confidence: 1.0, source: "USER", evidence: [], is_primary: true });
    }
    for (const code of secondaryCodes) {
      if (code === primaryCode) continue;
      roleFamilies.push({ code, label: roleOptions.find((r) => r.code === code)?.label ?? code, confidence: 1.0, source: "USER", evidence: [], is_primary: false });
    }
    const leadership: LeadershipLabel | null = leadershipCode
      ? { code: leadershipCode, label: taxonomy?.leadership[leadershipCode] ?? leadershipCode, confidence: 1.0, source: "USER", evidence: [] }
      : null;
    const businessDomains: BusinessDomainLabel[] = domainCodes.map((code) => ({
      code, label: taxonomy?.business_domains[code] ?? code, confidence: 1.0, source: "USER", evidence: [],
    }));
    return {
      taxonomy_version: "career-direction-v1",
      classifier_version: "direction-classifier-v1",
      status: roleFamilies.length === 0 ? "UNKNOWN" : "CONFIDENT",
      role_families: roleFamilies,
      leadership,
      business_domains: businessDomains,
      specialties: profile.specialties ?? [],
    };
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const next = buildProfile();
      const resp = kind === "resume"
        ? await api.saveResumeDirectionProfile(revisionId, next, version ?? undefined, reason || undefined)
        : await api.saveJdDirectionProfile(revisionId, next, version ?? undefined, reason || undefined);
      setVersion(resp.profile_version);
      setProfile(resp.direction_profile);
      setLatestActiveCorrectionId(resp.correction_id);
      onSaved?.({ profile_version: resp.profile_version, correction_id: resp.correction_id });
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 409) {
        setError("方向已被他人修改，请刷新后重试");
      } else {
        setError(e instanceof Error ? e.message : "保存失败");
      }
    } finally {
      setSaving(false);
    }
  };

  const undo = async () => {
    if (!latestActiveCorrectionId || saving || reevaluating) return;
    setSaving(true);
    setError(null);
    try {
      await api.undoCorrection(latestActiveCorrectionId);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤销失败");
    } finally {
      setSaving(false);
    }
  };

  const reevaluate = async () => {
    if (reevaluating || saving) return;
    setReevaluating(true);
    setError(null);
    try {
      const resp = kind === "resume"
        ? await api.reevaluateResumeDirection(revisionId, version ?? undefined)
        : await api.reevaluateJdDirection(revisionId, version ?? undefined);
      setMachineProfile(resp.machine_profile);
      setManualProfile(resp.manual_profile);
      applyProfile(resp.effective_profile, resp.profile_version);
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 409) {
        setError("方向已被他人修改或内容已变化，请刷新后重试");
      } else {
        setError(e instanceof Error ? e.message : "重新评估失败");
      }
    } finally {
      setReevaluating(false);
    }
  };

  const machineRoles = machineProfile.role_families;
  const effectiveRoles = profile.role_families;

  return (
    <div className="direction-editor">
      <h3 className="direction-editor__title">
        {kind === "jd" ? "岗位方向画像" : "候选人方向画像"}
      </h3>
      <p className="direction-editor__help">
        方向画像用于人才库搜索排序与 JD↔候选人匹配打分：主方向决定搜索时的方向加权，方向兼容度参与匹配综合分计算。
      </p>

      <div className="direction-editor__source">
        来源：<strong>{effectiveRoles[0] ? sourceLabel(effectiveRoles[0].source) : "—"}</strong>
        {profile.status ? <> · 状态：<strong>{profile.status}</strong></> : null}
        <> · 同步：<strong>{syncStatus}</strong></>
      </div>

      {scoringImpact && (
        <div className="direction-editor__impact">
          评分影响：方向兼容度权重 <strong>{Math.round(scoringImpact.weight * 100)}%</strong>
          <p className="muted">{scoringImpact.description}</p>
        </div>
      )}

      {machineRoles.length > 0 && (
        <div className="direction-editor__machine">
          机器结果：{machineRoles.map((r) => `${r.label}${r.is_primary ? "（主）" : ""}`).join("、")}
        </div>
      )}

      {manualProfile && (
        <div className="direction-editor__manual">
          人工覆盖：{manualProfile.role_families.map((r) => `${r.label}${r.is_primary ? "（主）" : ""}`).join("、")}
        </div>
      )}

      {profile.specialties.length > 0 && (
        <div className="direction-editor__specialties">专长：{profile.specialties.join("、")}</div>
      )}

      <div className="direction-editor__detail">
        <h4>当前画像</h4>
        {effectiveRoles.length > 0 ? (
          <ul className="direction-editor__roles">
            {effectiveRoles.map((r) => (
              <li key={r.code}>
                <strong>{r.label}</strong>
                {r.is_primary ? "（主方向）" : "（辅助方向）"}
                <span> · 置信度 {Math.round((r.confidence ?? 0) * 100)}%</span>
                <span> · 来源 {sourceLabel(r.source)}</span>
                {r.evidence.length > 0 && <span> · 证据：{r.evidence.join("；")}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">未设置方向</p>
        )}
        {profile.business_domains.length > 0 && (
          <p className="direction-editor__domains">
            业务领域：{profile.business_domains.map((d) => `${d.label}（${sourceLabel(d.source)} ${Math.round((d.confidence ?? 0) * 100)}%）`).join("、")}
          </p>
        )}
      </div>

      <label className="direction-editor__label">主方向</label>
      <select
        value={primaryCode}
        onChange={(e) => {
          setPrimaryCode(e.target.value);
          setSecondaryCodes((prev) => prev.filter((c) => c !== e.target.value));
        }}
      >
        <option value="">未设置（UNKNOWN）</option>
        {roleOptions.map((r) => (
          <option key={r.code} value={r.code}>{r.label}</option>
        ))}
      </select>

      <label className="direction-editor__label">辅助方向（最多 2 个）</label>
      <div className="direction-editor__chips">
        {roleOptions.map((r) => (
          <button
            key={r.code}
            type="button"
            disabled={r.code === primaryCode}
            className={secondaryCodes.includes(r.code) ? "chip chip--active" : "chip"}
            onClick={() => toggleSecondary(r.code)}
          >
            {r.label}
          </button>
        ))}
      </div>

      <label className="direction-editor__label">管理属性</label>
      <select value={leadershipCode} onChange={(e) => setLeadershipCode(e.target.value)}>
        <option value="">无</option>
        {taxonomy && Object.entries(taxonomy.leadership).map(([code, label]) => (
          <option key={code} value={code}>{label}</option>
        ))}
      </select>

      <label className="direction-editor__label">业务领域</label>
      <div className="direction-editor__chips">
        {taxonomy && Object.entries(taxonomy.business_domains).map(([code, label]) => (
          <button
            key={code}
            type="button"
            className={domainCodes.includes(code) ? "chip chip--active" : "chip"}
            onClick={() => toggleDomain(code)}
          >
            {label}
          </button>
        ))}
      </div>

      <label className="direction-editor__label">修正原因（可选）</label>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="方向不匹配" />

      {error && <div className="direction-editor__error" role="alert">{error}</div>}

      <div className="direction-editor__actions">
        <button type="button" disabled={saving || !taxonomy} onClick={save}>
          {saving ? "保存中…" : "保存"}
        </button>
        <button type="button" disabled={reevaluating || !taxonomy} onClick={reevaluate}>
          {reevaluating ? "评估中…" : "重新评估机器方向"}
        </button>
        <button type="button" disabled={!latestActiveCorrectionId || saving || reevaluating} onClick={undo}>
          撤销人工修改
        </button>
        {onCancel && (
          <button type="button" disabled={saving} onClick={onCancel}>
            取消
          </button>
        )}
      </div>
    </div>
  );
}
