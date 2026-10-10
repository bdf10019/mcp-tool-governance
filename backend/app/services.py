from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .db import append_trace, connect, rows_to_dicts
from .errors import AppError
from .security import canonical_hash, hash_secret, new_token, password_hash, password_matches


READ_TOOLS = {
    "get_equipment_status",
    "list_maintenance_history",
    "check_parts_stock",
}
READ_ROLES = {"viewer", "operator", "reviewer"}
KNOWN_ROLES = {"viewer", "operator", "reviewer", "admin"}


@dataclass(frozen=True)
class Actor:
    user_id: str
    username: str
    roles: tuple[str, ...]
    device_scopes: tuple[str, ...]
    profile_ids: tuple[str, ...]
    session_epoch: int

    def public(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "roles": list(self.roles),
            "device_scopes": list(self.device_scopes),
            "profile_ids": list(self.profile_ids),
        }


def setup_status(settings: Settings) -> dict[str, bool]:
    with connect(settings) as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    return {"needs_setup": count == 0}


def create_initial_admin(settings: Settings, username: str, password: str) -> Actor:
    username = username.strip()
    if not (3 <= len(username) <= 40):
        raise AppError("INVALID_ARGUMENT", "帳號需為 3–40 個字元")
    if len(password) < 10:
        raise AppError("INVALID_ARGUMENT", "密碼至少需要 10 個字元")
    salt, digest = password_hash(password)
    user_id = f"USR-{uuid.uuid4().hex[:12].upper()}"
    now = int(time.time())
    scopes = ["EQ-PUMP-001", "EQ-FAN-002", "EQ-CONV-003", "EQ-CHILLER-004"]
    profiles = ["service-v1", "asset-v1"]
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise AppError("SETUP_COMPLETE", "管理者已建立", status_code=409)
        conn.execute(
            """INSERT INTO users
               (user_id, username, password_salt, password_hash, roles_json,
                device_scopes_json, profile_ids_json, active, session_epoch, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)""",
            (
                user_id, username, salt, digest, json.dumps(["admin", "viewer"]),
                json.dumps(scopes), json.dumps(profiles), now,
            ),
        )
    return Actor(user_id, username, ("admin", "viewer"), tuple(scopes), tuple(profiles), 1)


def authenticate(settings: Settings, username: str, password: str) -> Actor:
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not row or not row["active"] or not password_matches(password, row["password_salt"], row["password_hash"]):
        raise AppError("INVALID_CREDENTIALS", "帳號或密碼不正確", status_code=401)
    return _row_to_actor(row)


def _row_to_actor(row: Any) -> Actor:
    return Actor(
        user_id=row["user_id"],
        username=row["username"],
        roles=tuple(json.loads(row["roles_json"])),
        device_scopes=tuple(json.loads(row["device_scopes_json"])),
        profile_ids=tuple(json.loads(row["profile_ids_json"])),
        session_epoch=int(row["session_epoch"]),
    )


