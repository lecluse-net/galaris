"""Exercise multipart upload, download and denial through the assembled API."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.storage import StoredFile


@pytest.mark.asyncio
async def test_managed_file_http_upload_download_rename_and_scope_denials(client):
    password = "Synthetic-file-password-123"
    admin_credentials = {"email": f"file-admin-{uuid4()}@example.com", "password": password}
    registered = await client.post("/api/auth/register", json=admin_credentials)
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/auth/login-json", json=admin_credentials)
    admin = {"Authorization": "Bearer " + login.json()["access_token"]}
    admin_id = (await client.get("/api/auth/me", headers=admin)).json()["id"]
    human_credentials = {"email": f"file-owner-{uuid4()}@example.com", "password": password}
    created = await client.post("/api/auth/users", headers=admin, json=human_credentials)
    assert created.status_code == 201, created.text
    human_id = created.json()["id"]
    async with get_db_session() as db:
        permissions = list(await db.scalars(select(Privilege).where(Privilege.code.in_(["MEMORY_ACCESS", "MEMORY_EDIT", "DATASET_EDIT"]))))
        role = Role(code=f"file-owner-{uuid4()}", display_name="Synthetic file owner", privileges=permissions)
        title = Title(label="Synthetic files", gender="X")
        db.add_all([role, title])
        await db.flush()
        db.add(Assignment(user_id=human_id, role_id=role.id, is_default=True))
        owner = Agent(user_id=human_id, title_id=title.id, code=f"file-owner-{uuid4()}", first_name="File", last_name="Owner")
        other = Agent(user_id=admin_id, title_id=title.id, code=f"file-other-{uuid4()}", first_name="Other", last_name="Owner")
        db.add_all([owner, other])
        await db.flush()
        owner_id, other_id = owner.id, other.id
    client.cookies.clear()
    denied = await client.post(f"/api/file-share/files?agent_id={owner_id}", files={"upload": ("x.txt", b"private")})
    assert denied.status_code in {401, 403}
    login = await client.post("/api/auth/login-json", json=human_credentials)
    human = {"Authorization": "Bearer " + login.json()["access_token"]}
    uploaded = await client.post(f"/api/file-share/files?agent_id={owner_id}", headers=human,
        files={"upload": ("Report.txt", b"Synthetic HTTP bytes", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    uri = uploaded.json()["uri"]
    assert uri.startswith("file://")
    identifier = uri.removeprefix("file://")
    async with get_db_session() as db:
        record = await db.get(StoredFile, UUID(identifier))
        assert record is not None and record.created_by == human_id
    download = f"/api/file-share/files/{identifier}/content"
    response = await client.get(download, params={"agent_id": owner_id}, headers=human)
    assert response.status_code == 200 and response.content == b"Synthetic HTTP bytes"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(download, params={"agent_id": other_id}, headers=human)).status_code == 404
    renamed = await client.patch(f"/api/file-share/files/{identifier}?agent_id={owner_id}", headers=human,
        json={"name": "Official.txt"})
    assert renamed.status_code == 200 and renamed.json()["uri"] == uri and renamed.json()["name"] == "Official.txt"
    # A manager of another agent cannot access this private owner binding either.
    assert (await client.get(download, params={"agent_id": other_id}, headers=admin)).status_code == 404

    # The browser uses the agent's canonical provider context and rechecks both scopes.
    browser = "/api/file-share/browser"
    params = {"agent_id": owner_id, "uri": uri}
    schemes = await client.get(f"{browser}/schemes", params={"agent_id": owner_id}, headers=human)
    assert schemes.status_code == 200, schemes.text
    assert "list" in next(item for item in schemes.json() if item["scheme"] == "file")["capabilities"]
    assert (await client.get(f"{browser}/schemes", params={"agent_id": other_id}, headers=human)).status_code == 404
    assert (await client.get(f"{browser}/info", params=params, headers=human)).json()["name"] == "Official.txt"
    content = await client.get(f"{browser}/content", params={**params, "preview": False}, headers=human)
    assert content.status_code == 200 and content.content == b"Synthetic HTTP bytes"
    assert content.headers["cache-control"] == "private, no-store"
    for endpoint in ["info", "content", "thumbnail"]:
        assert (await client.get(f"{browser}/{endpoint}", params={**params, "agent_id": other_id}, headers=human)).status_code == 404
        assert (await client.get(f"{browser}/{endpoint}", params={**params, "agent_id": other_id}, headers=admin)).status_code == 404
    second = await client.post("/api/file-share/files", params={"agent_id": owner_id}, headers=human,
        files={"upload": ("Official.txt", b"Another independent file", "text/plain")})
    assert second.status_code == 201
    first_page = await client.get(f"{browser}/entries", params={"agent_id": owner_id, "uri": "file://", "limit": 1}, headers=human)
    assert first_page.status_code == 200, first_page.text
    assert first_page.json()["truncated"] and first_page.json()["next_cursor"]
    second_page = await client.get(f"{browser}/entries", params={"agent_id": owner_id, "uri": "file://", "limit": 1,
        "cursor": first_page.json()["next_cursor"]}, headers=human)
    assert second_page.status_code == 200 and not second_page.json()["truncated"]
    assert {first_page.json()["entries"][0]["uri"], second_page.json()["entries"][0]["uri"]} == {uri, second.json()["uri"]}
    assert (await client.get(f"{browser}/entries", params={"agent_id": other_id, "uri": "file://"}, headers=admin)).json()["entries"] == []
    search = await client.get(f"{browser}/search", params={"agent_id": owner_id, "uri": "file://", "query": "Official"}, headers=human)
    assert search.status_code == 200, search.text
    assert {hit["resource"]["uri"] for hit in search.json()["hits"]} == {uri, second.json()["uri"]}
    assert (await client.get(f"{browser}/search", params={"agent_id": other_id, "uri": "file://", "query": "Official"}, headers=human)).status_code == 404
    document = await client.post("/api/memory/documents", headers=human, json={"owner_kind": "agent", "owner_id": owner_id,
        "actor_agent_id": owner_id, "document_type": "html", "title": "Synthetic internal attachments"})
    assert document.status_code == 201, document.text
    endpoint = f"/api/memory/documents/{document.json()['id']}/internal-attachments"
    body = {"uris": [uri, second.json()["uri"]], "resource_agent_id": owner_id,
        "expected_lock_version": document.json()["lock_version"]}
    attached = await client.put(endpoint, headers=human, json=body, params={"actor_agent_id": owner_id})
    assert attached.status_code == 200, attached.text
    assert {item["uri"] for item in attached.json()["items"]} == set(body["uris"])
    assert all(item["available"] for item in attached.json()["items"])
    personal = await client.post("/api/datasets", headers=human, json={"title": "Synthetic personal Dataset", "content": '{"value":42}'})
    assert personal.status_code == 200, personal.text
    personal_uri = f"data://{personal.json()['id']}"
    agent_view = await client.get(f"{browser}/entries", headers=human, params={"agent_id": owner_id, "uri": "data://"})
    assert personal_uri not in {item["uri"] for item in agent_view.json()["entries"]}
    management_view = await client.get(f"{browser}/search", headers=human,
        params={"agent_id": owner_id, "uri": "data://", "query": "personal", "management": True})
    assert management_view.status_code == 200, management_view.text
    assert [hit["resource"]["uri"] for hit in management_view.json()["hits"]] == [personal_uri]
    combined = await client.put(endpoint, headers=human, params={"actor_agent_id": owner_id}, json={**body,
        "uris": [*body["uris"], personal_uri], "expected_lock_version": attached.json()["lock_version"]})
    assert combined.status_code == 200, combined.text
    assert all(item["available"] for item in combined.json()["items"])
    assert (await client.get(endpoint, headers=human, params={"resource_agent_id": other_id})).status_code == 404
    assert (await client.put(endpoint, headers=admin, json={**body, "resource_agent_id": other_id})).status_code in {403, 404}
    assert (await client.get(f"{browser}/entries", params={"agent_id": owner_id, "uri": "file://", "cursor": "invalid"}, headers=human)).status_code == 422
    # A domain reference keeps shared bytes alive. Only independent owned files are removable here.
    domain_attachment = await client.post(f"/api/memory/documents/{document.json()['id']}/attachments",
        params={"actor_agent_id": owner_id}, headers=human,
        files={"file": ("Domain-owned.txt", b"Synthetic domain attachment", "text/plain")})
    assert domain_attachment.status_code == 201, domain_attachment.text
    domain_params = {"agent_id": owner_id, "uri": f"file://{domain_attachment.json()['id']}"}
    info = await client.get(f"{browser}/info", params=domain_params, headers=human)
    assert "delete" not in info.json()["capabilities"]
    assert (await client.delete(f"{browser}/entry", params=domain_params, headers=human)).status_code == 404
    disposable = await client.post(f"/api/file-share/files?agent_id={owner_id}", headers=human,
        files={"upload": ("Disposable.txt", b"Synthetic disposable bytes", "text/plain")})
    disposable_params = {"agent_id": owner_id, "uri": disposable.json()["uri"]}
    assert "delete" in disposable.json()["capabilities"]
    assert (await client.delete(f"{browser}/entry", params={**disposable_params, "agent_id": other_id}, headers=admin)).status_code == 404
    removed = await client.delete(f"{browser}/entry", params=disposable_params, headers=human)
    assert removed.status_code == 200, removed.text
    assert (await client.get(f"{browser}/info", params=disposable_params, headers=human)).status_code == 404
    client.cookies.clear()
    assert (await client.get(f"{browser}/schemes", params={"agent_id": owner_id})).status_code in {401, 403}
