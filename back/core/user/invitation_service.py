"""Issue and redeem invitations for accounts that are awaiting their first password."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from urllib.parse import urlsplit

from loguru import logger
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from core import settings
from core.database import get_db, lock_resource_sharing
from core.i18n import current_language, render_prompt, t

from .lifecycle import notify_user_access_changed, project_user_activation
from .models import User
from .platform_mail import PlatformSmtp
from .user_service import clear_cache, encrypt_password

_INVITATION_LIFETIME = timedelta(hours=24)


class InvitationUnavailableError(Exception):
    """The account or platform is not configured for sending an invitation."""


class InvitationDeliveryError(Exception):
    """The SMTP submission failed."""


def invitation_mail_configuration() -> tuple[PlatformSmtp, str]:
    smtp = PlatformSmtp.configured()
    base_url = settings.APP_HOST.strip().rstrip("/")
    try:
        origin = urlsplit(base_url)
        valid_origin = (
            (origin.scheme == "https" or (settings.is_dev and origin.scheme == "http"))
            and origin.hostname and origin.username is None and not origin.query and not origin.fragment
        )
    except ValueError:
        valid_origin = False
    if smtp is None or not valid_origin:
        raise InvitationUnavailableError
    return smtp, f"{base_url}/user/invitation"


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


async def send_invitation(user_id: int) -> bool:
    """Issue the newest link before submitting its email to SMTP."""
    smtp, page = invitation_mail_configuration()
    lang = await current_language()
    db = get_db()
    user = await db.scalar(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    )
    if user is None:
        return False
    if not user.invitation_pending or user.is_active:
        raise InvitationUnavailableError

    token = token_urlsafe(32)
    lang = user.language or lang
    recipient = user.email
    user.invitation_digest = _digest(token)
    user.invitation_expires_at = datetime.now(timezone.utc) + _INVITATION_LIFETIME
    # Release the account lock before contacting the relay. If submission is
    # uncertain, a delivered link remains usable until another link is issued.
    await db.commit()

    subject = t("user_api.invitation.subject", lang)
    body = render_prompt(t("user_api.invitation.body", lang), url=f"{page}#{token}")
    try:
        await run_in_threadpool(smtp.send, recipient, subject, body)
    except (OSError, ValueError) as exc:
        logger.warning("Invitation SMTP delivery failed for user_id={} ({})", user_id, type(exc).__name__)
        raise InvitationDeliveryError from None
    return True


async def accept_invitation(token: str, password: str) -> bool:
    db = get_db()
    query = select(User).where(
        User.invitation_digest == _digest(token),
        User.invitation_pending.is_(True),
        User.is_active.is_(False),
    )
    eligible = query.where(User.invitation_expires_at > datetime.now(timezone.utc))
    if await db.scalar(eligible.with_only_columns(User.id)) is None:
        return False
    hashed_password = await run_in_threadpool(encrypt_password, password)
    await lock_resource_sharing()
    user = await db.scalar(
        query.where(User.invitation_expires_at > datetime.now(timezone.utc))
        .with_for_update().execution_options(populate_existing=True)
    )
    if user is None:
        return False

    user.hashed_password = hashed_password
    user.is_active = True
    user.invitation_pending = False
    user.invitation_digest = None
    user.invitation_expires_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()
    await project_user_activation(user.id, True)
    await db.commit()
    clear_cache()
    await notify_user_access_changed(user.id)
    return True
