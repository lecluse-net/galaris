"""Shared AI preparation performed before eligible high-effort executions."""

from __future__ import annotations

from app.llm import LLMCallPurpose, model_usages

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from loguru import logger
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from app.llm import LLM
from app.llm.facade import record_structured_inferences, register_inference_output
from app.llm.structured_service import (
    StructuredOutputRetry as ModelRetry,
    run_structured,
)
from core.i18n import default_language, is_supported, t
from core.params import Params, params_service, prompt_default

from .contracts import (
    AgentTask,
    BriefingChoice,
    BriefingResult,
    TaskPhase,
    TaskTransition,
)
from .model_resolver import has_agent_profile_model, resolve_agent_profile_model
from .task_port import task_port


def _task_language(task: AgentTask) -> str:
    data = task.data if isinstance(task.data, dict) else {}
    language = str(data.get("language") or "").strip().lower()
    return language if is_supported(language) else default_language()


class _BriefingDraft(BaseModel):
    result: str = Field(min_length=1, max_length=8000)
    # An inline dictionary avoids nested JSON Schema references unsupported by some
    # OpenAI-compatible providers. Every entry is validated as BriefingChoice afterward.
    choices: list[dict[str, str | float | None]] = Field(default_factory=lambda: [], max_length=12)


class _ToolResource(BaseModel):
    identifier: str
    label: str
    description: str = ""


class _ProcessResource(BaseModel):
    identifier: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class _ResourceCatalog:
    tools: tuple[_ToolResource, ...]
    processes: tuple[_ProcessResource, ...]

    def prompt_value(self) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for item in self.tools:
            grouped.setdefault(item.label, []).append(
                {
                    "identifier": item.identifier,
                    "description": item.description,
                }
            )
        return {
            "tool_groups": [
                {"label": label, "functions": functions} for label, functions in grouped.items()
            ],
            "processes": [item.model_dump() for item in self.processes],
        }


def briefing_system_prompt() -> str:
    """Return the packaged contract used to initialize Lab evaluations."""
    value = prompt_default(Params.AI_BRIEFING_SYSTEM_PROMPT)
    if not value:
        raise RuntimeError("Missing built-in briefing system prompt.")
    return value


async def effective_briefing_system_prompt() -> str:
    """Resolve the editable production prompt, retaining its packaged fallback."""
    value = str(await params_service.get_or_default(Params.AI_BRIEFING_SYSTEM_PROMPT) or "").strip()
    return value or briefing_system_prompt()


async def is_enabled(task: AgentTask | None = None) -> bool:
    """Return whether the task's agent or the global briefing model is configured."""

    agent = task.agent if task is not None else None
    return await has_agent_profile_model(agent, model_usages.BRIEFING)


