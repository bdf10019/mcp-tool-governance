import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import type { Actor, BackupPreview, GovernanceBackup, Health, LocalUser, MaintenanceOrder, MigrationOverview, Profile, ProfileConfigVersion, Proposal, RestoreReceipt, Tool, Trace } from "./types";

type Screen = "tools" | "workflow" | "orders" | "traces" | "accounts" | "configs" | "backups" | "governance";

const toolIcon: Record<string, string> = {
  get_equipment_status: "脈",
  list_maintenance_history: "歷",
  check_parts_stock: "件",
};

const fieldLabels: Record<string, string> = {
  equipment_id: "設備編號",
  part_id: "零件編號",
  date_from: "起始時間",
  date_to: "結束時間",
  cursor: "接續游標",
  limit: "最多筆數",
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "發生未知錯誤";
}

function AuthPanel({ mode, onAuthenticated }: { mode: "setup" | "login"; onAuthenticated: (actor: Actor) => void }) {
  const [username, setUsername] = useState(mode === "setup" ? "" : "portfolio-admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await api<{ actor: Actor }>(mode === "setup" ? "/api/setup" : "/api/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onAuthenticated(response.actor);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <div className="eyebrow">MCP TOOL GOVERNANCE · LOCAL</div>
        <h1>工具有邊界，<br />每一步都有證據。</h1>
        <p>以正式 MCP stdio 串接三個唯讀工具與一個受核准保護的寫入工具。身分、範圍、核准與冪等都由後端重新驗證。</p>
        <div className="story-grid" aria-label="產品保證">
          <div><strong>3+1</strong><span>讀取／寫入工具</span></div>
          <div><strong>1–2</strong><span>獨立核准人數</span></div>
          <div><strong>1×</strong><span>冪等工單結果</span></div>
        </div>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="seal">TG</div>
        <p className="micro">本機產品 · 合成資料</p>
        <h2 id="auth-title">{mode === "setup" ? "建立第一位管理者" : "登入工具工作台"}</h2>
        <p>{mode === "setup" ? "帳號只保存在目前作品的本機資料庫。首位帳號具有 admin 與 viewer 角色。" : "使用你建立的本機帳號繼續。"}</p>
        <form onSubmit={submit}>
          <label>帳號<input value={username} onChange={(event) => setUsername(event.target.value)} minLength={3} maxLength={40} autoComplete="username" required /></label>
          <label>密碼<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={10} autoComplete={mode === "setup" ? "new-password" : "current-password"} required /></label>
          {error && <div className="alert error" role="alert">{error}</div>}
          <button className="primary wide" disabled={busy}>{busy ? "處理中…" : mode === "setup" ? "建立並進入" : "登入"}</button>
        </form>
        <small>不會建立展示帳號，也不會連線到公司或外部服務。</small>
      </section>
    </main>
  );
}

