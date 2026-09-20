"""Expose agent execution through OpenAI-compatible task-backed completions."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Collection
from typing import Any, AsyncIterator, Dict
from uuid import UUID, uuid4

from sqlalchemy import select

from core.database import get_db
from core.authorize import check_privilege, role_id_ctx
from core.user import UserModel, get_current_user_id
from core.i18n import render_prompt, tr
from app.agent.models import Agent

from .contracts import TaskMessage
from .contracts import AgentTaskDraft, ExecutionResult, TaskPhase
from .task_port import task_port
from .dialogue_service import dialogue_scope_for
from .openai_schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChunkChoice,
    ModelObject,
    ModelListResponse,
    Choice,
    Message,
    Usage,
)


def convert_openai_messages_to_messenger(
    messages: list[Message],
    self_id: str = "galaris-bot",
) -> list[TaskMessage]:
    """Convert OpenAI messages into canonical messages, preserving assistant identity."""
    current_time = int(time.time())
    result: list[TaskMessage] = []

    for idx, msg in enumerate(messages):
        role = msg.role
        content = msg.content

        if isinstance(content, list):
            texts = [str(seg.get("text", "")) for seg in content]
            message_text = "".join(texts).strip()
        elif content is None:
            message_text = ""
        else:
            message_text = str(content).strip()

        if role == "assistant":
            user_id = self_id
        elif role == "tool":
            user_id = msg.tool_call_id or f"tool-{idx}"
        else:
            user_id = msg.name or f"user-{idx}"

        result.append(TaskMessage(
            external_message_id=f"openai-{idx}",
            timestamp=current_time,
            text=message_text,
            sender_external_id=user_id,
            sender_display_name=msg.name or role,
            sender_is_ai=role == "assistant",
        ))

    return result


async def list_agent_models(
    *,
    agent_ids: Collection[int] | None = None,
) -> ModelListResponse:
    """List agents exposed as OpenAI-compatible models."""
    db = get_db()
    query = select(Agent)
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    result = await db.execute(query)
    agents = result.scalars().all()

    return ModelListResponse(
        data=[
            *[ModelObject(id=agent.code, owned_by="galaris") for agent in agents],
        ]
    )


async def list_models() -> ModelListResponse:
    """Legacy alias; the public endpoint is now /agent/openai/models."""
    return await list_agent_models()


async def prepare_task(
    agent: Agent,
    request: ChatCompletionRequest,
    conversation_id: str | None = None,
    process_run_id: UUID | None = None,
) -> Any:
    """Create a task for agent processing."""
    if conversation_id is None:
        conversation_id = f"galaris-{uuid4().hex[:12]}"
    from core.user import user_service
    human_id = user_service.get_current_user_id()
    scoped_conversation = f"human:{human_id}:{conversation_id}" if human_id is not None else conversation_id

    label = render_prompt(
        await tr("agent_api.openai_task.label"),
        agent_code=agent.code,
    )
    objective = render_prompt(
        await tr("agent_api.openai_task.objective"),
        message=request.messages[-1].content,
    )
    task_data = AgentTaskDraft(
        agent_id=agent.id,
        label=label,
        message_platform="openai",
        message_group_id=None,
        data={
            "conversation_id": scoped_conversation,
            **({"process_run_id": str(process_run_id)} if process_run_id else {}),
        },
        messages=tuple(
            message.model_dump(mode="json")
            for message in convert_openai_messages_to_messenger(request.messages)
        ),
        objective=objective,
        status=TaskPhase.CREATE,
        ai=True,
    )
    new_task = await task_port.create(task_data)
    # Reload eager relationships required by the dispatcher and driver.
    loaded = await task_port.get_by_id(new_task.id)
    return loaded or new_task


async def run_local_chat_completion(
    agent: Agent,
    request: ChatCompletionRequest,
    raw_body: Dict[str, Any] | None = None,
) -> AsyncIterator[str] | ChatCompletionResponse:
    """Run a completion and return either an SSE iterator or a complete response."""
    # OpenAI Chat Completions is stateless. Continuity is explicit through the
    # Galaris ``conversation_id`` extension; absent ids start an independent run.
    conversation_id = request.conversation_id or f"galaris-{uuid4().hex[:12]}"
    user_id = get_current_user_id()
    role_id = role_id_ctx.get()

    process_run_id: UUID | None = None
    if raw_body and raw_body.get("galaris_process_run_id"):
        process_run_id = UUID(str(raw_body["galaris_process_run_id"]))
    task = (
        await prepare_task(agent, request, conversation_id, process_run_id)
        if process_run_id is not None
        else await prepare_task(agent, request, conversation_id)
    )

    # The scheduler is the sole dispatcher-to-driver execution authority.
    task_port.schedule(task.id, fast=True)

    if request.stream:
        stream = _local_stream_response(task.id, request.model, conversation_id)
        return _authorized_stream(stream, agent.id, user_id, role_id)

    execution_result = await _wait_for_task_completion(task.id)
    await _require_completion_access(agent.id, user_id, role_id)
    return _local_json_response(execution_result, request.model, conversation_id)


async def _require_completion_access(agent_id: int, user_id: int | None, role_id: int | None) -> None:
    if user_id is None:
        return  # Internal service calls have no human API caller.
    from core.database import get_db_session

    token = role_id_ctx.set(role_id)
    try:
        async with get_db_session() as db:
            user = await db.scalar(select(UserModel).where(UserModel.id == user_id))
            if user is None or not await check_privilege(user, "AGENT_API_ACCESS", db):
                raise PermissionError("Agent API access was revoked")
            scope = await dialogue_scope_for(user, db)
            scope.require(agent_id)
    finally:
        role_id_ctx.reset(token)


async def _authorized_stream(
    stream: AsyncIterator[str], agent_id: int, user_id: int | None, role_id: int | None,
) -> AsyncIterator[str]:
    async for chunk in stream:
        try:
            await _require_completion_access(agent_id, user_id, role_id)
        except PermissionError:
            yield "data: " + json.dumps({"error": {"type": "permission_denied", "message": "Agent access was revoked"}}) + "\n\n"
            yield "data: [DONE]\n\n"
            return
        yield chunk


def _local_json_response(
    execution_result: Any,
    model: str,
    conversation_id: str,
) -> ChatCompletionResponse:
    """Build an OpenAI JSON response from an execution result."""
    created = int(time.time())
    completion_id = f"chatcmpl-{uuid4().hex[:16]}"
    content = execution_result.result or ""

    return ChatCompletionResponse(
        id=completion_id,
        object="chat.completion",
        created=created,
        model=model,
        choices=[
            Choice(
                index=0,
                message=Message(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(),
        conversation_id=conversation_id,
    )


_TASK_POLL_INTERVAL_SECONDS = 0.25
_TERMINAL_STATUSES = {TaskPhase.SUCCESS, TaskPhase.ERROR}


async def _load_task(task_id: UUID) -> Any | None:
    from core.database import get_db_session

    async with get_db_session():
        return await task_port.get_by_id(task_id)


async def _wait_for_task_completion(task_id: UUID) -> Any:
    while True:
        task = await _load_task(task_id)
        if task is None:
            return ExecutionResult(
                prompt="",
                success=False,
                result=render_prompt(
                    await tr("agent_api.errors.task_not_found"),
                    task_id=task_id,
                ),
            )
        if task.status in _TERMINAL_STATUSES:
            return task.get_execution_result() or ExecutionResult(
                prompt="",
                success=task.status == TaskPhase.SUCCESS,
                result=task.feedback or "",
            )
        await asyncio.sleep(_TASK_POLL_INTERVAL_SECONDS)


def _execution_text_snapshot(task: Any) -> str:
    execution_result = task.get_execution_result()
    if execution_result is None:
        return ""
    return "".join(
        message.content
        for message in execution_result.messages
        if message.type == "text" and message.content
    )


def _local_stream_response(
    task_id: UUID,
    model: str,
    conversation_id: str,
) -> AsyncIterator[str]:
    """Observe a scheduler-owned task and relay new execution text as SSE chunks."""
    completion_id = f"chatcmpl-{uuid4().hex[:16]}"
    created = int(time.time())

    def _content_chunk(delta: str) -> str:
        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[ChunkChoice(index=0, delta={"content": delta}, finish_reason=None)],
        )
        return f"data: {chunk.model_dump_json()}\n\n"

    async def event_generator() -> AsyncIterator[str]:
        # Initial role chunk.
        first_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[ChunkChoice(index=0, delta={"role": "assistant"}, finish_reason=None)],
            conversation_id=conversation_id,
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        emitted = ""
        while True:
            task = await _load_task(task_id)
            if task is None:
                break

            snapshot = _execution_text_snapshot(task)
            if snapshot.startswith(emitted) and len(snapshot) > len(emitted):
                yield _content_chunk(snapshot[len(emitted):])
                emitted = snapshot

            if task.status in _TERMINAL_STATUSES:
                execution_result = task.get_execution_result()
                final_text = execution_result.result if execution_result is not None else ""
                if final_text.startswith(emitted) and len(final_text) > len(emitted):
                    yield _content_chunk(final_text[len(emitted):])
                break

            await asyncio.sleep(_TASK_POLL_INTERVAL_SECONDS)

        # Final chunk.
        final_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[ChunkChoice(index=0, delta={}, finish_reason="stop")],
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return event_generator()
