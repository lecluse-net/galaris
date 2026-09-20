from contextlib import contextmanager
from typing import Generator

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
