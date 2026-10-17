"""Dataset pages preserve live ACLs without fetching every JSON payload."""

import hashlib

import pytest
from sqlalchemy import inspect, select

from app.dataset import service
from app.dataset.models import Dataset, DatasetGrant
from app.agent import AgentManagementScope
from core.user import HumanActor, UserModel
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
async def test_dataset_page_batches_permissions_and_keeps_content_unloaded(db, agents):
    owner, reader = agents
    content = '{"synthetic":"' + 'é' * 20000 + '"}'
    datasets = [Dataset(owner_agent_id=owner.id, title=f"Synthetic page {index}", content=content,
                        global_access=1 if index % 2 else 0) for index in range(30)]
    db.add_all(datasets)
    await db.flush()
    db.add_all([DatasetGrant(dataset_id=item.id, agent_id=reader.id, can_write=True)
                for index, item in enumerate(datasets) if index % 2 == 0])
    hidden = Dataset(owner_agent_id=owner.id, title="Synthetic hidden", content="null")
    db.add(hidden)
    await db.flush()
    expected = {str(item.id): (index % 2 == 0) for index, item in enumerate(datasets)}
    reader_id, owner_id = reader.id, owner.id
    db.expunge_all()
    async with measured_reads(db, "dataset-page-30") as reads:
        page = await service.list_datasets(reader_id, page_size=50)
    assert page["total"] == 30 and len(page["items"]) == 30
    for item in page["items"]:
        assert item["can_write"] == expected[item["id"]]
        assert not item["can_manage"] and "content" not in item
        assert item["size"] == len(content.encode())
        assert item["checksum"] == hashlib.sha256(content.encode()).hexdigest()
    assert len(reads) <= 3
    assert "content" not in reads.result_columns
    assert all("content" in inspect(item).unloaded for item in db.identity_map.values() if isinstance(item, Dataset))
    # Reopening after revocation must use current permissions, never a cached page decision.
    grant = await db.scalar(select(DatasetGrant).where(DatasetGrant.agent_id == reader_id).limit(1))
    removed_id = str(grant.dataset_id)
    await db.delete(grant)
    await db.flush()
    reopened = await service.list_datasets(reader_id, page_size=50)
    assert removed_id not in {item["id"] for item in reopened["items"]}
    assert (await service.list_datasets(owner_id, page_size=50))["total"] == 31


@pytest.mark.asyncio
async def test_dataset_page_keeps_human_and_managed_agent_scopes_separate(db, agents):
    owner, other = agents
    human = UserModel(email="synthetic-dataset-list@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    mine = Dataset(owner_user_id=human.id, title="Synthetic human data", content="false")
    shared = Dataset(owner_agent_id=other.id, title="Synthetic shared data", content="null", read_only=True)
    managed = Dataset(owner_agent_id=owner.id, title="Synthetic managed data", content="[]")
    hidden = Dataset(owner_agent_id=other.id, title="Synthetic private data", content="{}")
    db.add_all([mine, shared, managed, hidden])
    await db.flush()
    grant = DatasetGrant(dataset_id=shared.id, user_id=human.id, can_write=True)
    db.add(grant)
    await db.flush()
    page = await service.list_datasets(HumanActor(human.id))
    entries = {item["id"]: item for item in page["items"]}
    assert set(entries) == {str(mine.id), str(shared.id)}
    assert entries[str(mine.id)]["can_manage"] and entries[str(mine.id)]["can_write"]
    assert not entries[str(shared.id)]["can_manage"] and not entries[str(shared.id)]["can_write"]
    scoped = await service.list_datasets(AgentManagementScope(human.id, frozenset({owner.id})))
    assert {item["id"] for item in scoped["items"]} == {str(mine.id), str(shared.id), str(managed.id)}
    await db.delete(grant)
    await db.flush()
    assert (await service.list_datasets(HumanActor(human.id)))["total"] == 1
    human.is_active = False
    await db.flush()
    assert (await service.list_datasets(HumanActor(human.id)))["items"] == []
