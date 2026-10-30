"""Real file providers and document persistence across the authenticated API."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.agent.models import Agent, Title
from core.authorize import Assignment, Privilege, Role
from core.authorize.models import RolePrivilege
from core.database import get_db_session


@pytest.mark.asyncio
async def test_file_import_http_preserves_independent_content_and_enforces_both_domains(client):
    credentials = {"email": f"import-admin-{uuid4()}@example.com", "password": "Synthetic-import-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    admin = {"Authorization": "Bearer " + login.json()["access_token"]}
    credentials["email"] = f"import-owner-{uuid4()}@example.com"
    user = await client.post("/api/auth/users", headers=admin, json=credentials)
    assert user.status_code == 201, user.text
    user_id = user.json()["id"]
    async with get_db_session() as db:
        rights = list(await db.scalars(select(Privilege).where(Privilege.code.in_(
            ["DOCUMENT_EDIT", "DOCUMENT_ACCESS", "DATASET_READ", "DATASET_EDIT", "FILE_ACCESS", "FILE_EDIT"]))))
        role = Role(code=f"import-{uuid4()}", display_name="Synthetic importer", privileges=rights)
        title = Title(label="Synthetic import", gender="X")
        db.add_all([role, title])
        await db.flush()
        role_id = role.id
        db.add(Assignment(user_id=user_id, role_id=role_id, is_default=True))
        agent = Agent(user_id=user_id, title_id=title.id, code=f"import-{uuid4()}", first_name="Synthetic", last_name="Importer")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    request = {"owner_kind": "user", "owner_id": user_id, "title": "Synthetic import"}
    sources = [
        ("source.json", "application/json", b' {"value":7}\n', "data", ' {"value":7}\n'),
        ("source.md", "text/markdown", b"# Synthetic", "text", "<h1>Synthetic</h1>"),
        ("source.html", "text/html", b"<!doctype html><html><body><p>Synthetic</p></body></html>", "text", "<p>Synthetic</p>"),
        ("large.json", "application/json", b'{"value":"' + b"a" * 2_100_000 + b'"}', "data", '{"value":"' + "a" * 2_100_000 + '"}'),
        ("large.html", "text/html", b"<p>" + b"a" * 2_100_000 + b"</p>", "text", "<p>" + "a" * 2_100_000 + "</p>"),
    ]
    for name, mime, content, kind, expected in sources:
        uploaded = await client.post("/api/file-share/files", headers=headers, params={"agent_id": agent_id},
            files={"upload": (name, content, mime)})
        assert uploaded.status_code == 201, uploaded.text
        uri = uploaded.json()["uri"]
        body = {**request, "import_from": {"uri": uri, "agent_id": agent_id}}
        imported = await client.post("/api/documents", headers=headers, json=body)
        assert imported.status_code == 201, imported.text
        item = imported.json()
        assert item["document_type"] == kind and item["owner_user_id"] == user_id and item["revision"] == 1
        # A human-owned document can itself be a source, without granting it to the selected Agent.
        source_uri = f"{'data' if kind == 'data' else 'document'}://{item['id']}"
        clone = await client.post("/api/documents", headers=headers, json={**request,
            "import_from": {"uri": source_uri, "agent_id": agent_id}})
        assert clone.status_code == 201, clone.text
        assert clone.json()["id"] != item["id"] and clone.json()["document_type"] == kind
        clone_detail = await client.get(f"/api/documents/{clone.json()['id']}", headers=headers)
        assert clone_detail.status_code == 200, clone_detail.text
        assert clone_detail.json()["item"]["payload"]["text"] == expected
        deleted = await client.delete("/api/file-share/browser/entry", headers=headers, params={"agent_id": agent_id, "uri": uri})
        assert deleted.status_code == 200, deleted.text
        detail = await client.get(f"/api/documents/{item['id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["item"]["payload"]["text"] == expected
        assert (await client.post("/api/documents", headers=headers, json=body)).status_code == 404

    for name, content, mime, status in (("source.png", b"synthetic", "image/png", 415),
                                       ("invalid.json", b"{", "application/json", 422)):
        uploaded = await client.post("/api/file-share/files", headers=headers, params={"agent_id": agent_id}, files={"upload": (name, content, mime)})
        assert uploaded.status_code == 201, uploaded.text
        body = {**request, "import_from": {"uri": uploaded.json()["uri"], "agent_id": agent_id}}
        failure = await client.post("/api/documents", headers=headers, json=body)
        assert failure.status_code == status, failure.text
    # Creation rights do not authorize reading a source whose functional access was revoked.
    async with get_db_session() as db:
        await db.execute(delete(RolePrivilege).where(RolePrivilege.role_id == role_id,
            RolePrivilege.privilege_id.in_(select(Privilege.id).where(Privilege.code.in_(["FILE_ACCESS", "FILE_EDIT"])))))
    assert (await client.post("/api/documents", headers=headers, json=body)).status_code == 404
    # Native document copies use document privileges even without independent-file access.
    native_copy = await client.post("/api/documents", headers=headers, json={**request,
        "import_from": {"uri": f"document://{clone.json()['id']}", "agent_id": agent_id}})
    assert native_copy.status_code == 201, native_copy.text
    client.cookies.clear()
    assert (await client.post("/api/documents", json=body)).status_code in {401, 403}
