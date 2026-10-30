"""User browsing uses real HTTP, persistence and MIME parsing with synthetic IMAP."""

from contextlib import contextmanager
from email.message import EmailMessage

import pytest
from sqlalchemy import func, select

from app.agent.models import Agent, Title
from app.connection.models import Connection, ConnectionParam
from app.tools.models import Tool
from app.tools.authorization_models import ActionAuthorization
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password
from bridge.mail.imap_client import ImapClient
from bridge.mail.models import MailInboundReceipt


@pytest.mark.asyncio
async def test_imap_browser_folders_messages_content_and_isolation(client, monkeypatch):
    password = "synthetic-mail-browser-password"
    async with get_db_session() as db:
        grants = list(await db.scalars(select(Privilege).where(Privilege.code.in_(["MAIL_ACCESS", "FILE_ACCESS"]))))
        role = Role(code="synthetic-mail-browser", privileges=grants)
        files_only = Role(code="synthetic-files-only", privileges=[p for p in grants if p.code == "FILE_ACCESS"])
        users = [UserModel(email=f"imap-browser-{i}@example.com", is_active=True, hashed_password=encrypt_password(password)) for i in range(3)]
        title = Title(label="Synthetic mailbox browser", gender="N")
        db.add_all([role, files_only, title, *users])
        await db.flush()
        db.add_all([Assignment(user_id=users[0].id, role_id=role.id, is_default=True),
                    Assignment(user_id=users[1].id, role_id=files_only.id, is_default=True),
                    Assignment(user_id=users[2].id, role_id=role.id, is_default=True)])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-imap-browser-{i}", first_name="Synthetic", last_name=str(i)) for i, user in enumerate(users)]
        db.add_all(agents)
        await db.flush()
        tool = await db.scalar(select(Tool).where(Tool.code == "mail"))
        connection = Connection(tool_id=tool.id, agent_id=agents[0].id, active=True)
        db.add(connection)
        await db.flush()
        for name, value in {"email_address": "mail-reader@example.com", "password": "synthetic-imap-secret", "imap_host": "imap.example.com", "smtp_host": "smtp.example.com"}.items():
            db.add(ConnectionParam(connection_id=connection.id, param_name=name, param_value=value))
        owner, foreign, connection_id = agents[0].id, agents[2].id, connection.id

    raw = EmailMessage()
    raw["Subject"] = "Synthetic mail <script>untrusted</script>"
    raw["From"] = "Example Sender <sender@example.com>"
    raw["To"] = "Reader <mail-reader@example.com>"
    raw.set_content("Synthetic private body\n" + "x" * 20_100)
    raw.add_attachment(b"Synthetic attachment", maintype="text", subtype="plain", filename="example.txt")
    mime = raw.as_bytes()
    calls = []
    validity = 7
    outage = False

    class FakeImap:
        def noop(self):
            if outage == "status":
                return "NO", [b"Synthetic IMAP failure"]
            if outage:
                raise OSError("Synthetic IMAP outage")
            return "OK", [b"NOOP"]

        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Noselect) "/" "Projects"',
                          b'(\\HasNoChildren) "/" "Projects/Example"', b'(\\Sent) "/" "Sent Items"']

        def select(self, mailbox, *, readonly):
            assert readonly
            calls.append(("select", mailbox))
            assert mailbox in (b'"INBOX"', b'"Projects/Example"', b'"Sent Items"')
            return "OK", [b"51"]

        def response(self, key):
            assert key == "UIDVALIDITY"
            return "UIDVALIDITY", [str(validity).encode()]

        def uid(self, operation, *args):
            calls.append((operation, args))
            if operation == "SEARCH":
                return "OK", [b"1" if "UID" in args else b" ".join(str(i).encode() for i in range(1, 52))]
            assert operation == "FETCH", "Browsing must not modify flags or messages"
            uid, query = args
            metadata = f"1 (UID {uid} FLAGS () RFC822.SIZE {len(mime)})".encode()
            return "OK", [(metadata, b"" if "RFC822.SIZE" in query else mime)]

    @contextmanager
    def session(self):
        assert self.config.agent_id == owner
        yield FakeImap()

    monkeypatch.setattr(ImapClient, "_session", session)
    headers = []
    for i in range(3):
        # Model three independent browser sessions; a shared login cookie revokes
        # the previous identity's session when switching users.
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": f"imap-browser-{i}@example.com", "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})

    base = "/api/file-share/browser/"
    async def listing(uri, **params):
        result = await client.get(base + "entries", params={"agent_id": owner, "uri": uri, **params}, headers=headers[0])
        assert result.status_code == 200, result.text
        return result.json()

    root = await listing("mail://")
    assert [row["name"] for row in root["entries"]] == ["INBOX", "Projects", "Sent Items"]
    assert all(row["capabilities"] == ["info", "list"] for row in root["entries"])
    projects = next(row for row in root["entries"] if row["name"] == "Projects")
    child = (await listing(projects["uri"]))["entries"][0]
    assert child["name"] == "Example"
    assert [row["name"] for row in (await listing(child["uri"]))["ancestors"]] == ["Mail", "Projects", "Example"]
    sent = next(row for row in root["entries"] if row["name"] == "Sent Items")
    first = await listing(sent["uri"])
    assert len(first["entries"]) == 50 and first["next_cursor"]
    second = await listing(sent["uri"], cursor=first["next_cursor"])
    assert len(second["entries"]) == 1 and second["next_cursor"] is None
    assert not {row["uri"] for row in first["entries"]} & {row["uri"] for row in second["entries"]}
    full = await listing(sent["uri"], limit=500)
    assert len(full["entries"]) == 51 and full["next_cursor"] is None
    message = first["entries"][0]
    assert message["metadata"]["seen"] is False
    detail_params = {"agent_id": owner, "message_ref": message["metadata"]["mail_message_ref"]}
    detail = await client.get("/api/mail/browser/message", params=detail_params, headers=headers[0])
    assert detail.status_code == 200, detail.text
    detail = detail.json()
    assert detail["body"].startswith("Synthetic private body") and detail["next_body_offset"] == 20_000
    rest = await client.get("/api/mail/browser/message", params={**detail_params, "body_offset": detail["next_body_offset"]}, headers=headers[0])
    assert rest.status_code == 200 and rest.json()["next_body_offset"] is None
    reopened = await client.get("/api/mail/browser/message", params=detail_params, headers=headers[0])
    assert reopened.json() == detail
    attachment = detail["attachments"][0]
    response = await client.get(base + "content", params={"agent_id": owner, "uri": attachment["uri"], "preview": False}, headers=headers[0])
    assert response.status_code == 200 and response.content == b"Synthetic attachment"
    response = await client.get(base + "content", params={"agent_id": owner, "uri": message["uri"], "preview": False}, headers=headers[0])
    assert response.status_code == 200 and response.content == mime
    assert all(call[0] != "STORE" for call in calls)
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(MailInboundReceipt)) == 0
        assert await db.scalar(select(func.count()).select_from(ActionAuthorization)) == 0

    before = len(calls)
    for path, params in [(base + "entries", {"uri": "mail://"}),
                         (base + "content", {"uri": attachment["uri"]}),
                         ("/api/mail/browser/message", {"message_ref": detail["ref"]})]:
        assert (await client.get(path, params={"agent_id": owner, **params})).status_code == 401
        assert (await client.get(path, params={"agent_id": owner, **params}, headers=headers[1])).status_code == 403
        assert (await client.get(path, params={"agent_id": foreign, **params}, headers=headers[0])).status_code == 404
        assert (await client.get(path, params={"agent_id": owner, **params}, headers=headers[2])).status_code == 404
    assert len(calls) == before
    validity = 8
    stale = await client.get("/api/mail/browser/message", params=detail_params, headers=headers[0])
    assert stale.status_code == 422
    for outage in (True, "status"):
        assert (await client.get(base + "entries", params={"agent_id": owner, "uri": "mail://"}, headers=headers[0])).status_code == 502
    outage = False
    async with get_db_session() as db:
        connection = await db.get(Connection, connection_id)
        connection.active = False
    assert (await client.get("/api/mail/browser/message", params=detail_params, headers=headers[0])).status_code == 422
