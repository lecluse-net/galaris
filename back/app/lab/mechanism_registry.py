"""Registry of side-effect-free AI mechanisms benchmarked by the Lab."""

from __future__ import annotations

import json
import inspect
from functools import wraps
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, JsonValue

from app.agent import (
    evaluate_dispatcher_input,
    dispatcher_system_prompt,
    ExecutorKind,
    ExecutorPromptContext,
    PromptTree,
    build_executor_prompt_tree,
    render_prompt_tree,
)
from app.agent.evaluation import (
    BriefingChoice,
    Plan,
    briefing_system_prompt,
    built_in_planner_lab_configuration,
)
from app.dream.evaluation import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    MemoryExtractionLabConfiguration,
    MemoryExtractionLabOutput,
    TaskOutcomeReflection,
    evaluate_memory_extraction,
    outcome_reflection_system_prompt,
)
from app.goal.evaluation import GoalJudgement, goal_tracking_system_prompt
from app.llm import LLM, LLMCallPurpose, model_usages
from app.llm.facade import (
    record_text_inferences,
    record_structured_inferences,
    register_inference_output,
)
from app.llm.structured_service import (
    run_prompted,
    run_structured,
    run_text,
    run_text_with_tools,
)
from app.topic.evaluation import (
    TOPIC_CONTINUITY_SYSTEM_PROMPT,
    TopicDetectionLabConfiguration,
    TopicDetectionLabOutput,
    evaluate_topic_detection,
    topic_detection_case_prompt,
)

from .schemas import (
    DispatcherExpectedDecision,
    EvaluationMechanism,
    EvaluationValueFormat,
    TaskAnalysisContent,
)
from .prompts import ANALYST_SYSTEM_PROMPT
from app.agent.evaluation import (
    render_briefing_input,
    validate_briefing_resources,
    planner_evaluation_system_prompt,
)


class BriefingEvaluationOutput(BaseModel):
    result: str = Field(min_length=1, max_length=8_000)
    choices: list[BriefingChoice] = Field(default_factory=list[BriefingChoice], max_length=12)


class _BriefingValidationContext(BaseModel):
    resources: list[dict[str, JsonValue]]


def _briefing_validator(
    context: dict[str, JsonValue],
) -> Callable[[BriefingEvaluationOutput], BriefingEvaluationOutput]:
    frozen = _BriefingValidationContext.model_validate(context)

    def validate(value: BriefingEvaluationOutput) -> BriefingEvaluationOutput:
        validate_briefing_resources(value.model_dump(mode="json"), frozen.resources)
        return value

    return validate


def register_inference_output_contracts() -> None:
    register_inference_output(
        "galaris.lab.briefing/v1", BriefingEvaluationOutput, validator_factory=_briefing_validator
    )


