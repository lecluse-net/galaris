"""Read-only ``mail://`` transport for MIME attachments."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

from app.file_share import FileEntry, FileListing
from .service import get_attachment, get_message, parse_attachment_locator


class MailAttachmentTransport:
    """Expose attachments without turning the Mail bridge into a writable share."""

    def __init__(self, agent_id: int) -> None:
        self.agent_id = agent_id

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = 512 * 1024 * 1024) -> int:
        if target:
            raise ValueError("mail:// attachments do not accept a target")
        message_ref, part_id, _filename = parse_attachment_locator(remote)
        attachment = await get_attachment(self.agent_id, message_ref, part_id, max_bytes=max_bytes)
        if len(attachment.content) > max_bytes:
            raise ValueError("Mail attachment exceeds the requested byte limit")
        await asyncio.to_thread(dest.write_bytes, attachment.content)
        return len(attachment.content)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        del src, filename, target
        raise PermissionError("mail:// attachments are read-only")

    async def resource_info(
        self,
        path: str,
        *,
        include_sha256: bool = False,
    ) -> FileEntry:
        del include_sha256
        _message_ref, _part_id, filename = parse_attachment_locator(path)
        # A descriptor must not download the MIME message ahead of the caller's
        # budget. Existence and exact size are checked by bounded download_to.
        return FileEntry(path=path, is_dir=False, size=None,
                         mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")

    async def resource_list(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int,
    ) -> FileListing:
        del recursive
        segments = tuple(part for part in path.strip("/").split("/") if part)
        if len(segments) != 2 or segments[0] != "attachment":
            raise ValueError(
                "List mail://attachment/<message-ref>/ to enumerate attachments"
            )
        message_ref = segments[1]
        message = await get_message(self.agent_id, message_ref, body_limit=1)
        entries = tuple(
            FileEntry(
                path=attachment.uri.removeprefix("mail://"),
                is_dir=False,
                size=attachment.size,
                mime_type=attachment.media_type,
            )
            for attachment in message.attachments[:limit]
        )
        return FileListing(
            path=f"attachment/{message_ref}/",
            entries=entries,
            truncated=len(message.attachments) > limit,
        )


__all__ = ["MailAttachmentTransport"]
