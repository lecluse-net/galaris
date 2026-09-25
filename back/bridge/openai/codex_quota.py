"""Read account-wide Codex subscription windows without performing inference."""

from datetime import datetime, timezone
from math import isfinite
from typing import Literal

import httpx

from app.llm.facade import ProviderQuota, ProviderQuotaWindow
from core.i18n import current_language, t
from core.util import as_dict

from . import codex_oauth

# ChatGPT's account endpoint used by the Codex client, independent of model URLs.
_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def _window(name: Literal["primary", "secondary"], value: object) -> ProviderQuotaWindow | None:
    data = as_dict(value)
    used = _number(data.get("used_percent"))
    if used is None or not 0 <= used <= 100:
        return None
    duration = _number(data.get("limit_window_seconds"))
    reset = _number(data.get("reset_at"))
    resets_at = None
    if reset is not None:
        try:
            resets_at = datetime.fromtimestamp(reset, timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return ProviderQuotaWindow(
        name=name,
        used_percent=used,
        window_seconds=int(duration) if duration is not None and duration > 0 else None,
        resets_at=resets_at,
    )


async def get_quota(provider_id: int) -> ProviderQuota:
    language = await current_language()
    token = await codex_oauth.get_access_token(provider_id, language=language)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            response = await client.get(_USAGE_URL, headers=codex_oauth.codex_request_headers(token))
            if response.status_code == 401:
                token = await codex_oauth.get_access_token(
                    provider_id, force_refresh=True, language=language,
                )
                response = await client.get(_USAGE_URL, headers=codex_oauth.codex_request_headers(token))
    except httpx.HTTPError as exc:
        raise codex_oauth.CodexOAuthError(
            t("llm_api.codex.quota_unavailable", language), code="codex_quota_unavailable",
        ) from exc
    if response.status_code != 200:
        raise codex_oauth.CodexOAuthError(
            t("llm_api.codex.quota_unavailable", language),
            code="codex_quota_unavailable",
            status_code=response.status_code if response.status_code in {401, 403, 429} else 502,
            relogin_required=response.status_code == 401,
        )
    try:
        limits = as_dict(as_dict(response.json()).get("rate_limit"))
    except ValueError as exc:
        raise codex_oauth.CodexOAuthError(
            t("llm_api.codex.quota_unavailable", language), code="codex_quota_unavailable",
        ) from exc
    windows: list[ProviderQuotaWindow] = []
    for name in ("primary", "secondary"):
        window = _window(name, limits.get(f"{name}_window"))
        if window is not None:
            windows.append(window)
    return ProviderQuota(windows=windows, checked_at=datetime.now(timezone.utc))
