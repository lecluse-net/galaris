"""Dedicated Lab MCP package. All commands reuse canonical Lab services."""

from typing import Any, Literal
from uuid import UUID

from app.tools import McpToolContext, mcp_tool

from . import mcp_service as service, mechanism_evaluation_service as evaluations
from . import evaluation_service, judgment_service
from . import operations
from .contracts import LabInput
from .mechanism_registry import get_mechanism
from .mechanism_rubrics import get_rubric
from .mcp_access import lab_call, has_source_access
from .mcp_schemas import Page, DatasetPatch, CasePatch, SourceImport
from .schemas import (
    EvaluationMechanism,
    EvaluationCaseCreate,
    EvaluationCaseRead,
    EvaluationRunRead,
    EvaluationRunStart,
    EvaluationRejudge,
    MechanismDatasetCreate,
    TopicMessageRangeImport,
    HumanReviewCreate,
    TaskAnalysisRequest,
    EvaluationRunAnalysisRequest,
    MechanismExpectedGenerate,
)
from .synthetic_schemas import SyntheticDatasetRequest, SyntheticExecutorOutput


@mcp_tool(
    "lab",
    name="lab_list",
    description="Discover every Lab mechanism and whether real-source inspection is authorized.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_list(ctx: McpToolContext) -> dict[str, Any]:
    return {
        "items": [
            {"key": item.key, "executor": item.executor, "source_import": item.source_import}
            for item in evaluations.list_mechanisms()
        ],
        "source_access": await has_source_access(ctx),
    }


@mcp_tool(
    "lab",
    name="lab_get",
    description="Read one Lab's executable input/configuration/output contracts and scoring rubric before editing cases.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_get(ctx: McpToolContext, mechanism: EvaluationMechanism) -> dict[str, Any]:
    definition = get_mechanism(mechanism)
    item = next(item for item in evaluations.list_mechanisms() if item.key == mechanism)
    return {
        **service.dump(item),
        "output_schema": (definition.output_type or SyntheticExecutorOutput).model_json_schema(),
        "output_example": definition.default_output,
        "rubric": get_rubric(mechanism).prompt_value(),
    }


@mcp_tool(
    "lab",
    name="lab_models",
    description="List compatible configured candidate and judge models, without provider credentials.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_models(ctx: McpToolContext, mechanism: EvaluationMechanism) -> dict[str, Any]:
    config = await evaluation_service.config()
    return {
        "candidates": [
            service.dump(item)
            for item in config.llms
            + (
                config.decision_llms
                if mechanism in {"dispatcher", "topic_classification", "memory_extraction"}
                else []
            )
        ],
        "judges": [service.dump(item) for item in config.llms],
        "default_lab_llm_id": config.lab_llm_id,
        "hybrid_generation": mechanism in {"topic_classification", "memory_extraction"},
    }


@mcp_tool(
    "lab",
    name="lab_prompt_defaults",
    description="Inspect effective Lab prompt and parameter defaults without creating a dataset.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_prompt_defaults(
    ctx: McpToolContext, mechanism: EvaluationMechanism
) -> dict[str, Any]:
    temporary = await evaluations.prepare_dataset(
        mechanism, MechanismDatasetCreate(name="Preview defaults")
    )
    return {
        "configuration": temporary.configuration,
        "parameters": temporary.parameters,
        "prompt_suffix": temporary.prompt_suffix,
    }


@mcp_tool(
    "lab",
    name="lab_dataset_list",
    description="List datasets with stable server pagination.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_dataset_list(
    ctx: McpToolContext, mechanism: EvaluationMechanism, pagination: Page
) -> dict[str, Any]:
    return await service.datasets(mechanism, pagination)


@mcp_tool(
    "lab",
    name="lab_dataset_get",
    description="Read a dataset, its revision, configuration and coverage.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_dataset_get(
    ctx: McpToolContext, mechanism: EvaluationMechanism, dataset_id: UUID
) -> dict[str, Any]:
    return service.dump(
        await evaluations.dataset_read(await service.dataset(mechanism, dataset_id))
    )


@mcp_tool(
    "lab",
    name="lab_dataset_create",
    description="Create a Lab dataset; reuse invocation_key only to retry this exact command.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_dataset_create(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    data: MechanismDatasetCreate,
    invocation_key: str,
) -> dict[str, Any]:
    return service.dump(await evaluations.create_dataset(mechanism, data))


@mcp_tool(
    "lab",
    name="lab_dataset_update",
    description="Update selected dataset fields with the last read revision. Omitted fields are preserved.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_dataset_update(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: DatasetPatch,
    invocation_key: str,
) -> dict[str, Any]:
    return await service.update_dataset(mechanism, dataset_id, data)


@mcp_tool(
    "lab",
    name="lab_dataset_clone",
    description="Copy an experiment and its cases atomically, preserving provenance for controlled comparison.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_dataset_clone(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    revision: int,
    name: str,
    invocation_key: str,
) -> dict[str, Any]:
    return await service.clone_dataset(mechanism, dataset_id, revision, name)


@mcp_tool(
    "lab",
    name="lab_dataset_delete",
    description="Soft-delete an experiment at its expected revision; active benchmarks must finish first.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_dataset_delete(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    revision: int,
    invocation_key: str,
) -> dict[str, Any]:
    return await service.delete_dataset(mechanism, dataset_id, revision)


@mcp_tool(
    "lab",
    name="lab_case_list",
    description="List cases with server pagination.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_case_list(
    ctx: McpToolContext, mechanism: EvaluationMechanism, dataset_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await service.cases(mechanism, dataset_id, pagination)


@mcp_tool(
    "lab",
    name="lab_case_get",
    description="Read a case's variable, context, reference, readiness, provenance and revision.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_case_get(
    ctx: McpToolContext, mechanism: EvaluationMechanism, case_id: UUID
) -> dict[str, Any]:
    return service.dump(EvaluationCaseRead.model_validate(await service.case(mechanism, case_id)))


@mcp_tool(
    "lab",
    name="lab_case_create",
    description="Create a draft case using the mechanism's defaults.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_case_create(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationCaseCreate,
    invocation_key: str,
) -> dict[str, Any]:
    return service.dump(await evaluations.create_case(mechanism, dataset_id, data))


@mcp_tool(
    "lab",
    name="lab_case_update",
    description="Edit and validate a case at its expected revision, or explicitly mark it draft/disabled.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_case_update(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    case_id: UUID,
    data: CasePatch,
    invocation_key: str,
) -> dict[str, Any]:
    return await service.update_case(mechanism, case_id, data)


@mcp_tool(
    "lab",
    name="lab_case_duplicate",
    description="Case duplicate at the expected revision. Capture parameter conflicts return a confirmation token.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_case_duplicate(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    case_id: UUID,
    revision: int,
    invocation_key: str,
) -> dict[str, Any]:
    await service.case(mechanism, case_id, revision)
    return service.dump(await evaluations.duplicate_case(mechanism, case_id))


@mcp_tool(
    "lab",
    name="lab_case_delete",
    description="Case delete at the expected revision. Capture parameter conflicts return a confirmation token.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_case_delete(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    case_id: UUID,
    revision: int,
    invocation_key: str,
) -> dict[str, Any]:
    await service.case(mechanism, case_id, revision)
    await evaluations.delete_case(mechanism, case_id)
    return {"deleted": True, "case_id": str(case_id)}


@mcp_tool(
    "lab",
    name="lab_case_restore_source",
    description="Case restore source at the expected revision. Capture parameter conflicts return a confirmation token.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_case_restore_source(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    case_id: UUID,
    revision: int,
    invocation_key: str,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    await service.case(mechanism, case_id, revision)
    return service.dump(
        await evaluations.restore_case_source(mechanism, case_id, confirmation_token)
    )


@mcp_tool(
    "lab",
    name="lab_input_preview",
    description="Preview the exact resolved input and prompts without inference.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_input_preview(
    ctx: McpToolContext, mechanism: EvaluationMechanism, dataset_id: UUID, data: LabInput
) -> dict[str, Any]:
    return service.dump(await evaluations.preview_input(mechanism, dataset_id, data))


@mcp_tool(
    "lab",
    name="lab_source_list",
    description="Discover real capture sources. Requires an active galaris_admin connection.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_source_list(
    ctx: McpToolContext, mechanism: EvaluationMechanism, pagination: Page, search: str | None = None
) -> dict[str, Any]:
    return await operations.source_list(mechanism, pagination, search)


@mcp_tool(
    "lab",
    name="lab_case_import",
    description="Import a typed real source. galaris_admin required. If parameters differ, inspect the error and explicitly resubmit its confirmation_token.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=True)
async def lab_case_import(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: SourceImport,
    invocation_key: str,
) -> dict[str, Any]:
    return await operations.import_case(mechanism, dataset_id, data)


@mcp_tool(
    "lab",
    name="lab_topic_agent_list",
    description="List agents with Topic capture sources; administrative source access required.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_topic_agent_list(ctx: McpToolContext, pagination: Page) -> dict[str, Any]:
    return await operations.topic_agents(pagination)


@mcp_tool(
    "lab",
    name="lab_topic_person_list",
    description="List source interlocutors for a Topic experiment.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_topic_person_list(
    ctx: McpToolContext, agent_id: int, pagination: Page
) -> dict[str, Any]:
    return await operations.topic_people(agent_id, pagination)


@mcp_tool(
    "lab",
    name="lab_topic_messages_preview",
    description="Preview a bounded real message range before capture.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_topic_messages_preview(
    ctx: McpToolContext, data: TopicMessageRangeImport
) -> dict[str, Any]:
    return service.dump(await evaluations.preview_topic_message_range(data))


@mcp_tool(
    "lab",
    name="lab_topic_messages_import",
    description="Capture a complete message range as a Topic case; refuses truncated ranges.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=True)
async def lab_topic_messages_import(
    ctx: McpToolContext, dataset_id: UUID, data: TopicMessageRangeImport, invocation_key: str
) -> dict[str, Any]:
    return service.dump(await evaluations.import_topic_message_range(dataset_id, data))


@mcp_tool(
    "lab",
    name="lab_run_start",
    description="Start a durable benchmark immediately, freezing the dataset and models. Budget is a threshold between evaluations; repetitions range 1–20.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_run_start(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    revision: int,
    data: EvaluationRunStart,
    invocation_key: str,
) -> dict[str, Any]:
    await service.dataset(mechanism, dataset_id, revision)
    return await service.run_actor(
        ctx, mechanism, await evaluations.start_run(mechanism, dataset_id, data), "lab_run_start"
    )


@mcp_tool("lab", name="lab_run_list", description="List benchmark runs.", effect_policy="read")
@lab_call(mutation=False, sources=False)
async def lab_run_list(
    ctx: McpToolContext, mechanism: EvaluationMechanism, dataset_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await service.runs(mechanism, dataset_id, pagination)


@mcp_tool(
    "lab",
    name="lab_run_get",
    description="Inspect run status, two-pass progress, costs, configuration and errors. Results are paginated separately.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_run_get(
    ctx: McpToolContext, mechanism: EvaluationMechanism, run_id: UUID
) -> dict[str, Any]:
    return service.dump(EvaluationRunRead.model_validate(await service.run(mechanism, run_id)))


@mcp_tool(
    "lab",
    name="lab_run_results",
    description="Read candidate outputs, objective checks and automatic judgments by page.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_run_results(
    ctx: McpToolContext, mechanism: EvaluationMechanism, run_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await service.results(mechanism, run_id, pagination)


@mcp_tool(
    "lab",
    name="lab_run_cancel",
    description="Request benchmark cancellation; in-flight inference may still finish.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_run_cancel(
    ctx: McpToolContext, mechanism: EvaluationMechanism, run_id: UUID, invocation_key: str
) -> dict[str, Any]:
    return service.dump(await evaluations.cancel_run(mechanism, run_id))


@mcp_tool(
    "lab",
    name="lab_run_resume",
    description="Resume a cancelled benchmark's missing publications without repeating saved results.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_run_resume(
    ctx: McpToolContext, mechanism: EvaluationMechanism, run_id: UUID, invocation_key: str
) -> dict[str, Any]:
    return await service.run_actor(
        ctx, mechanism, await judgment_service.resume(mechanism, run_id), "lab_run_resume"
    )


@mcp_tool(
    "lab",
    name="lab_run_rejudge",
    description="Create a new judgment campaign over saved outputs, without rerunning candidates.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_run_rejudge(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    run_id: UUID,
    invocation_key: str,
    data: EvaluationRejudge,
) -> dict[str, Any]:
    return await service.run_actor(
        ctx, mechanism, await judgment_service.rejudge(mechanism, run_id, data), "lab_run_rejudge"
    )


@mcp_tool(
    "lab",
    name="lab_run_delete",
    description="Delete a terminal benchmark only after checking its observed status.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_run_delete(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    run_id: UUID,
    invocation_key: str,
    expected_status: str,
) -> dict[str, Any]:
    row = await service.run(mechanism, run_id)
    if row.status != expected_status:
        raise ValueError("Run status changed; read the run again.")
    await evaluations.delete_run(mechanism, run_id)
    return {"deleted": True, "run_id": str(run_id)}


@mcp_tool(
    "lab",
    name="lab_campaign_list",
    description="List independent judgment campaigns, preserving previous judges.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_campaign_list(
    ctx: McpToolContext, mechanism: EvaluationMechanism, run_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await service.campaigns(mechanism, run_id, pagination)


@mcp_tool(
    "lab",
    name="lab_campaign_get",
    description="Read a campaign and its paginated judgments.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_campaign_get(
    ctx: McpToolContext, mechanism: EvaluationMechanism, campaign_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await service.campaign_detail(mechanism, campaign_id, pagination)


@mcp_tool(
    "lab",
    name="lab_run_compare",
    description="Compare frozen experiments and per-case results; explicitly report incomparable corpus/context/judge changes.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_run_compare(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    left_run_id: UUID,
    right_run_id: UUID,
    axis: Literal["model", "prompt", "parameters"],
    pagination: Page,
) -> dict[str, Any]:
    return await service.compare(mechanism, left_run_id, right_run_id, axis, pagination)


@mcp_tool(
    "lab",
    name="lab_dataset_generate",
    description="Generate a synthetic draft dataset asynchronously. Returns an operation_id; inspect lab_operation_get.",
    effect_policy="idempotent",
)
@lab_call(mutation=False, sources=False)
async def lab_dataset_generate(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    data: SyntheticDatasetRequest,
    invocation_key: str,
) -> dict[str, Any]:
    return await operations.start(
        ctx, "lab_dataset_generate", mechanism, data.model_dump(mode="json"), invocation_key
    )


@mcp_tool(
    "lab",
    name="lab_expected_generate",
    description="Propose a case reference asynchronously; it is not automatically accepted as truth.",
    effect_policy="idempotent",
)
@lab_call(mutation=False, sources=False)
async def lab_expected_generate(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    case_id: UUID,
    revision: int,
    data: MechanismExpectedGenerate,
    invocation_key: str,
) -> dict[str, Any]:
    return await operations.start(
        ctx,
        "lab_expected_generate",
        mechanism,
        {"case_id": str(case_id), "revision": revision, "request": data.model_dump(mode="json")},
        invocation_key,
    )


@mcp_tool(
    "lab",
    name="lab_run_analyze",
    description="Analyze a terminal benchmark asynchronously; analysis cost is separate from its run budget.",
    effect_policy="idempotent",
)
@lab_call(mutation=False, sources=False)
async def lab_run_analyze(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    run_id: UUID,
    data: EvaluationRunAnalysisRequest,
    invocation_key: str,
) -> dict[str, Any]:
    return await operations.start(
        ctx,
        "lab_run_analyze",
        mechanism,
        {"run_id": str(run_id), "request": data.model_dump(mode="json")},
        invocation_key,
    )


@mcp_tool(
    "lab",
    name="lab_task_analyze",
    description="Analyze a registered Task asynchronously using real evidence. Requires galaris_admin.",
    effect_policy="idempotent",
)
@lab_call(mutation=False, sources=True)
async def lab_task_analyze(
    ctx: McpToolContext, task_id: UUID, data: TaskAnalysisRequest, invocation_key: str
) -> dict[str, Any]:
    return await operations.start(
        ctx,
        "lab_task_analyze",
        "task_analysis",
        {"task_id": str(task_id), "request": data.model_dump(mode="json")},
        invocation_key,
    )


@mcp_tool(
    "lab",
    name="lab_operation_get",
    description="Poll an asynchronous Lab Process and read its complete durable result by character pages.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_operation_get(
    ctx: McpToolContext, operation_id: UUID, offset: int = 0, length: int = 50000
) -> dict[str, Any]:
    return await operations.get(ctx, operation_id, offset, length)


@mcp_tool(
    "lab",
    name="lab_operation_cancel",
    description="Cancel a queued operation or request cancellation of in-flight work; never assume the provider stopped.",
    effect_policy="idempotent",
)
@lab_call(mutation=False, sources=False)
async def lab_operation_cancel(ctx: McpToolContext, operation_id: UUID) -> dict[str, Any]:
    return await operations.cancel(ctx, operation_id)


@mcp_tool(
    "lab",
    name="lab_task_candidates",
    description="Discover registered Lab Tasks or available Task evidence, with pagination.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_task_candidates(
    ctx: McpToolContext, pagination: Page, search: str | None = None
) -> dict[str, Any]:
    return await operations.tasks(pagination, search, registered=False)


@mcp_tool(
    "lab",
    name="lab_task_list",
    description="Discover registered Lab Tasks or available Task evidence, with pagination.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_task_list(
    ctx: McpToolContext, pagination: Page, search: str | None = None
) -> dict[str, Any]:
    return await operations.tasks(pagination, search, registered=True)


@mcp_tool(
    "lab",
    name="lab_task_add",
    description="Register an existing Task for diagnosis; does not execute the Task.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=True)
async def lab_task_add(ctx: McpToolContext, task_id: UUID, invocation_key: str) -> dict[str, Any]:
    result = service.dump(await evaluation_service.add_task(task_id))
    return {**result, "task_uri": f"galaris://task/{task_id}"}


@mcp_tool(
    "lab",
    name="lab_task_remove",
    description="Remove the Lab reference; retain the canonical Task and its diagnosis history.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=True)
async def lab_task_remove(
    ctx: McpToolContext, task_id: UUID, invocation_key: str
) -> dict[str, Any]:
    removed = await evaluation_service.remove_task(task_id)
    return {"removed": removed, "task_uri": f"galaris://task/{task_id}"}


@mcp_tool(
    "lab",
    name="lab_task_diagnoses",
    description="List immutable diagnoses for a real Task.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=True)
async def lab_task_diagnoses(
    ctx: McpToolContext, task_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await operations.diagnoses(task_id, pagination)


@mcp_tool(
    "lab",
    name="lab_review_list",
    description="List attributed agent assessments alongside distinctly labeled human reviews.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_review_list(
    ctx: McpToolContext, mechanism: EvaluationMechanism, campaign_id: UUID, pagination: Page
) -> dict[str, Any]:
    return await operations.reviews(mechanism, campaign_id, pagination)


@mcp_tool(
    "lab",
    name="lab_review_get",
    description="Read a candidate and frozen rubric for independent agent assessment; automatic judgment stays hidden until this agent submits.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_review_get(
    ctx: McpToolContext, mechanism: EvaluationMechanism, campaign_id: UUID, result_id: UUID
) -> dict[str, Any]:
    return await operations.review_input(ctx, mechanism, campaign_id, result_id)


@mcp_tool(
    "lab",
    name="lab_review_submit",
    description="Submit an immutable attributed agent assessment. Never writes a human review or changes the automatic score.",
    effect_policy="idempotent",
)
@lab_call(mutation=True, sources=False)
async def lab_review_submit(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    data: HumanReviewCreate,
    invocation_key: str,
) -> dict[str, Any]:
    return await service.submit_review(ctx, mechanism, data)


@mcp_tool(
    "lab",
    name="lab_content_read",
    description="Read oversized Lab JSON by character pages. Check the fingerprint stays identical across pages.",
    effect_policy="read",
)
@lab_call(mutation=False, sources=False)
async def lab_content_read(
    ctx: McpToolContext,
    mechanism: EvaluationMechanism,
    kind: Literal["case", "result", "run", "dataset", "campaign", "judgment", "review"],
    resource_id: UUID,
    offset: int = 0,
    length: int = 50000,
) -> dict[str, Any]:
    return await service.content(mechanism, kind, resource_id, offset, length)
