"""Synchronous IMAP adapter executed in a worker thread by the Mail service."""

from __future__ import annotations

import base64
import imaplib
import json
import re
import ssl
import socket
from threading import Timer
from contextlib import contextmanager
from datetime import date
from collections.abc import Generator, Iterable
from typing import Sequence, cast

from .contracts import (
    MailConnectionConfig,
    MailMessageDetail,
    MailMessageRef,
    MailMessageSummary,
    MailMutationResult,
    MailPollBatch,
    MailSearchPage,
    MailSearchQuery,
    MailboxInfo,
    OutgoingAttachment,
)
from .mime import extract_attachment, parse_message, parse_summary


_LIST_PATTERN = re.compile(
    rb"^\((?P<flags>[^)]*)\)\s+(?P<delimiter>NIL|\"(?:[^\"\\]|\\.)*\")\s+(?P<name>.+)$"
)
_UID_PATTERN = re.compile(rb"\bUID\s+(\d+)\b", re.IGNORECASE)
_FLAGS_PATTERN = re.compile(rb"\bFLAGS\s+\(([^)]*)\)", re.IGNORECASE)
_COPYUID_PATTERN = re.compile(rb"(?:COPYUID\s+)?(\d+)\s+\S+\s+(\d+)", re.IGNORECASE)
_SIZE_PATTERN = re.compile(rb"\bRFC822\.SIZE\s+(\d+)\b", re.IGNORECASE)


def _decode_atom(value: bytes) -> str:
    raw = value.strip()
    if raw.startswith(b'"') and raw.endswith(b'"'):
        raw = raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
    return raw.decode("utf-8", errors="replace").replace("\x00", "")


def _quote(value: str) -> str:
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Invalid control character in IMAP search value")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    # imaplib's runtime accepts bytes for command arguments, although its type stub
    # narrows variadic UID arguments to str. Bytes are required for UTF-8 SEARCH terms.
    return cast(str, f'"{escaped}"'.encode("utf-8"))


def _role(attributes: Sequence[str], name: str):
    lowered = {item.lower() for item in attributes}
    if "\\sent" in lowered:
        return "sent"
    if "\\trash" in lowered:
        return "trash"
    if "\\drafts" in lowered:
        return "drafts"
    if "\\junk" in lowered or "\\spam" in lowered:
        return "junk"
    if "\\archive" in lowered or "\\all" in lowered:
        return "archive"
    if name.upper() == "INBOX":
        return "inbox"
    return None


def _encode_cursor(mailbox: str, uid_validity: int, before_uid: int) -> str:
    raw = json.dumps(
        {"m": mailbox, "v": uid_validity, "b": before_uid},
        separators=(",", ":"),
    ).encode("utf-8")
    return "c1_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str, mailbox: str, uid_validity: int) -> int:
    if not value.startswith("c1_") or len(value) > 2048:
        raise ValueError("Invalid Mail search cursor")
    encoded = value[3:]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = cast(dict[str, object], json.loads(raw.decode("utf-8")))
        cursor_mailbox = str(data.get("m") or "")
        cursor_validity = int(str(data.get("v")))
        before_uid = int(str(data.get("b")))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid Mail search cursor") from exc
    if cursor_mailbox != mailbox or cursor_validity != uid_validity:
        raise ValueError("Mail search cursor is stale or belongs to another mailbox")
    if before_uid <= 0:
        raise ValueError("Invalid Mail search cursor")
    return before_uid


