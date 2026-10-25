"""Personal folders never alter JSON, revisions, ownership or another user's tree."""
from datetime import datetime, timezone
import base64
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.dataset import organization, service
from app.dataset.library import LibraryFilters
from app.dataset.models import DatasetTagAssignment
from core.user import HumanActor, UserModel


@pytest.mark.asyncio
async def test_folder_lifecycle_preserves_resources_and_isolates_classification(db, agents):
    owner, other = agents
    users = [UserModel(email=f"synthetic-folder-{index}@example.test", hashed_password="unused", is_active=True) for index in range(2)]
    db.add_all(users)
    await db.flush()
    first, second = [HumanActor(item.id) for item in users]
    dataset = await service.create(first, title="Synthetic folder data", content='{"count":0}')
    dataset.global_access = 1
    await db.flush()
    folder = await organization.save_tag(first, name="Synthetic root")
    child = await organization.save_tag(first, name="Synthetic child", parent_id=folder.id)
    other_folder = await organization.save_tag(second, name="Synthetic separate folder")
    await organization.move(first, kind="dataset", identity=dataset.id, parent_id=child.id)
    await organization.move(second, kind="dataset", identity=dataset.id, parent_id=other_folder.id)
    assert (await service.list_datasets(first, filters=LibraryFilters(classification="unclassified")))["total"] == 0
    assert (await service.list_datasets(first, tag_id=child.id))["total"] == 1
    assert (await service.list_datasets(second, tag_id=other_folder.id))["total"] == 1
    with pytest.raises(service.DatasetNotFoundError):
        await organization.update_tag(second, folder.id, name="Intrusion", parent_id=None, icon=None)
    with pytest.raises(ValueError):
        await organization.move(first, kind="tag", identity=folder.id, parent_id=child.id)
    with pytest.raises(service.DatasetNotFoundError):
        await organization.move(first, kind="dataset", identity=dataset.id, parent_id=other_folder.id)
    await organization.update_tag(first, child.id, name="Synthetic renamed", parent_id=folder.id, icon="folder:blue")
    assert (await organization.remove_tag(first, folder.id))["deleted"] is False
    assert (await organization.remove_tag(first, folder.id, confirmed=True))["deleted"] is True
    assert (await service.list_datasets(first, filters=LibraryFilters(classification="unclassified")))["total"] == 1
    assert (await service.list_datasets(second, tag_id=other_folder.id))["total"] == 1
    assert dataset.content == '{"count":0}' and dataset.revision == dataset.lock_version == 1
    assert dataset.owner_user_id == first.user_id and dataset.global_access == 1


@pytest.mark.asyncio
async def test_library_combines_filters_and_paginates_in_personal_order(db, agents):
    owner, other = agents
    actor = HumanActor(owner.user_id)
    folder = await organization.save_tag(actor, name="Synthetic sorted")
    items = [await service.create(actor, title=title) for title in ["Synthetic Zeta", "Synthetic Alpha", "Synthetic Middle"]]
    hidden = await service.create(other.id, title="Synthetic hidden")
    hidden.keywords = ["synthetic-keyword"]
    for item in items:
        item.keywords = ["synthetic-keyword"]
        item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await organization.move(actor, kind="dataset", identity=item.id, parent_id=folder.id)
    await organization.sort_folder(actor, folder.id)
    filters = LibraryFilters(keyword="synthetic-keyword", owner_kind="user", owner=actor.user_id,
        created_from=datetime(2025, 1, 1, tzinfo=timezone.utc), created_until=datetime(2027, 1, 1, tzinfo=timezone.utc),
        sort_by="position", sort_desc=False)
    page = await service.list_datasets(actor, tag_id=folder.id, page_size=1, page=2, filters=filters)
    assert page["total"] == 3 and page["items"][0]["id"] == str(items[2].id)
    await organization.move(actor, kind="dataset", identity=items[0].id, parent_id=folder.id,
        anchor_kind="dataset", anchor_id=items[1].id, after=False)
    assert (await service.list_datasets(actor, tag_id=folder.id, filters=filters))["items"][0]["id"] == str(items[0].id)
    assert (await service.list_datasets(actor, filters=filters.model_copy(update={"keyword": "absent"})))["total"] == 0
    await organization.move(actor, kind="dataset", identity=items[0].id, parent_id=None)
    assert await db.scalar(select(DatasetTagAssignment).where(DatasetTagAssignment.dataset_id == items[0].id)) is None
    assert (await service.list_datasets(actor, filters=LibraryFilters(classification="unclassified")))["total"] == 1
    with pytest.raises(service.DatasetNotFoundError):
        await organization.move(actor, kind="dataset", identity=hidden.id, parent_id=folder.id)