function FieldInput({ name, schema, value, profile, onChange }: {
  name: string;
  schema: { type?: string; default?: unknown };
  value: unknown;
  profile: Profile;
  onChange: (value: unknown) => void;
}) {
  if (name === "equipment_id") {
    return (
      <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        {profile.effective_device_scope.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    );
  }
  if (name === "part_id") {
    return (
      <select value={String(value ?? "PT-BRG-6204")} onChange={(event) => onChange(event.target.value)}>
        <option value="PT-BRG-6204">PT-BRG-6204 · 6204 軸承</option>
        <option value="PT-SEAL-01">PT-SEAL-01 · 機械軸封組</option>
        <option value="PT-BELT-A42">PT-BELT-A42 · A42 傳動皮帶</option>
        <option value="PT-SENSOR-P9">PT-SENSOR-P9 · 壓力感測器 P9</option>
      </select>
    );
  }
  if (schema.type === "integer") {
    return <input type="number" min={1} max={50} value={Number(value ?? schema.default ?? 20)} onChange={(event) => onChange(Number(event.target.value))} />;
  }
  return <input value={String(value ?? schema.default ?? "")} onChange={(event) => onChange(event.target.value)} placeholder={name.includes("date") ? "YYYY-MM-DD（可留空）" : "可留空"} />;
}

function ResultPanel({ payload }: { payload: Record<string, unknown> }) {
  const hidden = new Set(["source_sha256"]);
  const entries = Object.entries(payload).filter(([key]) => !hidden.has(key));
  return (
    <section className="result-panel" aria-live="polite">
      <div className="section-heading">
        <div><span className="kicker">STRUCTURED RESULT</span><h3>查詢結果</h3></div>
        <span className="status success">已完成</span>
      </div>
      <dl className="result-grid">
        {entries.map(([key, value]) => (
          <div key={key} className={typeof value === "object" ? "span-two" : ""}>
            <dt>{fieldLabels[key] ?? key.replaceAll("_", " ")}</dt>
            <dd>{typeof value === "object" ? <pre>{JSON.stringify(value, null, 2)}</pre> : String(value ?? "—")}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const proposalStatus: Record<string, string> = {
  draft: "草稿",
  validated: "驗證通過",
  pending_review: "等待審核",
  partially_approved: "部分核准",
  approved: "已核准",
  rejected: "已退回",
  changes_requested: "要求修改",
  invalidated: "舊版失效",
  expired: "已過期",
  cancelled: "已取消",
  consumed: "已建立工單",
};

const configStatus: Record<string, string> = {
  draft: "草稿",
  validated: "驗證通過",
  previewed: "已預覽",
  submitted: "等待核准",
  approved: "已核准",
  active: "啟用中",
  superseded: "歷史版本",
  rejected: "已退回",
  expired: "已過期",
  cancelled: "已取消",
};

const configFieldLabel: Record<string, string> = {
  display_name: "顯示名稱",
  scope_label: "範圍標籤",
  color: "品牌色",
  equipment_ids: "設備範圍",
  "settings.approval_count": "核准人數",
  "settings.terminology": "業務術語",
  "settings.maintenance_window_required": "維護時段必填",
  "settings.risk_summary_required": "風險說明必填",
  "settings.retention_default_days": "預設保存期限",
};

function WorkflowPanel({ actor, profiles, selectedProfileId, onTraceChanged }: {
  actor: Actor;
  profiles: Profile[];
  selectedProfileId: string;
  onTraceChanged: () => Promise<void>;
}) {
  const profile = profiles.find((item) => item.profile_id === selectedProfileId) ?? profiles[0];
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [orders, setOrders] = useState<MaintenanceOrder[]>([]);
  const [equipmentId, setEquipmentId] = useState("");
  const [summary, setSummary] = useState("循環水泵振動持續偏高，需要安排停機檢查。");
  const [priority, setPriority] = useState("high");
  const [maintenanceWindow, setMaintenanceWindow] = useState("");
  const [riskSummary, setRiskSummary] = useState("");
  const [retentionDays, setRetentionDays] = useState(7);
  const [reviewReasons, setReviewReasons] = useState<Record<string, string>>({});
  const [confirmations, setConfirmations] = useState<Record<string, boolean>>({});
  const [busyAction, setBusyAction] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [proposalData, orderData] = await Promise.all([
      api<{ items: Proposal[] }>("/api/proposals"),
      api<{ items: MaintenanceOrder[] }>("/api/orders"),
    ]);
    setProposals(proposalData.items);
    setOrders(orderData.items);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(messageOf(caught)));
  }, []);

  useEffect(() => {
    if (!profile) return;
    setEquipmentId(profile.effective_device_scope[0] ?? "");
    if (profile.settings.maintenance_window_required) {
      setMaintenanceWindow("2026-09-26 09:00–11:00");
      setRiskSummary("持續運轉可能造成軸承損壞與非預期停機。");
    } else {
      setMaintenanceWindow("");
      setRiskSummary("");
    }
    setRetentionDays(profile.settings.retention_default_days ?? 7);
  }, [profile?.profile_id]);

  async function runAction(key: string, action: () => Promise<unknown>, success: string) {
    setBusyAction(key);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      await refresh();
      await onTraceChanged().catch(() => undefined);
    } catch (caught) {
      const typed = caught as ApiError;
      setError(`${typed.message}${typed.nextAction ? `｜${typed.nextAction}` : ""}`);
      await refresh().catch(() => undefined);
    } finally {
      setBusyAction("");
    }
  }

  async function createDraft(event: FormEvent) {
    event.preventDefault();
    if (!profile) return;
    await runAction(
      "create",
      () => api("/api/proposals", {
        method: "POST",
        body: JSON.stringify({
          profile_id: profile.profile_id,
          retention_days: retentionDays,
          parameters: {
            equipment_id: equipmentId,
            issue_summary: summary,
            priority,
            maintenance_window: maintenanceWindow,
            risk_summary: riskSummary,
          },
        }),
      }),
      "草稿已建立；確認內容後再送審。",
    );
  }

  function review(proposal: Proposal, decision: "approve" | "reject" | "changes_requested") {
    const reason = reviewReasons[proposal.proposal_id] ?? "";
    return runAction(
      `review-${proposal.proposal_id}`,
      () => api(`/api/proposals/${proposal.proposal_id}/review`, {
        method: "POST",
        body: JSON.stringify({ proposal_version: proposal.proposal_version, decision, reason }),
      }),
      decision === "approve" ? "審核已記錄，歷史不會被覆寫。" : "審核結果已記錄。",
    );
  }

  if (!profile) return <div className="empty"><strong>沒有可用工作設定</strong></div>;
  const canOperate = actor.roles.includes("operator");
  const canReview = actor.roles.includes("reviewer");

  return (
    <section>
      <div className="page-intro compact">
        <div><span className="eyebrow">APPROVAL-GATED WRITE</span><h1>先提案、再核准，最後才建立工單。</h1><p>提出者不能自審；admin 不自動取得 reviewer 或 operator。重送同一提案只會得到同一張工單。</p></div>
        <div className="scope-card"><span>目前流程</span><strong>{profile.settings.approval_count} 人核准</strong><p>{profile.settings.terminology} · {profile.policy_version}</p></div>
      </div>
      {error && <div className="alert error" role="alert"><strong>操作被阻擋</strong><span>{error}</span></div>}
      {notice && <div className="alert success" role="status"><strong>完成</strong><span>{notice}</span></div>}

      <div className="workflow-layout">
        {canOperate && (
          <form className="proposal-form" onSubmit={createDraft}>
            <span className="kicker">NEW PROPOSAL</span><h2>建立{profile.settings.terminology}草稿</h2>
            <label>設備編號<select value={equipmentId} onChange={(event) => setEquipmentId(event.target.value)}>{profile.effective_device_scope.map((id) => <option key={id}>{id}</option>)}</select></label>
            <label>問題摘要<textarea value={summary} onChange={(event) => setSummary(event.target.value)} minLength={10} maxLength={1000} required /></label>
            <label>優先序<select value={priority} onChange={(event) => setPriority(event.target.value)}><option value="low">低</option><option value="normal">一般</option><option value="high">高</option><option value="urgent">緊急</option></select></label>
            {profile.settings.maintenance_window_required && <label>維護時段<input value={maintenanceWindow} onChange={(event) => setMaintenanceWindow(event.target.value)} required /></label>}
            {profile.settings.risk_summary_required && <label>風險說明<textarea value={riskSummary} onChange={(event) => setRiskSummary(event.target.value)} minLength={10} required /></label>}
            <fieldset className="retention-picker"><legend>內容保存期限</legend><label><input type="radio" name="retention" checked={retentionDays === 1} onChange={() => setRetentionDays(1)} />1 日 · 最少保存</label><label><input type="radio" name="retention" checked={retentionDays === 7} onChange={() => setRetentionDays(7)} />7 日 · 支援跨日審核</label><small>到期會清除提案內容、審核理由與工單業務欄位；識別碼、雜湊與稽核事件保留。</small></fieldset>
            <div className="permission-preview"><span>送審後會凍結</span><strong>參數 · 設備資料 · Profile · 政策版本</strong><small>任何修改都會建立新版本，舊核准不沿用。</small></div>
            <button className="primary" disabled={busyAction === "create"}>{busyAction === "create" ? "建立中…" : "建立草稿"}</button>
          </form>
        )}

        <div className="proposal-stream">
          <div className="stream-heading"><div><span className="kicker">LIVE STATE</span><h2>{canReview ? "審核收件匣" : "我的提案"}</h2></div><button className="secondary" onClick={() => refresh()}>重新整理</button></div>
          {proposals.length === 0 ? <div className="empty"><strong>目前沒有提案</strong><p>{canReview ? "等待 operator 送出一筆提案。" : "先建立草稿，再交給另一個帳號審核。"}</p></div> : proposals.map((proposal) => {
            const approvalCount = proposal.approvals.filter((item) => item.decision === "approve").length;
            const reviewable = canReview && proposal.content_state === "available" && ["pending_review", "partially_approved"].includes(proposal.status);
            const executable = canOperate && proposal.content_state === "available" && proposal.proposer_id === actor.user_id && proposal.status === "approved";
            const isAsset = proposal.profile_id === "asset-v1";
            return (
              <article className="proposal-card" key={`${proposal.proposal_id}-${proposal.proposal_version}`}>
                <header><div><span>{proposal.profile_id} · v{proposal.proposal_version}</span><strong>{proposal.content_state === "purged" ? "內容已依保存政策清除" : proposal.parameters.issue_summary}</strong><small>{proposal.proposal_id} · key …{proposal.idempotency_suffix}</small></div><span className={`state-pill ${proposal.status}`}>{proposalStatus[proposal.status] ?? proposal.status}</span></header>
                <div className="proposal-facts"><span>設備<strong>{proposal.equipment_id}</strong></span><span>優先序<strong>{proposal.parameters.priority || "已清除"}</strong></span><span>核准<strong>{approvalCount}/{proposal.required_approvals}</strong></span><span>保存<strong>{proposal.content_state === "purged" ? "已清除" : `${proposal.retention_days} 日`}</strong></span></div>
                <div className={`retention-note ${proposal.content_state}`}><strong>{proposal.content_state === "purged" ? "保存期限已到" : "內容仍在保存期"}</strong><span>{proposal.content_state === "purged" ? "敏感業務內容已刪除；此筆不可再核准、執行或查回結果。" : `預計 ${new Date(proposal.content_expires_at * 1000).toLocaleString("zh-TW")} 到期。`}</span></div>
                {proposal.approvals.length > 0 && <div className="approval-history">{proposal.approvals.map((item) => <div key={item.approval_id}><b>{item.reviewer_name}</b><span>{item.decision}</span><small>{item.reason}</small></div>)}</div>}
                {reviewable && <div className="review-box"><label>審核理由<input value={reviewReasons[proposal.proposal_id] ?? ""} onChange={(event) => setReviewReasons((current) => ({ ...current, [proposal.proposal_id]: event.target.value }))} placeholder="至少 8 個字元" /></label><div><button className="primary" onClick={() => review(proposal, "approve")} disabled={busyAction.startsWith("review-")}>核准</button><button className="secondary" onClick={() => review(proposal, "changes_requested")}>要求修改</button><button className="quiet danger" onClick={() => review(proposal, "reject")}>退回</button></div></div>}
                {canOperate && proposal.content_state === "available" && proposal.status === "draft" && <button className="primary" onClick={() => runAction(`submit-${proposal.proposal_id}`, () => api(`/api/proposals/${proposal.proposal_id}/submit`, { method: "POST", body: JSON.stringify({ proposal_version: proposal.proposal_version }) }), "提案已送審，等待獨立 reviewer。")}>送出審核</button>}
                {executable && <div className="execute-box">{isAsset && <label className="check-line"><input type="checkbox" checked={confirmations[proposal.proposal_id] ?? false} onChange={(event) => setConfirmations((current) => ({ ...current, [proposal.proposal_id]: event.target.checked }))} />我已重新確認維護時段、風險與資料版本</label>}<button className="primary write" onClick={() => runAction(`execute-${proposal.proposal_id}`, () => api(`/api/proposals/${proposal.proposal_id}/execute`, { method: "POST", body: JSON.stringify({ proposal_version: proposal.proposal_version, maintenance_confirmed: confirmations[proposal.proposal_id] ?? false }) }), "本機工單已交易提交。")}>建立本機工單</button></div>}
                {canOperate && proposal.content_state === "available" && proposal.proposer_id === actor.user_id && proposal.status === "consumed" && <button className="secondary" onClick={() => runAction(`recover-${proposal.proposal_id}`, () => api(`/api/proposals/${proposal.proposal_id}/recover?proposal_version=${proposal.proposal_version}`), "已使用原冪等鍵查回同一張工單。")}>查核原執行結果</button>}
              </article>
            );
          })}
        </div>
      </div>

      <section className="orders-section"><div className="stream-heading"><div><span className="kicker">COMMITTED ORDERS</span><h2>已建立的本機工單</h2></div><span className="status success">{orders.length} 筆</span></div>{orders.length === 0 ? <div className="empty compact-empty">核准並執行後，工單會顯示在這裡。</div> : <div className="order-grid">{orders.map((order) => <article key={order.order_id}><span>{order.order_status}</span><strong>{order.order_id}</strong><p>{order.issue_summary}</p><small>{order.equipment_id} · {order.profile_id} · {order.source_kind}</small></article>)}</div>}</section>
    </section>
  );
}

function ProfileConfigPanel({ actor, profiles, onApplied }: {
  actor: Actor;
  profiles: Profile[];
  onApplied: () => Promise<void>;
}) {
  const [versions, setVersions] = useState<ProfileConfigVersion[]>([]);
  const [profileId, setProfileId] = useState(profiles[0]?.profile_id ?? "");
  const [displayName, setDisplayName] = useState("");
  const [scopeLabel, setScopeLabel] = useState("");
  const [color, setColor] = useState("#08786c");
  const [terminology, setTerminology] = useState("");
  const [approvalCount, setApprovalCount] = useState(1);
  const [retentionDefault, setRetentionDefault] = useState(7);
  const [maintenanceRequired, setMaintenanceRequired] = useState(false);
  const [riskRequired, setRiskRequired] = useState(false);
  const [equipmentIds, setEquipmentIds] = useState<string[]>([]);
  const [reviewReasons, setReviewReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const isAdmin = actor.roles.includes("admin");
  const isReviewer = actor.roles.includes("reviewer");
  const selected = profiles.find((item) => item.profile_id === profileId) ?? profiles[0];
  const allEquipment = [...new Set(profiles.flatMap((item) => item.effective_device_scope))].sort();

  async function refresh() {
    const response = await api<{ items: ProfileConfigVersion[] }>("/api/profile-configs");
    setVersions(response.items);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(messageOf(caught)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDisplayName(selected.display_name);
    setScopeLabel(selected.scope_label);
    setColor(selected.color);
    setTerminology(selected.settings.terminology);
    setApprovalCount(selected.settings.approval_count);
    setRetentionDefault(selected.settings.retention_default_days ?? 7);
    setMaintenanceRequired(Boolean(selected.settings.maintenance_window_required));
    setRiskRequired(Boolean(selected.settings.risk_summary_required));
    setEquipmentIds(selected.effective_device_scope);
  }, [selected?.profile_id, selected?.version]);

  async function act(key: string, action: () => Promise<unknown>, success: string, applied = false) {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await action();
      if (applied) await onApplied();
      await refresh();
      setNotice(success);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy("");
    }
  }

  function createDraft(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    return act(
      "create-config",
      () => api(`/api/profile-configs/${selected.profile_id}/draft`, {
        method: "POST",
        body: JSON.stringify({
          snapshot: {
            profile_id: selected.profile_id,
            display_name: displayName,
            scope_label: scopeLabel,
            color,
            equipment_ids: equipmentIds,
            settings: {
              approval_count: approvalCount,
              terminology,
              read_tools: 3,
              write_tool: "create_maintenance_order",
              maintenance_window_required: maintenanceRequired,
              risk_summary_required: riskRequired,
              retention_default_days: retentionDefault,
            },
          },
        }),
      }),
      "設定草稿已建立；請先檢查差異再送審。",
    );
  }

  function transition(version: ProfileConfigVersion, action: "validate" | "preview" | "submit" | "cancel" | "apply" | "rollback") {
    const label = action === "validate" ? "白名單、欄位與安全底線驗證通過。" : action === "preview" ? "差異預覽已固定。" : action === "submit" ? "設定版本已送交獨立 reviewer。" : action === "cancel" ? "設定候選已取消；歷史仍保留。" : action === "apply" ? "新設定版本已套用；舊提案仍保留原版本。" : "已從歷史版本建立新的還原草稿。";
    return act(
      `${action}-${version.profile_id}-${version.revision}`,
      () => api(`/api/profile-configs/${version.profile_id}/${action}`, { method: "POST", body: JSON.stringify({ revision: version.revision }) }),
      label,
      action === "apply",
    );
  }

  function review(version: ProfileConfigVersion, decision: "approve" | "reject") {
    return act(
      `review-config-${version.revision}`,
      () => api(`/api/profile-configs/${version.profile_id}/review`, {
        method: "POST",
        body: JSON.stringify({ revision: version.revision, decision, reason: reviewReasons[`${version.profile_id}-${version.revision}`] ?? "" }),
      }),
      decision === "approve" ? "設定版本已獨立核准，等待管理者套用。" : "設定版本已退回。",
    );
  }

  const selectedVersions = versions.filter((item) => item.profile_id === selected?.profile_id);
  return (
    <section>
      <div className="page-intro compact"><div><span className="eyebrow">VERSIONED CONFIGURATION</span><h1>客製化要能預覽、核准，也能還原。</h1><p>設定草稿不會直接改動產品。差異固定後交由獨立 reviewer 核准，再由 admin 套用；歷史版本與舊提案快照都保留。</p></div><div className="scope-card"><span>目前啟用版本</span><strong>{selected?.version ?? "—"}</strong><p>{selected?.policy_version}</p></div></div>
      {error && <div className="alert error" role="alert">{error}</div>}{notice && <div className="alert success" role="status">{notice}</div>}
      <label className="config-profile-picker">設定對象<select value={selected?.profile_id ?? ""} onChange={(event) => setProfileId(event.target.value)}>{profiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.display_name} · {item.version}</option>)}</select></label>
      <div className="config-layout">
        {isAdmin && selected && <form className="proposal-form config-form" onSubmit={createDraft}><span className="kicker">NEW CONFIG DRAFT</span><h2>建立下一版設定</h2><label>顯示名稱<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} minLength={3} maxLength={40} required /></label><label>範圍標籤<input value={scopeLabel} onChange={(event) => setScopeLabel(event.target.value)} minLength={2} maxLength={30} required /></label><label>品牌色<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label><label>業務術語<input value={terminology} onChange={(event) => setTerminology(event.target.value)} minLength={2} maxLength={20} required /></label><label>核准人數<select value={approvalCount} onChange={(event) => setApprovalCount(Number(event.target.value))}><option value={1}>1 人</option><option value={2}>2 人</option></select></label><label>預設保存<select value={retentionDefault} onChange={(event) => setRetentionDefault(Number(event.target.value))}><option value={1}>1 日</option><option value={7}>7 日</option></select></label><fieldset><legend>設備範圍</legend>{allEquipment.map((equipment) => <label key={equipment} className="check-line"><input type="checkbox" checked={equipmentIds.includes(equipment)} onChange={() => setEquipmentIds((current) => current.includes(equipment) ? current.filter((item) => item !== equipment) : [...current, equipment])} />{equipment}</label>)}</fieldset><label className="check-line"><input type="checkbox" checked={maintenanceRequired} onChange={(event) => setMaintenanceRequired(event.target.checked)} />維護時段必填</label><label className="check-line"><input type="checkbox" checked={riskRequired} onChange={(event) => setRiskRequired(event.target.checked)} />風險說明必填</label><div className="permission-preview"><span>安全底線固定</span><strong>3 個唯讀工具 · 1 個核准式寫入工具</strong><small>設定不能加入 URL、命令、SQL、遠端引用或未知工具。</small></div><button className="primary" disabled={busy !== "" || equipmentIds.length === 0}>建立設定草稿</button></form>}
        <div className="config-stream"><div className="stream-heading"><div><span className="kicker">VERSION HISTORY</span><h2>設定版本與差異</h2></div><button className="secondary" onClick={() => refresh()}>重新整理</button></div>{selectedVersions.map((version) => <article className="config-card" key={`${version.profile_id}-${version.revision}`}><header><div><strong>{version.version}</strong><small>{version.policy_version} · 基於 {version.derived_from_version ?? "初始設定"}</small></div><span className={`state-pill ${version.status}`}>{configStatus[version.status] ?? version.status}</span></header><div className="config-summary"><span>{version.snapshot.display_name}</span><span>{version.snapshot.settings.approval_count} 人核准</span><span>{version.snapshot.settings.retention_default_days ?? 7} 日保存</span><span>{version.snapshot.equipment_ids.length} 部設備</span></div>{version.diff.length > 0 ? <div className="diff-list">{version.diff.map((item) => <div key={item.field}><b>{configFieldLabel[item.field] ?? item.field}</b><span>{JSON.stringify(item.before)} → {JSON.stringify(item.after)}</span></div>)}</div> : <div className="no-diff">此版本與目前啟用設定相同。</div>}{version.approvals.map((approval) => <div className="config-approval" key={approval.approval_id}><strong>{approval.reviewer_name}</strong><span>{approval.decision === "approve" ? "核准" : "退回"}</span><small>{approval.reason}</small></div>)}<div className="config-actions">{isAdmin && version.status === "draft" && <button className="secondary" onClick={() => transition(version, "validate")}>驗證設定草稿</button>}{isAdmin && version.status === "validated" && <button className="secondary" onClick={() => transition(version, "preview")}>產生差異預覽</button>}{isAdmin && version.status === "previewed" && <button className="primary" onClick={() => transition(version, "submit")}>送交獨立核准</button>}{isReviewer && version.status === "submitted" && <><label>核准理由<input value={reviewReasons[`${version.profile_id}-${version.revision}`] ?? ""} onChange={(event) => setReviewReasons((current) => ({ ...current, [`${version.profile_id}-${version.revision}`]: event.target.value }))} placeholder="至少 8 個字元" /></label><button className="primary" onClick={() => review(version, "approve")}>核准設定</button><button className="quiet danger" onClick={() => review(version, "reject")}>退回設定</button></>}{isAdmin && ["draft", "validated", "previewed", "submitted"].includes(version.status) && <button className="quiet danger" onClick={() => transition(version, "cancel")}>取消候選</button>}{isAdmin && version.status === "approved" && <button className="primary write" onClick={() => transition(version, "apply")}>套用新版本</button>}{isAdmin && version.status === "superseded" && <button className="secondary" onClick={() => transition(version, "rollback")}>建立還原草稿</button>}</div></article>)}</div>
      </div>
    </section>
  );
}

