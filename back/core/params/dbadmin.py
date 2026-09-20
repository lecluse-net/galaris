"""Programmatic DbAdmin data source for declared application parameters."""

from __future__ import annotations

import os
import secrets
from typing import cast

from sqlalchemy import Table, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminDataSource,
    DbAdminDataset,
    DbAdminDatasetResult,
    DbAdminRegistry,
)

from . import params_service
from .models import Param
from .consts import DEFAULT_PARAMS, Params
from core.util import encrypt_value
from .web_push import create_vapid_keys, deserialize_vapid_keys, serialize_vapid_keys


# Upgrade bridge only: seed newly moved preferences once. Existing rows, even
# explicit resets, always win. RuntimeSettings never reads the environment.
_LEGACY_OPERATION_PARAMS = (
    Params.MESSENGER_MAX_INLINE_MB,
    Params.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES,
    Params.LOGFIRE_TOKEN,
    Params.HARNESS_MANAGER_URL,
    Params.HARNESS_MANAGER_GALARIS_API_URL,
    Params.HARNESS_MANAGER_SECRET,
    Params.GALARIS_INTERNAL_MESSENGER_MAX_BYTES,
    Params.MEMORY_RESOURCE_MAX_BYTES,
    Params.BROWSER_EXECUTOR_TIMEOUT_SECONDS,
    Params.BROWSER_SESSION_TTL_SECONDS,
    Params.BROWSER_MAX_SESSIONS,
    Params.BROWSER_CONTENT_MAX_CHARS,
    Params.BROWSER_HTML_MAX_BYTES,
    Params.BROWSER_SCREENSHOT_TILE_HEIGHT,
    Params.BROWSER_SCREENSHOT_MAX_TILES,
    Params.BROWSER_SCREENSHOT_MAX_TOTAL_BYTES,
    Params.BROWSER_VIEWPORT_WIDTH,
    Params.BROWSER_VIEWPORT_HEIGHT,
)


async def _declared_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    """Seed missing preferences from the supported legacy configuration."""
    legacy = await session.scalar(select(Param.value).where(Param.name == "hermes.default.compose"))
    rows = params_service.declared_rows()
    existing = set(await session.scalars(select(Param.name).where(
        Param.name.in_(_LEGACY_OPERATION_PARAMS)
    )))
    for row in rows:
        name = str(row["name"])
        if name == Params.WEB_PUSH_VAPID_KEYS:
            stored = await session.scalar(select(Param).where(Param.name == name))
            if stored is not None:
                deserialize_vapid_keys(params_service.reveal(name, stored.value) or "")
            else:
                keys = create_vapid_keys()
                row["value"] = encrypt_value(serialize_vapid_keys(keys))
        if name == Params.AUTH_SECRET_KEY:
            stored = await session.scalar(select(Param).where(Param.name == name))
            if stored is not None:
                # A missing/corrupt stored value must stop startup, never rotate the key.
                params_service.reveal(name, stored.value)
            else:
                row["value"] = encrypt_value(secrets.token_hex(32))
        if name in _LEGACY_OPERATION_PARAMS and name not in existing:
            value = os.environ.get(name)
            if value is not None and value.strip():
                normalized = params_service.normalize(name, value)
                row["value"] = encrypt_value(normalized) if normalized and params_service.is_secret(name) else normalized
    if legacy is not None:
        for row in rows:
            if row["name"] == Params.HARNESS_DEFAULT_COMPOSE:
                row["value"] = legacy
    # update_columns=() preserves an existing common value, including an explicit reset.
    return rows


async def _reload_runtime_params(
    session: AsyncSession,
    _result: DbAdminDatasetResult,
) -> None:
    # Advance packaged size defaults only. Other administrator values and NULL
    # resets remain untouched; repeated synchronization is a no-op.
    for name, old_values in (
        (Params.MESSENGER_MAX_INLINE_MB, ("4", "4.0")),
        (Params.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES, ("20971520",)),
        (Params.MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES, ("1048576",)),
        (Params.PROCESS_SANITIZE_MAX_BYTES, ("65536",)),
    ):
        await session.execute(
            update(Param).where(Param.name == name, Param.value.in_(old_values))
            .values(value=DEFAULT_PARAMS[name]["value"])
        )
    prompts = list(
        (
            await session.scalars(
                select(Param).where(Param.name.in_(params_service.prompt_names()))
            )
        ).all()
    )
    for prompt in prompts:
        current_digest = params_service.prompt_default_digest(prompt.name)
        # Followers always advance.  Existing custom values receive their
        # initial baseline once; later packaged changes deliberately leave a
        # stale digest for the UI to resolve.
        if prompt.value is None or prompt.default_digest is None:
            prompt.default_digest = current_digest
    await session.flush()
    await params_service.refresh()


def datasets() -> tuple[DbAdminDataset, ...]:
    return (
        DbAdminDataset(
            key="core.params.declarations",
            table=cast(Table, Param.__table__),
            natural_key=("name",),
            rows=_declared_rows,
            # The declaration owns existence, never an administrator value.
            update_columns=(),
            delete_missing=True,
            after_merge=_reload_runtime_params,
            depends_on=("core.authorize.admin_grants",),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="core.params", factory=datasets)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
