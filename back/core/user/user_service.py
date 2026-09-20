"""
User management service.

Usage:
    >>> from core.user import user_service
    >>> users = await user_service.get_users()
    >>> user = await user_service.get_user_by_id(1)
    >>> current_user = await user_service.get_current_user()
"""

from contextvars import ContextVar
from sqlalchemy import select, func, delete as sqlalchemy_delete, text
from sqlalchemy.exc import IntegrityError
from typing import List, Literal, Optional
from uuid import UUID, uuid4
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher
from starlette.concurrency import run_in_threadpool
from loguru import logger

from core.database import get_db
from core.i18n import render_prompt, tr
from core.params import runtime_settings
from .models import User
from .schemas import UserCreate, UserRegistration, UserUpdate


class RegistrationClosedError(Exception):
    """Raised when public registration is disabled and an account already exists."""


class UserConflictError(ValueError):
    """An account cannot be removed while other resources still reference it."""


class InvalidAvatarTypeError(ValueError):
    """Raised when an avatar's declared media type is unsupported."""


class AvatarTooLargeError(ValueError):
    """Raised when an avatar exceeds the bounded upload size."""


class InvalidAvatarContentError(ValueError):
    """Raised when avatar bytes do not match their declared image media type."""


_INITIAL_REGISTRATION_LOCK_ID = 20_042_655_670_611
AVATAR_MAX_BYTES = 5_000_000
AVATAR_MEDIA_TYPES = frozenset(
    {"image/gif", "image/jpeg", "image/png", "image/webp"}
)

# Password hashing context.
_pwd_context = PasswordHash([BcryptHasher()])

# Context variable holding the current user ID.
_user_id_ctx: ContextVar[Optional[int]] = ContextVar("user_id_ctx", default=None)

# Per-context cache avoids repeated database calls.
_cached_user: ContextVar[Optional[User]] = ContextVar("cached_user", default=None)

# Context variable holding a raw non-JWT user token.
_raw_token_ctx: ContextVar[Optional[str]] = ContextVar("raw_token_ctx", default=None)
session_family_ctx: ContextVar[str | None] = ContextVar("session_family", default=None)


def encrypt_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return _pwd_context.verify(plain_password, hashed_password)


async def get_current_user() -> Optional[User]:
    """
    Return the current user from a per-context cache.

    The cache avoids repeated database calls from SQLAlchemy hooks and multiple
    authorization checks within the same request.

    Returns:
        The context User, or None.
    """

    user_id = get_current_user_id()
    if user_id is None:
        return None

    # Check the cache first.
    cached = _cached_user.get()
    if cached is not None:
        return cached

    user = await get_user_by_id(user_id)
    if user is not None:
        # Cache for later calls in the same context.
        _cached_user.set(user)

    return user


def clear_cache() -> None:
    """
    Clear the current-user cache.

    Use this after changing users or to force a reload.
    """
    _cached_user.set(None)


def get_current_user_id() -> Optional[int]:
    """
    Return the current user ID from context.

    This performs no database query.

    Returns:
        The context user ID, or None.
    """
    return _user_id_ctx.get()


def get_current_raw_token() -> Optional[str]:
    """
    Return the current raw token from context.

    Returns:
        The token value, or None.
    """
    return _raw_token_ctx.get()


def set_current_raw_token(token_value: Optional[str]) -> None:
    """
    Set the current raw token in context.

    Args:
        token_value: Token value, or None to clear it.
    """
    _raw_token_ctx.set(token_value)


def has_current_user() -> bool:
    return get_current_user_id() is not None


def set_current_user(user: Optional[User]) -> None:
    """
    Set the current user in context.

    Args:
        user: User to set, or None to clear the context.
    """
    user_id = user.id if user is not None else None
    _user_id_ctx.set(user_id)

    clear_cache()


async def get_users(
    skip: int = 0, limit: int = 50, search: Optional[str] = None,
    *, sort_by: Literal["id", "email", "display_name", "is_active", "created_at"] = "id",
    descending: bool = False,
) -> List[User]:
    """Return all users with optional search filtering."""
    db = get_db()
    query = select(User)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            (User.email.ilike(search_term)) | (User.display_name.ilike(search_term))
        )

    column = getattr(User, sort_by)
    query = query.order_by(column.desc() if descending else column.asc(), User.id).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_users(search: str | None = None) -> int:
    query = select(func.count(User.id))
    if search:
        query = query.where(User.email.ilike(f"%{search}%") | User.display_name.ilike(f"%{search}%"))
    return int(await get_db().scalar(query) or 0)


async def get_user_by_id(user_id: int) -> Optional[User]:
    """Get a user by ID."""
    db = get_db()
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(email: str) -> Optional[User]:
    """Get a user by email."""
    db = get_db()
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def is_registration_open() -> bool:
    """Allow bootstrap or explicitly enabled signup, counting inactive accounts too."""
    return runtime_settings.ALLOW_USER_REGISTRATION or await get_db().scalar(select(User.id).limit(1)) is None


async def is_initial_admin_required() -> bool:
    """No existing account, including inactive accounts, may be treated as a fresh install."""
    return await get_db().scalar(select(User.id).limit(1)) is None


