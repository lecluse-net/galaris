"""Transactional inference lifecycle; provider accounting remains in LLMCall."""

from datetime import datetime, timedelta
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.agent.contracts import AIMessage, AIResult, AgentUsage
from core.database import get_db
from .call_capture import InferenceOwner
from .contracts import (
    InferenceAction,
    InferenceAttempt,
    InferenceCommand,
    InferenceRead,
    InferenceRunEvent,
    InferenceRequest,
    InferenceRequestAdapter,
)
from .models import LLMCall, LLMCallEvent, LLMInference, LLMInferenceAttempt, LLMInferenceCommand
from .subscription_policy import LLMExecutionAuthority
from .inference_journal import call_usage

LEASE_SECONDS = 30
TERMINAL_ATTEMPTS = frozenset({"paused", "stopped", "completed", "failed", "interrupted"})


async def can_access(
    inference_id: UUID, *, requester_user_id: int | None,
    agent_ids: frozenset[int] | None,
) -> bool:
    operation = await get_db().get(LLMInference, inference_id)
    if operation is None:
        return False
    return (
        agent_ids is None
        or (requester_user_id is not None and operation.requester_user_id == requester_user_id)
        or operation.request.get("agent_id") in agent_ids
    )


class LostInferenceLease(RuntimeError):
    pass


async def now() -> datetime:
    return (await get_db().execute(select(func.clock_timestamp()))).scalar_one()


async def create(
    request: InferenceRequest,
    *,
    inference_id: UUID | None = None,
    replay_of_id: UUID | None = None,
    authority: LLMExecutionAuthority | None = None,
) -> UUID:
    db = get_db()
    key = inference_id or uuid4()
    payload = request.model_dump(mode="json")
    added = await db.scalar(
        insert(LLMInference)
        .values(
            id=key,
            request=payload,
            replay_of_id=replay_of_id,
            status="queued",
            generation=1,
            event_sequence=0,
            requester_user_id=authority.requester_user_id if authority else None,
            authority=asdict(authority) if authority else {},
        )
        .on_conflict_do_nothing(index_elements=[LLMInference.id])
        .returning(LLMInference.id)
    )
    if added is not None:
        db.add(LLMInferenceAttempt(inference_id=key, number=1, status="queued"))
        await db.flush()
    else:
        existing = await db.get(LLMInference, key)
        if (
            existing is None
            or InferenceRequestAdapter.validate_python(existing.request).model_dump(mode="json") != payload
            or existing.replay_of_id != replay_of_id
            or existing.authority != (asdict(authority) if authority else {})
        ):
            raise ValueError("An inference identity cannot be reused for another request.")
    return key


async def execution_authority(owner: InferenceOwner) -> LLMExecutionAuthority:
    operation, _ = await owned(owner)
    return LLMExecutionAuthority(**operation.authority)


async def execution_details(inference_id: UUID) -> tuple[list[Any], dict[UUID, float]]:
    """Recover the last SDK transcript and project authoritative physical-call costs."""
    snapshot = await read(inference_id)
    call_ids = [key for attempt in snapshot.attempts for key in attempt.call_ids]
    calls = list(await get_db().scalars(select(LLMCall).where(LLMCall.id.in_(call_ids))))
    transcript: list[Any] = []
    if call_ids:
        rows = await get_db().scalars(
            select(LLMCallEvent)
            .where(
                LLMCallEvent.call_id == call_ids[-1],
            )
            .order_by(LLMCallEvent.sequence)
        )
        for row in rows:
            if row.payload["kind"] == "request":
                transcript = list(row.payload["request"].get("sdk_messages", []))
            elif row.payload["kind"] == "result":
                transcript.extend(row.payload.get("sdk_response", []))
    if snapshot.attempts[-1].result is not None:
        transcript = snapshot.attempts[-1].result.metadata.get("sdk_messages", transcript)
    return transcript, {call.id: call.cost for call in calls}


