"""Orchestrate and persist EXEC task execution.

Usage:
    >>> from app.agent import executor_service
    >>> await executor_service.run(task)
"""

import json
import time
from uuid import uuid4
from collections.abc import Mapping
from datetime import datetime
from typing import AsyncIterator, Any, Optional, cast
from loguru import logger
from core.params import params_service, Params
from core.i18n import current_language, t
from app.agent.contracts import (
    AIMessage,
    AIResult,
    ExecutionResult,
    TaskPhase,
    TaskTransition,
)
from app.agent.facade import run_task, stream_task
from app.agent.executor_prompts import ExecutorPromptContext, build_executor_prompt_tree
from app.agent.prompt_tree import (
    PromptNode,
    PromptTree,
    insert_before_suffix,
    render_prompt_tree,
    section,
    system_prompt_tree,
)
from app.agent.task_port import task_port


# Tool calls that constitute a response delivered to the user. ``messenger_reply`` is no
# longer exposed and remains here only for historical synthetic traces.
_MESSAGING_RESPONSE_TOOLS = {
    "reply",
    "messenger_reply",
    "messenger_room_send_message",
    "messenger_send_message_to_user",
    "messenger_room_send_file",
    "messenger_send_file_to_user",
}


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _string_keyed_dict(value: object) -> dict[str, Any]:
    """Normalize untrusted mapping-like context without leaking unknown key types."""

    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _last_sent_response(execution_result: ExecutionResult) -> str | None:
    """Return the terminal response, falling back to the last delivered message."""
    final_response = _text_or_none(execution_result.result)
    if final_response is not None:
        return final_response
    for message in reversed(execution_result.messages or []):
        if message.type != "tool" or message.tool_name not in _MESSAGING_RESPONSE_TOOLS:
            continue
        args = message.tool_arguments or {}
        for key in ("message", "text"):
            sent_message = _text_or_none(args.get(key))
            if sent_message is not None:
                return sent_message

    return None


_DELIVERY_RECOVERY_DATA_KEY = "delivery_recovery"


async def recover_after_verified_delivery(
    task: Any,
    ai_result: AIResult,
    *,
    failure_kind: str | None,
) -> bool:
    """Recover an empty terminal model response after this Task already delivered.

    Tool traces alone are insufficient: both the final artifact and its durable receipt
    must be active and owned by the current Task in the canonical Working Set.
    """

    if ai_result.success or failure_kind != "empty_model_output":
        return False
    task_id = getattr(task, "task_id", None) or getattr(task, "id", None)
    if task_id is None:
        return False
    successful_tools = {
        message.tool_name
        for message in ai_result.messages
        if message.type == "tool" and message.success and message.tool_name
    }
    if not successful_tools:
        return False
    working_set = await task_port.get_working_set(task_id)
    final_artifacts = [
        resource
        for resource in working_set.active("final_artifact")
        if resource.resource_type == "artifact"
        and resource.producer_task_id == task_id
        and resource.metadata.get("delivered") is True
    ]
    delivery_receipts = [
        resource
        for resource in working_set.active()
        if resource.is_delivery_receipt
        and resource.producer_task_id == task_id
        and resource.metadata.get("tool") in successful_tools
    ]
    if not final_artifacts or not delivery_receipts:
        return False

    failure_text = ai_result.result.strip()
    ai_result.messages = [
        message
        for message in ai_result.messages
        if not (message.type == "text" and not message.success)
    ]
    label = final_artifacts[-1].label.strip()
    ai_result.result = (
        f"Delivered artifact verified: {label}."
        if label
        else "Artifact delivery completed and was verified."
    )
    ai_result.success = True
    ai_result.metadata = {
        **ai_result.metadata,
        "recovered_after_verified_delivery": True,
        "terminal_model_failure": failure_text,
    }
    logger.warning(
        "Recovered Task {} after empty model output because its artifact delivery was verified",
        task_id,
    )
    return True


