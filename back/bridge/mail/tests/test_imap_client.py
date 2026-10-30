from contextlib import contextmanager
from typing import Generator
from datetime import datetime, timezone

from pydantic import SecretStr
import pytest

from bridge.mail import imap_client
from bridge.mail.contracts import MailConnectionConfig, MailEndpointConfig, MailSearchQuery


def _client() -> imap_client.ImapClient:
    endpoint = MailEndpointConfig(
        host="mail.example.org",
        port=993,
        security="tls",
        username="agent@example.org",
        password=SecretStr("secret"),
    )
    return imap_client.ImapClient(
        MailConnectionConfig(
            connection_id=1,
            agent_id=2,
            email_address="agent@example.org",
            imap=endpoint,
            smtp=endpoint.model_copy(update={"port": 465}),
            connect_timeout_s=10,
            operation_timeout_s=30,
            max_attachment_bytes=1_000,
            max_total_attachment_bytes=2_000,
        )
    )


@pytest.mark.parametrize("provider_already_saved", [False, True])
def test_sent_copy_uses_exact_mime_and_does_not_duplicate_provider_copy(monkeypatch, provider_already_saved):
    from bridge.mail.contracts import MailboxInfo
    client = _client()
    raw = b"Message-ID: <synthetic@example.test>\r\n\r\nSynthetic greeting\r\n"
    appended = []
    exists = provider_already_saved
    sent_at = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    class FakeImap:
        def uid(self, *args):
            assert args == ("SEARCH", "CHARSET", "UTF-8", "HEADER", "Message-ID", b'"<synthetic@example.test>"')
            return "OK", [b"41" if exists else b""]

        def append(self, mailbox, flags, internal_date, message):
            nonlocal exists
            assert mailbox == b'"Sent Items"' and flags == r"(\Seen)"
            assert internal_date == '"02-Jan-2026 12:00:00 +0000"'
            appended.append(message)
            exists = True
            return "OK", [b"APPEND completed"]

    @contextmanager
    def session():
        yield FakeImap()

    monkeypatch.setattr(client, "_session", session)
    monkeypatch.setattr(client, "_mailboxes", lambda _: [MailboxInfo(name="Sent Items", role="sent")])
    monkeypatch.setattr(client, "_select", lambda _imap, mailbox, *, readonly: 1)
    for _ in range(2):
        assert client.store_sent_message(raw, message_id="<synthetic@example.test>", sent_at=sent_at) == "Sent Items"
    assert appended == ([] if provider_already_saved else [raw])


def test_search_criteria_encode_unicode_as_utf8_imap_argument() -> None:
    criteria = imap_client.ImapClient._criteria(  # pyright: ignore[reportPrivateUsage]
        MailSearchQuery(mailbox="INBOX", text="été", unread=True),
        before_uid=None,
    )

    assert criteria == ["TEXT", "été".encode().join((b'"', b'"')), "UNSEEN"]


def test_message_size_is_checked_before_fetching_full_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_fetch",
        lambda _imap, _uid, _query: (b"UID 1 RFC822.SIZE 1003001", b""),
    )

    with pytest.raises(ValueError, match="read limit"):
        client._ensure_message_size(object(), 1)  # pyright: ignore[reportPrivateUsage, reportArgumentType]


def test_cursor_is_bound_to_mailbox_and_uidvalidity() -> None:
    cursor = imap_client._encode_cursor("INBOX", 7, 42)  # pyright: ignore[reportPrivateUsage]

    assert imap_client._decode_cursor(cursor, "INBOX", 7) == 42  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError, match="stale"):
        imap_client._decode_cursor(cursor, "Archive", 7)  # pyright: ignore[reportPrivateUsage]


def test_poll_without_cursor_uses_uidnext_as_non_replaying_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()

    class FakeImap:
        def response(self, name: str) -> tuple[str, list[bytes]]:
            assert name == "UIDNEXT"
            return "UIDNEXT", [b"43"]

    @contextmanager
    def session() -> Generator[FakeImap, None, None]:
        yield FakeImap()

    monkeypatch.setattr(client, "_session", session)
    monkeypatch.setattr(client, "_select", lambda *_args, **_kwargs: 9)

    batch = client.poll_inbox(after_uid=None)

    assert batch.uid_validity == 9
    assert batch.latest_uid == 42
    assert batch.messages == []


