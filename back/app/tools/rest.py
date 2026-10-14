"""Async REST facade using live Tool connections; endpoint rights belong to the remote API."""

import asyncio
import base64
import json
from contextlib import nullcontext
from typing import Any, cast
from urllib.parse import quote, quote_plus, unquote, urlsplit

import httpx
import logfire
from pydantic import JsonValue, ValidationError

from . import tool_service
from .rest_contracts import RestConfig, RestError, RestRequest, RestResponse, validate_rest_base_url


def _request_url(base: str, path: str) -> str:
    validate_rest_base_url(base)
    decoded = path
    for _ in range(8):
        updated = unquote(decoded)
        if updated == decoded:
            break
        decoded = updated
    parts = urlsplit(decoded)
    if (parts.scheme or parts.netloc or parts.query or parts.fragment or decoded.startswith("//")
            or "\\" in decoded or any(ord(char) < 32 for char in decoded)
            or any(part in {".", ".."} for part in decoded.split("/")) or "%" in decoded):
        raise RestError("REST path must stay relative to the configured base URL")
    return base.rstrip("/") + "/" + path.lstrip("/")


async def execute_rest_request(*, agent_id: int, tool_code: str, request: RestRequest,
                               connection_id: int | None = None) -> RestResponse:
    """Invoke any endpoint through the agent's active connection, without per-operation grants.

    Callers are responsible for admitting their authenticated execution context. This is a
    domain facade, not an HTTP proxy or an automatically exposed MCP function. HTTP error
    statuses are returned as results; transport failures never retry a potentially applied effect.
    """
    from app.connection.facade import get_connection_by_agent_tool, get_connection, get_params_as_dict

    tool = await tool_service.get_tool_record(tool_code)
    if tool is None or not tool.rest_config:
        raise RestError("REST API is not enabled for this Tool")
    connection = (await get_connection(connection_id) if connection_id is not None
                  else await get_connection_by_agent_tool(tool.id, agent_id))
    if connection is not None:
        connection = await get_connection(connection.id)
    if connection is None or connection.tool_id != tool.id or connection.agent_id != agent_id or not connection.active:
        raise PermissionError("An active connection belonging to the executing agent is required")
    try:
        config = RestConfig.model_validate(tool.rest_config)
    except ValidationError:
        raise RestError("Invalid REST Tool configuration") from None
    _, params = await get_params_as_dict(connection)

    def value(name: str) -> str:
        result: Any = params.get(name)
        if result is None or result == "":
            raise RestError("A required REST connection parameter is missing")
        return str(result)

    def header_value(name: str) -> str:
        result = value(name)
        if not result.isascii() or "\r" in result or "\n" in result:
            raise RestError("A REST connection header parameter is invalid")
        return result

    base = config.base_url
    if base.startswith("${connection:"):
        base = value(base[len("${connection:"):-1])
    try:
        url = _request_url(base, request.path)
    except ValueError:
        raise RestError("Invalid REST destination or relative path") from None
    headers = httpx.Headers(request.headers)
    if any(name in headers for name in ("host", "content-length", "transfer-encoding", "connection")):
        raise RestError("Transport headers cannot be supplied by a REST caller")
    secret_names = {name for name, definition in tool.connection_schema.get("params", {}).items()
                    if definition.get("type") == "password"}
    secrets = {str(params[name]) for name in secret_names if params.get(name)}
    # Connection-level headers and authentication take precedence over caller values.
    for name, parameter in config.header_params.items():
        headers[name] = header_value(parameter)
    auth = config.auth
    authentication: httpx.BasicAuth | None = None
    query = httpx.QueryParams(request.params)
    if auth.type != "none":
        if auth.type == "basic":
            login, password = value(auth.login_param), value(auth.password_param)
            authentication = httpx.BasicAuth(login, password)
            secrets.update((password, base64.b64encode(f"{login}:{password}".encode()).decode()))
            headers.pop("authorization", None)
        else:
            token = value(auth.param)
            secrets.add(token)
            if auth.type == "query":
                query = query.set(auth.query_name, token)
            else:
                token = header_value(auth.param)
                headers["Authorization" if auth.type == "bearer" else auth.header_name] = (
                    "Bearer " + token if auth.type == "bearer" else token)

    def redact(text: str) -> str:
        for secret in sorted(secrets, key=len, reverse=True):
            for representation in (secret, quote(secret, safe=""), quote_plus(secret)):
                text = text.replace(representation, "[redacted]")
        return text

    def redact_json(value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, list):
            return [redact_json(item) for item in value]
        if isinstance(value, dict):
            return {redact(key): redact_json(item) for key, item in value.items()}
        return value

    kwargs: dict[str, Any] = {}
    if "json_body" in request.model_fields_set:
        kwargs["content"] = json.dumps(request.json_body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif request.text_body is not None:
        kwargs["content"] = request.text_body.encode("utf-8")
    try:
        # Query authentication necessarily places a credential in the transport URL.
        # Do not let automatic HTTP instrumentation export that URL to telemetry.
        with logfire.suppress_instrumentation() if auth.type == "query" else nullcontext():
            async with asyncio.timeout(config.timeout):
                async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=False, trust_env=False) as client:
                    async with client.stream(request.method, url, params=query, headers=headers, auth=authentication, **kwargs) as response:
                        content = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            content.extend(chunk)
                            if len(content) > config.max_response_bytes:
                                raise RestError("REST response exceeds the configured size limit")
                        text = bytes(content).decode(response.encoding or "utf-8", errors="replace")
                        try:
                            body = redact_json(cast(JsonValue, json.loads(text)))
                        except ValueError:
                            body = redact(text)
                        return RestResponse(status_code=response.status_code, body=body,
                            headers={name: redact(value) for name, value in response.headers.items()
                                     if name.lower() not in {"set-cookie", "authorization", "proxy-authorization"}})
    except (TimeoutError, httpx.TimeoutException):
        raise RestError("REST request timed out; the remote effect may have occurred") from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise RestError("REST transport failed; the remote effect may have occurred") from None
