from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .config import Settings
from .db import append_trace, connect
from .errors import AppError
from .security import canonical_hash, hash_secret, new_token
from .services import Actor, profile_for_actor


WRITE_TOOL = "create_maintenance_order"
WORKSPACE_ID = "local-default"
PRIORITIES = {"low", "normal", "high", "urgent"}
REVIEWABLE = {"pending_review", "partially_approved"}
RETENTION_DAYS = {1, 7}


def _proposal_row(conn, proposal_id: str, proposal_version: int | None = None):
    if proposal_version is None:
        return conn.execute(
            "SELECT * FROM proposals WHERE proposal_id=? ORDER BY proposal_version DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM proposals WHERE proposal_id=? AND proposal_version=?",
        (proposal_id, proposal_version),
    ).fetchone()


def _normalize_payload(profile: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
    allowed = {"equipment_id", "issue_summary", "priority", "maintenance_window", "risk_summary"}
    unknown = set(payload) - allowed
    if unknown:
        raise AppError("INVALID_ARGUMENT", f"不接受的提案欄位：{', '.join(sorted(unknown))}")
    normalized = {key: str(payload.get(key, "")).strip() for key in allowed}
    if normalized["equipment_id"] not in profile["effective_device_scope"]:
        raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到設備或不在授權範圍", status_code=404)
    if not 10 <= len(normalized["issue_summary"]) <= 1000:
        raise AppError("INVALID_ARGUMENT", "問題摘要需為 10–1000 字")
    if normalized["priority"] not in PRIORITIES:
        raise AppError("INVALID_ARGUMENT", "優先序不正確")
    settings = profile["settings"]
    if settings.get("maintenance_window_required") and not normalized["maintenance_window"]:
        raise AppError("INVALID_ARGUMENT", "設備管理版必須填寫維護時段")
    if settings.get("risk_summary_required") and not 10 <= len(normalized["risk_summary"]) <= 500:
        raise AppError("INVALID_ARGUMENT", "設備管理版風險說明需為 10–500 字")
    if "\x00" in "".join(normalized.values()):
        raise AppError("INVALID_ARGUMENT", "欄位包含不允許的控制字元")
    return normalized


def _public_proposal(conn, row) -> dict[str, Any]:
    approvals = conn.execute(
        """SELECT a.approval_id, a.reviewer_id, u.username AS reviewer_name,
                  a.decision, a.reason, a.created_at
           FROM approvals a JOIN users u ON u.user_id=a.reviewer_id
           WHERE a.proposal_id=? AND a.proposal_version=? ORDER BY a.created_at, a.approval_id""",
        (row["proposal_id"], row["proposal_version"]),
    ).fetchall()
    return {
        "proposal_id": row["proposal_id"],
        "proposal_version": row["proposal_version"],
        "profile_id": row["profile_id"],
        "profile_version": row["profile_version"],
        "policy_version": row["policy_version"],
        "tool_name": row["tool_name"],
        "equipment_id": row["equipment_id"],
        "parameters": json.loads(row["parameters_json"]),
        "parameters_sha256": row["parameters_sha256"],
        "equipment_data_version": row["equipment_data_version"],
        "status": row["status"],
        "required_approvals": row["required_approvals"],
        "proposer_id": row["proposer_id"],
        "expires_at": row["expires_at"],
        "idempotency_suffix": row["idempotency_key"][-8:],
        "environment_id": row["environment_id"],
        "source_kind": row["source_kind"],
        "evidence_kind": row["evidence_kind"],
        "retention_days": row["retention_days"],
        "content_expires_at": row["content_expires_at"],
        "content_state": row["content_state"],
        "purged_at": row["purged_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approvals": [dict(item) for item in approvals],
    }


def create_proposal(
    settings: Settings,
    actor: Actor,
    profile_id: str,
    payload: dict[str, Any],
    retention_days: int | None = None,
) -> dict[str, Any]:
    if "operator" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有 operator 可以建立提案", status_code=403)
    profile = profile_for_actor(settings, actor, profile_id)
    if retention_days is None:
        retention_days = int(profile["settings"].get("retention_default_days", 7))
    if retention_days not in RETENTION_DAYS:
        raise AppError("INVALID_ARGUMENT", "保存期限只能選擇 1 日或 7 日")
    normalized = _normalize_payload(profile, payload)
    now = int(time.time())
    proposal_id = f"PRP-{uuid.uuid4().hex[:12].upper()}"
    with connect(settings) as conn:
        equipment = conn.execute(
            "SELECT data_version FROM equipment WHERE equipment_id=? AND environment_id=?",
            (normalized["equipment_id"], settings.environment_id),
        ).fetchone()
        if not equipment:
            raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到設備或不在授權範圍", status_code=404)
        conn.execute(
            """INSERT INTO proposals
               (proposal_id, proposal_version, profile_id, profile_version, policy_version,
                tool_name, equipment_id, parameters_json, parameters_sha256,
                equipment_data_version, status, required_approvals, proposer_id, expires_at,
                idempotency_key, environment_id, workspace_id, source_kind, evidence_kind,
                retention_days, content_expires_at, content_state, purged_at,
                created_at, updated_at)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, NULL, ?, ?, ?,
                       'user_entered_synthetic_context', 'measured_local', ?, ?, 'available', NULL, ?, ?)""",
            (
                proposal_id,
                profile_id,
                profile["version"],
                profile["policy_version"],
                WRITE_TOOL,
                normalized["equipment_id"],
                json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                canonical_hash(normalized),
                equipment["data_version"],
                int(profile["settings"]["approval_count"]),
                actor.user_id,
                new_token(24),
                settings.environment_id,
                WORKSPACE_ID,
                retention_days,
                now + retention_days * 86400,
                now,
                now,
            ),
        )
        row = _proposal_row(conn, proposal_id, 1)
        return _public_proposal(conn, row)


def revise_proposal(
    settings: Settings,
    actor: Actor,
    proposal_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if "operator" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有 operator 可以修改提案", status_code=403)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _purge_expired_content(conn, settings)
        current = _proposal_row(conn, proposal_id)
        if not current or current["proposer_id"] != actor.user_id:
            raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到提案或不在授權範圍", status_code=404)
        _ensure_content_available(current)
        if current["status"] in {"consumed", "cancelled", "expired"}:
            raise AppError("PROPOSAL_IMMUTABLE", "此提案已不能修改", status_code=409)
        profile = profile_for_actor(settings, actor, current["profile_id"])
        normalized = _normalize_payload(profile, payload)
        equipment = conn.execute(
            "SELECT data_version FROM equipment WHERE equipment_id=?",
            (normalized["equipment_id"],),
        ).fetchone()
        next_version = int(current["proposal_version"]) + 1
        now = int(time.time())
        conn.execute(
            "UPDATE proposals SET status='invalidated', updated_at=? WHERE proposal_id=? AND proposal_version=?",
            (now, proposal_id, current["proposal_version"]),
        )
        conn.execute(
            """INSERT INTO proposals
               (proposal_id, proposal_version, profile_id, profile_version, policy_version,
                tool_name, equipment_id, parameters_json, parameters_sha256,
                equipment_data_version, status, required_approvals, proposer_id, expires_at,
                idempotency_key, environment_id, workspace_id, source_kind, evidence_kind,
                retention_days, content_expires_at, content_state, purged_at,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, NULL, ?, ?, ?,
                       'user_entered_synthetic_context', 'measured_local', ?, ?, 'available', NULL, ?, ?)""",
            (
                proposal_id,
                next_version,
                current["profile_id"],
                profile["version"],
                profile["policy_version"],
                WRITE_TOOL,
                normalized["equipment_id"],
                json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                canonical_hash(normalized),
                equipment["data_version"],
                int(profile["settings"]["approval_count"]),
                actor.user_id,
                new_token(24),
                settings.environment_id,
                WORKSPACE_ID,
                current["retention_days"],
                current["content_expires_at"],
                now,
                now,
            ),
        )
        return _public_proposal(conn, _proposal_row(conn, proposal_id, next_version))


def submit_proposal(settings: Settings, actor: Actor, proposal_id: str, proposal_version: int) -> dict[str, Any]:
    if "operator" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有 operator 可以送審", status_code=403)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _purge_expired_content(conn, settings)
        row = _proposal_row(conn, proposal_id, proposal_version)
        latest = _proposal_row(conn, proposal_id)
        if not row or row["proposer_id"] != actor.user_id:
            raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到提案或不在授權範圍", status_code=404)
        if latest["proposal_version"] != proposal_version:
            raise AppError("APPROVAL_STALE", "這不是最新提案版本", status_code=409)
        _ensure_content_available(row)
        if row["status"] != "draft":
            raise AppError("INVALID_TRANSITION", "只有草稿可以送審", status_code=409)
        now = int(time.time())
        conn.execute(
            "UPDATE proposals SET status='pending_review', expires_at=?, updated_at=? "
            "WHERE proposal_id=? AND proposal_version=?",
            (now + 24 * 60 * 60, now, proposal_id, proposal_version),
        )
        return _public_proposal(conn, _proposal_row(conn, proposal_id, proposal_version))


def review_proposal(
    settings: Settings,
    actor: Actor,
    proposal_id: str,
    proposal_version: int,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    if "reviewer" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有 reviewer 可以審核，admin 不會自動取得此權限", status_code=403)
    if decision not in {"approve", "reject", "changes_requested"}:
        raise AppError("INVALID_ARGUMENT", "審核決定不正確")
    reason = reason.strip()
    if len(reason) < 8:
        raise AppError("INVALID_ARGUMENT", "審核理由至少 8 個字元")
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _purge_expired_content(conn, settings)
        row = _proposal_row(conn, proposal_id, proposal_version)
        latest = _proposal_row(conn, proposal_id)
        if not row or latest["proposal_version"] != proposal_version:
            raise AppError("APPROVAL_STALE", "提案版本已變更", status_code=409)
        _ensure_content_available(row)
        if row["proposer_id"] == actor.user_id:
            raise AppError("SELF_REVIEW_FORBIDDEN", "提出者不得審核自己的提案", status_code=403)
        if row["profile_id"] not in actor.profile_ids or row["equipment_id"] not in actor.device_scopes:
            raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到提案或不在審核範圍", status_code=404)
        if row["status"] not in REVIEWABLE:
            raise AppError("INVALID_TRANSITION", "此提案目前不可審核", status_code=409)
        if row["expires_at"] is not None and row["expires_at"] <= int(time.time()):
            conn.execute(
                "UPDATE proposals SET status='expired', updated_at=? WHERE proposal_id=? AND proposal_version=?",
                (int(time.time()), proposal_id, proposal_version),
            )
            conn.commit()
            raise AppError("APPROVAL_STALE", "提案已過期，必須重新送審", status_code=409)
        existing = conn.execute(
            "SELECT decision FROM approvals WHERE proposal_id=? AND proposal_version=? AND reviewer_id=?",
            (proposal_id, proposal_version, actor.user_id),
        ).fetchone()
        if existing:
            if existing["decision"] != decision:
                raise AppError("DECISION_ALREADY_RECORDED", "已留下審核決定，不能覆寫歷史", status_code=409)
            return _public_proposal(conn, row)
        conn.execute(
            """INSERT INTO approvals
               (approval_id, proposal_id, proposal_version, reviewer_id, decision, reason,
                policy_version, parameters_sha256, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"APR-{uuid.uuid4().hex[:12].upper()}",
                proposal_id,
                proposal_version,
                actor.user_id,
                decision,
                reason,
                row["policy_version"],
                row["parameters_sha256"],
                int(time.time()),
            ),
        )
        if decision == "reject":
            next_status = "rejected"
        elif decision == "changes_requested":
            next_status = "changes_requested"
        else:
            approved = conn.execute(
                "SELECT COUNT(*) AS n FROM approvals WHERE proposal_id=? AND proposal_version=? AND decision='approve'",
                (proposal_id, proposal_version),
            ).fetchone()["n"]
            next_status = "approved" if approved >= row["required_approvals"] else "partially_approved"
        conn.execute(
            "UPDATE proposals SET status=?, updated_at=? WHERE proposal_id=? AND proposal_version=?",
            (next_status, int(time.time()), proposal_id, proposal_version),
        )
        return _public_proposal(conn, _proposal_row(conn, proposal_id, proposal_version))


def list_proposals(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    with connect(settings) as conn:
        _purge_expired_content(conn, settings)
        rows = conn.execute(
            """SELECT p.* FROM proposals p
               WHERE NOT EXISTS (
                 SELECT 1 FROM proposals newer
                 WHERE newer.proposal_id=p.proposal_id AND newer.proposal_version>p.proposal_version
               ) ORDER BY p.updated_at DESC"""
        ).fetchall()
        visible = []
        for row in rows:
            own = "operator" in actor.roles and row["proposer_id"] == actor.user_id
            reviewable = (
                "reviewer" in actor.roles
                and row["profile_id"] in actor.profile_ids
                and row["equipment_id"] in actor.device_scopes
            )
            if own or reviewable:
                visible.append(_public_proposal(conn, row))
        return visible


def _execution_arguments(row, maintenance_confirmed: bool) -> dict[str, Any]:
    parameters = json.loads(row["parameters_json"])
    return {
        "proposal_id": row["proposal_id"],
        "proposal_version": row["proposal_version"],
        **parameters,
        "maintenance_confirmed": bool(maintenance_confirmed),
        "idempotency_key": row["idempotency_key"],
    }


def prepare_execution_call(
    settings: Settings,
    actor: Actor,
    proposal_id: str,
    proposal_version: int,
    maintenance_confirmed: bool,
) -> tuple[str, str, str, dict[str, Any]]:
    if "operator" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有 operator 可以執行已核准提案", status_code=403)
    with connect(settings) as conn:
        _purge_expired_content(conn, settings)
        row = _proposal_row(conn, proposal_id, proposal_version)
        latest = _proposal_row(conn, proposal_id)
        if not row or row["proposer_id"] != actor.user_id:
            raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到提案或不在執行範圍", status_code=404)
        if latest["proposal_version"] != proposal_version:
            raise AppError("APPROVAL_STALE", "提案已有更新版本", status_code=409)
        _ensure_content_available(row)
        if row["status"] not in {"approved", "consumed"}:
            raise AppError("PROPOSAL_NOT_APPROVED", "提案尚未完成核准", status_code=409)
        profile = profile_for_actor(settings, actor, row["profile_id"])
        if profile["settings"].get("maintenance_window_required") and not maintenance_confirmed:
            raise AppError("MAINTENANCE_CONFIRMATION_REQUIRED", "設備管理版執行前必須確認維護時段與風險", status_code=409)
        arguments = _execution_arguments(row, maintenance_confirmed)
        trace_id = f"TRC-{uuid.uuid4().hex[:16].upper()}"
        raw_token = new_token()
        now = int(time.time())
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="policy.write_authorized",
            status="success",
            tool_name=WRITE_TOOL,
            actor_id=actor.user_id,
            profile_id=row["profile_id"],
            summary={
                "proposal_id": proposal_id,
                "proposal_version": proposal_version,
                "target_id": row["equipment_id"],
                "args_sha256": canonical_hash(arguments),
            },
        )
        conn.execute(
            """INSERT INTO auth_contexts
               (token_hash, actor_id, session_epoch, tool_name, args_sha256, profile_id,
                policy_version, target_id, trace_id, environment_id, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hash_secret(raw_token),
                actor.user_id,
                actor.session_epoch,
                WRITE_TOOL,
                canonical_hash(arguments),
                row["profile_id"],
                row["policy_version"],
                row["equipment_id"],
                trace_id,
                settings.environment_id,
                now + settings.auth_context_seconds,
                now,
            ),
        )
        return raw_token, trace_id, row["profile_id"], arguments


def _order_result(conn, execution, *, deduplicated: bool, recovered: bool = False) -> dict[str, Any]:
    order = conn.execute(
        "SELECT * FROM maintenance_orders WHERE order_id=?",
        (execution["order_id"],),
    ).fetchone()
    if not order:
        raise AppError("OUTCOME_UNKNOWN", "執行紀錄存在，但尚未找到工單", status_code=409, recoverable=True)
    return {
        "order_id": order["order_id"],
        "order_status": order["order_status"],
        "order_version": order["order_version"],
        "created_at": order["created_at"],
        "deduplicated": deduplicated,
        "recovered": recovered,
        "execution_id": execution["execution_id"],
        "trace_id": execution["trace_id"],
        "environment_id": order["environment_id"],
        "source_kind": order["source_kind"],
    }


def execute_write_query(
    settings: Settings,
    auth: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    request_sha = canonical_hash(arguments)
    now = int(time.time())
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _purge_expired_content(conn, settings)
        row = _proposal_row(conn, arguments["proposal_id"], int(arguments["proposal_version"]))
        if row:
            _ensure_content_available(row)
        existing = conn.execute(
            "SELECT * FROM executions WHERE environment_id=? AND tool_name=? AND idempotency_key=?",
            (settings.environment_id, WRITE_TOOL, arguments["idempotency_key"]),
        ).fetchone()
        if existing:
            if existing["request_sha256"] != request_sha:
                raise AppError("IDEMPOTENCY_CONFLICT", "相同冪等鍵綁定了不同內容", status_code=409)
            return _order_result(conn, existing, deduplicated=True)
        if not row or row["status"] != "approved":
            raise AppError("PROPOSAL_NOT_APPROVED", "提案未核准或已被消耗", status_code=409)
        if row["proposer_id"] != auth["actor_id"]:
            raise AppError("FORBIDDEN_SCOPE", "只有原提出者可以執行", status_code=403)
        user = conn.execute("SELECT * FROM users WHERE user_id=?", (auth["actor_id"],)).fetchone()
        if not user or not user["active"] or "operator" not in json.loads(user["roles_json"]):
            raise AppError("ACTOR_REVOKED", "operator 權限已被停用或撤回", status_code=403)
        if row["equipment_id"] not in json.loads(user["device_scopes_json"]):
            raise AppError("ACTOR_REVOKED", "設備執行權限已被撤回", status_code=403)
        if row["expires_at"] is None or row["expires_at"] <= now:
            raise AppError("APPROVAL_STALE", "核准已過期", status_code=409)
        profile = conn.execute("SELECT * FROM profiles WHERE profile_id=?", (row["profile_id"],)).fetchone()
        if not profile or profile["version"] != row["profile_version"] or profile["policy_version"] != row["policy_version"]:
            raise AppError("POLICY_VERSION_CONFLICT", "Profile 或政策版本已改變", status_code=409)
        equipment = conn.execute("SELECT data_version FROM equipment WHERE equipment_id=?", (row["equipment_id"],)).fetchone()
        if not equipment or equipment["data_version"] != row["equipment_data_version"]:
            raise AppError("DATA_VERSION_CONFLICT", "設備資料版本已改變，必須重新送審", status_code=409)
        stored = json.loads(row["parameters_json"])
        submitted = {key: arguments[key] for key in stored}
        if canonical_hash(stored) != canonical_hash(submitted) or row["parameters_sha256"] != canonical_hash(stored):
            raise AppError("APPROVAL_STALE", "執行參數與核准內容不一致", status_code=409)
        approval_rows = conn.execute(
            """SELECT a.reviewer_id, u.active, u.roles_json
               FROM approvals a JOIN users u ON u.user_id=a.reviewer_id
               WHERE a.proposal_id=? AND a.proposal_version=? AND a.decision='approve'""",
            (row["proposal_id"], row["proposal_version"]),
        ).fetchall()
        valid_reviewers = {
            item["reviewer_id"]
            for item in approval_rows
            if item["active"] and "reviewer" in json.loads(item["roles_json"])
            and item["reviewer_id"] != row["proposer_id"]
        }
        if len(valid_reviewers) < row["required_approvals"]:
            raise AppError("APPROVAL_STALE", "有效 reviewer 數量不足", status_code=409)
        profile_settings = json.loads(profile["settings_json"])
        if profile_settings.get("maintenance_window_required") and not arguments.get("maintenance_confirmed"):
            raise AppError("MAINTENANCE_CONFIRMATION_REQUIRED", "維護確認尚未完成", status_code=409)

        execution_id = f"EXE-{uuid.uuid4().hex[:12].upper()}"
        count = conn.execute("SELECT COUNT(*) AS n FROM maintenance_orders").fetchone()["n"] + 1
        order_id = f"MO-{time.strftime('%Y%m%d', time.localtime(now))}-{count:06d}"
        conn.execute(
            """INSERT INTO executions
               (execution_id, proposal_id, proposal_version, operator_id, environment_id,
                tool_name, idempotency_key, request_sha256, status, order_id, trace_id,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'succeeded', ?, ?, ?, ?)""",
            (
                execution_id, row["proposal_id"], row["proposal_version"], auth["actor_id"],
                settings.environment_id, WRITE_TOOL, arguments["idempotency_key"], request_sha,
                order_id, auth["trace_id"], now, now,
            ),
        )
        conn.execute(
            """INSERT INTO maintenance_orders
               (order_id, order_status, order_version, proposal_id, proposal_version,
                execution_id, equipment_id, profile_id, issue_summary, priority,
                maintenance_window, risk_summary, environment_id, workspace_id,
                source_kind, evidence_kind, created_by, created_at)
               VALUES (?, 'open', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       'approved_user_proposal', 'measured_local', ?, ?)""",
            (
                order_id, row["proposal_id"], row["proposal_version"], execution_id,
                stored["equipment_id"], row["profile_id"], stored["issue_summary"],
                stored["priority"], stored["maintenance_window"], stored["risk_summary"],
                settings.environment_id, WORKSPACE_ID, auth["actor_id"], now,
            ),
        )
        conn.execute(
            "UPDATE proposals SET status='consumed', updated_at=? WHERE proposal_id=? AND proposal_version=?",
            (now, row["proposal_id"], row["proposal_version"]),
        )
        conn.execute(
            """INSERT INTO outbox_events(event_id, event_type, aggregate_id, payload_json, environment_id, created_at)
               VALUES (?, 'maintenance_order.created', ?, ?, ?, ?)""",
            (
                f"EVT-{uuid.uuid4().hex[:12].upper()}",
                order_id,
                json.dumps({"order_id": order_id, "execution_id": execution_id}, sort_keys=True),
                settings.environment_id,
                now,
            ),
        )
        append_trace(
            conn,
            settings=settings,
            trace_id=auth["trace_id"],
            event_type="business.write_committed",
            status="success",
            tool_name=WRITE_TOOL,
            actor_id=auth["actor_id"],
            profile_id=row["profile_id"],
            summary={"order_id": order_id, "execution_id": execution_id, "atomic": True},
        )
        execution = conn.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
        return _order_result(conn, execution, deduplicated=False)


def recover_execution(
    settings: Settings,
    actor: Actor,
    proposal_id: str,
    proposal_version: int,
) -> dict[str, Any]:
    with connect(settings) as conn:
        _purge_expired_content(conn, settings)
        proposal = _proposal_row(conn, proposal_id, proposal_version)
        if not proposal or proposal["proposer_id"] != actor.user_id:
            raise AppError("NOT_FOUND_OR_FORBIDDEN", "找不到執行紀錄或不在授權範圍", status_code=404)
        _ensure_content_available(proposal)
        execution = conn.execute(
            "SELECT * FROM executions WHERE proposal_id=? AND proposal_version=? ORDER BY created_at DESC LIMIT 1",
            (proposal_id, proposal_version),
        ).fetchone()
        if not execution:
            raise AppError("OUTCOME_UNKNOWN", "尚未找到已提交的工單", status_code=404, recoverable=True)
        return _order_result(conn, execution, deduplicated=True, recovered=True)


def list_orders(settings: Settings, actor: Actor) -> list[dict[str, Any]]:
    if not {"viewer", "operator", "reviewer"}.intersection(actor.roles):
        raise AppError("FORBIDDEN_ROLE", "目前角色不可查看工單", status_code=403)
    with connect(settings) as conn:
        _purge_expired_content(conn, settings)
        rows = conn.execute("SELECT * FROM maintenance_orders ORDER BY created_at DESC, order_id DESC").fetchall()
    return [
        {
            "order_id": row["order_id"],
            "order_status": row["order_status"],
            "order_version": row["order_version"],
            "proposal_id": row["proposal_id"],
            "proposal_version": row["proposal_version"],
            "execution_id": row["execution_id"],
            "equipment_id": row["equipment_id"],
            "profile_id": row["profile_id"],
            "issue_summary": row["issue_summary"],
            "priority": row["priority"],
            "maintenance_window": row["maintenance_window"],
            "risk_summary": row["risk_summary"],
            "environment_id": row["environment_id"],
            "source_kind": row["source_kind"],
            "evidence_kind": row["evidence_kind"],
            "created_at": row["created_at"],
        }
        for row in rows
        if row["equipment_id"] in actor.device_scopes and row["profile_id"] in actor.profile_ids
    ]


def _ensure_content_available(row) -> None:
    if row["content_state"] != "available" or (
        row["content_expires_at"] is not None and row["content_expires_at"] <= int(time.time())
    ):
        raise AppError(
            "CONTENT_EXPIRED",
            "提案內容已依保存政策到期清除，不能再核准、執行或重播結果",
            status_code=410,
            recoverable=False,
        )


def _purge_expired_content(conn, settings: Settings, now: int | None = None) -> int:
    purge_time = now or int(time.time())
    rows = conn.execute(
        """SELECT proposal_id, proposal_version FROM proposals
           WHERE content_state='available' AND content_expires_at IS NOT NULL AND content_expires_at<=?""",
        (purge_time,),
    ).fetchall()
    for row in rows:
        proposal_id = row["proposal_id"]
        proposal_version = row["proposal_version"]
        conn.execute(
            """UPDATE proposals SET parameters_json='{}', content_state='purged', purged_at=?,
               status=CASE WHEN status='consumed' THEN status ELSE 'expired' END, updated_at=?
               WHERE proposal_id=? AND proposal_version=?""",
            (purge_time, purge_time, proposal_id, proposal_version),
        )
        conn.execute(
            "UPDATE approvals SET reason='［已依保存政策清除］' WHERE proposal_id=? AND proposal_version=?",
            (proposal_id, proposal_version),
        )
        conn.execute(
            """UPDATE maintenance_orders SET issue_summary='', maintenance_window='', risk_summary=''
               WHERE proposal_id=? AND proposal_version=?""",
            (proposal_id, proposal_version),
        )
        trace_rows = conn.execute(
            "SELECT trace_id FROM executions WHERE proposal_id=? AND proposal_version=?",
            (proposal_id, proposal_version),
        ).fetchall()
        for trace_row in trace_rows:
            conn.execute(
                "UPDATE traces SET summary_json=? WHERE trace_id=?",
                (
                    json.dumps(
                        {"content_state": "purged", "proposal_id": proposal_id},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    trace_row["trace_id"],
                ),
            )
    if rows:
        append_trace(
            conn,
            settings=settings,
            trace_id=f"TRC-{uuid.uuid4().hex[:16].upper()}",
            event_type="retention.content_purged",
            status="success",
            tool_name=None,
            actor_id=None,
            profile_id=None,
            summary={"purged_count": len(rows)},
        )
    return len(rows)


def purge_expired_content(settings: Settings, actor: Actor | None = None) -> dict[str, Any]:
    if actor is not None and "admin" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有管理者可以手動執行到期清除", status_code=403)
    with connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        purged_count = _purge_expired_content(conn, settings)
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE content_state='available'"
        ).fetchone()["n"]
    return {"purged_count": purged_count, "available_count": remaining}


def retention_summary(settings: Settings, actor: Actor) -> dict[str, Any]:
    if "admin" not in actor.roles:
        raise AppError("FORBIDDEN_ROLE", "只有管理者可以查看保存治理摘要", status_code=403)
    with connect(settings) as conn:
        _purge_expired_content(conn, settings)
        rows = conn.execute(
            "SELECT content_state, COUNT(*) AS n FROM proposals GROUP BY content_state"
        ).fetchall()
        counts = {row["content_state"]: row["n"] for row in rows}
    return {
        "allowed_retention_days": sorted(RETENTION_DAYS),
        "available_count": counts.get("available", 0),
        "purged_count": counts.get("purged", 0),
        "purge_scope": ["proposal_parameters", "approval_reasons", "order_business_fields", "execution_trace_summaries"],
        "preserved_scope": ["identifiers", "timestamps", "hashes", "statuses", "audit_events"],
    }
