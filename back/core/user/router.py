from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, Response, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, List, Literal
from uuid import UUID

from core import settings
from core.secrets import auth_secret_key
from core.database import get_db
from core.i18n import render_prompt, tr
from core.rate_limit import rate_limit
from .schemas import (
    UserCreate,
    UserLogin,
    UserRegistration,
    RegistrationStatus,
    UserUpdate,
    User as UserSchema,
    Token,
    MfaCode,
    MfaDisable,
    MfaRecoveryCodes,
    MfaSetup,
    MfaStatus,
)
from .schemas import UserTokenCreate, UserTokenUpdate, UserTokenResponse, UserTokenCreateResponse
from core.authorize import authorize, independent_auth, public
from core.authorize import AdministratorConflictError, Privileges
from core.authorize.context import role_id_ctx
from . import user_service
from . import help_service
from .models import User as UserModel
from . import refresh_session_service
from . import token_service
from . import mfa_service
from .auth_service import (
    authenticate_from_login,
    InvalidCredentialsError,
    InvalidMfaCodeError,
    LoginLockedError,
    MfaRequiredError,
    UserInactiveError,
    deauthenticate,
    create_access_token_for_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_PATH = "/api/auth"


def _refresh_cookie_secure() -> bool:
    return settings.APP_HOST.lower().startswith("https://")


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=_REFRESH_COOKIE_PATH,
        secure=_refresh_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        secure=_refresh_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def _assert_same_origin(request: Request) -> None:
    """Reject browser refresh/logout requests originating from another host."""

    origin = request.headers.get("origin")
    request_host = request.headers.get("host")
    if origin and request_host and urlsplit(origin).netloc != request_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin session request rejected",
        )


def _requested_role_id(request: Request) -> int | None:
    """Recover a signed role claim even when the previous access token expired."""

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            auth_secret_key(),
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
    except JWTError:
        return None

    role_id = payload.get("role_id")
    return role_id if isinstance(role_id, int) and not isinstance(role_id, bool) else None


@router.get("/registration-status", response_model=RegistrationStatus)
@public(reason="Expose only whether public registration is available")
async def registration_status(response: Response) -> RegistrationStatus:
    response.headers["Cache-Control"] = "no-store"
    return RegistrationStatus(
        registration_open=await user_service.is_registration_open(),
        initial_admin_required=await user_service.is_initial_admin_required(),
    )


@router.post(
    "/register", response_model=UserSchema, status_code=status.HTTP_201_CREATED
)
@public(reason="Initial administrator bootstrap or explicitly enabled public registration")
async def register(user: UserRegistration):
    """Create the first administrator, or an unprivileged account when signup is open."""
    try:
        new_user = await user_service.register_public_user(user)
        # Authenticate immediately after registration.
        await authenticate_from_login(new_user.email, user.password)
        return new_user
    except user_service.RegistrationClosedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=await tr("user_api.errors.registration_closed"),
        ) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _perform_login(
    email: str,
    password: str,
    db: AsyncSession,
    request: Request,
    response: Response,
    otp_code: str | None = None,
) -> Token:
    """Shared login logic for /login and /token."""
    try:
        user = await authenticate_from_login(email, password, otp_code)
    except InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except UserInactiveError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except LoginLockedError as e:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={"code": "account_locked", "message": str(e)},
            headers={"Retry-After": str(e.retry_after)},
        ) from e
    except MfaRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "mfa_required", "message": str(e)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except InvalidMfaCodeError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_mfa_code", "message": str(e)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    previous_refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    if previous_refresh_token:
        await refresh_session_service.revoke_refresh_token(previous_refresh_token)
    refresh_token = await refresh_session_service.create_refresh_session(
        user.id,
        request.headers.get("user-agent"),
    )
    access_token = await create_access_token_for_user(
        user, db, session_family=await refresh_session_service.family_for_token(refresh_token),
    )
    _set_refresh_cookie(response, refresh_token)
    return Token(access_token=access_token, token_type="bearer")


@router.post("/login", response_model=Token)
@rate_limit("10/minute")
@public(reason="Password authentication entry point")
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    otp_code: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """OAuth2 login endpoint used by Swagger UI and the frontend.

    OAuth2PasswordRequestForm names the field ``username`` while Galaris uses email.
    """
    return await _perform_login(
        form_data.username,
        form_data.password,
        db,
        request,
        response,
        otp_code,
    )


@router.post("/login-json", response_model=Token)
@rate_limit("10/minute")
@public(reason="Password authentication entry point for the frontend")
async def login_json(
    user_credentials: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """JSON login endpoint for the frontend."""
    return await _perform_login(
        user_credentials.email,
        user_credentials.password,
        db,
        request,
        response,
        user_credentials.otp_code,
    )


async def _current_user_id() -> int:
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )
    return current_user.id


