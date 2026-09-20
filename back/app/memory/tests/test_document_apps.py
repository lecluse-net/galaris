import json
from html import escape
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.agent import AgentManagementScope
from app.memory import service, document_service, router
from app.memory.document_apps import AppDatasetRequest, AppGrantUpdate, document_apps
from app.memory.document_app_service import app_dataset, app_permissions, set_app_permission
from app.memory.schemas import MemoryGrantUpdate, MemoryItemUpdate, MemoryPayload
from core.user import UserModel


def block(dataset_id, *, access="write", **overrides):
    app = {"id": "form", "title": "Synthetic form", "html": '<form id="entry"><input name="value"></form>',
           "javascript": "document.querySelector('form').onsubmit = event => event.preventDefault();",
           "datasets": {"entries": {"uri": f"document://{dataset_id}", "access": access}}, **overrides}
    return '<p>Introduction</p><pre><code class="language-galaris-app">' + escape(json.dumps(app)) + '</code></pre>'


async def setup(db, agents):
    owner, viewer = agents
    human = UserModel(email=f"apps-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    dataset = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title="Responses", content="[]", document_type="dataset")
    document = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title="Form", content=block(dataset.id))
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    viewer_scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({viewer.id}))
    return document, dataset, scope, viewer_scope


async def approve(document, scope, *, revision=1, app_key="form", alias="entries", access="write"):
    return await set_app_permission(document.id, app_key, alias,
        AppGrantUpdate(document_revision=revision, access=access), scope)


@pytest.mark.asyncio
async def test_generated_html_cannot_authorize_itself_even_for_dataset_owner(db, agents, memory_storage):
    document, dataset, scope, _ = await setup(db, agents)
    for operation in ("read", "replace", "append"):
        with pytest.raises(service.MemoryPermissionError):
            await app_dataset(document.id, "form", "entries", AppDatasetRequest(
                document_revision=1, operation=operation, expected_revision=1, value=[],
            ), scope)
    stored, content, *_ = await service.get_item(dataset.id, agent_id=agents[0].id)
    assert stored.revision == 1 and content == b"[]"


@pytest.mark.asyncio
async def test_form_submission_preserves_history_and_checks_both_revisions(db, agents, memory_storage):
    document, dataset, scope, _ = await setup(db, agents)
    await approve(document, scope)
    read = await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=1), scope)
    assert read.data == [] and read.revision == 1
    change = AppDatasetRequest(document_revision=1, operation="append", expected_revision=1, value={"value": "<script>literal</script>"})
    written = await app_dataset(document.id, "form", "entries", change, scope)
    assert written.data == [{"value": "<script>literal</script>"}] and written.revision == 2
    with pytest.raises(service.MemoryConflictError):
        await app_dataset(document.id, "form", "entries", change, scope)
    historical = await service.get_document_content_revision(dataset.id, 1, actor_agent_id=agents[0].id)
    assert historical.content == "[]"
    assert (await service.get_item(document.id, agent_id=agents[0].id))[0].revision == 1
    await service.update_item(document.id, MemoryItemUpdate(payload=MemoryPayload(text=block(dataset.id, title="Changed form")), expected_revision=1), actor_agent_id=agents[0].id)
    with pytest.raises(service.MemoryConflictError):
        await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=1), scope)
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=2), scope)
    await approve(document, scope, revision=2)
    current = await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=2), scope)
    assert current.data == written.data


