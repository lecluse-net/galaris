"""Anthropic-compatible routes for Claude Code and other Anthropic clients.

Mounted as `/api/llm/anthropic`, so pointing `ANTHROPIC_BASE_URL` at
`https://<galaris>/api/llm/anthropic` gives Claude Code a working
`/v1/messages`, `/v1/messages/count_tokens` and `/v1/models`. Authentication
mirrors the OpenAI surface: `x-api-key` or `Authorization: Bearer` carry a
managed-runtime system token (`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY`),
and logged-in users with `LLM_API_ACCESS` are accepted too.

Error bodies use the Anthropic envelope (`{"type": "error", "error": ...}`)
because Anthropic SDKs refuse to parse `{"detail": ...}`. This FastAPI version
does not support router-level exception handlers, so every endpoint catches
its `HTTPException` raise sites and returns the envelope explicitly.
"""

from __future__ import annotations

import json
from typing import Any, Optional, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from core.authorize import Privileges, independent_auth
from core.authorize.logic import check_privilege
from core.database import get_db
from core.i18n import render_prompt, tr
from core.user import user_service
from app.agent import current_management_scope

from . import llm_service
from .anthropic_schemas import (
    MessageRequest,
    error_envelope,
    json_dumps,
)
from .anthropic_service import (
    AnthropicStreamTranslator,
    anthropic_input_tokens,
    call_proxy,
    error_status_type,
    estimate_openai_body_tokens,
    translate_completion,
    translate_proxy_stream,
    translate_to_openai,
)
from .provider_facade import ProviderAuthenticationError
from .profile_gateway import (
    is_profile_api, mark_profile_api, profile_models, resolve_profile_model,
)
from .reasoning import normalize_reasoning_effort, parse_force_reasoning_effort
from .runtime_correlation import (
    resolve_runtime_process_run_id,
    resolve_runtime_task_id,
)
from .trace import (
    agent_run_id_from_messages,
    extract_process_context,
    llm_id_from_messages,
)


router = APIRouter()


def _error_envelope(status_code: int, detail: Any) -> dict[str, Any]:
    return error_envelope(str(detail) or "request failed", error_status_type(status_code))


