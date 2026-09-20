"""Synchronous SMTP Submission adapter executed in a worker thread."""

from __future__ import annotations

import smtplib
import ssl
from contextlib import contextmanager
from collections.abc import Generator

from .contracts import MailConnectionConfig


class SmtpClient:
    def __init__(self, config: MailConnectionConfig) -> None:
        self.config = config

    @contextmanager
    def _session(self) -> Generator[smtplib.SMTP, None, None]:
        endpoint = self.config.smtp
        context = ssl.create_default_context()
        if endpoint.security == "tls":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                endpoint.host,
                endpoint.port,
                timeout=self.config.connect_timeout_s,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                endpoint.host,
                endpoint.port,
                timeout=self.config.connect_timeout_s,
            )
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        try:
            if client.sock is not None:
                client.sock.settimeout(self.config.operation_timeout_s)
            client.login(endpoint.username, endpoint.password.get_secret_value())
            yield client
        finally:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                client.close()

    def status(self) -> None:
        with self._session() as client:
            code, _message = client.noop()
            if code < 200 or code >= 400:
                raise RuntimeError("SMTP NOOP failed")

    def send(
        self,
        message: bytes,
        *,
        sender: str,
        recipients: tuple[str, ...],
    ) -> tuple[int, int]:
        with self._session() as client:
            refused = client.sendmail(sender, list(recipients), message)
        rejected = len(refused)
        return len(recipients) - rejected, rejected


__all__ = ["SmtpClient"]
