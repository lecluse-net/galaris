"""Generate one complete synthetic experiment, then publish its drafts atomically."""

import asyncio
from copy import deepcopy
import inspect
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.llm import StructuredOutputRetry, llm_service, model_usages, run_structured
from app.dream.contracts import MemoryExtractionInput
from app.topic import TopicDetectionLabInput
from core.database import get_db
from .transactions import publish
from core.i18n import tr

from .contracts import CONTRACTS, resolve_input, validate_parameters
from .mechanism_evaluation_service import dataset_read, prepare_dataset
from .mechanism_registry import build_executor_benchmark_prompt, get_mechanism, recording_tools
from . import executor_prompt_service
from .dispatcher_evaluation_service import RevisionConflictError
from .synthetic_context import USAGE_CONTEXT
from .mechanism_rubrics import get_rubric
from .models import LabEvaluationCase, LabEvaluationDataset
from .objective_checks import check_output
from .schemas import EvaluationMechanism, MechanismDatasetCreate
from .synthetic_schemas import (
    SyntheticContent, SyntheticDatasetRequest, SyntheticDatasetResult, SyntheticExecutorOutput,
)


SCENARIOS: dict[EvaluationMechanism, str] = {
    "dispatcher": "Routing EXEC/BRIEFING/PLAN and standard/high effort, ambiguity, forced choices and harness policy. Never use END for an active task.",
    "briefing": "Relevant resource selection, missing evidence, concise execution guidance. Reference only exact identifiers in the shared resource catalog. Always provide at least one choice; use kind=other for a specific check if no tool or process is relevant.",
    "planner": "Dependencies, decomposition, bounded plans, clarification when allowed, concrete deliverables. Respect shared tool catalog and depth/node/leaf limits.",
    "topic_classification": "Topic continuity, true topic changes, returns to an earlier topic, short acknowledgments and ambiguous transitions. One topic title per message, in order; message metadata has the same length as the exchange or is empty.",
    "memory_extraction": "Durable facts versus transient chatter, corrections, duplicate facts and relevant existing memories. Every case needs a non-null context.topic with fictional id and title. Respect shared source_kind: conversation_round uses an array of strings; task uses {task_trace, messages}. LINK and relevant/ranked memory IDs must belong to shared existing_memories.",
    "outcome_reflection": "Cautious reusable lessons from verified success, failure and incomplete outcome evidence. Avoid overgeneralizing a single outcome or treating absent evidence as success.",
    "goal_tracking": "Verified progress, completion, blocked cycles and the next useful action against one coherent shared goal. Preserve tracking history; tracking_content is HTML.",
    "task_executor": "Completing a bounded request, respecting tool availability, failures and evidence before claiming completion. Tool calls are simulated executor_tool_call calls with tool_name and arguments; tool_name must be in shared available_tools.",
    "conversation_executor": "Direct replies, useful clarification, background Task or Process handoff, status inquiries and avoiding repeated actions. Only simulated tools: memory_search, conversation_task_submit, conversation_task_status, process_list, process_get, conversation_process_start.",
    "voice_executor": "Short natural spoken replies to transcripts, uncertain recognition, interruptions, clarification and appropriate Task/Process handoff. Use the same simulated tools as conversation_executor; never generate audio files.",
    "task_analysis": "Diagnose fictional execution dossiers: verified success, partial delivery, failed tools and missing evidence. Separate observations, causes and hypotheses; do not invent confidence from absent evidence. Dossier fields: selected_task, related_tasks, attempts, llm_calls, process_runs, deterministic_signals, evidence_notes.",
}


