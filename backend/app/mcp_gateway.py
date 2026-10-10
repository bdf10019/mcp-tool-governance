from __future__ import annotations

import os
import sys
from typing import Any

from mcp import Client, StdioServerParameters

from .config import Settings
from .db import append_trace, connect
from .errors import AppError


META_KEY = "local.toolworkbench/authContext"
KNOWN_REMOTE_CODES = {
    "AUTH_CONTEXT_MISSING",
    "AUTH_CONTEXT_REPLAYED",
    "AUTH_CONTEXT_EXPIRED",
    "AUTH_CONTEXT_MISMATCH",
    "ACTOR_REVOKED",
    "FORBIDDEN_SCOPE",
    "PROPOSAL_NOT_APPROVED",
    "APPROVAL_STALE",
    "DATA_VERSION_CONFLICT",
    "POLICY_VERSION_CONFLICT",
    "IDEMPOTENCY_CONFLICT",
    "MAINTENANCE_CONFIRMATION_REQUIRED",
}


class RemoteToolError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _remote_error_code(result: Any) -> str:
    message = " ".join(
        str(getattr(item, "text", "")) for item in getattr(result, "content", [])
    )
    for code in KNOWN_REMOTE_CODES | {"MCP_TEST_RESPONSE_LOST_AFTER_COMMIT"}:
        if code in message:
            return code
    return "REMOTE_TOOL_ERROR"


def _server_parameters(settings: Settings) -> StdioServerParameters:
    environment = os.environ.copy()
    environment.update(
        {
            "MCP_APP_ENV_KIND": settings.environment_kind,
            "MCP_APP_DB_PATH": str(settings.db_path),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.mcp_server.server"],
        cwd=settings.root,
        env=environment,
        encoding="utf-8",
        encoding_error_handler="strict",
    )


async def discover_tools(settings: Settings) -> dict[str, Any]:
    try:
        async with Client(
            _server_parameters(settings),
            read_timeout_seconds=settings.mcp_timeout_seconds,
            raise_exceptions=True,
        ) as client:
            response = await client.list_tools(cache_mode="refresh")
            return {
                "protocol_version": client.protocol_version,
                "server": "fixed-local-stdio",
                "tools": [tool.model_dump(by_alias=True, exclude_none=True) for tool in response.tools],
            }
    except Exception as exc:
        raise AppError(
            "MCP_UNAVAILABLE",
            "MCP Server 無法完成工具探索",
            status_code=503,
            recoverable=True,
            next_action="確認專用環境與 Server 後重試",
        ) from exc


async def call_tool(
    settings: Settings,
    *,
    actor_id: str,
    profile_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    auth_context: str,
    trace_id: str,
) -> dict[str, Any]:
    with connect(settings) as conn:
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="mcp.call_started",
            status="running",
            tool_name=tool_name,
            actor_id=actor_id,
            profile_id=profile_id,
            summary={"transport": "stdio", "protocol": "auto"},
        )
    try:
        remote_error: str | None = None
        payload: dict[str, Any] | None = None
        async with Client(
            _server_parameters(settings),
            read_timeout_seconds=settings.mcp_timeout_seconds,
            raise_exceptions=False,
        ) as client:
            result = await client.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=settings.mcp_timeout_seconds,
                meta={META_KEY: auth_context},
            )
            if result.is_error:
                remote_error = _remote_error_code(result)
            else:
                payload = result.structured_content
                if payload is None:
                    raise RuntimeError("MCP tool omitted structured content")
                if isinstance(payload.get("_tool_error"), str):
                    remote_error = str(payload["_tool_error"])
            protocol_version = client.protocol_version
        if remote_error:
            raise RemoteToolError(remote_error)
        if payload is None:
            raise RuntimeError("MCP tool omitted structured content")
    except RemoteToolError as exc:
        is_write = tool_name == "create_maintenance_order"
        outcome_unknown = is_write and exc.code not in KNOWN_REMOTE_CODES
        with connect(settings) as conn:
            append_trace(
                conn,
                settings=settings,
                trace_id=trace_id,
                event_type="mcp.call_failed",
                status="failed",
                tool_name=tool_name,
                actor_id=actor_id,
                profile_id=profile_id,
                summary={
                    "reason_code": exc.code if exc.code in KNOWN_REMOTE_CODES else "REMOTE_RESPONSE_LOST",
                    "outcome": "unknown" if outcome_unknown else "definite_rejection",
                },
            )
        if outcome_unknown:
            raise AppError(
                "OUTCOME_UNKNOWN",
                "工單回應中斷；不要重新產生請求，請先查核原執行結果",
                status_code=409,
                recoverable=True,
                next_action="使用原提案的結果查核",
            ) from exc
        raise AppError(
            exc.code if exc.code in KNOWN_REMOTE_CODES else "MCP_CALL_FAILED",
            "工具拒絕了這次操作；請依錯誤狀態修正後再試",
            status_code=409 if is_write else 403,
            recoverable=True,
            next_action="查看提案版本、權限與 Trace",
        ) from exc
    except Exception as exc:
        is_write = tool_name == "create_maintenance_order"
        exception_text = str(exc)
        remote_code = next(
            (
                code
                for code in KNOWN_REMOTE_CODES | {"MCP_TEST_RESPONSE_LOST_AFTER_COMMIT"}
                if code in exception_text
            ),
            None,
        )
        outcome_unknown = is_write and remote_code not in KNOWN_REMOTE_CODES
        with connect(settings) as conn:
            append_trace(
                conn,
                settings=settings,
                trace_id=trace_id,
                event_type="mcp.call_failed",
                status="failed",
                tool_name=tool_name,
                actor_id=actor_id,
                profile_id=profile_id,
                summary={
                    "reason": remote_code or "MCP call failed or timed out",
                    "outcome": "unknown" if outcome_unknown else "definite_rejection" if remote_code else "unknown" if is_write else "no_write_expected",
                },
            )
        if remote_code in KNOWN_REMOTE_CODES:
            raise AppError(
                remote_code,
                "工具拒絕了這次操作；請依錯誤狀態修正後再試",
                status_code=409 if is_write else 403,
                recoverable=True,
                next_action="查看提案版本、權限與 Trace",
            ) from exc
        raise AppError(
            "OUTCOME_UNKNOWN" if is_write else "MCP_CALL_FAILED",
            "工單回應中斷；不要重新產生請求，請先查核原執行結果"
            if is_write
            else "工具呼叫失敗或逾時；未執行任何寫入",
            status_code=409 if is_write else 502,
            recoverable=True,
            next_action="使用原提案的結果查核" if is_write else "查看 Trace 後重試唯讀查詢",
        ) from exc
    with connect(settings) as conn:
        append_trace(
            conn,
            settings=settings,
            trace_id=trace_id,
            event_type="mcp.call_completed",
            status="success",
            tool_name=tool_name,
            actor_id=actor_id,
            profile_id=profile_id,
            summary={"protocol_version": protocol_version, "structured": True},
        )
    return dict(payload)

