from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import Settings
from .security import canonical_hash


SCHEMA_VERSION = "p2d3-1"
SEED_VERSION = "synthetic-equipment-v1"


DDL = """
CREATE TABLE IF NOT EXISTS app_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  migration_id TEXT PRIMARY KEY,
  checksum_sha256 TEXT NOT NULL,
  from_schema TEXT NOT NULL,
  to_schema TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at INTEGER,
  finished_at INTEGER,
  error_code TEXT
);
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  roles_json TEXT NOT NULL,
  device_scopes_json TEXT NOT NULL,
  profile_ids_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  session_epoch INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  session_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  csrf_hash TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  profile_id TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  display_name TEXT NOT NULL,
  scope_label TEXT NOT NULL,
  color TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  settings_json TEXT NOT NULL,
  source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equipment (
  equipment_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  data_version TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_equipment (
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
  equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
  PRIMARY KEY(profile_id, equipment_id)
);
CREATE TABLE IF NOT EXISTS profile_config_versions (
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
  revision INTEGER NOT NULL,
  version TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  status TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  snapshot_sha256 TEXT NOT NULL,
  created_by TEXT NOT NULL,
  derived_from_version TEXT,
  expires_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(profile_id, revision),
  UNIQUE(profile_id, version)
);
CREATE INDEX IF NOT EXISTS idx_profile_config_status
  ON profile_config_versions(status, updated_at DESC);
CREATE TABLE IF NOT EXISTS profile_config_approvals (
  approval_id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  reviewer_id TEXT NOT NULL REFERENCES users(user_id),
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  snapshot_sha256 TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY(profile_id, revision) REFERENCES profile_config_versions(profile_id, revision),
  UNIQUE(profile_id, revision, reviewer_id)
);
CREATE TABLE IF NOT EXISTS maintenance_history (
  record_id TEXT PRIMARY KEY,
  equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
  category TEXT NOT NULL,
  summary TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  part_ids_json TEXT NOT NULL,
  data_version TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parts (
  part_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  stock_quantity INTEGER NOT NULL,
  unit TEXT NOT NULL,
  data_version TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS part_compatibility (
  part_id TEXT NOT NULL REFERENCES parts(part_id),
  equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
  basis TEXT NOT NULL,
  PRIMARY KEY(part_id, equipment_id)
);
CREATE TABLE IF NOT EXISTS auth_contexts (
  token_hash TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  session_epoch INTEGER NOT NULL,
  tool_name TEXT NOT NULL,
  args_sha256 TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  target_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS traces (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL,
  tool_name TEXT,
  actor_id TEXT,
  profile_id TEXT,
  summary_json TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  evidence_kind TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(trace_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_traces_actor ON traces(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_equipment ON maintenance_history(equipment_id, started_at DESC);
CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL,
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
  profile_version TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
  parameters_json TEXT NOT NULL,
  parameters_sha256 TEXT NOT NULL,
  equipment_data_version TEXT NOT NULL,
  status TEXT NOT NULL,
  required_approvals INTEGER NOT NULL,
  proposer_id TEXT NOT NULL REFERENCES users(user_id),
  expires_at INTEGER,
  idempotency_key TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  evidence_kind TEXT NOT NULL,
  retention_days INTEGER NOT NULL DEFAULT 7,
  content_expires_at INTEGER,
  content_state TEXT NOT NULL DEFAULT 'available',
  purged_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(proposal_id, proposal_version)
);
CREATE INDEX IF NOT EXISTS idx_proposals_actor ON proposals(proposer_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_proposals_review ON proposals(status, profile_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL,
  reviewer_id TEXT NOT NULL REFERENCES users(user_id),
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  parameters_sha256 TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY(proposal_id, proposal_version) REFERENCES proposals(proposal_id, proposal_version),
  UNIQUE(proposal_id, proposal_version, reviewer_id)
);
CREATE TABLE IF NOT EXISTS executions (
  execution_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL,
  operator_id TEXT NOT NULL REFERENCES users(user_id),
  environment_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  order_id TEXT,
  trace_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY(proposal_id, proposal_version) REFERENCES proposals(proposal_id, proposal_version),
  UNIQUE(environment_id, tool_name, idempotency_key)
);
CREATE TABLE IF NOT EXISTS maintenance_orders (
  order_id TEXT PRIMARY KEY,
  order_status TEXT NOT NULL,
  order_version INTEGER NOT NULL,
  proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL,
  execution_id TEXT NOT NULL UNIQUE REFERENCES executions(execution_id),
  equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
  issue_summary TEXT NOT NULL,
  priority TEXT NOT NULL,
  maintenance_window TEXT NOT NULL,
  risk_summary TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  evidence_kind TEXT NOT NULL,
  created_by TEXT NOT NULL REFERENCES users(user_id),
  created_at INTEGER NOT NULL,
  FOREIGN KEY(proposal_id, proposal_version) REFERENCES proposals(proposal_id, proposal_version)
);
CREATE TABLE IF NOT EXISTS outbox_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_equipment ON maintenance_orders(equipment_id, created_at DESC);
CREATE TABLE IF NOT EXISTS governance_backups (
  backup_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  file_name TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  manifest_json TEXT NOT NULL,
  created_by TEXT NOT NULL REFERENCES users(user_id),
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS restore_receipts (
  restore_id TEXT PRIMARY KEY,
  backup_id TEXT NOT NULL REFERENCES governance_backups(backup_id),
  target_environment_id TEXT NOT NULL UNIQUE,
  target_relative_path TEXT NOT NULL UNIQUE,
  receipt_json TEXT NOT NULL,
  created_by TEXT NOT NULL REFERENCES users(user_id),
  created_at INTEGER NOT NULL
);
"""