function BackupGovernancePanel({ actor }: { actor: Actor }) {
  const [migrations, setMigrations] = useState<MigrationOverview | null>(null);
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [backups, setBackups] = useState<GovernanceBackup[]>([]);
  const [restores, setRestores] = useState<RestoreReceipt[]>([]);
  const [backupConfirmation, setBackupConfirmation] = useState("");
  const [restoreConfirmation, setRestoreConfirmation] = useState("");
  const [selectedBackup, setSelectedBackup] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [migrationData, previewData, backupData, restoreData] = await Promise.all([
      api<MigrationOverview>("/api/admin/governance/migrations"),
      api<BackupPreview>("/api/admin/governance/backup-preview"),
      api<{ items: GovernanceBackup[] }>("/api/admin/governance/backups"),
      api<{ items: RestoreReceipt[] }>("/api/admin/governance/restores"),
    ]);
    setMigrations(migrationData);
    setPreview(previewData);
    setBackups(backupData.items);
    setRestores(restoreData.items);
    setSelectedBackup((current) => backupData.items.some((item) => item.backup_id === current) ? current : backupData.items[0]?.backup_id ?? "");
  }

  useEffect(() => {
    if (!actor.roles.includes("admin")) return;
    refresh().catch((caught) => setError(messageOf(caught)));
  }, []);

  async function createGovernanceBackup(event: FormEvent) {
    event.preventDefault();
    setBusy("backup");
    setError("");
    setNotice("");
    try {
      const response = await api<{ backup: GovernanceBackup }>("/api/admin/governance/backups", {
        method: "POST",
        body: JSON.stringify({ confirmation: backupConfirmation }),
      });
      setNotice(`備份 ${response.backup.backup_id} 已完成原子寫入與 SHA-256 驗證。`);
      setBackupConfirmation("");
      await refresh();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy("");
    }
  }

  async function createIsolationRestore(event: FormEvent) {
    event.preventDefault();
    if (!selectedBackup) return;
    setBusy("restore");
    setError("");
    setNotice("");
    try {
      const response = await api<{ receipt: RestoreReceipt }>("/api/admin/governance/restores", {
        method: "POST",
        body: JSON.stringify({ backup_id: selectedBackup, confirmation: restoreConfirmation }),
      });
      setNotice(`隔離環境 ${response.receipt.target_environment_id} 已建立；沒有恢復執行權威。`);
      setRestoreConfirmation("");
      await refresh();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy("");
    }
  }

  if (!actor.roles.includes("admin")) return <section><div className="page-intro compact"><div><span className="eyebrow">BACKUP GOVERNANCE</span><h1>資料遷移與備份不在目前角色範圍。</h1><p>只有 admin 能查看 migration ledger、建立去內容備份與隔離還原。</p></div></div></section>;
  return (
    <section>
      <div className="page-intro compact"><div><span className="eyebrow">MIGRATION · CONTENT-FREE BACKUP · ISOLATED RESTORE</span><h1>備份資料關係，不帶回執行權威。</h1><p>Migration checksum、備份白名單與還原收據都由後端實際產生。還原只建立新的唯讀隔離環境，不覆寫正式資料庫、不建立 Session，也不重放 MCP 工具。</p></div><div className="scope-card"><span>目前 Schema</span><strong>{migrations?.current_schema ?? "讀取中"}</strong><p>{migrations?.pending_count ?? "—"} 個待執行 · checksum {migrations?.checksum_drift ? "異常" : "一致"}</p></div></div>
      {error && <div className="alert error" role="alert">{error}</div>}{notice && <div className="alert success" role="status">{notice}</div>}
      <div className="backup-governance-grid">
        <article className="migration-ledger"><div className="stream-heading"><div><span className="kicker">MIGRATION LEDGER</span><h2>固定遷移序列</h2></div><button className="secondary" onClick={() => refresh()}>重新驗證</button></div>{migrations?.items.map((item) => <div className="migration-row" key={item.migration_id}><span className={`migration-mark ${item.status}`} /><div><strong>{item.migration_id}</strong><small>{item.from_schema} → {item.to_schema}</small></div><code>{item.checksum_sha256.slice(0, 12)}…</code><span className={`state-pill ${item.status === "applied" && item.checksum_matches ? "approved" : "rejected"}`}>{item.status === "applied" ? "已套用" : item.status}{!item.checksum_matches ? "／雜湊漂移" : ""}</span></div>)}</article>

        <article className="backup-preview-card"><span className="kicker">CONTENT-FREE PROJECTION</span><h2>備份預覽</h2><p>{preview?.warning}</p><div className="backup-counts">{Object.entries(preview?.counts ?? {}).map(([name, count]) => <span key={name}><b>{count}</b><small>{name}</small></span>)}</div><div className="include-exclude"><div><strong>會包含</strong><ul>{preview?.included.map((item) => <li key={item}>{item}</li>)}</ul></div><div className="excluded"><strong>一律排除</strong><ul>{preview?.excluded.map((item) => <li key={item}>{item}</li>)}</ul></div></div><form className="confirmation-form" onSubmit={createGovernanceBackup}><label>輸入確認文字<input value={backupConfirmation} onChange={(event) => setBackupConfirmation(event.target.value)} placeholder={preview?.confirmation_phrase} /></label><button className="primary" disabled={busy !== "" || backupConfirmation !== preview?.confirmation_phrase}>{busy === "backup" ? "正在原子寫入與驗證…" : "建立去內容備份"}</button></form></article>

        <article className="backup-history"><span className="kicker">VERIFIED BACKUPS</span><h2>已驗證備份</h2>{backups.length === 0 ? <div className="empty compact-empty"><strong>尚無備份</strong><p>先完成上方白名單預覽與二次確認。</p></div> : backups.map((item) => <div className="backup-record" key={item.backup_id}><div><strong>{item.backup_id}</strong><small>{new Date(item.created_at * 1000).toLocaleString("zh-TW")} · {(item.byte_size / 1024).toFixed(1)} KiB</small></div><code>{item.sha256.slice(0, 18)}…</code><a className="download-link" href={`/api/admin/governance/backups/${item.backup_id}/download`}>下載</a></div>)}</article>

        <article className="restore-panel"><span className="kicker">NEW RESTORE ISOLATION</span><h2>建立唯讀隔離還原</h2><p>目標路徑由後端建立。還原資料不能核准、執行、套用設定或觸發 MCP。</p><form className="confirmation-form" onSubmit={createIsolationRestore}><label>選擇已驗證備份<select value={selectedBackup} onChange={(event) => setSelectedBackup(event.target.value)}>{backups.map((item) => <option key={item.backup_id} value={item.backup_id}>{item.backup_id} · {item.schema_version}</option>)}</select></label><label>輸入確認文字<input value={restoreConfirmation} onChange={(event) => setRestoreConfirmation(event.target.value)} placeholder="建立唯讀隔離還原" /></label><button className="primary write" disabled={busy !== "" || !selectedBackup || restoreConfirmation !== "建立唯讀隔離還原"}>{busy === "restore" ? "正在驗證並建立新隔離環境…" : "建立隔離還原"}</button></form></article>
      </div>
      <div className="restore-receipts"><div className="stream-heading"><div><span className="kicker">RESTORE RECEIPTS</span><h2>不可重放證明</h2></div><span>{restores.length} 筆</span></div>{restores.length === 0 ? <div className="empty compact-empty"><strong>尚無還原收據</strong><p>建立隔離還原後，零權威計數會顯示在這裡。</p></div> : restores.map((item) => <article key={item.restore_id}><header><div><strong>{item.restore_id}</strong><small>{item.backup_id} · {item.target_environment_id}</small></div><span className="state-pill approved">唯讀</span></header><div className="zero-authority"><span><b>{item.sessions}</b>Sessions</span><span><b>{item.auth_contexts}</b>Auth contexts</span><span><b>{item.active_approvals}</b>有效核准</span><span><b>{item.auto_replay}</b>自動重放</span><span><b>{item.mcp_calls}</b>MCP 呼叫</span></div><p>{item.source_db_unchanged ? "來源資料內容雜湊未改變" : "來源內容發生變動，需停止使用"} · {item.restored_profile_candidates} 組待驗證設定 · {item.restored_business_records} 筆唯讀關係</p><code>{item.target_relative_path}</code></article>)}</div>
    </section>
  );
}

