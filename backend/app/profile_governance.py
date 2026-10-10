from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from .config import Settings
from .db import append_trace, connect
from .errors import AppError
from .security import canonical_hash
from .services import Actor


SETTINGS_KEYS = {
    "approval_count",
    "terminology",
    "read_tools",
    "write_tool",
    "maintenance_window_required",
    "risk_summary_required",
    "retention_default_days",
}


def _require_admin(actor: Actor) -> None:
    if "admin" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有管理者可以建立或套用設定版本", status_code=403)


def _row(conn, profile_id: str, revision: int):
    return conn.execute(
        "SELECT * FROM profile_config_versions WHERE profile_id=? AND revision=?",
        (profile_id, revision),
    ).fetchone()


def _active_row(conn, profile_id: str):
    return conn.execute(
        "SELECT * FROM profile_config_versions WHERE profile_id=? AND status='active'",
        (profile_id,),
    ).fetchone()


def _normalize_snapshot(conn, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"profile_id", "display_name", "scope_label", "color", "settings", "equipment_ids"}
    unknown = set(payload) - allowed
    if unknown:
        raise AppError("INVALID_ARGUMENT", f"設定包含未知欄位：{', '.join(sorted(unknown))}")
    if payload.get("profile_id", profile_id) != profile_id:
        raise AppError("INVALID_ARGUMENT", "Profile 識別與路徑不一致")
    display_name = str(payload.get("display_name", "")).strip()
    scope_label = str(payload.get("scope_label", "")).strip()
    color = str(payload.get("color", "")).strip().lower()
    if not 3 <= len(display_name) <= 40:
        raise AppError("INVALID_ARGUMENT", "顯示名稱需為 3–40 個字元")
    if not 2 <= len(scope_label) <= 30:
        raise AppError("INVALID_ARGUMENT", "範圍標籤需為 2–30 個字元")
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        raise AppError("INVALID_ARGUMENT", "品牌色必須是六位十六進位色碼")

    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict) or set(raw_settings) - SETTINGS_KEYS:
        raise AppError("INVALID_ARGUMENT", "設定欄位不在允許清單")
    terminology = str(raw_settings.get("terminology", "")).strip()
    if not 2 <= len(terminology) <= 20:
        raise AppError("INVALID_ARGUMENT", "業務術語需為 2–20 個字元")
    approval_count = raw_settings.get("approval_count")
    if type(approval_count) is not int or approval_count not in {1, 2}:
        raise AppError("INVALID_ARGUMENT", "核准人數只能是 1 或 2")
    if raw_settings.get("read_tools") != 3 or raw_settings.get("write_tool") != "create_maintenance_order":
        raise AppError("CONFIG_SAFETY_FLOOR", "工具白名單屬安全底線，不能由設定草稿改寫", status_code=409)
    for key in ("maintenance_window_required", "risk_summary_required"):
        if type(raw_settings.get(key)) is not bool:
            raise AppError("INVALID_ARGUMENT", f"{key} 必須是布林值")
    retention_default_days = raw_settings.get("retention_default_days", 7)
    if type(retention_default_days) is not int or retention_default_days not in {1, 7}:
        raise AppError("INVALID_ARGUMENT", "預設保存期限只能是 1 日或 7 日")

    equipment_ids = payload.get("equipment_ids")
    if not isinstance(equipment_ids, list) or not equipment_ids:
        raise AppError("INVALID_ARGUMENT", "設備範圍不可為空")
    normalized_equipment = sorted({str(item).strip() for item in equipment_ids})
    known = {row["equipment_id"] for row in conn.execute("SELECT equipment_id FROM equipment")}
    if not set(normalized_equipment).issubset(known):
        raise AppError("INVALID_ARGUMENT", "設備範圍包含未知設備")

    return {
        "profile_id": profile_id,
        "display_name": display_name,
        "scope_label": scope_label,
        "color": color,
        "settings": {
            "approval_count": approval_count,
            "terminology": terminology,
            "read_tools": 3,
            "write_tool": "create_maintenance_order",
            "maintenance_window_required": raw_settings["maintenance_window_required"],
            "risk_summary_required": raw_settings["risk_summary_required"],
            "retention_default_days": retention_default_days,
        },
        "equipment_ids": normalized_equipment,
    }


