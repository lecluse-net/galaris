"""Goal tracking stays unclassified until each user explicitly files it.

These replace the retired automatic filing/rename/fan-out contracts. Ordinary
folder CRUD, ACL and concurrency remain covered by document tag/resource tests.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.document import Document, DocumentAutomationJob, DocumentTag, DocumentTagAssignment
from app.document import document_tags
from app.document.dbadmin import retire_goal_filing
from app.document.library_queries import browse_document_library
from app.document.models import DocumentListPosition
from app.document.schemas import DocumentLibraryRequest, DocumentTagWrite
from app.goal import GoalCreate, GoalUpdate, goal_service
from app.goal.schemas import GoalAgentReferrerInput
from core.user import UserModel


async def create_goal(db, agents):
    user = UserModel(email=f"filing-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    agents[0].user_id = user.id
    await db.commit()
    goal = await goal_service.create(GoalCreate(
        title="Synthetic objective", description="<p>Objective</p>", agent_id=agents[0].id,
        referrer=GoalAgentReferrerInput(type="AGENT", agent_id=agents[1].id), active=False,
    ))
    return goal, user


@pytest.mark.asyncio
async def test_tracking_is_in_unclassified_list_and_never_in_tree_by_default(db, agents, memory_storage):
    goal, user = await create_goal(db, agents)
    tracking = await db.get(Document, goal.tracking_document_id)
    assert "document_path" not in tracking.metadata_
    assert await db.scalar(select(DocumentTag.id).where(DocumentTag.user_id == user.id)) is None
    assert await db.scalar(select(DocumentTagAssignment.id).where(DocumentTagAssignment.document_id == tracking.id)) is None
    assert await db.scalar(select(DocumentListPosition.id).where(
        DocumentListPosition.document_id == tracking.id, DocumentListPosition.at_root.is_(True))) is None
    for classification, expected in (("unclassified", {tracking.id}), ("root", set()), ("classified", set())):
        page = await browse_document_library(DocumentLibraryRequest(classification=classification),
            managed_agent_ids={agents[0].id}, user_id=user.id)
        assert {entry.item.id for entry in page.entries} == expected
    assert await db.scalar(select(DocumentAutomationJob.id).where(DocumentAutomationJob.kind == "goal_folder_reconcile")) is None


@pytest.mark.asyncio
async def test_manual_classification_survives_goal_renaming_and_reconciliation(db, agents, memory_storage):
    goal, user = await create_goal(db, agents)
    folder = await document_tags.write_tag(user.id, DocumentTagWrite(name="My projects"))
    scope = AgentManagementScope(user.id, frozenset({agents[0].id}))
    await document_tags.move_document(scope, goal.tracking_document_id, folder.id)
    updated = await goal_service.update(goal.id, GoalUpdate(expected_revision=goal.revision, title="Renamed objective"))
    await retire_goal_filing(db)
    await db.commit()
    assert await db.scalar(select(DocumentTagAssignment.tag_id).where(
        DocumentTagAssignment.document_id == goal.tracking_document_id)) == folder.id
    assert (await db.get(DocumentTag, folder.id)).name == "My projects"
    assert updated.tracking_document_id == goal.tracking_document_id
    await document_tags.write_tag(user.id, DocumentTagWrite(name="Personal name"), folder.id)
    await retire_goal_filing(db)
    await db.commit()
    assert (await db.get(DocumentTag, folder.id)).name == "Personal name"
    await document_tags.move_document(scope, goal.tracking_document_id, None)
    await retire_goal_filing(db)
    await db.commit()
    assert await db.scalar(select(DocumentTagAssignment.id).where(
        DocumentTagAssignment.document_id == goal.tracking_document_id)) is None
    assert await db.scalar(select(DocumentListPosition.id).where(
        DocumentListPosition.document_id == goal.tracking_document_id,
        DocumentListPosition.at_root.is_(True))) is None


@pytest.mark.asyncio
async def test_old_filing_jobs_drain_without_recreating_folders(db, agents, memory_storage, monkeypatch):
    from contextlib import asynccontextmanager
    from app.document import automation
    goal, user = await create_goal(db, agents)
    job = DocumentAutomationJob(kind="goal_folder_reconcile", idempotency_key=uuid4().hex,
        payload={"user_id": user.id, "goal_id": str(goal.id)})
    db.add(job)
    await db.commit()

    @asynccontextmanager
    async def session():
        yield db
        await db.commit()

    monkeypatch.setattr(automation, "get_db_session", session)
    assert await automation.process_next()
    await db.refresh(job)
    assert job.status == "success"
    assert await db.scalar(select(DocumentTag.id).where(DocumentTag.user_id == user.id)) is None
