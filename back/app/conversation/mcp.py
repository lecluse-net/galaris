"""Small, idempotent MCP surface for the conversation control plane."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from sqlalchemy import select

from app.agent import (
    OBJECTIVE_IS_STANDALONE_DATA_KEY,
    TaskMessage,
    current_message_data,
    get_plan_progress,
)
from app.task import STARTUP_TIMING_DATA_KEY, TaskAdmissionTiming, Task, TaskCreate, TaskStatus, amendment_basis
from app.tools import (
    McpToolContext,
    mcp_tool,
    require_galaris_admin_access,
)
from core.database import get_db

from .contracts import ConversationTurn
from .document_display import can_display_conversation_document, display_conversation_document
from .inspection_service import inspect_round
from .models import ConversationProcessLink, ConversationRound, ConversationTaskLink
from .task_objective import compose_task_objective, generate_task_fields, source_request_html
from .preparation import ConversationSuperseded, run_preparation


_TASK_RESOURCE_PREFIX = "galaris://task/"


def _task_resource_uri(task_id: object) -> str:
    raw = str(task_id).strip()
    return raw if raw.startswith(_TASK_RESOURCE_PREFIX) else f"{_TASK_RESOURCE_PREFIX}{raw}"


def _task_uuid(value: str) -> UUID:
    raw = value.strip().removeprefix(_TASK_RESOURCE_PREFIX)
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ValueError("task_id must be a canonical Task URI or UUID") from exc


def _turn(ctx: McpToolContext) -> ConversationTurn:
    value = ctx.resource("conversation_turn")
    if not isinstance(value, ConversationTurn):
        raise RuntimeError("Conversation tool called outside a conversation round.")
    return value


async def _fresh(ctx: McpToolContext, *, before_effect: bool = True) -> ConversationTurn:
    turn = _turn(ctx)
    if not before_effect:
        if turn.should_interrupt is not None and await turn.should_interrupt():
            raise ConversationSuperseded
        return turn
    guard = turn.assert_fresh_before_effect
    if guard is not None and not await guard():
        raise ConversationSuperseded(
            "A newer user message arrived. Do not apply this action; let the next round decide."
        )
    return turn


async def _can_show_document(ctx: McpToolContext) -> bool:
    return await can_display_conversation_document(ctx.resource("conversation_turn"), ctx.agent_id)


def _display_document_id(value: str) -> UUID:
    from core.settings import settings

    reference = value.strip()
    if reference.startswith("document://"):
        return UUID(reference.removeprefix("document://"))
    parsed = urlsplit(reference)
    if parsed.scheme in {"http", "https"} or reference.startswith("/"):
        origin = urlsplit(settings.APP_HOST)
        if (parsed.netloc and (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc)
                or parsed.path != "/memory/documents" or parsed.fragment):
            raise ValueError("Expected a Galaris document URL, document:// URI or UUID.")
        identifiers = parse_qs(parsed.query).get("document_id", [])
        if len(identifiers) != 1:
            raise ValueError("The document URL must identify exactly one document.")
        reference = identifiers[0]
    return UUID(reference)


@mcp_tool(
    "conversation",
    conversation_policy="short",
    task_enabled=False,
    available_when=_can_show_document,
    description=(
        "Present a relevant existing document in the current internal Chat's document pane. "
        "Pass its document:// URI, UUID or Galaris document URL as document. "
        "Requires document read access; does not change sharing or content. "
        "Returns a display request receipt, not proof that the human viewed the document."
    ),
)
async def document_show(ctx: McpToolContext, document: str) -> dict[str, str]:
    turn = _turn(ctx)
    if turn.agent_id != ctx.agent_id:
        raise PermissionError("Document presentation requires the current internal Chat conversation.")
    identifier = _display_document_id(document)
    await display_conversation_document(turn, identifier)
    return {"status": "requested", "uri": f"document://{identifier}", "room_id": str(turn.room_id)}


def _action_key(kind: str, *values: str) -> str:
    digest = hashlib.sha256("\x1f".join(values).encode()).hexdigest()[:32]
    return f"{kind}:{digest}"


def _effect_scope(turn: ConversationTurn) -> str:
    if turn.origin == "voice":
        return f"conversation_round:{turn.round_id}"
    return f"text:{turn.round_id}"


def _connection_id(turn: ConversationTurn) -> int | None:
    raw = turn.messaging_context.get("connection_id")
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw))
    except ValueError:
        return None
    return value if value > 0 else None


def _conversation_task_data(turn: ConversationTurn) -> dict[str, Any]:
    """Build server-owned sender, room and triggering-message metadata."""

    latest: dict[str, Any] = {}
    if turn.messages:
        latest.update(
            TaskMessage.model_validate(turn.messages[-1]).model_dump(mode="json")
        )
        latest.update(current_message_data(turn.messages[-1], language=turn.language))
    room_id = str(turn.messaging_context.get("room_id") or "")
    sender_id = str(
        turn.messaging_context.get("participant_id")
        or latest.get("sender.id")
        or ""
    )
    sender_name = latest.get("sender.display_name")
    latest.update(
        {
            "language": turn.language,
            "connection_id": _connection_id(turn),
            "messenger_connection_id": _connection_id(turn),
            "platform": str(
                turn.messaging_context.get("platform") or "conversation"
            ),
            "group_id": room_id,
            "room_id": room_id,
            "room_locator": turn.messaging_context.get("room_locator"),
            "room_label": turn.messaging_context.get("room_label"),
            "message_type": str(
                turn.messaging_context.get("room_kind")
                or ("voice" if turn.origin == "voice" else "conversation")
            ),
            "user_id": sender_id,
            "sender.id": sender_id,
            "sender.user_id": sender_id,
            "sender.nickname": sender_name,
            "sender.display_name": sender_name,
            "sender.agent_id": latest.get("sender_agent_id"),
            "sender_is_ai": turn.sender_is_ai,
        }
    )
    return latest


async def _turn_lineage(turn: ConversationTurn) -> tuple[UUID | None, UUID | None]:
    """Resolve the latest durable Topic/contact attached to the launching turn."""
    from .facade import current_turn_scope

    return await current_turn_scope(turn)


def _round_id(value: str) -> UUID:
    try:
        return UUID(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid conversation round UUID: {value}") from exc


def _dispatch_forces(
    mode: Literal["auto", "exec", "plan", "briefing"],
) -> tuple[Literal["EXEC", "BRIEFING", "PLAN"] | None, Literal["standard", "high"] | None]:
    """Normalize explicit route controls without choosing ordinary Task effort."""

    route: Literal["EXEC", "BRIEFING", "PLAN"] | None = None
    if mode == "exec":
        route = "EXEC"
    elif mode == "briefing":
        route = "BRIEFING"
    elif mode == "plan":
        route = "PLAN"
    # PLAN is intrinsically high in the dispatcher, and briefing requires high by
    # pipeline contract. Ordinary EXEC admissions deliberately leave effort unset.
    return route, "high" if mode in {"plan", "briefing"} else None


async def _validate_dispatch_mode(
    turn: ConversationTurn,
    mode: Literal["auto", "exec", "plan", "briefing"],
) -> None:
    if mode not in {"plan", "briefing"}:
        return
    from app.agent import get_agent_record, resolve_pipeline_policy

    agent = await get_agent_record(turn.agent_id)
    if agent is None:
        raise LookupError(f"Agent {turn.agent_id} not found.")
    policy = resolve_pipeline_policy(getattr(agent, "agent_driver", None))
    if mode == "plan" and not policy.use_planner:
        raise ValueError("plan is unavailable for the selected Task harness")
    if mode == "briefing" and not policy.allows_briefing("high"):
        raise ValueError("briefing is unavailable for the selected Task harness")


def _requests_existing_attachment_delivery(objective: str) -> bool:
    """Reject Task admission for a turn that only asks to resend an existing file."""

    lowered = objective.casefold()
    delivery_marker = any(
        marker in lowered
        for marker in (
            "attach",
            "envoie",
            "joins",
            "joindre",
            "renvoie",
            "send",
            "transmet",
        )
    )
    file_marker = any(
        marker in lowered for marker in ("fichier", "file", "html", "pdf", "document")
    )
    existing_marker = any(
        marker in lowered
        for marker in (
            "déjà",
            "deja",
            "existant",
            "existing",
            "précédent",
            "precedent",
            "previous",
            "v1",
            "v2",
            "v3",
        )
    )
    regeneration_marker = any(
        marker in lowered
        for marker in ("génère", "genere", "generate", "recrée", "recree", "recreate")
    )
    return delivery_marker and file_marker and existing_marker and not regeneration_marker


@mcp_tool(
    "galaris_admin",
    name="conversation_round_get",
    description=(
        "Return the complete persisted dataset for one text conversation round by exact UUID: "
        "round and room state, agent identity, canonical messages, attempts, Tasks created or "
        "amended by the round, linked Processes, complete execution result, and every "
        "correlated LLM call."
    ),
)
async def conversation_round_get(
    ctx: McpToolContext,
    *,
    round_id: str,
) -> dict[str, Any]:
    """Inspect one text round through the optional administration package."""


    identifier = _round_id(round_id)
    await require_galaris_admin_access(ctx.agent_id)
    payload = await inspect_round(identifier)
    if payload is None:
        raise ValueError(f"Text conversation round not found: {identifier}")
    return payload


def _observe_task_definition(ctx: McpToolContext, task: Task) -> None:
    """Remember only definitions actually returned to this run, never model input."""

    observations = cast(dict[str, tuple[int, str]], ctx.resources.setdefault("conversation_task_definitions", {}))
    observations.pop(str(task.id), None)
    observations[str(task.id)] = (task.revision, amendment_basis(task))
    while len(observations) > 40:
        del observations[next(iter(observations))]


async def _task_dict(
    task: Task, *, progress: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.task.operational_state import inspect_operational_state
    from app.task.working_set import parse_working_set

    result = task.get_execution_result()
    working_set = parse_working_set(task)
    return {
        "id": str(task.id),
        "resource_uri": _task_resource_uri(task.id),
        "label": task.label,
        "status": task.status.value,
        "paused": task.paused,
        "revision": task.revision,
        "progress": progress,
        "last_error": str(task.last_error or "")[:1_000],
        "result": str(result.result or "")[:6_000] if result is not None else "",
        "updated_at": str(task.updated_at or ""),
        "objective": str(task.objective or "")[:2_000],
        "objective_truncated": len(str(task.objective or "")) > 2_000,
        "working_set": [
            {
                "resource_type": resource.resource_type,
                "role": resource.role,
                "reference": resource.reference,
                "label": resource.label,
                "revision": resource.revision,
                "state": resource.state,
            }
            for resource in working_set.active()[:25]
        ],
        **(await inspect_operational_state(task)),
    }


async def _task_summary_dict(task: Task) -> dict[str, Any]:
    """Return the bounded task-list projection; full results require status by UUID."""

    item = await _task_dict(task)
    item.pop("result", None)
    objective = str(item.get("objective") or "")
    item["objective"] = objective[:500]
    item["objective_truncated"] = len(str(task.objective or "")) > 500
    item["last_error"] = str(item.get("last_error") or "")[:500]
    item["working_set"] = list(item.get("working_set") or [])[:10]
    return item


async def _visible_task(ctx: McpToolContext, raw_id: str, *, lock: bool = False) -> Task:
    task_id = _task_uuid(raw_id)
    query = select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = await get_db().scalar(Task.histo_filter(query))
    if task is None or task.agent_id != ctx.agent_id:
        raise ValueError("Task not found for this agent.")
    return task


async def _existing_admitted_task(
    turn: ConversationTurn, action_key: str
) -> Task | None:
    """Return the Task already created for one idempotent conversation action."""

    if turn.origin == "text":
        existing = await get_db().scalar(
            select(ConversationTaskLink).where(
                ConversationTaskLink.round_id == turn.round_id,
                ConversationTaskLink.action_key == action_key,
            )
        )
        if existing is None:
            return None
        task = await get_db().get(Task, existing.task_id)
        if task is None:
            raise RuntimeError("The Task linked to this conversation no longer exists.")
        return task

    return await get_db().scalar(
        Task.histo_filter(
            select(Task).where(
                Task.agent_id == turn.agent_id,
                Task.data["conversation_effect_scope"].as_string()
                == _effect_scope(turn),
                Task.data["conversation_action_key"].as_string() == action_key,
            )
        )
    )


async def _creation_result(
    task: Task,
    *,
    created: bool,
    requested_disposition: str,
    fallback_reason: str | None,
) -> dict[str, Any]:
    payload = await _task_dict(task)
    return {
        "created": created,
        "amended": False,
        "action": "REPLACE" if requested_disposition == "REPLACE" else "CREATE_NEW",
        "requested_action": requested_disposition,
        "queued": payload.get("operational_state") == "QUEUED",
        **(
            {
                "admission_fallback": True,
                "admission_fallback_reason": fallback_reason,
            }
            if fallback_reason is not None
            else {}
        ),
        **payload,
    }


async def _create_conversation_task(
    turn: ConversationTurn,
    *,
    clean_label: str,
    clean_objective: str,
    normalized_effort: Literal["standard", "high"],
    action_key: str,
    requested_disposition: str,
    fallback_reason: str | None = None,
    forced_route: Literal["EXEC", "BRIEFING", "PLAN"] | None = None,
    forced_effort: Literal["standard", "high"] | None = None,
    auto_approve: bool = False,
    replace_target: tuple[UUID, int] | None = None,
) -> dict[str, Any]:
    """Create an idempotent root Task that the scheduler may safely keep queued."""

    existing = await _existing_admitted_task(turn, action_key)
    if existing is not None:
        return await _creation_result(
            existing,
            created=False,
            requested_disposition=requested_disposition,
            fallback_reason=fallback_reason,
        )

    preparation_started_at = datetime.now(timezone.utc)
    generated_label, generated_objective, generation_cost = await run_preparation(
        turn, lambda: generate_task_fields(
            turn, label_hint=clean_label, objective_hint=clean_objective,
        ),
    )
    preparation_finished_at = datetime.now(timezone.utc)
    guard = turn.assert_fresh_before_effect
    if guard is not None and not await guard():
        raise ConversationSuperseded(
            "A newer user message arrived while the Task objective was being built. "
            "Do not create this Task; let the next round decide."
        )

    topic_id, contact_memory_item_id = await _turn_lineage(turn)
    latest_message = _conversation_task_data(turn)
    current_message_id = str(
        latest_message.get("external_message_id")
        or latest_message.get("id")
        or latest_message.get("messenger_message_id")
        or ""
    )
    from app.task import task_service

    task = task_service.build(
        TaskCreate(
            label=generated_label,
            objective=compose_task_objective(turn, generated_objective),
            status=TaskStatus.CREATE,
            cost=generation_cost,
            effort=normalized_effort,
            forced_route=forced_route,
            forced_effort=forced_effort,
            reasoning_effort_override=turn.reasoning_effort_override,
            auto_approve=auto_approve,
            agent_id=turn.agent_id,
            messenger_connection_id=_connection_id(turn),
            message_platform=str(
                turn.messaging_context.get("platform") or "conversation"
            ),
            message_group_id=str(turn.messaging_context["room_id"]),
            data={
                "origin": (
                    "voice_conversation" if turn.origin == "voice" else "conversation"
                ),
                "conversation_effect_scope": _effect_scope(turn),
                "conversation_action_key": action_key,
                "conversation_requested_disposition": requested_disposition,
                OBJECTIVE_IS_STANDALONE_DATA_KEY: True,
                **(
                    {"conversation_admission_fallback": fallback_reason}
                    if fallback_reason is not None
                    else {}
                ),
                **latest_message,
                "message_id": current_message_id,
                "conversation_round_id": str(turn.round_id),
            },
            messages=None,
        )
    )
    task.topic_id = topic_id
    task.contact_memory_item_id = contact_memory_item_id
    round_ = await get_db().get(ConversationRound, turn.round_id)
    task.requester_user_id = round_.requester_user_id if round_ is not None else None
    # Observe enqueue immediately before persistence; do not use transaction-time
    # created_at or add a post-commit write that could race the scheduler.
    task.data = {
        **(task.data or {}),
        "_original_demand": source_request_html(turn),
        STARTUP_TIMING_DATA_KEY: TaskAdmissionTiming(
            preparation_started_at=preparation_started_at,
            preparation_finished_at=preparation_finished_at,
            enqueued_at=datetime.now(timezone.utc),
        ).model_dump(mode="json"),
    }
    created = True
    if replace_target is not None:
        from app.task import prepare_replacement
        prepared = await prepare_replacement(task, predecessor_id=replace_target[0],
            expected_revision=replace_target[1], action_key=action_key)
        created = prepared is task
        task = prepared
    get_db().add(task)
    await get_db().flush()
    if turn.origin == "text":
        get_db().add(
            ConversationTaskLink(
                round_id=turn.round_id,
                task_id=task.id,
                action_key=action_key,
                notification_task_attempt_count=0,
            )
        )
    await get_db().commit()
    await get_db().refresh(task)
    if replace_target is not None and created:
        predecessor = await get_db().get(Task, replace_target[0])
        if predecessor is not None:
            await task_service.publish_updated(predecessor)
    await task_service.publish_created(task)
    from app.task.runner import go_next

    # A wake-up only asks the scheduler to reconsider the durable queue. Its per-agent lease
    # rules leave this Task in CREATE while another Task for the same agent is running.
    go_next(task.id)
    return await _creation_result(
        task,
        created=created,
        requested_disposition=requested_disposition,
        fallback_reason=fallback_reason,
    )


@mcp_tool(
    "conversation",
    name="conversation_task_submit",
    conversation_policy="deferred",
    task_enabled=False,
    description=(
        "Admit substantial work after comparing it with the recent Tasks shown in context. "
        "Choose AMEND_CURRENT or AMEND_QUEUED only when the same primary artifact or target "
        "keeps substantially the same success criteria. Choose CREATE_NEW for a different "
        "target, repository, resource, deliverable, or independently verifiable outcome, even "
        "when it shares the same document or incident. Sharing a destination is not enough "
        "to amend: if either outcome can be completed without the other, create a new Task "
        "and leave existing work unchanged. Amendments require target_task_id and "
        "expected_revision. An unavailable amendment returns without creating another Task: re-read "
        "the target and reconsider the amendment; use CREATE_NEW for an independent outcome. "
        "Use REPLACE only for an explicit replacement: its successor waits for confirmed stop "
        "of target_task_id at expected_revision. Unresolved coordination returns a conflict. "
        "The supplied label and objective are framing hints: before creating "
        "a new Task, Galaris rebuilds both with the agent's standard model from the complete "
        "conversation context, memory, URLs, and resource references. Use mode=plan or "
        "mode=briefing only when explicitly requested; omitted controls remain the dispatcher's "
        "decision. This tool never chooses Task effort; the dispatcher owns that decision. "
        "Explicit deterministic chat directives such as @high use the separate direct-admission "
        "path. Ask the user when the relationship is ambiguous. Return immediately and never "
        "expose the canonical Task URI unless explicitly asked."
    ),
)
async def conversation_task_submit(
    ctx: McpToolContext,
    *,
    objective: str,
    label: str = "",
    mode: Literal["auto", "exec", "plan", "briefing"] = "auto",
    disposition: Literal["CREATE_NEW", "AMEND_CURRENT", "AMEND_QUEUED", "REPLACE"] = "CREATE_NEW",
    target_task_id: str | None = None,
    expected_revision: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    turn = await _fresh(ctx, before_effect=False)
    clean_objective = objective.strip()
    if not clean_objective:
        raise ValueError("objective is required")
    clean_label = " ".join(label.split())[:400] or clean_objective[:120]
    forced_route, forced_effort = _dispatch_forces(mode)
    normalized_effort: Literal["standard", "high"] = forced_effort or "standard"
    await _validate_dispatch_mode(turn, mode)

    existing_attachment_delivery = _requests_existing_attachment_delivery(turn.objective)
    if disposition in {"CREATE_NEW", "REPLACE"} and existing_attachment_delivery:
        raise ValueError(
            "This turn asks to deliver an existing attachment. Re-send that attachment "
            "directly; do not create a new Task or regenerate the artifact."
        )

    clean_target = str(target_task_id or "").strip()
    if disposition == "REPLACE":
        from app.task.task_service import TaskEditConflict, TaskRevisionConflict
        if not clean_target or expected_revision is None:
            return {"created": False, "action": "CONFLICT", "conflict": "incomplete_replacement_target"}
        unavailable = {"created": False, "action": "CONFLICT", "conflict": "replacement_unavailable",
                       "next_action": "Re-read the target and its dependencies before choosing an action."}
        try:
            target = await _visible_task(ctx, clean_target)
        except ValueError:
            return unavailable
        if (target.messenger_connection_id != _connection_id(turn)
            or str(target.message_group_id or "") != str(turn.messaging_context.get("room_id") or "")):
            return unavailable
        try:
            return await _create_conversation_task(
                turn, clean_label=clean_label, clean_objective=clean_objective,
                normalized_effort=normalized_effort,
                action_key=_action_key("replace", str(target.id), clean_objective),
                requested_disposition=disposition, forced_route=forced_route,
                forced_effort=forced_effort, replace_target=(target.id, expected_revision),
            )
        except (TaskEditConflict, TaskRevisionConflict):
            await get_db().rollback()
            return unavailable
    if disposition != "CREATE_NEW":
        requested_revision = expected_revision
        action_key = _action_key(
            "amend", disposition, clean_target, clean_objective, str(reason or "")
        )
        conflict_reason: str | None = None
        task: Task | None = None
        if not clean_target or requested_revision is None:
            conflict_reason = "incomplete_amendment_target"
        else:
            try:
                task = await _visible_task(ctx, clean_target)
            except ValueError:
                conflict_reason = "amendment_target_unavailable"

        if task is not None and requested_revision is not None:
            turn_connection_id = _connection_id(turn)
            turn_room_id = str(turn.messaging_context.get("room_id") or "")
            if task.parent_id is not None:
                conflict_reason = "amendment_target_is_not_root"
            elif (
                task.messenger_connection_id != turn_connection_id
                or str(task.message_group_id or "") != turn_room_id
            ):
                conflict_reason = "amendment_target_outside_conversation"
            else:
                from app.task.operational_state import inspect_operational_state

                operational = await inspect_operational_state(task)
                # A known definition may tolerate progress writes; unknown or changed
                # definitions remain strict. Only use the server's frozen projection.
                expected_basis = next((
                    str(item["amendment_basis"])
                    for item in turn.linked_work
                    if item.get("task_id") == str(task.id)
                    and item.get("revision") == requested_revision
                    and item.get("amendment_basis")
                ), None)
                observations = cast(dict[str, tuple[int, str]], ctx.resources.get("conversation_task_definitions", {}))
                observed = observations.get(str(task.id))
                if observed is not None and observed[0] == requested_revision:
                    expected_basis = observed[1]
                if not operational["amendable"] and task.revision == requested_revision:
                    conflict_reason = "amendment_no_longer_safe"
                else:
                    effective_disposition: Literal["AMEND_CURRENT", "AMEND_QUEUED"] = (
                        "AMEND_QUEUED"
                        if operational["operational_state"] == "QUEUED"
                        else "AMEND_CURRENT"
                    )
                    from app.task.amendment_service import amend_task
                    from app.task.task_service import TaskEditConflict, TaskRevisionConflict

                    try:
                        await _fresh(ctx)
                        amended = await amend_task(
                            task_id=task.id,
                            expected_revision=requested_revision,
                            instruction=clean_objective,
                            disposition=effective_disposition,
                            reason=reason,
                            source_kind=(
                                "conversation_round"
                                if turn.origin == "text"
                                else "voice_turn"
                            ),
                            source_id=_effect_scope(turn),
                            idempotency_key=action_key,
                            expected_basis=expected_basis,
                            normalize_disposition=True,
                        )
                    except TaskRevisionConflict:
                        if (
                            task.agent_id != ctx.agent_id
                            or task.messenger_connection_id != turn_connection_id
                            or str(task.message_group_id or "") != turn_room_id
                        ):
                            # The locked refresh may have discovered a scope transfer.
                            # Do not expose its new definition in the conflict response.
                            return {
                                "created": False, "amended": False, "action": "CONFLICT",
                                "requested_action": disposition,
                                "conflict": "amendment_target_unavailable",
                                "next_action": "Re-read the Tasks in this conversation before choosing an action.",
                            }
                        _observe_task_definition(ctx, task)
                        return {
                            "created": False,
                            "amended": False,
                            "action": "CONFLICT",
                            "requested_action": disposition,
                            "conflict": "amendment_revision_changed",
                            "next_action": "Re-read this Task and reassess the amendment. Use CREATE_NEW only for an independently requested outcome.",
                            **(await _task_dict(task)),
                        }
                    except TaskEditConflict:
                        conflict_reason = "amendment_no_longer_safe"
                        # Release the rejected target's lock before the next decision.
                        await get_db().commit()
                    else:
                        return {
                            "created": False,
                            "amended": amended.created,
                            "action": getattr(amended.amendment, "disposition", effective_disposition),
                            "requested_action": disposition,
                            "amendment_id": str(amended.amendment.id),
                            "interrupted": amended.interrupted,
                            **(await _task_dict(amended.task)),
                        }

        return {
            "created": False,
            "amended": False,
            "action": "CONFLICT",
            "requested_action": disposition,
            "conflict": conflict_reason or "amendment_unavailable",
            "next_action": "Re-read the Tasks in this conversation and reassess the requested action.",
        }

    # Preserve the historical creation identity so an in-flight retry remains idempotent
    # across deployments that introduced admission dispositions.
    action_key = (
        _action_key("submit", clean_label, clean_objective, normalized_effort)
        if mode == "auto"
        else _action_key("submit", clean_label, clean_objective, mode, "auto")
    )
    return await _create_conversation_task(
        turn,
        clean_label=clean_label,
        clean_objective=clean_objective,
        normalized_effort=normalized_effort,
        action_key=action_key,
        requested_disposition=disposition,
        forced_route=forced_route,
        forced_effort=forced_effort,
    )


async def admit_background_task(
    turn: ConversationTurn,
    objective: str,
    *,
    forced_route: Literal["EXEC", "BRIEFING", "PLAN"] | None = None,
    forced_effort: Literal["standard", "high"] | None = None,
    require_briefing: bool = False,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """Admit a direct Task while bypassing the conversation controller LLM."""


    ctx = McpToolContext(
        agent_id=turn.agent_id,
        runtime="internal",
        resources={"conversation_turn": turn},
    )
    fresh_turn = await _fresh(ctx, before_effect=False)
    clean_objective = objective.strip()
    if not clean_objective:
        raise ValueError("objective is required")
    if _requests_existing_attachment_delivery(fresh_turn.objective):
        raise ValueError(
            "This turn asks to deliver an existing attachment. Re-send that attachment "
            "directly; do not create a new Task or regenerate the artifact."
        )
    direct_mode: Literal["auto", "exec", "plan", "briefing"] = "auto"
    if require_briefing or forced_route == "BRIEFING":
        direct_mode = "briefing"
        forced_route = "BRIEFING"
        forced_effort = forced_effort or "high"
    elif forced_route == "PLAN":
        direct_mode = "plan"
    elif forced_route == "EXEC":
        direct_mode = "exec"
    await _validate_dispatch_mode(fresh_turn, direct_mode)
    normalized_effort = forced_effort or "standard"
    clean_label = clean_objective[:120]
    action_key = _action_key(
        "direct-submit",
        clean_label,
        clean_objective,
        forced_route or "",
        forced_effort or "",
        fresh_turn.reasoning_effort_override or "",
        str(auto_approve),
    )
    return await _create_conversation_task(
        fresh_turn,
        clean_label=clean_label,
        clean_objective=clean_objective,
        normalized_effort=normalized_effort,
        action_key=action_key,
        requested_disposition="CREATE_NEW",
        forced_route=forced_route,
        forced_effort=forced_effort,
        auto_approve=auto_approve,
    )


@mcp_tool(
    "conversation",
    name="conversation_task_list",
    conversation_policy="short",
    task_enabled=False,
    description=(
        "List compact summaries of recent root Tasks in the current conversation scope, "
        "including their canonical resource_uri, operational state and active resource "
        "references. Use conversation_task_status with an exact Task URI for a full bounded result."
    ),
)
async def conversation_task_list(
    ctx: McpToolContext, *, active_only: bool = False, limit: int = 10
) -> list[dict[str, Any]]:
    turn = _turn(ctx)
    connection_id = _connection_id(turn)
    room_id = str(turn.messaging_context.get("room_id") or "")
    safe_limit = min(max(limit, 1), 20)
    query = Task.histo_filter(
        select(Task)
        .where(
            Task.agent_id == ctx.agent_id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
            Task.messenger_connection_id == connection_id,
            Task.message_group_id == room_id,
        )
        .order_by(Task.updated_at.desc())
        .limit(safe_limit)
    )
    if active_only:
        query = query.where(Task.status.not_in((TaskStatus.SUCCESS, TaskStatus.ERROR)))
    items: list[dict[str, Any]] = []
    for task in (await get_db().scalars(query)).all():
        item = await _task_summary_dict(task)
        _observe_task_definition(ctx, task)
        item["conversation_scope_match"] = True
        items.append(item)
    return items


@mcp_tool(
    "conversation",
    name="conversation_task_status",
    conversation_policy="short",
    task_enabled=False,
    description=(
        "Read one Task's durable phase, plan progress, last error and bounded result. "
        "Use this before describing what the agent is currently doing."
    ),
)
async def conversation_task_status(ctx: McpToolContext, *, task_id: str) -> dict[str, Any]:
    task = await _visible_task(ctx, task_id)
    result = await _task_dict(task, progress=await get_plan_progress(task.id))
    _observe_task_definition(ctx, task)
    return result


@mcp_tool(
    "conversation",
    name="conversation_choice_resolve",
    conversation_policy="deferred",
    task_enabled=False,
    description=(
        "Resolve one pending interaction after interpreting the user's free-form reply. "
        "Use only a reference and option_id shown in Pending interactions. Never infer consent "
        "when the user's intent is ambiguous; ask a concise clarification instead. If the user "
        "redirects the Task that requested an approval, deny the obsolete approval before "
        "amending that same Task with conversation_task_submit."
    ),
)
async def conversation_choice_resolve(
    ctx: McpToolContext,
    *,
    reference: str,
    option_id: str,
) -> dict[str, Any]:
    """Apply a model-interpreted choice through the canonical interaction handler."""

    turn = await _fresh(ctx)
    if turn.origin != "text":
        raise ValueError("Pending messaging choices can only be resolved from a text round.")
    connection_id = _connection_id(turn)
    tool_id_raw = turn.messaging_context.get("tool_id")
    room_id = str(turn.messaging_context.get("room_id") or "").strip()
    user_id = str(turn.messaging_context.get("participant_id") or "").strip() or None
    if connection_id is None or not room_id:
        raise ValueError("The conversation has no exact messaging scope.")
    tool_id = int(str(tool_id_raw)) if tool_id_raw is not None else None
    response_text = ""
    if turn.messages:
        response_text = str(turn.messages[-1].get("text") or "")

    from app.messenger import resolve_pending_choice

    resolution, delivered = await resolve_pending_choice(
        reference=reference,
        option_id=option_id,
        response_text=response_text,
        agent_id=turn.agent_id,
        connection_id=connection_id,
        tool_id=tool_id,
        room_id=room_id,
        user_id=user_id,
    )
    return {
        "interaction_id": str(resolution.interaction_id),
        "reference": reference.strip().lstrip("#").upper(),
        "kind": resolution.kind,
        "option_id": resolution.option_id,
        "applied": delivered,
        "status": "RESOLVED" if delivered else "PROCESSING",
    }


async def _mutate_task(ctx: McpToolContext, task_id: str, command: str) -> dict[str, Any]:
    await _fresh(ctx)
    task = await _visible_task(ctx, task_id, lock=command == "stop")
    # A stop racing with completion or a manual stop acknowledges the durable
    # terminal state without overwriting its result, cause or revision. Keep the
    # scope/freshness checks and serialize this decision with other Task commands.
    if command == "stop" and task.status in {TaskStatus.SUCCESS, TaskStatus.ERROR}:
        return await _task_dict(task)
    from app.task import task_service
    from app.task.runner import go_next

    if command == "pause":
        changed = await task_service.pause_tree(task.id)
    elif command == "resume":
        changed = await task_service.resume_tree(task.id)
        go_next(task.id, fast=True)
    elif command == "retry":
        changed = await task_service.retry(task.id, task.revision)
        if changed is not None:
            go_next(task.id, fast=True)
    elif command == "stop":
        changed = await task_service.cancel(task.id, task.revision)
    else:
        raise AssertionError(command)
    if changed is None:
        raise ValueError("Task not found.")
    return await _task_dict(changed)


@mcp_tool(
    "conversation",
    name="conversation_task_pause",
    conversation_policy="deferred",
    task_enabled=False,
)
async def conversation_task_pause(ctx: McpToolContext, *, task_id: str) -> dict[str, Any]:
    """Pause a Task and its unfinished descendants."""
    return await _mutate_task(ctx, task_id, "pause")


@mcp_tool(
    "conversation",
    name="conversation_task_resume",
    conversation_policy="deferred",
    task_enabled=False,
)
async def conversation_task_resume(ctx: McpToolContext, *, task_id: str) -> dict[str, Any]:
    """Resume a user-paused Task and wake the work scheduler."""
    return await _mutate_task(ctx, task_id, "resume")


@mcp_tool(
    "conversation",
    name="conversation_task_retry",
    conversation_policy="deferred",
    task_enabled=False,
)
async def conversation_task_retry(ctx: McpToolContext, *, task_id: str) -> dict[str, Any]:
    """Retry a failed Task through its normal state machine."""
    return await _mutate_task(ctx, task_id, "retry")


@mcp_tool(
    "conversation",
    name="conversation_task_stop",
    conversation_policy="deferred",
    task_enabled=False,
)
async def conversation_task_stop(ctx: McpToolContext, *, task_id: str) -> dict[str, Any]:
    """Stop an unfinished Task through its normal cancellation transition."""
    return await _mutate_task(ctx, task_id, "stop")


@mcp_tool(
    "conversation",
    name="conversation_process_start",
    conversation_policy="deferred",
    task_enabled=False,
    description=(
        "Start an assigned business Process asynchronously, associate it with this conversation, "
        "and return its internal tracking ID for later Process tools. Never wait for completion "
        "or expose that ID to the user unless explicitly asked."
    ),
)
async def conversation_process_start(
    ctx: McpToolContext,
    *,
    workflow_id: str,
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    turn = await _fresh(ctx)
    clean_workflow = workflow_id.strip()
    if not clean_workflow:
        raise ValueError("workflow_id is required")
    action_key = _action_key("process", clean_workflow, repr(sorted((input or {}).items())))
    if turn.origin == "text":
        existing = await get_db().scalar(
            select(ConversationProcessLink).where(
                ConversationProcessLink.round_id == turn.round_id,
                ConversationProcessLink.action_key == action_key,
            )
        )
        if existing is not None:
            return {
                "created": False,
                "run_id": str(existing.process_run_id),
                "status": "already_linked",
            }

    from app.process import process_service

    response = await process_service.start_process(
        agent_id=turn.agent_id,
        workflow_id=clean_workflow,
        input_data=input or {},
        wait_for_completion=False,
        idempotency_key=f"conversation:{_effect_scope(turn)}:{action_key}"[:255],
        task_id=None,
        runtime="internal",
    )
    if turn.origin == "text":
        get_db().add(
            ConversationProcessLink(
                round_id=turn.round_id,
                process_run_id=response.run_id,
                action_key=action_key,
            )
        )
    await get_db().commit()
    return {"created": not response.deduplicated, **response.model_dump(mode="json")}


__all__ = [
    "admit_background_task",
    "conversation_choice_resolve",
    "conversation_task_list",
    "conversation_task_pause",
    "conversation_task_resume",
    "conversation_task_retry",
    "conversation_task_status",
    "conversation_task_stop",
    "conversation_task_submit",
    "conversation_process_start",
]
