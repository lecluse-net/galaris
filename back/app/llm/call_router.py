"""OpenAI-compatible LLM routes and LLM call-trace inspection."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from core.authorize import Privileges, authorize, independent_auth
from core.authorize.logic import check_privilege
from core.database import get_db
from core.i18n import render_prompt, tr
from core.user import user_service
from app.agent import current_management_scope

from . import llm_call_service, llm_service
from . import inference_execution, inference_store
from .contracts import (
    InferenceRead, InferenceCommand, InferenceControlInput,
    TextInferenceRequest, StructuredInferenceRequest,
)
from .facade import AgentRunUsage, aggregate_agent_run_usage
from .protocol_inference import proxy_chat_completion, proxy_responses
from .provider_facade import ProviderAuthenticationError
from .profile_gateway import is_profile_api, mark_profile_api, profile_models
from .reasoning import normalize_reasoning_effort, parse_force_reasoning_effort
from .schemas import LLMCallPage, LLMCallRead, ProxyModel, ProxyModelList
from .runtime_correlation import (
    resolve_runtime_process_run_id as _resolve_llm_process_run_id,
    resolve_runtime_task_id as _resolve_llm_task_id,
)
from .trace import (
    agent_run_id_from_messages,
    extract_process_context,
    llm_id_from_messages,
)


router = APIRouter()
llm_api_router = APIRouter(prefix="/llm/openai", tags=["OpenAI-like LLM"])
profile_api_router = APIRouter(
    prefix="/profile/openai", tags=["OpenAI-like profiles"],
    dependencies=[Depends(mark_profile_api)],
)
calls_router = APIRouter(prefix="/llm-calls", tags=["llm-calls"])


async def _llm_api_auth(request: Request) -> int | None:
    """Authenticate requests to /api/llm/openai.

    Accept either a managed-runtime token identifying an agent or an authenticated
    user's JWT/API token. Return the agent ID only for runtime authentication.
    """
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
                detail=render_prompt(
                    await tr("authorize_api.errors.missing_privilege"),
                    privileges=[Privileges.LLM_API_ACCESS],
                ),
            )
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=await tr("llm_api.errors.invalid_llm_token"),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _llm_api_agent_ids(agent_id: int | None) -> frozenset[int] | None:
    """Pin runtime tokens to their Agent and human tokens to management scope."""

    if agent_id is not None:
        return frozenset((agent_id,))
    return (await current_management_scope()).agent_ids


async def authenticate_llm_api(request: Request) -> int | None:
    """Share the gateway's authentication with specialized inference endpoints."""
    return await _llm_api_auth(request)


async def _visible_inference(request: Request, inference_id: UUID) -> InferenceRead:
    agent_id = await _llm_api_auth(request)
    agent_ids = await _llm_api_agent_ids(agent_id)
    user = await user_service.get_current_user() if agent_id is None else None
    allowed = await inference_execution.transaction(lambda: inference_store.can_access(
        inference_id, requester_user_id=user.id if user else None, agent_ids=agent_ids,
    ))
    if not allowed:
        raise HTTPException(status_code=404, detail=await tr("llm_api.errors.inference_not_found"))
    return await inference_execution.read(inference_id)


@llm_api_router.post("/inferences", response_model=InferenceRead, status_code=202)
@independent_auth(reason="User with LLM_API_ACCESS; scoped standalone inference")
async def create_inference(
    request: Request, body: TextInferenceRequest | StructuredInferenceRequest,
) -> InferenceRead:
    agent_id = await _llm_api_auth(request)
    scope = await _llm_api_agent_ids(agent_id)
    # Correlated runtime work enters through the existing authenticated gateway.
    if agent_id is not None or any((body.task_id, body.agent_run_id,
                                   body.conversation_round_id, body.process_run_id)):
        raise HTTPException(status_code=403, detail=await tr("llm_api.errors.inference_runtime_required"))
    if body.agent_id is not None and scope is not None and body.agent_id not in scope:
        raise HTTPException(status_code=404, detail=await tr("llm_api.errors.inference_agent_not_found"))
    try:
        key = await inference_execution.submit(body)
    except ProviderAuthenticationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await inference_execution.read(key)


