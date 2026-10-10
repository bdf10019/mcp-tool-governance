import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";


function json(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }));
}

const actor = {
  user_id: "USR-1",
  username: "portfolio-admin",
  roles: ["admin", "viewer"],
  device_scopes: ["EQ-PUMP-001"],
  profile_ids: ["service-v1"],
};

const operatorActor = {
  ...actor,
  username: "operator-one",
  roles: ["operator", "viewer"],
};

const profile = {
  profile_id: "service-v1",
  version: "1.0.0",
  display_name: "維修服務團隊",
  scope_label: "SERVICE-A",
  color: "#08786c",
  policy_version: "service-policy-v1",
  settings: { approval_count: 1, terminology: "維修案件", read_tools: 3 },
  effective_device_scope: ["EQ-PUMP-001"],
  source_sha256: "abc",
};

const tool = {
  name: "get_equipment_status",
  title: "設備狀態查詢",
  description: "查詢設備狀態",
  inputSchema: {
    type: "object",
    properties: { equipment_id: { type: "string" } },
    required: ["equipment_id"],
  },
};

describe("App", () => {
  beforeEach(() => {
    document.cookie = "mcp_csrf=test-csrf; path=/";
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows first-admin setup without a seeded account", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json({ needs_setup: true })));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "建立第一位管理者" })).toBeInTheDocument();
    expect(screen.getByText(/不會建立展示帳號/)).toBeInTheDocument();
  });

  it("loads MCP discovery, profile scope and governance after authentication", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/setup/status") return json({ needs_setup: false });
      if (path === "/api/me") return json({ actor });
      if (path === "/api/profiles") return json({ items: [profile] });
      if (path === "/api/tools") return json({ items: [tool] });
      if (path === "/api/health") return json({ status: "healthy", environment_kind: "automated_test", environment_id: "automated_test-abc", actor_id: "USR-1", mcp: { transport: "stdio", protocol_version: "2026-07-28", tool_count: 3 } });
      if (path === "/api/traces") return json({ items: [] });
      return json({ error: { message: "not found" } }, 404);
    }));
    render(<App />);
    expect(await screen.findByRole("heading", { name: /先看清楚/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /設備狀態查詢/ })).toBeInTheDocument();
    expect(screen.getByText("SERVICE-A")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /污染與邊界/ }));
    expect(screen.getByRole("heading", { name: /資料不只要安全/ })).toBeInTheDocument();
  });

  it("renders a structured result after a real-shape API response", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/setup/status") return json({ needs_setup: false });
      if (path === "/api/me") return json({ actor });
      if (path === "/api/profiles") return json({ items: [profile] });
      if (path === "/api/tools") return json({ items: [tool] });
      if (path === "/api/health") return json({ status: "healthy", environment_kind: "automated_test", environment_id: "automated_test-abc", actor_id: "USR-1", mcp: { transport: "stdio", protocol_version: "2026-07-28", tool_count: 3 } });
      if (path === "/api/traces") return json({ items: [] });
      if (path.includes("/invoke") && init?.method === "POST") return json({ trace_id: "TRC-1", result: { equipment_id: "EQ-PUMP-001", status: "degraded", environment_kind: "automated_test" } });
      return json({ error: { message: "not found" } }, 404);
    }));
    render(<App />);
    const button = await screen.findByRole("button", { name: "執行唯讀查詢" });
    await userEvent.click(button);
    await waitFor(() => expect(screen.getByRole("heading", { name: "查詢結果" })).toBeInTheDocument());
    expect(screen.getByText("degraded")).toBeInTheDocument();
  });

  it("shows the proposal workflow for an operator", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/setup/status") return json({ needs_setup: false });
      if (path === "/api/me") return json({ actor: operatorActor });
      if (path === "/api/profiles") return json({ items: [profile] });
      if (path === "/api/tools") return json({ items: [tool] });
      if (path === "/api/health") return json({ status: "healthy", environment_kind: "automated_test", environment_id: "automated_test-abc", actor_id: "USR-1", mcp: { transport: "stdio", protocol_version: "2026-07-28", tool_count: 4 } });
      if (path === "/api/traces" || path === "/api/proposals" || path === "/api/orders") return json({ items: [] });
      return json({ error: { message: "not found" } }, 404);
    }));
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /提案與核准/ }));
    expect(await screen.findByRole("heading", { name: /先提案、再核准/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "建立草稿" })).toBeInTheDocument();
    expect(screen.getByText("內容保存期限")).toBeInTheDocument();
    expect(screen.getByLabelText(/7 日/)).toBeChecked();
  });

  it("shows account governance only to admin", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/setup/status") return json({ needs_setup: false });
      if (path === "/api/me") return json({ actor });
      if (path === "/api/profiles") return json({ items: [profile] });
      if (path === "/api/tools") return json({ items: [tool] });
      if (path === "/api/health") return json({ status: "healthy", environment_kind: "automated_test", environment_id: "automated_test-abc", actor_id: "USR-1", mcp: { transport: "stdio", protocol_version: "2026-07-28", tool_count: 4 } });
      if (path === "/api/traces") return json({ items: [] });
      if (path === "/api/admin/users") return json({ items: [{ ...actor, active: true, session_epoch: 1 }] });
      return json({ error: { message: "not found" } }, 404);
    }));
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /帳號治理/ }));
    expect(await screen.findByRole("heading", { name: /帳號從建立到撤權/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "編輯權限" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停用帳號" })).toBeDisabled();
  });

  it("shows versioned profile configuration with an active baseline", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/setup/status") return json({ needs_setup: false });
      if (path === "/api/me") return json({ actor });
      if (path === "/api/profiles") return json({ items: [profile] });
      if (path === "/api/tools") return json({ items: [tool] });
      if (path === "/api/health") return json({ status: "healthy", environment_kind: "automated_test", environment_id: "automated_test-abc", actor_id: "USR-1", mcp: { transport: "stdio", protocol_version: "2026-07-28", tool_count: 4 } });
      if (path === "/api/traces") return json({ items: [] });
      if (path === "/api/profile-configs") return json({ items: [{ profile_id: "service-v1", revision: 1, version: "1.0.0", policy_version: "service-policy-v1", status: "active", snapshot: { ...profile, equipment_ids: profile.effective_device_scope }, snapshot_sha256: "abc", created_by: "system-seed", created_at: 1, updated_at: 1, diff: [], approvals: [] }] });
      return json({ error: { message: "not found" } }, 404);
    }));
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /設定版本/ }));
    expect(await screen.findByRole("heading", { name: /客製化要能預覽/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "建立設定草稿" })).toBeInTheDocument();
    expect(screen.getAllByText("1.0.0", { exact: true }).length).toBeGreaterThanOrEqual(2);
  });

  it("shows migration, content-free backup and zero-authority restore evidence", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/setup/status") return json({ needs_setup: false });
      if (path === "/api/me") return json({ actor });
      if (path === "/api/profiles") return json({ items: [profile] });
      if (path === "/api/tools") return json({ items: [tool] });
      if (path === "/api/health") return json({ status: "healthy", environment_kind: "automated_test", environment_id: "automated_test-abc", actor_id: "USR-1", mcp: { transport: "stdio", protocol_version: "2026-07-28", tool_count: 4 } });
      if (path === "/api/traces") return json({ items: [] });
      if (path === "/api/admin/governance/migrations") return json({ current_schema: "p2d3-1", target_schema: "p2d3-1", pending_count: 0, checksum_drift: false, items: [{ migration_id: "004-p2d3-backup-restore", from_schema: "p2d2-1", to_schema: "p2d3-1", checksum_sha256: "a".repeat(64), status: "applied", checksum_matches: true }] });
      if (path === "/api/admin/governance/backup-preview") return json({ format: "mcp-governance-backup-v1", source_environment_kind: "automated_test", source_environment_id: "automated_test-abc", schema_version: "p2d3-1", counts: { profiles: 2 }, identity_summary: { user_count: 1, role_counts: { admin: 1 }, profile_scope_counts: { "service-v1": 1 } }, included: ["設定白名單快照"], excluded: ["Session 與密碼"], confirmation_phrase: "建立去內容備份", warning: "這不是災難復原檔。" });
      if (path === "/api/admin/governance/backups") return json({ items: [{ backup_id: "BKP-123456789ABC", status: "verified", created_at: 1, schema_version: "p2d3-1", sha256: "b".repeat(64), byte_size: 1024, payload_sha256: "c".repeat(64), counts: { profiles: 2 }, authority_included: false }] });
      if (path === "/api/admin/governance/restores") return json({ items: [{ restore_id: "RST-123456789ABC", backup_id: "BKP-123456789ABC", created_at: 1, target_environment_kind: "restore_isolation", target_environment_id: "restore_isolation-abc", target_relative_path: "state/restore_isolation/rst/app.db", source_db_unchanged: true, source_content_sha256: "d".repeat(64), read_only: true, restored_profile_candidates: 2, restored_business_records: 0, sessions: 0, auth_contexts: 0, active_approvals: 0, auto_replay: 0, mcp_calls: 0 }] });
      return json({ error: { message: "not found" } }, 404);
    }));
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /備份與還原/ }));
    expect(await screen.findByRole("heading", { name: /備份資料關係/ })).toBeInTheDocument();
    expect(screen.getByText("p2d3-1", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("一律排除")).toBeInTheDocument();
    expect(screen.getByText("不可重放證明")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(5);
  });
});