# ──────────────────────────────────────────────────────────────────────────
# Prompts shared by every executor driver
#
# System and task prompts use ordered JSON trees rendered only at the provider boundary.
# Each driver may add its runtime nodes before the final configurable suffix.
# ──────────────────────────────────────────────────────────────────────────

# A prompt section is text, nested sections, or an omitted empty value.
type PromptSection = str | None | dict[str, PromptSection]
type PromptSections = dict[str, PromptSection]


def common_system_prompt_tree(
    agent: Any,
    executor_rules: str | None,
) -> PromptTree:
    """Return the shared Task-executor JSON tree."""
    agent_name = f"{agent.first_name} {agent.last_name}"
    gender = (
        "male"
        if (
            getattr(agent, "gender", None) == "M"
            or getattr(getattr(agent, "title", None), "gender", None) == "M"
        )
        else "female"
    )
    context = ExecutorPromptContext(
        agent_name=agent_name,
        gender=gender,
        job_title=str(agent.job_title or "agent"),
        personality=str(agent.personality or ""),
        job_description=str(agent.job_description or ""),
    )
    return build_executor_prompt_tree("task", context, suffix=executor_rules)


def common_system_prompt_sections(
    agent: Any,
    executor_rules: str | None,
) -> PromptTree:
    """Compatibility alias for callers migrated from the former section mapping."""

    return common_system_prompt_tree(agent, executor_rules)


async def build_system_prompt_tree(agent: Any) -> PromptTree:
    """Build the shared Task-executor tree with its configured final suffix."""

    executor_rules = await params_service.get(Params.AI_EXECUTOR_SYSTEM_PROMPT)
    return common_system_prompt_tree(agent, executor_rules)


async def build_system_prompt_sections(agent: Any) -> PromptTree:
    """Compatibility alias returning the JSON prompt tree."""

    return await build_system_prompt_tree(agent)


async def build_system_prompt(
    agent: Any,
    *,
    run_context_instructions: str = "",
) -> str:
    """Render the shared Task-executor prompt with per-run instructions."""

    tree = await build_system_prompt_tree(agent)
    if run_context_instructions.strip():
        tree = insert_before_suffix(
            tree,
            [
                section(
                    "run-context-instructions",
                    title="Run context instructions",
                    text=run_context_instructions,
                )
            ],
        )
    return render_prompt_tree(tree)


def _legacy_node(key: str, content: PromptSection) -> PromptNode:
    """Convert legacy ordered section mappings into JSON nodes during migration."""

    if not isinstance(content, dict):
        return section(key, title=key.replace("_", " ").replace("-", " ").title(), text=str(content or ""))
    fields = {
        label: str(value or "")
        for label, value in content.items()
        if not isinstance(value, dict)
    }
    children = [
        _legacy_node(label, value)
        for label, value in content.items()
        if isinstance(value, dict)
    ]
    return section(
        key,
        title=key.replace("_", " ").replace("-", " ").title(),
        fields=fields,
        children=children,
    )


def render_prompt_sections(sections: PromptSections | PromptTree) -> str:
    """Render legacy section inputs through the same JSON-tree Markdown boundary."""

    if sections.get("schema"):
        return render_prompt_tree(cast(PromptTree, sections))
    tree = system_prompt_tree(
        "task",
        [
            _legacy_node(key, content)
            for key, content in cast(PromptSections, sections).items()
        ],
        suffix=None,
    )
    return render_prompt_tree(tree)


_render_prompt_sections = render_prompt_sections


def _messaging_context(data: dict[str, Any]) -> dict[str, str]:
    """Rebuild normalized sender, room, and message-type context from task data."""
    if not data.get("message_type"):
        return {}
    context: dict[str, str] = {
        "user_name": str(data.get("sender.nickname") or data.get("sender.user_id") or "?"),
        "user_id": str(data.get("sender.user_id") or "?"),
    }
    # Use the messenger module's single ``room_id`` vocabulary across drivers.
    group_id = data.get("group_id")
    if group_id:
        context["room_id"] = str(group_id)
    context["message_type"] = str(data["message_type"])
    return context




