"""Common OpenAI Chat Completions client for network Harnesses."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from loguru import logger

from app.agent import (
    AIMessage,
    AgentEvent,
    AgentRunEnvelopeV1,
    AgentUsage,
    ExecutionResult,
    UsageQuality,
)


_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
_GALARIS_MODEL_HARNESS_PROVIDERS = frozenset(
    {"claude_agent", "codex", "deepseek_harness"}
)


def _mapping(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    raw = cast(Mapping[object, object], payload)
    return {key: value for key, value in raw.items() if isinstance(key, str)}


def _float(payload: object, default: float = 0.0) -> float:
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return float(payload)
    return default


def normalize_base_url(value: str) -> str:
    """Normalize one explicit HTTP(S) target without inventing a deployment mode."""

    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Harness base_url must be an absolute http:// or https:// URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Harness base_url cannot contain credentials, a query, or a fragment.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _usage(payload: object) -> AgentUsage:
    raw = _mapping(payload)
    if not raw:
        return AgentUsage(token_quality="unknown")

    def counter(*keys: str) -> int:
        value = next((raw.get(key) for key in keys if raw.get(key) is not None), 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    def quality(key: str, fallback: UsageQuality) -> UsageQuality:
        value = raw.get(key)
        if isinstance(value, str) and value in {
            "exact",
            "estimated",
            "partial",
            "unknown",
        }:
            return cast(UsageQuality, value)
        return fallback

    prompt = next(
        (raw.get(key) for key in ("prompt_tokens", "input_tokens", "inputTokens") if raw.get(key) is not None),
        None,
    )
    completion = next(
        (
            raw.get(key)
            for key in ("completion_tokens", "output_tokens", "outputTokens")
            if raw.get(key) is not None
        ),
        None,
    )
    cost = _float(raw.get("cost"))
    inferred_token_quality: UsageQuality = (
        "exact"
        if all(isinstance(item, int) and not isinstance(item, bool) for item in (prompt, completion))
        else "partial"
    )
    return AgentUsage(
        input_tokens=counter("prompt_tokens", "input_tokens", "inputTokens"),
        output_tokens=counter("completion_tokens", "output_tokens", "outputTokens"),
        cache_read_tokens=counter(
            "cache_read_tokens", "cache_read_input_tokens", "cacheReadInputTokens"
        ),
        cache_write_tokens=counter(
            "cache_write_tokens",
            "cache_creation_input_tokens",
            "cacheCreationInputTokens",
        ),
        reasoning_tokens=counter("reasoning_tokens", "thinking_tokens"),
        requests=counter("requests") or 1,
        tool_calls=counter("tool_calls"),
        cost=max(0.0, cost),
        token_quality=quality("token_quality", inferred_token_quality),
        cost_quality=quality(
            "cost_quality", "estimated" if cost > 0 else "unknown"
        ),
    )


def _model(envelope: AgentRunEnvelopeV1) -> str:
    """Select a runtime model unless the provider delegates selection to Galaris."""

    if envelope.target.metadata.get("model_passthrough") is True:
        return envelope.model_code
    return str(envelope.target.metadata.get("model") or envelope.model_name)


async def _authoritative_gateway_usage(
    envelope: AgentRunEnvelopeV1,
    fallback: AgentUsage,
) -> tuple[AgentUsage, dict[str, object]]:
    """Prefer persisted Galaris accounting over runtime-reported telemetry."""

    gateway = str(envelope.target.metadata.get("model_gateway") or "")
    if (
        envelope.target.provider_code not in _GALARIS_MODEL_HARNESS_PROVIDERS
        and not gateway.startswith("galaris")
    ):
        return fallback, {}
    try:
        from app.agent import aggregate_llm_run_usage

        accounting = await aggregate_llm_run_usage(
            envelope.identity.run_id,
            agent_id=envelope.agent_id,
        )
    except Exception:
        logger.exception(
            "Harness gateway accounting failed: agent={} run={}",
            envelope.agent_id,
            envelope.identity.run_id,
        )
        return fallback, {}
    if accounting is None:
        return fallback, {}
    usage, inference_cost = accounting
    return usage, {
        "usage_source": "galaris_llm_calls",
        "inference_cost": inference_cost,
    }


def _trace_messages(payload: object) -> list[AIMessage]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return []
    messages: list[AIMessage] = []
    for item in cast(Sequence[object], payload):
        try:
            messages.append(AIMessage.model_validate(item))
        except ValueError:
            continue
    return messages


def _append_trace_message(messages: list[AIMessage], message: AIMessage) -> None:
    """Coalesce live fragments without persisting one trace row per token."""

    previous = messages[-1] if messages else None
    if (
        previous is not None
        and message.stream_id is not None
        and previous.stream_id == message.stream_id
        and previous.type == message.type
        and previous.tool_name == message.tool_name
    ):
        messages[-1] = previous.model_copy(
            update={
                "content": previous.content + message.content,
                "execution_time": previous.execution_time + message.execution_time,
                "cost": previous.cost + message.cost,
                "success": previous.success and message.success,
            }
        )
        return
    messages.append(message)


async def _sse_records(response: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    """Decode standard SSE records while retaining optional named events."""

    event_name = "message"
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        yield event_name, "\n".join(data_lines)


def _messages(envelope: AgentRunEnvelopeV1) -> list[dict[str, str]]:
    system_parts = [envelope.system_instructions.strip(), envelope.shared_context.strip()]
    if envelope.resource_uris:
        system_parts.append(
            "Canonical resources:\n" + "\n".join(f"- {uri}" for uri in envelope.resource_uris)
        )
    messages: list[dict[str, str]] = []
    system = "\n\n".join(part for part in system_parts if part)
    if system:
        messages.append({"role": "system", "content": system})
    for raw in envelope.conversation_history:
        role = str(raw.get("role") or "").strip().lower()
        content = raw.get("content")
        if role in {"system", "user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    objective = envelope.objective
    if envelope.messaging_context:
        context = json.dumps(
            envelope.messaging_context,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        objective = (
            f"<galaris_message_context>\n{context}\n"
            f"</galaris_message_context>\n{objective}"
        )
    messages.append({"role": "user", "content": objective})
    return messages


class OpenAIHarnessClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.token = token
        self.transport = transport

    def _headers(self, envelope: AgentRunEnvelopeV1 | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if (
            envelope is not None
            and envelope.target.metadata.get("galaris_extensions") is True
        ):
            headers.update(
                {
                    "X-Galaris-Agent-Run-Id": str(envelope.identity.run_id),
                    "X-Galaris-Agent-Id": str(envelope.agent_id),
                    "X-Galaris-Model-Code": envelope.model_code,
                    "X-Galaris-Model-Name": envelope.model_name,
                    "X-Galaris-Effort": envelope.effort,
                    "X-Galaris-Approval-Action": envelope.approval_action,
                }
            )
            if envelope.identity.task_id is not None:
                headers["X-Galaris-Task-Id"] = str(envelope.identity.task_id)
            if envelope.reasoning_effort is not None:
                headers["X-Galaris-Reasoning-Effort"] = envelope.reasoning_effort
            if envelope.limits.request_limit is not None:
                headers["X-Galaris-Request-Limit"] = str(envelope.limits.request_limit)
            if envelope.limits.tool_call_limit is not None:
                headers["X-Galaris-Tool-Call-Limit"] = str(
                    envelope.limits.tool_call_limit
                )
        return headers

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
            response.raise_for_status()
        payload_object = cast(object, response.json())
        payload = (
            cast(Mapping[str, object], payload_object)
            if isinstance(payload_object, Mapping)
            else None
        )
        data = payload.get("data") if payload is not None else None
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise RuntimeError("Harness /models returned an invalid response.")
        models: list[str] = []
        for item in cast(Sequence[object], data):
            if isinstance(item, Mapping):
                item_mapping = cast(Mapping[str, object], item)
                model_id = item_mapping.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    models.append(model_id.strip())
        return list(dict.fromkeys(models))

    async def run(self, envelope: AgentRunEnvelopeV1) -> ExecutionResult:
        payload = {
            "model": _model(envelope),
            "messages": _messages(envelope),
            "stream": False,
        }
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(envelope),
                json=payload,
            )
            response.raise_for_status()
        body_object = cast(object, response.json())
        if not isinstance(body_object, Mapping):
            raise RuntimeError("Harness Chat Completions response is invalid.")
        body = cast(Mapping[str, object], body_object)
        choices = body.get("choices")
        if not isinstance(choices, Sequence) or not choices:
            raise RuntimeError("Harness Chat Completions response has no choice.")
        first_object = cast(Sequence[object], choices)[0]
        if not isinstance(first_object, Mapping):
            raise RuntimeError("Harness Chat Completions choice is invalid.")
        first = cast(Mapping[str, object], first_object)
        message = first.get("message")
        if not isinstance(message, Mapping):
            raise RuntimeError("Harness Chat Completions choice has no assistant message.")
        message_mapping = cast(Mapping[str, object], message)
        if message_mapping.get("tool_calls"):
            raise RuntimeError("Harness returned unresolved tool_calls; V1 requires a final answer.")
        content = message_mapping.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Harness assistant message has no text content.")
        extension = _mapping(body.get("galaris"))
        usage = _usage(extension.get("usage") or body.get("usage"))
        usage, accounting_metadata = await _authoritative_gateway_usage(
            envelope,
            usage,
        )
        trace = _trace_messages(extension.get("messages"))
        text_message = AIMessage(type="text", content=content)
        if content:
            trace.append(text_message)
        return ExecutionResult(
            prompt=envelope.objective,
            system_prompt=envelope.system_instructions,
            result=content,
            messages=trace,
            execution_time=_float(extension.get("execution_time")),
            cost=usage.cost,
            usage=usage,
            success=extension.get("success") is not False,
            metadata={
                "completion_id": str(body.get("id") or "")[:300],
                **dict(_mapping(extension.get("metadata"))),
                **accounting_metadata,
            },
        )

    async def stream(self, envelope: AgentRunEnvelopeV1) -> AsyncIterator[AgentEvent]:
        payload = {
            "model": _model(envelope),
            "messages": _messages(envelope),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        chunks: list[str] = []
        trace_messages: list[AIMessage] = []
        usage = AgentUsage(token_quality="unknown", cost_quality="unknown")
        runtime_result: Mapping[str, object] = {}
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(envelope),
                json=payload,
            ) as response:
                response.raise_for_status()
                async for event_name, raw in _sse_records(response):
                    if not raw or raw == "[DONE]":
                        continue
                    body_object = cast(object, json.loads(raw))
                    if event_name == "galaris.agent-message/v1":
                        message = AIMessage.model_validate(body_object)
                        _append_trace_message(trace_messages, message)
                        yield AgentEvent.from_message(message)
                        continue
                    if event_name == "galaris.agent-result/v1":
                        runtime_result = _mapping(body_object)
                        if runtime_result.get("usage") is not None:
                            usage = _usage(runtime_result.get("usage"))
                        continue
                    body = _mapping(body_object)
                    if not body:
                        continue
                    if body.get("error") is not None:
                        error = body.get("error")
                        error_mapping = _mapping(error)
                        detail = (
                            str(body.get("detail") or error)
                            if not error_mapping
                            else str(error_mapping.get("message") or error_mapping)
                        )
                        raise RuntimeError(f"Harness streaming error: {detail[:1_000]}")
                    if body.get("usage") is not None:
                        usage = _usage(body.get("usage"))
                    choices = body.get("choices")
                    if not isinstance(choices, Sequence) or not choices:
                        continue
                    first_object = cast(Sequence[object], choices)[0]
                    if not isinstance(first_object, Mapping):
                        continue
                    first = cast(Mapping[str, object], first_object)
                    delta = first.get("delta")
                    if not isinstance(delta, Mapping):
                        continue
                    delta_mapping = cast(Mapping[str, object], delta)
                    if delta_mapping.get("tool_calls"):
                        raise RuntimeError(
                            "Harness returned unresolved tool_calls; V1 requires a final answer."
                        )
                    content = delta_mapping.get("content")
                    if isinstance(content, str) and content:
                        chunks.append(content)
                        yield AgentEvent.from_message(AIMessage(type="text", content=content))
        streamed_text = "".join(chunks)
        authoritative_result = runtime_result.get("result")
        result_text = (
            authoritative_result
            if isinstance(authoritative_result, str)
            else streamed_text
        )
        if result_text:
            trace_messages.append(AIMessage(type="text", content=result_text))
        runtime_metadata = runtime_result.get("metadata")
        usage, accounting_metadata = await _authoritative_gateway_usage(
            envelope,
            usage,
        )
        yield AgentEvent.from_result(
            ExecutionResult(
                prompt=envelope.objective,
                system_prompt=envelope.system_instructions,
                result=result_text,
                messages=trace_messages,
                execution_time=_float(runtime_result.get("execution_time")),
                cost=usage.cost,
                usage=usage,
                success=runtime_result.get("success") is not False,
                metadata=(
                    {
                        **dict(_mapping(runtime_metadata)),
                        **accounting_metadata,
                    }
                ),
            )
        )


__all__ = ["OpenAIHarnessClient", "normalize_base_url"]
