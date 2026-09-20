"""
Authentication service.

Usage:
    >>> from core.user import auth_service
    >>> user = await authenticate_from_login("user@example.com", "password123")
    >>> # The user is now in context.
    >>> deauthenticate()
    >>> # The user is logged out.
    >>> user = await authenticate_from_jwt_token("eyJhbGciOiJIUzI1NiIs...")
    >>> # The user is authenticated from the token.
    >>> token = await generate_jwt_token(user.id)
    >>> # Generate a JWT for the user.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from loguru import logger
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.secrets import auth_secret_key
from core.database import get_db
from core.i18n import tr
from core.user import user_service
from starlette.concurrency import run_in_threadpool
from . import mfa_service
from .models import User


class AuthenticationError(Exception):
    """Base authentication error."""

    pass


class InvalidCredentialsError(AuthenticationError):
    """Raised when credentials are invalid."""

    pass


class InvalidTokenError(AuthenticationError):
    """Raised when a token is invalid or expired."""

    pass


class UserInactiveError(AuthenticationError):
    """Raised when a user is inactive."""

    pass


class LoginLockedError(AuthenticationError):
    """Raised while progressive account lockout is active."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MfaRequiredError(AuthenticationError):
    """Raised after valid primary credentials when an MFA code is required."""


class InvalidMfaCodeError(AuthenticationError):
    """Raised when the submitted MFA or recovery code is invalid."""


_DUMMY_PASSWORD_HASH = user_service.encrypt_password(
    "galaris-dummy-password-never-used"
)


def _lockout_seconds(failed_attempts: int) -> int:
    exponent = max(
        0,
        min(failed_attempts - settings.AUTH_LOGIN_LOCKOUT_THRESHOLD, 20),
    )
    return min(
        settings.AUTH_LOGIN_LOCKOUT_BASE_SECONDS * (2**exponent),
        settings.AUTH_LOGIN_LOCKOUT_MAX_SECONDS,
    )


async def _record_failed_login(user: User) -> int:
    user.failed_login_attempts += 1
    lockout_seconds = 0
    if user.failed_login_attempts >= settings.AUTH_LOGIN_LOCKOUT_THRESHOLD:
        lockout_seconds = _lockout_seconds(user.failed_login_attempts)
        user.locked_until = datetime.now(timezone.utc) + timedelta(
            seconds=lockout_seconds
        )
    await get_db().commit()
    return lockout_seconds


async def authenticate_from_login(
    email: str,
    password: str,
    otp_code: str | None = None,
) -> User:
    """
    Authenticate a user from email and password.

    Find the user by email, verify the password and active state, then set the
    current user context.

    Args:
        email: User email.
        password: Plaintext password.

    Returns:
        The authenticated User.

    Raises:
        InvalidCredentialsError: When email or password is incorrect.
        UserInactiveError: When the user is disabled.
    """
    db = get_db()
    user = (
        await db.execute(
            select(User).where(User.email == email).with_for_update()
        )
    ).scalar_one_or_none()

    if user is None:
        # Keep the unknown-account path close to a real bcrypt verification so
        # response timing does not become a practical account-enumeration oracle.
        await run_in_threadpool(user_service.verify_password, password, _DUMMY_PASSWORD_HASH)
        logger.warning("Login attempt for an unknown account")
        raise InvalidCredentialsError(await tr("user_api.errors.incorrect_credentials"))

    now = datetime.now(timezone.utc)
    password_valid = await run_in_threadpool(user_service.verify_password, password, user.hashed_password)
    if user.locked_until is not None and user.locked_until > now:
        retry_after = max(1, int((user.locked_until - now).total_seconds()))
        logger.warning(
            "Rejected login for locked user_id={} retry_after={}",
            user.id,
            retry_after,
        )
        raise LoginLockedError(
            await tr("user_api.errors.account_locked"),
            retry_after,
        )

    if not password_valid:
        lockout_seconds = await _record_failed_login(user)
        logger.warning(
            "Invalid password for user_id={} failed_attempts={} lockout_seconds={}",
            user.id,
            user.failed_login_attempts,
            lockout_seconds,
        )
        raise InvalidCredentialsError(await tr("user_api.errors.incorrect_credentials"))

    # Verify the active state.
    if not user.is_active:
        logger.warning("Login attempt for disabled user_id={}", user.id)
        raise UserInactiveError(await tr("user_api.errors.account_disabled"))

    if user.totp_enabled:
        if not otp_code:
            raise MfaRequiredError(await tr("user_api.errors.mfa_required"))
        if not mfa_service.verify_user_code(user, otp_code):
            lockout_seconds = await _record_failed_login(user)
            logger.warning(
                "Invalid MFA code for user_id={} failed_attempts={} lockout_seconds={}",
                user.id,
                user.failed_login_attempts,
                lockout_seconds,
            )
            raise InvalidMfaCodeError(await tr("user_api.errors.invalid_mfa_code"))

    user.failed_login_attempts = 0
    user.locked_until = None
    await db.commit()

    # Set the current user context.
    user_service.set_current_user(user)

    logger.info("Authenticated user_id={}", user.id)

    return user