@pytest.mark.asyncio
async def test_apps_use_viewer_permissions_not_author_and_revocations_are_live(db, agents, memory_storage):
    document, dataset, _, scope = await setup(db, agents)
    owner, viewer = agents
    await service.set_item_grant(document.id, viewer.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    read = AppDatasetRequest(document_revision=1)
    with pytest.raises((service.MemoryPermissionError, service.MemoryNotFoundError)):
        await app_dataset(document.id, "form", "entries", read, scope)
    await service.set_item_grant(dataset.id, viewer.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    await approve(document, scope, access="read")
    assert (await app_dataset(document.id, "form", "entries", read, scope)).data == []
    change = AppDatasetRequest(document_revision=1, operation="append", expected_revision=1, value={"answer": 42})
    with pytest.raises((service.MemoryPermissionError, service.MemoryNotFoundError)):
        await app_dataset(document.id, "form", "entries", change, scope)
    await service.set_item_grant(dataset.id, viewer.id, MemoryGrantUpdate(can_write=True), actor_agent_id=owner.id)
    await approve(document, scope)
    assert (await app_dataset(document.id, "form", "entries", change, scope)).revision == 2
    await service.remove_item_grant(dataset.id, viewer.id, actor_agent_id=owner.id)
    with pytest.raises((service.MemoryPermissionError, service.MemoryNotFoundError)):
        await app_dataset(document.id, "form", "entries", read, scope)
    await service.remove_item_grant(document.id, viewer.id, actor_agent_id=owner.id)
    with pytest.raises((service.MemoryPermissionError, service.MemoryNotFoundError)):
        await app_dataset(document.id, "form", "entries", read, scope)


@pytest.mark.asyncio
async def test_bindings_are_a_ceiling_and_invalid_operations_do_not_change_data(db, agents, memory_storage, monkeypatch):
    document, dataset, scope, _ = await setup(db, agents)
    owner, _ = agents
    for app_id, alias in [("missing", "entries"), ("form", "undeclared")]:
        with pytest.raises(service.MemoryPermissionError):
            await app_dataset(document.id, app_id, alias, AppDatasetRequest(document_revision=1), scope)
    await service.update_item(document.id, MemoryItemUpdate(expected_revision=1, payload=MemoryPayload(text=block(dataset.id, access="read"))), actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await approve(document, scope, revision=2, access="write")
    change = AppDatasetRequest(document_revision=2, operation="replace", expected_revision=1, value={})
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "entries", change, scope)
    # The route enforces the human RBAC privilege in addition to dataset ACLs.
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as denied:
        await router.access_app_dataset(document.id, "form", "entries", change)
    assert denied.value.status_code == 403
    assert (await service.get_item(dataset.id, agent_id=owner.id))[1] == b"[]"
    await service.update_item(document.id, MemoryItemUpdate(expected_revision=2, payload=MemoryPayload(text=block(dataset.id))), actor_agent_id=owner.id)
    await approve(document, scope, revision=3)
    replaced = await app_dataset(document.id, "form", "entries", AppDatasetRequest(
        document_revision=3, operation="replace", expected_revision=1, value=None,
    ), scope)
    assert replaced.data is None and replaced.revision == 2
    with pytest.raises(ValueError, match="root is a JSON array"):
        await app_dataset(document.id, "form", "entries", AppDatasetRequest(
            document_revision=3, operation="append", expected_revision=2, value={"answer": 42},
        ), scope)
    stored, content, *_ = await service.get_item(dataset.id, agent_id=owner.id)
    assert stored.revision == 2 and content == b"null"


@pytest.mark.asyncio
async def test_app_manifest_validation_is_atomic_and_source_survives_restore(db, agents, memory_storage):
    document, dataset, scope, _ = await setup(db, agents)
    await approve(document, scope)
    owner, _ = agents
    source = (await service.get_item(document.id, agent_id=owner.id))[1].decode()
    assert document_apps(source)[0].html.startswith('<form')
    for invalid in [block(dataset.id, id="../escape"), block(dataset.id) + block(dataset.id),
                    '<pre><code class="language-galaris-app">{</code></pre>',
                    '<blockquote>' + block(dataset.id) + '</blockquote>']:
        with pytest.raises(ValueError):
            await service.update_item(document.id, MemoryItemUpdate(expected_revision=1, payload=MemoryPayload(text=invalid)), actor_agent_id=owner.id)
        assert (await service.get_item(document.id, agent_id=owner.id))[1].decode() == source
    await service.update_item(document.id, MemoryItemUpdate(expected_revision=1, payload=MemoryPayload(text="<p>Removed</p>")), actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=2), scope)
    await service.restore_document_content_revision(document.id, 1, expected_revision=2, actor_agent_id=owner.id)
    assert (await service.get_item(document.id, agent_id=owner.id))[1].decode() == source
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=3), scope)
    await approve(document, scope, revision=3)
    assert (await app_dataset(document.id, "form", "entries", AppDatasetRequest(document_revision=3), scope)).data == []


