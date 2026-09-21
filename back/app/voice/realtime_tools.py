"""Small, governed Galaris tool surface for realtime voice sessions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, cast
from uuid import UUID

from app.llm.provider_facade import RealtimeToolDefinition
from core.database import get_db_session


@dataclass(frozen=True, slots=True)
class RealtimeTool:
    definition: RealtimeToolDefinition
    execute: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def realtime_tools(
    *,
    agent_id: int,
    conversation_id: str,
    transport_kind: str,
    language: str,
    topic_id: UUID | None = None,
    contact_memory_item_id: UUID | None = None,
    voice_session_id: UUID | None = None,
    current_round_id: Callable[[], UUID | None] | None = None,
    hangup_requested: asyncio.Event | None = None,
) -> tuple[RealtimeTool, ...]:
    pending_hangup = hangup_requested or asyncio.Event()

    async def voice_call_stop(_arguments: dict[str, Any]) -> dict[str, Any]:
        """Arm a real hangup after the provider finishes its final spoken response."""

        pending_hangup.set()
        return {"hangup_requested": True}

    async def memory_search(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.memory import search_memory_detailed
        from app.memory.service import projected_topic_item_id

        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query must not be empty")
        raw_limit = arguments.get("limit")
        limit = (
            max(1, min(50, int(raw_limit)))
            if isinstance(raw_limit, int)
            else None
        )
        async with get_db_session():
            topic_item_id = await projected_topic_item_id(topic_id)
            result = await search_memory_detailed(
                query,
                agent_id=agent_id,
                limit=limit,
                topic_item_id=topic_item_id,
                contact_item_id=contact_memory_item_id,
                record_llm_access=True,
                telemetry_kind="search",
            )
        return {
            "query": result.query,
            "mode": result.mode,
            "degraded": result.degraded,
            "items": [
                {
                    "id": str(hit.item.id),
                    "title": hit.item.title,
                    "type": hit.item.memory_type,
                    "excerpt": hit.excerpt,
                    "source_refs": hit.source_refs,
                }
                for hit in result.hits
            ],
        }

    async def memory_remember(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.memory import (
            MemoryAcquisitionCreate,
            acquire_memory,
            ensure_contact_memory_scope,
            ensure_topic_contact_memory_scope,
            ensure_topic_memory_link,
        )
        from app.memory.service import projected_topic_item_id

        content = str(arguments.get("content") or "").strip()
        title = str(arguments.get("title") or "").strip()
        if not content or not title:
            raise ValueError("content and title must not be empty")
        memory_type = str(arguments.get("memory_type") or "semantic").strip()
        allowed_types = {
            "core",
            "working",
            "episodic",
            "semantic",
            "procedural",
            "social",
        }
        if memory_type not in allowed_types:
            raise ValueError(f"unsupported memory_type: {memory_type}")
        raw_keywords = arguments.get("keywords")
        keywords = (
            [str(value).strip() for value in cast(list[object], raw_keywords)]
            if isinstance(raw_keywords, list)
            else []
        )
        keywords = [value for value in keywords if value][:50]
        round_id = current_round_id() if current_round_id is not None else None
        if round_id is not None:
            source_kind = "conversation_round"
            source_ref = f"conversation_round:{round_id}"
        elif voice_session_id is not None:
            source_kind = "voice_session"
            source_ref = f"voice_session:{voice_session_id}"
        else:
            source_kind = "voice_conversation"
            source_ref = f"voice_conversation:{conversation_id}"

        async with get_db_session():
            topic_item_id = await projected_topic_item_id(topic_id)
            scope_metadata = (
                {
                    "scope_mode": (
                        "topic_contact" if topic_item_id is not None else "contact"
                    ),
                    "contact_item_id": str(contact_memory_item_id),
                    **(
                        {"topic_item_id": str(topic_item_id)}
                        if topic_item_id is not None
                        else {}
                    ),
                }
                if contact_memory_item_id is not None
                else {}
            )
            acquisition = await acquire_memory(
                MemoryAcquisitionCreate(
                    agent_id=agent_id,
                    title=title,
                    content=content,
                    keywords=keywords,
                    source_kind=source_kind,
                    source_ref=source_ref,
                    metadata={
                        "memory_type": memory_type,
                        "requested_by": "agent",
                        "language": language,
                        **scope_metadata,
                    },
                )
            )
            memory_id = acquisition.memory_id
            if memory_id is not None:
                if topic_item_id is not None and contact_memory_item_id is not None:
                    await ensure_topic_contact_memory_scope(
                        owner_agent_id=agent_id,
                        topic_item_id=topic_item_id,
                        contact_item_id=contact_memory_item_id,
                        memory_item_id=memory_id,
                        source_kind=source_kind,
                        source_ref=source_ref,
                    )
                elif contact_memory_item_id is not None:
                    await ensure_contact_memory_scope(
                        owner_agent_id=agent_id,
                        contact_item_id=contact_memory_item_id,
                        memory_item_id=memory_id,
                        source_kind=source_kind,
                        source_ref=source_ref,
                    )
                elif topic_item_id is not None:
                    await ensure_topic_memory_link(
                        topic_item_id=topic_item_id,
                        memory_item_id=memory_id,
                    )
        return {
            "acquisition_id": str(acquisition.acquisition_id),
            "created": acquisition.created,
            "status": acquisition.status,
            "memory_id": str(memory_id) if memory_id is not None else None,
        }

    async def conversation_task_submit(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.agent import submit_realtime_task

        objective = str(arguments.get("objective") or "").strip()
        label = str(arguments.get("label") or "").strip()
        raw_disposition = str(arguments.get("disposition") or "CREATE_NEW")
        if raw_disposition not in {"CREATE_NEW", "AMEND_CURRENT", "AMEND_QUEUED", "REPLACE"}:
            raise ValueError(f"Unsupported Task disposition: {raw_disposition}")
        disposition = cast(
            Literal["CREATE_NEW", "AMEND_CURRENT", "AMEND_QUEUED", "REPLACE"],
            raw_disposition,
        )
        raw_target = str(arguments.get("target_task_id") or "").strip()
        target_selector = raw_target.removeprefix("galaris://task/")
        raw_revision = arguments.get("expected_revision")
        async with get_db_session():
            return await submit_realtime_task(
                agent_id=agent_id,
                objective=objective,
                label=label,
                conversation_id=conversation_id,
                transport_kind=transport_kind,
                language=language,
                disposition=disposition,
                target_task_id=UUID(target_selector) if target_selector else None,
                expected_revision=(
                    int(raw_revision) if isinstance(raw_revision, int) else None
                ),
                reason=str(arguments.get("reason") or "").strip() or None,
            )

    async def conversation_task_list(arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        from app.conversation import linked_work_snapshot

        try:
            room_id = UUID(conversation_id)
        except ValueError:
            return {"items": []}
        async with get_db_session():
            items = await linked_work_snapshot(room_id)
        return {"items": list(items)}

    async def conversation_task_status(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.agent import realtime_task_status

        raw_id = str(arguments.get("task_id") or "").strip()
        raw_id = raw_id.removeprefix("galaris://task/")
        task_id = UUID(raw_id)
        async with get_db_session():
            return await realtime_task_status(task_id, agent_id=agent_id)

    async def process_list(_arguments: dict[str, Any]) -> dict[str, Any]:
        from app.process import process_service

        async with get_db_session():
            items = await process_service.list_for_agent(agent_id)
        return {"items": items}

    async def process_get(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.process import process_service

        workflow_id = str(arguments.get("workflow_id") or "").strip()
        if not workflow_id:
            raise ValueError("workflow_id must not be empty")
        async with get_db_session():
            process = await process_service.get_for_agent(agent_id, workflow_id)
            if process is None:
                return {"found": False, "workflow_id": workflow_id}
            return {
                "found": True,
                "workflow_id": process.engine_process_id,
                "label": process.label,
                "description": process.description,
            }

    async def conversation_process_start(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.process import process_service

        workflow_id = str(arguments.get("workflow_id") or "").strip()
        raw_input = arguments.get("input")
        input_data = cast(dict[str, Any], raw_input) if isinstance(raw_input, dict) else {}
        if not workflow_id:
            raise ValueError("workflow_id must not be empty")
        async with get_db_session():
            response = await process_service.start_process(
                agent_id=agent_id,
                workflow_id=workflow_id,
                input_data=input_data,
                wait_for_completion=False,
                task_id=None,
                runtime="internal",
            )
        return {"created": not response.deduplicated, **response.model_dump(mode="json")}

    return (
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="voice_call_stop",
                description=(
                    "End this live audio call for real after your final brief spoken "
                    "response. Use it whenever the caller asks to hang up, end, or "
                    "disconnect the call; never merely claim that you did."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            execute=voice_call_stop,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="memory_search",
                description=(
                    "Search the agent's governed long-term memory for preferences, "
                    "prior decisions, people, projects, or procedures."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Short focused memory query.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": (
                                "Optional per-call override. Omit it to use the configured "
                                "Memory result limit."
                            ),
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            execute=memory_search,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="memory_remember",
                description=(
                    "Store one lasting governed memory from this call. Use sparingly for an "
                    "explicit memory request, a correction, or an especially important confirmed "
                    "fact worth retaining immediately. Leave routine extraction and duplicate "
                    "checking to Dream; skip equivalent known memories. Do not store transient "
                    "status, secrets, or raw transcripts."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "title": {"type": "string"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "core",
                                "working",
                                "episodic",
                                "semantic",
                                "procedural",
                                "social",
                            ],
                            "default": "semantic",
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 50,
                        },
                    },
                    "required": ["content", "title"],
                    "additionalProperties": False,
                },
            ),
            execute=memory_remember,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="conversation_task_list",
                description=(
                    "List the canonical recent Task candidates for this conversation. Call this before "
                    "submitting background work. Amend only the same primary artifact or target "
                    "with substantially unchanged success criteria; related independent work "
                    "must receive a new Task, even within the same document."
                ),
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            execute=conversation_task_list,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="conversation_task_submit",
                description=(
                    "Create or amend a durable Galaris Task after comparing the request with "
                    "conversation_task_list. Use CREATE_NEW for a different target, repository, "
                    "resource, deliverable, or independently verifiable outcome, even when the "
                    "same document or incident connects them. If either outcome can be completed "
                    "without the other, leave existing work unchanged. Ask the caller when the relationship is "
                    "ambiguous. Use REPLACE for an explicit replacement; the successor waits "
                    "for confirmed stop of target_task_id at expected_revision."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "objective": {
                            "type": "string",
                            "description": "Complete actionable task objective.",
                        },
                        "label": {
                            "type": "string",
                            "description": "Short task title.",
                        },
                        "disposition": {
                            "type": "string",
                            "enum": ["CREATE_NEW", "AMEND_CURRENT", "AMEND_QUEUED", "REPLACE"],
                            "default": "CREATE_NEW",
                        },
                        "target_task_id": {
                            "type": "string",
                            "description": "Canonical galaris://task/<uuid> URI.",
                        },
                        "expected_revision": {"type": "integer", "minimum": 1},
                        "reason": {"type": "string"},
                    },
                    "required": ["objective"],
                    "additionalProperties": False,
                },
            ),
            execute=conversation_task_submit,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="conversation_task_status",
                description="Read the current status and result of a Galaris task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Canonical galaris://task/<uuid> URI.",
                        }
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            ),
            execute=conversation_task_status,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="process_list",
                description="List the business Processes assigned to this agent.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            execute=process_list,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="process_get",
                description="Read one assigned business Process by workflow ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "string"},
                    },
                    "required": ["workflow_id"],
                    "additionalProperties": False,
                },
            ),
            execute=process_get,
        ),
        RealtimeTool(
            definition=RealtimeToolDefinition(
                name="conversation_process_start",
                description=(
                    "Start an assigned business Process asynchronously and return immediately."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "string"},
                        "input": {"type": "object"},
                    },
                    "required": ["workflow_id"],
                    "additionalProperties": False,
                },
            ),
            execute=conversation_process_start,
        ),
    )


async def execute_realtime_tool(
    tools: tuple[RealtimeTool, ...],
    *,
    name: str,
    arguments: str,
) -> str:
    """Validate and execute one known tool, returning JSON for the provider."""

    selected = next((tool for tool in tools if tool.definition.name == name), None)
    if selected is None:
        return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
    try:
        raw = json.loads(arguments or "{}")
        if not isinstance(raw, dict):
            raise ValueError("tool arguments must be an object")
        raw_mapping = cast(dict[object, object], raw)
        result = await selected.execute(
            {str(key): value for key, value in raw_mapping.items()}
        )
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:2_000],
            },
            ensure_ascii=False,
        )


__all__ = ["RealtimeTool", "execute_realtime_tool", "realtime_tools"]
