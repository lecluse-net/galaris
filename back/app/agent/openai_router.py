"""OpenAI-compatible routes for the agent module."""

from __future__ import annotations

from typing import Any, Dict
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger

from core.authorize import Privileges, authorize
from core.i18n import render_prompt, tr
from app.llm.trace import extract_process_context

from . import agent_service
from .janus import MODEL_ID as JANUS_MODEL_ID
from .openai_schemas import ChatCompletionRequest, ModelListResponse
from .openai_service import list_agent_models, run_local_chat_completion
from .management_scope import current_management_scope
from .dialogue_service import current_dialogue_scope


router = APIRouter()
agent_router = APIRouter(prefix="/agent/openai", tags=["OpenAI-like Agents"])
janus_router = APIRouter(prefix="/janus/openai", tags=["OpenAI-like Janus"])


def _streaming_response(result: Any) -> StreamingResponse:
    return StreamingResponse(
        result,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _parse_chat_completion_body(raw_request: Request) -> tuple[ChatCompletionRequest, Dict[str, Any]]:
    body: Dict[str, Any] = await raw_request.json()
    extract_process_context(body)
    try:
        return ChatCompletionRequest.model_validate(body), body
    except Exception as validation_error:
        logger.warning("Validation OpenAI-like: {}", validation_error)
        # OpenWebUI compatibility for payloads that send user_message instead of messages.
        if "user_message" in body and "messages" not in body:
            user_msg = body["user_message"]
            body["messages"] = [{
                "role": user_msg.get("role", "user"),
                "content": user_msg.get("content", ""),
            }]
            return ChatCompletionRequest.model_validate(body), body
        raise


@agent_router.get(
    "/models",
    response_model=ModelListResponse,
    summary="List available agents",
    description="Return Galaris agents callable as OpenAI-compatible models.",
)
@authorize(privileges=Privileges.AGENT_API_ACCESS)
async def get_agent_models() -> ModelListResponse:
    scope = await current_dialogue_scope()
    return await list_agent_models(agent_ids=scope.agent_ids)


@agent_router.post(
    "/chat/completions",
    summary="Chat completion agent",
    description="OpenAI-compatible endpoint for calling a Galaris agent directly.",
)
@authorize(privileges=Privileges.AGENT_API_ACCESS)
async def agent_chat_completions(raw_request: Request):
    try:
        request, body = await _parse_chat_completion_body(raw_request)
        scope = await current_dialogue_scope()
        management = await current_management_scope()
        process_run_id: UUID | None = None
        raw_run_id = body.get("galaris_process_run_id")
        workflow_id = body.get("galaris_workflow_id")
        engine_run_id = body.get("galaris_engine_run_id")
        if not raw_run_id and workflow_id and engine_run_id:
            from app.process import process_service

            correlated_run = await process_service.resolve_engine_run(
                str(workflow_id),
                str(engine_run_id),
                agent_ids=management.agent_ids,
            )
            process_run_id = correlated_run.id
            body["galaris_process_run_id"] = str(correlated_run.id)
            raw_run_id = str(correlated_run.id)
        if raw_run_id:
            from app.process import process_service

            process_run_id = UUID(str(raw_run_id))
            await process_service.record_inbound_call(
                process_run_id,
                kind="agent",
                target_code=request.model,
                metadata={"correlation_id": body.get("galaris_correlation_id")},
                agent_ids=management.agent_ids,
            )
        agent = await agent_service.get_by_code(
            request.model,
            agent_ids=scope.agent_ids,
        )

        if agent is None:
            raise RuntimeError(render_prompt(
                await tr("agent_api.errors.code_not_found"), code=request.model
            ))

        result = await run_local_chat_completion(agent, request, body)

        if hasattr(result, "__aiter__"):
            return _streaming_response(result)
        return result

    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "message": str(e),
                    "type": "agent_error",
                }
            },
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Agent chat completion failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": render_prompt(
                        await tr("agent_api.errors.internal_error"),
                        error=e,
                    ),
                    "type": "internal_error",
                }
            },
        ) from e


@janus_router.get(
    "/models",
    response_model=ModelListResponse,
    summary="List the Janus model",
    description="Return only Janus and its configured aliases.",
)
@authorize(privileges=Privileges.AGENT_API_ACCESS)
async def get_janus_models() -> ModelListResponse:
    from .janus import alias_model_object, get_aliases, janus_model_object

    aliases = await get_aliases()
    return ModelListResponse(data=[
        janus_model_object(),
        *[alias_model_object(alias) for alias in aliases],
    ])


@janus_router.post(
    "/chat/completions",
    summary="Chat completion Janus",
    description="OpenAI-compatible endpoint for the Janus conversation router.",
)
@authorize(privileges=Privileges.AGENT_API_ACCESS)
async def janus_chat_completions(raw_request: Request):
    try:
        request, body = await _parse_chat_completion_body(raw_request)
        from .janus import get_aliases as _get_janus_aliases

        aliases = await _get_janus_aliases()
        if request.model != JANUS_MODEL_ID and request.model not in aliases:
            raise RuntimeError(render_prompt(
                await tr("agent_api.errors.janus_model_not_found"),
                model=request.model,
            ))

        from .janus import handle as janus_handle
        conversation_id = request.conversation_id or f"janus-{uuid4().hex[:12]}"
        result = await janus_handle(request, body, conversation_id)
        if hasattr(result, "__aiter__"):
            return _streaming_response(result)
        return result

    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "message": str(e),
                    "type": "janus_error",
                }
            },
        ) from e
    except Exception as e:
        logger.exception("Janus chat completion failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": render_prompt(
                        await tr("agent_api.errors.internal_error"), error=e
                    ),
                    "type": "internal_error",
                }
            },
        ) from e


router.include_router(agent_router)
router.include_router(janus_router)
