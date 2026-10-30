"""User-scoped mailbox browsing, independent of autonomous email admission."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from app.agent import current_management_scope
from app.tools.contracts import current_tool_execution
from core.authorize import Privileges, check_privilege
from core.database import get_db
from core.user import get_current_user
from core.util import buffered_io_budget, complete_io

from .connection_service import resolve_mail_connection
from .contracts import MailConnectionConfig, MailMessageDetail, MailMessageRef, OutgoingAttachment
from .imap_client import ImapClient
from .service import get_message

_T = TypeVar("_T")


async def browser_config(agent_id: int) -> MailConnectionConfig:
    """A browser operation requires a user, Mail rights and this agent's scope."""
    user = await get_current_user()
    if current_tool_execution() is not None or user is None or not await check_privilege(
        user, [Privileges.MAIL_ACCESS, Privileges.MAIL_EDIT], get_db(),
    ) or not (await current_management_scope()).allows(agent_id):
        raise PermissionError("Mail resource unavailable")
    return await resolve_mail_connection(agent_id)


async def _read(config: MailConnectionConfig, operation: Callable[[], _T]) -> _T:
    # Keep the admission until the IMAP worker ends, including request cancellation.
    maximum = config.max_total_attachment_bytes + 1_000_000
    async with buffered_io_budget.reserve(maximum * 6, owner=f"mail:{config.agent_id}"):
        return await complete_io(operation)


async def read_message(agent_id: int, message_ref: str, *, body_offset: int = 0,
                       body_limit: int = 20_000) -> MailMessageDetail:
    config = await browser_config(agent_id)
    ref = MailMessageRef.decode(message_ref)
    return await _read(config, lambda: ImapClient(config).get_message(
        ref, body_offset=max(0, body_offset), body_limit=max(1, min(body_limit, 50_000)),
    ))


async def read_raw_message(agent_id: int, message_ref: str, *, browser: bool, max_bytes: int) -> bytes:
    if browser:
        config = await browser_config(agent_id)
    else:
        config = await resolve_mail_connection(agent_id)
        from .inbound import ensure_readable
        await ensure_readable(config, message_ref)
    ref = MailMessageRef.decode(message_ref)
    return await _read(config, lambda: ImapClient(config).get_raw_message(ref, max_bytes=max_bytes))


async def read_attachment(agent_id: int, message_ref: str, part_id: str, *, max_bytes: int) -> OutgoingAttachment:
    config = await browser_config(agent_id)
    ref = MailMessageRef.decode(message_ref)
    return await _read(config, lambda: ImapClient(config).get_attachment(ref, part_id, max_bytes=max_bytes))


async def attachment_message(agent_id: int, message_ref: str, *, browser: bool) -> MailMessageDetail:
    if browser:
        return await read_message(agent_id, message_ref, body_limit=1)
    return await get_message(agent_id, message_ref, body_limit=1)
