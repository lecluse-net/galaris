from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.connection import Connection
from bridge.mail import connection_service


@pytest.mark.asyncio
async def test_mail_uses_email_and_one_password_for_imap_and_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(id=9, tool_id=4, agent_id=3, active=True)
    monkeypatch.setattr(
        connection_service.tool_service,
        "get_tool_by_id",
        AsyncMock(return_value=SimpleNamespace(code="mail")),
    )
    monkeypatch.setattr(
        connection_service.connection_service,
        "get_params_as_dict",
        AsyncMock(return_value=(connection, {
            "email_address": "agent@example.org",
            "password": "application-secret",
            "imap_host": "imap.example.test",
            "imap_port": "993",
            "imap_security": "tls",
            "smtp_host": "smtp.example.test",
            "smtp_port": "465",
            "smtp_security": "tls",
            "poll_interval_s": "120",
            "max_attachment_mb": "12",
            "max_total_attachment_mb": "24",
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
    assert config.smtp.username == "agent@example.org"
    assert config.imap.password.get_secret_value() == "application-secret"
    assert config.smtp.password.get_secret_value() == "application-secret"
    assert config.poll_interval_s == 120
    assert config.agent_label == "Mail Agent"
    assert config.approval_required is False
    assert config.approver_user_id is None
    assert config.max_attachment_bytes == 12 * 1024 * 1024
    assert config.max_total_attachment_bytes == 24 * 1024 * 1024
