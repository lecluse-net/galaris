"""Canonical contacts remain private across generic file and HTTP access."""

import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.contact import service
from app.contact.schemas import ContactCreate, ContactUpdate
from app.file_share import mcp, resource_service as files
from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_uri import ResourceRevisionConflict
from app.memory import ContactCoordinates
from app.memory.models import MemoryItem
from app.memory.tests.conftest import agents, memory_storage
from app.tools import McpToolContext
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.auth_service import create_access_token


@pytest.mark.asyncio
async def test_contact_files_use_live_directory_and_private_snapshots(db, agents, memory_storage):
    owner, other = agents
    contact = await service.create_contact(ContactCreate(agent_id=owner.id, display_name="Synthetic Person",
        email="synthetic@example.org", coordinates=ContactCoordinates.model_validate({
            "phone_numbers": [{"number": "+33 1 23 45 67 89", "country": "FR"}],
            "postal_addresses": [{"city": "Synthetic City", "country": "FR"}],
        })))
    uri = f"galaris://contact/{contact.memory_item_id}"
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    peer = ResourceContext(agent_id=other.id, runtime="internal")
    tool_ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    await db.commit()
    db.expunge_all()

    page = json.loads(await mcp.list_files(tool_ctx, "galaris://contact/"))
    assert [(row["uri"], row["name"]) for row in page["entries"]] == [(uri, "Synthetic Person")]
    descriptor = await files.resource_info(ctx, uri)
    assert {"copy", "info", "read", "write", "edit"} <= set(descriptor.capabilities)
    assert descriptor.media_type == "application/vnd.galaris.contact+json"
    exported = await files.resource_copy(ctx, uri, "file://")
    assert json.loads((await files.resource_read(ctx, exported.uri)).content)["display_name"] == "Synthetic Person"
    text = json.loads(await mcp.read_file(tool_ctx, uri))
    payload = json.loads(text["content"])
    assert payload.pop("etag") == text["etag"] == descriptor.etag
    assert payload == contact.model_dump(mode="json", exclude_none=True)
    partial = await files.resource_read(ctx, uri, max_chars=25)
    assert partial.next_offset == 25
    assert partial.content + (await files.resource_read(ctx, uri, offset=25)).content == text["content"]
    assert [hit.resource.uri for hit in (await files.resource_search(ctx, "galaris://contact/", "synthetic@example.org")).hits] == [uri]
    assert not (await files.resource_list(peer, "galaris://contact/")).entries
    assert not (await files.resource_search(peer, "galaris://contact/", "Synthetic")).hits
    for inaccessible in (uri, f"galaris://contact/{uuid4()}"):
        with pytest.raises(FileNotFoundError):
            await files.resource_info(peer, inaccessible)
        with pytest.raises(FileNotFoundError):
            await files.resource_read(peer, inaccessible)
    # Contact writes now have their own persistence/concurrency contract below;
    # deletion and relocation of the canonical business object remain forbidden.
    with pytest.raises(PermissionError):
        await files.resource_delete(ctx, uri)
    with pytest.raises(PermissionError):
        await files.resource_move(ctx, uri, "console://contact.json")

    await service.update_contact(contact_item_id=contact.memory_item_id, data=ContactUpdate(display_name="Renamed Person"))
    assert (await files.resource_info(ctx, uri)).name == "Renamed Person"
    await service.forget_contact(contact_item_id=contact.memory_item_id)
    assert not (await files.resource_list(ctx, "galaris://contact/")).entries
    with pytest.raises(FileNotFoundError):
        await files.resource_read(ctx, uri)


