"""Autonomous inference execution roots and short database transactions."""

from __future__ import annotations

import asyncio
import anyio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing, suppress, nullcontext
from contextvars import Context
from dataclasses import replace
from typing import TypeVar
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from loguru import logger

from app.agent.contracts import AIResult
from core.database import get_db_session
from core.user import get_current_token_label, get_current_user_id
from . import inference_store, inference_notifications as notifications
from .call_capture import inference_owner
from .contracts import (
    InferenceAction,
    InferenceCommand,
    InferenceRead,
    InferenceRunEvent,
    TextInferenceRequest,
    InferenceRequest,
    StructuredInferenceRequest,
    ProtocolInferenceRequest,
    DecisionInferenceRequest,
)
from .correlation import current_llm_correlation_ref, llm_correlation_scope
from .decision_contracts import DecisionResult

if TYPE_CHECKING:
    from .structured_service import StructuredInferenceResult

T = TypeVar("T")
_worker: asyncio.Task[None] | None = None
_executions: dict[UUID, asyncio.Task[None]] = {}
HEARTBEAT_SECONDS = inference_store.LEASE_SECONDS / 6


async def transaction(action: Callable[[], Awaitable[T]]) -> T:
    async def writer() -> T:
        async with get_db_session():
            return await action()

    task = asyncio.create_task(writer())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await asyncio.shield(task)
        raise


async def read(inference_id: UUID) -> InferenceRead:
    return await transaction(lambda: inference_store.read(inference_id))


async def submit(request: InferenceRequest, *, inference_id: UUID | None = None) -> UUID:
    # Resolve before admission; subsequent attempts use the frozen explicit effort.
    from .llm_service import get_llm
    from .structured_service import resolve_reasoning_effort
    from .subscription_policy import (
        current_execution_authority,
        enforce_subscription_access,
        LLMExecutionAuthority,
    )

    async def admit() -> UUID:
        if isinstance(request, StructuredInferenceRequest):
            from .output_registry import resolve

            resolve(request.output)
        llm = await get_llm(request.llm_id)
        if llm is None:
            raise LookupError("LLM not found.")
        requester = await enforce_subscription_access(
            llm.provider, task_id=request.task_id,
            conversation_round_id=request.conversation_round_id,
            process_run_id=request.process_run_id,
        )
        authority = current_execution_authority()
        requester = (
            requester
            or get_current_user_id()
            or (authority.requester_user_id if authority else None)
        )
        if authority is not None:
            authority = replace(authority, requester_user_id=requester)
        elif requester is not None:
            authority = LLMExecutionAuthority(requester_user_id=requester)
        api_token_label = await get_current_token_label()
        if api_token_label is not None and authority is not None:
            authority = replace(authority, api_token_label=api_token_label)
        resolved = request.model_copy(deep=True)
        if isinstance(resolved, DecisionInferenceRequest):
            from .decision_binding import model_binding

            resolved.model_bindings = {str(llm.id): model_binding(llm)}
            if resolved.allow_text_fallback and resolved.fallback_llm_id is not None:
                fallback = await get_llm(resolved.fallback_llm_id)
                if fallback is None:
                    raise LookupError("Decision fallback model not found.")
                resolved.model_bindings[str(fallback.id)] = model_binding(fallback)
        resolved.correlation_ref = request.correlation_ref or current_llm_correlation_ref()
        if request.model_field is not None and request.reasoning_effort is None:
            resolved.reasoning_effort = await resolve_reasoning_effort(
                request.model_field, request.agent_id
            )
        return await inference_store.create(
            resolved, inference_id=inference_id, authority=authority
        )

    key = await transaction(admit)
    await start()
    return key


async def run_text(request: TextInferenceRequest) -> StructuredInferenceResult[str]:
    return await _run(request, lambda result: result.result)


async def run_decision(request: DecisionInferenceRequest) -> StructuredInferenceResult[DecisionResult]:
    return await _run(request, lambda result: DecisionResult.model_validate(result.structured_output))


