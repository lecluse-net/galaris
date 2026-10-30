from unittest.mock import AsyncMock

import pytest

from bridge.mail import file_transport
from bridge.mail.contracts import MailboxInfo, MailMessageRef, OutgoingAttachment


@pytest.mark.asyncio
async def test_mail_root_exposes_imap_folders(monkeypatch):
    monkeypatch.setattr(file_transport, "list_mailboxes", AsyncMock(return_value=[
        MailboxInfo(name="INBOX", delimiter="/"),
        MailboxInfo(name="Projects/Example", delimiter="/"),
    ]))
    listing = await file_transport.MailAttachmentTransport(12).resource_list("", recursive=False, limit=50)
    assert [entry.name for entry in listing.entries] == ["INBOX", "Projects"]
    assert all(entry.is_dir for entry in listing.entries)


@pytest.mark.asyncio
async def test_mail_hierarchy_keeps_delimiters_unicode_and_bounded_folder_pages(monkeypatch):
    monkeypatch.setattr(file_transport, "list_mailboxes", AsyncMock(return_value=[
        MailboxInfo(name="Projects.Example", delimiter="."),
        MailboxInfo(name="Projects", delimiter=".", selectable=False),
        MailboxInfo(name="Envoy&AOk-s", delimiter="/"),
        MailboxInfo(name="Literal/Name", delimiter=None),
    ]))
    transport = file_transport.MailAttachmentTransport(12)
    first = await transport.resource_list_page("", recursive=False, limit=2)
    second = await transport.resource_list_page("", recursive=False, limit=2, cursor=first.next_cursor)
    assert [item.name for item in (*first.entries, *second.entries)] == ["Envoyés", "Literal/Name", "Projects"]
    assert first.truncated and second.next_cursor is None
    projects = second.entries[0]
    nested = await transport.resource_list(projects.path, recursive=False, limit=50)
    assert [item.name for item in nested.entries] == ["Example"]
    assert [item.name for item in nested.ancestors] == ["Mail", "Projects"]
    with pytest.raises(ValueError, match="cursor"):
        await transport.resource_list_page(projects.path, recursive=False, limit=2, cursor=first.next_cursor)
    with pytest.raises(ValueError, match="one IMAP folder"):
        await transport.resource_list("", recursive=True, limit=50)


@pytest.mark.asyncio
async def test_mail_transport_is_read_only_and_downloads_exact_attachment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    reference = MailMessageRef(mailbox="INBOX", uid_validity=4, uid=5).encode()
    attachment = OutgoingAttachment(
        filename="report.pdf",
        media_type="application/pdf",
        content=b"report",
    )
    getter = AsyncMock(return_value=attachment)
    monkeypatch.setattr(file_transport, "get_attachment", getter)
    transport = file_transport.MailAttachmentTransport(12)
    destination = tmp_path / "report.pdf"

    size = await transport.download_to(
        f"attachment/{reference}/part-2/report.pdf",
        destination,
    )

    assert size == 6
    assert destination.read_bytes() == b"report"
    getter.assert_awaited_once_with(12, reference, "part-2", max_bytes=512 * 1024 * 1024)
    with pytest.raises(PermissionError):
        await transport.upload_from(destination, "replacement.pdf")
