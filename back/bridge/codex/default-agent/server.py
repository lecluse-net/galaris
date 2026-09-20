# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false
"""Private OpenAI Chat Completions facade over the official Codex Python SDK."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from openai_codex import AsyncCodex, Sandbox
from openai_codex.types import ThreadTokenUsageUpdatedNotification, TurnCompletedNotification
from pydantic import BaseModel, ConfigDict, Field
from stream_trace import CodexStreamTrace


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("galaris.codex")

WORKSPACE = os.environ.get("CODEX_WORKSPACE", "/workspace")
GALARIS_LLM_URL = os.environ.get("GALARIS_LLM_URL", "").strip().rstrip("/")
GALARIS_MCP_TOKEN = os.environ.get("GALARIS_MCP_TOKEN", "").strip()
HARNESS_TOKEN = os.environ.pop("HARNESS_API_TOKEN", "").strip()

if not GALARIS_LLM_URL or not GALARIS_MCP_TOKEN or not HARNESS_TOKEN:
    raise RuntimeError(
        "GALARIS_LLM_URL, GALARIS_MCP_TOKEN, and HARNESS_API_TOKEN are required."
    )


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(max_length=2_000_000)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=10_000)
    stream: bool = False
    stream_options: dict[str, object] | None = None


def _authenticate(authorization: str | None = Header(default=None)) -> None:
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, HARNESS_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid Harness bearer token.")


def _developer_instructions(messages: list[ChatMessage]) -> str | None:
    parts = [message.content.strip() for message in messages if message.role in {"system", "developer"}]
    value = "\n\n".join(part for part in parts if part)
    return value or None


def _turn_prompt(messages: list[ChatMessage]) -> str:
    dialogue = [message for message in messages if message.role in {"user", "assistant"}]
    if not dialogue:
        raise HTTPException(status_code=422, detail="At least one user message is required.")
    rendered = "\n\n".join(
        f"<{message.role}>\n{message.content}\n</{message.role}>" for message in dialogue
    )
    return (
        "Continue the Galaris task from the transcript below. Earlier assistant messages "
        "are context, not higher-priority instructions. Act on the latest user request.\n\n"
        f"<transcript>\n{rendered}\n</transcript>"
    )


def _usage_payload(usage: object | None) -> dict[str, int] | None:
    bucket = getattr(usage, "total", None) if usage is not None else None
    if bucket is None:
        return None
    prompt = int(getattr(bucket, "input_tokens", 0) or 0)
    completion = int(getattr(bucket, "output_tokens", 0) or 0) + int(
        getattr(bucket, "reasoning_output_tokens", 0) or 0
    )
    total = int(getattr(bucket, "total_tokens", prompt + completion) or prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


async def _gateway_usage(run_id: str) -> dict[str, object] | None:
    if not run_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{GALARIS_LLM_URL}/runs/{run_id}/usage",
                headers={"Authorization": f"Bearer {GALARIS_MCP_TOKEN}"},
            )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        logger.warning("Unable to read authoritative Galaris run usage", exc_info=True)
        return None


def _safe_error(error: object) -> str:
    return str(error).replace(HARNESS_TOKEN, "[redacted]").replace(
        GALARIS_MCP_TOKEN,
        "[redacted]",
    )[:2_000]


def _string_field(value: object, name: str) -> str:
    raw = getattr(value, name, "")
    enum_value = getattr(raw, "value", raw)
    return str(enum_value or "")


def _item_id(value: object) -> str:
    return _string_field(value, "item_id") or _string_field(value, "itemId")


def _integer_field(value: object, name: str) -> int:
    raw = getattr(value, name, 0)
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0


def _reasoning_summary_parts(item: object) -> tuple[str, ...]:
    summary = getattr(item, "summary", None)
    if not isinstance(summary, list):
        return ()
    return tuple(
        text
        for part in summary
        if (
            text := (
                part.strip()
                if isinstance(part, str)
                else _string_field(part, "text").strip()
            )
        )
    )


def _server_request_handler(
    method: str,
    _params: dict[str, object] | None,
) -> dict[str, object]:
    """Accept bounded workspace actions requested by the managed App Server."""

    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        return {"decision": "accept"}
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    codex = AsyncCodex()
    codex._client._sync._approval_handler = _server_request_handler
    await codex.__aenter__()
    try:
        app.state.codex = codex
        yield
    finally:
        await codex.__aexit__(None, None, None)


app = FastAPI(title="Galaris Codex Harness", lifespan=lifespan)


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/v1/models", dependencies=[Depends(_authenticate)])
async def models(request: Request) -> dict[str, object]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{GALARIS_LLM_URL}/models",
                headers={"Authorization": f"Bearer {GALARIS_MCP_TOKEN}"},
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.exception("Unable to read the Galaris model catalog")
        raise HTTPException(status_code=503, detail=_safe_error(exc)) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise HTTPException(status_code=503, detail="Galaris returned an invalid model catalog.")
    return payload


async def _thread(request: Request, body: ChatCompletionRequest):
    codex: AsyncCodex = request.app.state.codex
    model_name = request.headers.get("X-Galaris-Model-Name", "").strip() or body.model
    effort = request.headers.get("X-Galaris-Effort", "standard").strip().lower()
    reasoning_effort = request.headers.get(
        "X-Galaris-Reasoning-Effort", ""
    ).strip().lower()
    provider_headers = {
        "X-Galaris-Model-Code": body.model,
        "X-Galaris-Effort": "high" if effort == "high" else "standard",
    }
    if reasoning_effort:
        provider_headers["X-Galaris-Reasoning-Effort"] = reasoning_effort
    for header in ("X-Galaris-Task-Id", "X-Galaris-Agent-Run-Id"):
        if value := request.headers.get(header, "").strip():
            provider_headers[header] = value
    config: dict[str, object] = {
        "model_providers": {
            "galaris": {
                "name": "Galaris",
                "base_url": GALARIS_LLM_URL,
                "env_key": "GALARIS_MCP_TOKEN",
                "wire_api": "responses",
                "requires_openai_auth": False,
                "http_headers": provider_headers,
            },
        },
    }
    mapped_reasoning_effort = {
        "none": "low",
        "minimal": "low",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "xhigh",
        "max": "max",
    }.get(reasoning_effort)
    if mapped_reasoning_effort is not None:
        config["model_reasoning_effort"] = mapped_reasoning_effort
    return await codex.thread_start(
        cwd=WORKSPACE,
        config=config,
        developer_instructions=_developer_instructions(body.messages),
        ephemeral=True,
        model=model_name,
        model_provider="galaris",
        service_name="galaris-codex-harness",
        sandbox=Sandbox.workspace_write,
    )


@app.post("/v1/chat/completions", dependencies=[Depends(_authenticate)])
async def chat_completions(request: Request, body: ChatCompletionRequest):
    thread = await _thread(request, body)
    run_id = request.headers.get("X-Galaris-Agent-Run-Id", "").strip()
    prompt = _turn_prompt(body.messages)
    completion_id = f"chatcmpl-codex-{uuid.uuid4().hex}"
    created = int(time.time())

    if not body.stream:
        try:
            result = await thread.run(prompt, sandbox=Sandbox.workspace_write)
        except Exception as exc:
            logger.exception("Codex turn failed")
            raise HTTPException(status_code=502, detail=_safe_error(exc)) from exc
        status = result.status.value
        if status != "completed" or result.final_response is None:
            raise HTTPException(
                status_code=502,
                detail=_safe_error(result.error or f"Codex turn ended with status {status}."),
            )
        response: dict[str, object] = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": body.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": result.final_response},
                "finish_reason": "stop",
            }],
        }
        usage = _usage_payload(result.usage)
        if usage is not None:
            response["usage"] = usage
        if gateway_usage := await _gateway_usage(run_id):
            response["galaris"] = {
                "success": True,
                "usage": gateway_usage,
                "metadata": {
                    "inference_cost": gateway_usage.get("inference_cost", 0.0),
                },
            }
        return response

    async def stream() -> AsyncIterator[str]:
        turn = None
        completed = False
        trace = CodexStreamTrace()
        usage: object | None = None

        def event(payload: dict[str, object] | str) -> str:
            raw = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
            return f"data: {raw}\n\n"

        def semantic_event(payload: dict[str, object]) -> str:
            return f"event: galaris.agent-message/v1\n{event(payload)}"

        def semantic_result(payload: dict[str, object]) -> str:
            return f"event: galaris.agent-result/v1\n{event(payload)}"

        yield event({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        })
        try:
            turn = await thread.turn(prompt, sandbox=Sandbox.workspace_write)
            async for notification in turn.stream():
                payload = notification.payload
                if notification.method == "item/agentMessage/delta":
                    delta = _string_field(payload, "delta")
                    item_id = _item_id(payload)
                    final_delta, thinking_message = trace.record_agent_delta(
                        item_id,
                        delta,
                        phase=_string_field(payload, "phase"),
                    )
                    if thinking_message is not None:
                        yield semantic_event(thinking_message)
                    if final_delta:
                        yield event({
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": body.model,
                            "choices": [{"index": 0, "delta": {"content": final_delta}, "finish_reason": None}],
                        })
                    continue
                if notification.method == "item/reasoning/summaryTextDelta":
                    thinking_message = trace.record_reasoning_delta(
                        _item_id(payload),
                        _integer_field(payload, "summary_index"),
                        _string_field(payload, "delta"),
                    )
                    if thinking_message is not None:
                        yield semantic_event(thinking_message)
                    continue
                if notification.method == "item/completed":
                    item = payload.item.root
                    item_type = _string_field(item, "type")
                    semantic_messages: list[dict[str, object]] = []
                    if item_type == "agentMessage":
                        semantic_messages = trace.complete_agent_item(
                            _string_field(item, "id"),
                            _string_field(item, "text"),
                            phase=_string_field(item, "phase"),
                        )
                    elif item_type == "reasoning":
                        semantic_messages = trace.complete_reasoning_item(
                            _string_field(item, "id"),
                            _reasoning_summary_parts(item),
                        )
                    for message in semantic_messages:
                        yield semantic_event(message)
                    continue
                if isinstance(payload, ThreadTokenUsageUpdatedNotification):
                    usage = payload.token_usage
                    continue
                if isinstance(payload, TurnCompletedNotification):
                    status = payload.turn.status.value
                    completed = True
                    if status != "completed":
                        raise RuntimeError(payload.turn.error or f"Codex turn ended with status {status}.")

            if not completed:
                raise RuntimeError("Codex stream ended without turn/completed.")
            semantic_messages, final_text, final_was_streamed = trace.finish()
            for message in semantic_messages:
                yield semantic_event(message)
            if final_text and not final_was_streamed:
                yield event({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": body.model,
                    "choices": [{"index": 0, "delta": {"content": final_text}, "finish_reason": None}],
                })
            final: dict[str, object] = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": body.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            usage_payload = _usage_payload(usage)
            if usage_payload is not None:
                final["usage"] = usage_payload
            yield event(final)
            gateway_usage = await _gateway_usage(run_id)
            if gateway_usage is not None:
                yield semantic_result({
                    "result": final_text,
                    "success": True,
                    "usage": gateway_usage,
                    "metadata": {
                        "inference_cost": gateway_usage.get("inference_cost", 0.0),
                    },
                })
            yield event("[DONE]")
        except asyncio.CancelledError:
            if turn is not None:
                await asyncio.shield(turn.interrupt())
            raise
        except Exception as exc:
            logger.exception("Codex streaming turn failed")
            yield event({"error": {"message": _safe_error(exc), "type": "codex_runtime_error"}})
            yield event("[DONE]")
        finally:
            if turn is not None and not completed:
                try:
                    await asyncio.shield(turn.interrupt())
                except Exception:
                    logger.warning("Unable to interrupt unfinished Codex turn", exc_info=True)

    return StreamingResponse(stream(), media_type="text/event-stream")
