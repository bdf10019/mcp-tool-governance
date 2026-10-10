from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Cookie, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .db import initialize_database
from .errors import AppError
from .governance import (
    backup_path,
    backup_preview,
    create_backup,
    list_backups,
    list_restores,
    migration_overview,
    restore_backup,
)
from .mcp_gateway import call_tool, discover_tools
from .profile_governance import (
    apply_profile_version,
    cancel_profile_draft,
    create_profile_draft,
    create_rollback_draft,
    list_profile_versions,
    preview_profile_draft,
    review_profile_draft,
    submit_profile_draft,
    validate_profile_draft,
)
from .services import (
    Actor,
    actor_from_session,
    authenticate,
    create_initial_admin,
    create_local_user,
    create_session,
    list_profiles,
    list_traces,
    list_users,
    logout,
    prepare_tool_call,
    reset_user_password,
    set_user_active,
    setup_status,
    update_user_access,
    verify_csrf,
)
from .workflow import (
    create_proposal,
    list_orders,
    list_proposals,
    prepare_execution_call,
    purge_expired_content,
    recover_execution,
    retention_summary,
    review_proposal,
    revise_proposal,
    submit_proposal,
)


SESSION_COOKIE = "mcp_session"
CSRF_COOKIE = "mcp_csrf"


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=200)


class ToolInvocation(BaseModel):
    profile_id: str
    arguments: dict[str, Any]


class LocalUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=200)
    roles: list[str]
    device_scopes: list[str]
    profile_ids: list[str]


class AccountStatusInput(BaseModel):
    active: bool


class PasswordResetInput(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class AccessUpdateInput(BaseModel):
    roles: list[str]
    device_scopes: list[str]
    profile_ids: list[str]


class ProposalInput(BaseModel):
    profile_id: str
    parameters: dict[str, Any]
    retention_days: int | None = None


class ProposalVersion(BaseModel):
    proposal_version: int = Field(ge=1)


class ReviewInput(ProposalVersion):
    decision: str
    reason: str = Field(min_length=8, max_length=1000)


class ExecutionInput(ProposalVersion):
    maintenance_confirmed: bool = False


class ProfileDraftInput(BaseModel):
    snapshot: dict[str, Any]


class ProfileRevisionInput(BaseModel):
    revision: int = Field(ge=1)


class ProfileConfigReviewInput(ProfileRevisionInput):
    decision: str
    reason: str = Field(min_length=8, max_length=1000)


class GovernanceConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=1, max_length=80)