def _diff(active: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ["display_name", "scope_label", "color", "equipment_ids"]
    output = []
    for field in fields:
        if active.get(field) != candidate.get(field):
            output.append({"field": field, "before": active.get(field), "after": candidate.get(field)})
    for field in sorted(SETTINGS_KEYS):
        before = active.get("settings", {}).get(field, 7 if field == "retention_default_days" else None)
        after = candidate.get("settings", {}).get(field)
        if before != after:
            output.append({"field": f"settings.{field}", "before": before, "after": after})
    return output


def _public(conn, row) -> dict[str, Any]:
    snapshot = json.loads(row["snapshot_json"])
    approvals = [
        dict(item)
        for item in conn.execute(
            """SELECT a.approval_id, a.reviewer_id, u.username AS reviewer_name,
                      a.decision, a.reason, a.created_at
               FROM profile_config_approvals a JOIN users u ON u.user_id=a.reviewer_id
               WHERE a.profile_id=? AND a.revision=? ORDER BY a.created_at""",
            (row["profile_id"], row["revision"]),
        ).fetchall()
    ]
    active = _active_row(conn, row["profile_id"])
    active_snapshot = json.loads(active["snapshot_json"]) if active else snapshot
    return {
        "profile_id": row["profile_id"],
        "revision": row["revision"],
        "version": row["version"],
        "policy_version": row["policy_version"],
        "status": row["status"],
        "snapshot": snapshot,
        "snapshot_sha256": row["snapshot_sha256"],
        "created_by": row["created_by"],
        "derived_from_version": row["derived_from_version"],
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "diff": _diff(active_snapshot, snapshot),
        "approvals": approvals,
    }


def list_profile_versions(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    if not {"admin", "reviewer"}.intersection(actor.roles):
        raise AppError("FORBIDDEN_ROLE", "目前角色不能查看設定版本", status_code=403)
    with connect(settings) as conn:
        if "admin" in actor.roles:
            rows = conn.execute(
                "SELECT * FROM profile_config_versions ORDER BY updated_at DESC, profile_id, revision DESC"
            ).fetchall()
        elif actor.profile_ids:
            placeholders = ",".join("?" for _ in actor.profile_ids)
            rows = conn.execute(
                f"SELECT * FROM profile_config_versions WHERE profile_id IN ({placeholders}) "
                "ORDER BY updated_at DESC, profile_id, revision DESC",
                actor.profile_ids,
            ).fetchall()
        else:
            rows = []
        return [_public(conn, row) for row in rows]


def create_profile_draft(
    settings: Settings,
    actor: Actor,
    profile_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _require_admin(actor)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = _active_row(conn, profile_id)
        if not active:
            raise AppError("PROFILE_NOT_FOUND", "找不到啟用中的 Profile", status_code=404)
        if conn.execute(
            "SELECT 1 FROM profile_config_versions WHERE profile_id=? AND status IN ('draft','validated','previewed','submitted','approved')",
            (profile_id,),
        ).fetchone():
            raise AppError("CONFIG_DRAFT_EXISTS", "此 Profile 已有進行中的設定版本", status_code=409)
        snapshot = _normalize_snapshot(conn, profile_id, payload)
        revision = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 AS revision FROM profile_config_versions WHERE profile_id=?",
            (profile_id,),
        ).fetchone()["revision"]
        version = f"1.0.{revision - 1}"
        policy_version = f"{profile_id}-policy-r{revision}"
        now = int(time.time())
        conn.execute(
            """INSERT INTO profile_config_versions
               (profile_id, revision, version, policy_version, status, snapshot_json,
                snapshot_sha256, created_by, derived_from_version, expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, NULL, ?, ?)""",
            (
                profile_id,
                revision,
                version,
                policy_version,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                canonical_hash(snapshot),
                actor.user_id,
                active["version"],
                now,
                now,
            ),
        )
        return _public(conn, _row(conn, profile_id, revision))


def validate_profile_draft(settings: Settings, actor: Actor, profile_id: str, revision: int) -> dict[str, Any]:
    _require_admin(actor)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, profile_id, revision)
        if not row or row["status"] not in {"draft", "validated"}:
            raise AppError("INVALID_TRANSITION", "只有草稿可以執行設定驗證", status_code=409)
        snapshot = _normalize_snapshot(conn, profile_id, json.loads(row["snapshot_json"]))
        if canonical_hash(snapshot) != row["snapshot_sha256"]:
            raise AppError("CONFIG_SNAPSHOT_CONFLICT", "設定快照雜湊不一致", status_code=409)
        conn.execute(
            "UPDATE profile_config_versions SET status='validated', updated_at=? WHERE profile_id=? AND revision=?",
            (int(time.time()), profile_id, revision),
        )
        return _public(conn, _row(conn, profile_id, revision))


def preview_profile_draft(settings: Settings, actor: Actor, profile_id: str, revision: int) -> dict[str, Any]:
    _require_admin(actor)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, profile_id, revision)
        if not row or row["status"] not in {"validated", "previewed"}:
            raise AppError("INVALID_TRANSITION", "設定草稿必須先通過驗證", status_code=409)
        conn.execute(
            "UPDATE profile_config_versions SET status='previewed', updated_at=? WHERE profile_id=? AND revision=?",
            (int(time.time()), profile_id, revision),
        )
        return _public(conn, _row(conn, profile_id, revision))


