"""Closed-choice inference with a bounded, journaled text fallback."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from pydantic import JsonValue, TypeAdapter
from pydantic_ai import ModelRetry

from app.agent import AIResult
from . import llm_call_service, llm_provider_service, llm_service, output_registry
from .call_capture import TextCallCapture, inference_owner, text_call_capture
from .contracts import DecisionInferenceRequest, InferenceEvent, StructuredInferenceRequest
from .decision_binding import model_binding
from .decision_contracts import (
    ChoiceAnswer, ChoiceQuestion, DecisionResult, DecisionSelection, DecisionUnavailable,
)
from .provider_facade import decision_provider_for
from .resource_discovery import provider_connection
from .subscription_policy import enforce_subscription_access
from .text_inference import persist_events


def _validator(context: dict[str, JsonValue]) -> Callable[[DecisionSelection], DecisionSelection]:
    questions = TypeAdapter(dict[str, ChoiceQuestion]).validate_python(context)

    def validate(selection: DecisionSelection) -> DecisionSelection:
        result = DecisionResult(
            answers={key: ChoiceAnswer(choice=value) for key, value in selection.selections.items()},
            source="text", model="",
        )
        try:
            result.validate_questions(questions)
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return selection

    return validate


async def _native(request: DecisionInferenceRequest, timeout: float | None) -> DecisionResult:
    from .inference_execution import transaction

    llm = await llm_service.get_llm(request.llm_id)
    if llm is None or not llm.provider.is_active:
        raise LookupError("Decision model or provider is unavailable.")
    if request.model_bindings.get(str(llm.id)) != model_binding(llm):
        raise ValueError("Decision model binding changed after admission.")
    if "decision" not in (llm.service_capabilities or []):
        raise ValueError("The selected model does not support decisions.")
    requester = await enforce_subscription_access(
        llm.provider, task_id=request.task_id,
        conversation_round_id=request.conversation_round_id, process_run_id=request.process_run_id,
    )
    connection = provider_connection(llm.provider, llm_provider_service.decrypt_api_key(llm.provider.api_key))
    provider = decision_provider_for(connection)
    if provider is None:
        raise ValueError("No decision adapter is registered for this provider.")

    async def publish(_payload: dict[str, Any]) -> None:
        pass

    capture = TextCallCapture(request=request.model_dump(mode="json"), publish=publish)
    token = text_call_capture.set(capture)
    started = time.monotonic()
    result = AIResult(prompt=request.prompt, system_prompt=request.system_prompt)
    trace: dict[str, Any] = {}
    failure: BaseException | None = None
    try:
        call = await transaction(lambda: llm_call_service.create_running_call(
            purpose=request.purpose, task_id=request.task_id, agent_id=request.agent_id,
            agent_run_id=request.agent_run_id, conversation_round_id=request.conversation_round_id,
            process_run_id=request.process_run_id, requester_user_id=requester,
            llm_id=llm.id, provider_name=llm.provider.name, provider_code=llm.provider.catalog_code,
            requested_model=llm.llm_name, effective_model=llm.llm_name, stream=False,
            is_subscription=llm.is_subscription,
            request_body={"model": llm.llm_name, "state": request.prompt,
                          "questions": {key: value.model_dump(mode="json") for key, value in request.questions.items()},
                          "messages": [{"role": "system", "content": request.system_prompt},
                                       {"role": "user", "content": request.prompt}]},
        ))
        result.metadata["llm_call_id"] = str(call.id)
        try:
            async with asyncio.timeout(timeout):
                response = await provider.decide(
                    connection, model=llm.llm_name,
                    state=f"{request.system_prompt}\n\n{request.prompt}",
                    questions=request.questions, timeout_seconds=timeout,
                )
            trace = {"usage": response.usage.model_dump(exclude_none=True),
                     "upstream_request_id": response.id, "model": response.model,
                     "response_text": response.model_dump_json()}
            decision = DecisionResult(answers=response.answers, model=response.model)
            try:
                decision.validate_questions(request.questions)
            except ValueError as exc:
                raise DecisionUnavailable(str(exc)) from exc
            result.structured_output = decision.model_dump(mode="json")
            result.result = decision.model_dump_json()
            return decision
        except TimeoutError as exc:
            failure = DecisionUnavailable("Decision provider timed out.")
            raise failure from exc
        except BaseException as exc:
            failure = exc
            raise
        finally:
            result.execution_time = time.monotonic() - started
            if failure is not None:
                result.success = False
                result.metadata["error"] = str(failure)
            # Finish the call even when the caller cancels; never start a fallback here.
            with anyio.CancelScope(shield=True):
                await llm_call_service.finalize_call(
                    call.id, trace=trace, raw_response=result.result,
                    status=("cancelled" if isinstance(failure, asyncio.CancelledError)
                            else "failed" if failure else "completed"),
                    error=str(failure) if failure else None,
                    input_rate=llm.cost_per_input_token,
                    output_rate=llm.cost_per_output_token,
                    effective_model=trace.get("model"),
                )
                await persist_events(call.id, [{"kind": "result", "result": result.model_dump(mode="json")}])
    finally:
        text_call_capture.reset(token)


async def execute_decision(
    request: DecisionInferenceRequest, *,
    on_event: Callable[[InferenceEvent], Awaitable[None]] | None = None,
) -> AIResult:
    from .inference_execution import transaction
    from .inference_facade import run_inference
    from . import inference_store

    async with asyncio.timeout(request.timeout_seconds):
        try:
            decision = await _native(request, request.timeout_seconds)
            result = AIResult(prompt=request.prompt, system_prompt=request.system_prompt)
        except DecisionUnavailable as exc:
            if (not request.allow_text_fallback or request.fallback_llm_id is None
                    or (request.request_limit is not None and request.request_limit < 2)):
                raise
            owner = inference_owner.get()
            if owner is not None:
                async def check_active() -> None:
                    operation, _ = await inference_store.owned(owner)
                    if operation.status != "running":
                        raise asyncio.CancelledError("Decision inference is stopping.")
                await transaction(check_active)
            fallback = await llm_service.get_llm(request.fallback_llm_id)
            if fallback is None or "chat" not in (fallback.service_capabilities or []):
                raise ValueError("Decision fallback requires a text model.")
            if not fallback.provider.is_active:
                raise ValueError("Decision fallback provider is inactive.")
            if request.model_bindings.get(str(fallback.id)) != model_binding(fallback):
                raise ValueError("Decision fallback binding changed after admission.")
            output_registry.register("galaris.decision.selection/v1", DecisionSelection, validator_factory=_validator)
            result = await run_inference(StructuredInferenceRequest(
                **request.model_dump(exclude={"schema_version", "questions", "fallback_llm_id",
                                              "allow_text_fallback", "timeout_seconds", "llm_id",
                                              "prompt", "request_limit", "model_bindings"}),
                llm_id=fallback.id,
                prompt=request.prompt + "\n\nSelect exactly one criterion for each question. Return selections.\n"
                + TypeAdapter(dict[str, ChoiceQuestion]).dump_json(request.questions).decode(),
                request_limit=1, output_retries=0,
                output=output_registry.specification("galaris.decision.selection/v1", context={
                    key: question.model_dump(mode="json") for key, question in request.questions.items()
                }),
            ), physical_call_limit=1, on_event=on_event)
            selection = DecisionSelection.model_validate(result.structured_output)
            decision = DecisionResult(
                answers={key: ChoiceAnswer(choice=value) for key, value in selection.selections.items()},
                source="text", model=fallback.llm_name, fallback_reason=str(exc),
            )
            decision.validate_questions(request.questions)
        result.structured_output = decision.model_dump(mode="json")
        result.result = decision.model_dump_json()
        result.metadata["decision"] = decision.model_dump(mode="json")
        return result
