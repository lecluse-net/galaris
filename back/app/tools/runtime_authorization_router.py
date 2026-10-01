"""Runtime producers may request/consume one action, never answer as a human."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.authorize import independent_auth
from core.database import get_db_session

from .authorization import AuthorizationAction, AuthorizationClosed, AuthorizationRequired, claim_action, finish_action
from .authorization_models import ActionAuthorization, RuntimeRunGrant
from .runtime_authorization import resolve_runtime_run_grant, runtime_authorization_configuration
from .runtime_principals import RuntimePrincipal, runtime_principal_port

router = APIRouter(prefix="/runtime-authorizations", tags=["runtime-authorizations"])


async def runtime_scope(request: Request) -> tuple[RuntimePrincipal, RuntimeRunGrant]:
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    credential = request.headers.get("X-Galaris-Run-Context", "")
    if not bearer or not credential:
        raise HTTPException(401, "A runtime principal and a server-issued run context are required")
    async with get_db_session():
        principal = await runtime_principal_port().authenticate(bearer)
        if principal is None:
            raise HTTPException(401, "Invalid runtime principal")
        try:
            grant = await resolve_runtime_run_grant(credential, principal=principal)
        except PermissionError as exc:
            raise HTTPException(403, "Invalid or expired runtime run context") from exc
    return principal, grant


class RuntimeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    callback_key: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=255)
    session: str = Field(min_length=1, max_length=300)
    arguments: dict[str, Any]


@router.post("")
@independent_auth(reason="Managed runtime principal and server-issued run-bound credential")
async def request_action(request: Request, data: RuntimeAction) -> dict[str, Any]:
    _, grant = await runtime_scope(request)
    action = AuthorizationAction(agent_id=grant.agent_id, runtime=grant.runtime, context_key=grant.context_key,
        source="runtime", callback_key=f"{grant.id}:{data.session}:{data.callback_key}", name=data.name,
        runtime_grant_id=grant.id,
        arguments=data.arguments, configuration={"grant": str(grant.id), "session": data.session,
            "target": grant.target_ref, "revision": grant.target_revision}, preview=f"{grant.runtime}: {data.name}")
    try:
        identifier = await claim_action(action)
    except AuthorizationRequired as pending:
        return {"status": "pending", "request_id": str(pending.request_id)}
    except AuthorizationClosed as closed:
        return {"status": closed.status, "request_id": str(closed.request_id), "claimed": False}
    return {"status": "executing", "request_id": str(identifier), "claimed": True}


class RuntimeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    outcome: str = Field(pattern="^(completed|failed|outcome_unknown)$")
    receipt: dict[str, Any] = Field(default_factory=dict[str, Any])


@router.get("/context")
@independent_auth(reason="Validate the server-issued context before any managed model or SDK work")
async def context_status(request: Request) -> dict[str, Any]:
    _, grant = await runtime_scope(request)
    async with get_db_session():
        configuration = await runtime_authorization_configuration(grant.agent_id, grant.runtime)
    return {"active": True, "configuration": configuration}


@router.get("/{identifier}")
@independent_auth(reason="Read-only one-action continuation within the issued runtime context")
async def action_status(request: Request, identifier: UUID) -> dict[str, str]:
    _, grant = await runtime_scope(request)
    async with get_db_session() as db:
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == identifier,
            ActionAuthorization.agent_id == grant.agent_id, ActionAuthorization.runtime_grant_id == grant.id,
            ActionAuthorization.context_key == grant.context_key))
        if row is None:
            raise HTTPException(404, "Authorization not found")
        return {"status": row.status}


@router.post("/receipt")
@independent_auth(reason="Runtime receipts are restricted to their issued context and principal")
async def action_receipt(request: Request, data: RuntimeReceipt) -> dict[str, bool]:
    _, grant = await runtime_scope(request)
    async with get_db_session() as db:
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == data.request_id,
            ActionAuthorization.agent_id == grant.agent_id, ActionAuthorization.runtime == grant.runtime,
            ActionAuthorization.context_key == grant.context_key, ActionAuthorization.source == "runtime"))
        if row is not None and row.runtime_grant_id != grant.id:
            row = None
        if row is None:
            raise HTTPException(404, "Authorization not found")
    from typing import Literal, cast
    await finish_action(data.request_id, outcome=cast(Literal["completed", "failed", "outcome_unknown"], data.outcome), receipt=data.receipt)
    return {"recorded": True}
