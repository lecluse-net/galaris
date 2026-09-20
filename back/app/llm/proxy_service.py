"""Experimental OpenAI-compatible proxy."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional
from uuid import UUID

import httpx
import anyio
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from core.database import get_db_session
from core.i18n import render_prompt, t, tr
from . import llm_call_service, llm_provider_service, llm_service, model_usages
from core.util import as_dict, as_list
from .provider_models import LLM
from .provider_facade import (
    ChatStreamAdapter,
    ProviderAuthenticationError,
    ReasoningEffort,
    ResponsesOperation,
    chat_transport_for,
    openai_protocol_base_url,
    responses_transport_for,
    adapt_request_parameters,
    request_parameter_policy_for,
)
from .resource_discovery import provider_connection
from .responses_trace import (
    ResponsesStreamTrace,
    request_messages as responses_request_messages,
    response_trace as responses_response_trace,
)
from .reasoning import (
    effective_reasoning_effort,
    normalize_reasoning_effort,
)
from .trace import StreamTrace, response_trace
from .subscription_policy import enforce_subscription_access


PROXY_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)
_PARTIAL_UPDATE_INTERVAL = 0.5


async def _send_best_effort(
    client: httpx.AsyncClient, endpoint: str, headers: dict[str, str],
    body: dict[str, Any], *, stream: bool,
) -> httpx.Response:
    from copy import deepcopy
    from .request_parameters import PAYLOAD_PARAMETERS

    forwarded = deepcopy(body)
    # Preserve functional requirements, including budgets and structured output.
    budgets = {"max_tokens", "max_output_tokens", "max_completion_tokens", "budget_tokens"}
    required = PAYLOAD_PARAMETERS | budgets

    def contains_budget(value: object) -> bool:
        return isinstance(value, dict) and any(
            key in budgets or contains_budget(child) for key, child in as_dict(value).items()
        )

    while True:
        response = await client.send(
            client.build_request("POST", endpoint, headers=headers, json=forwarded), stream=stream,
        )
        if response.status_code not in {400, 422}:
            return response
        await response.aread()
        try:
            error = as_dict(response.json().get("error"))
        except (ValueError, AttributeError):
            return response
        parameter = error.get("param")
        if (error.get("code") not in {"unsupported_parameter", "unsupported_value", "unknown_parameter"}
                or not isinstance(parameter, str)):
            return response
        path = [parameter] if parameter in forwarded else parameter.split(".")
        if (not all(path) or any(part in budgets for part in path)
                or (path[0] in required and path != ["text", "verbosity"])):
            return response
        parent = forwarded
        for part in path[:-1]:
            child = parent.get(part)
            if not isinstance(child, dict):
                return response
            parent = as_dict(child)
        if path[-1] not in parent or contains_budget(parent[path[-1]]):
            return response
        # Only an explicit, pre-generation rejection permits a reduced request.
        # Never retry a rate limit, transport failure or a partially delivered stream.
        # Each retry removes an existing field, so nested negotiation is bounded too.
        del parent[path[-1]]
        await response.aclose()


async def _run_stream_cleanup(
    operation: Callable[[], Awaitable[None]],
    *,
    call_id: UUID,
    operation_name: str,
) -> None:
    """Run bounded persistence/transport cleanup outside an HTTP cancel scope."""

    with anyio.CancelScope(shield=True):
        try:
            with anyio.fail_after(10.0):
                await operation()
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.opt(exception=exc).error(
                "LLM {} failed for call {}", operation_name, call_id
            )


async def _finish_cancelled_request(client: httpx.AsyncClient, call_id: UUID, llm: LLM) -> None:
    """A cancellation before response headers must not leave a running call or client."""
    async def finalize() -> None:
        await llm_call_service.finalize_call(
            call_id, trace={}, status="cancelled", error="LLM request cancelled before response headers.",
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )

    await _run_stream_cleanup(finalize, call_id=call_id, operation_name="request cancellation")
    await _run_stream_cleanup(client.aclose, call_id=call_id, operation_name="request cleanup")


def _response_headers(upstream: httpx.Response, call_id: UUID) -> dict[str, str]:
    """Keep retry guidance and correlation without forwarding provider cookies."""
    headers = {"X-Galaris-LLM-Call-Id": str(call_id)}
    for name in ("retry-after", "retry-after-ms", "x-request-id"):
        if value := upstream.headers.get(name):
            headers[name] = value
    return headers


def _upstream_response_succeeded(http_success: bool, payload: dict[str, Any]) -> bool:
    """Reject OpenAI error envelopes even when the provider returns HTTP 200."""
    return http_success and payload.get("error") is None


def _remove_galaris_fields(body: dict[str, Any]) -> None:
    for key in tuple(body):
        if key.startswith("galaris_"):
            body.pop(key, None)


def parse_proxy_model(value: Any) -> int:
    """Parse the legacy ``llm-<id>`` technical alias.

    Existing managed runtimes retain compatibility; new external clients should use ``LLM.code``.
    """
    raw = str(value or "").strip()
    if raw.startswith("llm-"):
        raw = raw[4:]
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(t("llm_api.errors.invalid_proxy_model")) from exc


async def resolve_proxy_llm(
    value: Any,
    *,
    agent_id: int | None = None,
) -> LLM:
    """Resolve a proxy model by code, text-tier alias, or legacy identifier."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(await tr("llm_api.errors.model_required"))

    llm = await llm_service.get_llm_by_code(raw)
    if llm is not None:
        return llm

    tier = model_usages.text_tier_for_alias(raw)
    if tier is not None:
        llm = await llm_service.get_profile_llm_for_agent_id(tier, agent_id)
        if llm is not None:
            return llm

    # Legacy managed-runtime compatibility for ``llm-17`` and integer identifiers.
    try:
        llm_id = parse_proxy_model(raw)
    except ValueError as exc:
        raise LookupError(
            render_prompt(
                await tr("llm_api.errors.llm_code_not_found"),
                llm_id=raw,
            )
        ) from exc

    llm = await llm_service.get_llm(llm_id)
    if llm is None:
        raise LookupError(
            render_prompt(
                await tr("llm_api.errors.llm_code_not_found"),
                llm_id=raw,
            )
        )
    return llm