def _http_exception_response(exc: HTTPException) -> JSONResponse:
    """Render a raised HTTPException as an Anthropic error envelope.

    Every endpoint catches its raise sites and returns this response directly;
    the standard FastAPI handler would serialize `{"detail": ...}`, which
    Anthropic SDKs refuse to parse.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        # Already an envelope (e.g. raised by the auth helper).
        content = detail
    else:
        content = _error_envelope(exc.status_code, detail)
    return JSONResponse(
        content=content,
        status_code=exc.status_code,
        headers=dict(exc.headers or {}),
    )


anthropic_router = APIRouter(
    prefix="/llm/anthropic",
    tags=["Anthropic-like LLM"],
)
profile_api_router = APIRouter(
    prefix="/profile/anthropic", tags=["Anthropic-like profiles"],
    dependencies=[Depends(mark_profile_api)],
)


async def _anthropic_api_auth(request: Request) -> int | None:
    """Authenticate `/api/llm/anthropic` requests.

    `ANTHROPIC_AUTH_TOKEN` lands in `Authorization: Bearer`, `ANTHROPIC_API_KEY`
    in `x-api-key`; both resolve through the system-token store. Returns the
    agent ID only for managed-runtime authentication.
    """
    token = request.headers.get("x-api-key", "").strip()
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if token:
        from app.mcp import mcp_token_service

        record = await mcp_token_service.get_enabled_system_token_by_value(token)
        if record is not None:
            return record.agent_id

    current_user = await user_service.get_current_user()
    if current_user is not None and current_user.is_active:
        if not await check_privilege(
            current_user,
            Privileges.LLM_API_ACCESS,
            get_db(),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_envelope(
                    render_prompt(
                        await tr("authorize_api.errors.missing_privilege"),
                        privileges=[Privileges.LLM_API_ACCESS],
                    ),
                    "permission_error",
                ),
            )
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_envelope(
            await tr("llm_api.errors.invalid_llm_token"),
            "authentication_error",
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _anthropic_api_agent_ids(
    agent_id: int | None,
) -> frozenset[int] | None:
    """Pin runtime tokens to their Agent and human tokens to management scope."""

    if agent_id is not None:
        return frozenset((agent_id,))
    return (await current_management_scope()).agent_ids


def _provider_error_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)
    payload_dict = cast(dict[str, Any], payload)
    error = payload_dict.get("error")
    if isinstance(error, dict):
        error_dict = cast(dict[str, Any], error)
        message = error_dict.get("message")
        return str(message or error_dict)
    if error:
        return str(error)
    serialized = json_dumps(payload_dict)
    return serialized if len(serialized) <= 500 else serialized[:497] + "..."


def _call_id_headers(response: JSONResponse | StreamingResponse) -> dict[str, str]:
    return {name: value for name in ("X-Galaris-LLM-Call-Id", "X-Galaris-Inference-Id")
            if (value := response.headers.get(name))}


@anthropic_router.get("/v1/models")
@profile_api_router.get("/v1/models")
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def anthropic_models(request: Request):
    try:
        await _anthropic_api_auth(request)
        if is_profile_api(request):
            models = await profile_models(("chat",))
            data = [{"type": "model", "id": item.id, "display_name": item.id,
                     "created_at": "1970-01-01T00:00:00Z"} for item in models]
            return {"data": data, "has_more": False,
                    "first_id": models[0].id if models else None,
                    "last_id": models[-1].id if models else None}
        llms = await llm_service.list_llms(capability="chat")
        data = [{
            "type": "model",
            "id": llm.code,
            "display_name": llm.label or llm.code,
            "object": "model",
            "created": 0,
            "owned_by": llm.provider.name if llm.provider else "galaris",
            "context_length": llm.context_length,
        } for llm in llms]
        return {
            "data": data,
            "has_more": False,
            "first_id": data[0]["id"] if data else None,
        }
    except HTTPException as exc:
        return _http_exception_response(exc)


@anthropic_router.post("/v1/messages/count_tokens")
@profile_api_router.post("/v1/messages/count_tokens")
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def anthropic_count_tokens(request: Request):
    try:
        await _anthropic_api_auth(request)
        body: Any = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=await tr("anthropic_api.errors.invalid_request"),
            )
        parsed = MessageRequest.model_validate(body)
        if is_profile_api(request):
            await resolve_profile_model(parsed.model, "chat")
        return {"input_tokens": anthropic_input_tokens(parsed)}
    except ValidationError as exc:
        return _http_exception_response(
            HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        )
    except HTTPException as exc:
        return _http_exception_response(exc)

    except (ValueError, LookupError) as exc:
        return _http_exception_response(HTTPException(
            status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc),
        ))


@anthropic_router.post("/v1/messages")
@profile_api_router.post("/v1/messages")
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def anthropic_messages(
    request: Request,
    x_galaris_task_id: Optional[str] = Header(default=None),
    x_galaris_agent_run_id: Optional[str] = Header(default=None),
    x_galaris_conversation_round_id: Optional[str] = Header(default=None),
    x_galaris_process_run_id: Optional[str] = Header(default=None),
    x_galaris_reasoning_effort: Optional[str] = Header(default=None),
    x_galaris_force_reasoning_effort: Optional[str] = Header(default=None),
):
    try:
        return await _anthropic_messages_body(
            request,
            x_galaris_task_id,
            x_galaris_agent_run_id,
            x_galaris_conversation_round_id,
            x_galaris_process_run_id,
            x_galaris_reasoning_effort,
            x_galaris_force_reasoning_effort,
        )
    except HTTPException as exc:
        return _http_exception_response(exc)


async def _anthropic_messages_body(
    request: Request,
    x_galaris_task_id: Optional[str],
    x_galaris_agent_run_id: Optional[str],
    x_galaris_conversation_round_id: Optional[str],
    x_galaris_process_run_id: Optional[str],
    x_galaris_reasoning_effort: Optional[str],
    x_galaris_force_reasoning_effort: Optional[str],
):
    agent_id = await _anthropic_api_auth(request)
    body: dict[str, Any] = await request.json()
    # External profile clients may discuss unrelated Galaris records in tools.
    use_prompt_context = not is_profile_api(request) or agent_id is not None
    if use_prompt_context:
        extract_process_context(body)
    try:
        parsed = MessageRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if not parsed.model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=await tr("llm_api.errors.model_required"),
        )
    if not parsed.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=await tr("anthropic_api.errors.messages_required"),
        )

    openai_body = translate_to_openai(parsed)
    correlation_messages = openai_body.get("messages") if use_prompt_context else None
    input_tokens = estimate_openai_body_tokens(openai_body)

    raw_conversation_round_id = (
        x_galaris_conversation_round_id
        or body.get("galaris_conversation_round_id")
    )
    conversation_round_id = (
        UUID(str(raw_conversation_round_id))
        if raw_conversation_round_id
        else None
    )
    # Explicit Task metadata beats prompt correlation, then the runtime agent's
    # local or durable unique Task (a known round skips the fallback).
    raw_task_id = x_galaris_task_id or body.get("galaris_task_id")
    task_id = await resolve_runtime_task_id(
        raw_task_id=raw_task_id,
        messages=correlation_messages,
        agent_id=(None if conversation_round_id is not None else agent_id),
    )

    raw_agent_run_id = x_galaris_agent_run_id or body.get("galaris_agent_run_id")
    agent_run_id = (
        UUID(str(raw_agent_run_id))
        if raw_agent_run_id
        else agent_run_id_from_messages(correlation_messages)
    )

    explicit_llm_id = body.get("galaris_llm_id") or llm_id_from_messages(
        correlation_messages
    )
    llm_override = None
    if explicit_llm_id is not None:
        llm_override = await llm_service.get_llm(int(explicit_llm_id))
        if llm_override is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=render_prompt(
                    await tr("llm_api.errors.llm_code_not_found"),
                    llm_id=explicit_llm_id,
                ),
            )

    raw_process_run_id = x_galaris_process_run_id or body.get(
        "galaris_process_run_id"
    )
    workflow_id = body.get("galaris_workflow_id")
    engine_run_id = body.get("galaris_engine_run_id")
    agent_ids = (
        await _anthropic_api_agent_ids(agent_id)
        if raw_process_run_id or (workflow_id and engine_run_id)
        else None
    )
    process_run_id = await resolve_runtime_process_run_id(
        raw_process_run_id=raw_process_run_id,
        workflow_id=workflow_id,
        engine_run_id=engine_run_id,
        task_id=task_id,
        agent_ids=agent_ids,
    )
    if process_run_id is not None:
        from app.process import process_service

        if agent_ids is None:
            agent_ids = await _anthropic_api_agent_ids(agent_id)
        await process_service.record_inbound_call(
            process_run_id,
            kind="llm",
            target_code=parsed.model,
            metadata={"correlation_id": body.get("galaris_correlation_id")},
            agent_ids=agent_ids,
        )

    try:
        proxy_response = await call_proxy(
            openai_body,
            profile_model=is_profile_api(request),
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            process_run_id=process_run_id,
            agent_id=agent_id,
            reasoning_effort=normalize_reasoning_effort(
                x_galaris_reasoning_effort or body.get("galaris_reasoning_effort"),
                strict=True,
            ),
            force_reasoning_effort=parse_force_reasoning_effort(
                x_galaris_force_reasoning_effort
                or body.get("galaris_force_reasoning_effort")
            ),
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if isinstance(proxy_response, JSONResponse):
        try:
            raw_payload: Any = json.loads(bytes(proxy_response.body))
        except (json.JSONDecodeError, TypeError):
            raw_payload = None
        # Keep the original shape for error text; object bodies drive the
        # completion translation below, which expects a dict.
        payload = (
            cast(dict[str, Any], raw_payload)
            if isinstance(raw_payload, dict)
            else {}
        )
        if proxy_response.status_code >= 400 or payload.get("error"):
            # The upstream rejected before streaming (or the client did not ask
            # to stream): return the Anthropic error envelope with the same code.
            return JSONResponse(
                content=error_envelope(
                    _provider_error_text(raw_payload),
                    error_status_type(proxy_response.status_code),
                ),
                status_code=proxy_response.status_code,
                headers=_call_id_headers(proxy_response),
            )
        translated = translate_completion(
            payload,
            model=str(openai_body["model"]),
            input_tokens=input_tokens,
        )
        return JSONResponse(
            content=translated,
            headers=_call_id_headers(proxy_response),
        )

    translator = AnthropicStreamTranslator(
        model=str(openai_body["model"]),
        input_tokens=input_tokens,
    )
    return StreamingResponse(
        translate_proxy_stream(proxy_response, translator),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            **_call_id_headers(proxy_response),
        },
    )


router.include_router(anthropic_router)
router.include_router(profile_api_router)
