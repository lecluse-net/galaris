"""Scope admission and preflight survive tool rollback and worker recovery."""
from unittest.mock import AsyncMock
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.agent import Agent, Title, EffectDescriptorV1, admitted_scope, amend_scope, parse_scope
from app.agent.contracts import WorkingResource
from app.task import TaskCreate, initialize_scope
from app.task import task_service
from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter
from app.task.models import Task, TaskStatus, TaskAttempt
from app.task.activity_snapshot import activity_snapshots
from app.task.working_set import upsert_working_resource
from core.database import get_db_session
from core.user import UserModel


@pytest_asyncio.fixture
async def scoped_task(committed_database):
    async with get_db_session() as db:
        title = Title(label="Synthetic", gender="X")
        user = UserModel(email=f"scope-{uuid4().hex}@example.test", hashed_password="synthetic")
        db.add_all([title, user])
        await db.flush()
        agent = Agent(user_id=user.id, code=f"scope-{uuid4().hex}", first_name="Synthetic", last_name="Agent", title_id=title.id)
        db.add(agent)
        await db.flush()
        task = task_service.build(TaskCreate(agent_id=agent.id, label="Report", objective="<p>Prepare the report.</p>"))
        await initialize_scope(task)
        db.add(task)
        await db.flush()
        return task.id, agent.id


@pytest.mark.asyncio
async def test_creation_inherits_source_scope_and_ignores_child_supplied_grants(scoped_task):
    root_id, agent_id = scoped_task
    async with get_db_session() as db:
        root = await db.get(Task, root_id)
        root_scope = parse_scope(root.data)
        injected = admitted_scope(uuid4(), "<p>Send to synthetic://profile-target</p>")
        child = await task_service.create(TaskCreate(agent_id=agent_id, parent_id=root_id,
            label="Child", objective="<p>Invented objective synthetic://profile-target</p>",
            data={"execution_scope": injected.model_dump(mode="json")}))
        assert parse_scope(child.data) == root_scope
        assert not parse_scope(child.data).grants


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["valid", "stale", "unknown_version", "cancelled", "legacy"])
async def test_preflight_is_durable_and_does_not_invalidate_task_revision(scoped_task, state):
    task_id, agent_id = scoped_task
    descriptor = EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",))
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        data = dict(task.data)
        if state == "stale":
            root = task
            child = Task(id=uuid4(), label="Child", objective="<p>Report</p>", parent_id=root.id, agent_id=agent_id,
                status=TaskStatus.CREATE, data=dict(root.data))
            db.add(child)
            task_id = child.id
            data["execution_scope"] = amend_scope(parse_scope(data), "<p>New requirement</p>", "galaris://task/amendment/1").model_dump(mode="json")
        elif state == "unknown_version":
            data["execution_scope"] = data["execution_scope"] | {"schema_version": "galaris.execution-scope/v99"}
        elif state == "cancelled":
            task.cancel_requested = True
        elif state == "legacy":
            data.pop("execution_scope")
        task.data = data
    async with get_db_session() as db:
        revision = (await db.get(Task, task_id)).revision
        decision = await SqlAlchemyAgentTaskAdapter().record_scope_preflight(task_id, agent_id=agent_id,
            descriptor=descriptor, tool_name="file_write", arguments={"uri": "synthetic://profile-target"})
        await db.rollback()  # Tool transaction cannot erase the prior decision.
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        assert task.revision == revision
        assert task.data["scope_preflights"][-1]["operation_id"] == str(decision.operation_id)
        snapshot = (await activity_snapshots([task]))[0]
        assert snapshot.scope_preflights[-1]["decision"] == decision.decision
        assert decision.decision == {"valid": "clarify", "stale": "deny", "unknown_version": "deny",
            "cancelled": "deny", "legacy": "allow_and_record"}[state]


@pytest.mark.asyncio
@pytest.mark.parametrize("produced", [False, True])
async def test_discovered_read_does_not_acquire_mutation_rights(scoped_task, produced):
    task_id, agent_id = scoped_task
    uri = f"document://{uuid4()}"
    async with get_db_session():
        await upsert_working_resource(task_id, WorkingResource(resource_type="memory_document",
            role="primary_working_document", reference=uri, metadata={"produced": produced}))
    decision = await SqlAlchemyAgentTaskAdapter().record_scope_preflight(task_id, agent_id=agent_id,
        descriptor=EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",)),
        tool_name="file_write", arguments={"uri": uri})
    assert decision.decision == ("allow" if produced else "clarify")