@pytest.mark.asyncio
async def test_contact_files_write_and_edit_validate_preserve_identity_and_reject_stale_or_foreign_changes(db, agents, memory_storage):
    owner, other = agents
    contact = await service.create_contact(ContactCreate(agent_id=owner.id, display_name="Synthetic Editable",
        email="editable@example.org", coordinates=ContactCoordinates.model_validate({
            "phone_numbers": [{"number": "+33 1 23 45 67 89", "country": "FR"}],
            "postal_addresses": [{"city": "Synthetic City", "country": "FR"}],
        })))
    uri = f"galaris://contact/{contact.memory_item_id}"
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    peer = ResourceContext(agent_id=other.id, runtime="internal")
    tool = McpToolContext(agent_id=owner.id, runtime="internal")
    original = await files.resource_read(ctx, uri)
    snapshot = json.loads(original.content)
    snapshot["display_name"] = "Synthetic Renamed"
    snapshot["coordinates"]["phone_numbers"] = []
    written = json.loads(await mcp.write_file(tool, uri, json.dumps(snapshot), expected_etag=original.etag))
    assert written["uri"] == uri and written["state"] == "written"
    await db.commit()
    db.expunge_all()
    current = await files.resource_read(ctx, uri)
    changed = json.loads(current.content)
    assert changed["display_name"] == "Synthetic Renamed"
    assert changed["coordinates"]["phone_numbers"] == []
    assert changed["coordinates"]["postal_addresses"] == snapshot["coordinates"]["postal_addresses"]
    assert changed["identities"] == snapshot["identities"]
    assert current.etag != original.etag
    with pytest.raises(ResourceRevisionConflict):
        await files.resource_write(ctx, uri, b'{"display_name":"Stale"}', expected_etag=original.etag)
    with pytest.raises(ValueError, match="expected_etag"):
        await files.resource_write(ctx, uri, b'{"display_name":"Missing token"}')
    for payload in (b"invalid JSON", b"[]", b'{"display_name":" "}',
                    b'{"coordinates":{"phone_numbers":[{"number":"1"}]}}',
                    b'{"identities":[]}', b'{"owner_agent_id":999999}', b'{"unknown":true}'):
        with pytest.raises(ValueError):
            await files.resource_write(ctx, uri, payload, expected_etag=current.etag)
    for inaccessible in (uri, f"galaris://contact/{uuid4()}"):
        with pytest.raises(FileNotFoundError):
            await files.resource_write(peer, inaccessible, b'{"display_name":"Foreign"}', expected_etag=current.etag)
    # A focused line edit goes through the same validated contact mutation.
    line = next(index for index, text in enumerate(current.content.splitlines(), 1) if '"display_name": "Synthetic Renamed"' in text)
    await mcp.edit_file(tool, uri, line, line, '  "display_name": "Synthetic Edited",', expected_etag=current.etag)
    edited = await files.resource_read(ctx, uri)
    assert json.loads(edited.content)["display_name"] == "Synthetic Edited"
    assert (await files.resource_info(ctx, uri)).name == "Synthetic Edited"
    assert json.loads(edited.content)["identities"] == snapshot["identities"]
    await files.resource_write(ctx, uri, b'{"coordinates":{"phone_numbers":[{"number":"+41 21 555 01 02","country":"CH"}]}}', expected_etag=edited.etag)
    partial = await files.resource_read(ctx, uri)
    assert json.loads(partial.content)["coordinates"]["postal_addresses"] == snapshot["coordinates"]["postal_addresses"]
    await files.resource_write(ctx, uri, b'{"coordinates":{"phone_numbers":[],"postal_addresses":[]}}', expected_etag=partial.etag)
    cleared = await service.get_contact(agent_id=owner.id, contact_item_id=contact.memory_item_id)
    assert cleared.display_name == "Synthetic Edited" and cleared.coordinates == ContactCoordinates()


@pytest.mark.asyncio
async def test_contact_file_pagination_keeps_the_501st_row_and_filters_before_paging(db, agents):
    owner, other = agents
    content = "Synthetic contact projection."
    for agent, count in ((owner, 501), (other, 1)):
        db.add_all([MemoryItem(owner_agent_id=agent.id, memory_resource_id=f"synthetic-contact-{uuid4().hex}",
            memory_content=content, memory_content_hash=hashlib.sha256(content.encode()).hexdigest(),
            memory_size_bytes=len(content.encode()), search_title=f"Contact — Synthetic {index:04d}",
            metadata_={"display_name": f"Synthetic {index:04d}"}, source_managed=True,
            managed_source_kind="messenger_contact", managed_source_ref=f"synthetic-{uuid4().hex}",
            memory_read_only=True) for index in range(count)])
    await db.commit()
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    first = await files.resource_list(ctx, "galaris://contact/", max_entries=500)
    second = await files.resource_list(ctx, "galaris://contact/", max_entries=500, cursor=first.next_cursor)
    assert len(first.entries) == 500 and first.next_cursor == "500"
    assert len(second.entries) == 1 and second.next_cursor is None
    assert len({row.uri for row in first.entries + second.entries}) == 501
    first_search = await files.resource_search(ctx, "galaris://contact/", "Synthetic", max_results=500)
    second_search = await files.resource_search(ctx, "galaris://contact/", "Synthetic", max_results=500, cursor=first_search.next_cursor)
    assert len(first_search.hits) == 500 and len(second_search.hits) == 1
    filtered = await files.resource_search(ctx, "galaris://contact/", "Synthetic 0500", max_results=1)
    assert [hit.resource.uri for hit in filtered.hits] == [second.entries[0].uri]


