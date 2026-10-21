"""History metadata preserves UTF-8 sizes and permissions without loading JSON snapshots."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select

from app.dataset import service
from app.dataset.models import Dataset, DatasetRevision
from app.share import ShareGrant
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_history_preserves_exact_metadata_and_does_not_materialize_revision_contents(db, agents):
    owner, reader = agents
    owner_id, reader_id = owner.id, reader.id
    now = datetime.now(timezone.utc)
    contents = [json.dumps({"synthetic": index, "value": "é🙂" * 25000}, ensure_ascii=False, indent=2) + "\n"
                for index in range(1, 65)]
    dataset = Dataset(owner_agent_id=owner_id, title="Synthetic history", content=contents[-1], revision=64)
    empty = Dataset(owner_agent_id=owner_id, title="Synthetic empty history", content="null")
    db.add_all([dataset, empty])
    await db.flush()
    identity, empty_id = dataset.id, empty.id
    revisions = [DatasetRevision(dataset_id=identity, revision=index, content=content,
                                created_at=now + timedelta(seconds=index),
                                author_agent_id=owner_id if index % 2 else None,
                                author_user_id=owner.user_id if index % 2 == 0 else None)
                 for index, content in enumerate(contents, start=1)]
    db.add_all(revisions)
    await db.commit()
    expected = [{"revision": row.revision, "size": len(row.content.encode("utf-8")),
                 "created_at": row.created_at.isoformat(), "author_user_id": row.author_user_id,
                 "author_agent_id": row.author_agent_id} for row in reversed(revisions)]
    db.expunge_all()
    loaded = []

    def materialized(_session, instance):
        if isinstance(instance, DatasetRevision):
            loaded.append(len(instance.content.encode("utf-8")))

    event.listen(db.sync_session, "loaded_as_persistent", materialized)
    try:
        page = await service.history(identity, owner_id)
    finally:
        event.remove(db.sync_session, "loaded_as_persistent", materialized)
    assert page == {"total": 64, "items": expected[:50]}
    assert (await service.history(identity, owner_id, page=2))["items"] == expected[50:]
    assert (await service.history(identity, owner_id, page_size=500))["items"] == expected
    assert await service.history(identity, owner_id, page=3) == {"total": 64, "items": []}
    assert await service.history(empty_id, owner_id) == {"total": 0, "items": []}
    with pytest.raises(service.DatasetNotFoundError):
        await service.history(identity, reader_id)
    grant = ShareGrant(share_id=Dataset.share_for(identity), agent_id=reader_id, can_write=False)
    db.add(grant)
    await db.commit()
    assert await service.history(identity, reader_id) == page
    await db.delete(grant)
    await db.commit()
    with pytest.raises(service.DatasetNotFoundError):
        await service.history(identity, reader_id)
    # The payload is still available to explicit revision reads and restoration.
    assert (await service.revision(identity, owner_id, 1)).content == contents[0]
    restored = await service.restore(identity, owner_id, number=1, expected_revision=64)
    assert restored.revision == 65 and restored.content == contents[0]
    assert (await service.history(identity, owner_id))["total"] == 65
    report = {"page_revisions": len(page["items"]), "loaded_revision_bytes": sum(loaded)}
    destination = Path(__file__).resolve().parents[4] / "artifacts/dataset-history-reads.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    assert report["loaded_revision_bytes"] == 0, report


@pytest.mark.asyncio
async def test_history_http_keeps_permissions_and_metadata_only_response(client):
    password = "synthetic-history-reader-password"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "DATASET_READ"))
        role = Role(code="synthetic-history-reader", privileges=[privilege])
        password_hash = encrypt_password(password)
        users = [UserModel(email=f"history-reader-{index}@example.com", hashed_password=password_hash,
                           is_active=True) for index in range(3)]
        db.add_all([role, *users])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users[:2]])
        content = '{ "synthetic": "é🙂" }\n'
        dataset = Dataset(owner_user_id=users[0].id, title="Synthetic HTTP history", content=content)
        db.add(dataset)
        await db.flush()
        identity = dataset.id
        db.add(DatasetRevision(dataset_id=identity, revision=1, content=content, author_user_id=users[0].id))
    path = f"/api/datasets/{identity}/revisions"
    assert (await client.get(path)).status_code == 401
    headers = []
    for index in range(3):
        client.cookies.clear()  # Each actor has an independent browser session.
        login = await client.post("/api/auth/login-json", json={
            "email": f"history-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert (await client.get(path, headers=headers[2])).status_code == 403
    assert (await client.get(path, headers=headers[1])).status_code == 404
    response = await client.get(path, params={"page_size": 500}, headers=headers[0])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["size"] == len(content.encode("utf-8"))
    assert "content" not in response.json()["items"][0]
    assert (await client.get(path, headers=headers[0])).json() == response.json()
    async with get_db_session() as db:
        dataset = await db.get(Dataset, identity)
        dataset.soft_delete()
    assert (await client.get(path, headers=headers[0])).status_code == 404