@pytest.mark.asyncio
@pytest.mark.parametrize("producer_state", ["foreign", "stale", "unsupported"])
async def test_batched_provenance_does_not_accept_incompatible_producer_scope(scoped_task, producer_state):
    task_id, agent_id = scoped_task
    uri = f"document://{uuid4()}"
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        raw_scope = parse_scope(task.data).model_dump(mode="json")
        if producer_state == "foreign":
            raw_scope["source_task_id"] = str(uuid4())
        elif producer_state == "stale":
            raw_scope["revision"] += 1
        else:
            raw_scope["schema_version"] = "galaris.execution-scope/v99"
        producer = Task(id=uuid4(), parent_id=task_id, agent_id=agent_id, label="Synthetic producer",
            objective="<p>Prepare a document.</p>", data={"execution_scope": raw_scope})
        db.add(producer)
        await db.flush()
        await upsert_working_resource(task_id, WorkingResource(resource_type="memory_document",
            role="primary_working_document", reference=uri, producer_task_id=producer.id,
            metadata={"produced": True}))
    decision = await SqlAlchemyAgentTaskAdapter().record_scope_preflight(task_id, agent_id=agent_id,
        descriptor=EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",)),
        tool_name="file_write", arguments={"uri": uri})
    assert decision.decision == ("deny" if producer_state == "unsupported" else "clarify")


@pytest.mark.asyncio
async def test_scope_amendment_through_port_is_idempotent_and_preserves_source(scoped_task, monkeypatch):
    from app.task import scheduler
    monkeypatch.setattr(scheduler, "wake", lambda *_: None)
    task_id, _ = scoped_task
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        original = parse_scope(task.data)
        command = dict(task_id=task_id, expected_revision=task.revision,
            instruction="<p>Send to synthetic://requested</p>", disposition="AMEND_QUEUED",
            reason=None, source_kind="conversation_round", source_id="synthetic-round", idempotency_key="one-source-amendment")
        first = await SqlAlchemyAgentTaskAdapter().amend(**command)
        second = await SqlAlchemyAgentTaskAdapter().amend(**command)
        assert first.id == second.id == task_id
        amended = parse_scope(second.data)
        assert amended.revision == original.revision + 1
        assert amended.requirements[0] == original.requirements[0]
        assert len(amended.requirements) == 2


