"""One tested value with item evidence, and separate shared experiment settings."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.topic import TopicDetectionLabInput
from app.dream.contracts import MemoryExtractionInput, TaskOutcomeEvidenceItem
from app.agent.contracts import TaskMessage


class LabInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable_value: JsonValue
    context: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class CapturedInput(LabInput):
    """Item evidence plus observed shared settings for capture comparison."""

    parameters: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PipelineParameters(Parameters):
    uses_llm_calls: bool = True
    use_planner: bool = True
    use_briefing: bool = False
    briefing_efforts: list[Literal["standard", "high"]] = Field(default_factory=list[Literal["standard", "high"]])
    execution_efforts: list[Literal["standard", "high"]] = Field(default_factory=lambda: ["standard", "high"])


class DispatcherParameters(Parameters):
    label: str = ""
    effort: Literal["standard", "high"] = "standard"
    forced_route: Literal["EXEC", "BRIEFING", "PLAN"] | None = None
    forced_effort: Literal["standard", "high"] | None = None
    auto_approve: bool = False
    driver_code: str = "internal"
    pipeline_policy: PipelineParameters = Field(default_factory=PipelineParameters)
    shared_context: str = ""
    agent_id: int | None = None
    message_platform: str | None = None
    message_group_id: str | None = None
    parent_id: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class BriefingParameters(Parameters):
    label: str = ""
    task_uri: str = ""
    effort: Literal["standard", "high"] = "standard"
    language: str = "en"
    agent: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    message_type: str = ""
    room_id: str = ""
    sender: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    attachments: list[JsonValue] = Field(default_factory=list[JsonValue])
    resources: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])


class PlannerParameters(Parameters):
    label: str = ""
    language: str = "en"
    shared_context: str = ""
    can_clarify: bool = True
    origin: str = ""
    tool_catalog: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])
    tool_catalog_version: str = ""
    result_contract: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    delivery_owner: str = ""
    max_depth: int = Field(default=3, ge=1, le=10)
    max_nodes: int = Field(default=24, ge=1, le=500)
    max_leaves: int = Field(default=12, ge=1, le=250)


class TopicParameters(Parameters):
    pass


class TaskMemorySource(Parameters):
    task_trace: dict[str, JsonValue]
    messages: list[str] = Field(min_length=1, max_length=20)


class MemoryParameters(Parameters):
    source_kind: Literal["conversation_round", "task"] = "conversation_round"
    existing_memories: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=10
    )


class OutcomeVariable(Parameters):
    terminal_status: str = Field(min_length=1, max_length=40)
    final_result: str = Field(default="", max_length=4000)
    normalized_error: str = Field(default="", max_length=2000)
    observations: list[TaskOutcomeEvidenceItem] = Field(
        default_factory=list[TaskOutcomeEvidenceItem], max_length=48
    )


class CycleVariable(Parameters):
    status: str = Field(min_length=1, max_length=40)
    result: str = Field(default="", max_length=30000)


class ReflectionParameters(Parameters):
    label: str = ""
    objective: str = ""
    owner_agent_id: int | None = None
    language: str = "en"
    driver_code: str = ""
    model_code: str = ""
    effort: str = ""
    route: str = ""
    injected_memory_ids: list[str] = Field(default_factory=list[str], max_length=50)


class GoalParameters(Parameters):
    title: str = ""
    description: str = ""
    sequence: int = Field(default=1, ge=1)
    latest_task_objective: str = ""
    referrer: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    referrer_max_reminders: int = Field(default=3, ge=0)


class ExecutorParameters(Parameters):
    agent: dict[str, JsonValue] = Field(
        default_factory=lambda: {
            "name": "Lab",
            "gender": "female",
            "job_title": "assistant",
            "personality": "Direct and reliable",
            "job_description": "Help the user.",
        }
    )
    language: str = "en"
    datetime: str = "2026-01-01T12:00:00+00:00"
    weekday: str = "Thursday"
    location: str = ""
    channel: str = "lab"
    room_id: str = "lab-benchmark"
    context_projection: str = ""
    linked_work: str = ""
    available_tools: list[str] = Field(default_factory=list[str])
    available_processes: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]]
    )
    memories: list[JsonValue] = Field(default_factory=list[JsonValue])
    resources: list[JsonValue] = Field(default_factory=list[JsonValue])
    briefing: str = ""
    plan: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    working_set: list[JsonValue] = Field(default_factory=list[JsonValue])
    interrupted_objective: str = ""
    tool_responses: dict[str, list[JsonValue]] = Field(default_factory=dict[str, list[JsonValue]])


class DiagnosisParameters(Parameters):
    language: Literal["en", "fr", "zh"] = "fr"
    user_context: str = Field(default="", max_length=6000)
    agent_configuration: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    available_tools: list[JsonValue] = Field(default_factory=list[JsonValue])
    active_skills: list[JsonValue] = Field(default_factory=list[JsonValue])
    current_task_runtime_settings: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue]
    )


class ItemContext(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DispatcherContext(ItemContext):
    messages: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])


class BriefingContext(ItemContext):
    history: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=6
    )
    recent_attachments: list[JsonValue] = Field(default_factory=list[JsonValue])
    recent_images: list[JsonValue] = Field(default_factory=list[JsonValue])


class PlannerContext(ItemContext):
    history: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=30
    )
    clarifications: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])


class TopicContext(ItemContext):
    initial_topic: dict[str, JsonValue] | None = None
    message_context: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=500
    )


class MemoryContext(ItemContext):
    topic: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    history: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=5
    )
    speaker_context: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=20
    )


class GoalContext(ItemContext):
    tracking_content: str = ""


class ExecutorContext(ItemContext):
    history: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])


@dataclass(frozen=True)
class LabContract:
    key: str
    variable_name: str
    variable_type: Literal["string", "array", "object", "source"]
    parameters_type: type[Parameters]
    result_name: str
    treatment: str
    context_type: type[ItemContext] = ItemContext

    def descriptor(self) -> dict[str, Any]:
        variable_schema: dict[str, Any] = (
            OutcomeVariable.model_json_schema()
            if self.key == "outcome_reflection"
            else CycleVariable.model_json_schema()
            if self.key == "goal_tracking"
            else {
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}},
                    TaskMemorySource.model_json_schema(),
                ]
            }
            if self.variable_type == "source"
            else {"type": self.variable_type}
        )
        return {
            "key": self.key,
            "variable_name": self.variable_name,
            "variable_schema": variable_schema,
            "parameters_schema": self.parameters_type.model_json_schema(),
            "parameter_defaults": self.parameters_type().model_dump(mode="json"),
            "context_schema": self.context_type.model_json_schema(),
            "context_defaults": self.context_type().model_dump(mode="json"),
            "result_name": self.result_name,
            "treatment": self.treatment,
        }


CONTRACTS = {
    entry.key: entry
    for entry in (
        LabContract(
            "dispatcher",
            "request",
            "string",
            DispatcherParameters,
            "dispatch_decision",
            "app.agent.Dispatcher.run",
            DispatcherContext,
        ),
        LabContract(
            "briefing",
            "objective",
            "string",
            BriefingParameters,
            "briefing_and_resources",
            "briefing",
            BriefingContext,
        ),
        LabContract(
            "planner",
            "objective",
            "string",
            PlannerParameters,
            "plan_or_clarification",
            "planner",
            PlannerContext,
        ),
        LabContract(
            "topic_classification",
            "exchange",
            "array",
            TopicParameters,
            "topics_per_message",
            "app.topic.detect_topic_with_diagnostics",
            TopicContext,
        ),
        LabContract(
            "memory_extraction",
            "source",
            "source",
            MemoryParameters,
            "memory_operations",
            "app.dream.evaluate_memory_extraction",
            MemoryContext,
        ),
        LabContract(
            "outcome_reflection",
            "outcome",
            "object",
            ReflectionParameters,
            "lessons",
            "outcome_reflection",
        ),
        LabContract(
            "goal_tracking",
            "cycle_result",
            "object",
            GoalParameters,
            "goal_judgment",
            "goal_tracking",
            GoalContext,
        ),
        LabContract(
            "task_executor",
            "request",
            "string",
            ExecutorParameters,
            "response_and_tool_calls",
            "task_executor_with_simulated_tools",
            ExecutorContext,
        ),
        LabContract(
            "conversation_executor",
            "current_turn",
            "string",
            ExecutorParameters,
            "response_and_actions",
            "conversation_executor_with_simulated_tools",
            ExecutorContext,
        ),
        LabContract(
            "voice_executor",
            "transcript",
            "string",
            ExecutorParameters,
            "spoken_response_and_actions",
            "voice_text_executor_with_simulated_tools",
            ExecutorContext,
        ),
        LabContract(
            "task_analysis",
            "execution_dossier",
            "object",
            DiagnosisParameters,
            "diagnosis",
            "task_analysis",
        ),
    )
}
_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def validate_parameters(
    mechanism: str, value: dict[str, Any], *, partial: bool = False
) -> dict[str, Any]:
    parsed = CONTRACTS[mechanism].parameters_type.model_validate(value)
    values = parsed.model_dump(mode="json")
    return {
        key: value for key, value in values.items() if not partial or key in parsed.model_fields_set
    }


def resolve_input(mechanism: str, value: object, shared: dict[str, Any]) -> tuple[LabInput, Any]:
    contract = CONTRACTS[mechanism]
    item = LabInput.model_validate(value)
    parameters = validate_parameters(mechanism, shared)
    context = contract.context_type.model_validate(item.context).model_dump(mode="json")
    native_fields = {**parameters, **context}
    variable = item.variable_value
    kind = contract.variable_type
    if kind == "string" and (not isinstance(variable, str) or not variable.strip()):
        raise ValueError(f"{contract.variable_name} must be non-empty text")
    if kind == "array" and (not isinstance(variable, list) or not variable):
        raise ValueError(f"{contract.variable_name} must be a non-empty array")
    if kind == "object" and not isinstance(variable, dict):
        raise ValueError(f"{contract.variable_name} must be an object")
    if mechanism == "dispatcher":
        native: Any = {**native_fields, "objective": variable}
        native["data"] = {**parameters["data"], "text": variable}
    elif mechanism == "topic_classification":
        texts = TypeAdapter(list[str]).validate_python(variable)
        metadata: list[dict[str, Any]] = native_fields.pop("message_context")
        if metadata and len(metadata) != len(texts):
            raise ValueError("Provide one message context per message, or an empty context list")
        for message_context in metadata:
            if set(message_context) - (
                set(TaskMessage.model_fields) - {"text"} | {"time", "id", "sender", "role"}
            ):
                raise ValueError("Unknown message context field")
        messages = [
            {**(metadata[i] if metadata else {}), "text": text} for i, text in enumerate(texts)
        ]
        native = TopicDetectionLabInput.model_validate(
            {**native_fields, "messages": messages}
        ).model_dump(mode="json")
    elif mechanism == "memory_extraction":
        speakers: list[dict[str, Any]] = native_fields.pop("speaker_context")
        if parameters["source_kind"] == "conversation_round":
            texts = TypeAdapter(list[str]).validate_python(variable)
            if speakers and len(speakers) != len(texts):
                raise ValueError("Provide one speaker context per source message")
            current = [
                {**(speakers[i] if speakers else {}), "text": text} for i, text in enumerate(texts)
            ]
            native = {**native_fields, "current": current, "task_trace": None}
        else:
            if not isinstance(variable, dict):
                raise ValueError("A Task source must be an execution report object")
            source = TaskMemorySource.model_validate(variable)
            if speakers and len(speakers) != len(source.messages):
                raise ValueError("Provide one speaker context per source message")
            native = {
                **native_fields,
                "current": [
                    {**(speakers[i] if speakers else {}), "text": text}
                    for i, text in enumerate(source.messages)
                ],
                "task_trace": source.task_trace,
            }
        native = MemoryExtractionInput.model_validate(native).model_dump(mode="json")
        if not native["topic"]:
            raise ValueError("Memory extraction requires a Topic")
    elif mechanism == "outcome_reflection":
        outcome = OutcomeVariable.model_validate(variable)
        native = {**native_fields, **outcome.model_dump(mode="json")}
    elif mechanism == "goal_tracking":
        cycle = CycleVariable.model_validate(variable)
        native = {**native_fields, "cycle_result": cycle.model_dump(mode="json")}
    elif mechanism.endswith("_executor"):
        native = {**native_fields, "message": variable}
    elif mechanism == "task_analysis":
        allowed = {
            "selected_task",
            "related_tasks",
            "attempts",
            "llm_calls",
            "process_runs",
            "deterministic_signals",
            "evidence_notes",
        }
        if not isinstance(variable, dict) or not variable or set(variable) - allowed:
            raise ValueError("Execution dossier contains only Task evidence")
        native = {**native_fields, "dossier": variable}
    else:
        native = {**native_fields, "objective": variable}
    return LabInput(variable_value=variable, context=context), native


def split_capture(mechanism: str, native: Any, *, objective: str | None = None) -> CapturedInput:
    """Classify a current native capture; this is not an old-dataset converter."""
    fields = set(CONTRACTS[mechanism].parameters_type.model_fields)
    context_fields = set(CONTRACTS[mechanism].context_type.model_fields)
    mapping = cast(dict[str, Any], native) if isinstance(native, dict) else {}
    parameters = {key: deepcopy(value) for key, value in mapping.items() if key in fields}
    context = {key: deepcopy(value) for key, value in mapping.items() if key in context_fields}
    if mechanism == "topic_classification":
        messages: list[dict[str, Any]] = mapping.get("messages", [])
        variable: Any = [message.get("text", "") for message in messages]
        context["message_context"] = [
            {key: value for key, value in message.items() if key != "text"} for message in messages
        ]
    elif mechanism == "memory_extraction":
        if mapping.get("source_kind") == "task":
            variable = {
                "task_trace": mapping.get("task_trace", {}),
                "messages": [message.get("text", "") for message in mapping.get("current", [])],
            }
            context["speaker_context"] = [
                {key: value for key, value in message.items() if key != "text"}
                for message in mapping.get("current", [])
            ]
        else:
            variable = [message.get("text", "") for message in mapping.get("current", [])]
            context["speaker_context"] = [
                {key: value for key, value in message.items() if key != "text"}
                for message in mapping.get("current", [])
            ]
    elif mechanism == "outcome_reflection":
        variable = {
            key: mapping.get(key, [] if key == "observations" else "")
            for key in ("terminal_status", "final_result", "normalized_error", "observations")
        }
    elif mechanism == "goal_tracking":
        variable = mapping.get("cycle_result", {"status": "", "result": ""})
    elif mechanism == "task_analysis":
        parameters["agent_configuration"] = parameters.get("agent_configuration") or {}
        variable = {key: val for key, val in mapping.items() if key not in fields}
    else:
        variable = (
            objective
            if objective is not None
            else mapping.get("message" if mechanism.endswith("_executor") else "objective", "")
        )
    return CapturedInput(
        variable_value=_JSON.validate_python(variable),
        context=cast(dict[str, JsonValue], context),
        parameters=cast(dict[str, JsonValue], parameters),
    )


def capture_input(mechanism: str, native: Any, *, objective: str | None = None) -> dict[str, Any]:
    source = split_capture(mechanism, native, objective=objective)
    return LabInput(variable_value=source.variable_value, context=source.context).model_dump(
        mode="json"
    )