function AccountsPanel({ actor, profiles }: { actor: Actor; profiles: Profile[] }) {
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("operator");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState("");
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [editScopes, setEditScopes] = useState<string[]>([]);
  const [editProfiles, setEditProfiles] = useState<string[]>([]);
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>({});
  const [busyAction, setBusyAction] = useState("");
  const isAdmin = actor.roles.includes("admin");
  const allScopes = [...new Set(profiles.flatMap((item) => item.effective_device_scope))];

  async function refresh() {
    const response = await api<{ items: LocalUser[] }>("/api/admin/users");
    setUsers(response.items);
  }

  useEffect(() => {
    if (isAdmin) refresh().catch((caught) => setError(messageOf(caught)));
  }, [isAdmin]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    const roles = role === "viewer" ? ["viewer"] : [role, "viewer"];
    const deviceScopes = [...new Set(profiles.flatMap((item) => item.effective_device_scope))];
    try {
      await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ username, password, roles, device_scopes: deviceScopes, profile_ids: profiles.map((item) => item.profile_id) }),
      });
      setMessage(`已建立 ${username}；密碼不會再次顯示。`);
      setUsername("");
      setPassword("");
      await refresh();
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  function toggle(list: string[], value: string, update: (next: string[]) => void) {
    update(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  }

  function startEditing(user: LocalUser) {
    setEditingId(user.user_id);
    setEditRoles(user.roles);
    setEditScopes(user.device_scopes);
    setEditProfiles(user.profile_ids);
  }

  async function mutate(key: string, action: () => Promise<unknown>, success: string) {
    setBusyAction(key);
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
      setEditingId("");
      await refresh();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusyAction("");
    }
  }

  if (!isAdmin) return <section><div className="page-intro compact"><div><span className="eyebrow">IDENTITY GOVERNANCE</span><h1>帳號治理不在目前角色範圍。</h1><p>admin 不會因為管理權限自動取得 reviewer 或 operator。</p></div></div></section>;
  return (
    <section>
      <div className="page-intro compact"><div><span className="eyebrow">LOCAL IDENTITY</span><h1>帳號從建立到撤權，都能被治理。</h1><p>可停用、重設密碼與縮放角色／設備／Profile；每次變更都撤銷該帳號的既有工作階段，且 admin 不能停用自己或移除自己的管理權。</p></div></div>
      {error && <div className="alert error" role="alert">{error}</div>}{message && <div className="alert success" role="status">{message}</div>}
      <div className="account-layout">
        <form className="proposal-form" onSubmit={create}><span className="kicker">CREATE ACCOUNT</span><h2>新增本機帳號</h2><label>帳號<input value={username} onChange={(event) => setUsername(event.target.value)} minLength={3} required /></label><label>初始密碼<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={10} required /></label><label>主要角色<select value={role} onChange={(event) => setRole(event.target.value)}><option value="operator">operator · 提案與執行</option><option value="reviewer">reviewer · 獨立審核</option><option value="viewer">viewer · 查看</option><option value="admin">admin · 帳號治理</option></select></label><div className="permission-preview"><span>資料範圍</span><strong>目前兩組 Profile 的合成設備</strong><small>角色仍受自審、核准人數與設備交集限制。</small></div><button className="primary">建立帳號</button></form>
        <div className="user-list"><div className="stream-heading"><div><span className="kicker">ACCOUNT LIFECYCLE</span><h2>本機帳號</h2></div><span>{users.length} 位</span></div>{users.map((user) => (
          <article className="user-card" key={user.user_id}>
            <div className="user-summary"><span className={`user-dot ${user.active ? "active" : ""}`} /><div><strong>{user.username}</strong><small>{user.user_id} · 權限版本 {user.session_epoch}</small></div><div className="role-tags">{user.roles.map((item) => <span key={item}>{item}</span>)}</div></div>
            <div className="account-actions"><button className="secondary" onClick={() => startEditing(user)}>編輯權限</button><button className="quiet" disabled={user.user_id === actor.user_id || busyAction !== ""} onClick={() => mutate(`status-${user.user_id}`, () => api(`/api/admin/users/${user.user_id}/status`, { method: "PATCH", body: JSON.stringify({ active: !user.active }) }), user.active ? `已停用 ${user.username} 並撤銷工作階段。` : `已重新啟用 ${user.username}。`)}>{user.active ? "停用帳號" : "重新啟用"}</button></div>
            {editingId === user.user_id && <div className="account-editor">
              <fieldset><legend>角色</legend>{["viewer", "operator", "reviewer", "admin"].map((item) => <label key={item}><input type="checkbox" checked={editRoles.includes(item)} disabled={user.user_id === actor.user_id && item === "admin"} onChange={() => toggle(editRoles, item, setEditRoles)} />{item}</label>)}</fieldset>
              <fieldset><legend>設備範圍</legend>{allScopes.map((item) => <label key={item}><input type="checkbox" checked={editScopes.includes(item)} onChange={() => toggle(editScopes, item, setEditScopes)} />{item}</label>)}</fieldset>
              <fieldset><legend>工作設定</legend>{profiles.map((item) => <label key={item.profile_id}><input type="checkbox" checked={editProfiles.includes(item.profile_id)} onChange={() => toggle(editProfiles, item.profile_id, setEditProfiles)} />{item.display_name}</label>)}</fieldset>
              <button className="primary" disabled={busyAction !== ""} onClick={() => mutate(`access-${user.user_id}`, () => api(`/api/admin/users/${user.user_id}/access`, { method: "PUT", body: JSON.stringify({ roles: editRoles, device_scopes: editScopes, profile_ids: editProfiles }) }), `已更新 ${user.username} 的權限並撤銷舊工作階段。`)}>儲存權限並撤權</button>
              <label className="password-reset">新密碼<input type="password" minLength={10} value={resetPasswords[user.user_id] ?? ""} onChange={(event) => setResetPasswords((current) => ({ ...current, [user.user_id]: event.target.value }))} placeholder="至少 10 個字元" /></label>
              <button className="secondary" disabled={(resetPasswords[user.user_id]?.length ?? 0) < 10 || busyAction !== ""} onClick={() => mutate(`password-${user.user_id}`, () => api(`/api/admin/users/${user.user_id}/password-reset`, { method: "POST", body: JSON.stringify({ password: resetPasswords[user.user_id] }) }), `已重設 ${user.username} 的密碼並撤銷舊工作階段。`)}>重設密碼</button>
            </div>}
          </article>
        ))}</div>
      </div>
    </section>
  );
}

