from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.connection import Connection
from app.tools.protocols import ProtocolConfig
from bridge.mail import connection_service


@pytest.mark.asyncio
@pytest.mark.parametrize("separate_smtp", [False, True])
@pytest.mark.parametrize("allowed, expected", [
    (None, ()), ("", ()), (" , , ", ()),
    (" INBOX, Projects/Active, INBOX ", ("INBOX", "Projects/Active")),
    ('["INBOX", "Projects, Active"]', ("INBOX", "Projects, Active")),
    ('[]', ()),
])
async def test_mail_uses_email_and_one_password_for_imap_and_smtp(
    monkeypatch: pytest.MonkeyPatch,
    allowed, expected,
    separate_smtp,
) -> None:
    connection = Connection(id=9, tool_id=4, agent_id=3, active=True)
    monkeypatch.setattr(
        connection_service.tool_service,
        "get_tool_by_id",
        AsyncMock(return_value=SimpleNamespace(code="mail", mail=ProtocolConfig(param_map={"smtp_username": "relay_username", "smtp_password": "relay_secret"} if separate_smtp else {}), file_share=None)),
    )
    monkeypatch.setattr(
        connection_service.connection_service,
        "get_params_as_dict",
        AsyncMock(return_value=(connection, {
            "email_address": "agent@example.org",
            "password": "application-secret",
            "relay_username": "relay-user",
            "relay_secret": "separate-smtp-secret",
            "imap_host": "imap.example.test",
            "imap_port": "993",
            "imap_security": "tls",
            "smtp_host": "smtp.example.test",
            "smtp_port": "465",
            "smtp_security": "tls",
            "poll_interval_s": "120",
            "max_attachment_mb": "12",
            "max_total_attachment_mb": "24",
            "allowed_mailboxes": allowed,
            "approval_required": "true",  # A stale legacy value grants no separate policy.
        })),
    )
    monkeypatch.setattr(
        connection_service,
        "get_agent_record",
        AsyncMock(return_value=SimpleNamespace(first_name="Mail", last_name="Agent")),
    )

    config = await connection_service._config_from_connection(  # pyright: ignore[reportPrivateUsage]
        connection,
        require_active=True,
    )

    assert config.email_address == "agent@example.org"
    assert config.imap.username == "agent@example.org"
    assert config.smtp.username == ("relay-user" if separate_smtp else "agent@example.org")
    assert config.imap.password.get_secret_value() == "application-secret"
    assert config.smtp.password.get_secret_value() == ("separate-smtp-secret" if separate_smtp else "application-secret")
    assert config.poll_interval_s == 120
    assert config.agent_label == "Mail Agent"
    assert config.approval_required is False
    assert config.approver_user_id is None
    assert config.max_attachment_bytes == 12 * 1024 * 1024
    assert config.max_total_attachment_bytes == 24 * 1024 * 1024
    assert config.allowed_mailboxes == expected


@pytest.mark.parametrize("raw", ["INBOX, bad\x00folder", "x" * 513, ",".join(str(i) for i in range(501)), '[1]', '[""]', '["INBOX"'])
def test_invalid_allowed_mailboxes_do_not_fall_back_to_unrestricted(raw):
    with pytest.raises(ValueError, match="allowed_mailboxes"):
        connection_service._allowed_mailboxes({"allowed_mailboxes": raw})
