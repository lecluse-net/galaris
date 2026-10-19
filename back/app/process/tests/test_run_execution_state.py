"""Run receipts survive failures without entering business resources."""

from app.share import set_grant

from copy import deepcopy

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app.process import process_service
from app.process.models import ProcessRun
from app.process.native_definitions import create
from app.process.run_data import integrate_workflow_values, create_workflow_attachment
from app.process.tests.test_native_bpmn import committed_native, native, typed_graph


async def start_run(session, owner):
    definition = await create(actor_agent_id=owner.id, title="Synthetic run data", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await session.get(ProcessRun, launched.run_id)
    await session.commit()
    return run


@pytest.mark.asyncio
async def test_failed_integration_commit_rolls_back_business_data_and_run_receipt(
        inference_db, committed_native):
    session = inference_db
    run = await start_run(session, committed_native[0])
    before = (deepcopy(run.data), run.data_revision, deepcopy(run.execution_state))
    run_id = run.id
    await session.commit()

    def fail_commit(_session):
        raise SQLAlchemyError("Synthetic lost transaction")

    event.listen(session.sync_session, "before_commit", fail_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="Synthetic"):
            await integrate_workflow_values(run_id, command="once", baseline={},
                changes={"approved": {"type": "bool", "value": True}}, files=[])
    finally:
        event.remove(session.sync_session, "before_commit", fail_commit)
        await session.rollback()
    current_run = await session.get(ProcessRun, run_id)
    assert (current_run.data, current_run.data_revision, current_run.execution_state) == before
    result = await integrate_workflow_values(run_id, command="once", baseline={},
        changes={"approved": {"type": "bool", "value": True}}, files=[])
    assert result["revision"] == before[1] + 1


@pytest.mark.asyncio
async def test_input_copy_and_receipt_commit_together_and_replay_without_source(
        inference_db, committed_native, tmp_path):
    from app.process.run_data import run_files
    session = inference_db
    owner, _ = committed_native
    run = await start_run(session, owner)
    run_id = run.id
    path = tmp_path / "input.txt"
    path.write_text("Entirely synthetic input", encoding="utf-8")

    def fail_commit(_session):
        raise SQLAlchemyError("Synthetic interrupted file transaction")

    event.listen(session.sync_session, "before_commit", fail_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="Synthetic"):
            await create_workflow_attachment(run_id, key="input", source_uri="https://example.test/input.txt",
                path=path, name="input.txt", media_type="text/plain")
    finally:
        event.remove(session.sync_session, "before_commit", fail_commit)
        await session.rollback()
    current = await session.get(ProcessRun, run_id)
    assert not current.execution_state.get("attachments")
    assert not await run_files(run_id)
    receipt = await create_workflow_attachment(run_id, key="input", source_uri="https://example.test/input.txt",
        path=path, name="input.txt", media_type="text/plain")
    path.unlink()
    assert await create_workflow_attachment(run_id, key="input", source_uri="https://example.test/input.txt",
        path=path, name="input.txt", media_type="text/plain") == receipt
    assert len(await run_files(run_id)) == 1
    assert current.execution_state["attachments"] == {"input": receipt}


@pytest.mark.asyncio
async def test_late_integration_reuses_receipt_but_cannot_change_terminal_run(db, native):
    from app.process.run_data import RunDataConflictError
    run = await start_run(db, native[0])
    changes = {"approved": {"type": "bool", "value": True}}
    result = await integrate_workflow_values(run.id, command="once", baseline={}, changes=changes, files=[])
    run.status = "cancelled"
    await db.commit()
    assert await integrate_workflow_values(run.id, command="once", baseline={}, changes=changes, files=[]) == result
    with pytest.raises(RunDataConflictError, match="stopped run"):
        await integrate_workflow_values(run.id, command="late", baseline={},
            changes={"late": {"type": "bool", "value": True}}, files=[])
    assert set(run.execution_state["integrations"]) == {"once"}


@pytest.mark.asyncio
async def test_run_data_and_files_use_process_rights_without_creating_a_dataset(db, native):
    from sqlalchemy import func, select
    from app.dataset.models import Dataset
    from app.memory.models import MemoryItem
    from app.file_share import ResourceContext, resource_read, resource_write, resource_create, resource_info, resource_list
    from app.process.models import ProcessRunFile
    from app.process.native_runs import inspect_run, list_runs
    from app.process.run_resources import read_run_data
    from .test_native_bpmn import graph

    owner, reader = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic run ownership", graph=graph())
    counts = [await db.scalar(select(func.count()).select_from(model)) for model in (Dataset, MemoryItem)]
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"kept": False})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await db.get(ProcessRun, launched.run_id)
    assert run.data == {"kept": False}
    assert counts == [await db.scalar(select(func.count()).select_from(model)) for model in (Dataset, MemoryItem)]
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    data_uri = f"galaris://processes/runs/{run.id}/data"
    collection = f"galaris://processes/runs/{run.id}/attachments/"
    added = await resource_create(ctx, collection, b"Entirely synthetic report", name="report.txt")
    link = await db.scalar(select(ProcessRunFile).where(ProcessRunFile.run_id == run.id))
    assert link.file_id is not None
    file_uri = f"file://{link.file_id}"
    foreign = ResourceContext(agent_id=reader.id, runtime="internal")
    for uri in (data_uri, added.uri, file_uri):
        with pytest.raises(PermissionError):
            await resource_info(foreign, uri)
    await set_grant(definition.share_id, "agent", reader.id, False)
    await db.commit()
    assert (await resource_read(foreign, added.uri)).content == "Entirely synthetic report"
    assert (await resource_info(foreign, file_uri)).uri == file_uri
    assert (await list_runs(reader.id))["total"] == 1
    assert not (await inspect_run(run.id, reader.id))["can_control"]
    assert (await resource_list(foreign, collection)).entries[0].uri == added.uri
    with pytest.raises(PermissionError):
        await resource_write(foreign, data_uri, b'{"kept": false, "approved": true}', expected_revision=1)
    with pytest.raises(PermissionError):
        await resource_create(foreign, collection, b"Denied synthetic report", name="denied.txt")
    await set_grant(definition.share_id, "agent", reader.id, True)
    await db.commit()
    await resource_write(foreign, data_uri, b'{"kept": false, "approved": true}', expected_revision=1)
    assert (await read_run_data(run.id, owner.id))["data"] == {"kept": False, "approved": True}
    await set_grant(definition.share_id, "agent", reader.id, None)
    await db.commit()
    for uri in (data_uri, added.uri, file_uri):
        with pytest.raises(PermissionError):
            await resource_info(foreign, uri)
    assert (await list_runs(reader.id))["total"] == 0
    assert counts == [await db.scalar(select(func.count()).select_from(model)) for model in (Dataset, MemoryItem)]
    from app.file_share import resource_copy, resource_delete
    second = await resource_copy(ctx, added.uri, collection)
    assert second.uri.startswith(collection) and second.uri != added.uri
    assert (await resource_read(ctx, second.uri)).content == "Entirely synthetic report"
    await resource_delete(ctx, added.uri)
    with pytest.raises(FileNotFoundError):
        await resource_info(ctx, added.uri)
    assert [entry.uri for entry in (await resource_list(ctx, collection)).entries] == [second.uri]
    former_dataset = Dataset(owner_agent_id=owner.id, title="Synthetic obsolete run Dataset", content='{"old":true}',
        metadata_={"engine_dataset": True, "engine_managed": True, "engine_agent": owner.id})
    db.add(former_dataset)
    await db.flush()
    await resource_delete(ctx, f"data://{former_dataset.id}")
    assert (await read_run_data(run.id, owner.id))["data"] == {"kept": False, "approved": True}
    assert (await resource_read(ctx, second.uri)).content == "Entirely synthetic report"