PROFILE_SEEDS = [
    {
        "profile_id": "service-v1",
        "version": "1.0.0",
        "display_name": "維修服務團隊",
        "scope_label": "SERVICE-A",
        "color": "#08786c",
        "policy_version": "service-policy-v1",
        "equipment": ["EQ-PUMP-001", "EQ-FAN-002", "EQ-CONV-003"],
        "settings": {
            "approval_count": 1,
            "terminology": "維修案件",
            "read_tools": 3,
            "write_tool": "create_maintenance_order",
            "maintenance_window_required": False,
            "risk_summary_required": False,
            "retention_default_days": 7,
        },
    },
    {
        "profile_id": "asset-v1",
        "version": "1.0.0",
        "display_name": "設備管理團隊",
        "scope_label": "ASSET-B",
        "color": "#4f46a5",
        "policy_version": "asset-policy-v1",
        "equipment": ["EQ-PUMP-001", "EQ-CHILLER-004"],
        "settings": {
            "approval_count": 2,
            "terminology": "設備事件",
            "read_tools": 3,
            "write_tool": "create_maintenance_order",
            "maintenance_window_required": True,
            "risk_summary_required": True,
            "retention_default_days": 7,
        },
    },
]

EQUIPMENT_SEEDS = [
    ("EQ-PUMP-001", "循環水泵 01", "degraded", "2026-09-24T09:40:00+08:00", "eq-seed-v3"),
    ("EQ-FAN-002", "排風機 02", "operating", "2026-09-24T09:42:00+08:00", "eq-seed-v2"),
    ("EQ-CONV-003", "輸送帶 03", "maintenance", "2026-09-24T09:38:00+08:00", "eq-seed-v4"),
    ("EQ-CHILLER-004", "冰水主機 04", "offline", "2026-09-24T09:35:00+08:00", "eq-seed-v2"),
]

HISTORY_SEEDS = [
    ("MH-1001", "EQ-PUMP-001", "inspection", "軸承溫度偏高，已安排複查", "open", "2026-09-23T14:30:00+08:00", None, ["PT-BRG-6204"]),
    ("MH-0988", "EQ-PUMP-001", "repair", "更換機械軸封並完成試運轉", "closed", "2026-08-18T08:20:00+08:00", "2026-08-18T11:45:00+08:00", ["PT-SEAL-01"]),
    ("MH-1012", "EQ-FAN-002", "inspection", "皮帶張力正常", "closed", "2026-09-20T10:00:00+08:00", "2026-09-20T10:25:00+08:00", ["PT-BELT-A42"]),
    ("MH-1006", "EQ-CONV-003", "repair", "安全護罩感測器校正中", "open", "2026-09-22T16:10:00+08:00", None, []),
    ("MH-0999", "EQ-CHILLER-004", "incident", "冷媒壓力異常停機，等待檢查", "open", "2026-09-21T06:50:00+08:00", None, ["PT-SENSOR-P9"]),
]

PART_SEEDS = [
    ("PT-BRG-6204", "6204 軸承", 12, "個"),
    ("PT-SEAL-01", "機械軸封組", 3, "組"),
    ("PT-BELT-A42", "A42 傳動皮帶", 7, "條"),
    ("PT-SENSOR-P9", "壓力感測器 P9", 0, "個"),
]