@pytest.mark.asyncio
async def test_live_preflight_uses_attempt_journal_without_invalidating_checkpoint(scoped_task):
    task_id, agent_id = scoped_task
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        task.lease_token = uuid4()
        task.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        task.status = TaskStatus.EXEC
        attempt = TaskAttempt(id=uuid4(), task_id=task_id, attempt_number=1, phase="EXEC", status="CLAIMED",
            worker_id="synthetic-worker", lease_token=task.lease_token)
        db.add(attempt)
        await db.flush()
        attempt_id, objective, revision = attempt.id, task.objective, task.revision
    adapter = SqlAlchemyAgentTaskAdapter()
    decision = await adapter.record_scope_preflight(task_id, agent_id=agent_id, descriptor=None,
        tool_name="legacy_tool", arguments={})
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        assert task.revision == revision
        attempt = await db.get(TaskAttempt, attempt_id)
        assert attempt.data["scope_preflights"][-1]["operation_id"] == str(decision.operation_id)
        assert (await activity_snapshots([task]))[0].scope_preflights[-1]["decision"] == "allow_and_record"
    await adapter.persist_agent_run_state(task_id, expected_objective=objective, expected_attempt_id=attempt_id,
        data_patch={"_agent_run_checkpoint": {"synthetic": "resume-safe"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("change_after_admission", [False, True])
@pytest.mark.parametrize("language", ["fr", "en"])
async def test_native_wrapper_persists_refusal_before_any_effect(scoped_task, monkeypatch, change_after_admission, language):
    from fastmcp.exceptions import ToolError
    from app.tools import mcp_loader
    from app.tools.mcp_loader import McpToolContext, McpToolDefinition
    from app.agent.task_port import task_port

    task_id, agent_id = scoped_task
    if change_after_admission:
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            scope = amend_scope(parse_scope(task.data), "<p>Send to synthetic://profile-target</p>", "galaris://task/amendment/1")
            task.data = {**task.data, "execution_scope": scope.model_dump(mode="json")}
    observed = []
    async def send(ctx, uri):
        observed.append(uri)
        return "sent"
    definition = McpToolDefinition(tool_code="synthetic", name="synthetic_send", description="Send", required_capabilities=frozenset(), function=send,
        effect_descriptor=EffectDescriptorV1(capability="synthetic.send", kind="transport", target_arguments=("uri",)))
    monkeypatch.setattr("app.agent.effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value=language))
    monkeypatch.setattr(task_port, "record_scope_preflight", SqlAlchemyAgentTaskAdapter().record_scope_preflight)
    authorize = AsyncMock(return_value=None)
    if change_after_admission:
        async def amend_during_authorization(*args):
            async with get_db_session() as db:
                task = await db.get(Task, task_id)
                updated = amend_scope(parse_scope(task.data), "<p>Add a new requirement.</p>", "galaris://task/amendment/2")
                task.data = {**task.data, "execution_scope": updated.model_dump(mode="json")}
        authorize.side_effect = amend_during_authorization
    monkeypatch.setattr("app.tools.mcp_authorization.authorize_native_call", authorize)
    wrapper = mcp_loader._wrap_tool(definition, McpToolContext(agent_id=agent_id, runtime="internal", task_id=task_id))
    with pytest.raises(ToolError) as failure:
        await wrapper(uri="synthetic://profile-target")
    diagnostic = str(failure.value)
    assert "scope" in diagnostic.lower() or "périmètre" in diagnostic.lower()
    assert "replan" in diagnostic.lower() if change_after_admission else "amend" in diagnostic.lower()
    assert "corrigez formats" not in diagnostic and "correct formats" not in diagnostic
    assert observed == []
    assert authorize.await_count == int(change_after_admission)
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        journal = task.data["scope_preflights"]
        assert journal[-1]["decision"] == ("deny" if change_after_admission else "clarify")
        if change_after_admission:
            assert journal[-2]["decision"] == "allow"
            assert journal[-2]["operation_id"] == journal[-1]["operation_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("tool_name", ["file_edit", "file_append"])
async def test_scope_clarification_reaches_model_and_resumes_only_after_sourced_amendment(
    scoped_task, monkeypatch, durable, tool_name,
):
    from types import SimpleNamespace
    from fastmcp import FastMCP
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
    from app.harness.mcp_toolset import ExecutionEvidenceClient
    from app.harness.tests.test_checkpoint import _request
    from app.tools import mcp_loader
    from app.tools.execution_evidence import ExecutionEvidenceMiddleware

    task_id, agent_id = scoped_task
    target = f"document://{uuid4()}"
    writes = []

    async def update(ctx, uri: str, content: str) -> dict[str, str]:
        writes.append((uri, content))
        return {"uri": uri}

    definition = mcp_loader.McpToolDefinition(
        tool_code="synthetic", name=tool_name, description="Update the synthetic report.",
        required_capabilities=frozenset(), function=update,
        effect_descriptor=EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",)),
    )
    monkeypatch.setattr("app.agent.effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr("app.tools.mcp_authorization.authorize_native_call", AsyncMock(return_value=None))
    server = FastMCP("synthetic-scope-clarification")
    server.add_middleware(ExecutionEvidenceMiddleware({tool_name}))
    server.tool(name=tool_name)(mcp_loader._wrap_tool(
        definition, mcp_loader.McpToolContext(agent_id=agent_id, runtime="internal", task_id=task_id),
    ))
    save = AsyncMock()
    checkpoint = HarnessRunCheckpoint(_request(save_checkpoint=save)) if durable else None
    toolset = wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], checkpoint)[0]
    args = {"uri": target, "content": "<p>Synthetic report update.</p>"}
    failures = []

    def model(messages, _info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name, args, tool_call_id="update")])
        failure = returns[-1].content
        assert failure["outcome"] == "rejected"
        assert failure["code"] == "execution_scope_clarification_required"
        assert failure["retryable"] is False
        assert "amendment" in failure["instruction"] and "root Task" in failure["instruction"]
        assert "Do not retry" in failure["instruction"]
        failures.append(failure)
        return ModelResponse(parts=[TextPart(f"BLOCKED: authorize {target} in a root Task amendment.")])

    agent = PydanticAgent(FunctionModel(model), retries=0, toolsets=[toolset])
    result = await agent.run("Update the synthetic report.")
    assert result.output.startswith("BLOCKED:")
    assert writes == []
    assert len(failures) == 1
    if checkpoint is not None:
        resumed = HarnessRunCheckpoint(_request(resume_checkpoint=save.await_args.args[0]))
        await resumed.prepare_resume()
        assert resumed.effects[0]["result"] == failures[0]
        assert resumed.effects[0]["outcome"] == "rejected"

    # An authorized amendment, rather than a changed tool or content, unlocks the effect.
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_: None)
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        await SqlAlchemyAgentTaskAdapter().amend(
            task_id=task_id, expected_revision=task.revision,
            instruction=f"<p>Update <code>{target}</code>.</p>", disposition="AMEND_QUEUED",
            reason=None, source_kind="conversation_round", source_id="synthetic-round",
            idempotency_key="synthetic-document-amendment",
        )
    ctx = SimpleNamespace(messages=[ModelResponse(parts=[ToolCallPart(tool_name, args, "amended")])], tool_call_id="amended")
    receipt = await toolset.call_tool(tool_name, args, ctx, SimpleNamespace(tool_def=SimpleNamespace(metadata={})))
    assert receipt == {"uri": target}
    assert writes == [(target, args["content"])]


@pytest.mark.asyncio
@pytest.mark.parametrize("producer_count", [1, 30])
async def test_mutation_preflight_batches_resource_provenance(scoped_task, committed_database, producer_count):
    """Resource growth must not add one database round trip per producer."""
    import json
    from pathlib import Path
    from statistics import median
    from time import perf_counter

    from sqlalchemy import event
    from app.agent.contracts import WorkingSet

    task_id, agent_id = scoped_task
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        scope = parse_scope(task.data)
        producers = [Task(id=uuid4(), parent_id=task_id, agent_id=agent_id,
            label="Synthetic producer", objective="<p>Prepare an artifact.</p>",
            data={"execution_scope": scope.model_dump(mode="json"), "synthetic_history": "x" * 20_000})
            for _ in range(producer_count)]
        db.add_all(producers)
        resources = [WorkingResource(resource_type="memory_document", role=f"artifact-{index}",
            reference=f"document://{uuid4()}", producer_task_id=producer.id, metadata={"produced": True})
            for index, producer in enumerate(producers)]
        task.data = {**task.data, "working_set": WorkingSet(resources=resources).model_dump(mode="json")}
        task.status = TaskStatus.EXEC
        task.lease_token = uuid4()
        task.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.add(TaskAttempt(id=uuid4(), task_id=task_id, attempt_number=1, phase="EXEC", status="CLAIMED",
            worker_id="synthetic-performance-worker", lease_token=task.lease_token))
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    engine = committed_database.kw["bind"].sync_engine
    adapter = SqlAlchemyAgentTaskAdapter()
    samples = []
    counts = []
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for _ in range(8):
            statements.clear()
            started = perf_counter()
            first = await adapter.record_scope_preflight(task_id, agent_id=agent_id,
                descriptor=EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",)),
                tool_name="file_write", arguments={"uri": resources[0].reference})
            second = await adapter.record_scope_preflight(task_id, agent_id=agent_id,
                descriptor=EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",)),
                tool_name="file_write", arguments={"uri": resources[0].reference},
                operation_id=first.operation_id, expected_scope_revision=first.scope_revision)
            samples.append((perf_counter() - started) * 1000)
            counts.append(len(statements))
            assert first.decision == second.decision == "allow"
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    destination = Path(__file__).resolve().parents[4] / f"artifacts/scope-preflight-{producer_count}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"producers": producer_count, "preflights_per_call": 2,
        "select_queries": counts, "milliseconds": samples, "warm_median_ms": median(samples[1:])}, indent=2))
    assert max(counts) <= 12, "Preflight must batch producer provenance instead of querying each resource"