@pytest.mark.asyncio
async def test_ordinary_html_form_and_scripts_preserve_source_and_write_declared_dataset(db, agents, memory_storage):
    document, dataset, scope, _ = await setup(db, agents)
    source = (f'<p>Editable introduction</p><form data-dataset="document://{dataset.id}" id="entry">'
              '<label>Answer<input name="answer" required></label><button>Save</button></form>'
              '<style>form { display: flex; gap: 1rem; }</style>'
              '<script>document.getElementById("entry").onsubmit = async event => { event.preventDefault(); '
              'const current = await galaris.datasets.read("entries"); '
              'await galaris.datasets.append("entries", {answer: "Synthetic"}, current.revision); };</script>')
    saved = await service.update_item(document.id, MemoryItemUpdate(expected_revision=1, payload=MemoryPayload(text=source)), actor_agent_id=agents[0].id)
    text = (await service.get_item(document.id, agent_id=agents[0].id))[1].decode()
    assert '<form ' in text and '<script>' in text and 'event.preventDefault()' in text
    assert 'language-galaris' not in text
    await approve(document, scope, revision=saved.revision, app_key="document-html")
    written = await app_dataset(document.id, "document-html", "entries", AppDatasetRequest(
        document_revision=saved.revision, operation="append", expected_revision=1, value={"answer": "Synthetic"},
    ), scope)
    assert written.data == [{"answer": "Synthetic"}]
    await service.update_item(document.id, MemoryItemUpdate(expected_revision=2, payload=MemoryPayload(text='<p>Replaced</p>')), actor_agent_id=agents[0].id)
    await service.restore_document_content_revision(document.id, 2, expected_revision=3, actor_agent_id=agents[0].id)
    assert (await service.get_item(document.id, agent_id=agents[0].id))[1].decode() == text


@pytest.mark.asyncio
async def test_consent_is_personal_revocable_and_cannot_be_forged_or_transferred(db, agents, memory_storage, monkeypatch):
    document, dataset, scope, _ = await setup(db, agents)
    await approve(document, scope)
    other = UserModel(email=f"reader-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(other)
    await db.flush()
    other_scope = AgentManagementScope(user_id=other.id, agent_ids=scope.agent_ids)
    read = AppDatasetRequest(document_revision=1)
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "entries", read, other_scope)
    assert (await app_permissions(document.id, other_scope)).grants[0].access is None
    await approve(document, scope, access=None)
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "entries", read, scope)
    # Write consent itself cannot bypass the human's edit privilege.
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as denied:
        await router.update_app_permission(document.id, "form", "entries", AppGrantUpdate(document_revision=1, access="write"))
    assert denied.value.status_code == 403
    await router.update_app_permission(document.id, "form", "entries", AppGrantUpdate(document_revision=1, access="read"))
    assert (await app_dataset(document.id, "form", "entries", read, scope)).data == []
    with pytest.raises(service.MemoryPermissionError):
        await approve(document, scope, alias="undeclared")
    with pytest.raises(service.MemoryConflictError):
        await approve(document, scope, revision=2)


@pytest.mark.asyncio
async def test_cross_dataset_exfiltration_needs_separate_consent_for_each_binding(db, agents, memory_storage):
    document, secret, scope, _ = await setup(db, agents)
    sink = await document_service.create_document(owner_agent_id=agents[0].id, task_id=None,
        title="Shared collection", content="[]", document_type="dataset")
    source = block(secret.id, datasets={
        "secret": {"uri": f"document://{secret.id}", "access": "read"},
        "sink": {"uri": f"document://{sink.id}", "access": "write"},
    })
    await service.update_item(document.id, MemoryItemUpdate(expected_revision=1, payload=MemoryPayload(text=source)), actor_agent_id=agents[0].id)
    await approve(document, scope, revision=2, alias="sink")
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "secret", AppDatasetRequest(document_revision=2), scope)
    await approve(document, scope, revision=2, alias="sink", access=None)
    await approve(document, scope, revision=2, alias="secret", access="read")
    content = await app_dataset(document.id, "form", "secret", AppDatasetRequest(document_revision=2), scope)
    with pytest.raises(service.MemoryPermissionError):
        await app_dataset(document.id, "form", "sink", AppDatasetRequest(
            document_revision=2, operation="replace", expected_revision=1, value=content.data), scope)
    assert (await service.get_item(sink.id, agent_id=agents[0].id))[0].revision == 1


@pytest.mark.asyncio
async def test_invalid_app_data_preserves_dataset_and_does_not_consume_budget(db, agents, memory_storage):
    from app.memory.models import DocumentAppWriteBudget
    from sqlalchemy import select
    document, dataset, scope, _ = await setup(db, agents)
    await approve(document, scope)
    deep = None
    for _ in range(34):
        deep = [deep]
    for value in (float("inf"), {"number": float("nan")}, "é" * 1_000_001, [0] * 20_001, deep):
        with pytest.raises(ValueError):
            await app_dataset(document.id, "form", "entries", AppDatasetRequest(
                document_revision=1, operation="replace", expected_revision=1, value=value), scope)
        stored, content, *_ = await service.get_item(dataset.id, agent_id=agents[0].id)
        assert stored.revision == 1 and content == b"[]"
    assert await db.scalar(select(DocumentAppWriteBudget.id).where(DocumentAppWriteBudget.dataset_id == dataset.id)) is None


