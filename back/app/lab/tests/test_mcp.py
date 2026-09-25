"""Agents operate canonical Lab experiments through the real MCP transport."""

from copy import deepcopy
from uuid import UUID, uuid4

from fastmcp import Client
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent import Agent
from app.task import TaskStatus
from app.agent.models import Title
from app.connection import Connection
from app.connection.models import ConnectionFunctionState
from app.tools import mandatory_tools, mcp_loader
from app.tools.models import Tool
from app.lab import mcp
from app.lab.contracts import CONTRACTS
from app.lab.mcp_schemas import DatasetPatch, CasePatch, Page
from app.lab.models import (
    LabCommand,
    LabEvaluationDataset,
    LabEvaluationCase,
    LabEvaluationRunCase,
    LabAgentReview,
)
from app.lab.schemas import (
    MechanismDatasetCreate,
    EvaluationCaseCreate,
    HumanReviewCreate,
    EvaluationRunStart,
)
from app.lab.tests.test_synthetic_datasets import generated_content
from app.lab.tests.test_stability_and_review import benchmark  # noqa: F401
from app.lab.mechanism_rubrics import get_rubric
from core.database import get_db_session
from core.user.models import User


async def provision(db):
    user = User(email=f"lab-{uuid4().hex}@example.test", hashed_password="unused")
    title = Title(label=f"Lab {uuid4().hex}", gender="X")
    db.add_all([user, title])
    await db.flush()
    agent = Agent(
        user_id=user.id,
        title_id=title.id,
        code=f"lab-{uuid4().hex}",
        first_name="Synthetic",
        last_name="Researcher",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    await mandatory_tools.sync_integrated_tool_connections(agent.id)
    connection = await db.scalar(
        select(Connection).join(Tool).where(Connection.agent_id == agent.id, Tool.code == "lab")
    )
    assert connection is not None and not connection.active
    connection.active = True
    await db.flush()
    return agent.id, connection.id


@pytest_asyncio.fixture
async def actor(db):
    identifier, connection_id = await provision(db)
    return mcp_loader.McpToolContext(identifier, "internal"), connection_id


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", list(CONTRACTS))
async def test_each_mechanism_can_be_authored_inspected_and_cloned(db, actor, mechanism):
    ctx, _ = actor
    descriptor = await mcp.lab_get(ctx, mechanism)
    assert descriptor["contract"]["key"] == mechanism
    dataset = await mcp.lab_dataset_create(
        ctx, mechanism, MechanismDatasetCreate(name=f"Experiment {mechanism}"), "create"
    )
    assert (
        await mcp.lab_dataset_create(
            ctx, mechanism, MechanismDatasetCreate(name=f"Experiment {mechanism}"), "create"
        )
        == dataset
    )
    content = generated_content(mechanism)
    case = await mcp.lab_case_create(
        ctx, mechanism, UUID(dataset["id"]), EvaluationCaseCreate(name="Synthetic case"), "case"
    )
    data = content.cases[0]
    edited = await mcp.lab_case_update(
        ctx,
        mechanism,
        UUID(case["id"]),
        CasePatch(
            revision=case["revision"],
            input_data=data.input_data,
            expected_output=data.expected_output,
            categories=data.categories,
        ),
        "edit",
    )
    assert edited["readiness"] == "ready"
    preview = await mcp.lab_input_preview(ctx, mechanism, UUID(dataset["id"]), data.input_data)
    assert preview["input"]["variable_value"] == data.input_data.variable_value
    copied = await mcp.lab_dataset_clone(
        ctx, mechanism, UUID(dataset["id"]), dataset["revision"], f"Variant {mechanism}", "clone"
    )
    assert copied["case_count"] == copied["ready_case_count"] == 1
    copied_case = (await mcp.lab_case_list(ctx, mechanism, UUID(copied["id"]), Page()))["items"][0]
    assert copied_case["derived_from_case_id"] == edited["id"]
    assert copied_case["input_data"] == edited["input_data"]
    with pytest.raises(Exception):
        await mcp.lab_dataset_create(
            ctx, mechanism, MechanismDatasetCreate(name="Other intention"), "create"
        )
    assert (
        await db.scalar(
            select(func.count(LabCommand.id)).where(LabCommand.agent_id == ctx.agent_id)
        )
        == 4
    )


@pytest.mark.asyncio
async def test_partial_edits_conflicts_and_function_revocation(db, actor):
    ctx, connection_id = actor
    dataset = await mcp.lab_dataset_create(
        ctx, "briefing", MechanismDatasetCreate(name="Holdout", purpose="holdout"), "create"
    )
    identifier = UUID(dataset["id"])
    edited = await mcp.lab_dataset_update(
        ctx,
        "briefing",
        identifier,
        DatasetPatch(revision=dataset["revision"], description="Preserved"),
        "edit",
    )
    assert edited["purpose"] == "holdout" and edited["parameters"] == dataset["parameters"]
    with pytest.raises(Exception, match="revision"):
        await mcp.lab_dataset_update(
            ctx,
            "briefing",
            identifier,
            DatasetPatch(revision=dataset["revision"], description="stale"),
            "stale",
        )
    db.add(
        ConnectionFunctionState(
            connection_id=connection_id, function_name="lab_dataset_delete", enabled=False
        )
    )
    await db.flush()
    with pytest.raises(PermissionError):
        await mcp.lab_dataset_delete(ctx, "briefing", identifier, edited["revision"], "delete")
    assert (await mcp.lab_dataset_get(ctx, "briefing", identifier))["description"] == "Preserved"
    with pytest.raises(PermissionError):
        await mcp.lab_task_candidates(ctx, Page())


@pytest.mark.asyncio
async def test_sql_pagination_does_not_lose_cases_after_500(db, actor):
    ctx, _ = actor
    dataset = await mcp.lab_dataset_create(
        ctx, "briefing", MechanismDatasetCreate(name="Paged"), "create"
    )
    identifier = UUID(dataset["id"])
    db.add_all(
        [
            LabEvaluationCase(dataset_id=identifier, name=f"Case {number}", readiness="draft")
            for number in range(503)
        ]
    )
    await db.flush()
    first = await mcp.lab_case_list(ctx, "briefing", identifier, Page(limit=500))
    second = await mcp.lab_case_list(
        ctx, "briefing", identifier, Page(limit=500, offset=first["next_offset"])
    )
    assert len(first["items"]) == 500 and len(second["items"]) == 3
    assert second["next_offset"] is None
    assert len({item["id"] for item in first["items"] + second["items"]}) == 503


@pytest.mark.asyncio
async def test_mounted_mcp_rechecks_grants_and_keeps_canonical_objects(committed_database):
    async with get_db_session() as db:
        identifier, connection_id = await provision(db)
    async with get_db_session():
        server = await mcp_loader.build_agent_galaris_fastmcp(identifier, runtime="internal")
    async with Client(server) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert {"lab_run_start", "lab_dataset_generate", "lab_review_submit"} <= tools
        args = {
            "mechanism": "dispatcher",
            "data": {"name": f"MCP {uuid4().hex}"},
            "invocation_key": "first",
        }
        created = await client.call_tool("lab_dataset_create", args)
        again = await client.call_tool("lab_dataset_create", args)
        assert not created.is_error and created.data == again.data
        async with get_db_session() as db:
            assert (
                await db.scalar(
                    select(func.count(LabEvaluationDataset.id)).where(
                        LabEvaluationDataset.name == args["data"]["name"]
                    )
                )
                == 1
            )
            (await db.get(Connection, connection_id)).active = False
        denied = await client.call_tool("lab_dataset_create", args, raise_on_error=False)
        assert denied.is_error


@pytest.mark.asyncio
async def test_run_rejudge_and_agent_review_preserve_candidate_and_human_identity(
    db, actor, benchmark
):
    from app.lab import mechanism_evaluation_service as evaluations
    from app.lab.schemas import EvaluationRejudge

    ctx, _ = actor
    dataset, llm, calls = benchmark
    started = await mcp.lab_run_start(
        ctx, "briefing", dataset.id, dataset.revision, EvaluationRunStart(llm_id=llm.id), "run"
    )
    run_id = UUID(started["id"])
    await db.commit()
    for _ in range(6):
        await evaluations.process_runs()
    result = (await mcp.lab_run_results(ctx, "briefing", run_id, Page()))["items"][0]
    campaigns = (await mcp.lab_campaign_list(ctx, "briefing", run_id, Page()))["items"]
    campaign_id = UUID(campaigns[0]["id"])
    blind = await mcp.lab_review_get(ctx, "briefing", campaign_id, UUID(result["id"]))
    assert "automatic_judgment" not in blind
    review = await mcp.lab_review_submit(
        ctx,
        "briefing",
        HumanReviewCreate(
            result_id=UUID(result["id"]),
            campaign_id=campaign_id,
            dimensions=[
                {"code": dim.code, "score_percent": 80, "assessment": "Supported by evidence"}
                for dim in get_rubric("briefing").dimensions
            ],
            explanation="Synthetic review",
        ),
        "review",
    )
    assert review["author_kind"] == "agent" and review["agent_id"] == ctx.agent_id
    assert await db.scalar(select(func.count(LabAgentReview.id))) == 1
    displayed = await evaluations.get_run("briefing", run_id)
    assert displayed.agent_reviews[0].agent_id == ctx.agent_id
    assert str(displayed.agent_reviews[0].campaign_id) == review["campaign_id"]
    snapshot = deepcopy((await db.get(LabEvaluationRunCase, UUID(result["id"]))).actual_output)
    candidate_calls = calls.count("candidate")
    await mcp.lab_run_rejudge(
        ctx, "briefing", run_id, "rejudge", EvaluationRejudge(judge_llm_id=llm.id)
    )
    await db.commit()
    for _ in range(4):
        await evaluations.process_runs()
    assert calls.count("candidate") == candidate_calls
    assert (await db.get(LabEvaluationRunCase, UUID(result["id"]))).actual_output == snapshot


@pytest.mark.asyncio
async def test_command_failure_rolls_back_effect_and_receipt(committed_database):
    async with get_db_session() as db:
        identifier, _ = await provision(db)
    name = f"rollback-{uuid4()}"
    with pytest.raises(RuntimeError):
        async with get_db_session():
            await mcp.lab_dataset_create(
                mcp_loader.McpToolContext(identifier, "internal"),
                "briefing",
                MechanismDatasetCreate(name=name),
                "rollback",
            )
            raise RuntimeError("Caller did not complete")
    async with get_db_session() as db:
        assert (
            await db.scalar(
                select(func.count(LabEvaluationDataset.id)).where(LabEvaluationDataset.name == name)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(LabCommand.id)).where(LabCommand.agent_id == identifier)
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["success", "revoked_before", "revoked_during", "cancelled", "provider_error"]
)
async def test_async_generation_is_durable_and_never_rebills_on_retry(
    db, actor, benchmark, monkeypatch, outcome
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.lab import synthetic_service
    from app.lab.models import LabOperationResult
    from app.lab.synthetic_schemas import SyntheticDatasetRequest
    from app.process import ProcessRun, process_service

    ctx, connection_id = actor
    _, llm, _ = benchmark
    name = f"Generated {uuid4()}"
    request = SyntheticDatasetRequest(name=name, count=1, categories=["nominal"], llm_id=llm.id)

    async def infer(**kwargs):
        if outcome == "provider_error":
            raise RuntimeError("Synthetic provider failure")
        if outcome == "revoked_during":
            (await db.get(Connection, connection_id)).active = False
            await db.flush()
        return SimpleNamespace(output=generated_content("briefing"), cost=0.012)

    inference = AsyncMock(side_effect=infer)
    monkeypatch.setattr(synthetic_service, "run_structured", inference)
    first = await mcp.lab_dataset_generate(ctx, "briefing", request, "generation")
    repeat = await mcp.lab_dataset_generate(ctx, "briefing", request, "generation")
    assert first["operation_id"] == repeat["operation_id"]
    identifier = UUID(first["operation_id"])
    assert inference.await_count == 0
    if outcome == "revoked_before":
        (await db.get(Connection, connection_id)).active = False
        await db.commit()
    if outcome == "cancelled":
        await mcp.lab_operation_cancel(ctx, identifier)
    await process_service.refresh_run(identifier)
    await process_service.refresh_run(identifier)
    saved = await db.get(ProcessRun, identifier)
    assert saved.status == (
        "success" if outcome == "success" else "cancelled" if outcome == "cancelled" else "error"
    )
    assert inference.await_count == (0 if outcome in {"cancelled", "revoked_before"} else 1)
    generated = await db.scalar(
        select(LabEvaluationDataset).where(LabEvaluationDataset.name == name)
    )
    receipt = await db.scalar(
        select(LabOperationResult).where(LabOperationResult.process_run_id == identifier)
    )
    if outcome == "success":
        assert generated is not None and receipt is not None
        result = await mcp.lab_operation_get(ctx, identifier)
        assert result["result"]["dataset"]["id"] == str(generated.id)
        assert result["result"]["dataset"]["ready_case_count"] == 0
        assert (await mcp.lab_dataset_generate(ctx, "briefing", request, "generation"))[
            "operation_id"
        ] == str(identifier)
        with pytest.raises(ValueError, match="different arguments"):
            await mcp.lab_dataset_generate(
                ctx, "briefing", request.model_copy(update={"name": "Changed"}), "generation"
            )
    else:
        assert generated is None and receipt is None


@pytest.mark.asyncio
async def test_revoked_run_is_stopped_before_candidate_inference(db, actor, benchmark):
    from app.lab import mechanism_evaluation_service as evaluations

    ctx, connection_id = actor
    dataset, llm, calls = benchmark
    result = await mcp.lab_run_start(
        ctx, "briefing", dataset.id, dataset.revision, EvaluationRunStart(llm_id=llm.id), "run"
    )
    (await db.get(Connection, connection_id)).active = False
    await db.commit()
    await evaluations.process_runs()
    stopped = await evaluations.get_run("briefing", UUID(result["id"]))
    assert stopped.status == "cancelled" and stopped.stop_reason == "authorization_revoked"
    assert calls == []


@pytest.mark.asyncio
async def test_comparison_identifies_prompt_treatment_and_ambiguous_evidence(db, actor, benchmark):
    from app.lab import mechanism_evaluation_service as evaluations

    ctx, _ = actor
    dataset, llm, _ = benchmark
    left = await mcp.lab_run_start(
        ctx, "briefing", dataset.id, dataset.revision, EvaluationRunStart(llm_id=llm.id), "baseline"
    )
    copy = await mcp.lab_dataset_clone(
        ctx, "briefing", dataset.id, dataset.revision, "Prompt variant", "variant"
    )
    changed = await mcp.lab_dataset_update(
        ctx,
        "briefing",
        UUID(copy["id"]),
        DatasetPatch(
            revision=copy["revision"],
            configuration={
                **copy["configuration"],
                "system_prompt": "Use the provided evidence carefully.",
            },
        ),
        "prompt",
    )
    right = await mcp.lab_run_start(
        ctx,
        "briefing",
        UUID(copy["id"]),
        changed["revision"],
        EvaluationRunStart(llm_id=llm.id),
        "variant-run",
    )
    await db.commit()
    for _ in range(6):
        await evaluations.process_runs()
    compared = await mcp.lab_run_compare(
        ctx, "briefing", UUID(left["id"]), UUID(right["id"]), "prompt", Page()
    )
    assert compared["comparable"] and compared["items"][0]["pairing"] == "matched"
    assert compared["items"][0]["score_delta"] == 0
    assert not (
        await mcp.lab_run_compare(
            ctx, "briefing", UUID(left["id"]), UUID(right["id"]), "model", Page()
        )
    )["comparable"]
    original = await db.get(LabEvaluationRunCase, UUID(compared["items"][0]["right_result_id"]))
    db.add(
        LabEvaluationRunCase(
            run_id=original.run_id,
            repetition=original.repetition,
            case_snapshot=original.case_snapshot,
            actual_output=original.actual_output,
            score_details=original.score_details,
            structured_score_percent=0,
        )
    )
    await db.flush()
    ambiguous = await mcp.lab_run_compare(
        ctx, "briefing", UUID(left["id"]), UUID(right["id"]), "prompt", Page()
    )
    assert "ambiguous_case_pairing" in ambiguous["blockers"]


@pytest.mark.asyncio
async def test_lab_skill_is_opt_in_and_projected_for_both_drivers(db, actor):
    from app.skill import skill_service, storage, build_skill_projection, build_skill_prompt
    from bridge.hermes.skill_sync import collect_managed_files

    ctx, _ = actor
    await skill_service.sync_from_disk()
    skill = await skill_service.get_by_code("galaris-lab")
    assert skill is not None and skill.system and not skill.global_enabled
    assert "galaris-lab" not in await skill_service.get_assigned_codes(ctx.agent_id)
    await skill_service.set_agent_authorization(skill.id, ctx.agent_id, "enabled")
    snapshot = await build_skill_projection(ctx.agent_id)
    assert "galaris-lab" in snapshot.skill_codes
    assert storage.read_text("galaris-lab", "SKILL.md").strip() in await build_skill_prompt(
        ctx.agent_id
    )
    assert "data/skills/galaris/galaris-lab/SKILL.md" in collect_managed_files(
        list(snapshot.skill_codes)
    )
    await skill_service.set_agent_authorization(skill.id, ctx.agent_id, "disabled")
    assert "galaris-lab" not in (await build_skill_projection(ctx.agent_id)).skill_codes


@pytest.mark.asyncio
async def test_capture_confirmation_survives_real_mcp_and_requires_source_access(
    committed_database,
):
    import re
    from app.llm import LLMCall
    from app.task import Task

    async with get_db_session() as db:
        agent_id, _ = await provision(db)
        ctx = mcp_loader.McpToolContext(agent_id, "internal")
        dataset = await mcp.lab_dataset_create(
            ctx, "briefing", MechanismDatasetCreate(name=f"Capture {uuid4()}"), "capture-dataset"
        )
        task = Task(label="Synthetic observatory report", status="SUCCESS")
        db.add(task)
        await db.flush()
        call = LLMCall(
            task_id=task.id,
            provider_name="test",
            requested_model="synthetic",
            effective_model="synthetic",
            status="completed",
            prompt="Task: prepare the observatory report",
            system_prompt="You prepare a concise execution briefing for another AI agent before a complex HIGH-effort task.",
            response_text="",
            tool_calls=[
                {
                    "id": "test-output",
                    "name": "final_result",
                    "arguments": generated_content("briefing").cases[0].expected_output,
                }
            ],
        )
        db.add(call)
        await db.flush()
        source_id = str(call.id)
    async with get_db_session():
        server = await mcp_loader.build_agent_galaris_fastmcp(agent_id, runtime="internal")
    args = {
        "mechanism": "briefing",
        "dataset_id": dataset["id"],
        "data": {"source_kind": "llm_call", "source_id": source_id},
        "invocation_key": "capture",
    }
    async with Client(server) as client:
        denied = await client.call_tool("lab_case_import", args, raise_on_error=False)
        assert denied.is_error
        async with get_db_session() as db:
            admin = await db.scalar(
                select(Connection)
                .join(Tool)
                .where(Connection.agent_id == agent_id, Tool.code == "galaris_admin")
            )
            admin.active = True
        conflict = await client.call_tool("lab_case_import", args, raise_on_error=False)
        assert conflict.is_error
        text = " ".join(item.text for item in conflict.content if hasattr(item, "text"))
        match = re.search(r'"confirmation_token":\s*"([a-f0-9]{64})"', text)
        assert match, text
        args["data"]["confirmation_token"] = match.group(1)
        imported = await client.call_tool("lab_case_import", args)
        assert imported.data["readiness"] == "draft"
        assert imported.data["source_capture"]


@pytest.mark.asyncio
async def test_async_reference_and_analysis_keep_results_canonical(db, actor, benchmark, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.lab import mechanism_evaluation_service as evaluations, mechanism_registry
    from app.lab.schemas import MechanismExpectedGenerate, EvaluationRunAnalysisRequest, BenchmarkAnalysisContent
    from app.process import process_service
    ctx, _ = actor
    dataset, llm, _ = benchmark
    monkeypatch.setattr(evaluations.llm_service, "get_profile_llm_for_agent_id", AsyncMock(return_value=llm))
    async def infer(**kwargs):
        return SimpleNamespace(output=kwargs["output_type"].model_validate(generated_content("briefing").cases[0].expected_output), cost=0.01)
    monkeypatch.setattr(mechanism_registry, "run_structured", infer)
    case = (await mcp.lab_case_list(ctx, "briefing", dataset.id, Page()))["items"][0]
    operation = await mcp.lab_expected_generate(ctx, "briefing", UUID(case["id"]), case["revision"], MechanismExpectedGenerate(), "reference")
    await process_service.refresh_run(UUID(operation["operation_id"]))
    proposal = await mcp.lab_operation_get(ctx, UUID(operation["operation_id"]))
    assert proposal["status"] == "success", proposal
    assert proposal["result"]["cost"] == 0.01
    assert (await mcp.lab_case_get(ctx, "briefing", UUID(case["id"])))["expected_output"] == case["expected_output"]
    started = await mcp.lab_run_start(ctx, "briefing", dataset.id, dataset.revision, EvaluationRunStart(llm_id=llm.id), "analyzed-run")
    await db.commit()
    for _ in range(3):
        await evaluations.process_runs()
    monkeypatch.setattr(evaluations, "run_structured", AsyncMock(return_value=SimpleNamespace(output=BenchmarkAnalysisContent(
        summary="Evidence supports the result.", case_analyses=[{"case_name": "Report", "assessment": "Supported"}], conclusion="Retain the baseline."), cost=0.02)))
    analysis = await mcp.lab_run_analyze(ctx, "briefing", UUID(started["id"]), EvaluationRunAnalysisRequest(language="en"), "analysis")
    await process_service.refresh_run(UUID(analysis["operation_id"]))
    result = await mcp.lab_operation_get(ctx, UUID(analysis["operation_id"]))
    assert result["status"] == "success", result
    displayed = await evaluations.get_run("briefing", UUID(started["id"]))
    assert displayed.analysis_cost == 0.02 and "Retain the baseline" in displayed.analysis_markdown


@pytest.mark.asyncio
async def test_async_task_diagnosis_uses_real_evidence_and_persisted_diagnosis(db, actor, benchmark, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.lab import analysis_service
    from app.lab.schemas import TaskAnalysisRequest, TaskAnalysisContent
    from app.task import Task
    from app.process import process_service
    ctx, _ = actor
    _, llm, _ = benchmark
    monkeypatch.setattr(analysis_service.llm_service, "get_profile_llm_for_agent_id", AsyncMock(return_value=llm))
    admin = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == ctx.agent_id, Tool.code == "galaris_admin"))
    admin.active = True
    task = Task(label="Synthetic diagnosis", objective="<p>Report observatory opening hours.</p>", status=TaskStatus.SUCCESS,
        execution_result={"success": True, "result": "Opens at nine."})
    db.add(task)
    await db.commit()
    await mcp.lab_task_add(ctx, task.id, "register")
    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass
        async def run(self, prompt):
            assert "Report observatory opening hours" in prompt
            return SimpleNamespace(output=TaskAnalysisContent(verdict="success", confidence=0.8, summary="Opening hours supplied.",
                goal_assessment="Objective met.", observed_outcome="Hours reported.", findings=[], root_causes=[], recommendations=[]))
    monkeypatch.setattr(analysis_service, "PydanticAgent", FakeAgent)
    monkeypatch.setattr(analysis_service, "build_model_for_llm", AsyncMock(return_value=object()))
    monkeypatch.setattr(analysis_service, "estimate_cost_from_usage", lambda *args: 0.02)
    operation = await mcp.lab_task_analyze(ctx, task.id, TaskAnalysisRequest(language="en", user_context="Check the available evidence."), "diagnosis")
    await process_service.refresh_run(UUID(operation["operation_id"]))
    result = await mcp.lab_operation_get(ctx, UUID(operation["operation_id"]))
    assert result["status"] == "success", result
    diagnoses = await mcp.lab_task_diagnoses(ctx, task.id, Page())
    assert diagnoses["items"][0]["summary"] == "Opening hours supplied."
    assert result["result"]["id"] == diagnoses["items"][0]["id"]
