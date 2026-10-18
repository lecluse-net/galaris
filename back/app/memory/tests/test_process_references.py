"""References preserve Process ownership, frozen runs and independently revocable access."""

import pytest

from app.file_share import ResourceContext, resource_list, resource_search, resource_info
from app.memory import document_service, service
from app.memory.process_references import change_reference, references
from app.memory.schemas import MemoryGrantUpdate
from app.process import process_resource_preview, process_service
from app.process.native_definitions import create, update
from app.process.resource_previews import process_resource_options
from app.process.tests.test_native_bpmn import graph, native as native
from app.share import set_grant
from core.util.rich_text import normalize_html


@pytest.mark.asyncio
async def test_internal_attachment_batches_preserve_sources_and_legacy_memberships(db, native):
    from app.memory.internal_attachments import change_references, references as internal_references
    owner, reader = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic internal attachment", graph=graph("Synthetic work"))
    uri = f"galaris://processes/{definition.code}"
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic attachment picker",
        content="<p>Synthetic content.</p>", task_id=None)
    revision = document.revision
    with pytest.raises((FileNotFoundError, service.MemoryNotFoundError)):
        await change_references(document.id, owner.id, owner.id, uris=[uri, "file://00000000-0000-4000-8000-000000000001"], expected_lock_version=document.lock_version)
    assert "resource_attachments" not in document.metadata_
    attached = await change_references(document.id, owner.id, owner.id, uris=[uri, uri], expected_lock_version=document.lock_version)
    assert [item["uri"] for item in attached["items"]] == [uri]
    assert document.revision == revision
    assert await change_references(document.id, owner.id, owner.id, uris=[uri], expected_lock_version=1) == attached
    await service.set_item_grant(document.id, reader.id, MemoryGrantUpdate(can_write=True), actor_agent_id=owner.id)
    hidden = await internal_references(document.id, reader.id, reader.id)
    assert hidden["items"] == [{"uri": uri, "name": None, "available": False}]
    assert (await resource_list(ResourceContext(agent_id=owner.id, runtime="internal"), f"document://{document.id}/attachments/")).entries == []
    with pytest.raises(service.MemoryPermissionError):
        await change_references(document.id, reader.id + 100000, owner.id, uris=[uri], expected_lock_version=document.lock_version, remove=True)
    # Revoking access to the source does not prevent detaching its reference.
    detached = await change_references(document.id, reader.id, reader.id, uris=[uri], expected_lock_version=document.lock_version, remove=True)
    assert detached["items"] == []
    legacy = await change_reference(document.id, owner.id, owner.id, uri=uri, expected_lock_version=detached["lock_version"])
    assert len((await internal_references(document.id, owner.id, owner.id))["items"]) == 1
    assert not (await change_references(document.id, owner.id, owner.id, uris=[uri], expected_lock_version=legacy["lock_version"], remove=True))["items"]
    from uuid import uuid4
    from core.user import UserModel
    from app.agent import AgentManagementScope
    from app.dataset import service as datasets
    human = UserModel(email=f"synthetic-picker-{uuid4().hex}@example.com", hashed_password="synthetic", is_active=True)
    outsider = UserModel(email=f"synthetic-picker-other-{uuid4().hex}@example.com", hashed_password="synthetic", is_active=True)
    db.add_all([human, outsider]); await db.flush()
    scope = AgentManagementScope(human.id, frozenset({owner.id}))
    personal = await create(actor_agent_id=owner.id, owner_user_id=human.id, title="Synthetic personal workflow", graph=graph())
    dataset = await datasets.create(scope, title="Synthetic personal values", content='{"value":42}')
    personal_uri = f"galaris://processes/{personal.code}"
    agent_context = ResourceContext(agent_id=owner.id, runtime="internal")
    human_context = ResourceContext(agent_id=owner.id, runtime="internal", management_scope=scope)
    assert personal_uri not in {entry.uri for entry in (await resource_list(agent_context, "galaris://processes/")).entries}
    assert personal_uri in {entry.uri for entry in (await resource_list(human_context, "galaris://processes/")).entries}
    assert (await resource_info(human_context, personal_uri)).uri == personal_uri
    attached = await change_references(document.id, owner.id, owner.id, uris=[personal_uri, f"data://{dataset.id}"],
        expected_lock_version=document.lock_version, scope=scope)
    assert all(item["available"] for item in attached["items"])
    hidden = await internal_references(document.id, owner.id, owner.id,
        scope=AgentManagementScope(outsider.id, frozenset({owner.id})))
    assert all(not item["available"] and item["name"] is None for item in hidden["items"])