def list_users(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    if "admin" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有管理者可以查看本機帳號", status_code=403)
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT user_id, username, roles_json, device_scopes_json, profile_ids_json, active, session_epoch, created_at "
            "FROM users ORDER BY created_at, username"
        ).fetchall()
    return [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "roles": json.loads(row["roles_json"]),
            "device_scopes": json.loads(row["device_scopes_json"]),
            "profile_ids": json.loads(row["profile_ids_json"]),
            "active": bool(row["active"]),
            "session_epoch": row["session_epoch"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _require_admin(actor: Actor) -> None:
    if "admin" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有管理者可以管理本機帳號", status_code=403)


def _validated_access(
    conn: sqlite3.Connection,
    roles: list[str],
    device_scopes: list[str],
    profile_ids: list[str],
) -> tuple[list[str], list[str], list[str]]:
    normalized_roles = sorted(set(roles))
    normalized_scopes = sorted(set(device_scopes))
    normalized_profiles = sorted(set(profile_ids))
    if not normalized_roles or not set(normalized_roles).issubset(KNOWN_ROLES):
        raise AppError("INVALID_ARGUMENT", "角色不存在或不可為空")
    known_scopes = {row["equipment_id"] for row in conn.execute("SELECT equipment_id FROM equipment")}
    known_profiles = {row["profile_id"] for row in conn.execute("SELECT profile_id FROM profiles")}
    if not set(normalized_scopes).issubset(known_scopes):
        raise AppError("INVALID_ARGUMENT", "設備範圍包含未知設備")
    if not normalized_profiles or not set(normalized_profiles).issubset(known_profiles):
        raise AppError("INVALID_ARGUMENT", "工作設定包含未知項目或為空")
    return normalized_roles, normalized_scopes, normalized_profiles


def create_local_user(
    settings: Settings,
    actor: Actor,
    *,
    username: str,
    password: str,
    roles: list[str],
    device_scopes: list[str],
    profile_ids: list[str],
) -> dict[str, Any]:
    _require_admin(actor)
    username = username.strip()
    if not (3 <= len(username) <= 40) or len(password) < 10:
        raise AppError("INVALID_ARGUMENT", "帳號需 3–40 字，密碼至少 10 字")
    with connect(settings) as conn:
        normalized_roles, normalized_scopes, normalized_profiles = _validated_access(
            conn, roles, device_scopes, profile_ids
        )
        salt, digest = password_hash(password)
        user_id = f"USR-{uuid.uuid4().hex[:12].upper()}"
        try:
            conn.execute(
                """INSERT INTO users
                   (user_id, username, password_salt, password_hash, roles_json,
                    device_scopes_json, profile_ids_json, active, session_epoch, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)""",
                (
                    user_id,
                    username,
                    salt,
                    digest,
                    json.dumps(normalized_roles),
                    json.dumps(normalized_scopes),
                    json.dumps(normalized_profiles),
                    int(time.time()),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError("USERNAME_EXISTS", "此帳號名稱已存在", status_code=409) from exc
    return {
        "user_id": user_id,
        "username": username,
        "roles": normalized_roles,
        "device_scopes": normalized_scopes,
        "profile_ids": normalized_profiles,
        "active": True,
    }


def set_user_active(settings: Settings, actor: Actor, user_id: str, active: bool) -> dict[str, Any]:
    _require_admin(actor)
    if actor.user_id == user_id and not active:
        raise AppError("SELF_LOCKOUT_FORBIDDEN", "不能停用目前登入的管理者", status_code=409)
    now = int(time.time())
    trace_id = f"TRC-{uuid.uuid4().hex[:16].upper()}"
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not target:
            raise AppError("USER_NOT_FOUND", "找不到本機帳號", status_code=404)
        conn.execute(
            "UPDATE users SET active=?, session_epoch=session_epoch+1 WHERE user_id=?",
            (1 if active else 0, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="account.status_changed",
            status="success",
            tool_name=None,
            actor_id=actor.user_id,
            profile_id=None,
            summary={"target_user_id": user_id, "active": active, "sessions_revoked": True},
        )
    return next(item for item in list_users(settings, actor) if item["user_id"] == user_id)


def reset_user_password(settings: Settings, actor: Actor, user_id: str, password: str) -> dict[str, bool]:
    _require_admin(actor)
    if len(password) < 10:
        raise AppError("INVALID_ARGUMENT", "密碼至少需要 10 個字元")
    salt, digest = password_hash(password)
    trace_id = f"TRC-{uuid.uuid4().hex[:16].upper()}"
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            raise AppError("USER_NOT_FOUND", "找不到本機帳號", status_code=404)
        conn.execute(
            "UPDATE users SET password_salt=?, password_hash=?, session_epoch=session_epoch+1 WHERE user_id=?",
            (salt, digest, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="account.password_reset",
            status="success",
            tool_name=None,
            actor_id=actor.user_id,
            profile_id=None,
            summary={"target_user_id": user_id, "sessions_revoked": True},
        )
    return {"ok": True, "sessions_revoked": True}


def update_user_access(
    settings: Settings,
    actor: Actor,
    user_id: str,
    *,
    roles: list[str],
    device_scopes: list[str],
    profile_ids: list[str],
) -> dict[str, Any]:
    _require_admin(actor)
    trace_id = f"TRC-{uuid.uuid4().hex[:16].upper()}"
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not target:
            raise AppError("USER_NOT_FOUND", "找不到本機帳號", status_code=404)
        normalized_roles, normalized_scopes, normalized_profiles = _validated_access(
            conn, roles, device_scopes, profile_ids
        )
        if actor.user_id == user_id and "admin" not in normalized_roles:
            raise AppError("SELF_LOCKOUT_FORBIDDEN", "不能移除目前登入管理者的 admin 角色", status_code=409)
        conn.execute(
            """UPDATE users SET roles_json=?, device_scopes_json=?, profile_ids_json=?,
               session_epoch=session_epoch+1 WHERE user_id=?""",
            (
                json.dumps(normalized_roles),
                json.dumps(normalized_scopes),
                json.dumps(normalized_profiles),
                user_id,
            ),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="account.access_changed",
            status="success",
            tool_name=None,
            actor_id=actor.user_id,
            profile_id=None,
            summary={
                "target_user_id": user_id,
                "roles": normalized_roles,
                "device_scope_count": len(normalized_scopes),
                "profile_count": len(normalized_profiles),
                "sessions_revoked": True,
            },
        )
    return next(item for item in list_users(settings, actor) if item["user_id"] == user_id)


def create_session(settings: Settings, actor: Actor) -> tuple[str, str, int]:
    session_token = new_token()
    csrf_token = new_token(24)
    expires_at = int(time.time()) + settings.session_seconds
    with connect(settings) as conn:
        conn.execute(
            """INSERT INTO sessions(session_hash, user_id, csrf_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (hash_secret(session_token), actor.user_id, hash_secret(csrf_token), expires_at, int(time.time())),
        )
    return session_token, csrf_token, expires_at


def actor_from_session(settings: Settings, session_token: str | None) -> Actor:
    if not session_token:
        raise AppError("UNAUTHENTICATED", "請先登入", status_code=401)
    with connect(settings) as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.user_id=s.user_id
               WHERE s.session_hash=? AND s.expires_at>? AND u.active=1""",
            (hash_secret(session_token), int(time.time())),
        ).fetchone()
    if not row:
        raise AppError("SESSION_EXPIRED", "登入已過期，請重新登入", status_code=401, recoverable=True)
    return _row_to_actor(row)


def verify_csrf(settings: Settings, session_token: str | None, csrf_token: str | None) -> None:
    if not session_token or not csrf_token:
        raise AppError("CSRF_REQUIRED", "缺少操作驗證碼", status_code=403)
    with connect(settings) as conn:
        row = conn.execute(
            "SELECT csrf_hash FROM sessions WHERE session_hash=? AND expires_at>?",
            (hash_secret(session_token), int(time.time())),
        ).fetchone()
    if not row or row["csrf_hash"] != hash_secret(csrf_token):
        raise AppError("CSRF_INVALID", "操作驗證失敗，請重新整理或登入", status_code=403)


def logout(settings: Settings, session_token: str | None) -> None:
    if not session_token:
        return
    with connect(settings) as conn:
        conn.execute("DELETE FROM sessions WHERE session_hash=?", (hash_secret(session_token),))


def list_profiles(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    if not actor.profile_ids:
        return []
    placeholders = ",".join("?" for _ in actor.profile_ids)
    with connect(settings) as conn:
        rows = conn.execute(
            f"SELECT * FROM profiles WHERE profile_id IN ({placeholders}) ORDER BY profile_id",
            actor.profile_ids,
        ).fetchall()
        output = []
        for row in rows:
            scope = [
                r["equipment_id"]
                for r in conn.execute(
                    "SELECT equipment_id FROM profile_equipment WHERE profile_id=? ORDER BY equipment_id",
                    (row["profile_id"],),
                ).fetchall()
                if r["equipment_id"] in actor.device_scopes
            ]
            output.append(
                {
                    "profile_id": row["profile_id"],
                    "version": row["version"],
                    "display_name": row["display_name"],
                    "scope_label": row["scope_label"],
                    "color": row["color"],
                    "policy_version": row["policy_version"],
                    "settings": json.loads(row["settings_json"]),
                    "effective_device_scope": scope,
                    "source_sha256": row["source_sha256"],
                }
            )
    return output


def _profile_for_actor(settings: Settings, actor: Actor, profile_id: str) -> dict[str, Any]:
    if profile_id not in actor.profile_ids:
        raise AppError("FORBIDDEN_PROFILE", "你沒有使用此設定的權限", status_code=403)
    profiles = {item["profile_id"]: item for item in list_profiles(settings, actor)}
    if profile_id not in profiles:
        raise AppError("FORBIDDEN_PROFILE", "設定不存在或不在授權範圍", status_code=403)
    return profiles[profile_id]


def profile_for_actor(settings: Settings, actor: Actor, profile_id: str) -> dict[str, Any]:
    return _profile_for_actor(settings, actor, profile_id)


def normalize_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, set[str]] = {
        "get_equipment_status": {"equipment_id"},
        "list_maintenance_history": {"equipment_id", "date_from", "date_to", "cursor", "limit"},
        "check_parts_stock": {"part_id", "equipment_id"},
    }
    if tool_name not in allowed:
        raise AppError("TOOL_NOT_ALLOWED", "首版只開放三個唯讀工具", status_code=404)
    unknown = set(arguments) - allowed[tool_name]
    if unknown:
        raise AppError("INVALID_ARGUMENT", f"不接受的欄位：{', '.join(sorted(unknown))}")
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            cleaned[key] = value.strip()
        else:
            cleaned[key] = value
    if not cleaned.get("equipment_id"):
        raise AppError("INVALID_ARGUMENT", "設備編號為必填")
    if tool_name == "check_parts_stock" and not cleaned.get("part_id"):
        raise AppError("INVALID_ARGUMENT", "零件編號為必填")
    if tool_name == "list_maintenance_history":
        cleaned.setdefault("date_from", "")
        cleaned.setdefault("date_to", "")
        cleaned.setdefault("cursor", "")
        try:
            cleaned["limit"] = int(cleaned.get("limit", 20))
        except (TypeError, ValueError) as exc:
            raise AppError("INVALID_ARGUMENT", "筆數上限必須是整數") from exc
        if not 1 <= cleaned["limit"] <= 50:
            raise AppError("INVALID_ARGUMENT", "筆數上限需介於 1–50")
    return cleaned


def prepare_tool_call(
    settings: Settings,
    actor: Actor,
    profile_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    if not READ_ROLES.intersection(actor.roles):
        raise AppError("FORBIDDEN_ROLE", "目前角色不可查詢工具", status_code=403)
    normalized = normalize_arguments(tool_name, arguments)
    profile = _profile_for_actor(settings, actor, profile_id)
    equipment_id = str(normalized["equipment_id"])
    if equipment_id not in actor.device_scopes or equipment_id not in profile["effective_device_scope"]:
        raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到資料或不在授權範圍", status_code=404)
    trace_id = f"TRC-{uuid.uuid4().hex[:16].upper()}"
    raw_token = new_token()
    now = int(time.time())
    with connect(settings) as conn:
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="policy.authorized",
            status="success",
            tool_name=tool_name,
            actor_id=actor.user_id,
            profile_id=profile_id,
            summary={"target_id": equipment_id, "args_sha256": canonical_hash(normalized)},
        )
        conn.execute(
            """INSERT INTO auth_contexts
               (token_hash, actor_id, session_epoch, tool_name, args_sha256, profile_id,
                policy_version, target_id, trace_id, environment_id, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hash_secret(raw_token), actor.user_id, actor.session_epoch, tool_name,
                canonical_hash(normalized), profile_id, profile["policy_version"], equipment_id,
                trace_id, settings.environment_id, now + settings.auth_context_seconds, now,
            ),
        )
    return raw_token, trace_id, normalized


def consume_auth_context(
    settings: Settings,
    token: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    now = int(time.time())
    token_hash = hash_secret(token)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM auth_contexts WHERE token_hash=?", (token_hash,)).fetchone()
        if not row:
            raise AppError("AUTH_CONTEXT_MISSING", "授權上下文不存在", status_code=403)
        if row["used_at"] is not None:
            raise AppError("AUTH_CONTEXT_REPLAYED", "授權上下文已使用", status_code=403)
        if row["expires_at"] <= now:
            raise AppError("AUTH_CONTEXT_EXPIRED", "授權上下文已過期", status_code=403)
        if row["environment_id"] != settings.environment_id:
            raise AppError("ENVIRONMENT_MISMATCH", "授權環境不相符", status_code=403)
        if row["tool_name"] != tool_name or row["args_sha256"] != canonical_hash(arguments):
            raise AppError("AUTH_CONTEXT_MISMATCH", "工具或參數與授權內容不符", status_code=403)
        user = conn.execute("SELECT active, session_epoch FROM users WHERE user_id=?", (row["actor_id"],)).fetchone()
        if not user or not user["active"] or int(user["session_epoch"]) != int(row["session_epoch"]):
            raise AppError("ACTOR_REVOKED", "帳號已停用或權限版本改變", status_code=403)
        conn.execute("UPDATE auth_contexts SET used_at=? WHERE token_hash=?", (now, token_hash))
        append_trace(
            conn,
            settings=settings,
            trace_id=row["trace_id"],
            event_type="mcp.auth_context_consumed",
            status="success",
            tool_name=tool_name,
            actor_id=row["actor_id"],
            profile_id=row["profile_id"],
            summary={"target_id": row["target_id"], "single_use": True},
        )
        return dict(row)


def execute_read_query(
    settings: Settings,
    auth: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    equipment_id = arguments["equipment_id"]
    with connect(settings) as conn:
        membership = conn.execute(
            "SELECT 1 FROM profile_equipment WHERE profile_id=? AND equipment_id=?",
            (auth["profile_id"], equipment_id),
        ).fetchone()
        if not membership:
            raise AppError("FORBIDDEN_SCOPE", "設備不在設定範圍", status_code=403)
        if tool_name == "get_equipment_status":
            row = conn.execute("SELECT * FROM equipment WHERE equipment_id=?", (equipment_id,)).fetchone()
            if not row:
                raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到資料或不在授權範圍", status_code=404)
            result = {
                "equipment_id": row["equipment_id"],
                "display_name": row["display_name"],
                "status": row["status"],
                "observed_at": row["observed_at"],
                "source_record_id": row["equipment_id"],
                "data_version": row["data_version"],
                "provenance": {"source_kind": row["source_kind"], "source_sha256": row["source_sha256"]},
            }
        elif tool_name == "list_maintenance_history":
            clauses = ["equipment_id=?"]
            params: list[Any] = [equipment_id]
            if arguments.get("date_from"):
                clauses.append("started_at>=?")
                params.append(arguments["date_from"])
            if arguments.get("date_to"):
                clauses.append("started_at<=?")
                params.append(arguments["date_to"])
            if arguments.get("cursor"):
                clauses.append("record_id>?")
                params.append(arguments["cursor"])
            params.append(arguments.get("limit", 20))
            rows = conn.execute(
                f"""SELECT * FROM maintenance_history WHERE {' AND '.join(clauses)}
                    ORDER BY record_id LIMIT ?""",
                params,
            ).fetchall()
            items = []
            for row in rows:
                items.append(
                    {
                        "record_id": row["record_id"], "category": row["category"],
                        "summary": row["summary"], "status": row["status"],
                        "started_at": row["started_at"], "completed_at": row["completed_at"],
                        "part_ids": json.loads(row["part_ids_json"]),
                        "provenance": {"source_kind": row["source_kind"], "source_sha256": row["source_sha256"]},
                    }
                )
            result = {
                "items": items,
                "result_count": len(items),
                "next_cursor": items[-1]["record_id"] if len(items) == arguments.get("limit", 20) else None,
                "data_version": "history-seed-v1",
            }
        elif tool_name == "check_parts_stock":
            row = conn.execute("SELECT * FROM parts WHERE part_id=?", (arguments["part_id"],)).fetchone()
            if not row:
                raise AppError("PART_NOT_FOUND", "找不到零件", status_code=404)
            compatibility = conn.execute(
                "SELECT basis FROM part_compatibility WHERE part_id=? AND equipment_id=?",
                (arguments["part_id"], equipment_id),
            ).fetchone()
            result = {
                "part_id": row["part_id"], "display_name": row["display_name"],
                "stock_quantity": row["stock_quantity"], "unit": row["unit"],
                "compatible": bool(compatibility),
                "compatibility_basis": compatibility["basis"] if compatibility else None,
                "data_version": row["data_version"],
                "provenance": {"source_kind": row["source_kind"], "source_sha256": row["source_sha256"]},
            }
        else:
            raise AppError("TOOL_NOT_ALLOWED", "工具不在唯讀清單", status_code=404)
        result.update(
            {
                "trace_id": auth["trace_id"],
                "tool_version": "v1",
                "schema_version": "v1",
                "environment_kind": settings.environment_kind,
                "environment_id": settings.environment_id,
                "profile_id": auth["profile_id"],
            }
        )
        append_trace(
            conn,
            settings=settings,
            trace_id=auth["trace_id"],
            event_type="business.read_completed",
            status="success",
            tool_name=tool_name,
            actor_id=auth["actor_id"],
            profile_id=auth["profile_id"],
            summary={"target_id": equipment_id, "result_count": result.get("result_count", 1)},
        )
        return result


def list_traces(settings: Settings, actor: Actor, limit: int = 50) -> list[dict[str, Any]]:
    with connect(settings) as conn:
        rows = conn.execute(
            """SELECT * FROM traces WHERE actor_id=? ORDER BY created_at DESC, event_id DESC LIMIT ?""",
            (actor.user_id, min(max(limit, 1), 200)),
        ).fetchall()
    output = rows_to_dicts(rows)
    for row in output:
        row["summary"] = json.loads(row.pop("summary_json"))
    return output