async def resolve_task_executor_llm(task_id: UUID | None) -> LLM | None:
    """Return a task-specific high or standard executor override."""
    if task_id is None:
        return None

    from app.task import task_service

    task = await task_service.get_by_id(task_id)
    if task is None:
        return None
    effort = str(task.effort or "standard").strip().lower()
    if effort != "high":
        return None
    return await llm_service.get_executor_llm_for_task(task)


@dataclass(frozen=True, slots=True)
class TaskReasoningPolicy:
    """A task policy distinguishes frozen automatic mode from no task policy."""

    resolved: bool
    effort: ReasoningEffort | None = None


async def resolve_task_reasoning_effort(
    task_id: UUID | None,
    agent_run_id: UUID | None,
) -> TaskReasoningPolicy:
    """Return the effort frozen for a run, with a profile fallback for legacy tasks."""

    if task_id is None:
        return TaskReasoningPolicy(resolved=False)
    from app.task import task_service

    task = await task_service.get_by_id(task_id)
    if task is None:
        return TaskReasoningPolicy(resolved=False)
    task_override = normalize_reasoning_effort(
        getattr(task, "reasoning_effort_override", None)
    )
    if task_override is not None:
        return TaskReasoningPolicy(resolved=True, effort=task_override)
    task_data = as_dict(task.data)
    identity = as_dict(task_data.get("_agent_run_identity"))
    frozen_run_id = str(identity.get("request_run_id") or "")
    if (
        (agent_run_id is None or frozen_run_id == str(agent_run_id))
        and "reasoning_effort" in identity
    ):
        return TaskReasoningPolicy(
            resolved=True,
            effort=normalize_reasoning_effort(identity.get("reasoning_effort")),
        )

    model_field = model_usages.EXECUTOR
    if str(task.effort or "standard").strip().lower() == "high":
        high_llm = await llm_service.get_profile_llm(
            model_usages.EXECUTOR_HIGH,
            agent=task.agent,
        )
        if high_llm is not None:
            model_field = model_usages.EXECUTOR_HIGH
    return TaskReasoningPolicy(
        resolved=True,
        effort=await llm_service.get_profile_reasoning_effort(
            model_field,
            agent=task.agent,
        ),
    )


def _chat_completion_from_stream_trace(
    trace: StreamTrace,
    *,
    model: str,
    response_id: str | None = None,
    created: int | None = None,
) -> dict[str, Any]:
    """Collapse converted Chat Completions chunks into one ordinary completion."""
    trace_data = trace.result()
    metadata = trace.raw_payloads[0] if trace.raw_payloads else {}
    raw_tools = as_list(trace_data.get("tool_calls"))
    tool_calls: list[dict[str, Any]] = []
    for index, raw_tool in enumerate(raw_tools):
        tool = as_dict(raw_tool)
        arguments = tool.get("arguments")
        serialized_arguments = (
            arguments
            if isinstance(arguments, str)
            else json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)
        )
        tool_calls.append({
            "id": str(tool.get("id") or f"tool-{index}"),
            "type": str(tool.get("type") or "function"),
            "function": {
                "name": str(tool.get("name") or "unknown"),
                "arguments": serialized_arguments,
            },
        })

    message: dict[str, Any] = {
        "role": "assistant",
        "content": str(trace_data.get("response_text") or "") or None,
    }
    reasoning = str(trace_data.get("reasoning") or "")
    if reasoning:
        message["reasoning_content"] = reasoning
    if tool_calls:
        message["tool_calls"] = tool_calls

    completion: dict[str, Any] = {
        "id": str(trace_data.get("upstream_request_id") or response_id or ""),
        "object": "chat.completion",
        "model": str(metadata.get("model") or model),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": (
                str(trace_data.get("finish_reason"))
                if trace_data.get("finish_reason")
                else "tool_calls" if tool_calls else "stop"
            ),
        }],
        "usage": as_dict(trace_data.get("usage")),
    }
    effective_created = metadata.get("created", created)
    if isinstance(effective_created, int):
        completion["created"] = effective_created
    for key in ("provider", "service_tier", "system_fingerprint"):
        if metadata.get(key) is not None:
            completion[key] = metadata[key]
    return completion


