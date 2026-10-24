"""Resource-scoped browser cookies, revalidated against live user access."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from uuid import UUID

from fastapi import HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel, ValidationError

from core.authorize import check_privilege, role_id_ctx
from core.database import get_db
from core.secrets import auth_secret_key
from core.user import (
    current_web_session_family, get_current_user, get_user_record,
    user_identity_context, web_session_active,
)

from .browser_policy import resource_privileges

COOKIE_NAME = "galaris_file_media"
MEDIA_SECONDS = 6 * 60 * 60


class MediaGrant(BaseModel):
    user_id: int
    auth_version: int
    role_id: int | None
    family: str
    agent_id: int
    uri: str
    management: bool


def _key() -> str:
    # A media cookie cannot be used as a normal access JWT.
    return hmac.new(auth_secret_key().encode(), b"file-share-browser-media-v1", hashlib.sha256).hexdigest()


async def issue_media_cookie(identifier: UUID, agent_id: int, uri: str, management: bool) -> str:
    user = await get_current_user()
    family = current_web_session_family()
    if user is None or family is None:
        raise HTTPException(401, "A browser session is required")
    grant = MediaGrant(user_id=user.id, auth_version=user.auth_version, role_id=role_id_ctx.get(),
        family=family, agent_id=agent_id, uri=uri, management=management)
    return jwt.encode({**grant.model_dump(), "aud": str(identifier),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=MEDIA_SECONDS)}, _key(), algorithm="HS256")


@asynccontextmanager
async def media_identity(identifier: UUID, cookie: str | None) -> AsyncGenerator[MediaGrant]:
    try:
        payload = jwt.decode(cookie or "", _key(), algorithms=["HS256"], audience=str(identifier))
        grant = MediaGrant.model_validate(payload)
    except (JWTError, ValidationError) as exc:
        raise HTTPException(401, "Media access expired or unavailable") from exc
    user = await get_user_record(grant.user_id)
    if (user is None or not user.is_active or user.auth_version != grant.auth_version
            or not await web_session_active(grant.user_id, grant.family)):
        raise HTTPException(401, "Media session unavailable")
    role_token = role_id_ctx.set(grant.role_id)
    try:
        with user_identity_context(user):
            required = resource_privileges(grant.uri)
            if not required or not await check_privilege(user, list(required), get_db()):
                raise HTTPException(403, "Media access denied")
            yield grant
    finally:
        role_id_ctx.reset(role_token)