@llm_api_router.get("/inferences/{inference_id}", response_model=InferenceRead)
@independent_auth(reason="LLM API authentication and inference ownership or management scope")
async def get_inference(request: Request, inference_id: UUID) -> InferenceRead:
    return await _visible_inference(request, inference_id)


@llm_api_router.post("/inferences/{inference_id}/commands", response_model=InferenceCommand)
@independent_auth(reason="LLM API authentication and inference ownership or management scope")
async def command_inference(
    request: Request, inference_id: UUID, body: InferenceControlInput,
) -> InferenceCommand:
    from uuid import uuid4

    await _visible_inference(request, inference_id)
    try:
        return await inference_execution.command(inference_id, body.action, body.command_id or uuid4())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@llm_api_router.get("/inferences/{inference_id}/events")
@independent_auth(reason="LLM API authentication and inference ownership or management scope")
async def inference_events(
    request: Request, inference_id: UUID, attempt_id: UUID | None = None,
    after_sequence: int = Query(default=0, ge=0),
) -> StreamingResponse:
    snapshot = await _visible_inference(request, inference_id)
    selected = attempt_id or snapshot.attempts[-1].id
    if not any(item.id == selected for item in snapshot.attempts):
        raise HTTPException(status_code=404, detail=await tr("llm_api.errors.inference_attempt_not_found"))

    async def stream():
        async for event in inference_execution.events(
            inference_id, attempt_id=selected, after_sequence=after_sequence,
        ):
            yield f"id: {event.sequence}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@llm_api_router.get("/models", response_model=ProxyModelList)
@profile_api_router.get("/models", response_model=ProxyModelList)
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def llm_models(request: Request) -> ProxyModelList:
    await _llm_api_auth(request)
    if is_profile_api(request):
        return ProxyModelList(data=await profile_models(("chat", "embedding")))
    llms = await llm_service.list_llms(capability="chat")
    return ProxyModelList(data=[
        ProxyModel(
            id=llm.code,
            owned_by=llm.provider.name if llm.provider else "galaris",
            context_length=llm.context_length,
        )
        for llm in llms
    ])


