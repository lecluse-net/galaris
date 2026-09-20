"""Inference journal persistence beside the existing gateway trace."""

from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent.contracts import AgentUsage
from core.database import get_db
from . import llm_call_service
from .models import LLMCall, LLMCallEvent


def call_usage(call: LLMCall) -> AgentUsage:
    """Read counters from the gateway's authoritative accounting row."""
    return AgentUsage(
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cache_read_tokens=call.cache_read_tokens,
        cache_write_tokens=call.cache_write_tokens,
        reasoning_tokens=call.reasoning_tokens,
        requests=1,
        cost=call.cost,
        token_quality="exact" if call.usage else "unknown",
        cost_quality=(
            "exact"
            if call.is_subscription or not call.cost_estimated
            else "estimated"
            if call.inference_cost
            else "unknown"
        ),
    )


async def append_events(
    call_id: UUID,
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Commit before delivery, using the execution writer’s contextual session."""
    for index, payload in enumerate(payloads):
        if payload.get("kind") not in {"message", "result", "wire"}:
            raise ValueError("Invalid inference event kind.")
        if payload["kind"] == "result" and index != len(payloads) - 1:
            raise ValueError("The terminal result must be the last event.")
    db = get_db()
    from .call_capture import inference_owner
    from .inference_store import owned, LostInferenceLease

    operation = None
    attempt_id = await db.scalar(select(LLMCall.inference_attempt_id).where(LLMCall.id == call_id))
    if attempt_id is not None:
        owner = inference_owner.get()
        if owner is None or owner.attempt_id != attempt_id:
            raise LostInferenceLease("This writer does not own the inference attempt.")
        operation, _ = await owned(owner)
    call = await db.scalar(select(LLMCall).where(LLMCall.id == call_id).with_for_update())
    if call is None:
        raise LookupError("The inference call no longer exists.")
    last = await db.scalar(
        select(LLMCallEvent)
        .where(LLMCallEvent.call_id == call_id)
        .order_by(LLMCallEvent.sequence.desc())
        .limit(1)
    )
    if last is None:
        raise LookupError("This call has no inference journal.")
    if last.payload["kind"] == "result":
        raise ValueError("An inference journal is already terminal.")
    sequence = last.sequence
    events: list[dict[str, Any]] = []
    for payload in payloads:
        sequence += 1
        if payload["kind"] == "result":
            result = payload["result"]
            result["cost"] = call.cost
            result["usage"] = call_usage(call).model_dump(mode="json")
        event = {
            **payload,
            "call_id": str(call_id),
            "sequence": sequence,
            "schema_version": "galaris.inference-event/v1",
        }
        if operation is not None:
            operation.event_sequence += 1
        db.add(
            LLMCallEvent(
                call_id=call_id,
                sequence=sequence,
                payload=event,
                inference_id=operation.id if operation is not None else None,
                inference_sequence=operation.event_sequence if operation is not None else None,
            )
        )
        events.append(event)
    await db.commit()
    return events


async def read_events(
    call_id: UUID,
    *,
    after_sequence: int = 0,
    limit: int = 500,
    agent_ids: Collection[int] | None = None,
) -> list[dict[str, Any]]:
    """Read a bounded page, with the same ownership scope as the existing call reader."""
    if after_sequence < 0 or not 1 <= limit <= 500:
        raise ValueError("Invalid inference journal cursor or page size.")
    if await llm_call_service.get_call(call_id, agent_ids=agent_ids) is None:
        raise LookupError("Inference call not found.")
    rows = await get_db().scalars(
        select(LLMCallEvent)
        .where(
            LLMCallEvent.call_id == call_id,
            LLMCallEvent.sequence > after_sequence,
            LLMCallEvent.payload["kind"].astext.in_(["message", "result"]),
        )
        .order_by(LLMCallEvent.sequence)
        .limit(limit)
    )
    return [row.payload for row in rows]


async def read_result(
    call_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> dict[str, Any] | None:
    if await llm_call_service.get_call(call_id, agent_ids=agent_ids) is None:
        raise LookupError("Inference call not found.")
    row = await get_db().scalar(
        select(LLMCallEvent)
        .where(
            LLMCallEvent.call_id == call_id,
        )
        .order_by(LLMCallEvent.sequence.desc())
        .limit(1)
    )
    return row.payload["result"] if row is not None and row.payload["kind"] == "result" else None