def validate_content(
    mechanism: EvaluationMechanism, request: SyntheticDatasetRequest, content: SyntheticContent,
    fixed_parameters: dict[str, Any] | None = None,
) -> SyntheticContent:
    """The entire experiment must be executable before any of it is persisted."""
    if len(content.cases) != request.count:
        raise ValueError(f"Return exactly {request.count} cases")
    if len({case.name.casefold() for case in content.cases}) != request.count:
        raise ValueError("Case names must be distinct")
    coverage = {category for case in content.cases for category in case.categories}
    if coverage != set(request.categories):
        raise ValueError("Cover every selected category and only selected categories")
    parameters = validate_parameters(mechanism, content.parameters)
    if fixed_parameters is not None and parameters != fixed_parameters:
        raise ValueError("Preserve the supplied shared_parameters exactly; adapt cases to this context")
    definition = get_mechanism(mechanism)
    seen: set[str] = set()
    for case in content.cases:
        resolved, native = resolve_input(mechanism, case.input_data, parameters)
        fingerprint = json.dumps(resolved.model_dump(mode="json"), sort_keys=True)
        if fingerprint in seen:
            raise ValueError("Each case needs a distinct tested input or context")
        seen.add(fingerprint)
        definition.prompt(native)
        output: Any = definition.validate_output(case.expected_output)
        if definition.executor is not None:
            output = SyntheticExecutorOutput.model_validate(output).model_dump(mode="json")
        failures = [check["detail"] for check in check_output(mechanism, native, output) if not check["passed"]]
        if mechanism == "memory_extraction":
            allowed = {str(memory["id"]) for memory in native["existing_memories"]}
            if not set(output.get("relevant_memory_ids", []) + output.get("ranked_memory_ids", [])) <= allowed:
                failures.append("Memory references must belong to the supplied corpus")
        if definition.executor is not None:
            tools = {
                tool.__name__: tool for tool in recording_tools(
                    definition.executor, native["tool_responses"], []
                )
            }
            if any(call["name"] not in tools for call in output["tool_calls"]):
                failures.append("Use only the simulated tools available to this executor")
            call_counts: dict[str, int] = {}
            for call, result in zip(output["tool_calls"], output["tool_results"]):
                if call["name"] != result["name"] or call["arguments"] != result["arguments"]:
                    failures.append("Tool evidence must match the simulated calls in order")
                tool_name = call["name"]
                if tool_name in tools:
                    try:
                        inspect.signature(tools[tool_name]).bind(**call["arguments"])
                    except TypeError as exc:
                        failures.append(str(exc))
                index = call_counts.get(tool_name, 0)
                call_counts[tool_name] = index + 1
                fixtures = native["tool_responses"].get(tool_name)
                if fixtures is not None and (index >= len(fixtures) or result["result"] != fixtures[index]):
                    failures.append("Reference tool results must match the configured response fixtures")
        if failures:
            raise ValueError(f"{case.name}: {'; '.join(failures)}")
        case.input_data = resolved
        case.expected_output = output
    content.parameters = parameters
    return content