async def register_public_user(user_data: UserRegistration) -> User:
    """Serialize public signup and grant administration only to the first account."""
    db = get_db()

    # Serialize bootstrap attempts across processes. The transaction-scoped
    # PostgreSQL lock is released automatically on commit or rollback.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _INITIAL_REGISTRATION_LOCK_ID},
    )
    user_count = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar_one()
    if user_count != 0:
        if not runtime_settings.ALLOW_USER_REGISTRATION:
            raise RegistrationClosedError
        return await create(UserCreate(**user_data.model_dump(), is_active=True))

    # The administrative role is reference data and must exist before the
    # public bootstrap can succeed; never create an unprivileged first account.
    from core.authorize.models import Assignment, Role
    from core.authorize.update_admin_role import ADMIN_ROLE_CODE

    admin_role = (
        await db.execute(select(Role).where(Role.code == ADMIN_ROLE_CODE))
    ).scalar_one_or_none()
    if admin_role is None:
        raise RuntimeError("The admin role is unavailable during initial registration")

    new_user = User(
        email=user_data.email,
        hashed_password=await run_in_threadpool(encrypt_password, user_data.password),
        display_name=user_data.display_name,
        language=user_data.language,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()
    db.add(
        Assignment(
            user_id=new_user.id,
            role_id=admin_role.id,
            is_default=True,
        )
    )
    await db.commit()
    await db.refresh(new_user)
    logger.info(
        "Created initial administrator user_id={} role={}",
        new_user.id,
        ADMIN_ROLE_CODE,
    )
    from .lifecycle import notify_user_access_changed
    await notify_user_access_changed(new_user.id)
    return new_user


async def create(user_data: UserCreate) -> User:
    """Create a user through the authenticated administration API."""
    db = get_db()

    # Reject duplicate email addresses.
    existing = await get_user_by_email(user_data.email)
    if existing:
        raise ValueError(
            render_prompt(
                await tr("user_api.errors.email_registered"),
                email=user_data.email,
            )
        )

    hashed_password = await run_in_threadpool(encrypt_password, user_data.password)
    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        display_name=user_data.display_name,
        is_active=user_data.is_active,
        language=user_data.language,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    from .lifecycle import notify_user_access_changed
    await notify_user_access_changed(new_user.id)
    return new_user


async def update(user_id: int, user_update: UserUpdate) -> Optional[User]:
    """Update an existing user."""
    db = get_db()
    if user_update.is_active is False:
        from core.authorize import preserve_administrator

        await preserve_administrator(user_id=user_id)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None

    if user_update.email and user_update.email != user.email:
        existing = await get_user_by_email(user_update.email)
        if existing:
            raise ValueError(
                render_prompt(
                    await tr("user_api.errors.email_in_use"),
                    email=user_update.email,
                )
            )
        user.email = user_update.email

    if user_update.display_name is not None:
        user.display_name = user_update.display_name

    revoke_persistent_sessions = bool(user_update.password) or user_update.is_active is False

    if user_update.password:
        user.hashed_password = await run_in_threadpool(encrypt_password, user_update.password)

    if revoke_persistent_sessions:
        user.auth_version += 1

    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    if user_update.language is not None:
        user.language = user_update.language

    if user_update.document_open_mode is not None:
        user.document_open_mode = user_update.document_open_mode

    if revoke_persistent_sessions:
        from .refresh_session_service import revoke_all_user_sessions

        # Flush account changes under the same owner lock as token rotation;
        # revocation commits both together, leaving no usable session window.
        await db.flush()
        await revoke_all_user_sessions(user.id)
    else:
        await db.commit()
    await db.refresh(user)

    clear_cache()

    if user_update.is_active is not None or user_update.language is not None:
        from .lifecycle import notify_user_access_changed
        await notify_user_access_changed(user.id)
    return user


def _detect_avatar_media_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


async def update_avatar(
    user_id: int,
    content: bytes,
    declared_media_type: str | None,
) -> User | None:
    """Validate and replace a user's avatar with a cache-busting URL key."""

    if declared_media_type not in AVATAR_MEDIA_TYPES:
        raise InvalidAvatarTypeError
    if len(content) > AVATAR_MAX_BYTES:
        raise AvatarTooLargeError
    detected_media_type = _detect_avatar_media_type(content)
    if detected_media_type is None or detected_media_type != declared_media_type:
        raise InvalidAvatarContentError

    db = get_db()
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        return None
    user.avatar = content
    user.avatar_mime_type = detected_media_type
    user.avatar_key = uuid4()
    await db.commit()
    await db.refresh(user)
    clear_cache()
    return user


async def get_avatar_by_key(avatar_key: UUID) -> tuple[bytes, str] | None:
    """Return avatar bytes and their verified media type for an opaque URL key."""

    row = (
        await get_db().execute(
            select(User.avatar, User.avatar_mime_type).where(
                User.avatar_key == avatar_key,
                User.avatar.is_not(None),
                User.avatar_mime_type.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    content, media_type = row
    if content is None or media_type is None:
        return None
    return content, media_type


async def delete_avatar(user_id: int) -> User | None:
    """Remove a user's avatar and invalidate its public opaque URL."""

    db = get_db()
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        return None
    user.avatar = None
    user.avatar_mime_type = None
    user.avatar_key = None
    await db.commit()
    await db.refresh(user)
    clear_cache()
    return user


async def delete(user_id: int) -> bool:
    """Delete a user."""
    db = get_db()
    from core.authorize import preserve_administrator

    await preserve_administrator(user_id=user_id)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False

    try:
        await db.execute(sqlalchemy_delete(User).where(User.id == user_id))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        clear_cache()
        if getattr(exc.orig, "sqlstate", None) != "23503":
            raise
        raise UserConflictError(await tr("user_api.errors.account_in_use")) from exc

    clear_cache()

    return True