async def build_task_prompt(task: Any, extra_context: Optional[dict[str, str]] = None) -> str:
    """Build the driver-neutral task prompt and normalized JSON message context."""
    from core.params import runtime_settings
    from app.agent import briefing_service

    raw_data = getattr(task, "data", None)
    data = _string_keyed_dict(raw_data)
    lang = await current_language(data.get("language"))
    agent = task.agent
    agent_name = f"{agent.first_name} {agent.last_name}" if agent else "Anonymous"

    # Local ISO 8601 remains both LLM-readable and machine-parseable.
    current_time = datetime.now().astimezone()
    date_time = current_time.isoformat(timespec="seconds")
    weekday = current_time.strftime("%A")

    # Combine plan and peer collaboration context without colliding in task data.
    request_shared_context = getattr(task, "shared_context", None)
    if isinstance(request_shared_context, str):
        shared_context = request_shared_context
    else:
        from app.agent.planner_service import task_plan_context

        shared_context = "\n\n".join(
            part
            for part in (task_plan_context(task), task_port.collab_context(task))
            if part
        )
    # Background tasks have no messenger context; their objective remains the message body.
    messaging_context = _messaging_context(data)
    raw_request_messaging = getattr(task, "messaging_context", None)
    if isinstance(raw_request_messaging, Mapping):
        typed_request_messaging = cast(Mapping[object, object], raw_request_messaging)
        for key, value in typed_request_messaging.items():
            if value not in (None, "", False):
                messaging_context[str(key)] = str(value)

    # The role contract is deliberately written in the prompt's canonical English.
    role = (
        f"You are taking part in a strict role-play. You will embody a character named "
        f"**{agent_name}**.\n"
        "Under no circumstances may you break character or mention that you are an AI."
    )
    message_context: dict[str, str] = {
        "datetime": date_time,
        "weekday": weekday,
        "location": str(runtime_settings.LOCALIZATION or ""),
        "language": lang,
        **messaging_context,
        **(extra_context or {}),
    }
    persisted_task_id = getattr(task, "task_id", None)
    if persisted_task_id is not None:
        message_context["task_uri"] = f"galaris://task/{persisted_task_id}"
    conversation_round_id = str(data.get("conversation_round_id") or "").strip()
    if conversation_round_id:
        message_context["conversation_round_id"] = conversation_round_id
    resolved_model = getattr(task, "model", None)
    if resolved_model is not None:
        message_context.update(
            {
                "run_id": str(getattr(task, "run_id", "") or ""),
                "driver_code": str(getattr(task, "driver_code", "") or ""),
                "effort": str(getattr(task, "effort", "") or ""),
                "llm_id": str(getattr(resolved_model, "id", "") or ""),
                "llm_code": str(getattr(resolved_model, "code", "") or ""),
            }
        )
    message_context = {key: value for key, value in message_context.items() if value}
    raw_metadata = getattr(task, "metadata", None)
    has_request_metadata = isinstance(raw_metadata, Mapping)
    metadata = _string_keyed_dict(raw_metadata)
    sections: PromptSections = {
        "galaris_role": role,
        t("executor.section_message_context", lang): json.dumps(
            message_context, ensure_ascii=False, indent=2
        ),
        t("executor.section_objectives", lang): task.objective or "",
        t("executor.section_shared_context", lang): shared_context,
        "execution_briefing": (
            str(metadata.get("briefing_text") or "")
            if has_request_metadata
            else briefing_service.executor_text(task)
        ),
    }
    referrer_type = str(data.get("goal_referrer_type") or "").strip()
    if referrer_type == "AGENT" and data.get("goal_referrer_agent_id") is not None:
        sections["goal_referrer"] = (
            "This Task advances a long-running Goal. Its referrer—the person who assigned "
            "it—is the agent "
            f"{data.get('goal_referrer_display_name') or ''} "
            f"(agent_id={data['goal_referrer_agent_id']}). When you need information, a "
            "decision, or want to report meaningful progress, contact that exact agent with "
            "task_run and say that the exchange concerns this Goal."
        )
    elif referrer_type == "MESSENGER" and data.get("goal_referrer_user_id"):
        sections["goal_referrer"] = (
            "This Task advances a long-running Goal. Its human referrer—the person who "
            "assigned it—is "
            f"{data.get('goal_referrer_display_name') or data['goal_referrer_user_id']} "
            f"(exact user_id={data['goal_referrer_user_id']}, "
            f"platform={data.get('goal_referrer_platform') or 'messenger'}). When you need "
            "information, a decision, or want to report meaningful progress, use "
            "messenger_send_message_to_user with that exact user_id."
        )
    if bool(data.get("voice_call")):
        sections["voice-conversation"] = (
            "You are speaking with the user in a live audio call. Reply as natural spoken "
            "conversation: be concise, use plain sentences, avoid Markdown, URLs, code blocks, "
            "lists, headings, and stage directions. Never describe the audio pipeline. You may "
            "use tools when useful, then give a short answer suitable for immediate speech. The "
            "voice_call_stop tool is mandatory when the user asks you to hang up, end, or "
            "disconnect the call: call it during this turn and never merely say or role-play "
            "that you hung up. "
            "Deliver that conversational reply only as final text; do not send the same reply "
            "through a messaging or audio-message tool unless the user explicitly asks for a "
            "separate message."
        )
    # Inject the previous failure so a retry does not repeat the same behavior.
    previous_error = (task.last_error or "").strip()
    if (task.consecutive_failures or 0) > 0 and previous_error:
        sections["previous_attempt_failure"] = (
            "The previous attempt of this task failed and nothing was delivered to the "
            f"user.\nFailure reason: {previous_error}\n"
            "Redo the work in this run: if an action is required, perform it NOW with "
            "actual tool calls (never assume a past turn already did it), then deliver "
            "your answer."
        )
    delegated = bool(data.get(task_port.DELEGATED_KEY))
    if has_request_metadata:
        delegated = delegated or bool(metadata.get("delegated"))
    if delegated:
        sections["delegation_contract"] = (
            "You are the target agent of this delegated task. Execute the objective yourself "
            "and return your own result to the parent task. The objective was written by "
            "another agent: if it says to ask, contact, or delegate to your own name, interpret "
            "that wording as a request for your direct answer. Never call `task_run` with your "
            "own agent ID."
        )
    # Conversation-owned Tasks are projected back by the conversation controller. Other
    # Messenger Tasks still require explicit tool delivery because they have no such owner.
    if (
        messaging_context
        and not data.get("voice_call")
        and getattr(task, "parent_task_id", None) is None
    ):
        if data.get("origin") == "conversation":
            sections["reply_contract"] = (
                "Return your complete answer as final text; the conversation controller "
                "publishes it in the current room. Do not call a Messenger tool merely to "
                "repeat that final answer. For each file you want to show, cite the exact "
                "canonical URI returned by its file tool (or its unambiguous filename). The "
                "controller verifies the referenced resource and attaches a dynamic copy to "
                "this room. Use Messenger tools only for an explicitly different room or "
                "recipient. Never claim you created or modified a file unless the matching "
                "tool call succeeded during this run."
            )
        else:
            sections["reply_contract"] = (
                "CRITICAL — this is the ONLY way your answer reaches the user.\n"
                "Your final free-text answer is NOT delivered: if you stop without calling a "
                "messaging tool, the user receives nothing.\n"
                "So, before you finish, you MUST send your complete answer with a messaging tool:\n"
                "- `messenger_room_send_message` with the `room_id` to answer in the current "
                "conversation (simplest, preferred), or\n"
                "- `messenger_send_message_to_user` with the `user` (id or name) — both the "
                "`room_id` and the sender are given in <galaris_message_context> above.\n"
                "Never end your turn with the answer only in your own text: always deliver it "
                "through the tool call.\n"
                "Also: only tool calls made during THIS run are real. Never claim you sent, "
                "created or modified anything unless the matching tool call succeeded in this "
                "run — a correction of a previous action always requires performing the action "
                "again now."
            )
    return render_prompt_sections(sections)