class ImapClient:
    def __init__(self, config: MailConnectionConfig) -> None:
        self.config = config

    @contextmanager
    def _session(self) -> Generator[imaplib.IMAP4, None, None]:
        endpoint = self.config.imap
        context = ssl.create_default_context()
        if endpoint.security == "tls":
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                endpoint.host,
                endpoint.port,
                ssl_context=context,
                timeout=self.config.connect_timeout_s,
            )
        else:
            client = imaplib.IMAP4(
                endpoint.host,
                endpoint.port,
                timeout=self.config.connect_timeout_s,
            )
            client.starttls(ssl_context=context)
        try:
            client.sock.settimeout(self.config.operation_timeout_s)
            client.login(endpoint.username, endpoint.password.get_secret_value())
            yield client
        finally:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    @staticmethod
    def _require_ok(status: str, data: object, operation: str) -> None:
        if status != "OK":
            raise RuntimeError(f"IMAP {operation} failed")
        if data is None:
            raise RuntimeError(f"IMAP {operation} returned no data")

    @staticmethod
    def _mailboxes(client: imaplib.IMAP4) -> list[MailboxInfo]:
        status, data = client.list()
        ImapClient._require_ok(status, data, "LIST")
        result: list[MailboxInfo] = []
        for item in data or []:
            if not isinstance(item, bytes):
                continue
            match = _LIST_PATTERN.match(item)
            if match is None:
                continue
            attributes = [
                part.decode("ascii", errors="ignore")
                for part in match.group("flags").split()
            ]
            delimiter_raw = match.group("delimiter")
            delimiter = None if delimiter_raw == b"NIL" else _decode_atom(delimiter_raw)
            name = _decode_atom(match.group("name"))[:512]
            if not name:
                continue
            lowered = {value.lower() for value in attributes}
            result.append(
                MailboxInfo(
                    name=name,
                    delimiter=delimiter,
                    attributes=attributes,
                    role=_role(attributes, name),
                    selectable="\\noselect" not in lowered,
                )
            )
        return result

    @staticmethod
    def _select(client: imaplib.IMAP4, mailbox: str, *, readonly: bool) -> int:
        status, _data = client.select(mailbox, readonly=readonly)
        ImapClient._require_ok(status, _data, "SELECT")
        response = client.response("UIDVALIDITY")
        values = response[1] if response else None
        if not values or not isinstance(values[0], bytes):
            raise RuntimeError("IMAP server did not provide UIDVALIDITY")
        try:
            uid_validity = int(values[0].split()[0])
        except (ValueError, IndexError) as exc:
            raise RuntimeError("Invalid IMAP UIDVALIDITY response") from exc
        if uid_validity <= 0:
            raise RuntimeError("Invalid IMAP UIDVALIDITY response")
        return uid_validity

    @staticmethod
    def _validate_mailbox(client: imaplib.IMAP4, mailbox: str) -> None:
        available = {
            item.name for item in ImapClient._mailboxes(client) if item.selectable
        }
        if mailbox not in available and not (mailbox.upper() == "INBOX" and "INBOX" in available):
            raise ValueError("Unknown or non-selectable IMAP mailbox")

    @staticmethod
    def _flags(metadata: bytes) -> list[str]:
        match = _FLAGS_PATTERN.search(metadata)
        if match is None:
            return []
        return [item.decode("ascii", errors="ignore") for item in match.group(1).split()]

    @staticmethod
    def _fetch(client: imaplib.IMAP4, uid: int, query: str) -> tuple[bytes, bytes]:
        status, data = client.uid("FETCH", str(uid), query)
        ImapClient._require_ok(status, data, "FETCH")
        metadata = b""
        payload = b""
        for item in data or []:
            if isinstance(item, tuple):
                values = cast(tuple[object, ...], item)
                if len(values) != 2:
                    continue
                head, body = values
                if isinstance(head, bytes):
                    metadata += head
                if isinstance(body, bytes):
                    payload += body
            elif isinstance(item, bytes):
                metadata += item
        fetched_uid = _UID_PATTERN.search(metadata)
        if fetched_uid is None or int(fetched_uid.group(1)) != uid:
            raise FileNotFoundError("Mail message not found")
        return metadata, payload

    def _ensure_message_size(self, client: imaplib.IMAP4, uid: int, *, max_bytes: int | None = None) -> int:
        metadata, _payload = self._fetch(client, uid, "(UID RFC822.SIZE)")
        match = _SIZE_PATTERN.search(metadata)
        if match is None:
            raise RuntimeError("IMAP server did not provide RFC822.SIZE")
        maximum = self.config.max_total_attachment_bytes + 1_000_000
        if max_bytes is not None:
            maximum = min(maximum, max_bytes * 2 + 1_000_000)
        if int(match.group(1)) > maximum:
            raise ValueError(
                f"Mail message exceeds the configured {maximum}-byte read limit"
            )

        return maximum

    @staticmethod
    def _assert_ref(client: imaplib.IMAP4, ref: MailMessageRef, *, readonly: bool) -> None:
        ImapClient._validate_mailbox(client, ref.mailbox)
        current = ImapClient._select(client, ref.mailbox, readonly=readonly)
        if current != ref.uid_validity:
            raise ValueError("Mail message reference is stale because UIDVALIDITY changed")

    def status(self) -> tuple[list[MailboxInfo], int]:
        with self._session() as client:
            status, _data = client.noop()
            self._require_ok(status, _data, "NOOP")
            mailboxes = self._mailboxes(client)
            return mailboxes, len(mailboxes)

    @staticmethod
    def _criteria(query: MailSearchQuery, before_uid: int | None) -> list[str]:
        criteria: list[str] = []
        if before_uid is not None:
            criteria.extend(["UID", f"1:{before_uid - 1}"])
        if query.text:
            criteria.extend(["TEXT", _quote(query.text[:500])])
        if query.subject:
            criteria.extend(["SUBJECT", _quote(query.subject[:500])])
        if query.from_address:
            criteria.extend(["FROM", _quote(query.from_address[:320])])
        if query.to_address:
            criteria.extend(["TO", _quote(query.to_address[:320])])
        if query.since:
            parsed = date.fromisoformat(query.since)
            criteria.extend(["SINCE", parsed.strftime("%d-%b-%Y")])
        if query.before:
            parsed = date.fromisoformat(query.before)
            criteria.extend(["BEFORE", parsed.strftime("%d-%b-%Y")])
        if query.unread is True:
            criteria.append("UNSEEN")
        elif query.unread is False:
            criteria.append("SEEN")
        if query.flagged is True:
            criteria.append("FLAGGED")
        elif query.flagged is False:
            criteria.append("UNFLAGGED")
        if query.has_attachments is True:
            criteria.extend(["HEADER", "Content-Disposition", _quote("attachment")])
        elif query.has_attachments is False:
            raise ValueError("IMAP cannot safely filter has_attachments=false without scanning")
        return criteria or ["ALL"]

    def search(self, query: MailSearchQuery) -> MailSearchPage:
        limit = max(1, min(query.limit, 50))
        with self._session() as client:
            self._validate_mailbox(client, query.mailbox)
            uid_validity = self._select(client, query.mailbox, readonly=True)
            before_uid = (
                _decode_cursor(query.cursor, query.mailbox, uid_validity)
                if query.cursor
                else None
            )
            status, data = client.uid(
                "SEARCH", "CHARSET", "UTF-8", *self._criteria(query, before_uid)
            )
            self._require_ok(status, data, "SEARCH")
            raw_ids = next(
                (item for item in (data or []) if isinstance(item, bytes)),
                b"",
            )
            try:
                uids = sorted(
                    {int(value) for value in raw_ids.split() if int(value) > 0},
                    reverse=True,
                )
            except ValueError as exc:
                raise RuntimeError("Invalid IMAP SEARCH response") from exc
            page_uids = uids[: limit + 1]
            summaries: list[MailMessageSummary] = []
            for uid in page_uids[:limit]:
                metadata, headers = self._fetch(
                    client,
                    uid,
                    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID CONTENT-TYPE)])",
                )
                summaries.append(
                    parse_summary(
                        headers,
                        MailMessageRef(
                            mailbox=query.mailbox,
                            uid_validity=uid_validity,
                            uid=uid,
                        ),
                        self._flags(metadata),
                    )
                )
            truncated = len(page_uids) > limit
            next_cursor = (
                _encode_cursor(query.mailbox, uid_validity, page_uids[limit - 1])
                if truncated and page_uids
                else None
            )
            return MailSearchPage(
                mailbox=query.mailbox,
                uid_validity=uid_validity,
                messages=summaries,
                next_cursor=next_cursor,
                truncated=truncated,
            )

    def poll_inbox(
        self,
        *,
        after_uid: int | None,
        limit: int = 50,
    ) -> MailPollBatch:
        """Return new INBOX summaries in ascending UID order.

        A missing cursor establishes a baseline without downloading existing messages.
        Callers persist each returned UID only after its canonical admission succeeds.
        """

        safe_limit = max(1, min(limit, 50))
        with self._session() as client:
            uid_validity = self._select(client, "INBOX", readonly=True)
            if after_uid is None:
                response = client.response("UIDNEXT")
                values = response[1] if response else None
                if values and isinstance(values[0], bytes):
                    try:
                        latest_uid = max(0, int(values[0].split()[0]) - 1)
                    except (ValueError, IndexError) as exc:
                        raise RuntimeError("Invalid IMAP UIDNEXT response") from exc
                else:
                    status, data = client.uid("SEARCH", "ALL")
                    self._require_ok(status, data, "SEARCH")
                    raw_ids = next(
                        (item for item in (data or []) if isinstance(item, bytes)),
                        b"",
                    )
                    try:
                        latest_uid = max(
                            (int(value) for value in raw_ids.split()),
                            default=0,
                        )
                    except ValueError as exc:
                        raise RuntimeError("Invalid IMAP SEARCH response") from exc
                return MailPollBatch(
                    uid_validity=uid_validity,
                    latest_uid=latest_uid,
                )

            status, data = client.uid(
                "SEARCH",
                "UID",
                f"{max(1, after_uid + 1)}:*",
            )
            self._require_ok(status, data, "SEARCH")
            raw_ids = next(
                (item for item in (data or []) if isinstance(item, bytes)),
                b"",
            )
            try:
                uids = sorted(
                    {
                        int(value)
                        for value in raw_ids.split()
                        if int(value) > after_uid
                    }
                )
            except ValueError as exc:
                raise RuntimeError("Invalid IMAP SEARCH response") from exc
            page_uids = uids[:safe_limit]
            summaries: list[MailMessageSummary] = []
            for uid in page_uids:
                metadata, headers = self._fetch(
                    client,
                    uid,
                    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID CONTENT-TYPE)])",
                )
                summaries.append(
                    parse_summary(
                        headers,
                        MailMessageRef(
                            mailbox="INBOX",
                            uid_validity=uid_validity,
                            uid=uid,
                        ),
                        self._flags(metadata),
                    )
                )
            return MailPollBatch(
                uid_validity=uid_validity,
                latest_uid=max(uids, default=after_uid),
                messages=summaries,
                truncated=len(uids) > safe_limit,
            )

    def get_message(
        self,
        ref: MailMessageRef,
        *,
        body_offset: int,
        body_limit: int,
    ) -> MailMessageDetail:
        with self._session() as client:
            self._assert_ref(client, ref, readonly=True)
            self._ensure_message_size(client, ref.uid)
            metadata, raw = self._fetch(client, ref.uid, "(UID FLAGS BODY.PEEK[])")
            return parse_message(
                raw,
                ref,
                self._flags(metadata),
                body_offset=body_offset,
                body_limit=body_limit,
            )

    def set_flags(
        self,
        ref: MailMessageRef,
        *,
        seen: bool | None,
        flagged: bool | None,
    ) -> MailMutationResult:
        if seen is None and flagged is None:
            raise ValueError("At least one Mail flag must be supplied")
        with self._session() as client:
            self._assert_ref(client, ref, readonly=False)
            for value, flag in ((seen, "\\Seen"), (flagged, "\\Flagged")):
                if value is None:
                    continue
                operation = "+FLAGS.SILENT" if value else "-FLAGS.SILENT"
                status, data = client.uid("STORE", str(ref.uid), operation, f"({flag})")
                self._require_ok(status, data, "STORE")
            metadata, _payload = self._fetch(client, ref.uid, "(UID FLAGS)")
            flags = {item.lower() for item in self._flags(metadata)}
            return MailMutationResult(
                ref=ref.encode(),
                state="flags-updated",
                seen="\\seen" in flags,
                flagged="\\flagged" in flags,
            )

    def move(self, ref: MailMessageRef, mailbox: str) -> MailMutationResult:
        with self._session() as client:
            self._validate_mailbox(client, mailbox)
            self._assert_ref(client, ref, readonly=False)
            capabilities = {
                (
                    item.decode("ascii", errors="ignore")
                    if isinstance(item, bytes)
                    else str(item)
                ).upper()
                for item in cast(Iterable[object], client.capabilities)
            }
            if "MOVE" in capabilities:
                status, data = client.uid("MOVE", str(ref.uid), mailbox)
                self._require_ok(status, data, "MOVE")
            else:
                status, data = client.uid("COPY", str(ref.uid), mailbox)
                self._require_ok(status, data, "COPY")
                status, data = client.uid(
                    "STORE", str(ref.uid), "+FLAGS.SILENT", "(\\Deleted)"
                )
                self._require_ok(status, data, "STORE")
            new_uid: int | None = None
            copy_response = client.response("COPYUID")
            copy_values = copy_response[1] if copy_response else None
            for item in copy_values or []:
                if not isinstance(item, bytes):
                    continue
                match = _COPYUID_PATTERN.search(item)
                if match is not None:
                    new_uid = int(match.group(2))
                    break
            destination_validity = self._select(client, mailbox, readonly=True)
            new_ref = (
                MailMessageRef(
                    mailbox=mailbox,
                    uid_validity=destination_validity,
                    uid=new_uid,
                ).encode()
                if new_uid is not None
                else None
            )
            return MailMutationResult(
                ref=ref.encode(),
                state="moved",
                new_ref=new_ref,
            )

    def get_attachment(self, ref: MailMessageRef, part_id: str, *, max_bytes: int | None = None) -> OutgoingAttachment:
        with self._session() as client:
            def interrupt_read() -> None:
                try:
                    client.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            deadline = Timer(120, interrupt_read)
            deadline.daemon = True
            deadline.start()
            try:
                self._assert_ref(client, ref, readonly=True)
                maximum = self._ensure_message_size(client, ref.uid, max_bytes=max_bytes)
                _metadata, raw = self._fetch(client, ref.uid, f"(UID BODY.PEEK[]<0.{maximum + 1}>)")
                if len(raw) > maximum:
                    raise ValueError("Mail message exceeds the MIME read limit")
                attachment = extract_attachment(raw, part_id)
                if max_bytes is not None and len(attachment.content) > max_bytes:
                    raise ValueError("Mail attachment exceeds the requested byte limit")
                if len(attachment.content) > self.config.max_attachment_bytes:
                    raise ValueError("Mail attachment exceeds the configured size limit")
                return attachment
            finally:
                deadline.cancel()

    def message_id_exists(self, mailbox: str, message_id: str) -> bool:
        with self._session() as client:
            self._validate_mailbox(client, mailbox)
            self._select(client, mailbox, readonly=True)
            status, data = client.uid(
                "SEARCH",
                "CHARSET",
                "UTF-8",
                "HEADER",
                "Message-ID",
                _quote(message_id[:255]),
            )
            self._require_ok(status, data, "SEARCH")
            return any(isinstance(item, bytes) and bool(item.strip()) for item in data or [])


__all__ = ["ImapClient"]
