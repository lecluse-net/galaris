"""Opaque server-issued authority for a concrete managed runtime run.

A reusable agent token identifies a principal. It never selects an active Task or run.
The orchestrator issues the extra credential and owns its lifetime and replacement.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from uuid import UUID
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select, update

from app.agent import AgentRunRequest, get_agent_record, configured_harness_selection
from core.database import get_db_session
from core.util import get_encryption_service

from .authorization import fingerprint, authorization_context_snapshot
from .authorization_models import RuntimeRunGrant
from .runtime_principals import RuntimePrincipal, runtime_principal_port

_runtime_configurations: dict[str, Callable[[int], Awaitable[dict[str, Any]]]] = {}


def register_runtime_authorization_configuration(runtime: str, callback: Callable[[int], Awaitable[dict[str, Any]]]) -> None:
    _runtime_configurations[runtime] = callback


async def runtime_authorization_configuration(agent_id: int, runtime: str) -> dict[str, Any]:
    callback = _runtime_configurations.get(runtime)
    return await callback(agent_id) if callback else {}


async def runtime_grant_snapshot(agent_id: int, runtime: str, context: str) -> dict[str, Any]:
    return {"context": await authorization_context_snapshot(agent_id, context),
        "configuration": await runtime_authorization_configuration(agent_id, runtime)}


def _run_context(request: AgentRunRequest) -> str:
    if request.task_id:
        return f"task:{request.task_id}"
    round_key = request.messaging_context.get("round_id") or request.task_data.get("conversation_round_id")
    if round_key:
        session = request.messaging_context.get("voice_session_id") or request.task_data.get("voice_session_id")
        return f"voice:{session}:round:{round_key}" if session else f"round:{round_key}"
    return f"principal:runtime:{request.run_id}"


async def issue_runtime_run_grant(request: AgentRunRequest) -> str:
    if request.target is None or not request.target.target_ref.startswith("harness:"):
        raise PermissionError("A frozen managed Harness target is required")
    context = _run_context(request)
    async with get_db_session() as db:
        from app.agent import authorization_policy
        await authorization_policy(request.agent_id, lock=True)
        agent = await get_agent_record(request.agent_id)
        selected = await configured_harness_selection(agent) if agent else None
        if selected is None or selected.status != "ready" or selected.metadata.get("authorization_enabled") is not True or request.target.target_ref != f"harness:{selected.id}" or request.target.revision != str(selected.revision):
            raise PermissionError("The frozen runtime assignment changed")
        token = await runtime_principal_port().for_agent(request.agent_id)
        if token is None or not token.enabled:
            raise PermissionError("A managed runtime principal is required")
        await db.execute(update(RuntimeRunGrant).where(RuntimeRunGrant.agent_id == request.agent_id,
            RuntimeRunGrant.context_key == context, RuntimeRunGrant.active.is_(True)).values(active=False))
        from uuid import uuid4
        identifier = uuid4()
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        credential = get_encryption_service().encrypt(f"runtime-run:{identifier}:{uuid4()}")
        db.add(RuntimeRunGrant(id=identifier, agent_id=request.agent_id, token_id=token.id,
            credential_hash=fingerprint(credential), actor_key=hashlib.sha256(credential.encode()).hexdigest(),
            context_fingerprint=fingerprint(await runtime_grant_snapshot(request.agent_id, request.target.provider_code, context)), runtime=request.target.provider_code,
            context_key=context, run_key=request.run_id, attempt_key=request.attempt_id,
            target_ref=request.target.target_ref, target_revision=request.target.revision,
            expires_at=expires))
        await db.commit()
    return credential


async def resolve_runtime_run_grant(credential: str, *, principal: RuntimePrincipal) -> RuntimeRunGrant:
    if not principal.enabled:
        raise PermissionError("The runtime principal is disabled")
    async with get_db_session() as db:
        row = await db.scalar(select(RuntimeRunGrant).where(
            RuntimeRunGrant.credential_hash == fingerprint(credential), RuntimeRunGrant.token_id == principal.id,
            RuntimeRunGrant.agent_id == principal.agent_id, RuntimeRunGrant.active.is_(True),
            RuntimeRunGrant.expires_at > datetime.now(timezone.utc)))
        if row is None:
            raise PermissionError("Invalid, stale or foreign runtime run context")
        agent = await get_agent_record(row.agent_id)
        target = await configured_harness_selection(agent) if agent is not None else None
        if target is None or target.status != "ready" or target.metadata.get("authorization_enabled") is not True or row.target_ref != f"harness:{target.id}" or row.target_revision != str(target.revision):
            raise PermissionError("The runtime assignment changed")
        if row.context_fingerprint != fingerprint(await runtime_grant_snapshot(row.agent_id, row.runtime, row.context_key)):
            raise PermissionError("The runtime objective or context changed")
        return row


async def revoke_runtime_run_grant(run_id: UUID) -> RuntimeRunGrant | None:
    """Revoke before asking the runtime to stop; a lost reply cannot authorize more effects."""
    from .authorization_models import ActionAuthorization
    async with get_db_session() as db:
        row = await db.scalar(select(RuntimeRunGrant).where(RuntimeRunGrant.run_key == run_id).with_for_update())
        if row is None:
            return None
        row.active = False
        now = datetime.now(timezone.utc)
        await db.execute(update(ActionAuthorization).where(ActionAuthorization.runtime_grant_id == row.id,
            ActionAuthorization.status.in_(("pending", "approved"))).values(status="invalidated",
                encrypted_arguments=None, notification_due_at=None, wake_due_at=now, finished_at=now))
        await db.commit()
        return row


async def close_runtime_run_grant(credential: str) -> None:
    async with get_db_session() as db:
        await db.execute(update(RuntimeRunGrant).where(RuntimeRunGrant.credential_hash == fingerprint(credential)).values(active=False))
        await db.commit()


async def renew_runtime_run_grant(credential: str, request: AgentRunRequest) -> str:
    """Transfer a suspended runtime to the new orchestrator attempt, without widening it."""
    async with get_db_session() as db:
        from app.agent import authorization_policy
        await authorization_policy(request.agent_id, lock=True)
        row = await db.scalar(select(RuntimeRunGrant).where(RuntimeRunGrant.credential_hash == fingerprint(credential),
            RuntimeRunGrant.agent_id == request.agent_id, RuntimeRunGrant.active.is_(True)).with_for_update())
        if row is None or row.expires_at <= datetime.now(timezone.utc) or request.target is None:
            raise PermissionError("The suspended runtime authority expired")
        if row.target_ref != request.target.target_ref or row.target_revision != request.target.revision:
            raise PermissionError("The suspended runtime target changed")
        principal = await runtime_principal_port().by_key(row.token_id)
        agent = await get_agent_record(row.agent_id)
        selected = await configured_harness_selection(agent) if agent else None
        if principal is None or not principal.enabled or selected is None or selected.status != "ready" or selected.metadata.get("authorization_enabled") is not True or row.target_ref != f"harness:{selected.id}" or row.target_revision != str(selected.revision):
            raise PermissionError("The suspended runtime assignment was revoked")
        expected_context = _run_context(request)
        if expected_context.startswith("principal:runtime:") and request.resume_checkpoint is not None and request.resume_checkpoint.runtime_run_id == row.actor_key:
            expected_context = row.context_key
        if row.context_key != expected_context or row.context_fingerprint != fingerprint(await runtime_grant_snapshot(row.agent_id, row.runtime, row.context_key)):
            raise PermissionError("The suspended runtime context changed")
        row.run_key, row.attempt_key = request.run_id, request.attempt_id
        await db.commit()
    return credential