class RestoreInput(GovernanceConfirmation):
    backup_id: str = Field(pattern=r"^BKP-[A-F0-9]{12}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = (settings or Settings.from_env()).validated()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(active_settings)
        purge_expired_content(active_settings)
        yield

    app = FastAPI(title="MCP 工具整合與授權治理", version="0.5.0", lifespan=lifespan)
    app.state.settings = active_settings

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.payload(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "輸入格式不正確",
                    "recoverable": True,
                    "details": exc.errors(),
                }
            },
            status_code=422,
        )

    def current_actor(mcp_session: Annotated[str | None, Cookie()] = None) -> Actor:
        return actor_from_session(active_settings, mcp_session)

    def csrf_guard(
        mcp_session: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> None:
        verify_csrf(active_settings, mcp_session, x_csrf_token)

    def set_auth_cookies(response: Response, session_token: str, csrf_token: str, max_age: int) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            max_age=max_age,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token,
            max_age=max_age,
            httponly=False,
            secure=False,
            samesite="strict",
            path="/",
        )

    @app.get("/api/setup/status")
    async def api_setup_status() -> dict[str, bool]:
        return setup_status(active_settings)

    @app.post("/api/setup")
    async def api_setup(payload: Credentials, response: Response) -> dict[str, Any]:
        actor = create_initial_admin(active_settings, payload.username, payload.password)
        session_token, csrf_token, expires_at = create_session(active_settings, actor)
        set_auth_cookies(response, session_token, csrf_token, active_settings.session_seconds)
        return {"actor": actor.public(), "expires_at": expires_at}

    @app.post("/api/login")
    async def api_login(payload: Credentials, response: Response) -> dict[str, Any]:
        actor = authenticate(active_settings, payload.username, payload.password)
        session_token, csrf_token, expires_at = create_session(active_settings, actor)
        set_auth_cookies(response, session_token, csrf_token, active_settings.session_seconds)
        return {"actor": actor.public(), "expires_at": expires_at}

    @app.post("/api/logout", dependencies=[Depends(csrf_guard)])
    async def api_logout(
        response: Response,
        mcp_session: Annotated[str | None, Cookie()] = None,
    ) -> dict[str, bool]:
        logout(active_settings, mcp_session)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    async def api_me(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"actor": actor.public()}

    @app.get("/api/health")
    async def api_health(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        discovery = await discover_tools(active_settings)
        return {
            "status": "healthy",
            "environment_kind": active_settings.environment_kind,
            "environment_id": active_settings.environment_id,
            "actor_id": actor.user_id,
            "mcp": {
                "transport": "stdio",
                "protocol_version": discovery["protocol_version"],
                "tool_count": len(discovery["tools"]),
            },
        }

    @app.get("/api/profiles")
    async def api_profiles(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_profiles(active_settings, actor)}

    @app.get("/api/admin/users")
    async def api_users(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_users(active_settings, actor)}

    @app.post("/api/admin/users", dependencies=[Depends(csrf_guard)])
    async def api_create_user(
        payload: LocalUserCreate,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {
            "user": create_local_user(
                active_settings,
                actor,
                username=payload.username,
                password=payload.password,
                roles=payload.roles,
                device_scopes=payload.device_scopes,
                profile_ids=payload.profile_ids,
            )
        }

    @app.patch("/api/admin/users/{user_id}/status", dependencies=[Depends(csrf_guard)])
    async def api_set_user_status(
        user_id: str,
        payload: AccountStatusInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"user": set_user_active(active_settings, actor, user_id, payload.active)}

    @app.post("/api/admin/users/{user_id}/password-reset", dependencies=[Depends(csrf_guard)])
    async def api_reset_user_password(
        user_id: str,
        payload: PasswordResetInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return reset_user_password(active_settings, actor, user_id, payload.password)

    @app.put("/api/admin/users/{user_id}/access", dependencies=[Depends(csrf_guard)])
    async def api_update_user_access(
        user_id: str,
        payload: AccessUpdateInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {
            "user": update_user_access(
                active_settings,
                actor,
                user_id,
                roles=payload.roles,
                device_scopes=payload.device_scopes,
                profile_ids=payload.profile_ids,
            )
        }

    @app.get("/api/admin/retention")
    async def api_retention_summary(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return retention_summary(active_settings, actor)

    @app.post("/api/admin/retention/purge", dependencies=[Depends(csrf_guard)])
    async def api_purge_retention(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return purge_expired_content(active_settings, actor)

    @app.get("/api/admin/governance/migrations")
    async def api_migration_overview(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return migration_overview(active_settings, actor)

    @app.get("/api/admin/governance/backup-preview")
    async def api_backup_preview(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return backup_preview(active_settings, actor)

    @app.get("/api/admin/governance/backups")
    async def api_backups(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_backups(active_settings, actor)}

    @app.post("/api/admin/governance/backups", dependencies=[Depends(csrf_guard)])
    async def api_create_backup(
        payload: GovernanceConfirmation,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"backup": create_backup(active_settings, actor, payload.confirmation)}

    @app.get("/api/admin/governance/backups/{backup_id}/download")
    async def api_download_backup(
        backup_id: str,
        actor: Actor = Depends(current_actor),
    ) -> FileResponse:
        path = backup_path(active_settings, actor, backup_id)
        return FileResponse(path, media_type="application/json", filename=path.name)

    @app.get("/api/admin/governance/restores")
    async def api_restores(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_restores(active_settings, actor)}

    @app.post("/api/admin/governance/restores", dependencies=[Depends(csrf_guard)])
    async def api_restore_backup(
        payload: RestoreInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {
            "receipt": restore_backup(
                active_settings,
                actor,
                payload.backup_id,
                payload.confirmation,
            )
        }

    @app.get("/api/profile-configs")
    async def api_profile_versions(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_profile_versions(active_settings, actor)}

    @app.post("/api/profile-configs/{profile_id}/draft", dependencies=[Depends(csrf_guard)])
    async def api_create_profile_draft(
        profile_id: str,
        payload: ProfileDraftInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": create_profile_draft(active_settings, actor, profile_id, payload.snapshot)}

    @app.post("/api/profile-configs/{profile_id}/preview", dependencies=[Depends(csrf_guard)])
    async def api_preview_profile_draft(
        profile_id: str,
        payload: ProfileRevisionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": preview_profile_draft(active_settings, actor, profile_id, payload.revision)}

    @app.post("/api/profile-configs/{profile_id}/validate", dependencies=[Depends(csrf_guard)])
    async def api_validate_profile_draft(
        profile_id: str,
        payload: ProfileRevisionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": validate_profile_draft(active_settings, actor, profile_id, payload.revision)}

    @app.post("/api/profile-configs/{profile_id}/submit", dependencies=[Depends(csrf_guard)])
    async def api_submit_profile_draft(
        profile_id: str,
        payload: ProfileRevisionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": submit_profile_draft(active_settings, actor, profile_id, payload.revision)}

    @app.post("/api/profile-configs/{profile_id}/cancel", dependencies=[Depends(csrf_guard)])
    async def api_cancel_profile_draft(
        profile_id: str,
        payload: ProfileRevisionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": cancel_profile_draft(active_settings, actor, profile_id, payload.revision)}

    @app.post("/api/profile-configs/{profile_id}/review", dependencies=[Depends(csrf_guard)])
    async def api_review_profile_draft(
        profile_id: str,
        payload: ProfileConfigReviewInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {
            "version": review_profile_draft(
                active_settings,
                actor,
                profile_id,
                payload.revision,
                payload.decision,
                payload.reason,
            )
        }

    @app.post("/api/profile-configs/{profile_id}/apply", dependencies=[Depends(csrf_guard)])
    async def api_apply_profile_version(
        profile_id: str,
        payload: ProfileRevisionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": apply_profile_version(active_settings, actor, profile_id, payload.revision)}

    @app.post("/api/profile-configs/{profile_id}/rollback", dependencies=[Depends(csrf_guard)])
    async def api_create_rollback_draft(
        profile_id: str,
        payload: ProfileRevisionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"version": create_rollback_draft(active_settings, actor, profile_id, payload.revision)}

    @app.get("/api/tools")
    async def api_tools(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        discovery = await discover_tools(active_settings)
        return {
            "protocol_version": discovery["protocol_version"],
            "transport": "stdio",
            "items": discovery["tools"],
            "actor_roles": list(actor.roles),
        }

    @app.post("/api/tools/{tool_name}/invoke", dependencies=[Depends(csrf_guard)])
    async def api_invoke(
        tool_name: str,
        payload: ToolInvocation,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        auth_context, trace_id, arguments = prepare_tool_call(
            active_settings, actor, payload.profile_id, tool_name, payload.arguments
        )
        result = await call_tool(
            active_settings,
            actor_id=actor.user_id,
            profile_id=payload.profile_id,
            tool_name=tool_name,
            arguments=arguments,
            auth_context=auth_context,
            trace_id=trace_id,
        )
        return {"trace_id": trace_id, "result": result}

    @app.get("/api/traces")
    async def api_traces(
        actor: Actor = Depends(current_actor),
        limit: int = 80,
    ) -> dict[str, Any]:
        return {"items": list_traces(active_settings, actor, limit)}

    @app.get("/api/proposals")
    async def api_proposals(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_proposals(active_settings, actor)}

    @app.post("/api/proposals", dependencies=[Depends(csrf_guard)])
    async def api_create_proposal(
        payload: ProposalInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {
            "proposal": create_proposal(
                active_settings,
                actor,
                payload.profile_id,
                payload.parameters,
                payload.retention_days,
            )
        }

    @app.put("/api/proposals/{proposal_id}", dependencies=[Depends(csrf_guard)])
    async def api_revise_proposal(
        proposal_id: str,
        payload: ProposalInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"proposal": revise_proposal(active_settings, actor, proposal_id, payload.parameters)}

    @app.post("/api/proposals/{proposal_id}/submit", dependencies=[Depends(csrf_guard)])
    async def api_submit_proposal(
        proposal_id: str,
        payload: ProposalVersion,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"proposal": submit_proposal(active_settings, actor, proposal_id, payload.proposal_version)}

    @app.post("/api/proposals/{proposal_id}/review", dependencies=[Depends(csrf_guard)])
    async def api_review_proposal(
        proposal_id: str,
        payload: ReviewInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {
            "proposal": review_proposal(
                active_settings,
                actor,
                proposal_id,
                payload.proposal_version,
                payload.decision,
                payload.reason,
            )
        }

    @app.post("/api/proposals/{proposal_id}/execute", dependencies=[Depends(csrf_guard)])
    async def api_execute_proposal(
        proposal_id: str,
        payload: ExecutionInput,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        auth_context, trace_id, profile_id, arguments = prepare_execution_call(
            active_settings,
            actor,
            proposal_id,
            payload.proposal_version,
            payload.maintenance_confirmed,
        )
        result = await call_tool(
            active_settings,
            actor_id=actor.user_id,
            profile_id=profile_id,
            tool_name="create_maintenance_order",
            arguments=arguments,
            auth_context=auth_context,
            trace_id=trace_id,
        )
        return {"trace_id": trace_id, "result": result}

    @app.get("/api/proposals/{proposal_id}/recover")
    async def api_recover_execution(
        proposal_id: str,
        proposal_version: int,
        actor: Actor = Depends(current_actor),
    ) -> dict[str, Any]:
        return {"result": recover_execution(active_settings, actor, proposal_id, proposal_version)}

    @app.get("/api/orders")
    async def api_orders(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        return {"items": list_orders(active_settings, actor)}

    frontend_dist = active_settings.root / "frontend" / "dist"
    if frontend_dist.exists():
        assets = frontend_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str) -> FileResponse:
            candidate = (frontend_dist / full_path).resolve()
            if full_path and candidate.is_file() and frontend_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()

