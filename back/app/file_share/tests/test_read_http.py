"""Read APIs keep source discovery and indexing progress inside the manager scope."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.file_share.models import FileIndexRun
from app.tools.models import Tool
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_file_read_http_permissions_isolation_and_reopening(client):
    password = "synthetic-file-reader-password"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "FILE_ACCESS"))
        index_privilege = await db.scalar(select(Privilege).where(Privilege.code == "FILE_INDEX_ACCESS"))
        role = Role(code="synthetic-file-reader", privileges=[privilege, index_privilege])
        users = [UserModel(email=f"file-reader-{index}@example.com", is_active=True,
                           hashed_password=encrypt_password(password)) for index in range(2)]
        title = Title(label="Synthetic HTTP file reads", gender="M")
        db.add_all([role, title, *users])
        await db.flush()
        db.add(Assignment(user_id=users[0].id, role_id=role.id, is_default=True))
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"file-read-http-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users)]
        tools = [Tool(code=f"synthetic-http-files-{index}", label=f"Synthetic source {index}",
                      file_share_config={"service": "nextcloud", "base_url": "https://files.example.com"})
                 for index in range(2)]
        db.add_all([*agents, *tools])
        await db.flush()
        now = datetime.now(timezone.utc)
        for agent, tool in zip(agents, tools, strict=True):
            db.add(Connection(agent_id=agent.id, tool_id=tool.id, active=True))
            db.add(FileIndexRun(agent_id=agent.id, binding_stamp="synthetic", root_uri=f"{tool.code}://",
                                frontier=[{"uri": f"{tool.code}://private-path"}],
                                started_at=now, updated_at=now, next_attempt_at=now))
        owner_id, peer_id = agents[0].id, agents[1].id

    paths = ("/api/file-share/browser/schemes", "/api/file-share/indexing")
    for path in paths:
        assert (await client.get(path, params={"agent_id": owner_id})).status_code == 401
    headers = []
    for index in range(2):
        login = await client.post("/api/auth/login-json", json={
            "email": f"file-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    for path in paths:
        assert (await client.get(path, params={"agent_id": peer_id}, headers=headers[0])).status_code == 404
        assert (await client.get(path, params={"agent_id": peer_id}, headers=headers[1])).status_code == 403
        first = await client.get(path, params={"agent_id": owner_id}, headers=headers[0])
        reopened = await client.get(path, params={"agent_id": owner_id}, headers=headers[0])
        assert first.status_code == reopened.status_code == 200
        assert first.json() == reopened.json()
        if path.endswith("schemes"):
            schemes = {row["scheme"] for row in first.json()}
            assert "synthetic-http-files-0" in schemes and "synthetic-http-files-1" not in schemes
        else:
            assert first.json()["total"] == 1
            assert first.json()["runs"][0]["root_uri"] == "synthetic-http-files-0://"
            assert "frontier" not in first.json()["runs"][0]


@pytest.mark.asyncio
async def test_video_stream_reads_only_requested_bytes_and_rechecks_access(client, monkeypatch):
    from app.file_share import resource_service
    from app.file_share.file_contracts import FileEntry

    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "FILE_ACCESS"))
        role = Role(code="synthetic-media-reader", privileges=[privilege])
        user = UserModel(email="media-reader@example.com", is_active=True,
                         hashed_password=encrypt_password("synthetic-media-password"))
        title = Title(label="Synthetic media reader", gender="M")
        db.add_all([role, user, title])
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        agent = Agent(user_id=user.id, title_id=title.id, code="synthetic-media-reader",
                      first_name="Synthetic", last_name="Reader")
        db.add(agent)
        await db.flush()
        agent_id = agent.id

    size = 3 * 1024**3
    reads = []
    allowed = True

    class VideoTransport:
        async def resource_info(self, path, **kwargs):
            return FileEntry(path=path, is_dir=False, size=size, mime_type="video/mp4")

        async def iter_range(self, remote, *, offset, length, target=""):
            reads.append((offset, length))
            yield b"v" * length

    async def resolve(owner, *args, **kwargs):
        assert owner == agent_id
        if not allowed:
            raise PermissionError("Synthetic revoked connection")
        return VideoTransport(), "samba"

    # Replace the remote provider, preserving the real URI facade and HTTP workflow.
    monkeypatch.setattr(resource_service, "resolve_resource_transport_with_service", resolve)
    login = await client.post("/api/auth/login-json", json={
        "email": "media-reader@example.com", "password": "synthetic-media-password",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    params = {"agent_id": agent_id, "uri": "synthetic-share://Synthetic.mp4"}
    assert (await client.post("/api/file-share/browser/media", params=params)).status_code == 401
    issued = await client.post("/api/file-share/browser/media", params=params, headers=headers)
    assert issued.status_code == 200, issued.text
    url = "https://localhost" + issued.json()["url"]
    assert reads == []
    head = await client.head(url)
    assert head.status_code == 200 and head.headers["content-length"] == str(size)
    assert reads == []
    assert (await client.get(url.rsplit("/", 1)[0] + "/00000000-0000-4000-8000-000000000001")).status_code == 401
    for byte_range, start, count in [("bytes=0-31", 0, 32), (f"bytes={size - 16}-", size - 16, 16), ("bytes=-8", size - 8, 8)]:
        response = await client.get(url, headers={"Range": byte_range})
        assert response.status_code == 206, response.text
        assert response.content == b"v" * count
        assert response.headers["content-range"] == f"bytes {start}-{start + count - 1}/{size}"
        assert response.headers["accept-ranges"] == "bytes"
        assert reads[-1] == (start, count)
    invalid = await client.get(url, headers={"Range": f"bytes={size}-"})
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{size}"
    allowed = False
    assert (await client.get(url, headers={"Range": "bytes=0-31"})).status_code == 404
    assert len(reads) == 3
    allowed = True
    released = await client.delete(issued.json()["url"], headers=headers)
    assert released.status_code == 204
    assert (await client.get(url, headers={"Range": "bytes=0-31"})).status_code == 401
    issued = await client.post("/api/file-share/browser/media", params=params, headers=headers)
    url = "https://localhost" + issued.json()["url"]
    assert (await client.get(url, headers={"Range": "bytes=0-3"})).status_code == 206
    assert (await client.post("https://localhost/api/auth/logout")).status_code == 200
    assert (await client.get(url, headers={"Range": "bytes=0-3"})).status_code == 401