async def locked(inference_id: UUID) -> tuple[LLMInference, LLMInferenceAttempt]:
    db = get_db()
    operation = await db.scalar(
        select(LLMInference).where(LLMInference.id == inference_id).with_for_update()
    )
    if operation is None:
        raise LookupError("Inference not found.")
    attempt = (
        await db.execute(
            select(LLMInferenceAttempt)
            .where(
                LLMInferenceAttempt.inference_id == inference_id,
                LLMInferenceAttempt.number == operation.generation,
            )
            .with_for_update()
        )
    ).scalar_one()
    return operation, attempt


async def owned(owner: InferenceOwner) -> tuple[LLMInference, LLMInferenceAttempt]:
    operation, attempt = await locked(owner.inference_id)
    if (
        attempt.id != owner.attempt_id
        or attempt.lease_token != owner.token
        or attempt.status != "running"
        or attempt.lease_expires_at is None
        or attempt.lease_expires_at <= await now()
    ):
        raise LostInferenceLease("This inference attempt no longer owns execution.")
    return operation, attempt


async def claim(inference_id: UUID) -> InferenceOwner | None:
    operation, attempt = await locked(inference_id)
    if operation.status != "queued" or attempt.status != "queued":
        return None
    timestamp = await now()
    token = uuid4()
    operation.status = attempt.status = "running"
    attempt.lease_token = token
    attempt.started_at = timestamp
    attempt.lease_expires_at = timestamp + timedelta(seconds=LEASE_SECONDS)
    return InferenceOwner(operation.id, attempt.id, token)


async def heartbeat(owner: InferenceOwner) -> str:
    operation, attempt = await owned(owner)
    attempt.lease_expires_at = await now() + timedelta(seconds=LEASE_SECONDS)
    return operation.status


async def _finish(
    operation: LLMInference, attempt: LLMInferenceAttempt, result: AIResult, status: str
) -> None:
    if attempt.status in TERMINAL_ATTEMPTS:
        raise LostInferenceLease("The inference attempt is already terminal.")
    timestamp = await now()
    operation.event_sequence += 1
    operation.status = attempt.status = status
    attempt.completed_at = timestamp
    attempt.lease_expires_at = None
    attempt.final_sequence = operation.event_sequence
    result.metadata.update(
        inference_id=str(operation.id), attempt_id=str(attempt.id), inference_status=status
    )
    calls = list(
        await get_db().scalars(select(LLMCall).where(LLMCall.inference_attempt_id == attempt.id))
    )
    result.cost = sum(call.cost for call in calls)
    result.usage = AgentUsage()
    for call in calls:
        result.usage = result.usage.merged(call_usage(call))
    attempt.result = result.model_dump(mode="json")
    commands = await get_db().scalars(
        select(LLMInferenceCommand).where(
            LLMInferenceCommand.attempt_id == attempt.id,
            LLMInferenceCommand.applied_at.is_(None),
        )
    )
    for command in commands:
        command.applied_at = timestamp


async def finish(owner: InferenceOwner, result: AIResult, *, interrupted: bool = False) -> None:
    operation, attempt = await owned(owner)
    status = {"pausing": "paused", "stopping": "stopped"}.get(operation.status)
    status = status or (
        "interrupted" if interrupted else "completed" if result.success else "failed"
    )
    if status != "completed":
        result.success = False
        result.structured_output = None
        result.metadata.pop("sdk_messages", None)
        result.metadata["inference_status"] = status
        await _close_abandoned_calls(
            operation,
            attempt,
            error=str(result.metadata.get("error", "Inference interrupted.")),
        )
        # The last committed delta may not have reached the callback at cancellation.
        persisted = AIResult(prompt=result.prompt, system_prompt=result.system_prompt)
        rows = await get_db().scalars(
            select(LLMCallEvent)
            .join(LLMCall)
            .where(
                LLMCall.inference_attempt_id == attempt.id,
                LLMCallEvent.payload["kind"].astext == "message",
            )
            .order_by(LLMCallEvent.inference_sequence)
        )
        for row in rows:
            persisted.add_message(AIMessage.model_validate(row.payload["message"]))
        result.messages = persisted.messages
        result.result = persisted.result
        result.tools_used = persisted.tools_used
    await _finish(operation, attempt, result, status)


