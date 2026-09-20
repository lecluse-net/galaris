"""Goal filing follows personal access and never replaces a human's classification."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.agent import AgentManagementScope
from app.goal.tests.factories import make_goal
from app.memory import document_tags, service
from app.memory import goal_folders as filing
from app.memory.goal_document_adapter import register_goal_document_adapter
from app.memory.models import DocumentTag, DocumentTagAssignment, DocumentUserGrant, MemoryAutomationJob, MemoryItem
from app.memory.schemas import DocumentTagWrite, MemorySourceCreate
from core.user import UserModel


async def setup_goal(db, agents, *, title="Lancement"):
    register_goal_document_adapter()
    owner, _ = agents
    user = UserModel(email=f"filing-{uuid4()}@example.test", hashed_password="unused", is_active=True, language="fr")
    other = UserModel(email=f"filing-{uuid4()}@example.test", hashed_password="unused", is_active=True, language="fr")
    db.add_all([user, other])
    await db.flush()
    owner.user_id = user.id
    await db.commit()
    goal = await make_goal(title=title, description="<p>Objectif</p>", agent_id=owner.id)
    db.add(goal)
    await db.commit()
    return goal, user, other


async def drain(db):
    """Consume persisted jobs through the production handler, including continuations."""
    for _ in range(200):
        job = await db.scalar(select(MemoryAutomationJob).where(
            MemoryAutomationJob.kind == filing.JOB_KIND, MemoryAutomationJob.status == "pending",
        ).order_by(MemoryAutomationJob.created_at, MemoryAutomationJob.id).limit(1))
        if job is None:
            return
        job.status = "running"
        await db.commit()
        await filing.process_goal_folder_job(job.id, filing.GoalFolderRequest.model_validate(job.payload))
        job.status = "success"
        await db.commit()
    pytest.fail("Folder work did not converge")


async def locations(db, user_id):
    return dict((await db.execute(select(DocumentTagAssignment.document_id, DocumentTagAssignment.tag_id)
        .join(DocumentTag).where(DocumentTag.user_id == user_id))).all())


@pytest.mark.asyncio
async def test_filing_is_personal_idempotent_and_preserves_manual_classification(db, agents, memory_storage):
    goal, user, other = await setup_goal(db, agents)
    for identity in (goal.description_document_id, goal.tracking_document_id):
        db.add(DocumentUserGrant(item_id=identity, user_id=other.id, can_write=False))
    await db.commit()
    manual = await document_tags.write_tag(user.id, DocumentTagWrite(name="Mes projets"))
    await document_tags.move_document(
        AgentManagementScope(user.id, frozenset({agents[0].id})), goal.description_document_id, manual.id,
    )
    documents = [await db.get(MemoryItem, identity) for identity in (goal.description_document_id, goal.tracking_document_id)]
    before = [(item.revision, item.lock_version, item.content_hash) for item in documents]
    for _ in range(2):
        await filing.enqueue_goal_folder_reconciliation(goal_id=goal.id)
        await drain(db)
    first, second = await locations(db, user.id), await locations(db, other.id)
    assert first[goal.description_document_id] == manual.id
    assert first[goal.tracking_document_id] != manual.id
    assert second[goal.description_document_id] == second[goal.tracking_document_id]
    assert first[goal.tracking_document_id] != second[goal.tracking_document_id]
    for person in (user, other):
        tags = list(await db.scalars(select(DocumentTag).where(DocumentTag.user_id == person.id)))
        root = next(tag for tag in tags if tag.system_role == "goals_root")
        folder = next(tag for tag in tags if tag.goal_id == goal.id)
        assert root.name == "Objectifs"
        assert folder.name == goal.title
        assert folder.parent_id == root.id
        assert sum(tag.goal_id == goal.id for tag in tags) == 1
    for item in documents:
        await db.refresh(item)
    assert [(item.revision, item.lock_version, item.content_hash) for item in documents] == before


@pytest.mark.asyncio
async def test_filing_renames_generated_folders_and_recreates_deleted_branches(db, agents, memory_storage):
    goal, user, other = await setup_goal(db, agents)
    db.add(DocumentUserGrant(item_id=goal.tracking_document_id, user_id=other.id, can_write=False))
    await db.commit()
    await filing.enqueue_goal_folder_reconciliation(goal_id=goal.id)
    await drain(db)
    folder = await db.scalar(select(DocumentTag).where(DocumentTag.user_id == user.id, DocumentTag.goal_id == goal.id))
    personal = await db.scalar(select(DocumentTag).where(DocumentTag.user_id == other.id, DocumentTag.goal_id == goal.id))
    await document_tags.write_tag(other.id, DocumentTagWrite(name="Mon dossier", parent_id=None), personal.id)
    goal.title = "Nouveau libellé"
    await db.commit()
    await filing.enqueue_goal_folder_reconciliation(goal_id=goal.id)
    await drain(db)
    await db.refresh(folder)
    await db.refresh(personal)
    assert folder.name == "Nouveau libellé"
    assert personal.name == "Mon dossier" and personal.parent_id is None
    previous_root = folder.parent_id
    await document_tags.remove_tag(user.id, previous_root, confirmed=True)
    assert await locations(db, user.id) == {}
    await filing.enqueue_goal_folder_reconciliation(user_id=user.id)
    await drain(db)
    replacement = await db.scalar(select(DocumentTag).where(DocumentTag.user_id == user.id, DocumentTag.goal_id == goal.id))
    assert replacement.id != folder.id and replacement.parent_id != previous_root
    assert set(await locations(db, user.id)) == {goal.description_document_id, goal.tracking_document_id}


@pytest.mark.asyncio
async def test_global_filing_handles_late_access_rechecks_revocation_and_skips_empty_folders(db, agents, memory_storage):
    goal, user, other = await setup_goal(db, agents)
    manual = await document_tags.write_tag(user.id, DocumentTagWrite(name="Déjà rangés"))
    scope = AgentManagementScope(user.id, frozenset({agents[0].id}))
    for identity in (goal.description_document_id, goal.tracking_document_id):
        await document_tags.move_document(scope, identity, manual.id)
    await filing.enqueue_goal_folder_reconciliation()
    await drain(db)
    assert await db.scalar(select(DocumentTag.id).where(DocumentTag.goal_id == goal.id)) is None
    db.add(DocumentUserGrant(item_id=goal.description_document_id, user_id=other.id, can_write=False))
    await db.commit()
    await filing.enqueue_goal_folder_reconciliation(user_id=other.id, goal_id=goal.id)
    # Permissions are evaluated at execution, not when enqueuing.
    await db.execute(delete(DocumentUserGrant).where(DocumentUserGrant.user_id == other.id))
    await db.commit()
    await drain(db)
    assert await locations(db, other.id) == {}
    db.add(DocumentUserGrant(item_id=goal.description_document_id, user_id=other.id, can_write=False))
    await db.commit()
    await filing.on_user_change(other.id)
    await drain(db)
    assert set(await locations(db, other.id)) == {goal.description_document_id}


@pytest.mark.asyncio
async def test_scopes_coalesce_pending_but_preserve_changes_during_execution(db, agents, memory_storage, monkeypatch):
    goal, user, _ = await setup_goal(db, agents)
    first = await filing.enqueue_goal_folder_reconciliation(user_id=user.id)
    assert await filing.enqueue_goal_folder_reconciliation(user_id=user.id) == first
    running = await db.get(MemoryAutomationJob, first)
    running.status = "running"
    await db.commit()
    second = await filing.enqueue_goal_folder_reconciliation(user_id=user.id)
    assert second != first
    # Force every fan-out and document batch to need a durable continuation.
    monkeypatch.setattr(filing, "BATCH_SIZE", 1)
    other_goal = await make_goal(title=goal.title, description="<p>Autre</p>", agent_id=agents[0].id)
    db.add(other_goal)
    await db.commit()
    await filing.enqueue_goal_folder_reconciliation()
    await drain(db)
    folders = list(await db.scalars(select(DocumentTag).where(DocumentTag.user_id == user.id, DocumentTag.goal_id.is_not(None))))
    assert {tag.goal_id for tag in folders} == {goal.id, other_goal.id}
    assert len(await locations(db, user.id)) == 4
    assert len({tag.parent_id for tag in folders}) == 1


@pytest.mark.asyncio
async def test_task_document_provenance_triggers_goal_filing(db, agents, memory_storage):
    from app.task import Task, TaskStatus
    from app.memory.document_service import create_document
    from app.memory.lifecycle import register_memory_item_observer, unregister_memory_item_observer

    goal, user, _ = await setup_goal(db, agents)
    task = Task(id=uuid4(), agent_id=agents[0].id, goal_id=goal.id,
                label="Livrable", objective="<p>Rédiger</p>", status=TaskStatus.SUCCESS)
    db.add(task)
    await db.commit()
    register_memory_item_observer("test_goal_folders", filing.on_document_change)
    try:
        document = await create_document(owner_agent_id=agents[0].id, title="Rapport", content="<p>Résultat</p>", task_id=task.id)
        await drain(db)
        assert document.id in await locations(db, user.id)
        existing = await create_document(owner_agent_id=agents[0].id, title="Annexe", content="<p>Annexe</p>", task_id=None)
        await service.add_item_source(existing.id, MemorySourceCreate(source_kind="task", source_ref=f"task:{task.id}"), actor_agent_id=agents[0].id)
        await drain(db)
        assert existing.id in await locations(db, user.id)
    finally:
        unregister_memory_item_observer("test_goal_folders")


@pytest.mark.asyncio
async def test_goal_and_new_user_events_queue_filing_and_follow_renames(db, agents, memory_storage):
    from app.goal import GoalCreate, GoalUpdate, goal_service, register_goal_observer, unregister_goal_observer
    from app.goal.schemas import GoalAgentReferrerInput
    from core.user import UserCreate, register_user_access_observer, unregister_user_access_observer, user_service

    _, owner, _ = await setup_goal(db, agents)
    register_goal_observer("test_goal_folders", filing.on_goal_change)
    register_user_access_observer("test_goal_folders", filing.on_user_change)
    try:
        created = await goal_service.create(GoalCreate(
            title="Événements", description="<p>Suivre</p>", agent_id=agents[0].id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=agents[1].id), active=False,
        ))
        await drain(db)
        folder = await db.scalar(select(DocumentTag).where(DocumentTag.user_id == owner.id, DocumentTag.goal_id == created.id))
        assert folder is not None
        await goal_service.update(created.id, GoalUpdate(expected_revision=created.revision, title="Renommé"))
        await drain(db)
        await db.refresh(folder)
        assert folder.name == "Renommé"
        # A new user gains access to an existing public Goal document.
        item = await db.get(MemoryItem, created.tracking_document_id)
        from app.memory.schemas import DocumentGlobalAccessUpdate
        await service.set_document_global_access(item.id, DocumentGlobalAccessUpdate(
            expected_revision=item.revision, global_access=1,
        ), actor_agent_id=agents[0].id)
        user = await user_service.create(UserCreate(
            email=f"new-{uuid4()}@example.com", password="strong-password-123", language="fr",
        ))
        await drain(db)
        assert set(await locations(db, user.id)) == {created.tracking_document_id}
    finally:
        unregister_goal_observer("test_goal_folders")
        unregister_user_access_observer("test_goal_folders")


@pytest.mark.asyncio
async def test_sharing_change_queues_new_reader_filing(db, agents, memory_storage):
    from app.memory import item_sharing
    from app.memory.lifecycle import register_memory_item_observer, unregister_memory_item_observer
    from app.memory.schemas import DocumentSharingLevelUpdate, DocumentSharingGrantUpdate

    goal, user, reader = await setup_goal(db, agents)
    register_memory_item_observer("test_goal_folders", filing.on_document_change)
    try:
        item = await db.get(MemoryItem, goal.tracking_document_id)
        await item_sharing.update_level(item.id, DocumentSharingLevelUpdate(
            expected_lock_version=item.lock_version, level="private", can_write=False,
            grants=[DocumentSharingGrantUpdate(kind="user", id=reader.id, can_write=False)],
        ), AgentManagementScope(user.id, frozenset({agents[0].id})))
        await drain(db)
        assert set(await locations(db, reader.id)) == {item.id}
    finally:
        unregister_memory_item_observer("test_goal_folders")


@pytest.mark.asyncio
async def test_reconciliation_api_is_admin_only_and_preserves_filters(client):
    path = "/api/memory/goal-folders/reconcile"
    assert (await client.post(path, json={})).status_code == 401
    credentials = {"email": "filing-admin@example.com", "password": "strong-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    for filters in ({}, {"user_id": 1}, {"goal_id": str(uuid4())}, {"user_id": 1, "goal_id": str(uuid4())}):
        response = await client.post(path, headers=headers, json=filters)
        assert response.status_code == 202, response.text
        assert "job_id" in response.json()
    ordinary = {"email": "filing-reader@example.com", "password": "strong-password-123"}
    assert (await client.post("/api/auth/users", headers=headers, json=ordinary)).status_code == 201
    login = await client.post("/api/auth/login-json", json=ordinary)
    denied = await client.post(path, headers={"Authorization": f"Bearer {login.json()['access_token']}"}, json={})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_filing_respects_committed_manual_move_and_recovers_after_rollback(
    committed_database, memory_storage, monkeypatch,
):
    import asyncio
    from app.agent.models import Agent, Title
    from core.database import get_db_session
    from app.memory import document_structure

    async with get_db_session() as db:
        manager = UserModel(email="concurrent-filing@example.test", hashed_password="unused", language="fr", is_active=True)
        title = Title(label="Test", gender="X")
        db.add_all([manager, title])
        await db.flush()
        owner = Agent(title_id=title.id, first_name="Folder", last_name="Agent", code="folder-test", user_id=manager.id, agent_driver="internal")
        db.add(owner)
        await db.flush()
        goal, user, _ = await setup_goal(db, (owner, owner))
        request = filing.GoalFolderRequest(user_id=user.id, goal_id=goal.id)
        manual = await document_tags.write_tag(user.id, DocumentTagWrite(name="Choix manuel"))
        scope = AgentManagementScope(user.id, frozenset({owner.id}))
        manual_id, document_id, user_id, goal_id = manual.id, goal.description_document_id, user.id, goal.id

    started = asyncio.Event()

    async def run():
        async with get_db_session():
            started.set()
            await filing.process_goal_folder_job(uuid4(), request)

    async with get_db_session():
        await document_tags.lock_tree(user_id)
        worker = asyncio.create_task(run())
        await started.wait()
        await document_tags.move_document(scope, document_id, manual_id)
    await asyncio.wait_for(worker, timeout=10)
    async with get_db_session() as db:
        result = await locations(db, user_id)
        assert result[document_id] == manual_id
        folder = await db.scalar(select(DocumentTag).where(DocumentTag.user_id == user_id, DocumentTag.goal_id == goal_id))
        await document_tags.remove_tag(user_id, folder.id, confirmed=True)

    original = document_structure.sync_folder_structure

    async def unavailable(_user_id):
        raise RuntimeError("storage temporarily unavailable")

    monkeypatch.setattr(document_structure, "sync_folder_structure", unavailable)
    with pytest.raises(RuntimeError, match="temporarily"):
        async with get_db_session():
            await filing.process_goal_folder_job(uuid4(), request)
    monkeypatch.setattr(document_structure, "sync_folder_structure", original)
    # Two independent workers converge after the failed transaction, without duplicates.
    await asyncio.gather(run(), run())
    async with get_db_session() as db:
        result = await locations(db, user_id)
        assert len(result) == 2 and result[document_id] == manual_id
        folders = list(await db.scalars(select(DocumentTag.id).where(DocumentTag.user_id == user_id, DocumentTag.goal_id == goal_id)))
        assert len(folders) == 1
