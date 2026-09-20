"""Bounded MIME parsing and construction for the Mail bridge."""

from __future__ import annotations

import re
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Iterable, Literal, cast
from urllib.parse import quote

from .contracts import (
    MailAttachment,
    MailConnectionConfig,
    MailMessageDetail,
    MailMessageRef,
    MailMessageSummary,
    OutgoingAttachment,
    OutgoingMail,
)


AI_DISCLOSURE_VERSION = "galaris-ai-v1"
AI_DISCLOSURE_PLAIN = (
    "---\n"
    "Ce message a été envoyé par un agent d'intelligence artificielle via Galaris.\n"
    "This message was sent by an artificial intelligence agent via Galaris."
)
AI_DISCLOSURE_HTML = (
    '<hr><p data-galaris-ai-disclosure="galaris-ai-v1">'
    "Ce message a été envoyé par un agent d’intelligence artificielle via Galaris.<br>"
    "This message was sent by an artificial intelligence agent via Galaris."
    "</p>"
)
_HEADER_LIMIT = 2_000
_ADDRESS_LIMIT = 100
_MIME_PART_LIMIT = 500


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.suppressed += 1
        elif self.suppressed == 0 and tag.lower() in {"br", "p", "div", "li", "tr", "hr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.suppressed:
            self.suppressed -= 1
        elif self.suppressed == 0 and tag.lower() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.suppressed == 0:
            self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts).replace("\r", "")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def _safe_header(value: object) -> str:
    raw = str(value or "")
    try:
        decoded = str(make_header(decode_header(raw)))
    except (LookupError, UnicodeError):
        decoded = raw
    return decoded.replace("\r", " ").replace("\n", " ")[:_HEADER_LIMIT].strip()


def _mailboxes(value: object) -> list[tuple[str, str]]:
    pairs = getaddresses([str(value or "")])[:_ADDRESS_LIMIT]
    return [
        (_safe_header(name), address[:320])
        for name, address in pairs
        if address
    ]


def _addresses(value: object) -> list[str]:
    return [address for _name, address in _mailboxes(value)]


def _safe_filename(value: object, fallback: str) -> str:
    filename = re.sub(r"[/\\\x00-\x1f\x7f]+", "_", _safe_header(value))[:255]
    return fallback if filename in {"", ".", ".."} else filename


def _date(value: object) -> datetime | None:
    try:
        return parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return None


def _payload_text(part: Message) -> str:
    payload = cast(object, part.get_payload(decode=True))
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        try:
            value = payload.decode(charset, errors="replace")
        except LookupError:
            value = payload.decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        value = payload
    else:
        raw = cast(object, part.get_payload())
        value = raw if isinstance(raw, str) else ""
    return value.replace("\x00", "")