@router.get("/mfa/status", response_model=MfaStatus)
@authorize(privileges=[])
async def read_mfa_status() -> MfaStatus:
    enabled, setup_pending, recovery_codes_remaining = await mfa_service.status(
        await _current_user_id()
    )
    return MfaStatus(
        enabled=enabled,
        setup_pending=setup_pending,
        recovery_codes_remaining=recovery_codes_remaining,
    )


@router.post("/mfa/setup", response_model=MfaSetup)
@authorize(privileges=[])
async def setup_mfa() -> MfaSetup:
    try:
        secret, provisioning_uri = await mfa_service.begin_setup(
            await _current_user_id()
        )
    except mfa_service.MfaAlreadyEnabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MfaSetup(secret=secret, provisioning_uri=provisioning_uri)


@router.post("/mfa/confirm", response_model=MfaRecoveryCodes)
@authorize(privileges=[])
async def confirm_mfa(data: MfaCode) -> MfaRecoveryCodes:
    try:
        recovery_codes = await mfa_service.confirm_setup(
            await _current_user_id(),
            data.code,
        )
    except (mfa_service.MfaNotConfiguredError, mfa_service.InvalidMfaCodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MfaRecoveryCodes(recovery_codes=recovery_codes)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=[])
async def disable_mfa(data: MfaDisable) -> None:
    try:
        await mfa_service.disable(
            await _current_user_id(),
            data.password,
            data.code,
        )
    except mfa_service.InvalidMfaCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/mfa/recovery-codes", response_model=MfaRecoveryCodes)
@authorize(privileges=[])
async def regenerate_mfa_recovery_codes(data: MfaCode) -> MfaRecoveryCodes:
    try:
        recovery_codes = await mfa_service.regenerate_recovery_codes(
            await _current_user_id(),
            data.code,
        )
    except mfa_service.InvalidMfaCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MfaRecoveryCodes(recovery_codes=recovery_codes)


@router.post("/logout")
@independent_auth(reason="Refresh-cookie revocation with same-origin validation")
async def logout(request: Request, response: Response) -> dict[str, str]:
    """
    Log out the current request context.

    Revoke the persistent browser session and clear its HttpOnly cookie. The
    associated access tokens are rejected by HTTP and WebSocket authorization.
    """
    _assert_same_origin(request)
    refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    if refresh_token:
        await refresh_session_service.revoke_refresh_token(refresh_token)
    _clear_refresh_cookie(response)
    deauthenticate()
    return {"message": await tr("user_api.logged_out")}


@router.post("/refresh", response_model=Token)
@independent_auth(reason="Rotating HttpOnly refresh-cookie authentication")
async def refresh_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """Rotate the persistent browser session and return a fresh access token."""

    _assert_same_origin(request)
    refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    if not refresh_token:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.invalid_or_expired_token"),
        )

    try:
        rotation = await refresh_session_service.rotate_refresh_token(
            refresh_token,
            request.headers.get("user-agent"),
        )
    except refresh_session_service.InvalidRefreshTokenError:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.invalid_or_expired_token"),
        )

    access_token = await create_access_token_for_user(
        rotation.user,
        db,
        role_id=_requested_role_id(request),
        session_family=rotation.family,
    )
    _set_refresh_cookie(response, rotation.token)
    return Token(access_token=access_token, token_type="bearer")


@router.post("/keep-alive", response_model=Token)
@authorize(privileges=[])
async def keep_alive(db: AsyncSession = Depends(get_db)):
    """Refresh the JWT while the current user remains authenticated."""
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )

    access_token = await create_access_token_for_user(
        current_user,
        db,
        role_id=role_id_ctx.get(),
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserSchema)
@authorize(privileges=["user"])
async def read_users_me():
    """Return the current authenticated user."""
    # @authorize guarantees authentication.
    return await user_service.get_current_user()


@router.get("/avatars/{avatar_key}")
@public(reason="Opaque self-hosted user avatar URL used by browser image elements")
async def read_user_avatar(avatar_key: UUID) -> Response:
    avatar = await user_service.get_avatar_by_key(avatar_key)
    if avatar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("user_api.errors.avatar_not_found"),
        )
    content, media_type = avatar
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/me/avatar", response_model=UserSchema)
@authorize(privileges=[])
async def upload_user_avatar(file: UploadFile = File(...)) -> UserModel:
    current_user_id = await _current_user_id()
    content = await file.read(user_service.AVATAR_MAX_BYTES + 1)
    try:
        user = await user_service.update_avatar(
            current_user_id,
            content,
            file.content_type,
        )
    except user_service.InvalidAvatarTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=render_prompt(
                await tr("user_api.errors.invalid_avatar_type"),
                types=", ".join(sorted(user_service.AVATAR_MEDIA_TYPES)),
            ),
        ) from exc
    except user_service.AvatarTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=await tr("user_api.errors.avatar_too_large"),
        ) from exc
    except user_service.InvalidAvatarContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=await tr("user_api.errors.invalid_avatar_content"),
        ) from exc
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("user_api.errors.user_not_found"),
        )
    return user


