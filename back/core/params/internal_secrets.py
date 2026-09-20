"""Verify persistent internal secrets before removing obsolete deployment variables."""

import asyncio

from sqlalchemy import select

from core.database import get_db_session
from core.secrets import browser_executor_token
from .consts import Params
from .models import Param
from .params_service import normalize, reveal
from .web_push import deserialize_vapid_keys


async def verify_internal_secrets() -> None:
    async with get_db_session() as session:
        stored = await session.scalar(select(Param.value).where(Param.name == Params.AUTH_SECRET_KEY))
        value = reveal(Params.AUTH_SECRET_KEY, stored)
        if value is None or len(value.strip()) < 32:
            raise RuntimeError("The persistent signing key is invalid")
        stored = await session.scalar(select(Param.value).where(Param.name == Params.WEB_PUSH_VAPID_KEYS))
        deserialize_vapid_keys(reveal(Params.WEB_PUSH_VAPID_KEYS, stored) or "")
        for name in (
            Params.LOGFIRE_TOKEN, Params.BROWSER_SESSION_TTL_SECONDS, Params.BROWSER_MAX_SESSIONS,
            Params.MESSENGER_MAX_INLINE_MB, Params.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES,
        ):
            param = await session.scalar(select(Param).where(Param.name == name))
            if param is None:
                raise RuntimeError(f"The {name} preference has not been initialized")
            normalize(name, reveal(name, param.value))
    browser_executor_token()


if __name__ == "__main__":
    asyncio.run(verify_internal_secrets())