async def run_structured(
    request: StructuredInferenceRequest, output_type: type[T]
) -> StructuredInferenceResult[T]:
    from pydantic import TypeAdapter

    adapter = TypeAdapter(output_type)
    return await _run(request, lambda result: adapter.validate_python(result.structured_output))


async def _run(
    request: InferenceRequest, decode: Callable[[AIResult], T]
) -> StructuredInferenceResult[T]:
    """Compatibility adapter for the Lab pilot's existing synchronous contract."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from .accounting_scope import record_persisted_call_cost
    from .structured_service import StructuredInferenceResult

    key = uuid4()
    try:
        await submit(request, inference_id=key)
        while True:
            with notifications.subscribe("changes", key) as changed:
                snapshot = await read(key)
                if snapshot.status == "paused":
                    await notifications.wait(changed)
                    continue
            async with aclosing(events(key, attempt_id=snapshot.attempts[-1].id)) as stream:
                async for event in stream:
                    if event.result is not None:
                        if not event.result.success:
                            if (
                                event.result.metadata.get("inference_status") == "paused"
                                and (await read(key)).status != "stopped"
                            ):
                                break
                            raise RuntimeError(
                                str(event.result.metadata.get("error", "Inference did not complete."))
                            )
                        transcript, _ = await transaction(
                            lambda: inference_store.execution_details(key)
                        )
                        return StructuredInferenceResult(
                            output=decode(event.result),
                            cost=(await read(key)).cost,
                            messages=list(ModelMessagesTypeAdapter.validate_python(transcript)),
                        )
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            with suppress(LookupError, ValueError):
                await command(key, "stop", uuid4())
                async for _ in events(key):
                    pass
        raise
    finally:
        with anyio.CancelScope(shield=True):
            with suppress(LookupError):
                _, costs = await transaction(lambda: inference_store.execution_details(key))
                for call_id, cost in costs.items():
                    record_persisted_call_cost(call_id, cost)


async def command(
    inference_id: UUID, action: InferenceAction, command_id: UUID
) -> InferenceCommand:
    result = await transaction(lambda: inference_store.command(inference_id, action, command_id))
    if action in {"resume", "replay"}:
        await start()
    return result


async def events(
    inference_id: UUID, *, attempt_id: UUID | None = None, after_sequence: int = 0
) -> AsyncGenerator[InferenceRunEvent]:
    snapshot = await read(inference_id)
    attempt_id = attempt_id or snapshot.attempts[-1].id
    cursor = after_sequence
    with notifications.subscribe("changes", inference_id) as changed:
        while True:
            changed.clear()
            status = await transaction(lambda: inference_store.read_attempt_status(inference_id, attempt_id))
            batch = await transaction(
                lambda cursor=cursor: inference_store.read_events(inference_id, attempt_id, cursor)
            )
            for event in batch:
                cursor = event.sequence
                yield event
                if event.kind == "result":
                    return
            if status in inference_store.TERMINAL_ATTEMPTS and not batch:
                return
            if not batch:
                await notifications.wait(changed)


async def execute(inference_id: UUID) -> None:
    owner = await transaction(lambda: inference_store.claim(inference_id))
    if owner is None:
        return
    snapshot = await read(inference_id)
    authority = await transaction(lambda: inference_store.execution_authority(owner))
    partial = AIResult(prompt=snapshot.request.prompt, system_prompt=snapshot.request.system_prompt)

    async def invoke() -> AIResult:
        from .inference_facade import run_inference
        from .structured_service import reasoning_effort_scope
        from .reasoning import normalize_reasoning_effort
        from .subscription_policy import llm_execution_scope

        token = inference_owner.set(owner)
        try:
            async with get_db_session():
                with (
                    reasoning_effort_scope(
                        normalize_reasoning_effort(snapshot.request.reasoning_effort, strict=True)
                    ),
                    llm_correlation_scope(snapshot.request.correlation_ref)
                    if snapshot.request.correlation_ref
                    else nullcontext(),
                    llm_execution_scope(
                        requester_user_id=authority.requester_user_id,
                        source_kind=authority.source_kind,
                        source_id=authority.source_id,
                        messenger_origin=authority.messenger_origin,
                        api_token_label=authority.api_token_label,
                    ),
                ):

                    async def receive(event: object) -> None:
                        from .contracts import InferenceEvent

                        if isinstance(event, InferenceEvent) and event.message is not None:
                            partial.add_message(event.message.model_copy(deep=True))

                    if isinstance(snapshot.request, ProtocolInferenceRequest):
                        from .protocol_inference import run_protocol

                        return await run_protocol(snapshot.request, on_event=receive)
                    if isinstance(snapshot.request, DecisionInferenceRequest):
                        from .decision_service import execute_decision

                        return await execute_decision(snapshot.request, on_event=receive)
                    return await run_inference(snapshot.request, on_event=receive)
        finally:
            inference_owner.reset(token)

    task = asyncio.create_task(invoke(), name=f"inference-attempt:{owner.attempt_id}")
    result = partial
    interrupted = False
    lost = False
    try:
        with notifications.subscribe("control", inference_id) as control:
            while True:
                # Register/clear before checking durable state: a command may
                # commit during that check, before we start waiting.
                control.clear()
                status = await transaction(lambda: inference_store.heartbeat(owner))
                if status in {"pausing", "stopping"}:
                    task.cancel()
                    break
                if task.done():
                    break
                command_wait = asyncio.create_task(control.wait())
                try:
                    await asyncio.wait(
                        {task, command_wait}, timeout=HEARTBEAT_SECONDS,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    command_wait.cancel()
                    await asyncio.gather(command_wait, return_exceptions=True)
        result = await task
    except inference_store.LostInferenceLease:
        lost = True
    except asyncio.CancelledError:
        interrupted = True
        result.success = False
        result.metadata["error"] = "Inference execution interrupted."
    except Exception as exc:
        result.success = False
        result.metadata["error"] = str(exc)
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
        if not lost:
            with suppress(inference_store.LostInferenceLease):
                await transaction(
                    lambda: inference_store.finish(owner, result, interrupted=interrupted)
                )


async def _loop() -> None:
    try:
        with notifications.subscribe("work") as work:
            loop = asyncio.get_running_loop()
            recover_at = 0.0
            while True:
                work.clear()
                if loop.time() >= recover_at:
                    recovered = await transaction(inference_store.recover_expired)
                    # A restart can leave more than one recovery page. Drain it
                    # without adding a reconciliation delay between every page.
                    recover_at = loop.time() + (
                        0.0 if recovered == inference_store.RECOVERY_BATCH_SIZE
                        else notifications.RECONCILE_SECONDS
                    )
                for key, task in list(_executions.items()):
                    if task.done():
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            logger.exception("Inference execution root failed for {}", key)
                        del _executions[key]
                # Drain bounded pages without waiting for the reconciliation
                # timer; exclude roots whose claim has not committed yet.
                pending = await transaction(lambda: inference_store.pending(exclude=tuple(_executions)))
                for key in pending:
                    task = asyncio.create_task(
                        execute(key), name=f"inference:{key}"
                    )
                    _executions[key] = task
                    task.add_done_callback(_execution_done)
                if len(pending) == inference_store.PENDING_BATCH_SIZE:
                    continue
                await notifications.wait(work, timeout=max(0.0, recover_at - loop.time()))
    finally:
        tasks = list(_executions.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        _executions.clear()


def _execution_done(task: asyncio.Task[None]) -> None:
    # A failed claim must not create an immediate, unbounded retry loop. The
    # periodic reconciliation will retry it. Successful roots free their slot
    # immediately, including a resume racing with the old root's finalization.
    if not task.cancelled() and task.exception() is None:
        notifications.notify("work")


async def start() -> None:
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_loop(), name="llm-inference-worker", context=Context())


async def stop() -> None:
    global _worker
    worker, _worker = _worker, None
    if worker is not None:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


def is_running() -> bool:
    return _worker is not None and not _worker.done()