def submit_profile_draft(settings: Settings, actor: Actor, profile_id: str, revision: int) -> dict[str, Any]:
    _require_admin(actor)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, profile_id, revision)
        if not row or row["status"] != "previewed":
            raise AppError("INVALID_TRANSITION", "設定草稿必須先完成差異預覽", status_code=409)
        now = int(time.time())
        conn.execute(
            """UPDATE profile_config_versions SET status='submitted', expires_at=?, updated_at=?
               WHERE profile_id=? AND revision=?""",
            (now + 24 * 60 * 60, now, profile_id, revision),
        )
        return _public(conn, _row(conn, profile_id, revision))


def cancel_profile_draft(settings: Settings, actor: Actor, profile_id: str, revision: int) -> dict[str, Any]:
    _require_admin(actor)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, profile_id, revision)
        if not row or row["status"] not in {"draft", "validated", "previewed", "submitted"}:
            raise AppError("INVALID_TRANSITION", "此設定版本目前不能取消", status_code=409)
        conn.execute(
            "UPDATE profile_config_versions SET status='cancelled', updated_at=? WHERE profile_id=? AND revision=?",
            (int(time.time()), profile_id, revision),
        )
        return _public(conn, _row(conn, profile_id, revision))


def review_profile_draft(
    settings: Settings,
    actor: Actor,
    profile_id: str,
    revision: int,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    if "reviewer" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有 reviewer 可以核准設定版本", status_code=403)
    if profile_id not in actor.profile_ids:
        raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到設定版本或不在審核範圍", status_code=404)
    if decision not in {"approve", "reject"}:
        raise AppError("INVALID_ARGUMENT", "設定審核決定不正確")
    reason = reason.strip()
    if len(reason) < 8:
        raise AppError("INVALID_ARGUMENT", "設定審核理由至少 8 個字元")
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, profile_id, revision)
        if not row or row["status"] != "submitted":
            raise AppError("INVALID_TRANSITION", "此設定版本目前不能審核", status_code=409)
        if row["created_by"] == actor.user_id:
            raise AppError("SELF_REVIEW_FORBIDDEN", "設定提出者不得核准自己的版本", status_code=403)
        now = int(time.time())
        if row["expires_at"] is not None and row["expires_at"] <= now:
            conn.execute(
                "UPDATE profile_config_versions SET status='expired', updated_at=? WHERE profile_id=? AND revision=?",
                (now, profile_id, revision),
            )
            conn.commit()
            raise AppError("APPROVAL_STALE", "設定審核期限已過", status_code=409)
        conn.execute(
            """INSERT INTO profile_config_approvals
               (approval_id, profile_id, revision, reviewer_id, decision, reason, snapshot_sha256, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"PCA-{uuid.uuid4().hex[:12].upper()}",
                profile_id,
                revision,
                actor.user_id,
                decision,
                reason,
                row["snapshot_sha256"],
                now,
            ),
        )
        conn.execute(
            "UPDATE profile_config_versions SET status=?, updated_at=? WHERE profile_id=? AND revision=?",
            ("approved" if decision == "approve" else "rejected", now, profile_id, revision),
        )
        return _public(conn, _row(conn, profile_id, revision))


def apply_profile_version(settings: Settings, actor: Actor, profile_id: str, revision: int) -> dict[str, Any]:
    _require_admin(actor)
    trace_id = f"TRC-{uuid.uuid4().hex[:16].upper()}"
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn, profile_id, revision)
        active = _active_row(conn, profile_id)
        if not row or row["status"] != "approved" or not active:
            raise AppError("INVALID_TRANSITION", "只有已獨立核准的設定版本可以套用", status_code=409)
        if row["derived_from_version"] != active["version"]:
            raise AppError("CONFIG_BASE_CHANGED", "啟用版本已改變，必須重新建立草稿", status_code=409)
        snapshot = json.loads(row["snapshot_json"])
        now = int(time.time())
        conn.execute(
            "UPDATE profile_config_versions SET status='superseded', updated_at=? WHERE profile_id=? AND status='active'",
            (now, profile_id),
        )
        conn.execute(
            "UPDATE profile_config_versions SET status='active', updated_at=? WHERE profile_id=? AND revision=?",
            (now, profile_id, revision),
        )
        conn.execute(
            """UPDATE profiles SET version=?, display_name=?, scope_label=?, color=?, policy_version=?,
               settings_json=?, source_sha256=? WHERE profile_id=?""",
            (
                row["version"],
                snapshot["display_name"],
                snapshot["scope_label"],
                snapshot["color"],
                row["policy_version"],
                json.dumps(snapshot["settings"], ensure_ascii=False, sort_keys=True),
                row["snapshot_sha256"],
                profile_id,
            ),
        )
        conn.execute("DELETE FROM profile_equipment WHERE profile_id=?", (profile_id,))
        conn.executemany(
            "INSERT INTO profile_equipment(profile_id, equipment_id) VALUES (?, ?)",
            [(profile_id, equipment_id) for equipment_id in snapshot["equipment_ids"]],
        )
        invalidated = conn.execute(
            """UPDATE proposals SET status='invalidated', updated_at=?
               WHERE profile_id=? AND profile_version<>?
               AND status IN ('draft','pending_review','partially_approved','approved')""",
            (now, profile_id, row["version"]),
        ).rowcount
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="profile.version_applied",
            status="success",
            tool_name=None,
            actor_id=actor.user_id,
            profile_id=profile_id,
            summary={
                "version": row["version"],
                "policy_version": row["policy_version"],
                "invalidated_proposal_count": invalidated,
            },
        )
        return _public(conn, _row(conn, profile_id, revision))


def create_rollback_draft(
    settings: Settings,
    actor: Actor,
    profile_id: str,
    target_revision: int,
) -> dict[str, Any]:
    _require_admin(actor)
    with connect(settings) as conn:
        target = _row(conn, profile_id, target_revision)
        if not target or target["status"] not in {"active", "superseded"}:
            raise AppError("INVALID_ARGUMENT", "只能從已啟用過的設定版本建立還原草稿")
        payload = json.loads(target["snapshot_json"])
    return create_profile_draft(settings, actor, profile_id, payload)
