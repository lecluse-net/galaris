"""TOTP multi-factor authentication and one-time recovery codes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from core import settings
from core.secrets import auth_secret_key
from core.database import get_db
from core.util.encryption import decrypt_value, encrypt_value

from .models import User

_TOTP_PERIOD_SECONDS = 30
_TOTP_DIGITS = 6
_RECOVERY_CODE_COUNT = 10


class MfaNotConfiguredError(ValueError):
    """Raised when an MFA operation requires an existing setup."""


class MfaAlreadyEnabledError(ValueError):
    """Raised when setup is requested for an MFA-protected account."""


class InvalidMfaCodeError(ValueError):
    """Raised when a TOTP or recovery code is invalid or already used."""


def _normalize_recovery_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def _recovery_hash(code: str) -> str:
    normalized = _normalize_recovery_code(code)
    return hmac.new(
        auth_secret_key().encode(),
        normalized.encode(),
        hashlib.sha256,
    ).hexdigest()


def _totp(secret: str, counter: int) -> str:
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(f"{secret}{padding}", casefold=True)
    digest = hmac.new(
        key,
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** _TOTP_DIGITS)).zfill(_TOTP_DIGITS)


def verify_totp(
    secret: str,
    code: str,
    *,
    last_counter: int | None = None,
    at_time: int | None = None,
) -> int | None:
    """Return the accepted counter, rejecting stale and replayed TOTP values."""

    normalized = code.strip().replace(" ", "")
    if len(normalized) != _TOTP_DIGITS or not normalized.isdigit():
        return None
    counter = (at_time if at_time is not None else int(time.time())) // _TOTP_PERIOD_SECONDS
    for candidate in range(counter - 1, counter + 2):
        if last_counter is not None and candidate <= last_counter:
            continue
        if hmac.compare_digest(_totp(secret, candidate), normalized):
            return candidate
    return None


async def _locked_user(user_id: int) -> User:
    user = (
        await get_db().execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise LookupError("User not found")
    return user


async def status(user_id: int) -> tuple[bool, bool, int]:
    user = (
        await get_db().execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise LookupError("User not found")
    return (
        user.totp_enabled,
        bool(user.totp_secret_encrypted and not user.totp_enabled),
        len(user.recovery_code_hashes),
    )


async def begin_setup(user_id: int) -> tuple[str, str]:
    user = await _locked_user(user_id)
    if user.totp_enabled:
        raise MfaAlreadyEnabledError("MFA is already enabled")
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    user.totp_secret_encrypted = encrypt_value(secret)
    user.totp_enabled = False
    user.totp_last_counter = None
    user.recovery_code_hashes = []
    await get_db().commit()
    label = quote(user.email, safe="")
    issuer = quote(settings.APP_NAME, safe="")
    uri = (
        f"otpauth://totp/{issuer}:{label}?secret={secret}"
        f"&issuer={issuer}&algorithm=SHA1&digits={_TOTP_DIGITS}"
        f"&period={_TOTP_PERIOD_SECONDS}"
    )
    return secret, uri


def _new_recovery_codes() -> list[str]:
    codes: list[str] = []
    for _ in range(_RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(8).upper()
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}")
    return codes


async def confirm_setup(user_id: int, code: str) -> list[str]:
    user = await _locked_user(user_id)
    if not user.totp_secret_encrypted:
        raise MfaNotConfiguredError("MFA setup has not been started")
    secret = decrypt_value(user.totp_secret_encrypted)
    counter = verify_totp(secret, code, last_counter=user.totp_last_counter)
    if counter is None:
        raise InvalidMfaCodeError("Invalid or already used authentication code")
    recovery_codes = _new_recovery_codes()
    user.totp_enabled = True
    user.totp_last_counter = counter
    user.recovery_code_hashes = [_recovery_hash(item) for item in recovery_codes]
    await _commit_mfa_change(user_id)
    return recovery_codes


def verify_user_code(user: User, code: str) -> bool:
    """Verify and consume a TOTP or recovery code on a locked User row."""

    if not user.totp_enabled or not user.totp_secret_encrypted:
        return False
    secret = decrypt_value(user.totp_secret_encrypted)
    counter = verify_totp(secret, code, last_counter=user.totp_last_counter)
    if counter is not None:
        user.totp_last_counter = counter
        return True

    candidate_hash = _recovery_hash(code)
    for index, stored_hash in enumerate(user.recovery_code_hashes):
        if hmac.compare_digest(stored_hash, candidate_hash):
            user.recovery_code_hashes = [
                *user.recovery_code_hashes[:index],
                *user.recovery_code_hashes[index + 1 :],
            ]
            return True
    return False


async def disable(user_id: int, password: str, code: str) -> None:
    from .user_service import verify_password

    user = await _locked_user(user_id)
    if not await run_in_threadpool(verify_password, password, user.hashed_password):
        raise InvalidMfaCodeError("Invalid password or authentication code")
    if not verify_user_code(user, code):
        raise InvalidMfaCodeError("Invalid password or authentication code")
    user.totp_secret_encrypted = None
    user.totp_enabled = False
    user.totp_last_counter = None
    user.recovery_code_hashes = []
    await _commit_mfa_change(user_id)


async def regenerate_recovery_codes(user_id: int, code: str) -> list[str]:
    user = await _locked_user(user_id)
    if not verify_user_code(user, code):
        raise InvalidMfaCodeError("Invalid or already used authentication code")
    recovery_codes = _new_recovery_codes()
    user.recovery_code_hashes = [_recovery_hash(item) for item in recovery_codes]
    await _commit_mfa_change(user_id)
    return recovery_codes


async def _commit_mfa_change(user_id: int) -> None:
    """Revoke other browsers atomically, preserving the authenticated setup flow."""
    from .refresh_session_service import revoke_all_user_sessions
    from .user_service import session_family_ctx

    await get_db().flush()
    await revoke_all_user_sessions(user_id, preserve_family=session_family_ctx.get())


__all__ = [
    "InvalidMfaCodeError",
    "MfaAlreadyEnabledError",
    "MfaNotConfiguredError",
    "begin_setup",
    "confirm_setup",
    "disable",
    "regenerate_recovery_codes",
    "status",
    "verify_totp",
    "verify_user_code",
]