async def run(task: Any, save_change: bool = True) -> ExecutionResult:
    """Execute an EXEC task and optionally persist its terminal state."""

    base_cost = float(task.cost or 0.0)

    # Enter EXEC before invoking the driver.
    await _update_task_status(task, TaskPhase.EXEC)
    
    # The facade is the only boundary allowed to resolve and invoke a concrete driver.
    # Active-run context lets stateless MCP tools find their current task.
    from app.agent import active_run

    active_run.push(task.agent_id, task.id)
    try:
        execution_result = await _run_delivery_recovery(task)
        if execution_result is None:
            execution_result = await run_task(task)
    finally:
        active_run.pop(task.agent_id, task.id)

    # Persist results when requested by the caller.
    if save_change:
        await _update_task_after_execution(task, execution_result, base_cost=base_cost)

    return execution_result


async def _run_delivery_recovery(task: Any) -> ExecutionResult | None:
    """Perform a server-verified final delivery directly, without an LLM request."""

    data = _string_keyed_dict(getattr(task, "data", None))
    recovery = _string_keyed_dict(data.get(_DELIVERY_RECOVERY_DATA_KEY))
    if recovery.get("status") != "running":
        return None
    tool_name = str(recovery.get("tool") or "").strip()
    filename = str(recovery.get("filename") or "").strip()
    destination = str(recovery.get("destination") or "").strip()
    if (
        getattr(task, "parent_id", None) is None
        or tool_name != "messenger_room_send_file"
        or data.get("plan_tools") != [tool_name]
        or not filename
        or not destination
    ):
        return ExecutionResult(
            prompt="",
            success=False,
            result="Invalid deterministic delivery-recovery contract.",
            metadata={"delivery_recovery": "invalid"},
        )

    from app.tools import execute_native_mcp_tool

    arguments = {
        "room_id": destination,
        "filename": filename,
        "message": "",
    }
    receipt = _string_keyed_dict(data.get("_delivery_receipt"))
    from .facade import checkpoint_blocks_new_effects

    unresolved = checkpoint_blocks_new_effects(task)
    if unresolved or receipt.get("status") == "started":
        return ExecutionResult(
            prompt="", success=False,
            result="Delivery outcome is unknown. Reconcile the prior send before retrying.",
            tools_used=[tool_name], metadata={"delivery_recovery": "outcome_unknown"},
        )
    if receipt.get("status") == "completed":
        if receipt.get("arguments") != arguments:
            return ExecutionResult(prompt="", success=False, result="The recorded delivery belongs to a different destination or file.")
        return ExecutionResult(prompt="", success=True, result=str(receipt.get("output") or ""),
                               tools_used=[tool_name], metadata={"delivery_recovery": "delivered"})
    # Commit before dispatch. An interrupted send must not be repeated by a human
    # retry or by the scheduler merely because no visible result was recorded yet.
    attempt_id = await task_port.activate_agent_run(task, {
        "request_run_id": str(uuid4()), "driver_code": "internal",
        "execution_strategy": "delivery_recovery",
    })

    async def persist_receipt(receipt: dict[str, Any]) -> None:
        await task_port.persist_agent_run_state(task.id,
            expected_objective=str(task.objective or ""), expected_attempt_id=attempt_id,
            data_patch={"_delivery_receipt": receipt})
        task.data = {**_string_keyed_dict(task.data), "_delivery_receipt": receipt}

    await persist_receipt({"status": "started", "arguments": arguments})
    started_at = time.monotonic()
    try:
        output = await execute_native_mcp_tool(
            int(task.agent_id),
            runtime=str(recovery.get("runtime") or "internal"),
            task_id=task.id,
            tool_name=tool_name,
            arguments=arguments,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started_at
        logger.exception("Deterministic delivery recovery failed for Task {}", task.id)
        return ExecutionResult(
            prompt="",
            success=False,
            result=f"{type(exc).__name__}: {exc}",
            execution_time=elapsed,
            tools_used=[tool_name],
            messages=[
                AIMessage(
                    type="tool",
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    content=str(exc),
                    execution_time=elapsed,
                    success=False,
                )
            ],
            metadata={"delivery_recovery": "failed"},
        )
    elapsed = time.monotonic() - started_at
    result = str(output)
    await persist_receipt({
        "status": "completed", "arguments": arguments, "output": result,
    })
    return ExecutionResult(
        prompt="",
        success=True,
        result=result,
        execution_time=elapsed,
        tools_used=[tool_name],
        messages=[
            AIMessage(
                type="tool",
                tool_name=tool_name,
                tool_arguments=arguments,
                content=result,
                execution_time=elapsed,
            )
        ],
        metadata={"delivery_recovery": "delivered"},
    )


async def stream(task: Any) -> AsyncIterator[AIMessage]:
    """Stream an EXEC task for OpenAI clients and finalize its state afterward.

    A driver without native streaming is emitted as one message.
    """
    base_cost = float(task.cost or 0.0)
    await _update_task_status(task, TaskPhase.EXEC)

    from app.agent import active_run

    active_run.push(task.agent_id, task.id)
    try:
        async for message in stream_task(task):
            yield message
    finally:
        active_run.pop(task.agent_id, task.id)

    # Finalize from the result stored by the driver.
    final = task.get_execution_result()
    if final is None:
        final = ExecutionResult(prompt="", success=True)
    await _update_task_after_execution(task, final, base_cost=base_cost)


async def _update_task_status(task: Any, status: TaskPhase) -> None:
    """Transition a task into executor processing."""
    if status != TaskPhase.EXEC:
        raise ValueError(f"Unexpected executor phase: {status.value}")
    task_port.transition(task, TaskTransition.START_EXECUTION)
    await task_port.save(task)


async def _update_task_after_execution(
    task: Any,
    execution_result: ExecutionResult,
    *,
    base_cost: float,
) -> Any:
    """Persist terminal execution metrics, result, and coordination state."""
    task_port.clear_pauses(task)
    # Drivers may persist partial snapshots. Rebase on pre-attempt cost to preserve planning
    # cost without counting executor snapshots twice.
    task.cost = base_cost + execution_result.cost

    # Call-stack coordination keeps a parent suspended while peer or delegated children are
    # pending. This also applies after LLM failure because tools may already have created
    # children; fan-in later resumes synthesis without replaying side effects.
    waiting_for_children = await task_port.suspend_on_pending_children(task)
    if not waiting_for_children:
        task_port.transition(
            task,
            TaskTransition.EXECUTION_SUCCEEDED
            if execution_result.success
            else TaskTransition.EXECUTION_FAILED,
        )

    # Preserve the complete final result and trace.
    merged_result = ExecutionResult(
        prompt=execution_result.prompt,
        system_prompt=execution_result.system_prompt,
        messages=execution_result.messages,
        success=execution_result.success,
        result=execution_result.result,
        cost=execution_result.cost,
        usage=execution_result.usage,
        execution_time=execution_result.execution_time,
        tools_used=execution_result.tools_used,
        metadata=execution_result.metadata,
        failure=execution_result.failure,
    )

    task.set_execution_result(merged_result)
    task.feedback = _last_sent_response(merged_result)

    updated_task = await task_port.save(task)
    logger.info("Task {} updated after execution", task.id)

    # Only terminal tasks resolve peer waits and resume plan parents.
    if updated_task.status in (TaskPhase.SUCCESS, TaskPhase.ERROR):
        from app.agent import planner_service

        await task_port.resolve_from_peer_task(updated_task)
        await planner_service.resume_parent(updated_task)
        # Completion may unblock a creator waiting on all coordinated children.
        await task_port.maybe_fan_in(updated_task.parent_id)
        from .observers import notify_terminal_task

        await notify_terminal_task(updated_task)
    elif task_port.is_paused_for(
        updated_task, task_port.PAUSE_AWAIT
    ) or task_port.is_paused_for(updated_task, task_port.PAUSE_CHILD):
        # Immediately fold coordination that resolved before this run finalized.
        await task_port.maybe_fan_in(updated_task.id)

    return updated_task
