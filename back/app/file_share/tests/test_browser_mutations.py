"""The assembled browser API rechecks users, agents and provider capabilities."""

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.file_share import resource_service
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password
from .local_file_transport import TemporaryFileTransport


@pytest.mark.asyncio
async def test_browser_rename_delete_files_and_trees_preserve_scope_and_conflicts(client, monkeypatch, tmp_path):
    password = "Synthetic-browser-mutations-123"
    async with get_db_session() as db:
        read = await db.scalar(select(Privilege).where(Privilege.code == "FILE_ACCESS"))
        edit = await db.scalar(select(Privilege).where(Privilege.code == "FILE_EDIT"))
        roles = [Role(code="synthetic-files-writer", privileges=[read, edit]),
                 Role(code="synthetic-files-reader", privileges=[read])]
        users = [UserModel(email=f"browser-mutations-{index}@example.com", is_active=True,
                           hashed_password=encrypt_password(password)) for index in range(2)]
        title = Title(label="Synthetic browser mutations", gender="X")
        db.add_all([*roles, *users, title])
        await db.flush()
        for user, role in zip(users, roles, strict=True):
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-mutations-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users)]
        db.add_all(agents)
        await db.flush()
        owner, peer = [agent.id for agent in agents]
    headers = []
    for index in range(2):
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": f"browser-mutations-{index}@example.com", "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": "Bearer " + login.json()["access_token"]})
    client.cookies.clear()
    transport = TemporaryFileTransport(tmp_path / "console")
    root = transport.root_path()

    async def resolve(ctx):
        assert ctx.agent_id == owner
        return transport

    monkeypatch.setattr(resource_service, "_console_transport", resolve)
    endpoint = "/api/file-share/browser/entry"
    params = {"agent_id": owner, "uri": "console://Original.txt"}
    (root / "Original.txt").write_text("Synthetic preserved bytes")
    assert (await client.patch(endpoint, params=params, json={"name": "New.txt"})).status_code == 401
    assert (await client.delete(endpoint, params=params, headers=headers[1])).status_code == 403
    assert (await client.patch(endpoint, params=params, json={"name": "New.txt"}, headers=headers[1])).status_code == 403
    assert (await client.delete(endpoint, params={**params, "agent_id": peer}, headers=headers[0])).status_code == 404
    # A file edit privilege cannot bypass the native domain's own mutation authorization.
    for native in ["galaris://skill/synthetic/extra.txt", "data://00000000-0000-4000-8000-000000000001"]:
        native_params = {**params, "uri": native}
        assert (await client.delete(endpoint, params=native_params, headers=headers[0])).status_code == 403
        assert (await client.patch(endpoint, params=native_params, json={"name": "New"}, headers=headers[0])).status_code == 403
    for name in ["../escape", "dir/name", "dir\\name", ".."]:
        assert (await client.patch(endpoint, params=params, json={"name": name}, headers=headers[0])).status_code == 422
    renamed = await client.patch(endpoint, params=params, json={"name": "New é.txt"}, headers=headers[0])
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["uri"] == "console://New%20%C3%A9.txt"
    assert (root / "New é.txt").read_text() == "Synthetic preserved bytes"
    (root / "Existing").mkdir()
    conflict = await client.patch(endpoint, params={**params, "uri": renamed.json()["uri"]}, json={"name": "Existing"}, headers=headers[0])
    assert conflict.status_code == 409, conflict.text
    assert list((root / "Existing").iterdir()) == []
    assert (await client.delete(endpoint, params={**params, "uri": renamed.json()["uri"]}, headers=headers[0])).status_code == 200
    assert not (root / "New é.txt").exists()
    (root / "Tree" / "Nested").mkdir(parents=True)
    (root / "Tree" / "Nested" / "Content.txt").write_text("Synthetic tree bytes")
    params["uri"] = "console://Tree/"
    renamed = await client.patch(endpoint, params=params, json={"name": "Renamed"}, headers=headers[0])
    assert renamed.status_code == 200 and renamed.json()["uri"] == "console://Renamed/", renamed.text
    params["uri"] = renamed.json()["uri"]
    assert (await client.delete(endpoint, params=params, headers=headers[0])).status_code == 422
    assert (root / "Renamed" / "Nested" / "Content.txt").read_text() == "Synthetic tree bytes"
    removed = await client.delete(endpoint, params={**params, "recursive": True}, headers=headers[0])
    assert removed.status_code == 200, removed.text
    assert not (root / "Renamed").exists()
    for method in ["patch", "delete"]:
        kwargs = {"json": {"name": "Home"}} if method == "patch" else {"params": {"agent_id": owner, "uri": "console://", "recursive": True}}
        if method == "patch":
            kwargs["params"] = {"agent_id": owner, "uri": "console://"}
        assert (await getattr(client, method)(endpoint, headers=headers[0], **kwargs)).status_code in {404, 422}
    assert root.exists()
