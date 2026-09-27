"""Collections retain item boundaries even when the static plan budget is small."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.planner_contracts import Plan, PlanStep
from app.agent import planner_collection, planner_service
from app.agent.contracts import ExecutionResult, WorkingResource
from app.task import task_service, upsert_working_resource
from app.task.models import Task, TaskStatus
from app.task.workflow import TaskEvent, transition

# Reuse the real isolated Memory actors/storage for the end-to-end inventory workflow.
from app.memory.tests.conftest import agents, memory_storage  # noqa: F401


def collection_step() -> PlanStep:
    return PlanStep.model_validate({
        "label": "Workspace A",
        "objective": "<p>Convert each document faithfully, in order.</p>",
        "tools": ["file_read", "file_create"],
        "collection": {
            "inventory_objective": "<p>Read the existing index and identify remaining documents.</p>",
            "inventory_tools": ["file_read", "file_create"],
            "item_objective": "<p>Read, convert and verify only this document. Record its destination URI.</p>",
        },
    })


def test_repeated_work_is_preserved_as_a_collection() -> None:
    plan = Plan(steps=[collection_step()])
    assert plan.model_dump()["steps"][0]["collection"] is not None


def test_collection_cannot_silently_become_an_executable_leaf() -> None:
    data = collection_step().model_dump()
    data["steps"] = [{"label": "Hidden batch", "objective": "Convert all documents"}]
    with pytest.raises(ValidationError):
        PlanStep.model_validate(data)


@pytest.mark.parametrize("count", [None, 2, 118])
def test_multi_item_leaf_is_rejected(count) -> None:
    with pytest.raises(ValidationError, match="Repeated or unbounded"):
        PlanStep(label="Batch", objective="Convert the batch", item_count=count)


@pytest.mark.parametrize("count", [2, 3, 5])
def test_small_mechanical_batch_stays_one_leaf(count) -> None:
    step = PlanStep.model_validate({
        "label": "Rename known documents",
        "objective": "<p>Apply the supplied names to the listed documents and verify them.</p>",
        "item_count": count,
        "item_work": "mechanical",
    })
    assert step.item_count == count
    assert not step.steps and step.collection is None


@pytest.mark.parametrize("count", [None, 6, 118])
def test_mechanical_batch_cannot_hide_large_or_unknown_work(count) -> None:
    with pytest.raises(ValidationError, match="Repeated or unbounded"):
        PlanStep.model_validate({
            "label": "Batch", "objective": "<p>Rename the documents.</p>",
            "item_count": count, "item_work": "mechanical",
        })


def test_collection_inventory_tools_are_authorized_and_depth_is_not_flattened(monkeypatch) -> None:
    step = collection_step()
    step.collection.inventory_tools.append("external_list")
    assert "external_list" in planner_service._plan_tool_names(Plan(steps=[step]))
    monkeypatch.setattr(planner_service.runtime_settings, "TASK_PLAN_MAX_DEPTH", 1)
    with pytest.raises(ValueError, match="maximum depth"):
        planner_service._validate_plan_depth([step], 1)


def inventory(task_id, count=5):
    return {
        "schema_version": "galaris.collection/v1", "complete": True,
        "collection_task": f"galaris://task/{task_id}", "item_count": count,
        "items": [{"key": f"source-{i}", "label": f"Document {i}",
                   "inputs": {"source_uri": f"https://example.test/doc/{i}"}}
                  for i in range(count)],
    }


@pytest.mark.parametrize("defect", ["duplicate", "count", "incomplete", "oversized"])
def test_incomplete_or_ambiguous_inventory_is_rejected(defect) -> None:
    manifest = inventory(uuid4())
    if defect == "duplicate":
        manifest["items"][1]["key"] = manifest["items"][0]["key"]
    elif defect == "count":
        manifest["item_count"] += 1
    elif defect == "incomplete":
        manifest["complete"] = False
    else:
        manifest = inventory(uuid4(), planner_collection.MAX_COLLECTION_ITEMS + 1)
    with pytest.raises(ValidationError):
        planner_collection.CollectionInventory.model_validate(manifest)


async def complete(task, *, success=True, result="Verified item", cost=0.1):
    transition(task, TaskEvent.START_EXECUTION)
    transition(task, TaskEvent.EXECUTION_SUCCEEDED if success else TaskEvent.EXECUTION_FAILED)
    task.set_execution_result(ExecutionResult(prompt="", result=result, success=success))
    task.feedback = result
    task.cost = cost
    await task_service.save(task)


@pytest.mark.asyncio
async def test_small_mechanical_batch_executes_without_inventory_or_replanning(db, agents, monkeypatch) -> None:
    worker, _ = agents
    monkeypatch.setattr(planner_service, "go_next", MagicMock())
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    monkeypatch.setattr(planner_service, "require_agent_profile_model", AsyncMock(return_value=object()))
    monkeypatch.setattr(planner_service, "run_structured", AsyncMock(
        return_value=SimpleNamespace(output="Names verified", cost=0.0)))
    root = Task(label="Apply supplied names", objective="<p>Rename the three listed documents.</p>",
                agent_id=worker.id, status=TaskStatus.PLAN, cost=0.0)
    db.add(root)
    await db.commit()
    plan = Plan(steps=[PlanStep(
        label="Rename documents", objective=root.objective, item_count=3, item_work="mechanical",
    )])
    build = AsyncMock(return_value=(plan, 0.0, ""))
    monkeypatch.setattr(planner_service, "_build_plan", build)
    await planner_service.advance(root)
    leaf, = await task_service.get_children(root.id)
    assert leaf.status == TaskStatus.DISPATCH and not leaf.paused
    assert not leaf.plan
    assert not await task_service.get_children(leaf.id)
    await complete(leaf, result="All supplied names applied and verified")
    await planner_service.advance(root)
    assert root.status == TaskStatus.SUCCESS
    assert [child.id for child in await task_service.get_children(root.id)] == [leaf.id]
    build.assert_awaited_once()


@pytest.mark.asyncio
async def test_collection_journey_survives_restart_and_retries_only_failed_items(
    db, agents, memory_storage, monkeypatch,
) -> None:
    from app.file_share import ResourceContext, resource_create, resource_write

    worker, _ = agents
    monkeypatch.setattr(planner_service.runtime_settings, "TASK_PLAN_MAX_LEAVES", 2)
    monkeypatch.setattr(planner_service, "go_next", MagicMock())
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    monkeypatch.setattr(planner_service, "require_agent_profile_model", AsyncMock(return_value=object()))
    monkeypatch.setattr(planner_service, "run_structured", AsyncMock(
        return_value=SimpleNamespace(output="Verified collection", cost=0.0)))
    root = Task(label="Convert ordered workspaces", objective="<p>Create a document per source.</p>",
                agent_id=worker.id, status=TaskStatus.PLAN, cost=0.0)
    db.add(root)
    await db.commit()
    root_id = root.id
    plan = Plan(steps=[collection_step(), PlanStep(label="Reconcile links", objective="<p>Check cross-item links.</p>")])
    monkeypatch.setattr(planner_service, "_build_plan", AsyncMock(return_value=(plan, 0.0, "")))
    await planner_service.advance(root)
    group, final = sorted(await task_service.get_children(root.id), key=lambda t: t.data["plan_step"])
    assert final.paused
    discovery, = await task_service.get_children(group.id)
    assert discovery.status == TaskStatus.DISPATCH and not discovery.paused
    ctx = ResourceContext(agent_id=worker.id, task_id=discovery.id, runtime="internal")
    manifest = inventory(group.id)
    manifest["items"][0]["key"] = "inventory"  # Item keys cannot collide with discovery.
    created = await resource_create(ctx, "document://", json.dumps(manifest).encode(),
                                    name="Synthetic inventory", document_type="dataset")
    # The harness records successful file operations in the canonical Working Set.
    await upsert_working_resource(discovery.id, WorkingResource(
        resource_type="memory_document", role="primary_working_document", reference=created.uri,
        producer_task_id=discovery.id, metadata={"produced": True},
    ))
    await complete(discovery, result=json.dumps({"inventory_uri": created.uri}))
    await planner_service.advance(group)
    children = sorted(await task_service.get_children(group.id), key=lambda t: t.data["plan_step"])
    assert await planner_service._working_set_completion_error(root) is not None
    assert len(children) == 3  # Discovery plus a bounded wave of two documents.
    assert children[1].status == TaskStatus.DISPATCH and not children[1].paused
    assert children[2].paused
    # Simulate a worker stopping after creating the wave but before activating its leaf.
    task_service.suspend(children[1], task_service.PAUSE_PLAN)
    await task_service.save(children[1])
    await planner_service.advance(group)
    assert not children[1].paused
    group_id, first_id, failed_id = group.id, children[1].id, children[2].id
    output = await resource_create(
        ResourceContext(agent_id=worker.id, task_id=first_id, runtime="internal"),
        "document://", b"<p>Synthetic converted content.</p>", name="Converted document",
    )
    await upsert_working_resource(first_id, WorkingResource(
        resource_type="memory_document", role="referenced_document:output", reference=output.uri,
        producer_task_id=first_id, metadata={"produced": True},
    ))
    await complete(children[1])
    await planner_service.advance(group)
    await complete(children[2], success=False, result="Provider failed")
    await planner_service.advance(group)
    await planner_service.advance(root)
    assert root.status == group.status == TaskStatus.ERROR
    assert final.data["plan_skipped"] is True
    cost_before_retry = root.cost

    # A later edit cannot silently replace the frozen work list.
    await resource_write(ctx, created.uri, json.dumps(inventory(group_id, 1)).encode(), expected_revision=1)
    await db.commit()
    db.expunge_all()
    root = await task_service.get_by_id(root_id)
    await task_service.retry(root.id, root.revision)
    await planner_service.advance(root)
    group = await task_service.get_by_id(group_id)
    first = await task_service.get_by_id(first_id)
    failed = await task_service.get_by_id(failed_id)
    assert first.status == TaskStatus.SUCCESS
    assert first.get_execution_result().result == "Verified item"
    assert failed.status == TaskStatus.DISPATCH and not failed.paused
    await complete(failed, cost=0.2)
    await planner_service.advance(group)
    await planner_service.advance(group)  # Spurious wake-up must not duplicate the wave.
    assert len(await task_service.get_children(group.id)) == 5
    for index in range(3, 6):
        children = sorted(await task_service.get_children(group.id), key=lambda t: t.data["plan_step"])
        await complete(children[index])
        await planner_service.advance(group)
    assert group.status == TaskStatus.SUCCESS
    all_children = await task_service.get_children(group.id)
    assert len(all_children) == 6
    assert len({child.id for child in all_children}) == 6
    await planner_service.advance(root)
    final = next(t for t in await task_service.get_children(root.id) if t.id != group.id)
    assert not final.paused
    await complete(final)
    await planner_service.advance(root)
    assert root.status == TaskStatus.SUCCESS
    assert root.cost == pytest.approx(cost_before_retry + 0.5)
    progress = await planner_service.get_progress(root.id)
    assert progress["done"] == progress["total"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("record_receipt", [False, True])
async def test_inventory_requires_both_resource_receipt_and_read_permission(
    db, agents, memory_storage, monkeypatch, record_receipt,
) -> None:
    from app.file_share import ResourceContext, resource_create
    from app.memory.service import MemoryPermissionError

    worker, other = agents
    group = Task(label="Restricted collection", agent_id=worker.id, status=TaskStatus.PLAN,
                 plan={"collection": collection_step().collection.model_dump()})
    db.add(group)
    await db.flush()
    discovery = Task(label="Discovery", agent_id=worker.id, parent_id=group.id,
                     status=TaskStatus.SUCCESS)
    db.add(discovery)
    await db.commit()
    created = await resource_create(
        ResourceContext(agent_id=other.id, runtime="internal"), "document://",
        json.dumps(inventory(group.id)).encode(), document_type="dataset",
    )
    discovery.set_execution_result(ExecutionResult(
        prompt="", result=json.dumps({"inventory_uri": created.uri}), success=True,
    ))
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    if record_receipt:
        await upsert_working_resource(discovery.id, WorkingResource(
            resource_type="memory_document", role="collection_inventory", reference=created.uri,
            producer_task_id=discovery.id, metadata={"produced": True},
        ))
    with pytest.raises(MemoryPermissionError if record_receipt else ValueError):
        await planner_collection.freeze_inventory(group, discovery)
    assert "inventory" not in group.plan
    assert await task_service.get_children(discovery.id) == []


def test_large_collection_waves_are_finite_and_empty_inventory_finishes(monkeypatch) -> None:
    monkeypatch.setattr(planner_service.runtime_settings, "TASK_PLAN_MAX_LEAVES", 7)
    task = Task(label="Many records", plan={
        "collection": collection_step().collection.model_dump(),
        "inventory": inventory(uuid4(), 123), "steps": [{"label": "Discovery"}],
        "item_tools": ["file_read"], "item_effort": "standard",
    })
    sizes = []
    while True:
        before = len(task.plan["steps"])
        if not planner_collection.append_item_wave(task):
            break
        sizes.append(len(task.plan["steps"]) - before)
    assert max(sizes) <= 7
    assert sum(sizes) == 123
    assert len({step["collection_key"] for step in task.plan["steps"][1:]}) == 123
    task.plan = {**task.plan, "inventory": inventory(uuid4(), 0), "steps": [{"label": "Discovery"}]}
    assert not planner_collection.append_item_wave(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,held", [(TaskStatus.PLAN, True), (TaskStatus.ERROR, False), (TaskStatus.SUCCESS, False)])
async def test_late_planner_wakeup_cannot_restart_held_or_terminal_work(monkeypatch, status, held) -> None:
    task = Task(label="Stopped collection", status=status,
                paused=held, data={"pause_reasons": ["user"]} if held else None)
    build = AsyncMock()
    monkeypatch.setattr(planner_service, "_build_plan", build)
    await planner_service.advance(task)
    build.assert_not_awaited()
    assert task.status == status


def test_inventory_creation_cannot_satisfy_the_requested_file_deliverable() -> None:
    step = collection_step()
    step.tools = ["file_read"]
    step.artifact_policy = "none"
    root = Task(label="Create report", objective="Create a final .pdf file")
    with pytest.raises(ValueError, match="file-production"):
        planner_service._validate_plan_result_contract(root, Plan(steps=[step]))


@pytest.mark.asyncio
@pytest.mark.parametrize("leased", [False, True])
async def test_retry_waits_for_all_descendants_to_stop_and_release_their_lease(db, leased) -> None:
    root = Task(label="Failed plan", status=TaskStatus.ERROR,
                plan={"steps": [{"label": "Item"}], "cursor": 0})
    db.add(root)
    await db.flush()
    child = Task(label="Pending shutdown", parent_id=root.id,
                 status=TaskStatus.ERROR if leased else TaskStatus.EXEC,
                 lease_token=uuid4() if leased else None)
    db.add(child)
    await db.commit()
    with pytest.raises(task_service.TaskEditConflict):
        await task_service.retry(root.id, root.revision)
    assert root.status == TaskStatus.ERROR
    assert child.status == (TaskStatus.ERROR if leased else TaskStatus.EXEC)