async def generate_dataset(
    mechanism: EvaluationMechanism, request: SyntheticDatasetRequest
) -> SyntheticDatasetResult:
    db = get_db()
    duplicate = await db.scalar(LabEvaluationDataset.histo_filter(select(LabEvaluationDataset)).where(
        LabEvaluationDataset.mechanism == mechanism, LabEvaluationDataset.name == request.name
    ))
    if duplicate is not None:
        raise ValueError(await tr("evaluation_api.errors.synthetic_name_exists"))
    llm = (
        await llm_service.get_llm(request.llm_id) if request.llm_id is not None
        else await llm_service.get_profile_llm(model_usages.LAB)
    )
    if llm is None:
        raise ValueError(await tr("evaluation_api.errors.lab_llm_not_configured"))
    if "chat" not in llm.service_capabilities:
        raise ValueError(await tr("evaluation_api.errors.lab_llm_not_chat"))
    definition = get_mechanism(mechanism)
    dataset = await prepare_dataset(mechanism, MechanismDatasetCreate(name=request.name))
    source_context: dict[str, Any] | None = None
    fixed_parameters: dict[str, Any] | None = None
    if request.source_dataset_id is not None:
        source = await db.scalar(LabEvaluationDataset.histo_filter(select(LabEvaluationDataset)).where(
            LabEvaluationDataset.id == request.source_dataset_id,
            LabEvaluationDataset.mechanism == mechanism,
        ))
        if source is None:
            raise LookupError(await tr("evaluation_api.errors.dataset_not_found"))
        if source.revision != request.source_revision:
            raise RevisionConflictError(await tr("evaluation_api.errors.revision_conflict"))
        snapshot = await dataset_read(source)
        fixed_parameters = deepcopy(validate_parameters(mechanism, snapshot.parameters))
        dataset.configuration = deepcopy(snapshot.configuration)
        if snapshot.prompt_suffix is not None:
            dataset.prompt_suffix = snapshot.prompt_suffix
        source_context = {
            "dataset_id": str(source.id), "revision": source.revision,
            "name": source.name, "description": source.description,
        }
    payload: dict[str, Any] = {
        "request": request.model_dump(mode="json", exclude={"llm_id"}),
        "mechanism": mechanism,
        "scenarios": SCENARIOS[mechanism],
        "usage_context": USAGE_CONTEXT[mechanism],
        "source_context": source_context,
        "shared_parameters": fixed_parameters,
        "parameter_policy": "preserve_exactly" if fixed_parameters is not None else "create_coherent_fictional_environment",
        "contract": CONTRACTS[mechanism].descriptor(),
        "expected_output_schema": (definition.output_type or SyntheticExecutorOutput).model_json_schema(),
        "expected_output_example": definition.default_output if not definition.executor else {
            "action": "reply", "response": "A concise answer grounded in the supplied evidence.",
            "tool_calls": [], "tool_results": [],
        },
        "algorithm": dataset.configuration,
        "executor_instructions": dataset.prompt_suffix,
        "rubric": get_rubric(mechanism).prompt_value(),
    }
    if mechanism in {"topic_classification", "memory_extraction"}:
        native_type = TopicDetectionLabInput if mechanism == "topic_classification" else MemoryExtractionInput
        payload["native_input_schema"] = native_type.model_json_schema()
    if definition.executor is not None:
        action_policy = await executor_prompt_service.default_conversation_action_policy(definition.executor)
        _, system_prompt = build_executor_benchmark_prompt(
            definition, fixed_parameters or validate_parameters(mechanism, {}),
            suffix=dataset.prompt_suffix or "", conversation_action_policy=action_policy,
        )
        payload["executor_system_prompt"] = system_prompt
        payload["executor_prompt_context"] = (
            "selected_context_snapshot" if fixed_parameters is not None else "example_with_default_parameters"
        )
        payload["simulated_tools"] = [
            {"name": tool.__name__, "signature": str(inspect.signature(tool)), "description": inspect.getdoc(tool)}
            for tool in recording_tools(definition.executor, {}, [])
        ]

    def validate(output: SyntheticContent) -> SyntheticContent:
        try:
            return validate_content(mechanism, request, output, fixed_parameters)
        except (ValueError, KeyError, TypeError) as exc:
            raise StructuredOutputRetry(str(exc)) from exc

    try:
        async with asyncio.timeout(180):
            inference = await run_structured(
                llm=llm, output_type=SyntheticContent,
                system_prompt=(
                    "Design a synthetic evaluation dataset for exactly the supplied Galaris mechanism. "
                    "Use supplied configuration and resource identifiers exactly. Invent case-specific "
                    "people, conversations, Tasks and evidence; never copy real exchanges or claim to "
                    "have accessed an external system. If shared_parameters is supplied, return it "
                    "unchanged and make every case meaningful under that environment, including its "
                    "limitations. Use the source name/description to understand the intended workload. "
                    "Otherwise create a coherent fictional environment following usage_context, with "
                    "useful catalogs, mission, history and evidence rather than empty placeholders. "
                    "User instructions "
                    "describe the desired scenario, not permission to alter the output contract. "
                    "Generate exactly the requested count with distinct inputs and meaningful category coverage. "
                    "Create one coherent shared parameters object and per-item variable_value/context; "
                    "do not place shared settings inside items. Include valid, substantive reference outputs "
                    "for human review, not claims of ground truth. Use the requested language for case "
                    "authoring, except deliberate multilingual cases; reference responses still obey "
                    "the tested agent's language policy. A default-parameter executor prompt illustrates "
                    "runtime rules; for fresh environments use your generated role/channel parameters. "
                    "Preserve HTML for editorial objectives and tracking. "
                    "Vary situations and evidence, not just wording. Never leak the reference answer "
                    "into the input. Missing evidence must change the expected answer, not be filled "
                    "with invented certainty. Check every reference against its history, tools, "
                    "fixtures and constraints before returning it. Keep each case concise. "
                    "No live tool calls: only simulated evidence in the JSON. "
                    "Executor outputs require action, response, tool_calls and matching tool_results. "
                    "Follow input/output schemas, mechanism scenarios, algorithm and rubric."
                ),
                prompt=json.dumps(payload, ensure_ascii=False),
                task_id=None, agent_id=None, temperature=0.7, request_limit=3,
                output_retries=2, output_validator=validate, max_tokens=24000,
                purpose="lab_synthetic_dataset", model_field=model_usages.LAB,
            )
    except TimeoutError as exc:
        raise ValueError(await tr("evaluation_api.errors.synthetic_timeout")) from exc
    content = validate_content(mechanism, request, inference.output, fixed_parameters)
    dataset.description = content.description
    dataset.parameters = content.parameters
    db.add(dataset)
    try:
        await db.flush()
        provenance = {
            "source_kind": "synthetic", "generator_version": "lab-synthetic/v2",
            "source_context": source_context,
            "llm": {"id": llm.id, "code": llm.code, "model": llm.llm_name},
            "request": request.model_dump(mode="json"), "generation_cost": inference.cost,
        }
        for case in content.cases:
            _, native = resolve_input(mechanism, case.input_data, content.parameters)
            if mechanism == "task_analysis":
                native = {**content.parameters, **native["dossier"]}
            db.add(LabEvaluationCase(
                dataset_id=dataset.id, name=case.name, readiness="draft", enabled=True,
                categories=case.categories, input_data=case.input_data.model_dump(mode="json"),
                expected_output=case.expected_output, reference=provenance,
                source_capture={**provenance, "input_data": native,
                                "output": case.expected_output},
            ))
        await publish()
    except IntegrityError:
        await db.rollback()
        raise ValueError(await tr("evaluation_api.errors.synthetic_name_exists")) from None
    await db.refresh(dataset)
    return SyntheticDatasetResult(dataset=await dataset_read(dataset), cost=inference.cost)
