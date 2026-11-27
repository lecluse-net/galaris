"""SMTP transport for platform account messages."""

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from smtplib import SMTP, SMTPAuthenticationError, SMTPNotSupportedError, SMTP_SSL
from ssl import create_default_context

from loguru import logger
from starlette.concurrency import run_in_threadpool

from core.i18n import tr
from core.params import PlatformSmtpAuthentication, PlatformSmtpSecurity, runtime_settings

from .smtp_sasl import authenticate_integrated


class PlatformSmtpNotConfiguredError(Exception):
    """The platform SMTP settings are incomplete."""


class PlatformSmtpDeliveryError(Exception):
    """The relay did not confirm submission of the test message."""


@dataclass(frozen=True)
class PlatformSmtp:
    host: str
    port: int
    security: PlatformSmtpSecurity
    authentication: PlatformSmtpAuthentication
    sender: str
    username: str
    password: str = field(repr=False)

    @classmethod
    def configured(cls) -> "PlatformSmtp | None":
        host = runtime_settings.PLATFORM_SMTP_HOST.strip()
        sender = runtime_settings.PLATFORM_SMTP_FROM
        username = runtime_settings.PLATFORM_SMTP_USERNAME.strip()
        password = runtime_settings.PLATFORM_SMTP_PASSWORD
        authentication = runtime_settings.PLATFORM_SMTP_AUTHENTICATION
        if authentication == "auto":
            if bool(username) != bool(password):
                return None
            if not username:
                authentication = "none"
        if authentication in {"password", "cram-md5", "ntlm"} and not (username and password):
            return None
        if not host or not sender:
            return None
        return cls(
            host, runtime_settings.PLATFORM_SMTP_PORT, runtime_settings.PLATFORM_SMTP_SECURITY,
            authentication, sender, username, password,
        )

    def send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Date"] = formatdate(usegmt=True)
        message["Message-ID"] = make_msgid(domain=self.sender.rsplit("@", 1)[-1])
        message.set_content(body)
        timeout = 8
        smtp = (
            SMTP_SSL(self.host, self.port, timeout=timeout, context=create_default_context())
            if self.security == "tls" else SMTP(self.host, self.port, timeout=timeout)
        )
        try:
            if self.security == "starttls":
                smtp.starttls(context=create_default_context())
            self._authenticate(smtp)
            smtp.send_message(message)
        finally:
            smtp.close()

    def _authenticate(self, smtp: SMTP) -> None:
        if self.authentication == "none":
            return
        if self.authentication == "auto":
            smtp.login(self.username, self.password)
            return

        smtp.ehlo_or_helo_if_needed()
        advertised = smtp.esmtp_features.get("auth", "").upper().split()
        if self.authentication in ("ntlm", "gssapi"):
            if self.authentication.upper() not in advertised:
                raise SMTPNotSupportedError("The relay does not offer the selected authentication method")
            authenticate_integrated(smtp, self.authentication, self.host, self.username, self.password)
            return

        smtp.user = self.username
        smtp.password = self.password
        mechanisms = (
            (("CRAM-MD5", smtp.auth_cram_md5),)
            if self.authentication == "cram-md5" else (("PLAIN", smtp.auth_plain), ("LOGIN", smtp.auth_login))
        )
        rejected: SMTPAuthenticationError | None = None
        for mechanism, respond in mechanisms:
            if mechanism in advertised:
                try:
                    smtp.auth(mechanism, respond)
                    return
                except SMTPAuthenticationError as exc:
                    rejected = exc
        if rejected is not None:
            raise rejected
        raise SMTPNotSupportedError("The relay does not offer the selected authentication method")


async def send_platform_smtp_test(recipient: str) -> None:
    smtp = PlatformSmtp.configured()
    if smtp is None:
        raise PlatformSmtpNotConfiguredError
    subject = await tr("user_api.smtp_test.subject")
    body = await tr("user_api.smtp_test.body")
    try:
        await run_in_threadpool(smtp.send, recipient, subject, body)
    except (OSError, ValueError) as exc:
        logger.warning("Platform SMTP test failed ({})", type(exc).__name__)
        raise PlatformSmtpDeliveryError from None