@pytest.mark.asyncio
async def test_documents_reference_live_processes_and_frozen_runs_with_independent_access(db, native):
    owner, reader = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic cited workflow", graph=graph("Original task"))
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    process_uri = f"galaris://processes/{definition.code}"
    run_uri = f"galaris://processes/runs/{launched.run_id}"
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    collection = await resource_list(context, "galaris://processes/", max_entries=1)
    assert [entry.uri for entry in collection.entries] == ["galaris://processes/runs/"]
    assert collection.next_cursor
    following = await resource_list(context, "galaris://processes/", max_entries=1, cursor=collection.next_cursor)
    assert [entry.uri for entry in following.entries] == [process_uri]
    runs = await resource_list(context, "galaris://processes/runs/")
    assert [entry.uri for entry in runs.entries] == [run_uri]
    found = await resource_search(context, "galaris://processes/runs/", "Synthetic cited")
    assert [hit.resource.uri for hit in found.hits] == [run_uri]
    assert not (await resource_list(ResourceContext(agent_id=reader.id, runtime="internal"), "galaris://processes/runs/")).entries
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic process guide",
        content="<p>Entirely synthetic guide.</p>", task_id=None)
    original_revision = document.revision
    first = await change_reference(document.id, owner.id, owner.id, uri=process_uri, expected_lock_version=document.lock_version)
    assert await change_reference(document.id, owner.id, owner.id, uri=process_uri, expected_lock_version=1) == first
    with pytest.raises(service.MemoryConflictError):
        await change_reference(document.id, owner.id, owner.id, uri=run_uri, expected_lock_version=1)
    attached = await change_reference(document.id, owner.id, owner.id, uri=run_uri, expected_lock_version=first["lock_version"])
    assert document.metadata_["process_attachments"] == [process_uri, run_uri]
    assert document.revision == original_revision
    await service.set_item_grant(document.id, reader.id, MemoryGrantUpdate(can_write=True), actor_agent_id=owner.id)
    hidden = await references(document.id, reader.id, reader.id)
    assert all(not item["available"] and item["title"] is None for item in hidden["items"])
    assert await process_resource_options("Synthetic cited", reader.id) == []
    with pytest.raises(PermissionError):
        await process_resource_preview(process_uri, reader.id)
    await set_grant(definition.share_id, "agent", reader.id, False)
    await db.commit()
    visible = await references(document.id, reader.id, reader.id)
    assert [item["uri"] for item in visible["items"]] == [process_uri, run_uri]
    assert all(item["available"] for item in visible["items"])
    assert {item["uri"] for item in await process_resource_options("Synthetic cited", reader.id)} == {process_uri, run_uri}
    listed = await resource_list(ResourceContext(agent_id=reader.id, runtime="internal"), f"document://{document.id}/attachments/")
    assert listed.entries == []
    await update(definition.code, owner.id, expected_revision=1, graph=graph("Revised task"))
    current = await process_resource_preview(process_uri, reader.id)
    frozen = await process_resource_preview(run_uri, reader.id)
    thumbnail = await process_resource_preview(run_uri, reader.id, thumbnail=True)
    assert current["graph"]["nodes"][1]["config"]["prompt"] == "Revised task"
    assert frozen["graph"]["nodes"][1]["config"]["prompt"] == "Original task"
    assert thumbnail["graph"] == current["graph"] and thumbnail["process_uri"] == process_uri
    html = f'<blockquote class="galaris-link-card galaris-process-diagram"><p><a href="{run_uri}">Synthetic execution</a></p></blockquote>'
    assert "galaris-process-diagram" in normalize_html(html, profile="document")
    assert run_uri in normalize_html(html, profile="document")
    await set_grant(definition.share_id, "agent", reader.id, None)
    await db.commit()
    assert all(not item["available"] for item in (await references(document.id, reader.id, reader.id))["items"])
    with pytest.raises(PermissionError):
        await process_resource_preview(run_uri, reader.id, thumbnail=True)
    removed = await change_reference(document.id, reader.id, reader.id, uri=run_uri,
        expected_lock_version=(await references(document.id, reader.id, reader.id))["lock_version"], remove=True)
    assert [item["uri"] for item in removed["items"]] == [process_uri]
    assert attached["items"][1]["uri"] == run_uri


@pytest.mark.asyncio
@pytest.mark.parametrize("manifest", [None, ["galaris://processes/synthetic"] * 51, ["galaris://processes/synthetic/data"]])
async def test_document_process_reference_manifests_are_bounded_and_validated(db, native, manifest):
    owner, _ = native
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic invalid references", content="<p>Guide</p>", task_id=None)
    document.metadata_ = {**document.metadata_, "process_attachments": manifest}
    await db.flush()
    with pytest.raises(service.MemoryConflictError):
        await references(document.id, owner.id, owner.id)


@pytest.mark.asyncio
async def test_native_definition_references_do_not_shadow_external_workflow_identifiers(db, native):
    from app.file_share import resource_info
    from app.process.models import ProcessDefinition
    from app.tools import ToolModel
    owner, other = native
    definition = await create(actor_agent_id=other.id, title="Synthetic private native process", code="synthetic_collision", graph=graph())
    tool = ToolModel(code="synthetic-preview-engine", label="Synthetic external engine", description="", connection_schema={})
    db.add(tool)
    await db.flush()
    db.add(ProcessDefinition(agent_id=owner.id, tool_id=tool.id, engine_process_id=definition.code, label="Synthetic external workflow"))
    await db.commit()
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    external = await resource_info(context, f"galaris://process/{definition.code}")
    assert external.metadata["label"] == "Synthetic external workflow"
    with pytest.raises(PermissionError):
        await resource_info(context, f"galaris://processes/{definition.code}")
