"""MCP admission and ownership for domain-owned media generations."""
import hashlib
import json
import secrets
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.llm import LLMExecutionAuthority, current_execution_authority
from app.tools import McpToolContext
from app.tools.facade import finish_action, register_deferred_dispatch
from core.database import get_db
from core.user import get_current_user_id
from .models import MediaGeneration
from .generation_execution import MediaGenerationExecutor
from .generation_store import snapshot
from .service import authorize

async def start(ctx: McpToolContext, input_data: dict[str, Any], invocation_key: str | None) -> dict[str, Any]:
    if invocation_key is not None and (not invocation_key.strip() or len(invocation_key) > 255):
        raise ValueError("Provide an invocation_key of 1–255 characters.")
    digest = hashlib.sha256(json.dumps(input_data, sort_keys=True).encode()).hexdigest()
    key = f"{input_data['request']['operation']}:{invocation_key}" if invocation_key else None
    db = get_db()
    if invocation_key:
        existing = await db.scalar(select(MediaGeneration).where(
            MediaGeneration.agent_id == ctx.agent_id, MediaGeneration.idempotency_key == key))
        if existing is not None:
            if existing.input.get("request_fingerprint") != digest:
                raise ValueError("The invocation_key belongs to different arguments.")
            return await read(ctx, existing.id)
    payload = await MediaGenerationExecutor().prepare_input(ctx.agent_id, input_data)
    payload["request_fingerprint"] = digest
    authority = current_execution_authority() or LLMExecutionAuthority(requester_user_id=get_current_user_id())
    dispatch: dict[str, Any] = {"input": payload}
    await db.commit()
    permit = await register_deferred_dispatch(dispatch)
    if permit:
        dispatch["authorization_permit"] = str(permit)
    identifier = uuid4()
    added = await db.scalar(insert(MediaGeneration).values(
        id=identifier, agent_id=ctx.agent_id, task_id=ctx.task_id, input=payload,
        idempotency_key=key, authority=asdict(authority), dispatch=dispatch,
        callback_token=secrets.token_hex(32),
    ).on_conflict_do_nothing().returning(MediaGeneration.id))
    await db.commit()
    if added is None:
        existing = await db.scalar(select(MediaGeneration).where(
            MediaGeneration.agent_id == ctx.agent_id, MediaGeneration.idempotency_key == key))
        if existing is None or existing.input.get("request_fingerprint") != digest:
            await finish_action(permit, outcome="failed", deferred=True)
            raise ValueError("The invocation_key belongs to different arguments.")
        await finish_action(permit, receipt={"generation_id": str(existing.id)}, deferred=True)
        identifier = existing.id
    return await read(ctx, identifier)

async def read(ctx: McpToolContext, identifier: UUID) -> dict[str, Any]:
    row = await get_db().get(MediaGeneration, identifier, populate_existing=True)
    if row is None or row.agent_id != ctx.agent_id:
        raise PermissionError("Media generation not accessible")
    await authorize(ctx.agent_id, "multimedia_get_run")
    return {"generation_id": str(row.id), "run_id": str(row.id),
            **snapshot(row).model_dump(mode="json")}