async def command(
    inference_id: UUID, action: InferenceAction, command_id: UUID
) -> InferenceCommand:
    db = get_db()
    operation, attempt = await locked(inference_id)
    previous = await db.get(LLMInferenceCommand, command_id)
    if previous is not None:
        if previous.inference_id != inference_id or previous.action != action:
            raise ValueError("A command identity cannot be reused for another action.")
        return InferenceCommand.model_validate(previous, from_attributes=True)
    receipt = LLMInferenceCommand(
        id=command_id, inference_id=inference_id, attempt_id=attempt.id, action=action
    )
    if action == "replay":
        receipt.replay_id = await create(
            InferenceRequestAdapter.validate_python(operation.request),
            replay_of_id=inference_id,
            authority=LLMExecutionAuthority(**operation.authority) if operation.authority else None,
        )
    elif action == "resume":
        if operation.status not in {"paused", "interrupted"}:
            raise ValueError("Only a paused or interrupted inference can resume.")
        operation.generation += 1
        operation.status = "queued"
        db.add(
            LLMInferenceAttempt(
                inference_id=inference_id, number=operation.generation, status="queued"
            )
        )
    elif operation.status in {"completed", "failed", "stopped"}:
        raise ValueError("A completed inference is immutable; use replay.")
    elif attempt.status == "running":
        if action == "pause" and operation.status == "stopping":
            raise ValueError("A stop already requested cannot become a pause.")
        operation.status = "pausing" if action == "pause" else "stopping"
    elif attempt.status == "queued":
        partial = AIResult(
            prompt=str(operation.request["prompt"]),
            system_prompt=str(operation.request.get("system_prompt", "")),
            success=False,
        )
        await _finish(operation, attempt, partial, "paused" if action == "pause" else "stopped")
    elif action == "stop":
        operation.status = "stopped"  # Preserve the previous attempt's immutable terminal result.
    if operation.status not in {"pausing", "stopping"} or action == "replay":
        receipt.applied_at = await now()
    db.add(receipt)
    await db.flush()
    return InferenceCommand.model_validate(receipt, from_attributes=True)


async def read(inference_id: UUID) -> InferenceRead:
    db = get_db()
    operation = await db.get(LLMInference, inference_id)
    if operation is None:
        raise LookupError("Inference not found.")
    attempts = list(
        await db.scalars(
            select(LLMInferenceAttempt)
            .where(
                LLMInferenceAttempt.inference_id == inference_id,
            )
            .order_by(LLMInferenceAttempt.number)
        )
    )
    calls = list(
        await db.scalars(
            select(LLMCall)
            .where(
                LLMCall.inference_attempt_id.in_([attempt.id for attempt in attempts]),
            )
            .order_by(LLMCall.started_at, LLMCall.id)
        )
    )
    return InferenceRead.model_validate(
        {
            "id": operation.id,
            "replay_of_id": operation.replay_of_id,
            "status": operation.status,
            "request": operation.request,
            "cost": sum(call.cost for call in calls),
            "attempts": [
                InferenceAttempt.model_validate(
                    {
                        "id": row.id,
                        "number": row.number,
                        "status": row.status,
                        "started_at": row.started_at,
                        "completed_at": row.completed_at,
                        "result": row.result,
                        "call_ids": [
                            call.id for call in calls if call.inference_attempt_id == row.id
                        ],
                    }
                )
                for row in attempts
            ],
        }
    )


async def read_events(
    inference_id: UUID, attempt_id: UUID, after_sequence: int = 0, limit: int = 500
) -> list[InferenceRunEvent]:
    if after_sequence < 0 or not 1 <= limit <= 500:
        raise ValueError("Invalid inference cursor or page size.")
    db = get_db()
    attempt = await db.get(LLMInferenceAttempt, attempt_id)
    if attempt is None or attempt.inference_id != inference_id:
        raise LookupError("Inference attempt not found.")
    rows = await db.scalars(
        select(LLMCallEvent)
        .join(LLMCall)
        .where(
            LLMCall.inference_attempt_id == attempt_id,
            LLMCallEvent.inference_sequence > after_sequence,
            LLMCallEvent.payload["kind"].astext == "message",
        )
        .order_by(LLMCallEvent.inference_sequence)
        .limit(limit)
    )
    events = [
        InferenceRunEvent(
            inference_id=inference_id,
            attempt_id=attempt_id,
            sequence=row.inference_sequence or 0,
            kind="message",
            call_id=row.call_id,
            message=row.payload["message"],
        )
        for row in rows
    ]
    if (
        len(events) < limit
        and attempt.final_sequence is not None
        and attempt.final_sequence > after_sequence
        and attempt.result is not None
    ):
        events.append(
            InferenceRunEvent(
                inference_id=inference_id,
                attempt_id=attempt_id,
                sequence=attempt.final_sequence,
                kind="result",
                result=AIResult.model_validate(attempt.result),
            )
        )
    return events