def test_poll_fetches_only_strictly_new_uids_in_ascending_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()

    class FakeImap:
        def uid(self, *args: object) -> tuple[str, list[bytes]]:
            assert args == ("SEARCH", "UID", "41:*")
            # Some servers may include the range boundary/max marker. The bridge
            # must still filter the already-admitted UID itself.
            return "OK", [b"40 42 41"]

    @contextmanager
    def session() -> Generator[FakeImap, None, None]:
        yield FakeImap()

    headers = {
        41: b"From: first@example.org\r\nSubject: First\r\n\r\n",
        42: b"From: second@example.org\r\nSubject: Second\r\n\r\n",
    }
    monkeypatch.setattr(client, "_session", session)
    monkeypatch.setattr(client, "_select", lambda *_args, **_kwargs: 9)
    monkeypatch.setattr(
        client,
        "_fetch",
        lambda _imap, uid, _query: (f"UID {uid} FLAGS ()".encode(), headers[uid]),
    )

    batch = client.poll_inbox(after_uid=40)

    assert [message.subject for message in batch.messages] == ["First", "Second"]
    assert [message.ref for message in batch.messages] == [
        imap_client.MailMessageRef(mailbox="INBOX", uid_validity=9, uid=41).encode(),
        imap_client.MailMessageRef(mailbox="INBOX", uid_validity=9, uid=42).encode(),
    ]


def test_attachment_budget_rejects_mime_before_body_fetch(monkeypatch):
    from bridge.mail.contracts import MailMessageRef
    client = _client()
    queries = []
    @contextmanager
    def session():
        yield object()
    def fetch(_connection, _uid, query):
        queries.append(query)
        return b"UID 1 RFC822.SIZE 1001500", b""
    monkeypatch.setattr(client, "_session", session)
    monkeypatch.setattr(client, "_assert_ref", lambda *_a, **_k: None)
    monkeypatch.setattr(client, "_fetch", fetch)
    with pytest.raises(ValueError, match="read limit"):
        client.get_attachment(MailMessageRef(mailbox="INBOX", uid_validity=1, uid=1), "part-2", max_bytes=100)
    assert queries == ["(UID RFC822.SIZE)"]


@pytest.mark.parametrize("uidnext, existing, expected", [
    (b"8", b"7", 7),
    (None, b"2 7 4", 7),
    (None, b"", 0),
])
def test_poll_reports_current_mailbox_high_watermark_after_uid_validity_reset(monkeypatch, uidnext, existing, expected):
    """An old-generation cursor must not become the baseline of a rebuilt mailbox."""
    client = _client()

    class RebuiltMailbox:
        def response(self, name):
            assert name == "UIDNEXT"
            return "UIDNEXT", [uidnext]

        def uid(self, *args):
            # IMAP's reversed range can return the current highest UID, even
            # though it is lower than the previous generation's cursor.
            if args == ("SEARCH", "UID", "101:*"):
                return "OK", [b"7"]
            assert args == ("SEARCH", "ALL")
            return "OK", [existing]

    @contextmanager
    def session():
        yield RebuiltMailbox()

    monkeypatch.setattr(client, "_session", session)
    monkeypatch.setattr(client, "_select", lambda _imap, mailbox, *, readonly: 12)
    batch = client.poll_inbox(after_uid=100)
    assert batch.uid_validity == 12
    assert batch.latest_uid == expected
    assert batch.messages == []


@pytest.mark.parametrize("declared_size", [101, 50])
def test_raw_message_export_enforces_its_budget_before_writing(monkeypatch, declared_size):
    from bridge.mail.contracts import MailMessageRef
    client = _client()
    calls = []

    @contextmanager
    def session():
        yield object()

    def fetch(_imap, _uid, query):
        calls.append(query)
        return f"UID 1 RFC822.SIZE {declared_size}".encode(), b"x" * 101

    monkeypatch.setattr(client, "_session", session)
    monkeypatch.setattr(client, "_assert_ref", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "_fetch", fetch)
    with pytest.raises(ValueError, match="byte limit"):
        client.get_raw_message(MailMessageRef(mailbox="INBOX", uid_validity=7, uid=1), max_bytes=100)
    assert len(calls) == (1 if declared_size > 100 else 2)