@llm_api_router.post("/chat/completions")
@profile_api_router.post("/chat/completions")
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def llm_completion(
    request: Request,
    x_galaris_task_id: Optional[str] = Header(default=None),
    x_galaris_agent_run_id: Optional[str] = Header(default=None),
    x_galaris_conversation_round_id: Optional[str] = Header(default=None),
    x_galaris_process_run_id: Optional[str] = Header(default=None),
    x_galaris_reasoning_effort: Optional[str] = Header(default=None),
    x_galaris_force_reasoning_effort: Optional[str] = Header(default=None),
):
    try:
        agent_id = await _llm_api_auth(request)
        body: dict[str, Any] = await request.json()
        # External profile clients may discuss unrelated Galaris records in tools.
        use_prompt_context = not is_profile_api(request) or agent_id is not None
        if use_prompt_context:
            extract_process_context(body)
        correlation_messages = body.get("messages") if use_prompt_context else None
        raw_task_id = x_galaris_task_id or body.get("galaris_task_id")
        raw_conversation_round_id = (
            x_galaris_conversation_round_id
            or body.get("galaris_conversation_round_id")
        )
        conversation_round_id = (
            UUID(str(raw_conversation_round_id))
            if raw_conversation_round_id
            else None
        )
        # Explicit task ID beats prompt correlation, then the active runtime Task.
        # The final fallback captures subagent calls without Galaris message context.
        task_id = await _resolve_llm_task_id(
            raw_task_id=raw_task_id,
            messages=correlation_messages,
            agent_id=(
                None if conversation_round_id is not None else agent_id
            ),
        )
        raw_agent_run_id = (
            x_galaris_agent_run_id or body.get("galaris_agent_run_id")
        )
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
                raise LookupError(
                    render_prompt(
                        await tr("llm_api.errors.llm_code_not_found"),
                        llm_id=explicit_llm_id,
                    )
                )
        raw_process_run_id = x_galaris_process_run_id or body.get("galaris_process_run_id")
        workflow_id = body.get("galaris_workflow_id")
        engine_run_id = body.get("galaris_engine_run_id")
        agent_ids = (
            await _llm_api_agent_ids(agent_id)
            if raw_process_run_id or (workflow_id and engine_run_id)
            else None
        )
        process_run_id = await _resolve_llm_process_run_id(
            raw_process_run_id=raw_process_run_id,
            workflow_id=workflow_id,
            engine_run_id=engine_run_id,
            task_id=task_id,
            agent_ids=agent_ids,
        )
        if process_run_id is not None:
            from app.process import process_service

            if agent_ids is None:
                agent_ids = await _llm_api_agent_ids(agent_id)
            model_code = str(body.get("model") or "")
            await process_service.record_inbound_call(
                process_run_id,
                kind="llm",
                target_code=model_code,
                metadata={"correlation_id": body.get("galaris_correlation_id")},
                agent_ids=agent_ids,
            )
        return await proxy_chat_completion(
            body,
            profile_model=is_profile_api(request),
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            process_run_id=process_run_id,
            agent_id=agent_id,
            llm_override=llm_override,
            unwrap_deferred_tools=agent_id is not None,
            managed_runtime_request=agent_id is not None,
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        raise


@llm_api_router.post("/responses")
@llm_api_router.post("/responses/compact")
@profile_api_router.post("/responses")
@profile_api_router.post("/responses/compact")
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def llm_responses(
    request: Request,
    x_galaris_task_id: Optional[str] = Header(default=None),
    x_galaris_agent_run_id: Optional[str] = Header(default=None),
    x_galaris_process_run_id: Optional[str] = Header(default=None),
    x_galaris_model_code: Optional[str] = Header(default=None),
    x_galaris_reasoning_effort: Optional[str] = Header(default=None),
    x_galaris_force_reasoning_effort: Optional[str] = Header(default=None),
):
    """Expose the native Responses wire protocol to managed agent runtimes."""

    try:
        agent_id = await _llm_api_auth(request)
        body: dict[str, Any] = await request.json()
        raw_task_id = x_galaris_task_id or body.get("galaris_task_id")
        task_id = await _resolve_llm_task_id(
            raw_task_id=raw_task_id,
            messages=None,
            agent_id=agent_id,
        )
        raw_agent_run_id = x_galaris_agent_run_id or body.get("galaris_agent_run_id")
        agent_run_id = UUID(str(raw_agent_run_id)) if raw_agent_run_id else None
        raw_process_run_id = (
            x_galaris_process_run_id or body.get("galaris_process_run_id")
        )
        workflow_id = body.get("galaris_workflow_id")
        engine_run_id = body.get("galaris_engine_run_id")
        has_explicit_process = bool(
            raw_process_run_id or (workflow_id and engine_run_id)
        )
        agent_ids = (
            await _llm_api_agent_ids(agent_id) if has_explicit_process else None
        )
        process_run_id = await _resolve_llm_process_run_id(
            raw_process_run_id=raw_process_run_id,
            workflow_id=workflow_id,
            engine_run_id=engine_run_id,
            task_id=task_id,
            agent_ids=agent_ids,
        )
        if process_run_id is not None:
            from app.process import process_service

            if agent_ids is None:
                agent_ids = await _llm_api_agent_ids(agent_id)
            await process_service.record_inbound_call(
                process_run_id,
                kind="llm",
                target_code=str(
                    x_galaris_model_code or body.get("galaris_model_code")
                    or body.get("model") or ""
                ),
                metadata={"correlation_id": body.get("galaris_correlation_id")},
                agent_ids=agent_ids,
            )
        return await proxy_responses(
            body,
            profile_model=is_profile_api(request),
            operation=(
                "compact" if request.url.path.endswith("/responses/compact") else "create"
            ),
            task_id=task_id,
            agent_run_id=agent_run_id,
            process_run_id=process_run_id,
            agent_id=agent_id,
            model_code=x_galaris_model_code or body.get("galaris_model_code"),
            managed_runtime_request=agent_id is not None,
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        raise


@llm_api_router.get("/runs/{agent_run_id}/usage")
@independent_auth(
    reason="Managed-runtime capability token or user with LLM_API_ACCESS"
)
async def llm_run_usage(
    agent_run_id: UUID,
    request: Request,
) -> AgentRunUsage:
    """Return authoritative gateway accounting for one logical agent run."""

    agent_id = await _llm_api_auth(request)
    try:
        return await aggregate_agent_run_usage(agent_run_id, agent_id=agent_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail="The agent run belongs to another runtime.",
        ) from exc


@calls_router.get("", response_model=list[LLMCallRead])
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_calls(
    task_id: Optional[UUID] = None,
    task_ids: list[UUID] | None = Query(default=None, max_length=50),
    agent_run_ids: list[UUID] | None = Query(default=None, max_length=50),
    task_attempt_id: Optional[UUID] = None,
    conversation_round_id: Optional[UUID] = None,
    process_run_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[LLMCallRead]:
    scope = await current_management_scope()
    calls = await llm_call_service.list_calls(
        task_id=task_id,
        task_ids=task_ids,
        agent_run_ids=agent_run_ids,
        task_attempt_id=task_attempt_id,
        conversation_round_id=conversation_round_id,
        process_run_id=process_run_id,
        limit=limit,
        agent_ids=scope.agent_ids,
    )
    return await llm_call_service.serialize_calls(calls)


@calls_router.get("/running", response_model=list[LLMCallRead])
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_running_calls(
    limit: int = Query(default=10, ge=1, le=50),
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[LLMCallRead]:
    """List calls that are currently executing, newest first."""
    scope = await current_management_scope()
    calls = await llm_call_service.list_running_calls(
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        agent_ids=scope.agent_ids,
    )
    return await llm_call_service.serialize_calls(calls)


@calls_router.get("/history", response_model=LLMCallPage)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_call_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    errors_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
) -> LLMCallPage:
    scope = await current_management_scope()
    calls, total, summary = await llm_call_service.paginate_history(
        page=page,
        page_size=page_size,
        errors_only=errors_only,
        date_from=date_from,
        date_to=date_to,
        agent_ids=scope.agent_ids,
    )
    return LLMCallPage(
        items=await llm_call_service.serialize_calls(calls),
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
    )


@calls_router.delete("/cleanup", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.LLM_CALL_PURGE)
async def cleanup_calls() -> None:
    """Permanently delete completed LLM calls."""
    scope = await current_management_scope()
    await llm_call_service.cleanup_all(agent_ids=scope.agent_ids)
    return None


@calls_router.get("/retention/preview")
@authorize(privileges=Privileges.LLM_CALL_PURGE)
async def preview_call_retention() -> dict[str, int]:
    from .retention import preview_trace_retention

    scope = await current_management_scope()
    return await preview_trace_retention(agent_ids=scope.agent_ids)


@calls_router.delete("/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.LLM_CALL_PURGE)
async def delete_call(call_id: UUID) -> None:
    """Permanently delete an LLM call, including a running call."""
    scope = await current_management_scope()
    try:
        deleted = await llm_call_service.delete_call(call_id, agent_ids=scope.agent_ids)
    except llm_call_service.InferenceCallDeletionError as exc:
        raise HTTPException(
            status_code=409, detail=await tr("llm_api.errors.inference_call_protected"),
        ) from exc
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=await tr("llm_api.errors.call_not_found"),
        )
    return None


@calls_router.get("/{call_id}", response_model=LLMCallRead)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_call(call_id: UUID) -> LLMCallRead:
    scope = await current_management_scope()
    call = await llm_call_service.get_call(call_id, agent_ids=scope.agent_ids)
    if call is None:
        raise HTTPException(
            status_code=404,
            detail=await tr("llm_api.errors.call_not_found"),
        )
    return await llm_call_service.serialize_call(call)


router.include_router(llm_api_router)
router.include_router(profile_api_router)
router.include_router(calls_router)