@pytest.mark.asyncio
async def test_contact_browser_http_requires_domain_rights_and_managed_owner(client, memory_storage):
    async with get_db_session() as db:
        title = Title(label="Synthetic file contacts", gender="X")
        db.add(title)
        users = [UserModel(email=f"contact-files-{index}@example.org", hashed_password="unused", is_active=True)
            for index in range(2)]
        db.add_all(users)
        roles = []
        for code in ("CONTACT_ACCESS", "FILE_ACCESS", "CONTACT_EDIT"):
            privilege = await db.scalar(select(Privilege).where(Privilege.code == code))
            role = Role(code=f"synthetic-contact-files-{code}", privileges=[privilege])
            db.add(role)
            roles.append(role)
        await db.flush()
        headers = []
        for user, role in zip((users[0], users[1], users[0]), roles, strict=True):
            db.add(Assignment(user_id=user.id, role_id=role.id))
            headers.append({"Authorization": "Bearer " + create_access_token({
                "sub": user.email, "user_id": user.id, "role_id": role.id})})
        agents = [Agent(title_id=title.id, user_id=users[index].id, code=f"synthetic-contact-files-{index}",
            first_name="Synthetic", last_name=f"Owner {index}") for index in range(2)]
        db.add_all(agents)
        await db.flush()
        contacts = [await service.create_contact(ContactCreate(agent_id=agent.id,
            display_name=f"Synthetic Contact {index}", email=f"person-{index}@example.org"))
            for index, agent in enumerate(agents)]
        owner, foreign = [agent.id for agent in agents]
        uri, foreign_uri = [f"galaris://contact/{contact.memory_item_id}" for contact in contacts]

    base = "/api/file-share/browser/"
    contact_url = f"/api/contacts/{contacts[0].memory_item_id}"
    assert (await client.get(contact_url)).status_code == 401
    assert (await client.get(contact_url, headers=headers[1])).status_code == 403
    assert (await client.get(f"/api/contacts/{contacts[1].memory_item_id}", headers=headers[0])).status_code == 404
    assert (await client.get(f"/api/contacts/{uuid4()}", headers=headers[0])).status_code == 404
    for allowed in (headers[0], headers[2]):
        response = await client.get(contact_url, headers=allowed)
        assert response.status_code == 200, response.text
        assert response.json()["memory_item_id"] == str(contacts[0].memory_item_id)
        assert response.json()["display_name"] == "Synthetic Contact 0"
    params = {"agent_id": owner, "uri": "galaris://contact/"}
    assert (await client.get(base + "entries", params=params)).status_code == 401
    root = await client.get(base + "entries", params={**params, "uri": "galaris://"}, headers=headers[0])
    assert [row["uri"] for row in root.json()["entries"]] == ["galaris://contact/"]
    for endpoint in ("entries", "search", "info", "content"):
        request = {**params, "uri": "galaris://contact/" if endpoint in {"entries", "search"} else uri}
        if endpoint == "search":
            request["query"] = "person-0@example.org"
        assert (await client.get(base + endpoint, params=request, headers=headers[1])).status_code == 403
        assert (await client.get(base + endpoint, params={**request, "agent_id": foreign}, headers=headers[0])).status_code == 404
        response = await client.get(base + endpoint, params=request, headers=headers[0])
        assert response.status_code == 200, response.text
        assert (await client.get(base + endpoint, params=request, headers=headers[2])).status_code == 200
        reopened = await client.get(base + endpoint, params=request, headers=headers[0])
        assert reopened.content == response.content
        if endpoint == "content":
            assert response.json()["display_name"] == "Synthetic Contact 0"
        if endpoint == "entries":
            assert [row["uri"] for row in response.json()["entries"]] == [uri]
    for endpoint in ("info", "content"):
        assert (await client.get(base + endpoint, params={**params, "uri": foreign_uri}, headers=headers[0])).status_code == 404
    assert (await client.patch(base + "entry", params={**params, "uri": uri}, json={"name": "Changed"}, headers=headers[0])).status_code == 403
    assert (await client.delete(base + "entry", params={**params, "uri": uri}, headers=headers[0])).status_code == 403
