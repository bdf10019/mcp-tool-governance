from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from backend.app.config import Settings
from backend.app.errors import AppError
from backend.app.services import consume_auth_context, execute_read_query
from backend.app.workflow import execute_write_query


META_KEY = "local.toolworkbench/authContext"
mcp = MCPServer("tool-governance-readonly", instructions="三個唯讀設備維修工具；所有授權由產品後端簽發的一次性上下文決定。")


def _authorize(ctx: Context, tool_name: str, arguments: dict[str, Any]) -> tuple[Settings, dict[str, Any]]:
    settings = Settings.from_env()
    meta = ctx.request_context.meta or {}
    token = meta.get(META_KEY)
    if not isinstance(token, str) or not token:
        raise AppError("AUTH_CONTEXT_MISSING", "缺少授權上下文", status_code=403)
    auth = consume_auth_context(settings, token, tool_name, arguments)
    return settings, auth


@mcp.tool(
    name="get_equipment_status",
    title="設備狀態查詢",
    description="查詢授權範圍內單一設備的最新合成狀態與來源版本。",
)
def get_equipment_status(equipment_id: str, ctx: Context) -> dict[str, Any]:
    arguments = {"equipment_id": equipment_id}
    try:
        settings, auth = _authorize(ctx, "get_equipment_status", arguments)
        return execute_read_query(settings, auth, "get_equipment_status", arguments)
    except AppError as exc:
        return {"_tool_error": exc.code}


@mcp.tool(
    name="list_maintenance_history",
    title="維修紀錄查詢",
    description="依設備與可選日期範圍查詢維修歷史；最多回傳 50 筆。",
)
def list_maintenance_history(
    equipment_id: str,
    ctx: Context,
    date_from: str = "",
    date_to: str = "",
    cursor: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    arguments = {
        "equipment_id": equipment_id,
        "date_from": date_from,
        "date_to": date_to,
        "cursor": cursor,
        "limit": limit,
    }
    try:
        settings, auth = _authorize(ctx, "list_maintenance_history", arguments)
        return execute_read_query(settings, auth, "list_maintenance_history", arguments)
    except AppError as exc:
        return {"_tool_error": exc.code}


@mcp.tool(
    name="check_parts_stock",
    title="零件庫存與相容性",
    description="查詢本機合成庫存及指定設備的相容性依據；不預留、不扣庫存。",
)
def check_parts_stock(part_id: str, equipment_id: str, ctx: Context) -> dict[str, Any]:
    arguments = {"part_id": part_id, "equipment_id": equipment_id}
    try:
        settings, auth = _authorize(ctx, "check_parts_stock", arguments)
        return execute_read_query(settings, auth, "check_parts_stock", arguments)
    except AppError as exc:
        return {"_tool_error": exc.code}


@mcp.tool(
    name="create_maintenance_order",
    title="建立本機維修工單",
    description="只接受已核准提案與一次性授權；以交易和冪等鍵建立一筆本機合成工單。",
)
def create_maintenance_order(
    proposal_id: str,
    proposal_version: int,
    equipment_id: str,
    issue_summary: str,
    priority: str,
    idempotency_key: str,
    ctx: Context,
    maintenance_window: str = "",
    risk_summary: str = "",
    maintenance_confirmed: bool = False,
) -> dict[str, Any]:
    arguments = {
        "proposal_id": proposal_id,
        "proposal_version": proposal_version,
        "equipment_id": equipment_id,
        "issue_summary": issue_summary,
        "priority": priority,
        "maintenance_window": maintenance_window,
        "risk_summary": risk_summary,
        "maintenance_confirmed": maintenance_confirmed,
        "idempotency_key": idempotency_key,
    }
    try:
        settings, auth = _authorize(ctx, "create_maintenance_order", arguments)
        result = execute_write_query(settings, auth, arguments)
        if settings.environment_kind == "automated_test" and os.environ.get("MCP_TEST_LOSE_WRITE_RESPONSE") == "1":
            raise ToolError("MCP_TEST_RESPONSE_LOST_AFTER_COMMIT")
        return result
    except AppError as exc:
        return {"_tool_error": exc.code}


def main() -> None:
    Settings.from_env()
    mcp.run("stdio")


if __name__ == "__main__":
    main()