@router.delete("/me/avatar", response_model=UserSchema)
@authorize(privileges=[])
async def delete_user_avatar() -> UserModel:
    user = await user_service.delete_avatar(await _current_user_id())
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("user_api.errors.user_not_found"),
        )
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=["user"])
async def delete_user_me():
    """Delete the current user's account."""
    # @authorize guarantees authentication; retain the guard for strict typing.
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )
    try:
        success = await user_service.delete(int(current_user.id))
    except (AdministratorConflictError, user_service.UserConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=404, detail=await tr("user_api.errors.user_not_found"))
    return None


@router.get("/me/help-dismissals", response_model=list[str])
@authorize(privileges=[])
async def list_help_dismissals(response: Response) -> list[str]:
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(status_code=401, detail=await tr("user_api.errors.not_authenticated"))
    response.headers["Cache-Control"] = "no-store"
    return await help_service.list_dismissed(current_user.id)


@router.put("/me/help-dismissals/{help_key}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=[])
async def dismiss_help(
    help_key: Annotated[str, Path(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$")],
) -> None:
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(status_code=401, detail=await tr("user_api.errors.not_authenticated"))
    await help_service.dismiss(current_user.id, help_key)


@router.put("/me", response_model=UserSchema)
@authorize(privileges=[])  # Any authenticated user can update their own profile
async def update_user_me(user_update: UserUpdate):
    """Update the current user's profile."""
    # @authorize guarantees authentication; retain the guard for strict typing.
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )

    try:
        user = await user_service.update(int(current_user.id), user_update)
        if not user:
            raise HTTPException(status_code=404, detail=await tr("user_api.errors.user_not_found"))
        return user
    except AdministratorConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users", response_model=List[UserSchema])
@authorize(
    privileges=[
        Privileges.READ_USER,
        Privileges.CREATE_USER,
        Privileges.UPDATE_USER,
        Privileges.DELETE_USER,
    ]
)
async def list_users(
    response: Response,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    search: str | None = Query(default=None, max_length=200),
    sort_by: Literal["id", "email", "display_name", "is_active", "created_at"] = "id",
    descending: bool = False,
):
    response.headers["X-Total-Count"] = str(await user_service.count_users(search))
    return await user_service.get_users(skip, limit, search, sort_by=sort_by, descending=descending)


@router.post("/users", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.CREATE_USER)
async def create_user_endpoint(user: UserCreate):
    try:
        return await user_service.create(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users/{user_id}", response_model=UserSchema)
@authorize(
    privileges=[Privileges.READ_USER, Privileges.UPDATE_USER, Privileges.DELETE_USER]
)
async def read_user(user_id: int):
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=await tr("user_api.errors.user_not_found"))
    return user


@router.put("/users/{user_id}", response_model=UserSchema)
@authorize(privileges=Privileges.UPDATE_USER)
async def update_user_endpoint(user_id: int, user_update: UserUpdate):
    try:
        user = await user_service.update(user_id, user_update)
        if not user:
            raise HTTPException(status_code=404, detail=await tr("user_api.errors.user_not_found"))
        return user
    except AdministratorConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.DELETE_USER)
async def delete_user_endpoint(user_id: int):
    try:
        success = await user_service.delete(user_id)
    except (AdministratorConflictError, user_service.UserConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=404, detail=await tr("user_api.errors.user_not_found"))
    return None


# ============================================================================
# UserToken CRUD for the current user.
# ============================================================================

@router.get("/me/tokens", response_model=List[UserTokenResponse])
@authorize(privileges=["user"])
async def list_my_tokens():
    """List the current user's tokens."""
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )
    return await token_service.list_tokens_for_user(int(current_user.id))


@router.post("/me/tokens", response_model=UserTokenCreateResponse, status_code=status.HTTP_201_CREATED)
@authorize(privileges=["user"])
async def create_my_token(data: UserTokenCreate = UserTokenCreate()):
    """Create a token for the current user."""
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )
    db_token, plain_token = await token_service.create_token_for_user(int(current_user.id), data)
    return UserTokenCreateResponse(
        id=db_token.id,
        user_id=db_token.user_id,
        label=db_token.label,
        token=plain_token,
        enabled=db_token.enabled,
        created_at=db_token.created_at,
    )


@router.put("/me/tokens/{token_id}", response_model=UserTokenResponse)
@authorize(privileges=["user"])
async def update_my_token(token_id: int, data: UserTokenUpdate):
    """Update one of the current user's tokens."""
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )
    token = await token_service.update_token(token_id, int(current_user.id), data)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("user_api.errors.token_not_found"),
        )
    return token


@router.delete("/me/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=["user"])
async def delete_my_token(token_id: int):
    """Delete one of the current user's tokens."""
    current_user = await user_service.get_current_user()
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
        )
    success = await token_service.delete_token(token_id, int(current_user.id))
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("user_api.errors.token_not_found"),
        )
    return None