function ToolWorkspace({ actor, onLogout }: { actor: Actor; onLogout: () => void }) {
  const [screen, setScreen] = useState<Screen>("tools");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [tools, setTools] = useState<Tool[]>([]);
  const [selectedTool, setSelectedTool] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [argumentsState, setArgumentsState] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(true);
  const [invoking, setInvoking] = useState(false);
  const [error, setError] = useState("");

  const profile = useMemo(() => profiles.find((item) => item.profile_id === profileId), [profiles, profileId]);
  const tool = useMemo(() => tools.find((item) => item.name === selectedTool), [tools, selectedTool]);
  const readTools = useMemo(() => tools.filter((item) => item.name !== "create_maintenance_order"), [tools]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [screen]);

  async function refreshProfiles() {
    const response = await api<{ items: Profile[] }>("/api/profiles");
    setProfiles(response.items);
    setProfileId((current) => response.items.some((item) => item.profile_id === current) ? current : response.items[0]?.profile_id ?? "");
  }

  async function refreshTraces() {
    const response = await api<{ items: Trace[] }>("/api/traces");
    setTraces(response.items);
  }

  useEffect(() => {
    let active = true;
    Promise.all([
      api<{ items: Profile[] }>("/api/profiles"),
      api<{ items: Tool[] }>("/api/tools"),
      api<Health>("/api/health"),
      api<{ items: Trace[] }>("/api/traces"),
    ])
      .then(([profileData, toolData, healthData, traceData]) => {
        if (!active) return;
        setProfiles(profileData.items);
        setProfileId(profileData.items[0]?.profile_id ?? "");
        setTools(toolData.items);
        setSelectedTool(toolData.items.find((item) => item.name !== "create_maintenance_order")?.name ?? "");
        setHealth(healthData);
        setTraces(traceData.items);
      })
      .catch((caught) => active && setError(messageOf(caught)))
      .finally(() => active && setBusy(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!profile || !tool) return;
    const next: Record<string, unknown> = {};
    for (const [name, schema] of Object.entries(tool.inputSchema.properties ?? {})) {
      if (name === "equipment_id") next[name] = profile.effective_device_scope[0] ?? "";
      else if (name === "part_id") next[name] = "PT-BRG-6204";
      else next[name] = schema.default ?? "";
    }
    setArgumentsState(next);
    setResult(null);
  }, [profile, tool]);

  async function invoke(event: FormEvent) {
    event.preventDefault();
    if (!tool || !profile) return;
    setInvoking(true);
    setError("");
    setResult(null);
    try {
      const response = await api<{ result: Record<string, unknown> }>(`/api/tools/${tool.name}/invoke`, {
        method: "POST",
        body: JSON.stringify({ profile_id: profile.profile_id, arguments: argumentsState }),
      });
      setResult(response.result);
      await refreshTraces();
    } catch (caught) {
      const typed = caught as ApiError;
      setError(`${typed.message}${typed.nextAction ? `｜${typed.nextAction}` : ""}`);
      await refreshTraces().catch(() => undefined);
    } finally {
      setInvoking(false);
    }
  }

  async function logoutNow() {
    await api("/api/logout", { method: "POST" });
    onLogout();
  }

  if (busy) return <main className="loading-screen"><div className="pulse" /><h1>正在確認 MCP 與資料邊界</h1><p>工具探索、環境與角色會從真實服務載入。</p></main>;

  return (
    <div className="app-shell" style={{ "--profile": profile?.color ?? "#08786c" } as React.CSSProperties}>
      <header className="topbar">
        <div className="brand"><span className="brand-mark">TG</span><div><strong>工具治理工作台</strong><small>MCP · LOCAL PRODUCT</small></div></div>
        <div className="context-bar">
          <span className="status success"><i />{health?.status === "healthy" ? "服務正常" : "檢查中"}</span>
          <label className="profile-picker">工作方式<select aria-label="選擇工作方式" value={profileId} onChange={(event) => setProfileId(event.target.value)}>{profiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.display_name}</option>)}</select></label>
          <div className="actor"><span>{actor.username.slice(0, 1).toUpperCase()}</span><div><strong>{actor.username}</strong><small>{actor.roles.join(" · ")}</small></div></div>
          <button className="quiet" onClick={logoutNow}>登出</button>
        </div>
      </header>

      <aside className="sidebar" aria-label="主要導覽">
        <div>
          <span className="nav-label">工作</span>
          <button className={screen === "tools" ? "active" : ""} onClick={() => setScreen("tools")}><b>⌁</b>工具與查詢</button>
          <button className={screen === "workflow" ? "active" : ""} onClick={() => setScreen("workflow")}><b>✓</b>提案與核准</button>
          <button className={screen === "traces" ? "active" : ""} onClick={() => setScreen("traces")}><b>↳</b>Trace</button>
        </div>
        <div>
          <span className="nav-label">治理</span>
          {actor.roles.includes("admin") && <button className={screen === "accounts" ? "active" : ""} onClick={() => setScreen("accounts")}><b>◎</b>帳號治理</button>}
          {(actor.roles.includes("admin") || actor.roles.includes("reviewer")) && <button className={screen === "configs" ? "active" : ""} onClick={() => setScreen("configs")}><b>◫</b>設定版本</button>}
          {actor.roles.includes("admin") && <button className={screen === "backups" ? "active" : ""} onClick={() => setScreen("backups")}><b>▣</b>備份與還原</button>}
          <button className={screen === "governance" ? "active" : ""} onClick={() => setScreen("governance")}><b>◇</b>污染與邊界</button>
        </div>
        <div className="env-card"><span>環境</span><strong>{health?.environment_kind}</strong><code>{health?.environment_id}</code><small>合成資料 · measured_local</small></div>
      </aside>

      <main className="content">
        {error && <div className="alert error" role="alert"><strong>目前無法完成操作</strong><span>{error}</span><button onClick={() => setError("")} aria-label="關閉錯誤">×</button></div>}

        {screen === "tools" && profile && (
          <>
            <section className="page-intro">
              <div><span className="eyebrow">READ-ONLY VERTICAL SLICE</span><h1>先看清楚，再允許工具行動。</h1><p>工具來自正式 MCP discovery。Profile 只會縮小資料範圍，不會改變登入身分。</p></div>
              <div className="scope-card"><span>有效資料範圍</span><strong>{profile.scope_label}</strong><p>{profile.effective_device_scope.length} 部設備 · policy {profile.policy_version}</p></div>
            </section>

            <section className="tool-grid" aria-label="MCP 工具目錄">
              {readTools.map((item) => (
                <button key={item.name} className={`tool-card ${selectedTool === item.name ? "selected" : ""}`} onClick={() => setSelectedTool(item.name)}>
                  <span className="tool-icon">{toolIcon[item.name] ?? "具"}</span>
                  <span className="tool-copy"><small>READ · MCP v1</small><strong>{item.title ?? item.name}</strong><em>{item.description}</em></span>
                  <span className="arrow">→</span>
                </button>
              ))}
            </section>

            {tool && (
              <section className="workbench">
                <div className="workbench-head"><div><span className="kicker">SCHEMA FORM</span><h2>{tool.title}</h2><p>欄位由 MCP inputSchema 產生；身分與核准不會成為工具參數。</p></div><div className="contract"><span>Transport<strong>{health?.mcp.transport}</strong></span><span>Protocol<strong>{health?.mcp.protocol_version}</strong></span><span>Mode<strong>唯讀</strong></span></div></div>
                <div className="workbench-body">
                  <form className="query-form" onSubmit={invoke}>
                    {Object.entries(tool.inputSchema.properties ?? {}).map(([name, schema]) => (
                      <label key={name}>{fieldLabels[name] ?? name}<small>{tool.inputSchema.required?.includes(name) ? "必填" : "選填"}</small><FieldInput name={name} schema={schema} value={argumentsState[name]} profile={profile} onChange={(value) => setArgumentsState((current) => ({ ...current, [name]: value }))} /></label>
                    ))}
                    <div className="permission-preview"><span>這次呼叫會使用</span><strong>{actor.username} · {profile.scope_label}</strong><small>一次性授權 · 綁定工具、參數與環境</small></div>
                    <button className="primary" disabled={invoking}>{invoking ? "透過 MCP 查詢中…" : "執行唯讀查詢"}</button>
                  </form>
                  <div className="flow-panel" aria-label="呼叫流程">
                    <span className="kicker">LIVE CONTRACT</span><h3>實際經過四道邊界</h3>
                    <ol><li><b>01</b><div><strong>Session</strong><span>後端辨識真實登入者</span></div></li><li><b>02</b><div><strong>Policy</strong><span>角色、Profile、設備取交集</span></div></li><li><b>03</b><div><strong>MCP stdio</strong><span>一次性 context 隨 request _meta 傳遞</span></div></li><li><b>04</b><div><strong>SQLite</strong><span>再次驗證後只讀取合成資料</span></div></li></ol>
                  </div>
                </div>
              </section>
            )}
            {result && <ResultPanel payload={result} />}
          </>
        )}

        {screen === "workflow" && (
          <WorkflowPanel actor={actor} profiles={profiles} selectedProfileId={profileId} onTraceChanged={refreshTraces} />
        )}

        {screen === "accounts" && <AccountsPanel actor={actor} profiles={profiles} />}

        {screen === "configs" && <ProfileConfigPanel actor={actor} profiles={profiles} onApplied={refreshProfiles} />}

        {screen === "backups" && <BackupGovernancePanel actor={actor} />}

        {screen === "traces" && (
          <section>
            <div className="page-intro compact"><div><span className="eyebrow">TRACE EXPLORER</span><h1>每次工具呼叫，都能拆開來看。</h1><p>只顯示目前登入者可看的事件。一次性授權值不會寫入 Trace。</p></div><button className="secondary" onClick={refreshTraces}>重新整理</button></div>
            {traces.length === 0 ? <div className="empty"><strong>還沒有 Trace</strong><p>完成第一筆唯讀查詢後，流程節點會出現在這裡。</p></div> : <div className="trace-list">{traces.map((trace) => <article key={trace.event_id}><div className={`trace-dot ${trace.status}`} /><div className="trace-main"><span>{trace.event_type}</span><strong>{trace.tool_name ?? "系統事件"}</strong><small>{trace.trace_id} · #{trace.sequence}</small></div><div className="trace-meta"><span>{trace.profile_id}</span><code>{JSON.stringify(trace.summary)}</code></div></article>)}</div>}
          </section>
        )}

        {screen === "governance" && (
          <section>
            <div className="page-intro compact"><div><span className="eyebrow">DATA CONTAMINATION CONTROL</span><h1>資料不只要安全，也不能混錯。</h1><p>本切片先用硬分區、來源標籤與阻擋規則，防止展示、測試與產品資料互相污染。</p></div></div>
            <div className="governance-grid">
              <article className="boundary-map"><span className="kicker">ENVIRONMENT BOUNDARY</span><h2>五種資料，各走自己的路</h2>{["local_product｜可形成 measured_local 證據", "development｜只供開發，不算正式驗收", "automated_test｜每次使用獨立資料庫", "fixture_demo｜只存在瀏覽器，不呼叫 MCP", "restore_isolation｜唯讀還原，不復活權限"].map((item, index) => <div key={item}><b>{String(index + 1).padStart(2, "0")}</b><span>{item}</span></div>)}</article>
              <article><span className="kicker">CURRENT PROVENANCE</span><h2>目前工作區</h2><dl className="facts"><div><dt>環境種類</dt><dd>{health?.environment_kind}</dd></div><div><dt>環境指紋</dt><dd>{health?.environment_id}</dd></div><div><dt>證據種類</dt><dd>measured_local</dd></div><div><dt>資料來源</dt><dd>synthetic_seed</dd></div><div><dt>MCP 工具</dt><dd>{health?.mcp.tool_count} 個（3 讀 1 寫）</dd></div></dl></article>
              <article><span className="kicker">BLOCKED BY DESIGN</span><h2>這些操作會被拒絕</h2><ul className="checks"><li>用 Fixture 建立產品資料</li><li>以 Profile 切換擴張設備權限</li><li>把 role 或 approved 塞進工具參數</li><li>重放已使用的一次性授權</li><li>把資料庫路徑指到其他作品</li></ul></article>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default function App() {
  const [phase, setPhase] = useState<"loading" | "setup" | "login" | "workspace">("loading");
  const [actor, setActor] = useState<Actor | null>(null);

  useEffect(() => {
    api<{ needs_setup: boolean }>("/api/setup/status")
      .then(async ({ needs_setup }) => {
        if (needs_setup) return setPhase("setup");
        try {
          const response = await api<{ actor: Actor }>("/api/me");
          setActor(response.actor);
          setPhase("workspace");
        } catch {
          setPhase("login");
        }
      })
      .catch(() => setPhase("login"));
  }, []);

  if (phase === "loading") return <main className="loading-screen"><div className="pulse" /><h1>正在讀取本機產品狀態</h1></main>;
  if (phase === "setup") return <AuthPanel mode="setup" onAuthenticated={(next) => { setActor(next); setPhase("workspace"); }} />;
  if (phase === "login") return <AuthPanel mode="login" onAuthenticated={(next) => { setActor(next); setPhase("workspace"); }} />;
  return actor ? <ToolWorkspace actor={actor} onLogout={() => { setActor(null); setPhase("login"); }} /> : null;
}

