export type Actor = {
  user_id: string;
  username: string;
  roles: string[];
  device_scopes: string[];
  profile_ids: string[];
};

export type Profile = {
  profile_id: string;
  version: string;
  display_name: string;
  scope_label: string;
  color: string;
  policy_version: string;
  settings: {
    approval_count: number;
    terminology: string;
    read_tools: number;
    write_tool?: string;
    maintenance_window_required?: boolean;
    risk_summary_required?: boolean;
    retention_default_days?: number;
  };
  effective_device_scope: string[];
  source_sha256: string;
};

export type JsonSchema = {
  type?: string;
  title?: string;
  default?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
};

export type Tool = {
  name: string;
  title?: string;
  description?: string;
  inputSchema: JsonSchema;
  outputSchema?: JsonSchema;
};

export type Health = {
  status: string;
  environment_kind: string;
  environment_id: string;
  actor_id: string;
  mcp: { transport: string; protocol_version: string; tool_count: number };
};

export type Trace = {
  event_id: number;
  trace_id: string;
  sequence: number;
  event_type: string;
  status: string;
  tool_name?: string;
  actor_id?: string;
  profile_id?: string;
  summary: Record<string, unknown>;
  environment_id: string;
  evidence_kind: string;
  created_at: number;
};

export type Approval = {
  approval_id: string;
  reviewer_id: string;
  reviewer_name: string;
  decision: string;
  reason: string;
  created_at: number;
};

export type Proposal = {
  proposal_id: string;
  proposal_version: number;
  profile_id: string;
  profile_version: string;
  policy_version: string;
  tool_name: string;
  equipment_id: string;
  parameters: Record<string, string>;
  parameters_sha256: string;
  equipment_data_version: string;
  status: string;
  required_approvals: number;
  proposer_id: string;
  expires_at?: number;
  idempotency_suffix: string;
  environment_id: string;
  source_kind: string;
  evidence_kind: string;
  retention_days: number;
  content_expires_at: number;
  content_state: "available" | "purged";
  purged_at?: number;
  created_at: number;
  updated_at: number;
  approvals: Approval[];
};

export type MaintenanceOrder = {
  order_id: string;
  order_status: string;
  order_version: number;
  proposal_id: string;
  proposal_version: number;
  execution_id: string;
  equipment_id: string;
  profile_id: string;
  issue_summary: string;
  priority: string;
  maintenance_window: string;
  risk_summary: string;
  environment_id: string;
  source_kind: string;
  evidence_kind: string;
  created_at: number;
};

export type LocalUser = {
  user_id: string;
  username: string;
  roles: string[];
  device_scopes: string[];
  profile_ids: string[];
  active: boolean;
  session_epoch?: number;
  created_at?: number;
};

export type ProfileConfigSnapshot = {
  profile_id: string;
  display_name: string;
  scope_label: string;
  color: string;
  settings: Profile["settings"] & {
    write_tool: string;
    maintenance_window_required: boolean;
    risk_summary_required: boolean;
    retention_default_days: number;
  };
  equipment_ids: string[];
};

export type ProfileConfigVersion = {
  profile_id: string;
  revision: number;
  version: string;
  policy_version: string;
  status: string;
  snapshot: ProfileConfigSnapshot;
  snapshot_sha256: string;
  created_by: string;
  derived_from_version?: string;
  expires_at?: number;
  created_at: number;
  updated_at: number;
  diff: { field: string; before: unknown; after: unknown }[];
  approvals: Approval[];
};

export type MigrationItem = {
  migration_id: string;
  from_schema: string;
  to_schema: string;
  checksum_sha256: string;
  status: string;
  started_at?: number;
  finished_at?: number;
  error_code?: string;
  checksum_matches: boolean;
};

export type MigrationOverview = {
  current_schema: string;
  target_schema: string;
  pending_count: number;
  checksum_drift: boolean;
  items: MigrationItem[];
};

export type BackupPreview = {
  format: string;
  source_environment_kind: string;
  source_environment_id: string;
  schema_version: string;
  counts: Record<string, number>;
  identity_summary: {
    user_count: number;
    role_counts: Record<string, number>;
    profile_scope_counts: Record<string, number>;
  };
  included: string[];
  excluded: string[];
  confirmation_phrase: string;
  warning: string;
};

export type GovernanceBackup = {
  backup_id: string;
  status: string;
  created_at: number;
  schema_version: string;
  sha256: string;
  byte_size: number;
  payload_sha256: string;
  counts: Record<string, number>;
  authority_included: boolean;
};

export type RestoreReceipt = {
  restore_id: string;
  backup_id: string;
  created_at: number;
  target_environment_kind: "restore_isolation";
  target_environment_id: string;
  target_relative_path: string;
  source_db_unchanged: boolean;
  source_content_sha256: string;
  read_only: boolean;
  restored_profile_candidates: number;
  restored_business_records: number;
  sessions: number;
  auth_contexts: number;
  active_approvals: number;
  auto_replay: number;
  mcp_calls: number;
};

