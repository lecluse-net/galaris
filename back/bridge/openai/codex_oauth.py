"""OpenAI Codex OAuth lifecycle and model discovery.

Codex OAuth credentials are deliberately owned by Galaris instead of reusing the Codex CLI or
Hermes credential store. Refresh tokens can rotate, so sharing one store between processes would
eventually invalidate one of them.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select

from core.database import get_db
from core.i18n import current_language, render_prompt, t
from core.util import as_dict, as_list, get_encryption_service
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderAuthenticationError
from app.llm.provider_models import LLMProvider


CODEX_API_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_DEVICE_VERIFICATION_URI = f"{CODEX_OAUTH_ISSUER}/codex/device"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"
CODEX_OAUTH_REDIRECT_URI = f"{CODEX_OAUTH_ISSUER}/deviceauth/callback"

_OAUTH_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_CODEX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_REFRESH_SKEW_SECONDS = 120


class CodexOAuthError(ProviderAuthenticationError):
    """A safe, user-facing Codex authentication failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "codex_oauth_error",
        status_code: int = 502,
        relogin_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.relogin_required = relogin_required


def _message(key: str, language: str, **values: Any) -> str:
    return render_prompt(t(f"llm_api.codex.{key}", language), **values)


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode non-sensitive JWT claims without verifying the already TLS-protected token."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return as_dict(decoded) if isinstance(decoded, dict) else {}
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError):
        return {}


def _account_id(token: str) -> Optional[str]:
    auth_claim = as_dict(_decode_jwt_claims(token).get("https://api.openai.com/auth"))
    account_id = auth_claim.get("chatgpt_account_id")
    return account_id.strip() if isinstance(account_id, str) and account_id.strip() else None


def account_id(token: str) -> Optional[str]:
    """Return the ChatGPT account claim needed by Codex external authentication."""

    return _account_id(token)


