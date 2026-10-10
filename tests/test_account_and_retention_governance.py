from __future__ import annotations

import time
import sqlite3

from fastapi.testclient import TestClient

from backend.app.db import _ensure_p2d1_schema, connect
from tests.conftest import csrf


def _create_user(admin, username: str, password: str, roles: list[str]):
    response = admin.post(
        "/api/admin/users",
        headers=csrf(admin),
        json={
            "username": username,
            "password": password,
            "roles": roles,
            "device_scopes": ["EQ-PUMP-001"],
            "profile_ids": ["service-v1"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]


def _login(app, username: str, password: str) -> TestClient:
    session = TestClient(app)
    response = session.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return session


def test_admin_account_lifecycle_revokes_sessions(authenticated):
    user = _create_user(authenticated, "field-operator", "operator-pass-1234", ["operator", "viewer"])
    worker = _login(authenticated.app, "field-operator", "operator-pass-1234")
    assert worker.get("/api/me").status_code == 200

    disabled = authenticated.patch(
        f"/api/admin/users/{user['user_id']}/status",
        headers=csrf(authenticated),
        json={"active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["user"]["active"] is False
    assert worker.get("/api/me").status_code == 401
    assert authenticated.post(
        "/api/login", json={"username": "field-operator", "password": "operator-pass-1234"}
    ).status_code == 401

    enabled = authenticated.patch(
        f"/api/admin/users/{user['user_id']}/status",
        headers=csrf(authenticated),
        json={"active": True},
    )
    assert enabled.status_code == 200
    worker = _login(authenticated.app, "field-operator", "operator-pass-1234")

    reset = authenticated.post(
        f"/api/admin/users/{user['user_id']}/password-reset",
        headers=csrf(authenticated),
        json={"password": "new-operator-pass-5678"},
    )
    assert reset.status_code == 200
    assert reset.json()["sessions_revoked"] is True
    assert worker.get("/api/me").status_code == 401
    assert authenticated.post(
        "/api/login", json={"username": "field-operator", "password": "operator-pass-1234"}
    ).status_code == 401
    worker = _login(authenticated.app, "field-operator", "new-operator-pass-5678")

    access = authenticated.put(
        f"/api/admin/users/{user['user_id']}/access",
        headers=csrf(authenticated),
        json={
            "roles": ["viewer"],
            "device_scopes": ["EQ-PUMP-001"],
            "profile_ids": ["service-v1"],
        },
    )
    assert access.status_code == 200
    assert access.json()["user"]["roles"] == ["viewer"]
    assert worker.get("/api/me").status_code == 401


def test_admin_cannot_disable_or_remove_own_admin_role(authenticated):
    me = authenticated.get("/api/me").json()["actor"]
    disabled = authenticated.patch(
        f"/api/admin/users/{me['user_id']}/status",
        headers=csrf(authenticated),
        json={"active": False},
    )
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "SELF_LOCKOUT_FORBIDDEN"
    changed = authenticated.put(
        f"/api/admin/users/{me['user_id']}/access",
        headers=csrf(authenticated),
        json={
            "roles": ["viewer"],
            "device_scopes": me["device_scopes"],
            "profile_ids": me["profile_ids"],
        },
    )
    assert changed.status_code == 409


def test_retention_expiry_purges_content_and_blocks_actions(settings, authenticated):
    user = _create_user(authenticated, "retention-operator", "operator-pass-1234", ["operator", "viewer"])
    worker = _login(authenticated.app, "retention-operator", "operator-pass-1234")
    created = worker.post(
        "/api/proposals",
        headers=csrf(worker),
        json={
            "profile_id": "service-v1",
            "retention_days": 1,
            "parameters": {
                "equipment_id": "EQ-PUMP-001",
                "issue_summary": "軸承溫度偏高且需要安排現場檢查",
                "priority": "high",
                "maintenance_window": "",
                "risk_summary": "",
            },
        },
    )
    assert created.status_code == 200, created.text
    proposal = created.json()["proposal"]
    assert proposal["retention_days"] == 1
    assert proposal["content_state"] == "available"
    assert proposal["content_expires_at"] - proposal["created_at"] == 86400

    with connect(settings) as conn:
        conn.execute(
            "UPDATE proposals SET content_expires_at=? WHERE proposal_id=?",
            (int(time.time()) - 1, proposal["proposal_id"]),
        )

    purge = authenticated.post("/api/admin/retention/purge", headers=csrf(authenticated))
    assert purge.status_code == 200
    assert purge.json()["purged_count"] == 1

    listed = worker.get("/api/proposals")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["content_state"] == "purged"
    assert item["parameters"] == {}
    assert item["status"] == "expired"

    submit = worker.post(
        f"/api/proposals/{proposal['proposal_id']}/submit",
        headers=csrf(worker),
        json={"proposal_version": 1},
    )
    assert submit.status_code == 410
    assert submit.json()["error"]["code"] == "CONTENT_EXPIRED"

    summary = authenticated.get("/api/admin/retention")
    assert summary.status_code == 200
    assert summary.json()["purged_count"] == 1
    assert summary.json()["allowed_retention_days"] == [1, 7]

    with connect(settings) as conn:
        stored = conn.execute(
            "SELECT parameters_json, parameters_sha256, content_state, purged_at FROM proposals WHERE proposal_id=?",
            (proposal["proposal_id"],),
        ).fetchone()
    assert stored["parameters_json"] == "{}"
    assert stored["parameters_sha256"]
    assert stored["content_state"] == "purged"
    assert stored["purged_at"] is not None


def test_invalid_retention_value_is_rejected(authenticated):
    _create_user(authenticated, "invalid-retention", "operator-pass-1234", ["operator"])
    worker = _login(authenticated.app, "invalid-retention", "operator-pass-1234")
    response = worker.post(
        "/api/proposals",
        headers=csrf(worker),
        json={
            "profile_id": "service-v1",
            "retention_days": 30,
            "parameters": {
                "equipment_id": "EQ-PUMP-001",
                "issue_summary": "測試不允許的內容保存期限輸入資料",
                "priority": "normal",
                "maintenance_window": "",
                "risk_summary": "",
            },
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_legacy_proposal_upgrade_grants_new_seven_day_window(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE proposals(proposal_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL)")
    conn.execute("INSERT INTO proposals(proposal_id, created_at) VALUES ('PRP-LEGACY', 1)")
    before = int(time.time())
    _ensure_p2d1_schema(conn)
    row = conn.execute("SELECT * FROM proposals WHERE proposal_id='PRP-LEGACY'").fetchone()
    conn.close()
    assert row["retention_days"] == 7
    assert row["content_state"] == "available"
    assert before + 7 * 86400 <= row["content_expires_at"] <= int(time.time()) + 7 * 86400


def test_retention_columns_belong_only_to_proposals(settings, client):
    with connect(settings) as conn:
        proposal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(proposals)")}
        trace_columns = {row["name"] for row in conn.execute("PRAGMA table_info(traces)")}
    retention_columns = {"retention_days", "content_expires_at", "content_state", "purged_at"}
    assert retention_columns.issubset(proposal_columns)
    assert retention_columns.isdisjoint(trace_columns)

