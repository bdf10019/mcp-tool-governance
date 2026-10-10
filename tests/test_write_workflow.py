from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.app.db import connect
from tests.conftest import csrf


PASSWORD = "workflow-pass-1234"
ALL_SCOPES = ["EQ-PUMP-001", "EQ-FAN-002", "EQ-CONV-003", "EQ-CHILLER-004"]
ALL_PROFILES = ["service-v1", "asset-v1"]


def create_user(admin: TestClient, username: str, roles: list[str]) -> None:
    response = admin.post(
        "/api/admin/users",
        headers=csrf(admin),
        json={
            "username": username,
            "password": PASSWORD,
            "roles": roles,
            "device_scopes": ALL_SCOPES,
            "profile_ids": ALL_PROFILES,
        },
    )
    assert response.status_code == 200, response.text


def login(client: TestClient, username: str) -> None:
    response = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text


def seed_workflow_accounts(admin: TestClient) -> None:
    create_user(admin, "operator-one", ["operator", "viewer"])
    create_user(admin, "reviewer-one", ["reviewer", "viewer"])
    create_user(admin, "reviewer-two", ["reviewer", "viewer"])


def create_and_submit(client: TestClient, profile_id: str = "service-v1") -> dict:
    parameters = {
        "equipment_id": "EQ-PUMP-001",
        "issue_summary": "循環水泵振動持續偏高，需要安排停機檢查。",
        "priority": "high",
        "maintenance_window": "2026-09-26 09:00-11:00" if profile_id == "asset-v1" else "",
        "risk_summary": "持續運轉可能造成軸承損壞與非預期停機。" if profile_id == "asset-v1" else "",
    }
    created = client.post(
        "/api/proposals",
        headers=csrf(client),
        json={"profile_id": profile_id, "parameters": parameters},
    )
    assert created.status_code == 200, created.text
    proposal = created.json()["proposal"]
    submitted = client.post(
        f"/api/proposals/{proposal['proposal_id']}/submit",
        headers=csrf(client),
        json={"proposal_version": proposal["proposal_version"]},
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()["proposal"]


def approve(client: TestClient, proposal: dict, reviewer: str) -> dict:
    login(client, reviewer)
    response = client.post(
        f"/api/proposals/{proposal['proposal_id']}/review",
        headers=csrf(client),
        json={
            "proposal_version": proposal["proposal_version"],
            "decision": "approve",
            "reason": "已確認設備範圍、風險與維護內容一致。",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["proposal"]


def test_service_profile_single_approval_and_idempotent_order(authenticated):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated)
    approved = approve(authenticated, proposal, "reviewer-one")
    assert approved["status"] == "approved"

    login(authenticated, "operator-one")
    first = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert first.status_code == 200, first.text
    first_result = first.json()["result"]
    assert first_result["deduplicated"] is False

    second = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert second.status_code == 200, second.text
    assert second.json()["result"]["order_id"] == first_result["order_id"]
    assert second.json()["result"]["deduplicated"] is True
    orders = authenticated.get("/api/orders").json()["items"]
    assert [item["order_id"] for item in orders] == [first_result["order_id"]]


def test_asset_profile_requires_two_reviewers_and_maintenance_confirmation(authenticated):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated, "asset-v1")
    partial = approve(authenticated, proposal, "reviewer-one")
    assert partial["status"] == "partially_approved"

    login(authenticated, "operator-one")
    early = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": True},
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "PROPOSAL_NOT_APPROVED"

    approved = approve(authenticated, proposal, "reviewer-two")
    assert approved["status"] == "approved"
    login(authenticated, "operator-one")
    missing_confirmation = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert missing_confirmation.status_code == 409
    assert missing_confirmation.json()["error"]["code"] == "MAINTENANCE_CONFIRMATION_REQUIRED"
    executed = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": True},
    )
    assert executed.status_code == 200, executed.text