COMPATIBILITY_SEEDS = [
    ("PT-BRG-6204", "EQ-PUMP-001", "設備 BOM v3"),
    ("PT-SEAL-01", "EQ-PUMP-001", "設備 BOM v3"),
    ("PT-BELT-A42", "EQ-FAN-002", "設備 BOM v2"),
    ("PT-SENSOR-P9", "EQ-CHILLER-004", "設備 BOM v2"),
]


def connect(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@dataclass(frozen=True)
class Migration:
    migration_id: str
    from_schema: str
    to_schema: str
    contract: str
    implementation_fingerprint: str
    apply: Callable[[sqlite3.Connection], None]

    @property
    def checksum_sha256(self) -> str:
        return canonical_hash(
            {
                "migration_id": self.migration_id,
                "from_schema": self.from_schema,
                "to_schema": self.to_schema,
                "contract": self.contract,
                "implementation_fingerprint": self.implementation_fingerprint,
            }
        )


def _migration_bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def _migration_retention(conn: sqlite3.Connection) -> None:
    _ensure_p2d1_schema(conn)


def _migration_profile_versions(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def _migration_governance(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


MIGRATIONS = (
    Migration(
        "001-p2c-core",
        "unversioned",
        "p2c-1",
        "建立本機帳號、MCP、提案、核准、執行、工單與稽核核心資料表。",
        canonical_hash(DDL),
        _migration_bootstrap,
    ),
    Migration(
        "002-p2d1-retention",
        "p2c-1",
        "p2d1-1",
        "新增提案內容保存期限、到期狀態與清除時間，並修正舊版欄位位置。",
        canonical_hash({"columns": ["retention_days", "content_expires_at", "content_state", "purged_at"], "legacy_cleanup": "traces"}),
        _migration_retention,
    ),
    Migration(
        "003-p2d2-profile-versions",
        "p2d1-1",
        "p2d2-1",
        "新增 Profile 設定版本、獨立核准及不可覆寫的版本快照。",
        canonical_hash({"ddl": canonical_hash(DDL), "tables": ["profile_config_versions", "profile_config_approvals"]}),
        _migration_profile_versions,
    ),
    Migration(
        "004-p2d3-backup-restore",
        "p2d2-1",
        "p2d3-1",
        "新增 migration ledger、去內容備份紀錄及唯讀隔離還原收據。",
        canonical_hash({"ddl": canonical_hash(DDL), "tables": ["schema_migrations", "governance_backups", "restore_receipts"]}),
        _migration_governance,
    ),
)


def _ensure_migration_ledger(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
          migration_id TEXT PRIMARY KEY,
          checksum_sha256 TEXT NOT NULL,
          from_schema TEXT NOT NULL,
          to_schema TEXT NOT NULL,
          status TEXT NOT NULL,
          started_at INTEGER,
          finished_at INTEGER,
          error_code TEXT
        );
        """
    )


def _apply_migrations(conn: sqlite3.Connection) -> None:
    _ensure_migration_ledger(conn)
    existing = {
        row["migration_id"]: row
        for row in conn.execute("SELECT * FROM schema_migrations").fetchall()
    }
    known_ids = {migration.migration_id for migration in MIGRATIONS}
    unknown_applied = [
        migration_id
        for migration_id, row in existing.items()
        if migration_id not in known_ids and row["status"] == "applied"
    ]
    if unknown_applied:
        raise RuntimeError("Migration ledger contains an unknown applied migration")

    for migration in MIGRATIONS:
        row = existing.get(migration.migration_id)
        if row and row["checksum_sha256"] != migration.checksum_sha256:
            raise RuntimeError(f"Migration checksum drift: {migration.migration_id}")
        if row and row["status"] == "applied":
            continue
        started_at = int(time.time())
        conn.execute(
            """INSERT INTO schema_migrations
               (migration_id, checksum_sha256, from_schema, to_schema, status, started_at, finished_at, error_code)
               VALUES (?, ?, ?, ?, 'running', ?, NULL, NULL)
               ON CONFLICT(migration_id) DO UPDATE SET
                 checksum_sha256=excluded.checksum_sha256,
                 from_schema=excluded.from_schema,
                 to_schema=excluded.to_schema,
                 status='running', started_at=excluded.started_at, finished_at=NULL, error_code=NULL""",
            (
                migration.migration_id,
                migration.checksum_sha256,
                migration.from_schema,
                migration.to_schema,
                started_at,
            ),
        )
        conn.commit()
        try:
            migration.apply(conn)
        except Exception:
            conn.execute(
                "UPDATE schema_migrations SET status='failed', finished_at=?, error_code='MIGRATION_FAILED' WHERE migration_id=?",
                (int(time.time()), migration.migration_id),
            )
            conn.commit()
            raise
        conn.execute(
            "UPDATE schema_migrations SET status='applied', finished_at=?, error_code=NULL WHERE migration_id=?",
            (int(time.time()), migration.migration_id),
        )
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (migration.to_schema,),
        )
        conn.commit()


def migration_status(settings: Settings) -> dict[str, Any]:
    with connect(settings) as conn:
        _ensure_migration_ledger(conn)
        rows = {
            row["migration_id"]: row
            for row in conn.execute("SELECT * FROM schema_migrations").fetchall()
        }
        items = []
        for migration in MIGRATIONS:
            row = rows.get(migration.migration_id)
            checksum_matches = row is None or row["checksum_sha256"] == migration.checksum_sha256
            items.append(
                {
                    "migration_id": migration.migration_id,
                    "from_schema": migration.from_schema,
                    "to_schema": migration.to_schema,
                    "checksum_sha256": migration.checksum_sha256,
                    "status": row["status"] if row else "planned",
                    "started_at": row["started_at"] if row else None,
                    "finished_at": row["finished_at"] if row else None,
                    "error_code": row["error_code"] if row else None,
                    "checksum_matches": checksum_matches,
                }
            )
        current = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        return {
            "current_schema": current["value"] if current else "unversioned",
            "target_schema": SCHEMA_VERSION,
            "pending_count": sum(1 for item in items if item["status"] != "applied"),
            "checksum_drift": any(not item["checksum_matches"] for item in items),
            "items": items,
        }


def initialize_database(settings: Settings) -> None:
    settings = settings.validated()
    with connect(settings) as conn:
        _ensure_migration_ledger(conn)
        meta = dict(conn.execute("SELECT key, value FROM app_meta").fetchall())
        if meta:
            for key in ("environment_kind", "environment_id"):
                if meta.get(key) is not None and meta.get(key) != getattr(settings, key):
                    raise RuntimeError(f"Database environment mismatch: {key}")
        _apply_migrations(conn)
        expected = {
            "schema_version": SCHEMA_VERSION,
            "environment_kind": settings.environment_kind,
            "environment_id": settings.environment_id,
            "seed_version": SEED_VERSION,
        }
        for key, value in expected.items():
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        _seed(conn, settings)
        _seed_profile_config_versions(conn)


def _ensure_p2d1_schema(conn: sqlite3.Connection) -> None:
    """Idempotent in-place upgrade for databases created before P2-D-1."""
    trace_columns = {row["name"] for row in conn.execute("PRAGMA table_info(traces)")}
    for accidental_name in ("retention_days", "content_expires_at", "content_state", "purged_at"):
        if accidental_name in trace_columns:
            conn.execute(f"ALTER TABLE traces DROP COLUMN {accidental_name}")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(proposals)")}
    additions = {
        "retention_days": "INTEGER NOT NULL DEFAULT 7",
        "content_expires_at": "INTEGER",
        "content_state": "TEXT NOT NULL DEFAULT 'available'",
        "purged_at": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {name} {definition}")
    conn.execute(
        "UPDATE proposals SET retention_days=7 WHERE retention_days IS NULL OR retention_days NOT IN (1, 7)"
    )
    conn.execute(
        "UPDATE proposals SET content_expires_at=? WHERE content_expires_at IS NULL",
        (int(time.time()) + 7 * 86400,),
    )
    conn.execute(
        "UPDATE proposals SET content_state='available' WHERE content_state IS NULL OR content_state=''"
    )


def _seed(conn: sqlite3.Connection, settings: Settings) -> None:
    new_profiles: set[str] = set()
    for item in PROFILE_SEEDS:
        settings_json = json.dumps(item["settings"], ensure_ascii=False, sort_keys=True)
        if not conn.execute("SELECT 1 FROM profiles WHERE profile_id=?", (item["profile_id"],)).fetchone():
            new_profiles.add(item["profile_id"])
        conn.execute(
            """INSERT INTO profiles
               (profile_id, version, display_name, scope_label, color, policy_version, settings_json, source_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(profile_id) DO NOTHING""",
            (
                item["profile_id"], item["version"], item["display_name"], item["scope_label"],
                item["color"], item["policy_version"], settings_json, canonical_hash(item),
            ),
        )
    for equipment_id, display_name, status, observed_at, data_version in EQUIPMENT_SEEDS:
        payload = [equipment_id, display_name, status, observed_at, data_version]
        conn.execute(
            """INSERT OR IGNORE INTO equipment
               (equipment_id, display_name, status, observed_at, data_version, environment_id, source_kind, source_sha256)
               VALUES (?, ?, ?, ?, ?, ?, 'synthetic_seed', ?)""",
            (*payload, settings.environment_id, canonical_hash(payload)),
        )
    for item in PROFILE_SEEDS:
        if item["profile_id"] not in new_profiles:
            continue
        for equipment_id in item["equipment"]:
            conn.execute(
                "INSERT OR IGNORE INTO profile_equipment(profile_id, equipment_id) VALUES (?, ?)",
                (item["profile_id"], equipment_id),
            )
    for record_id, equipment_id, category, summary, status, started_at, completed_at, part_ids in HISTORY_SEEDS:
        payload = [record_id, equipment_id, category, summary, status, started_at, completed_at, part_ids]
        conn.execute(
            """INSERT OR IGNORE INTO maintenance_history
               (record_id, equipment_id, category, summary, status, started_at, completed_at,
                part_ids_json, data_version, environment_id, source_kind, source_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'history-seed-v1', ?, 'synthetic_seed', ?)""",
            (record_id, equipment_id, category, summary, status, started_at, completed_at,
             json.dumps(part_ids), settings.environment_id, canonical_hash(payload)),
        )
    for part_id, display_name, quantity, unit in PART_SEEDS:
        payload = [part_id, display_name, quantity, unit]
        conn.execute(
            """INSERT OR IGNORE INTO parts
               (part_id, display_name, stock_quantity, unit, data_version, environment_id, source_kind, source_sha256)
               VALUES (?, ?, ?, ?, 'parts-seed-v1', ?, 'synthetic_seed', ?)""",
            (part_id, display_name, quantity, unit, settings.environment_id, canonical_hash(payload)),
        )
    conn.executemany(
        "INSERT OR IGNORE INTO part_compatibility(part_id, equipment_id, basis) VALUES (?, ?, ?)",
        COMPATIBILITY_SEEDS,
    )


def _seed_profile_config_versions(conn: sqlite3.Connection) -> None:
    now = int(time.time())
    for row in conn.execute("SELECT * FROM profiles ORDER BY profile_id").fetchall():
        profile_settings = json.loads(row["settings_json"])
        if "retention_default_days" not in profile_settings:
            profile_settings["retention_default_days"] = 7
            conn.execute(
                "UPDATE profiles SET settings_json=? WHERE profile_id=?",
                (json.dumps(profile_settings, ensure_ascii=False, sort_keys=True), row["profile_id"]),
            )
        if conn.execute(
            "SELECT 1 FROM profile_config_versions WHERE profile_id=? LIMIT 1",
            (row["profile_id"],),
        ).fetchone():
            continue
        equipment_ids = [
            item["equipment_id"]
            for item in conn.execute(
                "SELECT equipment_id FROM profile_equipment WHERE profile_id=? ORDER BY equipment_id",
                (row["profile_id"],),
            ).fetchall()
        ]
        snapshot = {
            "profile_id": row["profile_id"],
            "display_name": row["display_name"],
            "scope_label": row["scope_label"],
            "color": row["color"],
            "settings": profile_settings,
            "equipment_ids": equipment_ids,
        }
        conn.execute(
            """INSERT INTO profile_config_versions
               (profile_id, revision, version, policy_version, status, snapshot_json,
                snapshot_sha256, created_by, derived_from_version, expires_at, created_at, updated_at)
               VALUES (?, 1, ?, ?, 'active', ?, ?, 'system-seed', NULL, NULL, ?, ?)""",
            (
                row["profile_id"],
                row["version"],
                row["policy_version"],
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                canonical_hash(snapshot),
                now,
                now,
            ),
        )


def append_trace(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    trace_id: str,
    event_type: str,
    status: str,
    tool_name: str | None,
    actor_id: str | None,
    profile_id: str | None,
    summary: dict[str, Any],
    evidence_kind: str = "measured_local",
) -> None:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS seq FROM traces WHERE trace_id=?",
        (trace_id,),
    ).fetchone()
    conn.execute(
        """INSERT INTO traces
           (trace_id, sequence, event_type, status, tool_name, actor_id, profile_id,
            summary_json, environment_id, evidence_kind, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trace_id, row["seq"], event_type, status, tool_name, actor_id, profile_id,
            json.dumps(summary, ensure_ascii=False, sort_keys=True), settings.environment_id,
            evidence_kind, int(time.time()),
        ),
    )


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]

