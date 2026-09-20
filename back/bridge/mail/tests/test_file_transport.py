from unittest.mock import AsyncMock

import pytest

from bridge.mail import file_transport
from bridge.mail.contracts import MailMessageRef, OutgoingAttachment


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
