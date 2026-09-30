"""Shared HTTP boundary and numeric validation for provider-owned usage snapshots."""

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Literal

import httpx

from core.i18n import tr
from core.util import as_dict
from .provider_facade import ProviderAuthenticationError, ProviderConnection, ProviderQuotaWindow


def quota_number(value: object, *, signed: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if isfinite(number) and (signed or number >= 0) else None


def quota_reset(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value)
            return date.astimezone(timezone.utc) if date.tzinfo else None
        except ValueError:
            return None
    timestamp = quota_number(value)
    if timestamp is not None and timestamp > 0:
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return None


def amount_window(
    name: Literal["credits", "budget", "balance"], *,
    used: float | None = None, limit: float | None = None, remaining: float | None = None,
    unit: Literal["credits", "USD", "CNY"] = "credits", resets_at: datetime | None = None,
) -> ProviderQuotaWindow | None:
    if used is None and remaining is None:
        return None
    if remaining is None and limit is not None and used is not None:
        remaining = limit - used
    percent = used / limit * 100 if used is not None and limit is not None and limit > 0 else None
    if percent is not None and not isfinite(percent):
        percent = None
    return ProviderQuotaWindow(
        name=name, used_percent=percent, window_seconds=None, resets_at=resets_at,
        used=used, limit=limit, remaining=remaining, unit=unit,
    )


async def read_quota_payload(
    connection: ProviderConnection, path: str, *, auth_header: str = "Authorization",
) -> dict[str, Any]:
    """Read usage without retrying, inference, or exposing upstream response bodies."""
    message = await tr("llm_api.errors.provider_quota_unavailable")
    if not connection.api_key:
        raise ProviderAuthenticationError(message, code="provider_quota_unavailable", status_code=401)
    credential = connection.api_key if auth_header != "Authorization" else f"Bearer {connection.api_key}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            response = await client.get(
                f"{connection.base_url.rstrip('/')}/{path.lstrip('/')}",
                headers={auth_header: credential},
            )
        if response.status_code != 200:
            raise ProviderAuthenticationError(
                message, code="provider_quota_unavailable",
                status_code=response.status_code if response.status_code in {401, 403, 429} else 502,
            )
        return as_dict(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderAuthenticationError(message, code="provider_quota_unavailable") from exc


__all__ = ["amount_window", "quota_number", "quota_reset", "read_quota_payload"]
