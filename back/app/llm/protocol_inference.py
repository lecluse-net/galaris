"""Durable protocol requests; SDK and harness loops remain with their callers."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID, uuid4

import anyio
import httpx
import httpx2
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import select

from app.agent.contracts import AIResult
from core.database import get_db, release_db_transaction
from . import inference_execution as execution, inference_store, llm_service, proxy_service
from .accounting_scope import record_persisted_call_cost
from .call_capture import TextCallCapture, text_call_capture
from .contracts import InferenceEvent, ProtocolInferenceRequest
from .models import LLMCall, LLMCallEvent
from .provider_models import LLM
from .provider_facade import ProviderAuthenticationError, ReasoningEffort
from .profile_gateway import profile_error, resolve_profile_model
from .text_inference import RecordedTextModel, persist_events, message_for_part
from .trace import extract_prompts


async def _wire(capture: TextCallCapture, value: dict[str, Any]) -> None:
    if capture.call_id is None:
        raise RuntimeError("The protocol request has no persisted call.")
    await persist_events(capture.call_id, [{"kind": "wire", "wire": value}])


class _WireStream(httpx2.AsyncByteStream):
    def __init__(self, response: StreamingResponse, capture: TextCallCapture) -> None:
        self.response = response
        self.capture = capture

    async def __aiter__(self) -> AsyncIterator[bytes]:
        pending = bytearray()
        async for part in self.response.body_iterator:
            chunk = part.encode() if isinstance(part, str) else bytes(part)
            pending.extend(chunk)
            if b"\n\n" in pending or len(pending) >= 65536:
                chunk = bytes(pending)
                pending.clear()
                await _wire(self.capture, {"phase": "chunk", "data": base64.b64encode(chunk).decode()})
                yield chunk
        if pending:
            chunk = bytes(pending)
            await _wire(self.capture, {"phase": "chunk", "data": base64.b64encode(chunk).decode()})
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self.response.body_iterator, "aclose", None)
        if close is not None:
            await close()


class _ProtocolTransport(httpx2.AsyncBaseTransport):
    def __init__(self, request: ProtocolInferenceRequest, llm: LLM, capture: TextCallCapture) -> None:
        self.request = request
        self.llm = llm
        self.capture = capture
        self.used = False
        self.failure: BaseException | None = None

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        try:
            return await self.send(request)
        except BaseException as exc:
            self.failure = exc
            raise

    async def send(self, request: httpx2.Request) -> httpx2.Response:
        if self.used:
            raise RuntimeError("A protocol attempt must execute exactly one provider request.")
        self.used = True
        source = self.request
        options: dict[str, Any] = dict(
            llm_override=self.llm, task_id=source.task_id, agent_id=source.agent_id,
            agent_run_id=source.agent_run_id, conversation_round_id=source.conversation_round_id,
            process_run_id=source.process_run_id, purpose=source.purpose or None,
            reasoning_effort=source.reasoning_effort,
            force_reasoning_effort=source.force_reasoning_effort,
            route_executor_model=False, sdk_request=source.sdk_request,
            managed_runtime_request=source.managed_runtime_request,
            request_timeout=source.request_timeout,
        )
        body = source.model_copy(deep=True).body
        if source.protocol == "chat":
            response = await proxy_service.proxy_chat_completion(
                body, unwrap_deferred_tools=source.unwrap_deferred_tools, **options,
            )
        else:
            response = await proxy_service.proxy_responses(
                body, operation="compact" if source.protocol == "compact" else "create", **options,
            )
        await _wire(self.capture, {
            "phase": "headers", "status": response.status_code,
            "headers": dict(response.headers), "stream": isinstance(response, StreamingResponse),
        })
        if isinstance(response, StreamingResponse):
            return httpx2.Response(response.status_code, headers=dict(response.headers),
                                   stream=_WireStream(response, self.capture), request=request)
        content = bytes(response.body)
        await _wire(self.capture, {"phase": "body", "data": base64.b64encode(content).decode()})
        return httpx2.Response(response.status_code, headers=dict(response.headers), content=content,
                               request=request)


async def run_protocol(
    request: ProtocolInferenceRequest, *,
    on_event: Callable[[InferenceEvent], Awaitable[None]],
) -> AIResult:
    llm = await llm_service.get_llm(request.llm_id)
    if llm is None:
        raise LookupError("LLM not found.")

    async def publish(payload: dict[str, Any]) -> None:
        await on_event(InferenceEvent.model_validate(payload))

    capture = TextCallCapture(request=request.model_dump(mode="json"), publish=publish)
    token = text_call_capture.set(capture)
    result = AIResult(prompt=request.prompt, system_prompt=request.system_prompt)
    native = None
    transport = _ProtocolTransport(request, llm, capture)
    try:
        await release_db_transaction()
        client = httpx2.AsyncClient(transport=transport)
        async with AsyncOpenAI(api_key="internal", base_url="http://inference.invalid",
                              http_client=client, max_retries=0) as sdk:
            provider = OpenAIProvider(openai_client=sdk)
            model = (OpenAIChatModel(llm.llm_name, provider=provider) if request.protocol == "chat"
                     else OpenAIResponsesModel(llm.llm_name, provider=provider))
            if request.protocol == "compact":
                # Compaction is a protocol operation with an opaque state, not token generation.
                compact = await client.post("http://inference.invalid/responses/compact", json={})
                result.success = compact.is_success
                result.result = compact.text
            elif request.body.get("stream"):
                native = await RecordedTextModel(model, capture).request([], None, ModelRequestParameters())
            else:
                native = await model.request([], None, ModelRequestParameters())
                assert capture.call_id is not None
                for index, part in enumerate(native.parts):
                    message = message_for_part(capture.call_id, index, part)
                    if message is not None:
                        result.add_message(message)
                        events = await persist_events(capture.call_id, [{
                            "kind": "message", "message": message.model_dump(mode="json"),
                        }])
                        await publish(events[0])
    except BaseException as exc:
        exc = transport.failure or exc
        result.success = False
        result.metadata.update(error=str(exc) or type(exc).__name__, error_type=type(exc).__name__)
        if isinstance(exc, ProviderAuthenticationError):
            result.metadata["error_status"] = exc.status_code
        if isinstance(exc, asyncio.CancelledError):
            raise
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        try:
            if capture.results:
                metadata = dict(result.metadata)
                result = AIResult.model_validate(capture.results[-1])
                result.metadata.update(metadata)
            elif capture.call_id is not None:
                events = await persist_events(capture.call_id, [{"kind": "result", "result": result.model_dump(mode="json")}])
                result = AIResult.model_validate(events[0]["result"])
                await publish(events[0])
        finally:
            text_call_capture.reset(token)
    if native is not None:
        result.metadata["sdk_response"] = ModelMessagesTypeAdapter.dump_python([native], mode="json")
    return result


async def _read_wire(attempt_id: UUID, cursor: int) -> list[tuple[int, dict[str, Any]]]:
    rows = await get_db().scalars(select(LLMCallEvent).join(LLMCall).where(
        LLMCall.inference_attempt_id == attempt_id,
        LLMCallEvent.inference_sequence > cursor,
        LLMCallEvent.payload["kind"].astext == "wire",
    ).order_by(LLMCallEvent.inference_sequence).limit(500))
    return [(row.inference_sequence or 0, row.payload["wire"]) for row in rows]


async def _generation_completed(attempt_id: UUID | None) -> bool:
    if attempt_id is None:
        return False
    statuses = list(await get_db().scalars(select(LLMCall.status).where(
        LLMCall.inference_attempt_id == attempt_id,
    )))
    return bool(statuses) and all(status == "completed" for status in statuses)


def _raise_failure(result: AIResult | None) -> None:
    metadata = result.metadata if result is not None else {}
    message = str(metadata.get("error", "The inference was interrupted."))
    kind = metadata.get("error_type")
    if kind == "ProviderAuthenticationError":
        raise ProviderAuthenticationError(message, status_code=int(metadata.get("error_status", 401)))
    if kind in {"TimeoutException", "ReadTimeout", "ConnectTimeout", "PoolTimeout", "WriteTimeout"}:
        raise httpx.TimeoutException(message)
    if kind in {"TransportError", "ReadError", "ConnectError", "RemoteProtocolError"}:
        raise httpx.TransportError(message)
    if kind == "LookupError":
        raise LookupError(message)
    if kind in {"ValueError", "TypeError"}:
        raise ValueError(message)
    raise RuntimeError(message)


async def protocol_response(request: ProtocolInferenceRequest) -> JSONResponse | StreamingResponse:
    key = uuid4()
    attempt_id: UUID | None = None
    completed = False

    async def cleanup() -> None:
        with anyio.CancelScope(shield=True):
            with suppress(LookupError, ValueError):
                if not completed:
                    snapshot = await execution.read(key)
                    if snapshot.status not in inference_store.TERMINAL_ATTEMPTS:
                        # SDKs close after their terminal frame. If generation is
                        # already committed, wait for the journal writer instead
                        # of turning its successful response into a stop command.
                        if not await execution.transaction(lambda: _generation_completed(attempt_id)):
                            await execution.command(key, "stop", uuid4())
                        async for _ in execution.events(key):
                            pass
                _, costs = await execution.transaction(lambda: inference_store.execution_details(key))
                for call_id, cost in costs.items():
                    record_persisted_call_cost(call_id, cost)

    async def wire_events() -> AsyncGenerator[dict[str, Any]]:
        assert attempt_id is not None
        selected_attempt = attempt_id
        cursor = 0
        while True:
            batch = await execution.transaction(lambda cursor=cursor: _read_wire(selected_attempt, cursor))
            for cursor, payload in batch:
                yield payload
            snapshot = await execution.read(key)
            attempt = next(item for item in snapshot.attempts if item.id == attempt_id)
            if attempt.status in inference_store.TERMINAL_ATTEMPTS and not batch:
                if attempt.result is None or not attempt.result.success:
                    _raise_failure(attempt.result)
                return
            await asyncio.sleep(execution.POLL_SECONDS)

    stream = wire_events()
    try:
        await execution.submit(request, inference_id=key)
        attempt_id = (await execution.read(key)).attempts[-1].id
        headers = await anext(stream)
        if headers["phase"] != "headers":
            raise RuntimeError("Missing durable protocol response headers.")
        response_headers = {**headers["headers"], "X-Galaris-Inference-Id": str(key)}
        if not headers["stream"]:
            body = await anext(stream)
            # HTTP error envelopes keep their original status and body.
            with suppress(RuntimeError):
                async for _ in stream:
                    pass
            completed = True
            return JSONResponse(json.loads(base64.b64decode(body["data"])), status_code=headers["status"],
                                headers=response_headers)

        async def relay() -> AsyncIterator[bytes]:
            nonlocal completed
            try:
                async for item in stream:
                    if item["phase"] == "chunk":
                        yield base64.b64decode(item["data"])
                completed = True
            finally:
                await stream.aclose()
                await cleanup()

        return StreamingResponse(relay(), status_code=headers["status"], headers=response_headers)
    except BaseException:
        await stream.aclose()
        await cleanup()
        raise
    finally:
        if completed:
            await cleanup()


async def _request(
    body: dict[str, Any], *, protocol: Literal["chat", "responses", "compact"],
    task_id: UUID | None, agent_id: int | None = None, agent_run_id: UUID | None = None,
    conversation_round_id: UUID | None = None, process_run_id: UUID | None = None,
    purpose: str | None = None, llm_override: LLM | None = None, model_code: str | None = None,
    route_executor_model: bool = True, managed_runtime_request: bool = False,
    reasoning_effort: ReasoningEffort | None = None, force_reasoning_effort: bool = False,
    sdk_request: bool = False, unwrap_deferred_tools: bool = False,
    request_timeout: dict[str, float | None] | None = None,
    profile_model: bool = False,
) -> JSONResponse | StreamingResponse:
    if managed_runtime_request and task_id is None:
        from core.i18n import tr

        raise ValueError(await tr("llm_api.errors.managed_runtime_task_required"))
    async def resolve() -> tuple[LLM, ReasoningEffort | None]:
        if profile_model:
            selection = await resolve_profile_model(body.get("model"), "chat")
            task_llm = await proxy_service.resolve_task_executor_llm(task_id) if task_id else None
            if ((llm_override is not None and llm_override.id != selection.llm.id)
                    or (model_code is not None and model_code != selection.selector)
                    or (task_llm is not None and task_llm.id != selection.llm.id)):
                raise ValueError(await profile_error("profile_selector_conflict", model=selection.selector))
            policy = await proxy_service.resolve_task_reasoning_effort(task_id, agent_run_id)
            effort = (reasoning_effort if force_reasoning_effort and reasoning_effort is not None
                      else policy.effort if policy.resolved else selection.reasoning_effort)
            return selection.llm, effort
        task_llm = (await proxy_service.resolve_task_executor_llm(task_id)
                    if route_executor_model and llm_override is None and model_code is None else None)
        llm = llm_override or task_llm or await proxy_service.resolve_proxy_llm(
            model_code or body.get("model"), agent_id=agent_id,
        )
        policy = (await proxy_service.resolve_task_reasoning_effort(task_id, agent_run_id)
                  if route_executor_model else proxy_service.TaskReasoningPolicy(resolved=False))
        effort = (reasoning_effort if force_reasoning_effort and reasoning_effort is not None
                  else policy.effort if policy.resolved else reasoning_effort)
        return llm, effort

    llm, effort = await execution.transaction(resolve)
    from .message_cleanup import clean_request_messages

    messages = (clean_request_messages(body.get("messages")) if protocol == "chat"
                else proxy_service.responses_request_messages(body))
    prompt, system_prompt = extract_prompts(messages)
    request = ProtocolInferenceRequest(
        llm_id=llm.id, task_id=task_id, agent_id=agent_id, agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id, process_run_id=process_run_id,
        prompt=prompt, system_prompt=system_prompt, purpose=purpose or "",
        reasoning_effort=effort, body=body, protocol=protocol,
        sdk_request=sdk_request, managed_runtime_request=managed_runtime_request,
        force_reasoning_effort=force_reasoning_effort, unwrap_deferred_tools=unwrap_deferred_tools,
        request_timeout=request_timeout,
        correlation_ref=str(body.get("model")) if profile_model else None,
    )
    return await protocol_response(request)


async def proxy_chat_completion(body: dict[str, Any], **options: Any) -> JSONResponse | StreamingResponse:
    return await _request(body, protocol="chat", **options)


async def proxy_responses(
    body: dict[str, Any], *, operation: Literal["create", "compact"] = "create", **options: Any,
) -> JSONResponse | StreamingResponse:
    return await _request(body, protocol="compact" if operation == "compact" else "responses", **options)
