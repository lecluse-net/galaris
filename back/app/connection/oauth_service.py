"""Durable MCP authorization code grants, isolated per agent connection."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, cast
from urllib.parse import urlencode, urlsplit

import httpx2 as httpx
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata, OAuthToken, ProtectedResourceMetadata
from pydantic import AnyHttpUrl, AnyUrl, BaseModel, Field, SecretStr, ValidationError
from sqlalchemy import select

from app.tools.facade import get_tool_by_id, mcp_http_client
from app.tools import McpConfig
from app.tools.facade import resolve_connection_references
from core.database import get_db
from core.settings import settings
from core.util import get_encryption_service
from . import connection_service
from . import oauth_loopback
from .models import Connection, ConnectionOAuth


class OAuthError(ValueError):
    """A safe, localizable error key, never a provider response or credential."""

    def __init__(self, key: str, *, response: httpx.Response | None = None, redirect_uri: str | None = None) -> None:
        super().__init__(key)
        self.redirect_uri = redirect_uri
        self.provider_status = response.status_code if response is not None else None
        self.provider_error: str | None = None
        if response is not None:
            try:
                payload: dict[str, object] | None = response.json()
            except ValueError:
                payload = None
            # Never return arbitrary provider text: descriptions may echo secrets.
            if isinstance(payload, dict):
                code = payload.get("error")
                if isinstance(code, str) and code in {
                    "invalid_redirect_uri", "invalid_client_metadata", "invalid_software_statement",
                    "unapproved_software_statement", "invalid_request", "invalid_client", "invalid_grant",
                    "unauthorized_client", "unsupported_grant_type", "invalid_scope", "access_denied",
                    "temporarily_unavailable", "server_error",
                    "authorization_pending", "slow_down", "expired_token",
                }:
                    self.provider_error = code


class Grant(BaseModel):
    binding: str
    server_url: str
    resource_url: str | None = None
    issuer: str
    token_endpoint: str
    client: OAuthClientInformationFull
    token: OAuthToken | None = None
    token_expires_at: float | None = None


DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class AuthorizationMetadata(OAuthMetadata):
    device_authorization_endpoint: AnyHttpUrl | None = None


class DeviceGrant(BaseModel):
    device_code: str
    interval: int
    next_poll_at: float


class Pending(BaseModel):
    grant: Grant
    user_id: int
    verifier: str = ""
    redirect_uri: str = ""
    device: DeviceGrant | None = None


class RegisteredClient(BaseModel):
    client_id: str = Field(min_length=1, max_length=2048)
    client_secret: SecretStr | None = None
    token_endpoint_auth_method: Literal["none", "client_secret_post", "client_secret_basic"] | None = None


class OAuthStartOptions(BaseModel):
    browser_origin: AnyHttpUrl | None = None
    client: RegisteredClient | None = None


class DeviceAuthorization(BaseModel):
    device_code: str = Field(min_length=1, max_length=8192)
    user_code: str = Field(min_length=1, max_length=128)
    verification_uri: AnyHttpUrl
    verification_uri_complete: AnyHttpUrl | None = None
    expires_in: int = Field(gt=0)
    interval: int = Field(default=5, ge=1, le=600)


class DevicePrompt(BaseModel):
    state: str
    user_code: str
    verification_uri: str
    interval: int


class DevicePoll(BaseModel):
    state: str = Field(min_length=20, max_length=256)


class DevicePollResult(BaseModel):
    connected: bool = False
    interval: int = 5


class OAuthStatus(BaseModel):
    connected: bool = False
    pending: bool = False
    reconnect_required: bool = False
    redirect_uri: str


class OAuthStart(BaseModel):
    method: Literal["redirect", "device", "configure"] = "redirect"
    authorization_url: str = ""
    local_script: str | None = None
    device: DevicePrompt | None = None
    redirect_uri: str = ""


class OAuthCallback(BaseModel):
    state: str = Field(min_length=20, max_length=256)
    code: str = Field(default="", max_length=8192)
    error: str = Field(default="", max_length=256)
    iss: str = Field(default="", max_length=2048)


def redirect_uri(browser_origin: AnyHttpUrl | None = None) -> str:
    base = settings.APP_HOST.rstrip("/")
    if browser_origin:
        origin = str(browser_origin).rstrip("/")
        parsed = urlsplit(origin)
        # Only the configured application or a genuine loopback origin can
        # receive codes. Never trust an arbitrary origin supplied by a client.
        if (parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password
                or (_origin(origin) != _origin(base) and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise OAuthError("configuration")
        base = origin
    return str(AnyHttpUrl(base + "/connection/oauth-callback"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _encrypt(model: BaseModel) -> str:
    return get_encryption_service().encrypt(model.model_dump_json())


def _decrypt(value: str) -> str:
    return get_encryption_service().decrypt(value)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.scheme not in {"https", "http"}:
        raise OAuthError("configuration")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise OAuthError("https_required")
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


async def _client(url: str, server_url: str) -> httpx.AsyncClient:
    # Private self-hosted servers are allowed only on the explicitly configured
    # MCP origin. Discovered third-party endpoints must resolve to public IPs.
    same_origin = _origin(url) == _origin(server_url)
    return await mcp_http_client(url, allow_private=same_origin)


async def _request(method: str, url: str, server_url: str, *,
                   data: dict[str, str] | None = None,
                   body: dict[str, object] | None = None,
                   headers: dict[str, str] | None = None) -> httpx.Response:
    try:
        async with await _client(url, server_url) as client:
            response = await client.request(method, url, data=data, json=body, headers=headers)
        return response
    except httpx.TimeoutException:
        raise OAuthError("provider_timeout") from None
    except (httpx.HTTPError, ValueError, OSError):
        raise OAuthError("provider_unavailable") from None


async def configuration(connection: Connection) -> tuple[McpConfig, str, str, dict[str, object]]:
    tool = await get_tool_by_id(connection.tool_id)
    if tool is None or tool.mcp is None or tool.mcp.type == "stdio":
        raise OAuthError("configuration")
    _, params = await connection_service.get_params_as_dict(connection)
    url = resolve_connection_references(tool.mcp.url or "", params)
    _origin(url)
    if urlsplit(url).query:
        raise OAuthError("configuration")
    # Authorization belongs to this agent connection and its resolved resource.
    binding = _hash(f"{connection.agent_id}:{connection.tool_id}:{url}")
    return tool.mcp, url, binding, params


async def _row(connection_id: int, *, lock: bool = False) -> ConnectionOAuth | None:
    query = select(ConnectionOAuth).where(ConnectionOAuth.connection_id == connection_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return await get_db().scalar(query)


async def status(connection: Connection) -> OAuthStatus:
    row = await _row(connection.id)
    if row is None:
        return OAuthStatus(redirect_uri=redirect_uri())
    _, _, binding, _ = await configuration(connection)
    grant = Grant.model_validate_json(_decrypt(row.grant)) if row and row.grant else None
    valid = bool(grant and grant.binding == binding and grant.token)
    usable = bool(valid and grant and (grant.token_expires_at is None or grant.token_expires_at > time.time()
                                      or (grant.token and grant.token.refresh_token)))
    return OAuthStatus(connected=usable, pending=bool(row and row.pending and row.expires_at and row.expires_at > datetime.now(timezone.utc)),
                       reconnect_required=bool(grant and not usable), redirect_uri=redirect_uri())


async def _discover(server_url: str) -> tuple[AuthorizationMetadata, ProtectedResourceMetadata | None, str | None]:
    # Only headers are read: a successful SSE GET can be an unbounded stream.
    try:
        async with await _client(server_url, server_url) as client:
            async with client.stream("GET", server_url, headers={"Accept": "application/json, text/event-stream"}) as response:
                challenge = httpx.Response(response.status_code, headers=response.headers)
    except httpx.TimeoutException:
        raise OAuthError("provider_timeout") from None
    except (httpx.HTTPError, ValueError, OSError):
        raise OAuthError("provider_unavailable") from None
    prm: ProtectedResourceMetadata | None = None
    for url in build_protected_resource_metadata_discovery_urls(extract_resource_metadata_from_www_auth(challenge), server_url):
        response = await _request("GET", url, server_url)
        if response.status_code == 200:
            prm = ProtectedResourceMetadata.model_validate_json(response.content)
            resource = str(prm.resource).rstrip("/")
            if server_url.rstrip("/") != resource and not server_url.startswith(resource + "/"):
                raise OAuthError("configuration")
            break
    issuer = str(prm.authorization_servers[0]) if prm else None
    for url in build_oauth_authorization_server_metadata_discovery_urls(issuer, server_url):
        response = await _request("GET", url, server_url)
        if response.status_code != 200:
            continue
        metadata = AuthorizationMetadata.model_validate_json(response.content)
        if issuer and str(metadata.issuer).rstrip("/") != issuer.rstrip("/"):
            raise OAuthError("configuration")
        _origin(str(metadata.authorization_endpoint))
        _origin(str(metadata.token_endpoint))
        if metadata.device_authorization_endpoint:
            _origin(str(metadata.device_authorization_endpoint))
        return metadata, prm, extract_scope_from_www_auth(challenge)
    raise OAuthError("discovery_failed")


def client_document(callback_uri: str | None = None, *, force_loopback: bool = False) -> OAuthClientInformationFull:
    """Public client metadata only; never connection or account information."""
    metadata_url = settings.APP_HOST.rstrip("/") + "/api/connections/oauth/client-metadata"
    redirects = [AnyUrl(redirect_uri()), AnyUrl(oauth_loopback.REDIRECT_URI)]
    if callback_uri and (force_loopback or callback_uri not in {str(uri) for uri in redirects}):
        scheme, host, port = _origin(callback_uri)
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise OAuthError("configuration")
        metadata_url += f"/loopback/{scheme}/{host}/{port}"
        redirects = [AnyUrl(callback_uri)]
    return OAuthClientInformationFull(client_id=metadata_url,
        client_name="Galaris", redirect_uris=redirects,
        grant_types=["authorization_code", "refresh_token", DEVICE_GRANT], response_types=["code"], token_endpoint_auth_method="none")


async def _registered_client(metadata: AuthorizationMetadata, url: str, callback_uri: str | None, scope: str | None,
                             previous: Grant | None, supplied: RegisteredClient | None) -> OAuthClientInformationFull:
    grant_type = "authorization_code" if callback_uri else DEVICE_GRANT
    redirects = [AnyUrl(callback_uri)] if callback_uri else None
    if supplied:
        secret = supplied.client_secret.get_secret_value() if supplied.client_secret else None
        methods = metadata.token_endpoint_auth_methods_supported or ["client_secret_basic"]
        method = (supplied.token_endpoint_auth_method or ("client_secret_basic" if "client_secret_basic" in methods else "client_secret_post")) if secret else "none"
        return OAuthClientInformationFull(client_id=supplied.client_id, client_secret=secret,
            redirect_uris=redirects, grant_types=[grant_type, "refresh_token"], token_endpoint_auth_method=method)
    if (previous and (not callback_uri or callback_uri in {str(uri) for uri in previous.client.redirect_uris or []})
            and grant_type in (previous.client.grant_types or ["authorization_code"])
            and (not previous.client.client_secret_expires_at or previous.client.client_secret_expires_at > time.time())):
        return previous.client
    if metadata.client_id_metadata_document_supported:
        document = client_document(callback_uri)
        metadata_url = document.client_id or ""
        if metadata_url.startswith("https://") and (not callback_uri or callback_uri in {str(uri) for uri in document.redirect_uris or []}):
            try:
                # A private or unreachable document cannot identify a client to
                # a public provider. Check our published document before using it.
                async with await mcp_http_client(metadata_url, allow_private=False) as client:
                    response = await client.get(metadata_url)
                published = OAuthClientInformationFull.model_validate_json(response.content)
                if (response.status_code == 200 and published.client_id == metadata_url
                        and published.client_secret is None and (not callback_uri
                            or callback_uri in {str(uri) for uri in published.redirect_uris or []})):
                    return document
            except (ValueError, httpx.HTTPError, OSError):
                pass
    if not metadata.registration_endpoint:
        raise OAuthError("automatic_setup_unavailable")
    requested_grants = [grant_type]
    if metadata.grant_types_supported is None or "refresh_token" in metadata.grant_types_supported:
        requested_grants.append("refresh_token")
    client_metadata = OAuthClientMetadata(redirect_uris=redirects, client_name="Galaris",
        grant_types=requested_grants, response_types=["code"] if callback_uri else [],
        token_endpoint_auth_method="none", scope=scope)
    response: httpx.Response | None = None
    registration_methods: list[Literal["none", "client_secret_basic", "client_secret_post"]] = ["none"]
    for supported_method in metadata.token_endpoint_auth_methods_supported or []:
        if supported_method == "client_secret_basic":
            registration_methods.append("client_secret_basic")
        elif supported_method == "client_secret_post":
            registration_methods.append("client_secret_post")
    for registration_method in registration_methods:
        client_metadata.token_endpoint_auth_method = registration_method
        response = await _request("POST", str(metadata.registration_endpoint), url,
                                  body=client_metadata.model_dump(mode="json", exclude_none=True,
                                      exclude={"response_types"} if callback_uri is None else set()))
        if response.status_code in {200, 201} or OAuthError("registration_failed", response=response).provider_error != "invalid_client_metadata":
            break
    assert response is not None
    if response.status_code not in {200, 201}:
        error = OAuthError("registration_failed", response=response, redirect_uri=callback_uri)
        if error.provider_error == "invalid_redirect_uri":
            key = "local_redirect_rejected" if callback_uri == oauth_loopback.REDIRECT_URI else "redirect_uri_rejected"
            error = OAuthError(key, response=response, redirect_uri=callback_uri)
        raise error
    try:
        raw_payload: object = response.json()
        if not isinstance(raw_payload, dict):
            raise ValueError("Expected an OAuth client metadata object")
        payload = cast(dict[str, object], raw_payload)
        if callback_uri is None and payload.get("redirect_uris") == []:
            payload["redirect_uris"] = None
        info = OAuthClientInformationFull.model_validate(payload)
    except ValueError:
        raise OAuthError("registration_invalid_response", response=response) from None
    if not info.client_id or (callback_uri is not None and not info.redirect_uris):
        raise OAuthError("registration_invalid_response", response=response)
    info.redirect_uris = redirects
    info.grant_types = client_metadata.grant_types
    if not payload.get("token_endpoint_auth_method"):
        info.token_endpoint_auth_method = client_metadata.token_endpoint_auth_method
    if info.token_endpoint_auth_method == "none":
        info.client_secret = None
    elif info.token_endpoint_auth_method in {"client_secret_basic", "client_secret_post"}:
        if not info.client_secret:
            raise OAuthError("registration_invalid_response", response=response)
    else:
        raise OAuthError("automatic_setup_unavailable")
    return info


async def _store_pending(connection: Connection, pending: Pending, state: str, *, expires_in: int = 600) -> None:
    # Serialize starts/disconnects on the parent even when no credential exists.
    await get_db().execute(select(Connection.id).where(Connection.id == connection.id).with_for_update())
    row = await _row(connection.id, lock=True)
    if row is None:
        row = ConnectionOAuth(connection_id=connection.id)
        get_db().add(row)
    row.pending = _encrypt(pending)
    row.state_hash = _hash(state)
    row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=min(expires_in, 600))
    await get_db().commit()


def _can_try_another_method(error: OAuthError) -> bool:
    # Only capability/setup refusals permit negotiation. Never retry timeouts,
    # provider outages, user denial or an invalid/expired authorization code.
    return (str(error) == "automatic_setup_unavailable" or error.provider_status in {401, 403, 404, 405}
        or error.provider_error in {"invalid_redirect_uri", "invalid_client_metadata", "unsupported_grant_type", "unauthorized_client"})


async def start(connection: Connection, user_id: int, options: OAuthStartOptions | None = None) -> OAuthStart:
    if not connection.active:
        raise OAuthError("inactive")
    options = options or OAuthStartOptions()
    _, url, binding, _ = await configuration(connection)
    metadata, prm, challenge_scope = await _discover(url)
    scope = get_client_metadata_scopes(challenge_scope, prm, metadata)
    web_callback = redirect_uri(options.browser_origin)
    _origin(web_callback)
    row = await _row(connection.id)
    previous = Grant.model_validate_json(_decrypt(row.grant)) if row and row.grant else None
    if previous and (previous.binding != binding or AnyHttpUrl(previous.issuer) != AnyHttpUrl(str(metadata.issuer))):
        previous = None
    grants = metadata.grant_types_supported
    pkce_methods = metadata.code_challenge_methods_supported
    # Older OAuth metadata may omit this field. Still send S256; never fall
    # back to a plain verifier or an authorization code without PKCE.
    code_supported = (pkce_methods is None or "S256" in pkce_methods) and (grants is None or "authorization_code" in grants)
    device_supported = metadata.device_authorization_endpoint is not None and (grants is None or DEVICE_GRANT in grants)
    if not code_supported and not device_supported:
        raise OAuthError("pkce_required")
    methods: list[tuple[str, str | None]] = []
    if code_supported:
        methods.append(("redirect", web_callback))
    if device_supported:
        methods.append(("device", None))
    if code_supported and web_callback != oauth_loopback.REDIRECT_URI:
        methods.append(("relay", oauth_loopback.REDIRECT_URI))
    error: OAuthError | None = None
    for method, callback_uri in methods:
        try:
            info = await _registered_client(metadata, url, callback_uri, scope, previous, options.client)
            grant = Grant(binding=binding, server_url=url, resource_url=str(prm.resource) if prm else url,
                issuer=str(metadata.issuer), token_endpoint=str(metadata.token_endpoint), client=info)
            state = secrets.token_urlsafe(32)
            if method == "device":
                assert metadata.device_authorization_endpoint is not None
                response = await _grant_request(grant, str(metadata.device_authorization_endpoint), {"scope": scope} if scope else {})
                if response.status_code != 200:
                    raise OAuthError("registration_failed", response=response)
                device = DeviceAuthorization.model_validate_json(response.content)
                verification = str(device.verification_uri_complete or device.verification_uri)
                _origin(verification)
                await _store_pending(connection, Pending(grant=grant, user_id=user_id,
                    device=DeviceGrant(device_code=device.device_code, interval=device.interval, next_poll_at=time.time() + device.interval)), state,
                    expires_in=device.expires_in)
                return OAuthStart(method="device", device=DevicePrompt(state=state, user_code=device.user_code,
                    verification_uri=verification, interval=device.interval))
            assert callback_uri is not None
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            await _store_pending(connection, Pending(grant=grant, user_id=user_id, verifier=verifier, redirect_uri=callback_uri), state)
            query = {"response_type": "code", "client_id": info.client_id or "", "redirect_uri": callback_uri,
                "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "resource": grant.resource_url or url}
            if scope:
                query["scope"] = scope
            endpoint = str(metadata.authorization_endpoint)
            authorization_url = endpoint + ("&" if "?" in endpoint else "?") + urlencode(query)
            script = oauth_loopback.build_script(authorization_url, web_callback) if method == "relay" else None
            return OAuthStart(authorization_url=authorization_url, local_script=script, redirect_uri=callback_uri)
        except OAuthError as exc:
            if not _can_try_another_method(exc):
                raise
            error = exc
    if error and str(error) != "automatic_setup_unavailable" and error.provider_status not in {401, 403, 404, 405}:
        raise error
    return OAuthStart(method="configure", redirect_uri=web_callback)


async def _grant_request(grant: Grant, endpoint: str, data: dict[str, str]) -> httpx.Response:
    client = grant.client
    if not client.client_id:
        raise OAuthError("configuration")
    data["client_id"] = client.client_id
    data["resource"] = grant.resource_url or grant.server_url
    headers: dict[str, str] = {}
    if client.client_secret:
        if client.token_endpoint_auth_method == "client_secret_basic":
            from urllib.parse import quote
            credentials = f"{quote(client.client_id, safe='')}:{quote(client.client_secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
        elif client.token_endpoint_auth_method == "client_secret_post":
            data["client_secret"] = client.client_secret
        else:
            raise OAuthError("configuration")
    return await _request("POST", endpoint, grant.server_url, data=data, headers=headers)


async def _exchange(grant: Grant, data: dict[str, str]) -> OAuthToken:
    response = await _grant_request(grant, grant.token_endpoint, data)
    if response.status_code != 200:
        raise OAuthError("authorization_required" if response.status_code in {400, 401, 403} else "provider_unavailable", response=response)
    try:
        token = OAuthToken.model_validate_json(response.content)
    except ValidationError:
        raise OAuthError("configuration") from None
    if token.token_type.lower() != "bearer" or not token.access_token:
        raise OAuthError("configuration")
    return token


def _set_token(grant: Grant, token: OAuthToken) -> None:
    # Providers may rotate the refresh token or omit it on refresh.
    if grant.token and not token.refresh_token:
        token.refresh_token = grant.token.refresh_token
    grant.token = token
    grant.token_expires_at = time.time() + token.expires_in if token.expires_in is not None else None


async def poll_device(connection: Connection, data: DevicePoll, user_id: int) -> DevicePollResult:
    row = await _row(connection.id, lock=True)
    if (not row or not row.pending or row.state_hash != _hash(data.state)
            or not row.expires_at or row.expires_at <= datetime.now(timezone.utc)):
        raise OAuthError("invalid_state")
    pending = Pending.model_validate_json(_decrypt(row.pending))
    if pending.user_id != user_id or pending.device is None:
        raise OAuthError("invalid_state")
    _, _, binding, _ = await configuration(connection)
    if not connection.active or pending.grant.binding != binding:
        raise OAuthError("invalid_state")
    device = pending.device
    if device.next_poll_at > time.time():
        return DevicePollResult(interval=max(1, int(device.next_poll_at - time.time()) + 1))
    # Reserve the next interval before I/O so concurrent requests never poll the
    # provider faster than it allows. Disconnect/new starts still win afterward.
    device.next_poll_at = time.time() + device.interval
    row.pending = _encrypt(pending)
    generation = row.state_hash
    await get_db().commit()
    response = await _grant_request(pending.grant, pending.grant.token_endpoint,
                                    {"grant_type": DEVICE_GRANT, "device_code": device.device_code})
    current = await _row(connection.id, lock=True)
    if current is None or current.state_hash != generation or not current.pending:
        raise OAuthError("invalid_state")
    if response.status_code != 200:
        error = OAuthError("authorization_required", response=response)
        if error.provider_error == "authorization_pending":
            return DevicePollResult(interval=device.interval)
        if error.provider_error == "slow_down":
            device.interval += 5
            device.next_poll_at = time.time() + device.interval
            current.pending = _encrypt(pending)
            await get_db().commit()
            return DevicePollResult(interval=device.interval)
        if response.status_code in {400, 401, 403}:
            current.pending = None
            current.state_hash = None
            current.expires_at = None
            await get_db().commit()
        if error.provider_error == "access_denied":
            raise OAuthError("authorization_denied", response=response)
        if error.provider_error == "expired_token":
            raise OAuthError("invalid_state", response=response)
        raise error
    try:
        token = OAuthToken.model_validate_json(response.content)
    except ValidationError:
        raise OAuthError("configuration") from None
    if token.token_type.lower() != "bearer" or not token.access_token:
        raise OAuthError("configuration")
    current_connection = await connection_service.get_connection(connection.id)
    if (current_connection is None or not current_connection.active or (await configuration(current_connection))[2] != binding
            or not current.expires_at or current.expires_at <= datetime.now(timezone.utc)):
        raise OAuthError("invalid_state")
    _set_token(pending.grant, token)
    current.grant = _encrypt(pending.grant)
    current.pending = None
    current.state_hash = None
    current.expires_at = None
    await get_db().commit()
    return DevicePollResult(connected=True)


async def complete(connection: Connection, callback: OAuthCallback, user_id: int) -> None:
    row = await _row(connection.id, lock=True)
    if not row or not row.pending or row.state_hash != _hash(callback.state) or not row.expires_at or row.expires_at <= datetime.now(timezone.utc):
        raise OAuthError("invalid_state")
    pending = Pending.model_validate_json(_decrypt(row.pending))
    if pending.user_id != user_id or pending.device is not None:
        raise OAuthError("invalid_state")
    _, _, binding, _ = await configuration(connection)
    # Consume before external I/O: denial, interruption and a lost response cannot
    # make this code reusable. A failed exchange requires a fresh authorization.
    generation = row.state_hash
    row.pending = None
    row.expires_at = None
    await get_db().commit()
    if callback.error:
        raise OAuthError("authorization_denied")
    issuer_matches = not callback.iss or AnyHttpUrl(callback.iss) == AnyHttpUrl(pending.grant.issuer)
    if not callback.code or not connection.active or pending.grant.binding != binding or not issuer_matches:
        raise OAuthError("invalid_state")
    token = await _exchange(pending.grant, {"grant_type": "authorization_code", "code": callback.code,
                            "redirect_uri": pending.redirect_uri, "code_verifier": pending.verifier})
    # A disconnect or newer authorization during the exchange wins.
    current = await _row(connection.id, lock=True)
    if current is None or current.pending or current.state_hash != generation:
        raise OAuthError("invalid_state")
    current_connection = await connection_service.get_connection(connection.id)
    if current_connection is None or not current_connection.active or (await configuration(current_connection))[2] != binding:
        raise OAuthError("invalid_state")
    _set_token(pending.grant, token)
    current.grant = _encrypt(pending.grant)
    current.state_hash = None
    await get_db().commit()


async def disconnect(connection: Connection) -> None:
    await get_db().execute(select(Connection.id).where(Connection.id == connection.id).with_for_update())
    row = await _row(connection.id, lock=True)
    if row:
        await get_db().delete(row)
    await get_db().commit()


async def access_token(connection_id: int, expected_url: str) -> str:
    """Resolve and refresh under a SQL lock; no interactive flow in agent runs."""
    connection = await connection_service.get_connection(connection_id)
    if connection is None or not connection.active:
        raise OAuthError("authorization_required")
    _, url, binding, _ = await configuration(connection)
    row = await _row(connection_id, lock=True)
    if row is None or not row.grant:
        raise OAuthError("authorization_required")
    grant = Grant.model_validate_json(_decrypt(row.grant))
    if url != expected_url or grant.binding != binding or grant.token is None:
        raise OAuthError("authorization_required")
    if grant.token_expires_at is not None and grant.token_expires_at <= time.time() + 30:
        if not grant.token.refresh_token:
            raise OAuthError("authorization_required")
        try:
            token = await _exchange(grant, {"grant_type": "refresh_token", "refresh_token": grant.token.refresh_token})
        except OAuthError as exc:
            if str(exc) == "authorization_required":
                grant.token = None
                row.grant = _encrypt(grant)
                await get_db().commit()
            raise
        _set_token(grant, token)
        row.grant = _encrypt(grant)
        await get_db().flush()
    assert grant.token is not None
    return grant.token.access_token


async def invalidate_token(connection_id: int, token: str) -> None:
    """A 401 invalidates only the grant used by that request, never a newer one."""
    row = await _row(connection_id, lock=True)
    if row and row.grant:
        grant = Grant.model_validate_json(_decrypt(row.grant))
        if grant.token and secrets.compare_digest(grant.token.access_token, token):
            grant.token = None
            row.grant = _encrypt(grant)
            await get_db().flush()