@pytest.mark.asyncio
async def test_library_http_enforces_rbac_personal_scope_and_rejects_cycles(client):
    from core.authorize.models import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user.user_service import encrypt_password

    password = "synthetic-library-password"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "DATASET_READ"))
        role = Role(code="synthetic-library-reader", privileges=[privilege])
        users = [UserModel(email=f"synthetic-library-{index}@example.com", hashed_password=encrypt_password(password), is_active=True) for index in range(3)]
        db.add_all([role, *users]); await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users[:2]])
        dataset = await service.create(HumanActor(users[0].id), title="Synthetic HTTP data")
        identity = str(dataset.id)
    headers = []
    for index in range(3):
        client.cookies.clear()  # Each actor has an independent browser session.
        response = await client.post("/api/auth/login-json", json={"email": f"synthetic-library-{index}@example.com", "password": password})
        assert response.status_code == 200, response.text
        headers.append({"Authorization": f"Bearer {response.json()['access_token']}"})
    assert (await client.get("/api/datasets/tags")).status_code == 401
    assert (await client.post("/api/datasets/tags", headers=headers[2], json={"name": "Synthetic denied"})).status_code == 403
    created = []
    for name in ["Synthetic Alpha", "Synthetic Beta"]:
        response = await client.post("/api/datasets/tags", headers=headers[0], json={"name": name})
        assert response.status_code == 200, response.text
        created.append(response.json()["id"])
    assert (await client.get("/api/datasets/tags", headers=headers[1])).json() == []
    source = '<svg xmlns="http://www.w3.org/2000/svg">' + ' ' * 100_001 + '</svg>'
    icon = 'data:image/svg+xml;base64,' + base64.b64encode(source.encode()).decode()
    response = await client.put(f"/api/datasets/tags/{created[0]}", headers=headers[0],
        json={"name": "Synthetic Alpha", "icon": icon})
    assert response.status_code == 200, response.text
    folders = (await client.get("/api/datasets/tags", headers=headers[0])).json()
    assert next(folder for folder in folders if folder["id"] == created[0])["icon"] == icon
    response = await client.put(f"/api/datasets/{identity}/classification", headers=headers[0],
        json={"tags": [], "icon": icon})
    assert response.status_code == 200, response.text
    for format in ("PNG", "TIFF"):
        source = BytesIO()
        Image.new("RGB", (16, 16), "blue").save(source, format=format)
        raster = "data:image/octet-stream;base64," + base64.b64encode(source.getvalue()).decode()
        response = await client.put(f"/api/datasets/tags/{created[0]}", headers=headers[0],
            json={"name": "Synthetic Alpha", "icon": raster})
        assert response.status_code == 200, response.text
        folders = (await client.get("/api/datasets/tags", headers=headers[0])).json()
        saved = next(folder for folder in folders if folder["id"] == created[0])["icon"]
        assert saved.startswith("data:image/png;base64,")
    for invalid in ("data:image/png;base64,broken!", "javascript:alert(1)"):
        response = await client.put(f"/api/datasets/tags/{created[0]}", headers=headers[0],
            json={"name": "Synthetic Alpha", "icon": invalid})
        assert response.status_code == 422, response.text
    assert (await client.put(f"/api/datasets/tags/{created[0]}", headers=headers[1], json={"name": "Synthetic intrusion"})).status_code == 404
    assert (await client.post("/api/datasets/library/move", headers=headers[1], json={"kind": "dataset", "identity": identity, "parent_id": None})).status_code == 404
    responses = [await client.post("/api/datasets/library/move", headers=headers[0], json={
        "kind": "tag", "identity": created[index], "parent_id": created[1-index]}) for index in range(2)]
    assert sorted(response.status_code for response in responses) == [200, 422]
    response = await client.post("/api/datasets/library/move", headers=headers[0], json={"kind": "dataset", "identity": identity, "parent_id": created[0]})
    assert response.status_code == 200, response.text
    assert (await client.get("/api/datasets", headers=headers[0], params={"classification": "unclassified"})).json()["total"] == 0
    assert (await client.get("/api/datasets", headers=headers[0], params={"created_from": "2026-02-01T00:00:00Z", "created_until": "2026-01-01T00:00:00Z"})).status_code == 422
    facets = await client.get("/api/datasets/library/facets", headers=headers[1])
    assert facets.status_code == 200 and facets.json()["owners"] == []


@pytest.mark.asyncio
async def test_concurrent_folder_moves_cannot_commit_a_cycle(committed_database):
    import asyncio
    from core.database import get_db_session

    async with get_db_session() as db:
        human = UserModel(email="synthetic-folder-concurrency@example.com", hashed_password="unused", is_active=True)
        db.add(human); await db.flush()
        actor = HumanActor(human.id)
        folders = [await organization.save_tag(actor, name=name) for name in ["Synthetic first", "Synthetic second"]]
        identities = [folder.id for folder in folders]

    async def attempt(index):
        try:
            async with get_db_session():
                await organization.move(actor, kind="tag", identity=identities[index], parent_id=identities[1-index])
            return "saved"
        except ValueError:
            return "cycle rejected"

    results = await asyncio.gather(attempt(0), attempt(1))
    assert sorted(results) == ["cycle rejected", "saved"]
    async with get_db_session():
        rows = await organization.tags(actor)
        assert sum(row["parent_id"] is None for row in rows) == 1
