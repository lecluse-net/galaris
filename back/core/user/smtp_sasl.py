"""Binary SMTP SASL exchanges for NTLM and Kerberos."""

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from smtplib import SMTP, SMTPAuthenticationError
from typing import Literal

import spnego
from spnego.exceptions import SpnegoError


def authenticate_integrated(
    smtp: SMTP, method: Literal["ntlm", "gssapi"], host: str, username: str, password: str,
) -> None:
    try:
        context = (
            spnego.client(username, password, hostname=host, service="smtp", protocol="ntlm")
            if method == "ntlm"
            else spnego.client(
                hostname=host, service="smtp", protocol="kerberos",
                context_req=spnego.ContextReq.mutual_auth | spnego.ContextReq.integrity,
            )
        )
        initial = context.step()
        if not initial:
            raise SMTPAuthenticationError(535, b"Missing initial SASL token")
        code, response = smtp.docmd("AUTH", f"{method.upper()} {b64encode(initial).decode('ascii')}")
        negotiated_layer = False
        for _ in range(8):
            if code != 334 or negotiated_layer:
                break
            challenge = b64decode(response, validate=True)
            if method == "gssapi" and context.complete:
                layer = context.unwrap(challenge).data
                if len(layer) != 4 or not layer[0] & 1:
                    raise SMTPAuthenticationError(535, b"Unsupported Kerberos SASL security layer")
                # SMTP transport security is selected separately. RFC 4752's
                # no-layer response uses the default authorization identity.
                token = context.wrap(b"\x01\x00\x00\x00", encrypt=False).data
                negotiated_layer = True
            else:
                token = context.step(challenge)
            code, response = smtp.docmd(b64encode(token or b"").decode("ascii"))
        if code != 235 or not context.complete or (method == "gssapi" and not negotiated_layer):
            raise SMTPAuthenticationError(code, b"SMTP SASL authentication rejected")
    except (ImportError, SpnegoError, Base64Error):
        raise SMTPAuthenticationError(535, b"SMTP SASL negotiation failed") from None