@pytest.mark.asyncio
async def test_write_budget_survives_other_documents_and_permission_renewal(db, agents, memory_storage, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import select
    from app.memory.models import DocumentAppWriteBudget
    from app.memory import document_app_security as security
    monkeypatch.setattr(security, "MAX_WRITES", 2)
    document, dataset, scope, _ = await setup(db, agents)
    second = await document_service.create_document(owner_agent_id=agents[0].id, task_id=None,
        title="Second application", content=block(dataset.id))
    await approve(document, scope)
    await approve(second, scope)
    for revision, source in enumerate((document, second), start=1):
        await app_dataset(source.id, "form", "entries", AppDatasetRequest(
            document_revision=1, operation="append", expected_revision=revision, value={"answer": revision}), scope)
    await approve(document, scope, access=None)
    await approve(document, scope)
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=True))
    mutation = AppDatasetRequest(document_revision=1, operation="replace", expected_revision=3, value=[])
    with pytest.raises(HTTPException) as limited:
        await router.access_app_dataset(document.id, "form", "entries", mutation)
    assert limited.value.status_code == 429 and limited.value.headers["Retry-After"] == "60"
    assert (await service.get_item(dataset.id, agent_id=agents[0].id))[0].revision == 3
    budget = await db.scalar(select(DocumentAppWriteBudget).where(DocumentAppWriteBudget.dataset_id == dataset.id))
    assert budget.writes == 2
    budget.window_start -= timedelta(seconds=61)
    await db.commit()
    assert (await app_dataset(document.id, "form", "entries", mutation, scope)).revision == 4
    monkeypatch.setattr(security, "MAX_WRITE_BYTES", 5)
    with pytest.raises(security.AppWriteLimitError):
        await app_dataset(second.id, "form", "entries", AppDatasetRequest(
            document_revision=1, operation="replace", expected_revision=4, value="large"), scope)
    assert (await service.get_item(dataset.id, agent_id=agents[0].id))[0].revision == 4


@pytest.mark.asyncio
async def test_concurrent_workers_share_the_same_durable_write_budget(committed_database, memory_storage, monkeypatch):
    import asyncio
    from app.agent.models import Agent, Title
    from app.memory import document_app_security as security
    from core.database import get_db_session
    from sqlalchemy import select
    from app.memory.models import DocumentAppWriteBudget

    monkeypatch.setattr(security, "MAX_WRITES", 2)
    async with get_db_session() as db:
        human = UserModel(email="quota@example.test", hashed_password="unused", is_active=True)
        title = Title(label="Quota", gender="X")
        db.add_all([human, title])
        await db.flush()
        owner = Agent(title_id=title.id, user_id=human.id, first_name="Quota", last_name="Test", code="quota-test", agent_driver="internal")
        db.add(owner)
        await db.flush()
        scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
        dataset = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title="Concurrent data", content="[]", document_type="dataset")
        documents = []
        for index in range(2):
            document = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title=f"Concurrent form {index}", content=block(dataset.id))
            await approve(document, scope)
            documents.append(document.id)
        dataset_id, owner_id = dataset.id, owner.id

    async def write(document_id):
        try:
            async with get_db_session():
                # Identical content keeps revision 1: concurrency conflicts cannot mask quota failures.
                await app_dataset(document_id, "form", "entries", AppDatasetRequest(
                    document_revision=1, operation="replace", expected_revision=1, value=[]), scope)
            return "accepted"
        except security.AppWriteLimitError:
            return "limited"

    outcomes = await asyncio.wait_for(asyncio.gather(*(write(documents[index % 2]) for index in range(6))), timeout=15)
    assert outcomes.count("accepted") == 2 and outcomes.count("limited") == 4
    async with get_db_session() as db:
        budget = await db.scalar(select(DocumentAppWriteBudget).where(DocumentAppWriteBudget.dataset_id == dataset_id))
        assert budget.writes == 2
        stored, content, *_ = await service.get_item(dataset_id, agent_id=owner_id)
        assert stored.revision == 1 and content == b"[]"
