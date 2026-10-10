from __future__ import annotations

from backend.app.db import connect, initialize_database
from tests.conftest import csrf
from tests.test_write_workflow import create_user, login


def _login_admin(client) -> None:
    response = client.post(
        "/api/login",
        json={"username": "portfolio-admin", "password": "local-pass-1234"},
    )
    assert response.status_code == 200, response.text


def _snapshot(client, profile_id: str = "service-v1") -> dict:
    response = client.get("/api/profile-configs")
    assert response.status_code == 200, response.text
    return next(
        item["snapshot"]
        for item in response.json()["items"]
        if item["profile_id"] == profile_id and item["status"] == "active"
    )


def _candidate(snapshot: dict) -> dict:
    return {
        **snapshot,
        "display_name": "現場可靠度團隊",
        "scope_label": "RELIABILITY-C",
        "color": "#a34a28",
        "equipment_ids": ["EQ-PUMP-001", "EQ-FAN-002"],
        "settings": {
            **snapshot["settings"],
            "approval_count": 2,
            "terminology": "可靠度事件",
            "retention_default_days": 1,
        },
    }


def _create_preview_submit(client, snapshot: dict) -> dict:
    created = client.post(
        "/api/profile-configs/service-v1/draft",
        headers=csrf(client),
        json={"snapshot": snapshot},
    )
    assert created.status_code == 200, created.text
    version = created.json()["version"]
    premature_preview = client.post(
        "/api/profile-configs/service-v1/preview",
        headers=csrf(client),
        json={"revision": version["revision"]},
    )
    assert premature_preview.status_code == 409
    validated = client.post(
        "/api/profile-configs/service-v1/validate",
        headers=csrf(client),
        json={"revision": version["revision"]},
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["version"]["status"] == "validated"
    previewed = client.post(
        "/api/profile-configs/service-v1/preview",
        headers=csrf(client),
        json={"revision": version["revision"]},
    )
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["version"]["diff"]
    submitted = client.post(
        "/api/profile-configs/service-v1/submit",
        headers=csrf(client),
        json={"revision": version["revision"]},
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()["version"]


def _approve(client, version: dict) -> dict:
    response = client.post(
        "/api/profile-configs/service-v1/review",
        headers=csrf(client),
        json={
            "revision": version["revision"],
            "decision": "approve",
            "reason": "已確認設備範圍、核准人數與保存影響皆符合需求。",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["version"]


def test_profile_draft_preview_independent_approval_apply_and_restart(settings, authenticated):
    create_user(authenticated, "config-reviewer", ["reviewer", "viewer"])
    create_user(authenticated, "config-operator", ["operator", "viewer"])

    login(authenticated, "config-operator")
    old_proposal = authenticated.post(
        "/api/proposals",
        headers=csrf(authenticated),
        json={
            "profile_id": "service-v1",
            "parameters": {
                "equipment_id": "EQ-PUMP-001",
                "issue_summary": "設定套用前建立的提案應保留原始版本資料",
                "priority": "normal",
                "maintenance_window": "",
                "risk_summary": "",
            },
        },
    ).json()["proposal"]
    assert old_proposal["profile_version"] == "1.0.0"

    _login_admin(authenticated)
    version = _create_preview_submit(authenticated, _candidate(_snapshot(authenticated)))
    assert version["status"] == "submitted"
    assert version["version"] == "1.0.1"

    admin_review = authenticated.post(
        "/api/profile-configs/service-v1/review",
        headers=csrf(authenticated),
        json={"revision": version["revision"], "decision": "approve", "reason": "管理者不得代替 reviewer 核准。"},
    )
    assert admin_review.status_code == 403

    login(authenticated, "config-reviewer")
    approved = _approve(authenticated, version)
    assert approved["status"] == "approved"

    _login_admin(authenticated)
    applied = authenticated.post(
        "/api/profile-configs/service-v1/apply",
        headers=csrf(authenticated),
        json={"revision": version["revision"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["version"]["status"] == "active"

    profile = next(item for item in authenticated.get("/api/profiles").json()["items"] if item["profile_id"] == "service-v1")
    assert profile["version"] == "1.0.1"
    assert profile["policy_version"] == "service-v1-policy-r2"
    assert profile["display_name"] == "現場可靠度團隊"
    assert profile["effective_device_scope"] == ["EQ-FAN-002", "EQ-PUMP-001"]
    assert profile["settings"]["approval_count"] == 2
    assert profile["settings"]["retention_default_days"] == 1

    login(authenticated, "config-operator")
    proposals = authenticated.get("/api/proposals").json()["items"]
    preserved = next(item for item in proposals if item["proposal_id"] == old_proposal["proposal_id"])
    assert preserved["profile_version"] == "1.0.0"
    assert preserved["policy_version"] == "service-policy-v1"
    assert preserved["status"] == "invalidated"
    new_proposal = authenticated.post(
        "/api/proposals",
        headers=csrf(authenticated),
        json={
            "profile_id": "service-v1",
            "parameters": {
                "equipment_id": "EQ-PUMP-001",
                "issue_summary": "設定套用後建立的提案使用新的版本快照",
                "priority": "high",
                "maintenance_window": "",
                "risk_summary": "",
            },
        },
    ).json()["proposal"]
    assert new_proposal["profile_version"] == "1.0.1"
    assert new_proposal["required_approvals"] == 2
    assert new_proposal["retention_days"] == 1

    initialize_database(settings)
    _login_admin(authenticated)
    restarted = next(item for item in authenticated.get("/api/profiles").json()["items"] if item["profile_id"] == "service-v1")
    assert restarted["version"] == "1.0.1"
    assert restarted["effective_device_scope"] == ["EQ-FAN-002", "EQ-PUMP-001"]


def test_rollback_creates_new_draft_and_preserves_history(authenticated):
    create_user(authenticated, "rollback-reviewer", ["reviewer", "viewer"])
    version = _create_preview_submit(authenticated, _candidate(_snapshot(authenticated)))
    login(authenticated, "rollback-reviewer")
    _approve(authenticated, version)
    _login_admin(authenticated)
    authenticated.post(
        "/api/profile-configs/service-v1/apply",
        headers=csrf(authenticated),
        json={"revision": version["revision"]},
    )
    rollback = authenticated.post(
        "/api/profile-configs/service-v1/rollback",
        headers=csrf(authenticated),
        json={"revision": 1},
    )
    assert rollback.status_code == 200, rollback.text
    rollback_version = rollback.json()["version"]
    assert rollback_version["status"] == "draft"
    assert rollback_version["version"] == "1.0.2"
    assert rollback_version["snapshot"]["display_name"] == "維修服務團隊"
    history = authenticated.get("/api/profile-configs").json()["items"]
    assert {(item["version"], item["status"]) for item in history if item["profile_id"] == "service-v1"} == {
        ("1.0.0", "superseded"),
        ("1.0.1", "active"),
        ("1.0.2", "draft"),
    }


def test_profile_configuration_rejects_unknown_fields_and_tool_changes(authenticated):
    snapshot = _candidate(_snapshot(authenticated))
    snapshot["remote_url"] = "https://example.invalid/config.json"
    unknown = authenticated.post(
        "/api/profile-configs/service-v1/draft",
        headers=csrf(authenticated),
        json={"snapshot": snapshot},
    )
    assert unknown.status_code == 400

    snapshot.pop("remote_url")
    snapshot["settings"]["write_tool"] = "run_arbitrary_command"
    unsafe = authenticated.post(
        "/api/profile-configs/service-v1/draft",
        headers=csrf(authenticated),
        json={"snapshot": snapshot},
    )
    assert unsafe.status_code == 409
    assert unsafe.json()["error"]["code"] == "CONFIG_SAFETY_FLOOR"


def test_admin_can_cancel_in_progress_candidate_and_create_next_draft(authenticated):
    first = authenticated.post(
        "/api/profile-configs/service-v1/draft",
        headers=csrf(authenticated),
        json={"snapshot": _candidate(_snapshot(authenticated))},
    )
    assert first.status_code == 200, first.text
    revision = first.json()["version"]["revision"]

    cancelled = authenticated.post(
        "/api/profile-configs/service-v1/cancel",
        headers=csrf(authenticated),
        json={"revision": revision},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["version"]["status"] == "cancelled"

    next_snapshot = _candidate(_snapshot(authenticated))
    next_snapshot["display_name"] = "下一版可靠度團隊"
    second = authenticated.post(
        "/api/profile-configs/service-v1/draft",
        headers=csrf(authenticated),
        json={"snapshot": next_snapshot},
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"]["revision"] == revision + 1


def test_profile_config_tables_do_not_store_secrets_or_external_payloads(settings, authenticated):
    with connect(settings) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(profile_config_versions)")}
    assert "snapshot_json" in columns
    assert not {"api_key", "token", "secret", "remote_ref"}.intersection(columns)
