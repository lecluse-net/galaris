"""Canaries for the isolated PostgreSQL/files/master-key restore rehearsal."""

import asyncio
import hashlib
import json
from pathlib import Path
import sys
from io import BytesIO

from cryptography.fernet import Fernet, InvalidToken
from jose import jwt
from sqlalchemy import select
from fastapi import UploadFile
import httpx

import main  # Register the same ORM models as the application, without starting workers.
from core.database import get_db_session
from core.params.models import Param
from core.settings import settings
from core.util.encryption import EncryptionService, decrypt_value, encrypt_value


ROOT = Path("/restore")
CANARY = "restore-canary-only-not-a-production-credential"
PASSWORD = "Restore-drill-password-42!"


async def seed_application_document() -> None:
    from app.agent.models import Agent, Title
    from app.memory import document_service, document_attachment_service
    from core.authorize.models import Assignment, Role
    from core.user.models import User
    from core.user.user_service import encrypt_password

    async with get_db_session() as db:
        owner = User(email="restore-owner@example.com", display_name="Restore owner", hashed_password=encrypt_password(PASSWORD), is_active=True)
        outsider = User(email="restore-outsider@example.com", display_name="Restore outsider", hashed_password=encrypt_password(PASSWORD), is_active=True)
        title = Title(label="Restore probe", gender="X")
        db.add_all([owner, outsider, title])
        await db.flush()
        role = await db.scalar(select(Role).where(Role.code == "admin"))
        assert role is not None
        db.add(Assignment(user_id=owner.id, role_id=role.id, is_default=True))
        agent = Agent(user_id=owner.id, title_id=title.id, first_name="Restore", last_name="Probe", code="restore-probe", agent_driver="internal")
        db.add(agent)
        await db.flush()
        document = await document_service.create_document(owner_agent_id=agent.id, title="Restored document", content=CANARY, task_id=None)
        attachment = await document_attachment_service.add_document_attachment(
            document.id, actor_agent_id=agent.id,
            upload=UploadFile(file=BytesIO(b"restored application attachment"), filename="canary.txt"),
        )
        (ROOT / "application.json").write_text(json.dumps({
            "agent_id": agent.id, "document_id": str(document.id), "attachment_id": str(attachment.id),
        }))


async def verify_application_document() -> None:
    identifiers = json.loads((ROOT / "application.json").read_text())
    document_url = f"/api/memory/documents/{identifiers['document_id']}"
    attachment_url = f"{document_url}/attachments/{identifiers['attachment_id']}?agent_id={identifiers['agent_id']}"
    # A fresh process imports the real routers, middleware and authorization after restore.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as client:
        for identity, allowed in (("owner", True), ("outsider", False)):
            login = await client.post("/api/auth/login-json", json={"email": f"restore-{identity}@example.com", "password": PASSWORD})
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            document = await client.get(document_url, headers=headers)
            attachment = await client.get(attachment_url, headers=headers)
            if allowed:
                assert document.status_code == 200, document.text
                assert CANARY in document.text
                assert attachment.status_code == 200, attachment.text
                assert attachment.content == b"restored application attachment"
            else:
                assert document.status_code in {403, 404}
                assert attachment.status_code in {403, 404}


async def run(mode: str) -> None:
    if settings.APP_ENV != "test" or settings.POSTGRES_HOST != "db-test" or settings.POSTGRES_DB not in {"test_db", "test_restored", "test_rollback"}:
        raise RuntimeError("Restore probes require the isolated test stack.")
    key_path = ROOT / "keys/ENCRYPTION_MASTER_KEY"
    if mode == "seed":
        key_path.parent.mkdir(parents=True, mode=0o700)
        key_path.write_bytes(Fernet.generate_key())
        key_path.chmod(0o600)
        auth_key = ROOT / "keys/AUTH_SECRET_KEY"
        auth_key.write_bytes(Fernet.generate_key())
        auth_key.chmod(0o600)
        files = {
            "files/chat/attachments/canary.txt": b"chat attachment restore canary\n",
            "files/memory/document.md": b"# Persistent document restore canary\n",
            "files/skills/canary/SKILL.md": b"---\nname: canary\ndescription: Restore test.\n---\n",
            "files/ssh-executor/homes/agent/work.txt": b"executor home restore canary\n",
            "harness-manager/agent/data/workspace/result.txt": b"managed runtime output canary\n",
            "harness-manager/agent/data/.galaris/session.json": b'{"session":"restore-canary"}\n',
        }
        for name, content in files.items():
            path = ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (ROOT / "manifest.json").write_text(json.dumps({
            name: hashlib.sha256(content).hexdigest() for name, content in files.items()
        }))
    settings.ENCRYPTION_MASTER_KEY = key_path.read_text().strip()
    assert key_path.stat().st_mode & 0o777 == 0o600
    auth_secret = (ROOT / "keys/AUTH_SECRET_KEY").read_text().strip()
    if "AUTH_SECRET_KEY" in type(settings).model_fields:
        # Historical binaries used by rollback drills still read this setting.
        setattr(settings, "AUTH_SECRET_KEY", auth_secret)
    EncryptionService._instance = None
    async with get_db_session() as db:
        if mode == "seed":
            auth_param = await db.scalar(select(Param).where(Param.name == "AUTH_SECRET_KEY"))
            if auth_param is not None:
                auth_param.value = encrypt_value(auth_secret)
            push_param = await db.scalar(select(Param).where(Param.name == "WEB_PUSH_VAPID_KEYS"))
            if push_param is not None:
                from core.params.web_push import create_vapid_keys, serialize_vapid_keys
                push_param.value = encrypt_value(serialize_vapid_keys(create_vapid_keys()))
            # Declared string parameters survive DbAdmin's removal of obsolete names.
            # These credentials belong only to this isolated stack; no provider is called.
            encrypted = await db.scalar(select(Param).where(Param.name == "PROCESS_N8N_API_TOKEN"))
            signed_param = await db.scalar(select(Param).where(Param.name == "PROCESS_N8N_WEBHOOK_AUTH_TOKEN"))
            assert encrypted is not None and signed_param is not None
            encrypted.value = encrypt_value(CANARY)
            signed_param.value = encrypt_value(jwt.encode(
                {"sub": CANARY}, auth_secret, algorithm=settings.ALGORITHM,
            ))
        else:
            value = await db.scalar(select(Param.value).where(Param.name == "PROCESS_N8N_API_TOKEN"))
            assert value and decrypt_value(value) == CANARY
            signed = await db.scalar(select(Param.value).where(Param.name == "PROCESS_N8N_WEBHOOK_AUTH_TOKEN"))
            assert signed and jwt.decode(decrypt_value(signed), auth_secret, algorithms=[settings.ALGORITHM])["sub"] == CANARY
            # A different key must fail; restoring only the database is insufficient.
            try:
                Fernet(Fernet.generate_key()).decrypt(value.encode())
            except InvalidToken:
                pass
            else:
                raise AssertionError("The canary was not bound to the restored key.")
            for name, digest in json.loads((ROOT / "manifest.json").read_text()).items():
                assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    # Current binaries load the internal signing key before any authenticated API
    # call. The probe also runs against historical binaries during rollback drills.
    from core.params import params_service
    async with get_db_session():
        await params_service.load_params()
    if mode == "seed":
        await seed_application_document()
    else:
        await verify_application_document()


if __name__ == "__main__":
    if sys.argv[1:] not in (["seed"], ["verify"]):
        raise SystemExit("Usage: restore_probe.py seed|verify")
    asyncio.run(run(sys.argv[1]))
