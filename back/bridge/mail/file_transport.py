"""Read-only mail:// mailbox tree, MIME messages and attachment resources."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
from dataclasses import dataclass, replace
from collections.abc import Callable
from types import CoroutineType
from functools import wraps
from pathlib import Path
from typing import Any, cast

from app.file_share import FileEntry, FileListing, ResourceContext
from core.util import complete_io
from .browser_service import attachment_message, browser_config, read_attachment, read_raw_message
from .contracts import MailboxInfo, MailMessageRef, MailMessageSummary, MailSearchQuery
from .imap_client import ImapClient, mailbox_display_name
from .service import get_attachment, list_mailboxes, parse_attachment_locator, search
from app.tools import bind_protocol_connection, reset_protocol_connection


def _bound_connection[**P, T](method: Callable[P, CoroutineType[Any, Any, T]]) -> Callable[P, CoroutineType[Any, Any, T]]:
    @wraps(method)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        transport = cast("MailAttachmentTransport", args[0])
        token = (bind_protocol_connection("mail", transport.agent_id, transport.connection_id)
                 if transport.connection_id is not None else None)
        try:
            result = await method(*args, **kwargs)
            def entry(value: FileEntry) -> FileEntry:
                return replace(value, path=transport.prefix + value.path,
                    metadata={"mail_connection_id": transport.connection_id, **value.metadata})
            if isinstance(result, FileEntry):
                return cast(T, entry(result))
            if isinstance(result, FileListing):
                return cast(T, replace(result, path=transport.prefix + result.path,
                    entries=tuple(entry(value) for value in result.entries),
                    ancestors=tuple(entry(value) for value in result.ancestors)))
            return result
        finally:
            if token is not None:
                reset_protocol_connection(token)
    return wrapped


def _segment(value: str) -> str:
    return "b_" + base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


@dataclass(frozen=True)
class _Folder:
    path: str
    name: str
    mailbox: MailboxInfo | None = None

    def entry(self) -> FileEntry:
        return FileEntry(path=self.path, name=self.name, is_dir=True, size=None,
                         mime_type="inode/directory", metadata={"mailbox": self.mailbox.name if self.mailbox else None})


def _folders(mailboxes: list[MailboxInfo]) -> dict[str, _Folder]:
    result: dict[str, _Folder] = {"": _Folder("", "Mail")}
    for mailbox in mailboxes:
        parts = mailbox.name.split(mailbox.delimiter) if mailbox.delimiter else [mailbox.name]
        path = ""
        for index, part in enumerate(parts):
            path += _segment(part) + "/"
            previous = result.get(path)
            result[path] = _Folder(path, mailbox_display_name(part), mailbox if index == len(parts) - 1 else previous.mailbox if previous else None)
    return result


def _message_entry(folder: str, message: MailMessageSummary) -> FileEntry:
    filename = re.sub(r"[/\\\x00-\x1f\x7f]+", "_", message.subject).strip()[:180] or "message"
    return FileEntry(path=f"{folder}message-{message.ref}.eml", name=f"{filename}.eml",
        is_dir=False, size=None, mime_type="message/rfc822",
        modified_at=message.date.isoformat() if message.date else "",
        metadata={"mail_message_ref": message.ref, "subject": message.subject,
                  "from_name": message.from_name, "from_address": message.from_address,
                  "seen": message.seen, "flagged": message.flagged, "has_attachments": message.has_attachments,
                  "sort_order": -MailMessageRef.decode(message.ref).uid})


def _message_path(path: str) -> tuple[str, MailMessageRef]:
    folder, _, filename = path.rpartition("/")
    if not filename.startswith("message-m1_") or not filename.endswith(".eml"):
        raise ValueError("Invalid mail message resource")
    return folder + "/", MailMessageRef.decode(filename[len("message-"):-len(".eml")])


def _cursor(path: str, offset: int, message_cursor: str | None, messages: bool) -> str:
    return base64.urlsafe_b64encode(json.dumps([path, offset, message_cursor, messages]).encode()).decode().rstrip("=")


def _page(path: str, cursor: str | None) -> tuple[int, str | None, bool]:
    if not cursor:
        return 0, None, False
    try:
        raw: object = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if not isinstance(raw, list):
            raise ValueError("Invalid Mail listing cursor")
        value = cast(list[object], raw)
        if len(value) != 4 or value[0] != path:
            raise ValueError("Invalid Mail listing cursor")
        _, offset, next_message, messages = value
        if type(offset) is not int or offset < 0 or type(messages) is not bool or not (next_message is None or isinstance(next_message, str)):
            raise ValueError("Invalid Mail listing cursor")
        return offset, next_message, messages
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Mail listing cursor") from exc


class MailAttachmentTransport:
    """Browse live IMAP data; generic mutations remain forbidden."""

    def __init__(self, agent_id: int, *, browser: bool = False,
                 connection_id: int | None = None, tool_code: str = "mail", prefix: str = "") -> None:
        self.agent_id, self.browser = agent_id, browser
        self.connection_id, self.tool_code, self.prefix = connection_id, tool_code, prefix
        self.accounts: dict[int, str] = {}

    def for_accounts(self, accounts: dict[int, str], tool_code: str, *, prefix: str = "") -> MailAttachmentTransport:
        transport = MailAttachmentTransport(self.agent_id, browser=self.browser, tool_code=tool_code, prefix=prefix)
        transport.accounts = accounts
        return transport

    def for_connection(self, connection_id: int, tool_code: str, *, prefix: str = "") -> MailAttachmentTransport:
        return MailAttachmentTransport(self.agent_id, browser=self.browser,
            connection_id=connection_id, tool_code=tool_code, prefix=prefix)

    def _path(self, path: str) -> str:
        if self.prefix and not path.startswith(self.prefix):
            raise ValueError("Mail resource is outside this protocol namespace")
        return path.removeprefix(self.prefix)

    def for_resource_context(self, ctx: ResourceContext) -> MailAttachmentTransport:
        transport = MailAttachmentTransport(self.agent_id, browser=ctx.browser_navigation,
            connection_id=self.connection_id, tool_code=self.tool_code, prefix=self.prefix)
        transport.accounts = self.accounts
        return transport

    async def _account_root(self) -> FileEntry:
        if self.browser:
            binding = bind_protocol_connection("mail", self.agent_id, next(iter(self.accounts)))
            try:
                await browser_config(self.agent_id)
            finally:
                reset_protocol_connection(binding)
        return FileEntry(path="", name=self.tool_code, is_dir=True)

    async def _folders(self) -> dict[str, _Folder]:
        if self.browser:
            await browser_config(self.agent_id)
        return _folders(await list_mailboxes(self.agent_id))

    async def _message(self, path: str) -> MailMessageRef:
        folder, ref = _message_path(path)
        node = (await self._folders()).get(folder)
        if node is None or node.mailbox is None or node.mailbox.name != ref.mailbox or not node.mailbox.selectable:
            raise FileNotFoundError("Mail folder unavailable")
        return ref

    @_bound_connection
    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = 512 * 1024 * 1024) -> int:
        remote = self._path(remote)
        if target:
            raise ValueError("mail:// resources do not accept a target")
        if remote.startswith("attachment/"):
            message_ref, part_id, _filename = parse_attachment_locator(remote)
            if self.browser:
                attachment = await read_attachment(self.agent_id, message_ref, part_id, max_bytes=max_bytes)
            else:
                attachment = await get_attachment(self.agent_id, message_ref, part_id, max_bytes=max_bytes)
            content = attachment.content
        else:
            ref = await self._message(remote)
            content = await read_raw_message(self.agent_id, ref.encode(), browser=self.browser, max_bytes=max_bytes)
        if len(content) > max_bytes:
            raise ValueError("Mail resource exceeds the requested byte limit")
        await complete_io(dest.write_bytes, content)
        return len(content)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        del src, filename, target
        raise PermissionError("mail:// resources are read-only")

    @_bound_connection
    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        path = self._path(path)
        if self.accounts and not path:
            return await self._account_root()
        del include_sha256
        if path.startswith("attachment/"):
            _ref, _part, filename = parse_attachment_locator(path)
            if self.browser:
                await browser_config(self.agent_id)
            return FileEntry(path=path, name=filename, is_dir=False, size=None,
                             mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")
        if not path or path.endswith("/"):
            node = (await self._folders()).get(path)
            if node is None:
                raise FileNotFoundError("Mail folder unavailable")
            return node.entry()
        ref = await self._message(path)
        # Header-only reads do not admit a message for autonomous processing.
        from .connection_service import resolve_mail_connection
        config = await resolve_mail_connection(self.agent_id)
        summary = await asyncio.to_thread(ImapClient(config).get_summary, ref)
        folder, _ = _message_path(path)
        return _message_entry(folder, summary)

    async def resource_list(self, path: str, *, recursive: bool, limit: int) -> FileListing:
        return await self.resource_list_page(path, recursive=recursive, limit=limit)

    @_bound_connection
    async def resource_list_page(self, path: str, *, recursive: bool, limit: int, cursor: str | None = None) -> FileListing:
        path = self._path(path)
        if recursive:
            raise ValueError("Browse Mail one IMAP folder at a time")
        limit = max(1, min(limit, 500))
        if self.accounts and not path:
            root = await self._account_root()
            offset, _unused, messages = _page(path, cursor)
            if messages:
                raise ValueError("Invalid Mail account cursor")
            entries = tuple(FileEntry(path=f"account/{identity}/", name=label, is_dir=True,
                metadata={"mail_connection_id": identity}) for identity, label in sorted(self.accounts.items()))
            more = offset + limit < len(entries)
            return FileListing(path, entries[offset:offset + limit], more,
                _cursor(path, offset + limit, None, False) if more else None, ancestors=(root,))
        if path.startswith("attachment/"):
            parts = path.strip("/").split("/")
            if len(parts) != 2:
                raise ValueError("Invalid Mail attachment collection")
            offset, _unused, messages = _page(path, cursor)
            if messages:
                raise ValueError("Invalid Mail attachment cursor")
            message = await attachment_message(self.agent_id, parts[1], browser=self.browser)
            entries = tuple(FileEntry(path=a.uri.partition("://")[2].removeprefix(self.prefix), name=a.filename, is_dir=False,
                                      size=a.size, mime_type=a.media_type) for a in message.attachments[offset:offset + limit])
            more = offset + limit < len(message.attachments)
            return FileListing(path, entries, more, _cursor(path, offset + limit, None, False) if more else None)
        folders = await self._folders()
        node = folders.get(path)
        if node is None:
            raise FileNotFoundError("Mail folder unavailable")
        parents = [folders[""].entry()]
        prefix = ""
        for part in path.strip("/").split("/") if path else []:
            prefix += part + "/"
            parents.append(folders[prefix].entry())

        def listing(entries: list[FileEntry], truncated: bool = False, next_cursor: str | None = None) -> FileListing:
            return FileListing(path, tuple(entries), truncated, next_cursor, ancestors=tuple(parents))

        offset, message_cursor, messages = _page(path, cursor)
        children = sorted((value for key, value in folders.items() if key and key.rstrip("/").rpartition("/")[0] == path.rstrip("/")), key=lambda f: f.name.casefold())
        entries = [] if messages else [value.entry() for value in children[offset:offset + limit]]
        offset += len(entries)
        if not messages and offset < len(children):
            return listing(entries, True, _cursor(path, offset, None, False))
        if node.mailbox is not None and node.mailbox.selectable:
            if len(entries) == limit:
                return listing(entries, True, _cursor(path, offset, None, True))
            query = MailSearchQuery(mailbox=node.mailbox.name, limit=limit - len(entries), cursor=message_cursor)
            if self.browser:
                config = await browser_config(self.agent_id)
                page = await asyncio.to_thread(ImapClient(config).search, query)
            else:
                page = await search(self.agent_id, query)
            entries.extend(_message_entry(path, summary) for summary in page.messages)
            return listing(entries, page.truncated,
                _cursor(path, offset, page.next_cursor, True) if page.next_cursor else None)
        return listing(entries)


__all__ = ["MailAttachmentTransport"]
