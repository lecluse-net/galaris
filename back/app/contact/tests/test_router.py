from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.contact import router, service
from app.memory import MessengerContactObservation, observe_messenger_contact
from core.storage import NativeFileStorage, register_storage, reset_storage_registry
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.auth_service import create_access_token


def test_contact_endpoints_reuse_memory_privileges() -> None:
    assert router.read_contacts._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        "MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN",
    ]
    for endpoint in (router.create_contact, router.update_contact, router.merge_contacts, router.forget_contact):
        assert endpoint._authorize_meta["privileges"] == ["MEMORY_EDIT"]  # pyright: ignore[reportFunctionMemberAccess]


@pytest.mark.asyncio
async def test_address_book_rename_split_and_merge_require_privilege_and_managed_agent(client, tmp_path):
    # Direct identity editing/catalogue coverage is intentionally replaced by the
    # user-facing rename, split and checkbox/merge contracts.
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        async with get_db_session() as db:
            editor = UserModel(email=f"contact-editor-{uuid4()}@example.test", hashed_password="unused", is_active=True)
            reader = UserModel(email=f"contact-reader-{uuid4()}@example.test", hashed_password="unused", is_active=True)
            roles = []
            for code in ("MEMORY_EDIT", "MEMORY_ACCESS"):
                role = Role(code=f"contact-{uuid4()}", privileges=list((await db.scalars(
                    select(Privilege).where(Privilege.code == code)
                )).all()))
                db.add(role)
                roles.append(role)
            title = Title(label="Synthetic contact editor", gender="X")
            db.add_all([editor, reader, title])
            await db.flush()
            for user, role in zip((editor, reader), roles):
                db.add(Assignment(user_id=user.id, role_id=role.id))
            agents = [Agent(code=f"contact-owner-{uuid4()}", first_name="Test", last_name="Owner",
                title_id=title.id, user_id=user.id, agent_driver="internal") for user in (editor, reader)]
            db.add_all(agents)
            await db.flush()
            contact_ids = [await observe_messenger_contact(MessengerContactObservation(
                owner_agent_id=agent.id, messaging_id="matrix", user_id="@synthetic:example.test", display_name="Original",
            )) for agent in agents]
            mail_id = await observe_messenger_contact(MessengerContactObservation(
                owner_agent_id=agents[0].id, messaging_id="mail", user_id="known@example.org", display_name="Mail alias"))
            merged = await service.merge_contacts(source_contact_item_id=mail_id, target_contact_item_id=contact_ids[0])
            headers = [{"Authorization": "Bearer " + create_access_token({
                "sub": user.email, "user_id": user.id, "role_id": role.id,
            })} for user, role in zip((editor, reader), roles)]

        create = {"agent_id": agents[0].id, "display_name": "  External   correspondent ", "email": "OUTSIDE@example.org"}
        assert (await client.post("/api/contacts", json=create)).status_code == 401
        assert (await client.post("/api/contacts", json=create, headers=headers[1])).status_code == 403
        assert (await client.post("/api/contacts", json={**create, "agent_id": agents[1].id}, headers=headers[0])).status_code == 404
        for invalid in ({"email": "invalid"}, {"display_name": " "}, {"galaris_user_id": editor.id}):
            assert (await client.post("/api/contacts", json={**create, **invalid}, headers=headers[0])).status_code == 422
        created = await client.post("/api/contacts", json=create, headers=headers[0])
        assert created.status_code == 201, created.text
        entry = created.json()
        assert entry["display_name"] == "External correspondent"
        assert [(i["namespace"], i["external_id"], i["galaris_user_id"]) for i in entry["identities"]] == [("mail", "outside@example.org", None)]
        assert (await client.post("/api/contacts", json={**create, "email": "outside@example.org"}, headers=headers[0])).status_code == 409
        url = f"/api/contacts/{contact_ids[0]}"
        assert (await client.patch(url, json={"display_name": "Name"})).status_code == 401
        assert (await client.patch(url, json={"display_name": "Name"}, headers=headers[1])).status_code == 403
        assert (await client.patch(f"/api/contacts/{contact_ids[1]}", json={"display_name": "Name"}, headers=headers[0])).status_code == 404
        for invalid in ({"display_name": " "}, {"display_name": "Name", "identities": []}):
            assert (await client.patch(url, json=invalid, headers=headers[0])).status_code == 422
        renamed = await client.patch(url, json={"display_name": "  Edited  contact "}, headers=headers[0])
        assert renamed.status_code == 200, renamed.text
        snapshot = renamed.json()["identities"]
        assert renamed.json()["display_name"] == "Edited contact"
        assert {i["id"] for i in snapshot} == {str(i.id) for i in merged.contact.identities}
        detached_id = next(i["id"] for i in snapshot if i["namespace"] == "mail")
        split = {"display_name": "Edited contact", "split_identity_ids": [detached_id],
                 "expected_identity_ids": [i["id"] for i in snapshot]}
        assert (await client.patch(url, json=split, headers=headers[1])).status_code == 403
        assert (await client.patch(f"/api/contacts/{contact_ids[1]}", json=split, headers=headers[0])).status_code == 404
        assert (await client.patch(url, json={"display_name": "Name", "split_identity_ids": [detached_id]}, headers=headers[0])).status_code == 422
        for invalid in ({"split_identity_ids": [str(uuid4())]}, {"split_identity_ids": split["expected_identity_ids"]},
                        {"expected_identity_ids": []}, {"split_identity_ids": [detached_id, detached_id]}):
            assert (await client.patch(url, json={**split, **invalid}, headers=headers[0])).status_code == 409
        result = await client.patch(url, json=split, headers=headers[0])
        assert result.status_code == 200, result.text
        assert [i["namespace"] for i in result.json()["identities"]] == ["matrix"]
        assert (await client.patch(url, json=split, headers=headers[0])).status_code == 409
        page = (await client.get(f"/api/contacts?agent_id={agents[0].id}&limit=500", headers=headers[0])).json()
        assert page["total"] == 3
        detached = next(item for item in page["items"] if any(i["id"] == detached_id for i in item["identities"]))
        assert detached["memory_item_id"] != str(contact_ids[0])
        assert detached["identities"][0]["external_id"] == "known@example.org"
        rejoined = await client.post(f'/api/contacts/{detached["memory_item_id"]}/merge',
            json={"target_contact_item_id": str(contact_ids[0])}, headers=headers[0])
        assert rejoined.status_code == 200, rejoined.text
        assert {i["id"] for i in rejoined.json()["contact"]["identities"]} == set(split["expected_identity_ids"])
    finally:
        reset_storage_registry()
