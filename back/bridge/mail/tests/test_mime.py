from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser

from pydantic import SecretStr

from bridge.mail.contracts import (
    MailConnectionConfig,
    MailEndpointConfig,
    MailMessageRef,
    OutgoingAttachment,
    OutgoingMail,
)
from bridge.mail.mime import (
    AI_DISCLOSURE_HTML,
    AI_DISCLOSURE_PLAIN,
    build_message,
    extract_attachment,
    parse_message,
    parse_summary,
)


def _config() -> MailConnectionConfig:
    endpoint = MailEndpointConfig(
        host="mail.example.org",
        port=993,
        security="tls",
        username="agent@example.org",
        password=SecretStr("secret"),
    )
    return MailConnectionConfig(
        connection_id=1,
        agent_id=2,
        email_address="agent@example.org",
        display_name="Galaris Agent",
        imap=endpoint,
        smtp=endpoint.model_copy(update={"port": 465}),
        connect_timeout_s=10,
        operation_timeout_s=30,
        max_attachment_bytes=1_000_000,
        max_total_attachment_bytes=2_000_000,
    )


def test_build_message_always_adds_disclosure_to_plain_and_html() -> None:
    raw = build_message(
        _config(),
        OutgoingMail(
            to=("recipient@example.org",),
            cc=(),
            bcc=("hidden@example.org",),
            subject="Compte rendu",
            body="Bonjour",
            html_body="<p>Bonjour</p>",
            attachments=(),
        ),
        message_id="<test@example.org>",
        now=datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
    )

    message = BytesParser(policy=policy.default).parsebytes(raw)
    parts = list(message.iter_parts())
    assert AI_DISCLOSURE_PLAIN in parts[0].get_content().replace("\r", "")
    assert AI_DISCLOSURE_HTML in parts[1].get_content()
    assert message.get("Bcc") is None
    assert message["Message-ID"] == "<test@example.org>"


def test_parse_message_marks_external_content_and_exposes_attachment_uri() -> None:
    raw = build_message(
        _config(),
        OutgoingMail(
            to=("recipient@example.org",),
            cc=(),
            bcc=(),
            subject="Pièce jointe",
            body="Voir le rapport",
            html_body=None,
            attachments=(
                OutgoingAttachment(
                    filename="rapport été.pdf",
                    media_type="application/pdf",
                    content=b"%PDF-test",
                ),
            ),
        ),
        message_id="<attachment@example.org>",
        now=datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
    )
    reference = MailMessageRef(mailbox="INBOX", uid_validity=7, uid=8)

    detail = parse_message(raw, reference, ["\\Seen"], body_offset=0, body_limit=20)

    assert detail.untrusted_content is True
    assert detail.seen is True
    assert len(detail.attachments) == 1
    assert detail.attachments[0].uri.startswith(
        f"mail://attachment/{reference.encode()}/"
    )
    attachment = extract_attachment(raw, detail.attachments[0].part_id)
    assert attachment.content == b"%PDF-test"
    assert attachment.filename == "rapport été.pdf"


def test_parse_summary_keeps_sender_name_for_contact_memory() -> None:
    reference = MailMessageRef(mailbox="INBOX", uid_validity=7, uid=9)
    summary = parse_summary(
        (
            "From: =?utf-8?q?Alice_Exemple?= <Alice@Example.ORG>\r\n"
            "To: agent@example.org\r\n"
            "Subject: Bonjour\r\n\r\n"
        ).encode("ascii"),
        reference,
        [],
    )

    assert summary.from_name == "Alice Exemple"
    assert summary.from_address == "Alice@Example.ORG"