def _body_and_attachments(
    message: Message,
) -> tuple[
    str,
    Literal["plain", "html-converted", "empty"],
    list[tuple[str, Message]],
]:
    plain: list[str] = []
    html_parts: list[str] = []
    attachments: list[tuple[str, Message]] = []
    for index, part in enumerate(message.walk(), start=1):
        if index > _MIME_PART_LIMIT:
            raise ValueError(f"Mail message exceeds the {_MIME_PART_LIMIT}-part MIME limit")
        if part.is_multipart():
            continue
        disposition = str(part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        part_id = f"part-{index}"
        if disposition == "attachment" or filename:
            attachments.append((part_id, part))
            continue
        content_type = part.get_content_type().lower()
        if content_type == "text/plain":
            plain.append(_payload_text(part))
        elif content_type == "text/html":
            html_parts.append(_payload_text(part))
    if plain:
        return "\n\n".join(plain).strip(), "plain", attachments
    if html_parts:
        extractor = _HtmlTextExtractor()
        extractor.feed("\n".join(html_parts))
        return extractor.text(), "html-converted", attachments
    return "", "empty", attachments


def parse_summary(raw_headers: bytes, ref: MailMessageRef, flags: Iterable[str]) -> MailMessageSummary:
    message = BytesParser(policy=policy.default).parsebytes(raw_headers, headersonly=True)
    flag_set = {flag.lower() for flag in flags}
    content_type = str(message.get("Content-Type") or "").lower()
    sender_name, sender_address = (_mailboxes(message.get("From")) or [("", "")])[0]
    return MailMessageSummary(
        ref=ref.encode(),
        subject=_safe_header(message.get("Subject")),
        from_name=sender_name,
        from_address=sender_address,
        to_addresses=_addresses(message.get("To")),
        date=_date(message.get("Date")),
        message_id=_safe_header(message.get("Message-ID")) or None,
        seen="\\seen" in flag_set,
        flagged="\\flagged" in flag_set,
        has_attachments="multipart/mixed" in content_type,
    )


def parse_message(
    raw_message: bytes,
    ref: MailMessageRef,
    flags: Iterable[str],
    *,
    body_offset: int,
    body_limit: int,
) -> MailMessageDetail:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    body, body_format, attachment_parts = _body_and_attachments(message)
    start = min(max(0, body_offset), len(body))
    end = min(len(body), start + max(1, min(body_limit, 50_000)))
    summary = parse_summary(raw_message, ref, flags)
    attachments: list[MailAttachment] = []
    encoded_ref = ref.encode()
    for part_id, part in attachment_parts:
        payload_value = cast(object, part.get_payload(decode=True))
        payload = payload_value if isinstance(payload_value, bytes) else b""
        safe_filename = _safe_filename(part.get_filename(), f"{part_id}.bin")
        attachments.append(
            MailAttachment(
                part_id=part_id,
                filename=safe_filename,
                media_type=part.get_content_type() or "application/octet-stream",
                size=len(payload),
                content_id=_safe_header(part.get("Content-ID")) or None,
                uri=(
                    "mail://attachment/"
                    f"{encoded_ref}/{part_id}/{quote(safe_filename, safe='')}"
                ),
            )
        )
    return MailMessageDetail(
        **summary.model_dump(),
        cc_addresses=_addresses(message.get("Cc")),
        reply_to_addresses=_addresses(message.get("Reply-To")),
        in_reply_to=_safe_header(message.get("In-Reply-To")) or None,
        references=_safe_header(message.get("References")).split()[:100],
        body=body[start:end],
        body_format=body_format,
        body_start=start,
        body_end=end,
        body_total=len(body),
        next_body_offset=end if end < len(body) else None,
        attachments=attachments,
    )


def extract_attachment(raw_message: bytes, part_id: str) -> OutgoingAttachment:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    _body, _format, attachments = _body_and_attachments(message)
    for candidate, part in attachments:
        if candidate != part_id:
            continue
        payload_value = cast(object, part.get_payload(decode=True))
        payload = payload_value if isinstance(payload_value, bytes) else b""
        filename = _safe_filename(part.get_filename(), f"{part_id}.bin")
        return OutgoingAttachment(
            filename=filename,
            media_type=part.get_content_type() or "application/octet-stream",
            content=payload,
        )
    raise FileNotFoundError("Mail attachment not found")


def build_message(
    config: MailConnectionConfig,
    outgoing: OutgoingMail,
    *,
    message_id: str,
    now: datetime,
) -> bytes:
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = Address(
        display_name=config.display_name,
        addr_spec=str(config.email_address),
    )
    message["To"] = ", ".join(outgoing.to)
    if outgoing.cc:
        message["Cc"] = ", ".join(outgoing.cc)
    if outgoing.reply_to:
        message["Reply-To"] = outgoing.reply_to
    message["Subject"] = outgoing.subject
    message["Date"] = format_datetime(now)
    message["Message-ID"] = message_id
    if outgoing.in_reply_to:
        message["In-Reply-To"] = outgoing.in_reply_to
    if outgoing.references:
        message["References"] = " ".join(outgoing.references[-50:])

    plain = f"{outgoing.body.rstrip()}\n\n{AI_DISCLOSURE_PLAIN}\n"
    message.set_content(plain)
    if outgoing.html_body is not None:
        original_html = outgoing.html_body.rstrip()
        closing_body = re.search(r"</body\s*>", original_html, flags=re.IGNORECASE)
        if closing_body is None:
            html_body = f"{original_html}\n{AI_DISCLOSURE_HTML}"
        else:
            html_body = (
                f"{original_html[:closing_body.start()]}{AI_DISCLOSURE_HTML}\n"
                f"{original_html[closing_body.start():]}"
            )
        message.add_alternative(html_body, subtype="html")
    for attachment in outgoing.attachments:
        maintype, separator, subtype = attachment.media_type.partition("/")
        if not separator:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    return message.as_bytes()


__all__ = [
    "AI_DISCLOSURE_HTML",
    "AI_DISCLOSURE_PLAIN",
    "AI_DISCLOSURE_VERSION",
    "build_message",
    "extract_attachment",
    "parse_message",
    "parse_summary",
]