@dataclass(frozen=True)
class MechanismDefinition:
    key: EvaluationMechanism
    input_format: EvaluationValueFormat
    output_format: EvaluationValueFormat
    output_type: type[BaseModel] | None
    system_prompt: str
    call_style: Literal["structured", "prompted"]
    marker: str
    default_input: Any
    default_output: Any
    marker_aliases: tuple[str, ...] = ()
    executor: ExecutorKind | None = None
    source_import: bool = True

    def prompt(self, value: Any) -> str:
        if self.key == "task_analysis":
            from .analysis_service import render_analysis_prompt

            parameters = cast(dict[str, Any], value)
            payload = {
                **parameters["dossier"],
                **{
                    key: parameters[key]
                    for key in (
                        "agent_configuration",
                        "available_tools",
                        "active_skills",
                        "current_task_runtime_settings",
                    )
                },
            }
            return render_analysis_prompt(
                payload, language=parameters["language"], user_context=parameters["user_context"]
            )[0]
        if self.key == "briefing" and isinstance(value, dict):
            native = cast(dict[str, Any], value)
            grouped: dict[str, list[dict[str, Any]]] = {}
            processes: list[dict[str, Any]] = []
            for resource in native["resources"]:
                if resource.get("kind", "tool") == "process":
                    processes.append(resource)
                else:
                    grouped.setdefault(resource.get("label", ""), []).append(
                        {
                            "identifier": resource["identifier"],
                            "description": resource.get("description", ""),
                        }
                    )
            task_payload = {
                "uri": native["task_uri"],
                "label": native["label"],
                "objective": native["objective"],
                "effort": native["effort"],
                "context": {
                    key: native[key]
                    for key in (
                        "language",
                        "message_type",
                        "room_id",
                        "sender",
                        "attachments",
                        "recent_attachments",
                        "recent_images",
                    )
                },
                "recent_messages": native["history"],
            }
            return render_briefing_input(
                task_payload,
                native["agent"],
                {
                    "tool_groups": [
                        {"label": label, "functions": functions}
                        for label, functions in grouped.items()
                    ],
                    "processes": processes,
                },
            )
        if self.executor is not None:
            if not isinstance(value, dict):
                raise ValueError("Executor benchmark input must be a JSON object")
            mapping = cast(dict[str, Any], value)
            message = str(mapping.get("message") or "").strip()
            if not message:
                raise ValueError("Executor benchmark input.message cannot be empty")
            context = {
                key: mapping[key]
                for key in (
                    "history",
                    "memories",
                    "resources",
                    "briefing",
                    "plan",
                    "working_set",
                    "interrupted_objective",
                )
                if mapping.get(key)
            }
            return json.dumps({"request": message, "context": context}, ensure_ascii=False)
        if self.input_format == "text":
            if isinstance(value, dict):
                return json.dumps(value, ensure_ascii=False, indent=2)
            if not isinstance(value, str):
                raise ValueError("The mechanism input must be plain text")
            if not value.strip():
                raise ValueError("The mechanism input cannot be empty")
            return value
        if not isinstance(value, (dict, list)):
            raise ValueError("The mechanism input must be valid JSON")
        if self.key == "topic_classification":
            return topic_detection_case_prompt(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def validate_output(self, value: Any) -> Any:
        if self.key == "topic_classification":
            return TopicDetectionLabOutput.model_validate(value).model_dump(mode="json")
        if self.output_format == "text":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("The expected output must be plain text")
            return value
        if self.output_type is None:
            if not isinstance(value, (dict, list)):
                raise ValueError("The expected output must be valid JSON")
            return cast(Any, value)
        return self.output_type.model_validate(value).model_dump(mode="json")


_DEFINITIONS: tuple[MechanismDefinition, ...] = (
    MechanismDefinition(
        key="task_analysis",
        input_format="json",
        output_format="json",
        output_type=TaskAnalysisContent,
        system_prompt=ANALYST_SYSTEM_PROMPT,
        call_style="structured",
        marker="task_analysis",
        source_import=False,
        default_input={},
        default_output={
            "verdict": "inconclusive",
            "confidence": 0,
            "summary": "",
            "goal_assessment": "",
            "observed_outcome": "",
        },
    ),
    MechanismDefinition(
        key="dispatcher",
        input_format="json",
        output_format="json",
        output_type=DispatcherExpectedDecision,
        system_prompt=dispatcher_system_prompt(),
        call_style="structured",
        marker="dispatcher",
        default_input={
            "objective": "",
            "label": "",
            "effort": "standard",
            "data": {},
            "messages": [],
        },
        default_output={
            "route": "EXEC",
            "effort": "standard",
            "language": "en",
            "reasoning": "",
        },
    ),
    MechanismDefinition(
        key="briefing",
        input_format="text",
        output_format="json",
        output_type=BriefingEvaluationOutput,
        system_prompt=briefing_system_prompt(),
        call_style="structured",
        marker="You prepare a concise execution briefing",
        default_input=(
            "# Execution briefing input\n\n"
            "## Task\n\nDescribe the task, its objective and constraints here.\n\n"
            "## Executor\n\nDescribe the executor here.\n\n"
            "## Available resources\n\nList the exact available resources here."
        ),
        default_output={
            "result": "Describe the expected execution briefing.",
            "choices": [],
        },
    ),
    MechanismDefinition(
        key="planner",
        input_format="text",
        output_format="json",
        output_type=Plan,
        system_prompt=built_in_planner_lab_configuration().system_prompt,
        call_style="structured",
        marker="You are the Planner. You receive an objective",
        default_input="Describe the objective, context and available tools to plan.",
        default_output={
            "clarification_questions": [],
            "brief": {
                "objective": "Describe the expected objective.",
                "context": "",
                "strategy": "",
                "rationale": "",
                "constraints": [],
                "success_criteria": [],
                "deliverables": [],
            },
            "steps": [],
            "tool_catalog_version": "",
        },
    ),
    MechanismDefinition(
        key="topic_classification",
        input_format="json",
        output_format="json",
        output_type=TopicDetectionLabOutput,
        system_prompt=TOPIC_CONTINUITY_SYSTEM_PROMPT,
        call_style="prompted",
        marker="Decide whether the explicitly marked current message still belongs",
        default_input={
            "messages": [{"text": "", "time": 0}],
            "initial_topic": None,
        },
        default_output={"topics": [""]},
    ),
    MechanismDefinition(
        key="memory_extraction",
        input_format="json",
        output_format="json",
        output_type=MemoryExtractionLabOutput,
        system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
        call_style="prompted",
        marker="You decide whether one completed conversational round or Task contains durable information",
        default_input={
            "source_kind": "conversation_round",
            "topic": {"id": "topic-1", "title": "Topic"},
            "history": [],
            "current": [{"role": "human", "text": ""}],
            "task_trace": None,
            "existing_memories": [],
        },
        default_output={
            "operations": [],
            "relevant_memory_ids": [],
            "ranked_memory_ids": [],
        },
    ),
    MechanismDefinition(
        key="outcome_reflection",
        input_format="json",
        output_format="json",
        output_type=TaskOutcomeReflection,
        system_prompt=outcome_reflection_system_prompt(),
        call_style="prompted",
        marker="You produce cautious, reusable lessons from a bounded Task outcome evidence object",
        default_input={
            "task_uri": "galaris://task/00000000-0000-0000-0000-000000000000",
            "owner_agent_id": None,
            "label": "",
            "objective": "",
            "terminal_status": "SUCCESS",
            "final_result": "",
            "normalized_error": "",
            "driver_code": "",
            "model_code": "",
            "effort": "",
            "route": "",
            "observations": [],
            "injected_memory_ids": [],
            "fingerprint": "0" * 64,
        },
        default_output={"lessons": []},
    ),
    MechanismDefinition(
        key="goal_tracking",
        input_format="text",
        output_format="json",
        output_type=GoalJudgement,
        system_prompt=goal_tracking_system_prompt(),
        call_style="structured",
        marker="You maintain the durable Markdown tracking for a long-running Goal",
        default_input=(
            "GOAL TITLE:\n\nGOAL DESCRIPTION:\n\nCURRENT DURABLE TRACKING (HTML):\n\n"
            "LATEST CYCLE:\n1\n\nLATEST TASK STATUS:\nSUCCESS\n\n"
            "LATEST TASK OBJECTIVE:\n\nLATEST TASK RESULT:\n"
        ),
        default_output={
            "action": "CONTINUE",
            "reason": "Describe why another cycle is useful.",
            "progress": {"changed": False, "summary": "No verified progress.", "evidence": []},
            "tracking_content": "<h1>Goal tracking</h1><p>Describe the current state.</p>",
        },
        marker_aliases=("You are the post-task evaluator for a long-running Goal",),
    ),
    MechanismDefinition(
        key="task_executor",
        input_format="json",
        output_format="json",
        output_type=None,
        system_prompt="",
        call_style="structured",
        marker="galaris.system-prompt/v1:task",
        default_input={
            "message": "Inspect the supplied information and perform the requested action.",
            "language": "en",
            "agent": {
                "name": "Galaris Test Agent",
                "gender": "female",
                "job_title": "assistant",
                "personality": "Direct and reliable",
                "job_description": "Complete assigned work with the available tools.",
            },
            "available_tools": ["executor_tool_call"],
        },
        default_output={
            "action": "use_tool",
            "response_requirements": [],
            "objective_requirements": [],
        },
        executor="task",
    ),
    MechanismDefinition(
        key="conversation_executor",
        input_format="json",
        output_format="json",
        output_type=None,
        system_prompt="",
        call_style="structured",
        marker="galaris.system-prompt/v1:conversation",
        default_input={
            "message": "Prepare a detailed report that requires substantial research.",
            "language": "en",
            "agent": {
                "name": "Galaris Test Agent",
                "gender": "female",
                "job_title": "assistant",
                "personality": "Direct and reliable",
                "job_description": "Help the user and launch background work when necessary.",
            },
            "available_processes": [],
        },
        default_output={
            "action": "start_task",
            "response_requirements": ["Brief natural acknowledgement"],
            "objective_requirements": ["Preserve the requested deliverable"],
        },
        executor="conversation",
    ),
    MechanismDefinition(
        key="voice_executor",
        input_format="json",
        output_format="json",
        output_type=None,
        system_prompt="",
        call_style="structured",
        marker="galaris.system-prompt/v1:voice",
        default_input={
            "message": "Prepare a detailed report that requires substantial research.",
            "language": "en",
            "agent": {
                "name": "Galaris Test Agent",
                "gender": "female",
                "job_title": "assistant",
                "personality": "Natural, direct and reliable",
                "job_description": "Help during a live call and launch background work when needed.",
            },
            "available_processes": [],
        },
        default_output={
            "action": "start_task",
            "response_requirements": ["Concise natural spoken acknowledgement"],
            "objective_requirements": ["Preserve the requested deliverable"],
        },
        executor="voice",
    ),
)

MECHANISMS = {definition.key: definition for definition in _DEFINITIONS}


def get_mechanism(key: str) -> MechanismDefinition:
    definition = MECHANISMS.get(cast(EvaluationMechanism, key))
    if definition is None:
        raise LookupError(f"Unknown AI Lab mechanism: {key}")
    return definition


def build_executor_benchmark_prompt(
    definition: MechanismDefinition,
    input_data: Any,
    *,
    suffix: str,
    conversation_action_policy: str,
) -> tuple[PromptTree, str]:
    """Build the exact production prompt tree used by an executor benchmark case."""

    if definition.executor is None or not isinstance(input_data, dict):
        raise ValueError("This mechanism is not an executor benchmark")
    mapping = cast(dict[str, Any], input_data)
    raw_agent = mapping.get("agent")
    agent = cast(dict[str, Any], raw_agent) if isinstance(raw_agent, dict) else {}
    available_tools = mapping.get("available_tools")
    tool_names = [
        str(item)
        for item in (cast(list[Any], available_tools) if isinstance(available_tools, list) else [])
    ]
    raw_processes = mapping.get("available_processes")
    processes = cast(list[Any], raw_processes) if isinstance(raw_processes, list) else []
    process_text = json.dumps(processes, ensure_ascii=False, indent=2) if processes else ""
    if definition.executor in {"conversation", "voice"}:
        tool_text = (
            "Only these effect-free conversation tool contracts are exposed in this benchmark: "
            "`memory_search`, `conversation_task_submit`, `conversation_task_status`, "
            "`process_list`, `process_get`, and `conversation_process_start`."
        )
    else:
        tool_text = (
            "The benchmark exposes the effect-free `executor_tool_call` recorder. "
            f"The case declares these representative Task tools: {', '.join(tool_names) or 'none'}."
        )
    context = ExecutorPromptContext(
        agent_name=str(agent.get("name") or "Galaris Test Agent"),
        gender=str(agent.get("gender") or "female"),
        job_title=str(agent.get("job_title") or "assistant"),
        personality=str(agent.get("personality") or "Direct and reliable"),
        job_description=str(agent.get("job_description") or "Help the user."),
        language=str(mapping.get("language") or "en"),
        datetime=str(mapping.get("datetime") or "2026-01-01T12:00:00+00:00"),
        weekday=str(mapping.get("weekday") or "Thursday"),
        location=str(mapping.get("location") or ""),
        channel=str(
            mapping.get("channel") or ("voice:lab" if definition.executor == "voice" else "lab")
        ),
        room_id=str(mapping.get("room_id") or "lab-benchmark"),
        tool_advertisement=tool_text,
        process_advertisement=process_text,
        linked_work=str(mapping.get("linked_work") or "- none"),
        context_projection=str(
            mapping.get("context_projection") or "No unprocessed input was omitted."
        ),
        conversation_action_policy=conversation_action_policy,
    )
    tree = build_executor_prompt_tree(definition.executor, context, suffix=suffix)
    return tree, render_prompt_tree(tree)


async def memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    """Effect-free benchmark recorder for the production memory-search contract."""

    return {"query": query, "limit": limit, "items": [], "benchmark": True}


async def conversation_task_submit(
    objective: str,
    label: str = "",
) -> dict[str, Any]:
    """Record a proposed background Task without creating one."""

    return {
        "created": True,
        "task_uri": "galaris://task/00000000-0000-0000-0000-000000000001",
        "status": "CREATE",
        "objective": objective,
        "label": label,
        "benchmark": True,
    }


async def conversation_task_status(task_id: str) -> dict[str, Any]:
    """Return a deterministic effect-free Task status."""

    task_uri = task_id if task_id.startswith("galaris://task/") else f"galaris://task/{task_id}"
    return {"task_uri": task_uri, "status": "RUNNING", "benchmark": True}


async def process_list() -> dict[str, Any]:
    """Return a deterministic empty Process catalog."""

    return {"items": [], "benchmark": True}


async def process_get(workflow_id: str) -> dict[str, Any]:
    """Record Process discovery without accessing production state."""

    return {"found": True, "workflow_id": workflow_id, "benchmark": True}


async def conversation_process_start(
    workflow_id: str,
    input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a proposed Process launch without starting it."""

    return {
        "created": True,
        "run_id": "00000000-0000-0000-0000-000000000002",
        "workflow_id": workflow_id,
        "input": input or {},
        "benchmark": True,
    }


async def executor_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a representative Task tool call without performing its effect."""

    return {
        "tool_name": tool_name,
        "arguments": arguments or {},
        "success": True,
        "benchmark": True,
    }


def _executor_tools(executor: ExecutorKind) -> list[Any]:
    if executor == "task":
        return [executor_tool_call]
    return [
        memory_search,
        conversation_task_submit,
        conversation_task_status,
        process_list,
        process_get,
        conversation_process_start,
    ]


def recording_tools(
    executor: ExecutorKind, responses: dict[str, list[Any]], transcript: list[dict[str, Any]]
) -> list[Any]:
    """Typed native tool signatures with item-owned, sequential response fixtures."""
    tools = _executor_tools(executor)
    if set(responses) - {tool.__name__ for tool in tools}:
        raise ValueError("A response fixture names a tool unavailable to this executor")

    def wrap(tool: Any) -> Any:
        calls = 0

        @wraps(tool)
        async def recorded(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            arguments = dict(inspect.signature(tool).bind(*args, **kwargs).arguments)
            if tool.__name__ in responses:
                fixtures = responses[tool.__name__]
                if calls >= len(fixtures):
                    raise ValueError("The tool response fixture is exhausted")
                result = fixtures[calls]
            else:
                result = await tool(*args, **kwargs)
            calls += 1
            transcript.append({"name": tool.__name__, "arguments": arguments, "result": result})
            return result

        return recorded

    return [wrap(tool) for tool in tools]


def _executor_action(tool_calls: list[dict[str, Any]]) -> str:
    if not tool_calls:
        return "reply"
    names = [str(item.get("name") or "") for item in tool_calls]
    if "conversation_task_submit" in names:
        return "start_task"
    if "conversation_process_start" in names:
        return "start_process"
    if "conversation_task_status" in names:
        return "read_status"
    return "use_tool"


async def evaluate_mechanism(
    definition: MechanismDefinition,
    *,
    input_data: Any,
    llm: LLM,
    system_prompt_override: str | None = None,
    topic_configuration: dict[str, Any] | None = None,
) -> tuple[Any, float]:
    if definition.key == "dispatcher":
        result = await evaluate_dispatcher_input(
            input_data=input_data, llm=llm, system_prompt=system_prompt_override
        )
        return result.decision.model_dump(mode="json"), result.cost
    if definition.key == "topic_classification":
        configuration = (
            TopicDetectionLabConfiguration.model_validate(topic_configuration)
            if topic_configuration is not None
            else None
        )
        return await evaluate_topic_detection(
            input_data=input_data,
            llm=llm,
            configuration=configuration,
        )
    if definition.key == "memory_extraction":
        configuration = (
            MemoryExtractionLabConfiguration.model_validate(topic_configuration)
            if topic_configuration is not None
            else None
        )
        with record_text_inferences(durable=True):
            return await evaluate_memory_extraction(
                input_data=input_data,
                llm=llm,
                configuration=configuration,
            )
    if definition.key == "planner":
        system_prompt_override = planner_evaluation_system_prompt(
            system_prompt_override,
            max_depth=input_data["max_depth"],
            max_nodes=input_data["max_nodes"],
            max_leaves=input_data["max_leaves"],
            can_clarify=input_data["can_clarify"],
        )
    prompt = definition.prompt(input_data)
    if definition.executor is not None:
        if system_prompt_override is None:
            raise ValueError("Executor benchmarks require a frozen system prompt")
        transcript: list[dict[str, Any]] = []
        responses = cast(dict[str, list[Any]], input_data.get("tool_responses", {}))
        inference = await run_text_with_tools(
            llm=llm,
            prompt=prompt,
            system_prompt=system_prompt_override,
            tools=recording_tools(definition.executor, responses, transcript),
            purpose=LLMCallPurpose.LAB_MECHANISM_RUN,
            model_field=model_usages.LAB,
        )
        return {
            "action": _executor_action(inference.tool_calls),
            "response": inference.output,
            "tool_calls": inference.tool_calls,
            "tool_results": transcript,
        }, inference.cost
    if definition.output_type is None:
        if definition.output_format != "text":
            raise ValueError("This mechanism has no output contract")
        inference = await run_text(
            llm=llm,
            prompt=prompt,
            system_prompt=system_prompt_override or definition.system_prompt,
            task_id=None,
            agent_id=None,
            temperature=0.1 if definition.key == "task_analysis" else 0.0,
            request_limit=3,
            purpose=LLMCallPurpose.LAB_MECHANISM_RUN,
            model_field=model_usages.LAB,
        )
        return inference.output, inference.cost
    if definition.key == "briefing":
        register_inference_output_contracts()
        with record_structured_inferences():
            inference = await run_structured(
                llm=llm,
                output_type=BriefingEvaluationOutput,
                prompt=prompt,
                system_prompt=system_prompt_override or definition.system_prompt,
                task_id=None,
                agent_id=None,
                temperature=0.0,
                request_limit=3,
                output_retries=1,
                output_context={"resources": input_data["resources"]},
                purpose=LLMCallPurpose.LAB_MECHANISM_RUN,
                model_field=model_usages.LAB,
            )
        return inference.output.model_dump(mode="json"), inference.cost
    output_type = definition.output_type
    if definition.call_style == "prompted":
        inference = await run_prompted(
            llm=llm,
            output_type=output_type,
            prompt=prompt,
            system_prompt=system_prompt_override or definition.system_prompt,
            task_id=None,
            agent_id=None,
            temperature=0.1 if definition.key == "task_analysis" else 0.0,
            request_limit=3,
            output_retries=1,
            purpose=LLMCallPurpose.LAB_MECHANISM_RUN,
            model_field=model_usages.LAB,
        )
    else:
        inference = await run_structured(
            llm=llm,
            output_type=output_type,
            prompt=prompt,
            system_prompt=system_prompt_override or definition.system_prompt,
            task_id=None,
            agent_id=None,
            temperature=0.1 if definition.key == "task_analysis" else 0.0,
            request_limit=3,
            output_retries=1,
            purpose=LLMCallPurpose.LAB_MECHANISM_RUN,
            model_field=model_usages.LAB,
        )
    output = inference.output.model_dump(mode="json")
    return output, inference.cost


__all__ = [
    "MECHANISMS",
    "MechanismDefinition",
    "evaluate_mechanism",
    "build_executor_benchmark_prompt",
    "get_mechanism",
]
