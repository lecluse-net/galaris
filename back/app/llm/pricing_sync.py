"""Nightly provider-specific token prices, independent of agent execution."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import or_, select

from core.database import get_db
from core.util import local_timezone_name
from .capabilities import AICapability
from .llm_provider_service import decrypt_api_key
from .provider_facade import ProviderConnection, model_catalog_metadata
from .provider_models import LLM, LLMProvider
from .resource_discovery import list_resources, provider_connection


RATE_FIELDS = {
    "input": "cost_per_input_token",
    "cached_input": "cost_per_cached_input_token",
    "output": "cost_per_output_token",
}


@dataclass(frozen=True)
class _Model:
    id: int
    name: str
    capability: AICapability
    revision: datetime | None


@dataclass(frozen=True)
class _Provider:
    connection: ProviderConnection
    revision: datetime | None
    models: tuple[_Model, ...]


def nightly_boundary(now: datetime) -> datetime:
    """Most recent 03:00 in the installation timezone, including a missed night."""
    local = now.astimezone(ZoneInfo(local_timezone_name()))
    boundary = local.replace(hour=3, minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.astimezone(timezone.utc)


def _rates(pricing: Mapping[str, object]) -> dict[str, float]:
    rates: dict[str, float] = {}
    for key in RATE_FIELDS:
        value = pricing.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        try:
            number = float(value)
        except (ValueError, OverflowError):
            continue
        if math.isfinite(number) and number >= 0:
            rates[key] = number
    return rates


async def _claim(now: datetime) -> list[_Provider]:
    db = get_db()
    rows = (await db.execute(select(LLM, LLMProvider).join(LLMProvider).where(
        LLM.pricing_auto_update.is_(True), LLM.resource_type == "model",
        LLMProvider.is_active.is_(True),
        or_(LLM.pricing_updated_at.is_(None), LLM.pricing_updated_at < nightly_boundary(now)),
        or_(LLM.pricing_last_attempt_at.is_(None),
            LLM.pricing_last_attempt_at <= now - timedelta(minutes=30)),
    ).with_for_update(of=LLM, skip_locked=True))).all()
    grouped: dict[int, list[_Model]] = {}
    providers: dict[int, LLMProvider] = {}
    for llm, provider in rows:
        llm.pricing_last_attempt_at = now
        providers[provider.id] = provider
    await db.flush()
    for llm, provider in rows:
        await db.refresh(llm)
        grouped.setdefault(provider.id, []).append(_Model(
            llm.id, llm.llm_name, cast(AICapability, llm.primary_capability), llm.updated_at,
        ))
    snapshots = [_Provider(
        provider_connection(provider, decrypt_api_key(provider.api_key)),
        provider.updated_at, tuple(grouped[identifier]),
    ) for identifier, provider in providers.items()]
    # No row lock or transaction is kept across external HTTP calls.
    await db.commit()
    return snapshots


async def _fetch(provider: _Provider) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    prices: dict[str, dict[str, float]] = {}
    sources: dict[str, dict[str, str]] = {}
    catalog = model_catalog_metadata()
    if catalog is not None:
        try:
            async with asyncio.timeout(30):
                prices = await catalog.get_model_pricing(
                    provider.connection, tuple(model.name for model in provider.models),
                )
            sources = {name: {key: "models.dev" for key in values} for name, values in prices.items()}
        except Exception:
            logger.warning("LLM pricing catalog unavailable for provider {}", provider.connection.id)

    # Discover from detached configuration after committing the database claim.
    connection = provider.connection
    detached = LLMProvider(
        id=connection.id, name=connection.name, catalog_code=connection.catalog_code,
        provider_type=connection.provider_type, base_url=connection.base_url,
        configuration=connection.configuration, is_active=True,
    )
    capabilities: set[AICapability] = {model.capability for model in provider.models}
    for capability in sorted(capabilities):
        try:
            async with asyncio.timeout(45):
                models = await list_resources(detached, connection.api_key, capability)
            expected = {model.name for model in provider.models if model.capability == capability}
            for model in models:
                if model.id not in expected or model.resource_type != "model":
                    continue
                live = _rates(model.pricing or {})
                prices.setdefault(model.id, {}).update(live)
                sources.setdefault(model.id, {}).update({key: "provider" for key in live})
        except Exception:
            logger.warning("LLM provider prices unavailable for provider {} ({})", connection.id, capability)
    return prices, sources


async def _apply(
    provider: _Provider, prices: dict[str, dict[str, float]],
    sources: dict[str, dict[str, str]], attempted_at: datetime,
) -> None:
    db = get_db()
    current = await db.scalar(select(LLMProvider).where(
        LLMProvider.id == provider.connection.id,
        LLMProvider.is_active.is_(True), LLMProvider.updated_at == provider.revision,
    ).with_for_update().execution_options(populate_existing=True))
    if current is None:
        await db.commit()
        return
    for model in provider.models:
        llm = await db.scalar(select(LLM).where(
            LLM.id == model.id, LLM.pricing_auto_update.is_(True),
            LLM.updated_at == model.revision, LLM.pricing_last_attempt_at == attempted_at,
        ).with_for_update().execution_options(populate_existing=True))
        if llm is None:
            continue  # An administrator edited, removed or reassigned it while HTTP was pending.
        rates = _rates(prices.get(model.name, {}))
        llm.pricing_refresh_error = None if rates else "unavailable"
        if not rates:
            continue
        stamp = datetime.now(timezone.utc)
        pricing, provenance = dict(llm.pricing), dict(llm.pricing_provenance)
        for key, value in rates.items():
            setattr(llm, RATE_FIELDS[key], value)
            pricing[key] = value
            provenance[key] = {"source": sources[model.name][key], "updated_at": stamp.isoformat()}
        llm.pricing, llm.pricing_provenance = pricing, provenance
        llm.pricing_updated_at = stamp
    await db.commit()


async def refresh_pricing() -> None:
    """Poll once a minute; durable claims limit retries and prevent overlapping writes."""
    attempted_at = datetime.now(timezone.utc)
    providers = await _claim(attempted_at)
    if not providers:
        return
    catalog = model_catalog_metadata()
    if catalog is not None:
        catalog.clear_cache()
    for provider in providers:
        try:
            async with asyncio.timeout(180):
                prices, sources = await _fetch(provider)
            await _apply(provider, prices, sources, attempted_at)
        except Exception:
            await get_db().rollback()
            logger.warning("LLM pricing refresh failed for provider {}", provider.connection.id)
            await _apply(provider, {}, {}, attempted_at)
