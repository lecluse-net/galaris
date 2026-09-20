"""Runtime-independent validation and ownership of a concrete driver's stream."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import fields, replace
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import cast

from pydantic import BaseModel, ValidationError

from .contracts import AgentDriver, AgentDriverSpec, AgentEvent, AgentRunCheckpoint, AgentRunRequest, ExecutionResult, HarnessExecutionPolicy, StaleAgentRunError
from .execution_errors import HarnessExecutionError, HarnessProtocolError, classify_execution_error


def driver_payload(value: object) -> object:
    """Treat runtime-returned models as untrusted payloads, including nested fields."""
    return value.model_dump() if isinstance(value, BaseModel) else value


async def validated_driver_stream(
    driver: AgentDriver, request: AgentRunRequest, *, spec: AgentDriverSpec,
) -> AsyncGenerator[AgentEvent, None]:
    """Forward messages promptly; accept a result only after clean, bounded EOF.

    A result followed by a crash, a second result or a hanging tail is a failed run.
    Closing this generator also closes its owned driver iterator. Drivers must cooperate
    with asyncio cancellation; an in-process adapter cannot forcibly stop Python code.
    """
    # Frozen dataclasses still contain mutable mappings/models. Only control callbacks
    # retain their identity; no driver gets ownership of the caller's data graph.
    request = replace(request, **{
        item.name: deepcopy(getattr(request, item.name))
        for item in fields(request) if item.name != "control"
    })
    descriptor = request.target.descriptor if request.target is not None else None
    policy = descriptor.policy if descriptor is not None else HarnessExecutionPolicy(
        stream_close_timeout_seconds=spec.stream_close_timeout_seconds,
    )
    streaming = spec.supports_streaming and (descriptor is None or "streaming" in descriptor.effective)
    close_timeout = min(policy.stream_close_timeout_seconds, spec.stream_close_timeout_seconds)
    total_bytes = 0

    def account(payload: object, limit: int, *, source: str, stream_event: bool = False) -> None:
        nonlocal total_bytes
        try:
            size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise HarnessProtocolError("The Harness payload is not finite JSON data.") from exc
        if size > limit:
            raise HarnessProtocolError(
                f"The Harness {source} exceeds the configured byte budget ({size} > {limit} bytes)."
            )
        # Progress and checkpoints replace durable state. Counting their full history
        # on every save makes the output budget grow quadratically with tool calls.
        # Keep each snapshot bounded, but accumulate only emitted stream events.
        if stream_event:
            total_bytes += size
            if total_bytes > policy.max_stream_bytes:
                raise HarnessProtocolError(
                    "The Harness stream exceeds the configured byte budget "
                    f"({total_bytes} > {policy.max_stream_bytes} bytes)."
                )

    control = request.control

    async def save_progress(result: ExecutionResult) -> None:
        validated = ExecutionResult.model_validate(driver_payload(result))
        account(validated.model_dump(mode="json"), policy.max_result_bytes, source="progress snapshot")
        assert control.save_progress is not None
        await control.save_progress(validated)

    async def save_checkpoint(checkpoint: AgentRunCheckpoint) -> None:
        if "checkpoints" not in spec.execution_capabilities or checkpoint.driver_code != spec.code:
            raise HarnessProtocolError("The driver cannot write this checkpoint.")
        copied = deepcopy(checkpoint)
        result = None if copied.result is None else ExecutionResult.model_validate(driver_payload(copied.result))
        copied = replace(copied, result=result)
        account({"driver_code": copied.driver_code, "runtime_run_id": copied.runtime_run_id,
                 "status": copied.status, "data": copied.data,
                 "result": None if result is None else result.model_dump(mode="json")},
                policy.max_result_bytes, source="checkpoint")
        assert control.save_checkpoint is not None
        await control.save_checkpoint(copied)

    request = replace(request, control=replace(
        control, save_progress=save_progress if control.save_progress is not None else None,
        save_checkpoint=save_checkpoint if control.save_checkpoint is not None else None,
        # The facade owns terminal events and sequence allocation. Drivers publish
        # normalized messages/results through their iterator, never durable terminals.
        publish_event=None,
    ))

    async def result_stream() -> AsyncGenerator[AgentEvent, None]:
        result = ExecutionResult.model_validate(driver_payload(await driver.run(request)))
        yield AgentEvent.from_result(result)

    stream = driver.stream(request) if streaming else result_stream()
    terminal: AgentEvent | None = None
    started = asyncio.get_running_loop().time()
    try:
        iterator = aiter(stream)
        while True:
            try:
                if terminal is None:
                    remaining = (None if policy.execution_timeout_seconds is None
                        else max(0.0, policy.execution_timeout_seconds - (asyncio.get_running_loop().time() - started)))
                    timeout = policy.idle_timeout_seconds
                    if remaining is not None:
                        timeout = remaining if timeout is None else min(remaining, timeout)
                    async with asyncio.timeout(timeout):
                        raw = await anext(iterator)
                else:
                    try:
                        async with asyncio.timeout(close_timeout):
                            raw = await anext(iterator)
                    except TimeoutError as exc:
                        raise HarnessProtocolError(
                            f"Driver {spec.code!r} did not close after its terminal result."
                        ) from exc
            except StopAsyncIteration:
                break
            if terminal is not None:
                raise HarnessProtocolError(f"Driver {spec.code!r} emitted an event after its terminal result.")
            # Revalidate nested payloads even when a runtime mutated an existing model.
            event = AgentEvent.model_validate(driver_payload(raw))
            if event.result is not None and not event.result.success and event.result.failure is None:
                event.result.failure = classify_execution_error(RuntimeError("The Harness reported a failed run."))
            limit = policy.max_result_bytes if event.kind == "result" else policy.max_message_bytes
            account(event.model_dump(mode="json"), limit, source=event.kind, stream_event=True)
            if event.kind == "result":
                terminal = event
            else:
                yield event
        if terminal is None:
            raise HarnessProtocolError(f"Driver {spec.code!r} emitted no terminal result.")
    except ValidationError as exc:
        raise HarnessProtocolError("Invalid Harness event or result payload.") from exc
    except (HarnessExecutionError, StaleAgentRunError):
        raise
    except Exception as exc:
        raise HarnessExecutionError(classify_execution_error(exc)) from exc
    finally:
        close = getattr(stream, "aclose", None)
        if callable(close):
            async with asyncio.timeout(close_timeout):
                await cast(Callable[[], Awaitable[None]], close)()
    yield terminal
