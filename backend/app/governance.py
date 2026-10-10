from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .config import Settings
from .db import SCHEMA_VERSION, connect, migration_status
from .errors import AppError
from .security import canonical_hash, canonical_json
from .services import Actor


BACKUP_FORMAT = "mcp-governance-backup-v1"
BACKUP_CONFIRMATION = "建立去內容備份"
RESTORE_CONFIRMATION = "建立唯讀隔離還原"

INCLUDED = (
    "schema 與 migration metadata",
    "Profile 設定白名單快照與版本關係",
    "合成種子版本與來源雜湊",
    "去識別帳號角色／範圍統計",
    "提案、核准、執行、工單的去內容關係與狀態",
    "不含 payload 的 Trace 統計",
)

EXCLUDED = (
    "帳號名稱、密碼雜湊與 salt",
    "Session、CSRF 與 auth context",
    "原始工具輸入、輸出與 Trace summary",
    "提案參數、問題摘要、核准理由與工單內文",
    "idempotency key、outbox payload 與可執行核准權威",
    "API key、Token、secret、外部 URL 與任意檔案路徑",
)


def _require_admin(actor: Actor) -> None:
    if "admin" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有管理者可以操作遷移、備份與隔離還原", status_code=403)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_content_sha256(settings: Settings) -> str:
    """Hash logical SQLite content; file bytes may change during WAL checkpoints."""
    with connect(settings) as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        content: dict[str, Any] = {}
        for table in tables:
            columns = [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            quoted = ", ".join(f'"{column}"' for column in columns)
            rows = conn.execute(f'SELECT {quoted} FROM "{table}" ORDER BY {quoted}').fetchall()
            content[table] = [dict(row) for row in rows]
    return canonical_hash(content)


def _safe_ref(backup_id: str, kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    return f"{kind}-{canonical_hash([backup_id, kind, value])[:16]}"


def _backup_directory(settings: Settings) -> Path:
    return settings.db_path.parent / "backups"


def _restore_bucket(settings: Settings) -> Path:
    base = settings.db_path.parent if settings.environment_kind == "automated_test" else settings.root / "state"
    return base / "restore_isolation" / settings.environment_id


def migration_overview(settings: Settings, actor: Actor) -> dict[str, Any]:
    _require_admin(actor)
    return migration_status(settings)


def backup_preview(settings: Settings, actor: Actor) -> dict[str, Any]:
    _require_admin(actor)
    table_names = (
        "profiles",
        "profile_config_versions",
        "users",
        "proposals",
        "approvals",
        "executions",
        "maintenance_orders",
        "traces",
    )
    with connect(settings) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in table_names
        }
        roles: Counter[str] = Counter()
        profile_scope_counts: Counter[str] = Counter()
        for row in conn.execute("SELECT roles_json, profile_ids_json FROM users"):
            roles.update(json.loads(row["roles_json"]))
            profile_scope_counts.update(json.loads(row["profile_ids_json"]))
    return {
        "format": BACKUP_FORMAT,
        "source_environment_kind": settings.environment_kind,
        "source_environment_id": settings.environment_id,
        "schema_version": SCHEMA_VERSION,
        "counts": counts,
        "identity_summary": {
            "user_count": counts["users"],
            "role_counts": dict(sorted(roles.items())),
            "profile_scope_counts": dict(sorted(profile_scope_counts.items())),
        },
        "included": list(INCLUDED),
        "excluded": list(EXCLUDED),
        "confirmation_phrase": BACKUP_CONFIRMATION,
        "warning": "此產物是去內容治理備份，不是可直接覆寫正式資料庫的災難復原檔。",
    }


def _backup_payload(conn: sqlite3.Connection, settings: Settings, backup_id: str) -> dict[str, Any]:
    profiles = []
    for row in conn.execute(
        """SELECT profile_id, revision, version, policy_version, status, snapshot_json,
                  snapshot_sha256, derived_from_version, created_at, updated_at
           FROM profile_config_versions ORDER BY profile_id, revision"""
    ):
        profiles.append(
            {
                "profile_id": row["profile_id"],
                "revision": row["revision"],
                "version": row["version"],
                "policy_version": row["policy_version"],
                "source_status": row["status"],
                "snapshot": json.loads(row["snapshot_json"]),
                "snapshot_sha256": row["snapshot_sha256"],
                "derived_from_version": row["derived_from_version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    users = conn.execute(
        "SELECT user_id, roles_json, device_scopes_json, profile_ids_json, active FROM users"
    ).fetchall()
    role_counts: Counter[str] = Counter()
    device_scope_counts: Counter[str] = Counter()
    profile_scope_counts: Counter[str] = Counter()
    active_count = 0
    for row in users:
        role_counts.update(json.loads(row["roles_json"]))
        device_scope_counts.update(json.loads(row["device_scopes_json"]))
        profile_scope_counts.update(json.loads(row["profile_ids_json"]))
        active_count += int(bool(row["active"]))

    proposals = []
    for row in conn.execute(
        """SELECT proposal_id, proposal_version, profile_id, profile_version, policy_version,
                  tool_name, equipment_id, status, required_approvals, proposer_id,
                  environment_id, source_kind, evidence_kind, retention_days,
                  content_state, created_at, updated_at
           FROM proposals ORDER BY created_at, proposal_id, proposal_version"""
    ):
        proposals.append(
            {
                "proposal_ref": _safe_ref(backup_id, "proposal", row["proposal_id"]),
                "proposal_version": row["proposal_version"],
                "profile_id": row["profile_id"],
                "profile_version": row["profile_version"],
                "policy_version": row["policy_version"],
                "tool_name": row["tool_name"],
                "equipment_id": row["equipment_id"],
                "source_status": row["status"],
                "required_approvals": row["required_approvals"],
                "proposer_ref": _safe_ref(backup_id, "actor", row["proposer_id"]),
                "environment_kind": settings.environment_kind,
                "source_kind": row["source_kind"],
                "evidence_kind": row["evidence_kind"],
                "retention_days": row["retention_days"],
                "content_state": row["content_state"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    approval_counts = []
    for row in conn.execute(
        """SELECT proposal_id, proposal_version, decision, COUNT(*) AS n,
                  MIN(created_at) AS first_at, MAX(created_at) AS last_at
           FROM approvals GROUP BY proposal_id, proposal_version, decision
           ORDER BY proposal_id, proposal_version, decision"""
    ):
        approval_counts.append(
            {
                "proposal_ref": _safe_ref(backup_id, "proposal", row["proposal_id"]),
                "proposal_version": row["proposal_version"],
                "decision": row["decision"],
                "count": row["n"],
                "first_at": row["first_at"],
                "last_at": row["last_at"],
            }
        )

    executions = []
    for row in conn.execute(
        """SELECT execution_id, proposal_id, proposal_version, operator_id, tool_name,
                  status, order_id, created_at, updated_at
           FROM executions ORDER BY created_at, execution_id"""
    ):
        executions.append(
            {
                "execution_ref": _safe_ref(backup_id, "execution", row["execution_id"]),
                "proposal_ref": _safe_ref(backup_id, "proposal", row["proposal_id"]),
                "proposal_version": row["proposal_version"],
                "operator_ref": _safe_ref(backup_id, "actor", row["operator_id"]),
                "tool_name": row["tool_name"],
                "source_status": row["status"],
                "order_ref": _safe_ref(backup_id, "order", row["order_id"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    orders = []
    for row in conn.execute(
        """SELECT order_id, order_status, order_version, proposal_id, proposal_version,
                  execution_id, equipment_id, profile_id, source_kind, evidence_kind, created_at
           FROM maintenance_orders ORDER BY created_at, order_id"""
    ):
        orders.append(
            {
                "order_ref": _safe_ref(backup_id, "order", row["order_id"]),
                "source_status": row["order_status"],
                "order_version": row["order_version"],
                "proposal_ref": _safe_ref(backup_id, "proposal", row["proposal_id"]),
                "proposal_version": row["proposal_version"],
                "execution_ref": _safe_ref(backup_id, "execution", row["execution_id"]),
                "equipment_id": row["equipment_id"],
                "profile_id": row["profile_id"],
                "source_kind": row["source_kind"],
                "evidence_kind": row["evidence_kind"],
                "created_at": row["created_at"],
            }
        )

    trace_summary = [
        dict(row)
        for row in conn.execute(
            """SELECT event_type, status, COALESCE(tool_name, '') AS tool_name, COUNT(*) AS count,
                      MIN(created_at) AS first_at, MAX(created_at) AS last_at
               FROM traces GROUP BY event_type, status, COALESCE(tool_name, '')
               ORDER BY event_type, status, tool_name"""
        )
    ]
    migrations = [
        dict(row)
        for row in conn.execute(
            """SELECT migration_id, checksum_sha256, from_schema, to_schema, status,
                      started_at, finished_at, error_code
               FROM schema_migrations ORDER BY migration_id"""
        )
    ]
    meta = dict(conn.execute("SELECT key, value FROM app_meta").fetchall())
    return {
        "schema": {"version": SCHEMA_VERSION, "migrations": migrations},
        "seed_manifest": {
            "seed_version": meta.get("seed_version"),
            "profile_source_hashes": [
                dict(row)
                for row in conn.execute(
                    "SELECT profile_id, source_sha256 FROM profiles ORDER BY profile_id"
                )
            ],
        },
        "identity_summary": {
            "user_count": len(users),
            "active_count": active_count,
            "role_counts": dict(sorted(role_counts.items())),
            "device_scope_counts": dict(sorted(device_scope_counts.items())),
            "profile_scope_counts": dict(sorted(profile_scope_counts.items())),
        },
        "profile_versions": profiles,
        "business_records": {
            "proposals": proposals,
            "approval_counts": approval_counts,
            "executions": executions,
            "orders": orders,
            "trace_summary": trace_summary,
        },
    }


def create_backup(settings: Settings, actor: Actor, confirmation: str) -> dict[str, Any]:
    _require_admin(actor)
    if confirmation.strip() != BACKUP_CONFIRMATION:
        raise AppError("CONFIRMATION_REQUIRED", f"請輸入「{BACKUP_CONFIRMATION}」", status_code=409)
    backup_id = f"BKP-{uuid.uuid4().hex[:12].upper()}"
    created_at = int(time.time())
    preview = backup_preview(settings, actor)
    with connect(settings) as conn:
        payload = _backup_payload(conn, settings, backup_id)
    payload_sha256 = canonical_hash(payload)
    manifest = {
        "format": BACKUP_FORMAT,
        "backup_id": backup_id,
        "created_at": created_at,
        "source_environment_kind": settings.environment_kind,
        "source_environment_id": settings.environment_id,
        "schema_version": SCHEMA_VERSION,
        "payload_sha256": payload_sha256,
        "counts": preview["counts"],
        "included": list(INCLUDED),
        "excluded": list(EXCLUDED),
        "authority_included": False,
    }
    envelope = {"manifest": manifest, "payload": payload}
    encoded = canonical_json(envelope).encode("utf-8")
    backup_dir = _backup_directory(settings)
    backup_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{backup_id.lower()}.json"
    target = backup_dir / file_name
    if target.exists():
        raise AppError("BACKUP_EXISTS", "備份識別碼已存在", status_code=409)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=backup_dir, prefix=".partial-", suffix=".json") as handle:
            temporary_name = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    file_sha256 = _file_sha256(target)
    with connect(settings) as conn:
        conn.execute(
            """INSERT INTO governance_backups
               (backup_id, status, file_name, sha256, byte_size, manifest_json, created_by, created_at)
               VALUES (?, 'verified', ?, ?, ?, ?, ?, ?)""",
            (
                backup_id,
                file_name,
                file_sha256,
                len(encoded),
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                actor.user_id,
                created_at,
            ),
        )
    return _public_backup(manifest, file_sha256, len(encoded))


def _public_backup(manifest: dict[str, Any], sha256: str, byte_size: int) -> dict[str, Any]:
    return {
        "backup_id": manifest["backup_id"],
        "status": "verified",
        "created_at": manifest["created_at"],
        "schema_version": manifest["schema_version"],
        "sha256": sha256,
        "byte_size": byte_size,
        "payload_sha256": manifest["payload_sha256"],
        "counts": manifest["counts"],
        "authority_included": False,
    }


def list_backups(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    _require_admin(actor)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM governance_backups ORDER BY created_at DESC, backup_id DESC").fetchall()
    return [
        _public_backup(json.loads(row["manifest_json"]), row["sha256"], row["byte_size"])
        for row in rows
    ]


def backup_path(settings: Settings, actor: Actor, backup_id: str) -> Path:
    _require_admin(actor)
    with connect(settings) as conn:
        row = conn.execute(
            "SELECT file_name, sha256 FROM governance_backups WHERE backup_id=? AND status='verified'",
            (backup_id,),
        ).fetchone()
    if not row:
        raise AppError("BACKUP_NOT_FOUND", "找不到已驗證備份", status_code=404)
    path = (_backup_directory(settings) / row["file_name"]).resolve()
    allowed = _backup_directory(settings).resolve()
    if path.parent != allowed or not path.is_file() or path.is_symlink():
        raise AppError("BACKUP_FILE_INVALID", "備份檔不存在或超出允許範圍", status_code=409)
    if _file_sha256(path) != row["sha256"]:
        raise AppError("BACKUP_HASH_MISMATCH", "備份檔雜湊不符，已拒絕使用", status_code=409)
    return path


def _read_verified_backup(settings: Settings, actor: Actor, backup_id: str) -> tuple[dict[str, Any], Path]:
    path = backup_path(settings, actor, backup_id)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError("BACKUP_FORMAT_INVALID", "備份格式無法讀取", status_code=409) from exc
    if set(envelope) != {"manifest", "payload"}:
        raise AppError("BACKUP_FORMAT_INVALID", "備份封裝欄位不正確", status_code=409)
    manifest = envelope["manifest"]
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("backup_id") != backup_id:
        raise AppError("BACKUP_FORMAT_INVALID", "備份格式或識別碼不相容", status_code=409)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise AppError("BACKUP_SCHEMA_UNSUPPORTED", "備份 schema 版本不受支援", status_code=409)
    if manifest.get("authority_included") is not False:
        raise AppError("BACKUP_AUTHORITY_UNSAFE", "備份包含不可還原的執行權威", status_code=409)
    if canonical_hash(envelope["payload"]) != manifest.get("payload_sha256"):
        raise AppError("BACKUP_PAYLOAD_HASH_MISMATCH", "備份內容雜湊不符", status_code=409)
    return envelope, path


def restore_backup(settings: Settings, actor: Actor, backup_id: str, confirmation: str) -> dict[str, Any]:
    _require_admin(actor)
    if confirmation.strip() != RESTORE_CONFIRMATION:
        raise AppError("CONFIRMATION_REQUIRED", f"請輸入「{RESTORE_CONFIRMATION}」", status_code=409)
    envelope, _ = _read_verified_backup(settings, actor, backup_id)
    source_before = database_content_sha256(settings)
    restore_id = f"RST-{uuid.uuid4().hex[:12].upper()}"
    restore_root = _restore_bucket(settings) / restore_id.lower()
    restore_root.mkdir(parents=True, exist_ok=False)
    target_db = restore_root / "app.db"
    receipt_path = restore_root / "restore-receipt.json"
    payload = envelope["payload"]
    try:
        conn = sqlite3.connect(target_db)
        try:
            conn.executescript(
                """
                CREATE TABLE restore_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE restored_profile_candidates (
                  profile_id TEXT NOT NULL,
                  source_version TEXT NOT NULL,
                  source_policy_version TEXT NOT NULL,
                  snapshot_json TEXT NOT NULL,
                  snapshot_sha256 TEXT NOT NULL,
                  restore_state TEXT NOT NULL,
                  PRIMARY KEY(profile_id, source_version)
                );
                CREATE TABLE restored_business_records (
                  record_kind TEXT NOT NULL,
                  record_ref TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  restore_state TEXT NOT NULL,
                  PRIMARY KEY(record_kind, record_ref)
                );
                """
            )
            meta = {
                "environment_kind": "restore_isolation",
                "source_backup_id": backup_id,
                "schema_version": SCHEMA_VERSION,
                "read_only": "true",
                "sessions": "0",
                "auth_contexts": "0",
                "active_approvals": "0",
                "auto_replay": "0",
            }
            conn.executemany("INSERT INTO restore_meta(key, value) VALUES (?, ?)", meta.items())
            for version in payload["profile_versions"]:
                if version["source_status"] != "active":
                    continue
                conn.execute(
                    """INSERT INTO restored_profile_candidates
                       (profile_id, source_version, source_policy_version, snapshot_json,
                        snapshot_sha256, restore_state)
                       VALUES (?, ?, ?, ?, ?, 'pending_validation_readonly')""",
                    (
                        version["profile_id"],
                        version["version"],
                        version["policy_version"],
                        json.dumps(version["snapshot"], ensure_ascii=False, sort_keys=True),
                        version["snapshot_sha256"],
                    ),
                )
            record_count = 0
            for kind, records in payload["business_records"].items():
                if kind == "trace_summary":
                    for index, record in enumerate(records, start=1):
                        reference = f"trace-summary-{index:04d}"
                        conn.execute(
                            "INSERT INTO restored_business_records VALUES (?, ?, ?, 'restored_readonly')",
                            (kind, reference, json.dumps(record, ensure_ascii=False, sort_keys=True)),
                        )
                        record_count += 1
                    continue
                for index, record in enumerate(records, start=1):
                    reference = (
                        record.get("proposal_ref")
                        or record.get("execution_ref")
                        or record.get("order_ref")
                        or f"{kind}-{index:04d}"
                    )
                    if kind == "proposals":
                        reference = f"{reference}-{record['proposal_version']}"
                    if kind == "approval_counts":
                        reference = f"{reference}-{record['proposal_version']}-{record['decision']}"
                    conn.execute(
                        "INSERT INTO restored_business_records VALUES (?, ?, ?, 'restored_readonly')",
                        (kind, reference, json.dumps(record, ensure_ascii=False, sort_keys=True)),
                    )
                    record_count += 1
            conn.commit()
        finally:
            conn.close()
        os.chmod(target_db, 0o444)
        source_after = database_content_sha256(settings)
        receipt = {
            "restore_id": restore_id,
            "backup_id": backup_id,
            "created_at": int(time.time()),
            "target_environment_kind": "restore_isolation",
            "target_environment_id": f"restore_isolation-{canonical_hash(str(restore_root.resolve()))[:12]}",
            "target_relative_path": str(
                Path("restore_isolation") / settings.environment_id / restore_id.lower() / "app.db"
            ).replace("\\", "/"),
            "source_db_unchanged": source_before == source_after,
            "source_content_sha256": source_after,
            "read_only": True,
            "restored_profile_candidates": sum(
                1 for item in payload["profile_versions"] if item["source_status"] == "active"
            ),
            "restored_business_records": record_count,
            "sessions": 0,
            "auth_contexts": 0,
            "active_approvals": 0,
            "auto_replay": 0,
            "mcp_calls": 0,
        }
        receipt_path.write_text(
            canonical_json({"receipt": receipt, "receipt_sha256": canonical_hash(receipt)}),
            encoding="utf-8",
        )
        return receipt
    except Exception:
        for child in sorted(restore_root.glob("*"), reverse=True):
            try:
                os.chmod(child, 0o666)
                child.unlink()
            except OSError:
                pass
        try:
            restore_root.rmdir()
        except OSError:
            pass
        raise


def list_restores(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    _require_admin(actor)
    root = _restore_bucket(settings)
    if not root.exists():
        return []
    receipts = []
    for path in root.glob("*/restore-receipt.json"):
        if path.is_symlink() or path.parent.parent.resolve() != root.resolve():
            continue
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if set(envelope) != {"receipt", "receipt_sha256"}:
            continue
        receipt = envelope["receipt"]
        if canonical_hash(receipt) != envelope["receipt_sha256"]:
            continue
        if receipt.get("target_environment_kind") == "restore_isolation":
            receipts.append(receipt)
    return sorted(receipts, key=lambda item: (item["created_at"], item["restore_id"]), reverse=True)
