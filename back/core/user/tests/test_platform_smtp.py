"""The selected SMTP security and authentication modes control the actual exchange."""

from base64 import b64decode, b64encode
import os
from smtplib import SMTPNotSupportedError
from unittest.mock import Mock

import pytest
import spnego

from core.user import platform_mail, smtp_sasl


@pytest.mark.parametrize(
    ("security", "authentication", "mechanism", "steps"),
    [
        ("tls", "password", "PLAIN", ["ehlo_or_helo_if_needed", "auth"]),
        ("starttls", "cram-md5", "CRAM-MD5", ["starttls", "ehlo_or_helo_if_needed", "auth"]),
        ("none", "none", None, []),
        ("starttls", "auto", None, ["starttls", "login"]),
    ],
)
def test_transport_negotiates_only_the_selected_modes(monkeypatch, security, authentication, mechanism, steps):
    smtp = Mock(esmtp_features={"auth": "PLAIN LOGIN CRAM-MD5"})
    normal = Mock(return_value=smtp)
    implicit = Mock(return_value=smtp)
    monkeypatch.setattr(platform_mail, "SMTP", normal)
    monkeypatch.setattr(platform_mail, "SMTP_SSL", implicit)
    transport = platform_mail.PlatformSmtp(
        "smtp.example.com", 465 if security == "tls" else 587, security, authentication,
        "sender@example.com", "synthetic-user", "synthetic-password",
    )

    transport.send("recipient@example.com", "Test", "Synthetic message")

    assert [call[0] for call in smtp.method_calls] == [*steps, "send_message", "close"]
    if security == "tls":
        assert implicit.call_args.args == ("smtp.example.com", 465)
        assert implicit.call_args.kwargs["context"].check_hostname
        normal.assert_not_called()
    else:
        normal.assert_called_once()
        implicit.assert_not_called()
    if mechanism:
        assert smtp.auth.call_args.args[0] == mechanism


def test_encrypted_password_cannot_fall_back_to_normal_password(monkeypatch):
    smtp = Mock(esmtp_features={"auth": "PLAIN LOGIN"})
    monkeypatch.setattr(platform_mail, "SMTP_SSL", Mock(return_value=smtp))
    transport = platform_mail.PlatformSmtp(
        "smtp.example.com", 465, "tls", "cram-md5", "sender@example.com", "user", "password",
    )
    with pytest.raises(SMTPNotSupportedError):
        transport.send("recipient@example.com", "Test", "Synthetic message")
    smtp.auth.assert_not_called()
    smtp.send_message.assert_not_called()


def test_ntlm_completes_the_exchange_against_a_real_ntlm_acceptor(monkeypatch):
    with os.fdopen(os.memfd_create("synthetic-smtp-ntlm"), "wb") as passwords:
        passwords.write(b"SYNTHETIC:mail-user:sample-ntlm-credential\n")
        passwords.flush()
        monkeypatch.setenv("NTLM_USER_FILE", f"/proc/self/fd/{passwords.fileno()}")
        acceptor = spnego.server(protocol="ntlm")
        smtp = Mock()

        def reply(command, args=""):
            if command == "AUTH":
                mechanism, token = args.split()
                assert mechanism == "NTLM"
                return 334, b64encode(acceptor.step(b64decode(token)))
            acceptor.step(b64decode(command))
            return 235, b"Authenticated"

        smtp.docmd.side_effect = reply
        smtp_sasl.authenticate_integrated(
            smtp, "ntlm", "smtp.example.com", "SYNTHETIC\\mail-user", "sample-ntlm-credential",
        )
        assert acceptor.complete
        assert smtp.docmd.call_count == 2


def test_gssapi_negotiates_the_sasl_layer_using_the_backend_ticket(monkeypatch):
    context = Mock(complete=False)
    client = Mock(return_value=context)
    monkeypatch.setattr(smtp_sasl.spnego, "client", client)
    smtp = Mock()
    smtp.docmd.side_effect = [
        (334, b64encode(b"mutual-token")),
        (334, b64encode(b"wrapped-layer")),
        (235, b"Authenticated"),
    ]

    def step(token=None):
        if token is None:
            return b"initial-token"
        assert token == b"mutual-token"
        context.complete = True
        return None

    context.step.side_effect = step
    context.unwrap.return_value.data = b"\x01\x00\x00\x00"
    context.wrap.return_value.data = b"layer-response"

    smtp_sasl.authenticate_integrated(smtp, "gssapi", "smtp.example.com", "ignored", "ignored")

    assert client.call_args.args == ()
    assert client.call_args.kwargs["protocol"] == "kerberos"
    assert client.call_args.kwargs["service"] == "smtp"
    context.unwrap.assert_called_once_with(b"wrapped-layer")
    context.wrap.assert_called_once_with(b"\x01\x00\x00\x00", encrypt=False)
    assert smtp.docmd.call_args.args == (b64encode(b"layer-response").decode("ascii"),)
