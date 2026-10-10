from __future__ import annotations

import asyncio
import sys
from dataclasses import replace

import pytest

from backend.app.errors import AppError
from backend.app import mcp_gateway
from backend.app.mcp_gateway import call_tool
from mcp import StdioServerParameters
from backend.app.services import actor_from_session, prepare_tool_call
from tests.conftest import csrf


def test_real_mcp_discovery_returns_three_read_and_one_write_tool(authenticated):
    response = authenticated.get("/api/tools")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["protocol_version"] == "2026-07-28"
    assert payload["transport"] == "stdio"
    assert {item["name"] for item in payload["items"]} == {
        "get_equipment_status",
        "list_maintenance_history",
        "check_parts_stock",
        "create_maintenance_order",
    }


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_key"),
    [
        ("get_equipment_status", {"equipment_id": "EQ-PUMP-001"}, "status"),
        ("list_maintenance_history", {"equipment_id": "EQ-PUMP-001", "limit": 10}, "items"),
        ("check_parts_stock", {"equipment_id": "EQ-PUMP-001", "part_id": "PT-BRG-6204"}, "compatible"),
    ],
)
def test_three_read_tools_use_real_stdio_mcp(authenticated, tool_name, arguments, expected_key):
    response = authenticated.post(
        f"/api/tools/{tool_name}/invoke",
        headers=csrf(authenticated),
        json={"profile_id": "service-v1", "arguments": arguments},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trace_id"].startswith("TRC-")
    assert expected_key in payload["result"]
    assert payload["result"]["environment_kind"] == "automated_test"
    assert payload["result"]["profile_id"] == "service-v1"
    if "provenance" in payload["result"]:
        assert payload["result"]["provenance"]["source_kind"] == "synthetic_seed"


def test_profile_scope_cannot_expand_actor_access(authenticated):
    response = authenticated.post(
        "/api/tools/get_equipment_status/invoke",
        headers=csrf(authenticated),
        json={"profile_id": "service-v1", "arguments": {"equipment_id": "EQ-CHILLER-004"}},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND_OR_FORBIDDEN"


def test_forged_identity_fields_are_rejected(authenticated):
    response = authenticated.post(
        "/api/tools/get_equipment_status/invoke",
        headers=csrf(authenticated),
        json={
            "profile_id": "service-v1",
            "arguments": {
                "equipment_id": "EQ-PUMP-001",
                "role": "admin",
                "approved": True,
                "user_id": "attacker",
            },
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_auth_context_is_single_use(authenticated, settings):
    actor = actor_from_session(settings, authenticated.cookies.get("mcp_session"))
    arguments = {"equipment_id": "EQ-PUMP-001"}
    token, trace_id, normalized = prepare_tool_call(
        settings, actor, "service-v1", "get_equipment_status", arguments
    )
    first = asyncio.run(
        call_tool(
            settings,
            actor_id=actor.user_id,
            profile_id="service-v1",
            tool_name="get_equipment_status",
            arguments=normalized,
            auth_context=token,
            trace_id=trace_id,
        )
    )
    assert first["equipment_id"] == "EQ-PUMP-001"
    with pytest.raises(AppError) as caught:
        asyncio.run(
            call_tool(
                settings,
                actor_id=actor.user_id,
                profile_id="service-v1",
                tool_name="get_equipment_status",
                arguments=normalized,
                auth_context=token,
                trace_id=trace_id,
            )
        )
    assert caught.value.code == "AUTH_CONTEXT_REPLAYED"


def test_trace_exposes_stages_without_secret(authenticated):
    invoked = authenticated.post(
        "/api/tools/get_equipment_status/invoke",
        headers=csrf(authenticated),
        json={"profile_id": "asset-v1", "arguments": {"equipment_id": "EQ-PUMP-001"}},
    )
    trace_id = invoked.json()["trace_id"]
    traces = authenticated.get("/api/traces").json()["items"]
    selected = [item for item in traces if item["trace_id"] == trace_id]
    assert {item["event_type"] for item in selected} >= {
        "policy.authorized",
        "mcp.call_started",
        "mcp.auth_context_consumed",
        "business.read_completed",
        "mcp.call_completed",
    }
    assert "authContext" not in str(selected)


def test_gateway_maps_stdio_timeout_to_recoverable_error(authenticated, settings, monkeypatch):
    actor = actor_from_session(settings, authenticated.cookies.get("mcp_session"))
    arguments = {"equipment_id": "EQ-PUMP-001"}
    token, trace_id, normalized = prepare_tool_call(
        settings, actor, "service-v1", "get_equipment_status", arguments
    )
    short_timeout = replace(settings, mcp_timeout_seconds=0.05)

    def slow_server_parameters(_settings):
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "tests.slow_mcp_server"],
            cwd=settings.root,
            encoding="utf-8",
        )

    monkeypatch.setattr(mcp_gateway, "_server_parameters", slow_server_parameters)
    with pytest.raises(AppError) as caught:
        asyncio.run(
            call_tool(
                short_timeout,
                actor_id=actor.user_id,
                profile_id="service-v1",
                tool_name="get_equipment_status",
                arguments=normalized,
                auth_context=token,
                trace_id=trace_id,
            )
        )
    assert caught.value.code == "MCP_CALL_FAILED"
    assert caught.value.recoverable is True

