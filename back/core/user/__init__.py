# User module - Authentication and user management

from .models import User as UserModel, UserRefreshSession, UserToken
from .user_service import encrypt_password, get_current_user, get_current_user_id, verify_password
from .auth_service import create_access_token, generate_jwt_token
from .oauth import oauth2_scheme
from .dependencies import require_web_session
from .lifecycle import (
    notify_user_access_changed,
    register_user_access_observer,
    unregister_user_access_observer,
)
from .schemas import UserCreate, UserUpdate, User, Token
from .authContextMiddleware import AuthContextMiddleware
from .token_service import (
    list_tokens_for_user,
    get_token_by_id,
    get_token_by_value,
    get_current_token_label,
    create_token_for_user,
    update_token,
    delete_token,
)


async def get_user_record(user_id: int) -> UserModel | None:
    """Return one User through the public core.user surface."""

    from .user_service import get_user_by_id

    return await get_user_by_id(user_id)


async def list_user_records(
    *,
    skip: int = 0,
    limit: int = 500,
    search: str | None = None,
    active_only: bool = False,
) -> tuple[UserModel, ...]:
    """List Users through the public core.user surface."""

    from .user_service import get_users

    return tuple(await get_users(skip=skip, limit=limit, search=search, active_only=active_only))

__all__ = [
    "notify_user_access_changed",
    "register_user_access_observer",
    "unregister_user_access_observer",
    "User",
    "UserModel",
    "UserToken",
    "UserRefreshSession",
    "encrypt_password",
    "get_current_user_id",
    "get_current_user",
    "verify_password",
    "create_access_token",
    "generate_jwt_token",
    "oauth2_scheme",
    "require_web_session",
    "UserCreate",
    "UserUpdate",
    "Token",
    "AuthContextMiddleware",
    "list_tokens_for_user",
    "get_token_by_id",
    "get_token_by_value",
    "get_current_token_label",
    "create_token_for_user",
    "update_token",
    "delete_token",
    "get_user_record",
    "list_user_records",
]
from .actor import HumanActor as HumanActor