def _compact_description(value: Any, max_chars: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


async def _resource_catalog(task: AgentTask) -> _ResourceCatalog:
    """List resources actually available to the agent without exposing secrets."""
    if task.agent_id is None:
        return _ResourceCatalog((), ())

    # Lazy imports avoid module initialization cycles.
    from app.process import process_service
    from app.tools import list_agent_mcp_tools

    groups = await list_agent_mcp_tools(task.agent_id)
    tools: list[_ToolResource] = []
    for group in groups:
        group_label = str(group.get("tool_label") or group.get("tool_code") or "")
        raw_functions = group.get("mcp_tools")
        if not isinstance(raw_functions, list):
            continue
        for raw_function in cast(list[Any], raw_functions):
            if not isinstance(raw_function, dict):
                continue
            function = cast(dict[str, Any], raw_function)
            if function.get("enabled") is not True:
                continue
            identifier = str(function.get("name") or "").strip()
            if not identifier:
                continue
            tools.append(
                _ToolResource(
                    identifier=identifier,
                    label=group_label,
                    description=_compact_description(function.get("description")),
                )
            )

    raw_processes = await process_service.list_for_agent(task.agent_id)
    processes = tuple(
        _ProcessResource(
            identifier=str(process.get("workflow_id") or ""),
            label=str(process.get("label") or process.get("workflow_id") or ""),
            description=_compact_description(process.get("description")),
        )
        for process in raw_processes
        if process.get("workflow_id")
    )
    ordered_tools = tuple(sorted(tools, key=lambda item: item.identifier))
    return _ResourceCatalog(
        tools=ordered_tools,
        processes=processes,
    )


def _message_value(value: Any) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        raw = cast(dict[str, Any], dumped) if isinstance(dumped, dict) else {}
    elif isinstance(value, dict):
        raw = cast(dict[str, Any], value)
    else:
        return {"text": _compact_description(value, 800)}
    sender_raw = raw.get("sender")
    sender = cast(dict[str, Any], sender_raw) if isinstance(sender_raw, dict) else {}
    return {
        "id": raw.get("id"),
        "time": raw.get("time"),
        "sender": sender.get("display_name") or sender.get("id"),
        "text": _compact_description(raw.get("text"), 800),
    }


def _task_data_context(task: AgentTask) -> dict[str, Any]:
    data = task.data if isinstance(task.data, dict) else {}
    kept_keys = (
        "language",
        "message_type",
        "room_id",
        "sender.user_id",
        "sender.nickname",
        "attachments",
        "recent_attachments",
        "recent_images",
    )
    return {key: data[key] for key in kept_keys if data.get(key) not in (None, "", [])}


def _briefing_prompt(task: AgentTask, catalog: _ResourceCatalog) -> str:
    agent = task.agent
    task_payload = {
        "uri": f"galaris://task/{task.id}",
        "label": task.label,
        "objective": task.objective,
        "effort": task.effort,
        "context": _task_data_context(task),
        "recent_messages": [_message_value(item) for item in list(task.messages or [])[-6:]],
    }
    executor_payload = {
        "id": task.agent_id,
        "name": (f"{agent.first_name} {agent.last_name}" if agent is not None else ""),
        "job_title": agent.job_title if agent is not None else None,
        "job_description": agent.job_description if agent is not None else None,
    }

    return render_briefing_input(task_payload, executor_payload, catalog.prompt_value())


def render_briefing_input(
    task_payload: dict[str, Any], executor_payload: dict[str, Any], resources: dict[str, Any]
) -> str:
    """Shared evidence rendering for production and isolated evaluations."""

    def section(title: str, value: Any) -> str:
        # Indentation remains readable even when user data contains code delimiters.
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        indented = "\n".join(f"    {line}" for line in rendered.splitlines())
        return f"## {title}\n\n{indented}"

    return "\n\n".join(
        (
            "# Execution briefing input",
            section("Task", task_payload),
            section("Executor", executor_payload),
            section("Available resources", resources),
        )
    )


def _validate_choices(catalog: _ResourceCatalog, draft: _BriefingDraft) -> list[BriefingChoice]:
    tool_ids = {item.identifier for item in catalog.tools}
    process_ids = {item.identifier for item in catalog.processes}
    try:
        choices = [BriefingChoice.model_validate(item) for item in draft.choices]
    except ValidationError as exc:
        raise ModelRetry(f"Invalid resource choice: {exc}") from exc
    invalid: list[str] = []
    for choice in choices:
        if choice.kind == "tool" and choice.identifier not in tool_ids:
            invalid.append(f"tool:{choice.identifier}")
        elif choice.kind == "process" and choice.identifier not in process_ids:
            invalid.append(f"process:{choice.identifier}")
    if invalid:
        raise ModelRetry(
            "Unknown or unavailable resources: "
            + ", ".join(invalid)
            + ". Use only AVAILABLE_RESOURCES identifiers."
        )
    if draft.result.strip().upper() == "NO ISSUES":
        raise ModelRetry(
            'A HIGH-effort task requires an actionable briefing; "NO ISSUES" is forbidden. '
            "Explain the execution approach and select every required resource."
        )
    if not choices:
        raise ModelRetry(
            "A HIGH-effort briefing cannot leave choices empty. Select the required "
            'tool/process resources, or add an explicit kind="other" check '
            "when no resource is relevant."
        )
    return choices


def _briefing_validator(context: dict[str, JsonValue]) -> Callable[[_BriefingDraft], _BriefingDraft]:
    catalog = TypeAdapter(_ResourceCatalog).validate_python(context)

    def validate(draft: _BriefingDraft) -> _BriefingDraft:
        _validate_choices(catalog, draft)
        return draft

    return validate


def register_briefing_output_contracts() -> None:
    register_inference_output(
        "galaris.briefing/v1", _BriefingDraft, validator_factory=_briefing_validator
    )


async def generate(
    task: AgentTask,
    *,
    system_prompt_override: str | None = None,
    llm_override: LLM | None = None,
    record_task_trace: bool = True,
) -> BriefingResult:
    """Compute a structured briefing without mutating the task, including in the Lab."""
    started_at = time.perf_counter()
    system_prompt = system_prompt_override or await effective_briefing_system_prompt()
    human_prompt = ""
    try:
        catalog = await _resource_catalog(task)
        human_prompt = _briefing_prompt(task, catalog)
        llm = llm_override or await resolve_agent_profile_model(task.agent, model_usages.BRIEFING)
        if llm is None:
            raise ValueError(t("agent_api.errors.briefing_model_missing", _task_language(task)))

        register_briefing_output_contracts()
        with record_structured_inferences():
            inference = await run_structured(
                llm=llm,
                output_type=_BriefingDraft,
                prompt=human_prompt,
                system_prompt=system_prompt,
                task_id=task.id if record_task_trace else None,
                agent_id=task.agent_id,
                temperature=0.0,
                request_limit=3,
                output_context=TypeAdapter(_ResourceCatalog).dump_python(catalog, mode="json"),
                purpose=(
                    LLMCallPurpose.AGENT_BRIEFING
                    if record_task_trace
                    else LLMCallPurpose.LAB_MECHANISM_RUN
                ),
                model_field=model_usages.BRIEFING,
                reasoning_effort_override=getattr(task, "reasoning_effort_override", None),
            )
        draft = inference.output
        choices = _validate_choices(catalog, draft)
        return BriefingResult(
            prompt=human_prompt,
            system_prompt=system_prompt,
            result=draft.result.strip(),
            choices=choices,
            execution_time=time.perf_counter() - started_at,
            cost=inference.cost,
            success=True,
        )
    except Exception:
        logger.exception("AI briefing failed for task {}", task.id)
        return BriefingResult(
            prompt=human_prompt,
            system_prompt=system_prompt,
            result=t("agent_api.errors.briefing_unavailable", _task_language(task)),
            execution_time=time.perf_counter() - started_at,
            success=False,
        )


async def run(task: AgentTask) -> BriefingResult:
    """Generate and persist a briefing, then let the task proceed to execution."""
    if task.status != TaskPhase.BRIEFING:
        raise ValueError(f"Unexpected briefing phase: {task.status.value}")

    from .workflow import task_uses_briefing

    agent = getattr(task, "agent", None)
    driver_code = getattr(agent, "agent_driver", None)
    if not task_uses_briefing(task):
        task_port.transition(task, TaskTransition.BRIEFING_SUCCEEDED)
        await task_port.save(task)
        logger.info(
            "Briefing skipped by driver policy for task {} (driver={})",
            task.id,
            driver_code,
        )
        return BriefingResult(result="", success=True)

    if not await is_enabled(task):
        task_port.transition(task, TaskTransition.BRIEFING_SUCCEEDED)
        await task_port.save(task)
        logger.info("Briefing disabled for task {} because no model is configured", task.id)
        return BriefingResult(result="", success=True)

    result = await generate(task)
    task.set_briefing_result(result)
    task.cost += result.cost
    task_port.transition(task, TaskTransition.BRIEFING_SUCCEEDED)
    await task_port.save(task)
    logger.info(
        "Briefing completed for task {} (success={}, choices={})",
        task.id,
        result.success,
        len(result.choices),
    )
    return result


def executor_text(task: AgentTask) -> str:
    """Return validated briefing text and resources for the shared executor prompt."""
    result = task.get_briefing_result()
    if result is None or not result.success:
        return ""
    text = result.result.strip()
    sections = [
        "CRITICAL — this briefing is the execution contract for this run. Follow its objective, "
        "constraints, approach, and completion checks; do not silently omit or weaken any of "
        "them. Before finishing, compare the work actually performed and the tool results with "
        "every completion check. If a required action or check could not be completed, report "
        "that limitation explicitly instead of claiming success.",
        text,
    ]
    if result.choices:
        resources = "\n".join(
            f"- [{choice.kind}] {choice.identifier}"
            + (f": {choice.reason}" if choice.reason else "")
            for choice in result.choices
        )
        sections.append(
            "Selected resources and checks are expected parts of the execution. Use each one "
            "unless its purpose is already satisfied by equivalent evidence. If you replace a "
            "selected resource, you must still fulfill the same purpose and verification "
            "requirement; never silently skip it.\n"
            f"{resources}"
        )
    return "\n\n".join(section for section in sections if section)


def validate_briefing_resources(output: dict[str, Any], resources: list[dict[str, Any]]) -> None:
    """Apply the production resource-selection checks to a frozen catalog."""
    tools = tuple(
        _ToolResource.model_validate(
            {key: item.get(key, "") for key in ("identifier", "label", "description")}
        )
        for item in resources
        if item.get("kind", "tool") == "tool"
    )
    processes = tuple(
        _ProcessResource.model_validate(
            {key: item.get(key, "") for key in ("identifier", "label", "description")}
        )
        for item in resources
        if item.get("kind") == "process"
    )
    _validate_choices(_ResourceCatalog(tools, processes), _BriefingDraft.model_validate(output))
