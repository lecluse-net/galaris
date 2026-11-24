"""File catalogue projections of authorized INBOX messages and MIME parts."""

from __future__ import annotations

import asyncio
from hashlib import sha256

from loguru import logger
from sqlalchemy import select

from app.connection import facade as connections
from app.file_share import FileEntry, ResourceDescriptor, observe_received_resources
from app.services.facade import authorization_fingerprint, get_service_by_id
from app.services.contracts import current_tool_execution
from core.database import get_db
from core.user import get_current_user_id

from .browser_service import require_browser_access
from .connection_service import resolve_connection
from .contracts import MailConnectionConfig, MailMessageDetail, MailMessageRef
from .imap_client import ImapClient
from .inbound import processing_policy, require_inbox
from .models import MailInboundReceipt


def body_bytes(message: MailMessageDetail) -> bytes:
    return message.body.replace("\x00", "").encode("utf-8")


def index_entries(message: MailMessageDetail, generation: int) -> list[FileEntry]:
    base = f"indexed/{message.ref}/{generation}/"
    body = body_bytes(message)
    modified_at = message.date.isoformat() if message.date else ""
    return [
        FileEntry(path=base + "body.txt", name=message.subject or "Mail", is_dir=False,
                  size=len(body), mime_type="text/vnd.galaris.mail", modified_at=modified_at,
                  sha256=sha256(body).hexdigest()),
        *(FileEntry(path=base + part.part_id, name=part.filename, is_dir=False,
                    size=part.size, mime_type="text/plain" if part.media_type == "text/vnd.galaris.mail" else part.media_type,
                    modified_at=modified_at)
          for part in message.attachments),
    ]


async def observe_mail(row: MailInboundReceipt, message: MailMessageDetail) -> None:
    connection_id = row.connection_id
    if connection_id is None or row.authorized_at is None or row.message_ref != message.ref:
        return
    connection = await connections.get_connection(connection_id)
    if connection is None or not connection.active or connection.agent_id != row.agent_id:
        return
    tool = await get_service_by_id(connection.service_id)
    if tool is None or tool.mail is None:
        return
    namespace = "mail/" if tool.file_share and tool.file_share.service != "mail" else ""
    prefix = f"{tool.code}://{namespace}account/{connection_id}/"
    try:
        async with get_db().begin_nested():
            await observe_received_resources(connection_id, [
                ResourceDescriptor(uri=prefix + entry.path, name=entry.name or "", size=entry.size,
                                   media_type=entry.mime_type, modified_at=entry.modified_at or None,
                                   checksum=entry.sha256 or None)
                for entry in index_entries(message, row.authorization_generation)
            ])
    except Exception as exc:
        logger.warning("Mail catalogue observation failed: {}", type(exc).__name__)


async def indexed_source(
    agent_id: int, connection_id: int, path: str, *, check_imap: bool,
) -> tuple[MailConnectionConfig, MailMessageDetail, FileEntry]:
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "indexed":
        raise FileNotFoundError("Invalid indexed Mail reference")
    _, message_ref, generation, _part = parts
    require_inbox(message_ref)
    if get_current_user_id() is not None and current_tool_execution() is None:
        await require_browser_access(agent_id)
    ref = MailMessageRef.decode(message_ref)
    row = await get_db().scalar(select(MailInboundReceipt).where(
        MailInboundReceipt.connection_id == connection_id,
        MailInboundReceipt.agent_id == agent_id,
        MailInboundReceipt.message_ref == message_ref,
        MailInboundReceipt.authorized_at.is_not(None),
    ).execution_options(populate_existing=True))
    if row is None or row.content is None or str(row.authorization_generation) != generation:
        raise PermissionError("Indexed Mail authorization is no longer available")
    connection = await connections.get_connection(connection_id)
    if connection is None or not connection.active or connection.agent_id != agent_id:
        raise PermissionError("Mail connection is no longer available")
    config = await resolve_connection(connection_id, require_active=True)
    config.require_mailbox(ref.mailbox)
    policy, configuration = await processing_policy(connection)
    if (policy["effective_state"] == "disabled" or row.status in {"blocked", "rejected"}
            or authorization_fingerprint(configuration) != row.configuration_fingerprint):
        raise PermissionError("Indexed Mail authorization is no longer available")
    message = MailMessageDetail.model_validate(row.content)
    entry = next((candidate for candidate in index_entries(message, row.authorization_generation)
                  if candidate.path == path), None)
    if entry is None:
        raise FileNotFoundError("Indexed Mail part does not exist")
    if check_imap:
        await asyncio.to_thread(ImapClient(config).get_summary, ref)
    return config, message, entry