def plan_type(token: str) -> Optional[str]:
    """Return the ChatGPT plan claim used by Codex external authentication."""

    auth_claim = as_dict(_decode_jwt_claims(token).get("https://api.openai.com/auth"))
    value = auth_claim.get("chatgpt_plan_type")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _token_expiry(token: str) -> Optional[float]:
    value = _decode_jwt_claims(token).get("exp")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def codex_request_headers(access_token: str) -> dict[str, str]:
    """Return the headers expected by the ChatGPT Codex backend."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "codex_cli_rs/0.0.0 (Galaris)",
        "originator": "codex_cli_rs",
    }
    if account_id := _account_id(access_token):
        headers["ChatGPT-Account-ID"] = account_id
    return headers


def _response_error(response: httpx.Response, fallback: str) -> str:
    """Extract an upstream error message without ever including credentials."""
    try:
        payload = as_dict(response.json())
    except Exception:
        return fallback
    if not payload:
        return fallback
    error: Any = payload.get("error")
    if isinstance(error, dict):
        error_payload = as_dict(error)
        message: Any = (
            error_payload.get("message")
            or error_payload.get("code")
            or error_payload.get("type")
        )
    else:
        message = payload.get("error_description") or payload.get("message") or error
    return str(message).strip() if message else fallback


async def _get_provider(provider_id: int, *, for_update: bool = False) -> Optional[LLMProvider]:
    query = select(LLMProvider).where(LLMProvider.id == provider_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await get_db().execute(query)
    return result.scalar_one_or_none()


async def get_provider(provider_id: int) -> Optional[LLMProvider]:
    """Return the configured bridge connection for composition services."""

    return await _get_provider(provider_id)


def _assert_codex_provider(
    provider: Optional[LLMProvider],
    language: str,
) -> LLMProvider:
    if provider is None:
        raise CodexOAuthError(
            _message("provider_not_found", language),
            code="provider_not_found",
            status_code=404,
        )
    if provider.catalog_code != "openai-codex":
        raise CodexOAuthError(
            _message("not_codex_provider", language),
            code="not_codex_provider",
            status_code=400,
        )
    return provider


def _load_credentials(provider: LLMProvider, language: str) -> dict[str, Any]:
    encrypted = provider.oauth_credentials
    if not encrypted:
        return {}
    try:
        encryption = get_encryption_service()
        raw = encryption.decrypt(encrypted) if encryption.is_encrypted(encrypted) else encrypted
        payload = json.loads(raw)
        return as_dict(payload) if isinstance(payload, dict) else {}
    except Exception as exc:
        raise CodexOAuthError(
            _message("credentials_invalid", language),
            code="codex_credentials_invalid",
            status_code=401,
            relogin_required=True,
        ) from exc


def _save_credentials(provider: LLMProvider, credentials: dict[str, Any]) -> None:
    serialized = json.dumps(credentials, ensure_ascii=False, separators=(",", ":"))
    provider.oauth_credentials = get_encryption_service().encrypt(serialized)


def _credentials_are_fresh(credentials: dict[str, Any]) -> bool:
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token.strip():
        return False
    expires_at = credentials.get("expires_at")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        expires_at = _token_expiry(token)
    # Codex access tokens are JWTs today. If that ever changes, keep using an otherwise valid
    # opaque token and let the backend's 401 trigger a forced refresh.
    return expires_at is None or float(expires_at) > time.time() + _REFRESH_SKEW_SECONDS


def _credentials_from_token_payload(
    payload: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise CodexOAuthError(
            _message("access_token_missing", language),
            code="codex_access_token_missing",
            status_code=502,
        )
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    expires_at = _token_expiry(access_token)
    if expires_at is None and isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
        expires_at = time.time() + float(expires_in)
    return {
        "access_token": access_token.strip(),
        "refresh_token": refresh_token.strip() if isinstance(refresh_token, str) else "",
        "expires_at": expires_at,
        "account_id": _account_id(access_token),
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        "source": "device-code",
    }


async def start_device_login(provider_id: int) -> dict[str, Any]:
    """Create a Codex device challenge for a saved provider."""
    language = await current_language()
    _assert_codex_provider(await _get_provider(provider_id), language)
    try:
        async with httpx.AsyncClient(timeout=_OAUTH_TIMEOUT) as client:
            response = await client.post(
                f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise CodexOAuthError(
            _message("auth_unreachable", language, error=exc),
            code="device_code_request_failed",
        ) from exc

    if response.status_code == 429:
        raise CodexOAuthError(
            _message("login_rate_limited", language),
            code="codex_oauth_rate_limited",
            status_code=429,
        )
    if response.status_code != 200:
        raise CodexOAuthError(
            _response_error(
                response,
                _message("device_request_rejected", language),
            ),
            code="device_code_request_error",
            status_code=502,
        )

    payload = as_dict(response.json())
    user_code = payload.get("user_code")
    device_auth_id = payload.get("device_auth_id")
    if not isinstance(user_code, str) or not isinstance(device_auth_id, str):
        raise CodexOAuthError(
            _message("device_response_incomplete", language),
            code="device_code_incomplete",
        )
    interval = payload.get("interval")
    expires_in = payload.get("expires_in")
    interval_value = int(str(interval)) if str(interval or "").isdigit() else 5
    expires_in_value = int(str(expires_in)) if str(expires_in or "").isdigit() else 900
    return {
        "verification_uri": CODEX_DEVICE_VERIFICATION_URI,
        "user_code": user_code,
        "device_auth_id": device_auth_id,
        "interval": max(3, interval_value),
        "expires_in": max(60, expires_in_value),
    }


async def poll_device_login(
    provider_id: int,
    *,
    device_auth_id: str,
    user_code: str,
) -> dict[str, Any]:
    """Poll a device challenge and persist encrypted tokens once authorized."""
    language = await current_language()
    provider = _assert_codex_provider(await _get_provider(provider_id), language)
    try:
        async with httpx.AsyncClient(timeout=_OAUTH_TIMEOUT) as client:
            response = await client.post(
                f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/token",
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise CodexOAuthError(
            _message("poll_unreachable", language, error=exc),
            code="device_code_poll_failed",
        ) from exc

    if response.status_code in {403, 404}:
        return {"status": "pending", "oauth_connected": False}
    if response.status_code == 429:
        raise CodexOAuthError(
            _message("poll_rate_limited", language),
            code="codex_oauth_rate_limited",
            status_code=429,
        )
    if response.status_code != 200:
        raise CodexOAuthError(
            _response_error(response, _message("login_expired", language)),
            code="device_code_poll_error",
            status_code=400,
        )

    authorization = as_dict(response.json())
    authorization_code = authorization.get("authorization_code")
    code_verifier = authorization.get("code_verifier")
    if not isinstance(authorization_code, str) or not isinstance(code_verifier, str):
        raise CodexOAuthError(
            _message("authorization_incomplete", language),
            code="device_code_exchange_incomplete",
        )

    try:
        async with httpx.AsyncClient(timeout=_OAUTH_TIMEOUT) as client:
            token_response = await client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": CODEX_OAUTH_REDIRECT_URI,
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise CodexOAuthError(
            _message("exchange_unreachable", language, error=exc),
            code="token_exchange_failed",
        ) from exc

    if token_response.status_code == 429:
        raise CodexOAuthError(
            _message("exchange_rate_limited", language),
            code="codex_oauth_rate_limited",
            status_code=429,
        )
    if token_response.status_code != 200:
        raise CodexOAuthError(
            _response_error(
                token_response,
                _message("exchange_rejected", language),
            ),
            code="token_exchange_error",
            status_code=502,
        )

    credentials = _credentials_from_token_payload(
        as_dict(token_response.json()),
        language,
    )
    # Lock the provider row while replacing rotating credentials so concurrent UI actions cannot
    # overwrite a newer token pair.
    provider = _assert_codex_provider(
        await _get_provider(provider.id, for_update=True),
        language,
    )
    _save_credentials(provider, credentials)
    await get_db().commit()
    return {"status": "connected", "oauth_connected": True}


async def disconnect(provider_id: int) -> None:
    """Forget the locally stored Codex tokens."""
    language = await current_language()
    provider = _assert_codex_provider(
        await _get_provider(provider_id, for_update=True),
        language,
    )
    provider.oauth_credentials = None
    await get_db().commit()


async def _refresh_credentials(
    provider: LLMProvider,
    credentials: dict[str, Any],
    language: str,
) -> str:
    refresh_token = credentials.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise CodexOAuthError(
            _message("refresh_token_missing", language),
            code="codex_refresh_token_missing",
            status_code=401,
            relogin_required=True,
        )

    try:
        async with httpx.AsyncClient(
            timeout=_OAUTH_TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "galaris/1.0"},
        ) as client:
            response = await client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise CodexOAuthError(
            _message("refresh_unreachable", language, error=exc),
            code="codex_refresh_failed",
        ) from exc

    if response.status_code == 429:
        raise CodexOAuthError(
            _message("codex_rate_limited", language),
            code="codex_rate_limited",
            status_code=429,
        )
    if response.status_code != 200:
        relogin_required = response.status_code in {400, 401, 403}
        if relogin_required:
            provider.oauth_credentials = None
            await get_db().commit()
        raise CodexOAuthError(
            _response_error(response, _message("refresh_failed", language)),
            code="codex_refresh_failed",
            status_code=401 if relogin_required else 502,
            relogin_required=relogin_required,
        )

    payload = as_dict(response.json())
    if not payload.get("refresh_token"):
        payload["refresh_token"] = refresh_token
    refreshed = _credentials_from_token_payload(payload, language)
    _save_credentials(provider, refreshed)
    await get_db().commit()
    return str(refreshed["access_token"])


async def get_access_token(
    provider_id: int,
    *,
    force_refresh: bool = False,
    language: str | None = None,
) -> str:
    """Return a valid Codex access token, refreshing and persisting it when required."""
    language = language or await current_language()
    provider = _assert_codex_provider(await _get_provider(provider_id), language)
    credentials = _load_credentials(provider, language)
    if not force_refresh and _credentials_are_fresh(credentials):
        return str(credentials["access_token"])
    if not credentials:
        raise CodexOAuthError(
            _message("not_connected", language),
            code="codex_not_connected",
            status_code=401,
            relogin_required=True,
        )

    # PostgreSQL row locking serializes refresh-token rotation across backend workers. Re-read the
    # row after acquiring the lock because another request may already have refreshed it.
    provider = _assert_codex_provider(
        await _get_provider(provider_id, for_update=True),
        language,
    )
    credentials = _load_credentials(provider, language)
    if not force_refresh and _credentials_are_fresh(credentials):
        return str(credentials["access_token"])
    return await _refresh_credentials(provider, credentials, language)


async def list_models(provider: LLMProvider) -> list[LLMModelInfo]:
    """List the models enabled for the connected ChatGPT account."""
    language = await current_language()
    access_token = await get_access_token(provider.id, language=language)
    endpoint = f"{provider.base_url.rstrip('/')}/models"

    async def fetch(token: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=_CODEX_TIMEOUT) as client:
            return await client.get(
                endpoint,
                params={"client_version": "1.0.0"},
                headers=codex_request_headers(token),
            )

    try:
        response = await fetch(access_token)
        if response.status_code == 401:
            access_token = await get_access_token(
                provider.id,
                force_refresh=True,
                language=language,
            )
            response = await fetch(access_token)
    except httpx.HTTPError as exc:
        raise CodexOAuthError(
            _message("models_unreachable", language, error=exc),
            code="codex_models_request_failed",
        ) from exc

    if response.status_code != 200:
        raise CodexOAuthError(
            _response_error(response, _message("models_rejected", language)),
            code="codex_models_request_error",
            status_code=401 if response.status_code in {401, 403} else 502,
            relogin_required=response.status_code == 401,
        )

    payload = as_dict(response.json())
    sortable: list[tuple[int, LLMModelInfo]] = []
    for raw in as_list(payload.get("models")):
        if not isinstance(raw, dict):
            continue
        item = as_dict(raw)
        slug = item.get("slug") or item.get("id")
        if not isinstance(slug, str) or not slug.strip():
            continue
        visibility = str(item.get("visibility") or "").strip().lower()
        if visibility in {"hide", "hidden"}:
            continue
        context_window = item.get("context_window")
        context_length = (
            int(context_window)
            if isinstance(context_window, (int, float)) and not isinstance(context_window, bool)
            else None
        )
        display_name = item.get("display_name") or item.get("name") or slug
        description = item.get("description")
        modalities = {
            "input_text": True,
            "input_image": bool(item.get("supports_image_input") or item.get("supports_vision")),
            "output_text": True,
        }
        model = LLMModelInfo(
            id=slug.strip(),
            name=str(display_name),
            description=str(description) if description else None,
            context_length=context_length,
            modalities=modalities,
        )
        priority = item.get("priority")
        rank = int(priority) if isinstance(priority, (int, float)) else 10_000
        sortable.append((rank, model))

    sortable.sort(key=lambda entry: (entry[0], entry[1].id))
    return [model for _, model in sortable]
