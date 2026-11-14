"""Calendar provider registrations reuse the connection OAuth lifecycle."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, SecretStr

from app.tools.facade import get_tool_by_id
from . import connection_service
from .models import Connection
from .oauth_service import AuthorizationMetadata, OAuthError, RegisteredClient


PROVIDER_ROOTS = {"google": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                  "microsoft": "https://graph.microsoft.com/v1.0/me/calendars"}


async def configuration(connection: Connection) -> tuple[str, str, dict[str, object]]:
    tool = await get_tool_by_id(connection.tool_id)
    if tool is None or tool.calendar is None:
        raise OAuthError("configuration")
    config = tool.calendar
    provider = config.settings.get("source_kind", "caldav")
    _, params = await connection_service.get_params_as_dict(connection, decrypt_passwords=True)
    if provider in PROVIDER_ROOTS:
        url = PROVIDER_ROOTS[provider]
    elif provider == "caldav" and config.settings.get("auth_type") == "oauth":
        url = str(params.get(config.param_map.get("url", "")) or "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise OAuthError("configuration")
    else:
        raise OAuthError("configuration")
    # Include registration, endpoints and account choices. Changed configuration
    # cannot refresh a previous account's credential into a different resource.
    bound = json.dumps([connection.agent_id, connection.id, connection.tool_id, url,
                        {name: config.settings.get(name) for name in ("source_kind", "auth_type", "tenant", "issuer", "authorization_endpoint", "token_endpoint", "scope")},
                        {role: params.get(name) for role, name in config.param_map.items() if role in ("url", "username", "client_id", "client_secret")}], sort_keys=True, default=str)
    return url, hashlib.sha256(bound.encode()).hexdigest(), params


async def authorization(connection: Connection) -> tuple[AuthorizationMetadata, str, RegisteredClient, dict[str, str]]:
    _, _, params = await configuration(connection)
    tool = await get_tool_by_id(connection.tool_id)
    assert tool is not None and tool.calendar is not None
    config = tool.calendar
    provider = config.settings.get("source_kind", "caldav")
    client_id = str(params.get(config.param_map.get("client_id", "")) or "")
    secret = str(params.get(config.param_map.get("client_secret", "")) or "")
    if not client_id:
        raise OAuthError("configuration")
    extra: dict[str, str] = {}
    if provider == "google":
        issuer, authorize, token = "https://accounts.google.com", "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token"
        scope = "https://www.googleapis.com/auth/calendar"
        extra = {"access_type": "offline", "prompt": "consent"}
    elif provider == "microsoft":
        tenant = config.settings.get("tenant", "common")
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,255}", tenant):
            raise OAuthError("configuration")
        issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
        authorize = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        token = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        scope = "offline_access https://graph.microsoft.com/Calendars.ReadWrite https://graph.microsoft.com/Calendars.ReadWrite.Shared"
    else:
        issuer = config.settings.get("issuer", "")
        authorize = config.settings.get("authorization_endpoint", "")
        token = config.settings.get("token_endpoint", "")
        scope = config.settings.get("scope", "")
    for endpoint in (issuer, authorize, token):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise OAuthError("configuration")
    metadata = AuthorizationMetadata(issuer=AnyHttpUrl(issuer), authorization_endpoint=AnyHttpUrl(authorize),
        token_endpoint=AnyHttpUrl(token), response_types_supported=["code"], grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"], token_endpoint_auth_methods_supported=["client_secret_post", "none"])
    return metadata, scope, RegisteredClient(client_id=client_id, client_secret=SecretStr(secret) if secret else None,
        token_endpoint_auth_method="client_secret_post" if secret else "none"), extra


async def calendar_access_token(connection_id: int) -> tuple[str, str]:
    """Return a credential and its bound resource only inside a server worker."""
    from .oauth_service import access_token
    connection = await connection_service.get_connection(connection_id)
    if connection is None:
        raise OAuthError("authorization_required")
    url, _, _ = await configuration(connection)
    token = await access_token(connection_id, url, "calendar")
    return url, token


async def invalidate_calendar_token(connection_id: int, token: str) -> None:
    from .oauth_service import invalidate_token
    await invalidate_token(connection_id, token, "calendar")