async def pending() -> list[UUID]:
    return list(
        await get_db().scalars(
            select(LLMInference.id)
            .where(
                LLMInference.status == "queued",
            )
            .order_by(LLMInference.created_at)
            .limit(20)
        )
    )


async def recover_expired() -> int:
    db = get_db()
    expired = list(
        await db.scalars(
            select(LLMInferenceAttempt.inference_id)
            .where(
                LLMInferenceAttempt.status == "running",
                LLMInferenceAttempt.lease_expires_at <= await now(),
            )
            .limit(100)
        )
    )
    recovered = 0
    for key in expired:
        operation, attempt = await locked(key)
        if (
            attempt.status != "running"
            or attempt.lease_expires_at is None
            or attempt.lease_expires_at > await now()
        ):
            continue
        partial = AIResult(
            prompt=str(operation.request["prompt"]),
            system_prompt=str(operation.request.get("system_prompt", "")),
            success=False,
        )
        rows = await db.scalars(
            select(LLMCallEvent)
            .join(LLMCall)
            .where(
                LLMCall.inference_attempt_id == attempt.id,
                LLMCallEvent.payload["kind"].astext == "message",
            )
            .order_by(LLMCallEvent.inference_sequence)
        )
        for row in rows:
            partial.add_message(AIMessage.model_validate(row.payload["message"]))
        partial.metadata["error"] = "The execution lease expired. Explicit resume is required."
        await _close_abandoned_calls(operation, attempt)
        state = {"pausing": "paused", "stopping": "stopped"}.get(operation.status, "interrupted")
        await _finish(operation, attempt, partial, state)
        recovered += 1
    return recovered


async def _close_abandoned_calls(
    operation: LLMInference,
    attempt: LLMInferenceAttempt,
    *,
    error: str = "Inference execution lease expired.",
) -> None:
    db = get_db()
    calls = await db.scalars(
        select(LLMCall).where(LLMCall.inference_attempt_id == attempt.id).with_for_update()
    )
    for call in calls:
        rows = list(
            await db.scalars(
                select(LLMCallEvent)
                .where(LLMCallEvent.call_id == call.id)
                .order_by(LLMCallEvent.sequence)
            )
        )
        # Cancellation can happen after the gateway commits admission but before
        # its transport/cleanup has even started. Closing the logical attempt must
        # also close that physical trace, even if its journal is already terminal.
        if call.status == "running":
            call.status = "cancelled"
            completed_at = await now()
            call.completed_at = completed_at
            call.duration = max(0, (completed_at - call.started_at).total_seconds())
            call.error = error
        if not rows or rows[-1].payload["kind"] == "result":
            continue
        result = AIResult(
            prompt=call.prompt,
            system_prompt=call.system_prompt,
            success=False,
            cost=call.cost,
            usage=call_usage(call),
        )
        for row in rows:
            if row.payload["kind"] == "message":
                result.add_message(AIMessage.model_validate(row.payload["message"]))
        result.metadata.update(llm_call_id=str(call.id), error=error)
        sequence = rows[-1].sequence + 1
        operation.event_sequence += 1
        db.add(
            LLMCallEvent(
                call_id=call.id,
                sequence=sequence,
                inference_id=operation.id,
                inference_sequence=operation.event_sequence,
                payload={
                    "schema_version": "galaris.inference-event/v1",
                    "call_id": str(call.id),
                    "sequence": sequence,
                    "kind": "result",
                    "result": result.model_dump(mode="json"),
                },
            )
        )
