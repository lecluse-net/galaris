"""Common inference execution and durable readback adapters."""

from collections.abc import Awaitable, Callable, Collection, Generator
from contextlib import contextmanager, nullcontext
from uuid import UUID
from typing import Any

from app.agent.contracts import AIResult, AgentUsage
from . import llm_service, structured_service
from .call_capture import TextCallCapture, text_call_capture
from .contracts import InferenceEvent, InferenceRequest, StructuredInferenceRequest, TextInferenceRequest
from . import inference_journal
from .reasoning import normalize_reasoning_effort


@contextmanager
def record_text_inferences(*, durable: bool = False) -> Generator[None]:
    """Opt in an existing composed caller without changing its return or retry policy."""

    async def publish(_payload: dict[str, Any]) -> None:
        pass

    token = text_call_capture.set(TextCallCapture(request={}, publish=publish, durable=durable))
    try:
        yield
    finally:
        text_call_capture.reset(token)


@contextmanager
def record_structured_inferences() -> Generator[None]:
    async def publish(_payload: dict[str, Any]) -> None:
        pass

    token = text_call_capture.set(TextCallCapture(
        request={}, publish=publish, durable=True, structured=True
    ))
    try:
        yield
    finally:
        text_call_capture.reset(token)


async def run_text_inference(
    request: TextInferenceRequest,
    *,
    on_event: Callable[[InferenceEvent], Awaitable[None]] | None = None,
) -> AIResult:
    return await run_inference(request, on_event=on_event)


async def run_inference(
    request: InferenceRequest,
    *,
    on_event: Callable[[InferenceEvent], Awaitable[None]] | None = None,
) -> AIResult:
    """Run the SDK agent; deliver committed messages and per-call results.

    SDK validation retries retain distinct gateway calls. The returned result belongs
    to this inference operation; each event/result in the journal belongs to one call.
    Detached callers use start_inference and stream_inference for durable control.
    """
    llm = await llm_service.get_llm(request.llm_id)
    if llm is None:
        raise LookupError("LLM not found.")

    async def publish(payload: dict[str, Any]) -> None:
        if on_event is not None:
            await on_event(InferenceEvent.model_validate(payload))

    capture = TextCallCapture(
        request=request.model_dump(mode="json"),
        publish=publish,
        parameters=dict(request.parameters),
        structured=isinstance(request, StructuredInferenceRequest),
    )
    token = text_call_capture.set(capture)
    try:
        with (
            structured_service.reasoning_effort_scope(
                normalize_reasoning_effort(request.reasoning_effort, strict=True)
            )
            if request.reasoning_effort is not None
            else nullcontext()
        ):
            arguments: dict[str, Any] = dict(
                llm=llm,
                prompt=request.prompt,
                system_prompt=request.system_prompt,
                task_id=request.task_id,
                agent_id=request.agent_id,
                temperature=0.0,  # Explicit parameters are passed intact to the SDK model.
                request_limit=request.request_limit,
                count_tokens_before_request=request.count_tokens_before_request,
                purpose=request.purpose,
                model_field=request.model_field,
            )
            if isinstance(request, StructuredInferenceRequest):
                from .output_registry import resolve

                contract = resolve(request.output)
                inference = await structured_service.run_structured(
                    **arguments,
                    output_type=contract.output_type,
                    output_validator=contract.validator,
                    output_mode=request.output.mode,
                    output_retries=request.output_retries,
                    agent_run_id=request.agent_run_id,
                    conversation_round_id=request.conversation_round_id,
                )
            else:
                inference = await structured_service.run_text(**arguments)
    finally:
        text_call_capture.reset(token)
    result = AIResult(prompt=request.prompt, system_prompt=request.system_prompt)
    usage = AgentUsage()
    call_ids: list[str] = []
    for raw in capture.results:
        call_result = AIResult.model_validate(raw)
        for message in call_result.messages:
            result.add_message(message)
        usage = usage.merged(call_result.usage)
        result.execution_time += call_result.execution_time
        call_ids.append(str(call_result.metadata["llm_call_id"]))
    if isinstance(request, StructuredInferenceRequest):
        from pydantic import BaseModel
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        if not isinstance(inference.output, BaseModel):
            raise TypeError("The registered inference output must be a Pydantic model.")
        result.structured_output = inference.output.model_dump(
            mode="json", by_alias=True, round_trip=True
        )
        result.result = inference.output.model_dump_json(by_alias=True, round_trip=True)
        result.metadata["output_contract"] = request.output.contract
        result.metadata["sdk_messages"] = ModelMessagesTypeAdapter.dump_python(
            inference.messages, mode="json"
        )
    else:
        result.result = str(inference.output)
    result.cost = inference.cost
    result.usage = usage
    result.metadata["llm_call_ids"] = call_ids
    return result


async def read_inference_events(
    call_id: UUID,
    *,
    after_sequence: int = 0,
    limit: int = 500,
    agent_ids: Collection[int] | None = None,
) -> list[InferenceEvent]:
    return [
        InferenceEvent.model_validate(payload)
        for payload in await inference_journal.read_events(
            call_id,
            after_sequence=after_sequence,
            limit=limit,
            agent_ids=agent_ids,
        )
    ]


async def read_inference_result(
    call_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> AIResult | None:
    payload = await inference_journal.read_result(call_id, agent_ids=agent_ids)
    return AIResult.model_validate(payload) if payload is not None else None


__all__ = [
    "InferenceEvent",
    "TextInferenceRequest",
    "run_text_inference",
    "read_inference_events",
    "read_inference_result",
    "record_text_inferences",
]