def _serialized_final_chat_completion(trace: StreamTrace, *, model: str) -> str:
    """Serialize one complete result, or nothing until a terminal chunk exists."""

    if not trace.finish_reason:
        return ""
    return json.dumps(
        _chat_completion_from_stream_trace(trace, model=model),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _serialized_final_responses_result(trace: ResponsesStreamTrace) -> str:
    """Serialize only the terminal Responses object, never its SSE event envelope."""

    if trace.terminal_response is None:
        return ""
    return json.dumps(
        trace.terminal_response,
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def _consume_adapted_stream_as_completion(
    upstream: httpx.Response,
    *,
    model: str,
    adapter: ChatStreamAdapter,
) -> tuple[dict[str, Any], str]:
    """Consume an adapted SSE response while preserving a non-streaming contract."""
    trace = StreamTrace()
    async for line in upstream.aiter_lines():
        decoded_event: dict[str, Any] | None = None
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    decoded = json.loads(data)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    decoded_event = as_dict(decoded)
        if adapter.terminal:
            continue
        if decoded_event is None:
            continue
        for payload in adapter.convert(decoded_event):
            trace.add_payload(payload)
    if not adapter.terminal:
        raise RuntimeError("the provider stream ended before its terminal response")
    payload = _chat_completion_from_stream_trace(
        trace,
        model=adapter.model or model,
        response_id=adapter.response_id,
        created=adapter.created,
    )
    return payload, json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def proxy_chat_completion(
    body: dict[str, Any],
    *,
    purpose: str | None = None,
    task_id: Optional[UUID],
    agent_run_id: Optional[UUID] = None,
    conversation_round_id: Optional[UUID] = None,
    process_run_id: Optional[UUID] = None,
    agent_id: Optional[int] = None,
    llm_override: LLM | None = None,
    route_executor_model: bool = True,
    unwrap_deferred_tools: bool = False,
    managed_runtime_request: bool = False,
    reasoning_effort: ReasoningEffort | None = None,
    force_reasoning_effort: bool = False,
    sdk_request: bool = False,
    request_timeout: dict[str, float | None] | None = None,
) -> JSONResponse | StreamingResponse:
    # Route to the selected provider, record the trace, and forward the payload. The gateway never
    # manufactures an LLM answer. Provider policies adapt generation controls after routing;
    # message cleanup remains limited to Galaris-owned conversations.
    from .message_cleanup import clean_request_messages

    if managed_runtime_request and task_id is None:
        raise ValueError(await tr("llm_api.errors.managed_runtime_task_required"))

    body["messages"] = clean_request_messages(body.get("messages"))
    forwarded = dict(body)
    requested_model = str(body.get("model") or "")
    async with get_db_session():
        cancelled_message = await tr("llm_api.client_disconnected") if body.get("stream") else ""
        task_reasoning = (
            await resolve_task_reasoning_effort(task_id, agent_run_id)
            if route_executor_model
            else TaskReasoningPolicy(resolved=False)
        )
        configured_reasoning = (
            task_reasoning.effort if task_reasoning.resolved else reasoning_effort
        )
        applied_reasoning = effective_reasoning_effort(
            (
                reasoning_effort
                if force_reasoning_effort and reasoning_effort is not None
                else forwarded.get("reasoning_effort")
            ),
            configured=configured_reasoning,
            force=force_reasoning_effort,
        )
        if applied_reasoning is not None and not sdk_request:
            forwarded["reasoning_effort"] = applied_reasoning
        task_llm = (
            None
            if llm_override is not None or not route_executor_model
            else await resolve_task_executor_llm(task_id)
        )
        llm = llm_override or task_llm or await resolve_proxy_llm(
            body.get("model"),
            agent_id=agent_id,
        )
        provider_data = await llm_provider_service.get_provider_with_decrypted_key(llm.llm_provider_id)
        if provider_data is None:
            raise LookupError(
                render_prompt(
                    await tr("llm_api.errors.provider_for_llm_not_found"),
                    llm_code=llm.code,
                )
            )
        provider, api_key = provider_data
        if not provider.is_active:
            raise ValueError(
                render_prompt(
                    await tr("llm_api.errors.provider_inactive"),
                    provider_name=provider.name,
                )
            )
        requester_user_id = await enforce_subscription_access(
            provider,
            task_id=task_id,
            conversation_round_id=conversation_round_id,
            process_run_id=process_run_id,
        )
        connection = provider_connection(provider, api_key)
        transport = chat_transport_for(connection)
        _remove_galaris_fields(forwarded)
        forwarded = adapt_request_parameters(
            forwarded, request_parameter_policy_for(connection, llm.llm_name), "chat",
        )

        stream = bool(forwarded.get("stream", False))
        bridge_transport_nonstream = (
            transport is not None and transport.stream_only and not stream
        )

        if purpose is None:
            if managed_runtime_request:
                from .purposes import LLMCallPurpose

                purpose = LLMCallPurpose.AGENT_EXEC
            elif process_run_id is not None:
                from .purposes import LLMCallPurpose

                purpose = LLMCallPurpose.PROCESS_EXEC

        call = await llm_call_service.create_running_call(
            purpose=purpose,
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            process_run_id=process_run_id,
            requester_user_id=requester_user_id,
            agent_id=agent_id,
            llm_id=llm.id,
            provider_name=provider.name,
            provider_code=provider.catalog_code or (
                provider.provider_type
                if provider.provider_type != "openai_compatible"
                else None
            ),
            requested_model=requested_model,
            effective_model=llm.llm_name,
            reasoning_effort=applied_reasoning,
            stream=stream,
            request_body=body,
            is_subscription=bool(getattr(llm, "is_subscription", False)),
        )

    forwarded["model"] = llm.llm_name
    forwarded.pop("galaris_task_id", None)
    forwarded.pop("galaris_agent_run_id", None)
    forwarded.pop("galaris_conversation_round_id", None)
    forwarded.pop("galaris_process_run_id", None)
    forwarded.pop("galaris_correlation_id", None)
    forwarded.pop("galaris_workflow_id", None)
    forwarded.pop("galaris_engine_run_id", None)
    forwarded.pop("galaris_effort", None)
    forwarded.pop("galaris_executor_llm_tier", None)
    forwarded.pop("galaris_llm_tier", None)
    forwarded.pop("galaris_llm_id", None)
    forwarded.pop("galaris_reasoning_effort", None)
    forwarded.pop("galaris_force_reasoning_effort", None)

    base_url = openai_protocol_base_url(connection)
    canonical_forwarded = dict(forwarded)
    client = httpx.AsyncClient(
        timeout=PROXY_TIMEOUT if request_timeout is None else httpx.Timeout(**request_timeout),
    )
    upstream_stream = stream or bridge_transport_nonstream
    try:
        if transport is not None:
            prepared = await transport.prepare_request(
                provider.id,
                connection,
                canonical_forwarded,
                force_stream=bridge_transport_nonstream,
            )
            headers = prepared.headers
            forwarded = prepared.body
            endpoint = prepared.endpoint
            if bridge_transport_nonstream:
                logger.info(
                    "LLM proxy: bridging a non-streaming call through a stream-only "
                    "provider task={} agent={}",
                    task_id,
                    agent_id,
                )
        else:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            endpoint = f"{base_url}/chat/completions"
        upstream = await _send_best_effort(client, endpoint, headers, forwarded, stream=upstream_stream)
        if transport is not None and upstream.status_code == 401:
            await upstream.aclose()
            async with get_db_session():
                prepared = await transport.prepare_request(
                    provider.id,
                    connection,
                    canonical_forwarded,
                    force_refresh=True,
                    force_stream=bridge_transport_nonstream,
                )
            headers = prepared.headers
            forwarded = prepared.body
            endpoint = prepared.endpoint
            upstream = await _send_best_effort(client, endpoint, headers, forwarded, stream=upstream_stream)
    except asyncio.CancelledError:
        await _finish_cancelled_request(client, call.id, llm)
        raise
    except ProviderAuthenticationError as exc:
        await client.aclose()
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            status="error",
            error=str(exc),
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        raise
    except Exception as exc:
        await client.aclose()
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            status="error",
            error=str(exc),
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        if sdk_request and isinstance(exc, httpx.TransportError):
            raise
        raise RuntimeError(render_prompt(
            await tr("llm_api.errors.provider_connection_error"), error=exc
        )) from exc

    if not stream:
        try:
            if bridge_transport_nonstream and upstream.is_success:
                try:
                    adapter = (
                        transport.create_stream_adapter(llm.llm_name)
                        if transport is not None
                        else None
                    )
                    if adapter is None:
                        raise RuntimeError(
                            "the provider did not supply its required stream adapter"
                        )
                    payload, raw_response = await _consume_adapted_stream_as_completion(
                        upstream,
                        model=llm.llm_name,
                        adapter=adapter,
                    )
                except Exception as exc:
                    await llm_call_service.finalize_call(
                        call.id,
                        trace={},
                        raw_response="",
                        status="error",
                        error=str(exc),
                        input_rate=llm.cost_per_input_token,
                        cached_input_rate=llm.cost_per_cached_input_token,
                        output_rate=llm.cost_per_output_token,
                    )
                    raise RuntimeError(render_prompt(
                        await tr("llm_api.errors.provider_connection_error"),
                        error=exc,
                    )) from exc
            else:
                raw = await upstream.aread()
                raw_response = raw.decode("utf-8", errors="replace")
                try:
                    decoded = json.loads(raw)
                    payload = as_dict(decoded) if isinstance(decoded, dict) else {"data": decoded}
                except json.JSONDecodeError:
                    payload = {"error": {"message": raw.decode(errors="replace")}}
                if transport is not None and upstream.is_success:
                    payload = transport.normalize_response(
                        payload,
                        model=llm.llm_name,
                    )
            provider_success = _upstream_response_succeeded(upstream.is_success, payload)
            trace = (
                response_trace(
                    payload,
                    unwrap_deferred_tools=unwrap_deferred_tools,
                )
                if provider_success
                else {}
            )
            error_detail = payload.get("error") or payload
            await llm_call_service.finalize_call(
                call.id,
                trace=trace,
                raw_response=raw_response,
                status="completed" if provider_success else "error",
                error=None if provider_success else str(error_detail),
                input_rate=llm.cost_per_input_token,
                cached_input_rate=llm.cost_per_cached_input_token,
                output_rate=llm.cost_per_output_token,
            )
            return JSONResponse(
                content=payload,
                status_code=(
                    upstream.status_code
                    if provider_success or not upstream.is_success
                    else 502
                ),
                headers=_response_headers(upstream, call.id),
            )
        finally:
            await upstream.aclose()
            await client.aclose()

    if not upstream.is_success:
        raw = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        message = raw.decode(errors="replace")
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            raw_response=message,
            status="error",
            error=message,
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        try:
            decoded = json.loads(raw)
            payload = as_dict(decoded) if isinstance(decoded, dict) else {"data": decoded}
        except json.JSONDecodeError:
            payload = {"error": {"message": message}}
        return JSONResponse(content=payload, status_code=upstream.status_code, headers=_response_headers(upstream, call.id))

    trace = StreamTrace()
    stream_adapter = (
        transport.create_stream_adapter(llm.llm_name)
        if transport is not None
        else None
    )

    async def relay() -> AsyncIterator[bytes]:
        first_token_at: datetime | None = None
        error: str | None = None
        status = "completed"
        stream_completed = False
        last_partial_update = 0.0

        async def track_payload(payload: dict[str, Any]) -> None:
            nonlocal first_token_at, last_partial_update
            before = (
                len(trace.response_parts),
                len(trace.reasoning_parts),
                len(trace.tools),
            )
            trace.add_payload(payload)
            after = (
                len(trace.response_parts),
                len(trace.reasoning_parts),
                len(trace.tools),
            )
            if first_token_at is None and after != before:
                first_token_at = datetime.now(timezone.utc)
            now = time.monotonic()
            if after != before and now - last_partial_update >= _PARTIAL_UPDATE_INTERVAL:
                last_partial_update = now
                try:
                    await llm_call_service.update_running_call(
                        call.id,
                        trace=trace.result(
                            unwrap_deferred_tools=unwrap_deferred_tools,
                        ),
                        first_token_at=first_token_at,
                        input_rate=llm.cost_per_input_token,
                        cached_input_rate=llm.cost_per_cached_input_token,
                        output_rate=llm.cost_per_output_token,
                    )
                except Exception:
                    logger.exception("LLM trace partial update failed for call {}", call.id)

        try:
            if stream_adapter is not None:
                async for line in upstream.aiter_lines():
                    decoded_event: dict[str, Any] | None = None
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data and data != "[DONE]":
                            try:
                                decoded = json.loads(data)
                            except json.JSONDecodeError:
                                decoded = None
                            if isinstance(decoded, dict):
                                decoded_event = as_dict(decoded)
                    if stream_adapter.terminal:
                        continue
                    if decoded_event is None:
                        continue
                    for payload in stream_adapter.convert(decoded_event):
                        await track_payload(payload)
                        serialized = json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        yield f"data: {serialized}\n\n".encode("utf-8")
                if not stream_adapter.terminal:
                    raise RuntimeError(
                        "the provider stream ended before its terminal response"
                    )
                stream_completed = True
                yield b"data: [DONE]\n\n"
            else:
                received_done = False
                async for line in upstream.aiter_lines():
                    if line.startswith("data:") and line[5:].strip() == "[DONE]":
                        received_done = True
                        stream_completed = True
                    if line.startswith("data:") and line[5:].strip() != "[DONE]":
                        try:
                            decoded = json.loads(line[5:].strip())
                            if not isinstance(decoded, dict):
                                yield (line + "\n").encode("utf-8")
                                continue
                            await track_payload(as_dict(decoded))
                        except json.JSONDecodeError:
                            pass
                    yield (line + "\n").encode("utf-8")
                if not received_done and not trace.finish_reason:
                    raise RuntimeError("the provider stream ended before its terminal response")
                stream_completed = True
        except asyncio.CancelledError:
            # Some clients disconnect after the terminal chunk without waiting for SSE [DONE].
            # A provider finish reason proves generation completed, so do not turn successful
            # work and tool effects into a task error.
            if trace.finish_reason:
                status = "completed"
                error = None
            else:
                status = "cancelled"
                error = cancelled_message
            raise
        except Exception as exc:
            status = "error"
            error = str(exc)
            raise
        finally:
            if status == "completed" and not stream_completed and not trace.finish_reason:
                # ASGI may close an async body iterator with GeneratorExit rather than
                # CancelledError. An incomplete stream must still stop being reported as
                # a live LLM call immediately.
                status = "cancelled"
                error = "LLM stream closed before a terminal provider response."

            async def finalize_trace() -> None:
                await llm_call_service.finalize_call(
                    call.id,
                    trace=trace.result(
                        unwrap_deferred_tools=unwrap_deferred_tools,
                    ),
                    raw_response=_serialized_final_chat_completion(
                        trace,
                        model=llm.llm_name,
                    ),
                    status=status,
                    error=error,
                    input_rate=llm.cost_per_input_token,
                    cached_input_rate=llm.cost_per_cached_input_token,
                    output_rate=llm.cost_per_output_token,
                    first_token_at=first_token_at,
                )

            # Persist the terminal trace before potentially slow HTTP shutdown. In the
            # incident this ordering left a cancelled provider call marked ``running`` for
            # another complete Task timeout window.
            await _run_stream_cleanup(
                finalize_trace,
                call_id=call.id,
                operation_name="trace finalization",
            )

            async def close_transport() -> None:
                await upstream.aclose()
                await client.aclose()

            await _run_stream_cleanup(
                close_transport,
                call_id=call.id,
                operation_name="upstream cleanup",
            )

    response_headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Galaris-LLM-Call-Id": str(call.id),
    }
    return StreamingResponse(relay(), media_type="text/event-stream", headers=response_headers)


async def proxy_responses(
    body: dict[str, Any],
    *,
    operation: ResponsesOperation = "create",
    purpose: str | None = None,
    task_id: UUID | None,
    agent_run_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
    process_run_id: UUID | None = None,
    agent_id: int | None = None,
    model_code: str | None = None,
    llm_override: LLM | None = None,
    route_executor_model: bool = True,
    managed_runtime_request: bool = False,
    reasoning_effort: ReasoningEffort | None = None,
    force_reasoning_effort: bool = False,
    sdk_request: bool = False,
    request_timeout: dict[str, float | None] | None = None,
) -> JSONResponse | StreamingResponse:
    """Forward a native Responses call and persist one correlated ``LLMCall``."""

    if managed_runtime_request and task_id is None:
        raise ValueError(await tr("llm_api.errors.managed_runtime_task_required"))
    if operation == "compact" and body.get("stream"):
        raise ValueError("Responses compaction does not support streaming.")

    requested_model = str(model_code or body.get("model") or "")
    forwarded = dict(body)
    trace_body = {"messages": responses_request_messages(body)}
    async with get_db_session():
        cancelled_message = await tr("llm_api.client_disconnected") if body.get("stream") else ""
        task_reasoning = (
            await resolve_task_reasoning_effort(task_id, agent_run_id)
            if route_executor_model
            else TaskReasoningPolicy(resolved=False)
        )
        configured_reasoning = (
            task_reasoning.effort if task_reasoning.resolved else reasoning_effort
        )
        applied_reasoning = (
            None
            if operation == "compact"
            else effective_reasoning_effort(
                (
                    reasoning_effort
                    if force_reasoning_effort and reasoning_effort is not None
                    else as_dict(forwarded.get("reasoning")).get("effort")
                    or forwarded.get("reasoning_effort")
                ),
                configured=configured_reasoning,
                force=force_reasoning_effort,
            )
        )
        if operation == "compact":
            forwarded.pop("reasoning", None)
        elif applied_reasoning is not None and not sdk_request:
            forwarded["reasoning"] = {
                **as_dict(forwarded.get("reasoning")),
                "effort": applied_reasoning,
            }
        forwarded.pop("reasoning_effort", None)
        task_llm = (
            None
            if llm_override is not None or model_code is not None or not route_executor_model
            else await resolve_task_executor_llm(task_id)
        )
        llm = llm_override or task_llm or await resolve_proxy_llm(
            requested_model,
            agent_id=agent_id,
        )
        provider_data = await llm_provider_service.get_provider_with_decrypted_key(
            llm.llm_provider_id
        )
        if provider_data is None:
            raise LookupError(
                render_prompt(
                    await tr("llm_api.errors.provider_for_llm_not_found"),
                    llm_code=llm.code,
                )
            )
        provider, api_key = provider_data
        if not provider.is_active:
            raise ValueError(
                render_prompt(
                    await tr("llm_api.errors.provider_inactive"),
                    provider_name=provider.name,
                )
            )
        requester_user_id = await enforce_subscription_access(
            provider,
            task_id=task_id,
            conversation_round_id=conversation_round_id,
            process_run_id=process_run_id,
        )
        connection = provider_connection(provider, api_key)
        transport = responses_transport_for(connection)
        _remove_galaris_fields(forwarded)
        forwarded = adapt_request_parameters(
            forwarded, request_parameter_policy_for(connection, llm.llm_name),
            "compact" if operation == "compact" else "responses",
        )
        stream = operation == "create" and bool(forwarded.get("stream", False))

        if purpose is None:
            if managed_runtime_request:
                from .purposes import LLMCallPurpose

                purpose = LLMCallPurpose.AGENT_EXEC
            elif process_run_id is not None:
                from .purposes import LLMCallPurpose

                purpose = LLMCallPurpose.PROCESS_EXEC

        call = await llm_call_service.create_running_call(
            purpose=purpose,
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            process_run_id=process_run_id,
            requester_user_id=requester_user_id,
            agent_id=agent_id,
            llm_id=llm.id,
            provider_name=provider.name,
            provider_code=provider.catalog_code or (
                provider.provider_type
                if provider.provider_type != "openai_compatible"
                else None
            ),
            requested_model=requested_model,
            effective_model=llm.llm_name,
            reasoning_effort=applied_reasoning,
            stream=stream,
            request_body=trace_body,
            is_subscription=bool(getattr(llm, "is_subscription", False)),
        )

    forwarded["model"] = llm.llm_name
    _remove_galaris_fields(forwarded)
    canonical_forwarded = dict(forwarded)
    client = httpx.AsyncClient(
        timeout=PROXY_TIMEOUT if request_timeout is None else httpx.Timeout(**request_timeout),
    )
    try:
        if transport is not None:
            prepared = await transport.prepare_responses_request(
                provider.id,
                connection,
                canonical_forwarded,
                operation=operation,
            )
            endpoint = prepared.endpoint
            headers = prepared.headers
            forwarded = prepared.body
        else:
            suffix = "/responses/compact" if operation == "compact" else "/responses"
            endpoint = f"{openai_protocol_base_url(connection)}{suffix}"
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        upstream_stream = operation == "create" and bool(forwarded.get("stream", False))
        upstream = await _send_best_effort(client, endpoint, headers, forwarded, stream=upstream_stream)
        if transport is not None and upstream.status_code == 401:
            await upstream.aclose()
            async with get_db_session():
                prepared = await transport.prepare_responses_request(
                    provider.id,
                    connection,
                    canonical_forwarded,
                    operation=operation,
                    force_refresh=True,
                )
            upstream_stream = operation == "create" and bool(prepared.body.get("stream", False))
            upstream = await _send_best_effort(
                client, prepared.endpoint, prepared.headers, prepared.body, stream=upstream_stream,
            )
    except asyncio.CancelledError:
        await _finish_cancelled_request(client, call.id, llm)
        raise
    except ProviderAuthenticationError as exc:
        await client.aclose()
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            status="error",
            error=str(exc),
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        raise
    except Exception as exc:
        await client.aclose()
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            status="error",
            error=str(exc),
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        if sdk_request and isinstance(exc, httpx.TransportError):
            raise
        raise RuntimeError(
            render_prompt(await tr("llm_api.errors.provider_connection_error"), error=exc)
        ) from exc

    if not stream and not upstream_stream:
        try:
            raw = await upstream.aread()
            raw_response = raw.decode("utf-8", errors="replace")
            try:
                decoded = json.loads(raw)
                payload = as_dict(decoded) if isinstance(decoded, dict) else {"data": decoded}
            except json.JSONDecodeError:
                payload = {"error": {"message": raw.decode(errors="replace")}}
            provider_success = _upstream_response_succeeded(upstream.is_success, payload)
            response_status = str(payload.get("status") or "").lower()
            provider_success = provider_success and response_status != "failed"
            trace = responses_response_trace(payload) if provider_success else {}
            error_detail = payload.get("error") or payload
            await llm_call_service.finalize_call(
                call.id,
                trace=trace,
                raw_response=raw_response,
                status="completed" if provider_success else "error",
                error=None if provider_success else str(error_detail),
                input_rate=llm.cost_per_input_token,
                cached_input_rate=llm.cost_per_cached_input_token,
                output_rate=llm.cost_per_output_token,
            )
            return JSONResponse(
                content=payload,
                status_code=(
                    upstream.status_code
                    if provider_success or not upstream.is_success
                    else 502
                ),
                headers=_response_headers(upstream, call.id),
            )
        finally:
            await upstream.aclose()
            await client.aclose()

    if not upstream.is_success:
        raw = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        message = raw.decode(errors="replace")
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            raw_response=message,
            status="error",
            error=message,
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        try:
            decoded = json.loads(raw)
            payload = as_dict(decoded) if isinstance(decoded, dict) else {"data": decoded}
        except json.JSONDecodeError:
            payload = {"error": {"message": message}}
        return JSONResponse(content=payload, status_code=upstream.status_code, headers=_response_headers(upstream, call.id))

    stream_trace = ResponsesStreamTrace()
    async def relay_responses() -> AsyncIterator[bytes]:
        first_token_at: datetime | None = None
        status = "completed"
        error: str | None = None
        stream_completed = False
        last_partial_update = 0.0
        try:
            async for line in upstream.aiter_lines():
                decoded_event: dict[str, Any] | None = None
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data and data != "[DONE]":
                        try:
                            decoded = json.loads(data)
                        except json.JSONDecodeError:
                            decoded = None
                        if isinstance(decoded, dict):
                            decoded_event = as_dict(decoded)
                            changed = stream_trace.add_event(decoded_event)
                            if changed and first_token_at is None:
                                first_token_at = datetime.now(timezone.utc)
                            now = time.monotonic()
                            if changed and now - last_partial_update >= _PARTIAL_UPDATE_INTERVAL:
                                last_partial_update = now
                                try:
                                    await llm_call_service.update_running_call(
                                        call.id,
                                        trace=stream_trace.result(),
                                        first_token_at=first_token_at,
                                        input_rate=llm.cost_per_input_token,
                                        cached_input_rate=llm.cost_per_cached_input_token,
                                        output_rate=llm.cost_per_output_token,
                                    )
                                except Exception:
                                    logger.exception(
                                        "Responses trace partial update failed for call {}",
                                        call.id,
                                    )
                yield (line + "\n").encode("utf-8")
            if not stream_trace.terminal:
                raise RuntimeError("the Responses stream ended before its terminal event")
            stream_completed = True
            if stream_trace.error is not None:
                status = "error"
                error = stream_trace.error
        except asyncio.CancelledError:
            if stream_trace.terminal:
                status = "error" if stream_trace.error else "completed"
                error = stream_trace.error
            else:
                status = "cancelled"
                error = cancelled_message
            raise
        except Exception as exc:
            status = "error"
            error = str(exc)
            raise
        finally:
            if status == "completed" and not stream_completed and not stream_trace.terminal:
                status = "cancelled"
                error = "Responses stream closed before a terminal provider response."

            async def finalize_trace() -> None:
                await llm_call_service.finalize_call(
                    call.id,
                    trace=stream_trace.result(),
                    raw_response=_serialized_final_responses_result(stream_trace),
                    status=status,
                    error=error,
                    input_rate=llm.cost_per_input_token,
                    cached_input_rate=llm.cost_per_cached_input_token,
                    output_rate=llm.cost_per_output_token,
                    first_token_at=first_token_at,
                )

            await _run_stream_cleanup(
                finalize_trace,
                call_id=call.id,
                operation_name="Responses trace finalization",
            )

            async def close_transport() -> None:
                await upstream.aclose()
                await client.aclose()

            await _run_stream_cleanup(
                close_transport,
                call_id=call.id,
                operation_name="Responses upstream cleanup",
            )

    if not stream:
        # Preserve the caller's JSON contract, including structured tool output.
        # Reuse the streaming trace and cleanup path; never return partial output.
        try:
            async for _chunk in relay_responses():
                pass
        except Exception:
            return JSONResponse(
                content={"error": {"message": "Responses stream interrupted before a complete result."}},
                status_code=502,
                headers=_response_headers(upstream, call.id),
            )
        return JSONResponse(
            content=stream_trace.terminal_response or {"error": {"message": stream_trace.error}},
            status_code=502 if stream_trace.error else 200,
            headers=_response_headers(upstream, call.id),
        )

    return StreamingResponse(
        relay_responses(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Galaris-LLM-Call-Id": str(call.id),
        },
    )