def deauthenticate() -> None:
    """
    Remove the current user from the authentication context.

    This clears both the current user and its per-context cache.
    """
    user_service.set_current_user(None)
    logger.debug("Cleared user authentication context")


async def _authenticate_from_user_token(token: str, *, set_context: bool = True) -> Optional[User]:
    """
    Authenticate a user from a database-backed UserToken.

    Returns:
        The User when the token is valid and enabled, otherwise None.
    """
    try:
        from .token_service import get_token_by_value
        user_token = await get_token_by_value(token)
        if user_token and user_token.enabled:
            user = await user_service.get_user_by_id(user_token.user_id)
            if user and user.is_active:
                if set_context:
                    user_service.set_current_user(user)
                logger.info("Authenticated user_id={} from UserToken", user.id)
                return user
    except Exception:
        logger.exception("Database-backed user token authentication failed")
    return None


async def authenticate_from_jwt_token(token: str, *, set_context: bool = True) -> User:
    """
    Authenticate a user from a JWT.

    Decode and validate the JWT, extract the email, find the user, verify the
    account state, and set the current context.

    If the token is not a valid JWT, try it as a UserToken.

    Args:
        token: JWT or UserToken to validate.

    Returns:
        The authenticated User.

    Raises:
        InvalidTokenError: When the token is invalid, expired, or malformed.
        InvalidCredentialsError: When the user no longer exists.
        UserInactiveError: When the user is disabled.
    """
    # Decode and validate the token.
    try:
        payload: dict[str, Any] = jwt.decode( # type: ignore
            token,
            auth_secret_key(),
            algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        # Not a valid JWT; try matching it as a user token.
        user = await _authenticate_from_user_token(token, set_context=set_context)
        if user is not None:
            return user
        logger.warning("Authentication attempt with invalid JWT and UserToken")
        raise InvalidTokenError(await tr("user_api.errors.invalid_or_expired_token"))

    # Extract the email from the payload.
    email: Optional[str] = payload.get("sub")
    if email is None:
        logger.warning("Authentication attempt with token missing 'sub'")
        raise InvalidTokenError(await tr("user_api.errors.malformed_token"))

    # Find the user by email.
    user: Optional[User] = await user_service.get_user_by_email(email)

    if user is None:
        logger.warning("Token authentication attempt for an unknown account")
        raise InvalidCredentialsError(await tr("user_api.errors.user_not_found"))

    # Verify the active state.
    if not user.is_active:
        logger.warning("Token authentication attempt for disabled user_id={}", user.id)
        raise UserInactiveError(await tr("user_api.errors.account_disabled"))

    await validate_access_claims(payload, user)

    # Set the current user context.
    if set_context:
        user_service.set_current_user(user)

    logger.info("Authenticated user_id={} from JWT", user.id)

    return user


async def validate_access_claims(payload: dict[str, Any], user: User) -> None:
    """Shared HTTP/socket revocation checks, including legacy version-zero JWTs."""
    from .refresh_session_service import is_family_active

    family = payload.get("session_family")
    if (
        payload.get("auth_version", 0) != user.auth_version
        or (payload.get("user_id") is not None and payload["user_id"] != user.id)
        or payload.get("sub") != user.email
        or (family is not None and (
            not isinstance(family, str) or not await is_family_active(user.id, family)
        ))
    ):
        raise InvalidTokenError(await tr("user_api.errors.invalid_or_expired_token"))


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT from the supplied data.

    Args:
        data: Claims to encode.
        expires_delta: Optional validity duration, defaulting to 15 minutes.

    Returns:
        The encoded JWT.
    """
    to_encode: dict[str, Any] = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt: str = jwt.encode( # type: ignore
        to_encode,
        auth_secret_key(),
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


async def create_access_token_for_user(
    user: User,
    db: Optional[AsyncSession] = None,
    role_id: Optional[int] = None,
    *,
    session_family: str | None = None,
) -> str:
    """
    Create a frontend JWT for a user, including the active role when available.

    If role_id is provided, preserve that context. Otherwise use the
    Choose the default role, then the first available role, as during login.
    """
    token_payload: dict[str, Any] = {
        "sub": user.email,
        "user_id": user.id,
        "display_name": user.display_name,
        "auth_version": user.auth_version,
    }
    family = session_family or user_service.session_family_ctx.get()
    if family is not None:
        token_payload["session_family"] = family

    if db is not None:
        try:
            from core.authorize import Assignment, Role

            stmt = (
                select(Assignment, Role)
                .join(Role)
                .where(Assignment.user_id == user.id)
            )
            if role_id is not None:
                stmt = stmt.where(Assignment.role_id == role_id)
            else:
                stmt = stmt.where(Assignment.is_default.is_(True))

            result = await db.execute(stmt)
            assignment_row = result.first()

            if role_id is None and not assignment_row:
                result_first = await db.execute(
                    select(Assignment, Role)
                    .join(Role)
                    .where(Assignment.user_id == user.id)
                    .limit(1)
                )
                assignment_row = result_first.first()

            if assignment_row:
                assignment, role = assignment_row
                token_payload.update(
                    {
                        "role_id": role.id,
                        "role_code": role.code,
                        "role_name": role.display_name,
                        "assignment_id": assignment.id,
                    }
                )
        except ImportError:
            logger.debug("Authorization module unavailable while creating access token")
        except Exception as e:
            logger.error(f"Error fetching role while creating access token: {e}")

    access_token_expires = timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES)
    return create_access_token(
        data=token_payload,
        expires_delta=access_token_expires,
    )


async def generate_jwt_token(
    user_id: int,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None
) -> str:
    """
    Generate a JWT for a user.

    Load the user by ID, build the standard claims, add optional claims, then
    generate and return the token.

    Args:
        user_id: User ID.
        expires_delta: Optional validity duration, defaulting to 15 minutes.
        extra_claims: Additional token claims.

    Returns:
        The generated JWT.

    Raises:
        InvalidCredentialsError: When the user does not exist.
        UserInactiveError: When the user is disabled.
    """
    # Load the user.
    user: Optional[User] = await user_service.get_user_by_id(user_id)

    if user is None:
        raise InvalidCredentialsError(await tr("user_api.errors.user_not_found"))

    if not user.is_active:
        raise UserInactiveError(await tr("user_api.errors.account_disabled"))

    # Build the base payload.
    token_payload: dict[str, Any] = {
        "sub": user.email,
        "user_id": user.id,
        "display_name": user.display_name,
    }

    # Add extra claims.
    if extra_claims:
        token_payload.update(extra_claims)
    token_payload["auth_version"] = user.auth_version

    # Generate the token.
    token = create_access_token(token_payload, expires_delta)

    logger.debug("Generated token for user {} (id={})", user.email, user.id)

    return token