def test_self_review_and_admin_bypass_are_rejected(authenticated):
    create_user(authenticated, "hybrid-user", ["operator", "reviewer", "viewer"])
    login(authenticated, "hybrid-user")
    proposal = create_and_submit(authenticated)
    self_review = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/review",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "decision": "approve", "reason": "本人確認內容沒有問題，不應通過。"},
    )
    assert self_review.status_code == 403
    assert self_review.json()["error"]["code"] == "SELF_REVIEW_FORBIDDEN"

    login_response = authenticated.post(
        "/api/login",
        json={"username": "portfolio-admin", "password": "local-pass-1234"},
    )
    assert login_response.status_code == 200
    admin_review = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/review",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "decision": "approve", "reason": "管理者不應自動具有審核角色。"},
    )
    assert admin_review.status_code == 403
    assert admin_review.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_data_version_drift_blocks_write_after_approval(authenticated, settings):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated)
    approve(authenticated, proposal, "reviewer-one")
    with connect(settings) as conn:
        conn.execute("UPDATE equipment SET data_version='changed-after-approval' WHERE equipment_id='EQ-PUMP-001'")
    login(authenticated, "operator-one")
    response = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "DATA_VERSION_CONFLICT"
    with connect(settings) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM maintenance_orders").fetchone()["n"] == 0


def test_lost_write_response_recovers_without_duplicate(authenticated, monkeypatch):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated)
    approve(authenticated, proposal, "reviewer-one")
    login(authenticated, "operator-one")
    monkeypatch.setenv("MCP_TEST_LOSE_WRITE_RESPONSE", "1")
    response = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "OUTCOME_UNKNOWN"
    recovered = authenticated.get(
        f"/api/proposals/{proposal['proposal_id']}/recover",
        params={"proposal_version": 1},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["result"]["recovered"] is True
    assert recovered.json()["result"]["deduplicated"] is True


def test_parallel_execution_creates_exactly_one_order(authenticated, settings):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated)
    approve(authenticated, proposal, "reviewer-one")

    client_a = TestClient(authenticated.app)
    client_b = TestClient(authenticated.app)
    with client_a, client_b:
        login(client_a, "operator-one")
        login(client_b, "operator-one")

        def execute(client: TestClient):
            return client.post(
                f"/api/proposals/{proposal['proposal_id']}/execute",
                headers=csrf(client),
                json={"proposal_version": 1, "maintenance_confirmed": False},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(execute, [client_a, client_b]))
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
    order_ids = {response.json()["result"]["order_id"] for response in responses}
    assert len(order_ids) == 1
    assert sorted(response.json()["result"]["deduplicated"] for response in responses) == [False, True]
    with connect(settings) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM maintenance_orders").fetchone()["n"] == 1


def test_revising_approved_proposal_invalidates_old_approval(authenticated):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated)
    approve(authenticated, proposal, "reviewer-one")
    login(authenticated, "operator-one")
    revised = authenticated.put(
        f"/api/proposals/{proposal['proposal_id']}",
        headers=csrf(authenticated),
        json={
            "profile_id": "service-v1",
            "parameters": {
                "equipment_id": "EQ-PUMP-001",
                "issue_summary": "重新確認後發現振動範圍擴大，需要更新檢查內容。",
                "priority": "urgent",
                "maintenance_window": "",
                "risk_summary": "",
            },
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["proposal"]["proposal_version"] == 2
    assert revised.json()["proposal"]["status"] == "draft"
    stale = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "APPROVAL_STALE"


def test_reviewer_role_revocation_invalidates_previous_approval(authenticated, settings):
    seed_workflow_accounts(authenticated)
    login(authenticated, "operator-one")
    proposal = create_and_submit(authenticated)
    approve(authenticated, proposal, "reviewer-one")
    with connect(settings) as conn:
        conn.execute(
            "UPDATE users SET roles_json='[\"viewer\"]', session_epoch=session_epoch+1 WHERE username='reviewer-one'"
        )
    login(authenticated, "operator-one")
    response = authenticated.post(
        f"/api/proposals/{proposal['proposal_id']}/execute",
        headers=csrf(authenticated),
        json={"proposal_version": 1, "maintenance_confirmed": False},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_STALE"
