"""Ownership preserves Dataset content, ACLs and the live management boundary."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.dataset import ownership, service
from app.dataset.models import DatasetRevision
from core.user import HumanActor, UserModel


@pytest.mark.asyncio
async def test_transfer_keeps_former_owner_as_editor_and_rejects_stale_or_unmanaged_targets(db, agents):
    first, second = agents
    user = UserModel(email=f"dataset-owner-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    actor = AgentManagementScope(user.id, frozenset({first.id, second.id}))
    limited = AgentManagementScope(user.id, frozenset({first.id}))
    dataset = await service.create(first.id, title="Synthetic ownership", content='{"precise":9007199254740993}')
    dataset.metadata_ = {"engine_dataset": True, "engine_managed": True, "engine_agent": first.id}
    await db.flush()
    version = dataset.lock_version
    choices = await ownership.options(dataset.id, limited)
    assert choices.current_user_id == limited.user_id
    assert choices.owner.id == first.id
    assert {(p.kind, p.id) for p in choices.options} == {("agent", first.id), ("user", user.id)}
    with pytest.raises(service.DatasetPermissionError):
        await ownership.transfer(dataset.id, limited, kind="agent", principal=second.id, expected_lock_version=version)
    with pytest.raises(service.DatasetConflictError):
        await ownership.transfer(dataset.id, actor, kind="user", principal=user.id, expected_lock_version=version + 1)
    await service.set_grant(dataset.id, first.id, kind="agent", principal=second.id, can_write=True, expected_lock_version=version)
    version = dataset.lock_version
    transferred = await ownership.transfer(dataset.id, actor, kind="agent", principal=second.id, expected_lock_version=version)
    assert transferred.owner_agent_id == second.id and transferred.owner_user_id is None
    assert transferred.lock_version == version + 1
    assert (await service.record(dataset.id, first.id, write=True)).id == dataset.id
    assert not (await ownership.options(dataset.id, limited)).options
    with pytest.raises(service.DatasetNotFoundError):
        await ownership.transfer(dataset.id, limited, kind="user", principal=user.id, expected_lock_version=dataset.lock_version)
    await ownership.transfer(dataset.id, actor, kind="user", principal=user.id, expected_lock_version=dataset.lock_version)
    assert dataset.owner_user_id == user.id and dataset.owner_agent_id is None
    assert (await service.record(dataset.id, second.id, write=True)).id == dataset.id
    assert (await service.describe(dataset, HumanActor(user.id)))["can_manage"]
    assert dataset.content == '{"precise":9007199254740993}' and dataset.revision == 1
    revisions = list(await db.scalars(select(DatasetRevision).where(DatasetRevision.dataset_id == dataset.id)))
    assert len(revisions) == 1 and revisions[0].content == dataset.content
    dataset.read_only = True
    await db.flush()
    assert not (await ownership.options(dataset.id, actor)).options
    with pytest.raises(service.DatasetNotFoundError):
        await ownership.transfer(dataset.id, actor, kind="agent", principal=first.id, expected_lock_version=4)


@pytest.mark.asyncio
async def test_owner_http_requires_edit_privilege_and_management_and_restricts_user_targets(client):
    from app.dataset.models import Dataset
    from app.share import ShareGrant
    from core.authorize import Assignment, Privilege
    from core.authorize.models import Role
    from core.database import get_db_session
    from core.user import encrypt_password

    password = "synthetic-ownership-password"
    async with get_db_session() as db:
        privileges = {p.code: p for p in await db.scalars(select(Privilege).where(Privilege.code.in_(["DATASET_EDIT", "DATASET_READ", "DATASET_ADMIN"])))}
        roles = [Role(code=f"synthetic-dataset-owner-{index}", privileges=[privileges[code]])
                 for index, code in enumerate(["DATASET_EDIT", "DATASET_READ", "DATASET_ADMIN"])]
        users = [UserModel(email=f"dataset-owner-{index}@example.com", hashed_password=encrypt_password(password), is_active=True) for index in range(5)]
        db.add_all([*roles, *users])
        await db.flush()
        db.add_all([Assignment(user_id=users[index].id, role_id=roles[role].id, is_default=True) for index, role in [(0, 0), (1, 0), (2, 1), (4, 2)]])
        dataset = Dataset(owner_user_id=users[0].id, title="Synthetic owner HTTP", content='{"kept":true}',
            metadata_={"engine_dataset": True, "engine_managed": True})
        db.add(dataset)
        await db.flush()
        db.add_all([ShareGrant(share_id=dataset.share_id, user_id=users[index].id, can_write=True) for index in [1, 2, 4]])
        identity = dataset.id
        user_ids = [user.id for user in users]
    path = f"/api/datasets/{identity}/owner"
    body = {"kind": "user", "principal": user_ids[1], "expected_lock_version": 1}
    assert (await client.get(path)).status_code == 401
    headers = []
    for index in range(5):
        client.cookies.clear()  # Each actor has an independent browser session.
        login = await client.post("/api/auth/login-json", json={"email": f"dataset-owner-{index}@example.com", "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert (await client.get(path, headers=headers[3])).status_code == 403
    assert (await client.patch(path, json=body, headers=headers[2])).status_code == 403
    assert (await client.patch(path, json=body, headers=headers[1])).status_code == 404
    assert (await client.patch(path, json=body, headers=headers[0])).status_code == 403
    options = (await client.get(path, headers=headers[0])).json()
    assert options["owner"]["id"] == user_ids[0]
    assert [(p["kind"], p["id"]) for p in options["options"]] == [("user", user_ids[0])]
    assert (await client.patch(path, json={**body, "expected_lock_version": 2}, headers=headers[4])).status_code == 409
    response = await client.patch(path, json=body, headers=headers[4])
    assert response.status_code == 200, response.text
    assert response.json()["owner_user_id"] == user_ids[1]
    assert response.json()["can_write"] and response.json()["can_delete"]
    assert response.json()["revision"] == 1 and response.json()["content"] == '{"kept":true}'
    assert (await client.get(path, headers=headers[0])).json()["options"] == []
    updated = (await client.get(path, headers=headers[1])).json()
    assert updated["owner"]["id"] == user_ids[1] and updated["options"]
    resource_path = f"/api/datasets/{identity}"
    assert (await client.delete(resource_path, params={"expected_lock_version": 2}, headers=headers[0])).status_code == 404
    assert (await client.delete(resource_path, params={"expected_lock_version": 1}, headers=headers[1])).status_code == 409
    assert (await client.delete(resource_path, params={"expected_lock_version": 2}, headers=headers[1])).status_code == 200
    assert (await client.get(resource_path, headers=headers[1])).status_code == 404
