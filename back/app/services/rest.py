"""Async REST facade using live Service connections; endpoint rights belong to the remote API."""

import asyncio
import base64
import hmac
import json
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from typing import Any, cast
from urllib.parse import quote, quote_plus, unquote, urlsplit
from uuid import UUID, uuid4

import httpx
import logfire
from pydantic import JsonValue, ValidationError

from . import service
from . import n8n_receipt
from .authorization import fingerprint
from .rest_contracts import (RestConfig, RestEffectIntent, RestError, RestRequest, RestRequestRejected, RestResponse, RestToolRequest, RestUpload,
                             validate_rest_base_url)


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
        raise ValueError("REST path must stay relative to the configured base URL")
    return base.rstrip("/") + "/" + path.lstrip("/")


async def execute_rest_request(*, agent_id: int, service_code: str, request: RestRequest,
                               connection_id: int | None = None,
                               uploads: tuple[RestUpload, ...] = (),
                               admit_effect: Callable[[RestEffectIntent], Awaitable[bool]] | None = None) -> RestResponse:
    """Invoke any endpoint through the agent's active connection, without per-operation grants.

    Callers admit their authenticated execution context and supply the Service code. An admitted
    connection identity pins execution to that exact account. HTTP error statuses
    are returned as results. RestRequestRejected guarantees that local validation
    failed before sending. Transport failures never retry a potentially applied effect.
    """
    return await _execute_rest_request(agent_id=agent_id, service_code=service_code, request=request,
        connection_id=connection_id, admit_effect=admit_effect, uploads=uploads)


async def find_rest_effect(*, agent_id: int, service_code: str, request: RestRequest, intent: RestEffectIntent) -> int | None:
    """Return a confirmed provider row identity without repeating a mutation."""
    try:
        row = n8n_receipt.insert_row(request)
        if row is None:
            return None
        response = await _execute_rest_request(agent_id=agent_id, service_code=service_code,
            request=n8n_receipt.lookup_request(request.path, intent.reference), expected_effect=(intent, request))
        return n8n_receipt.confirmed_row_id(response, row, intent.reference)
    except (PermissionError, ValueError):
        return None


async def _execute_rest_request(*, agent_id: int, service_code: str, request: RestRequest,
                                connection_id: int | None = None,
                                admit_effect: Callable[[RestEffectIntent], Awaitable[bool]] | None = None,
                                uploads: tuple[RestUpload, ...] = (),
                                expected_effect: tuple[RestEffectIntent, RestRequest] | None = None) -> RestResponse:
    from app.connection.facade import get_connection, get_params_as_dict

    tool = await service.get_service_record(service_code)
    if tool is None or not tool.rest_config:
        raise RestRequestRejected("REST API is not enabled for this Service")
    if connection_id is None:
        from app.connection.facade import resolve_service_connection

        try:
            connection = await resolve_service_connection(agent_id, service_code)
        except ValueError as exc:
            raise PermissionError(str(exc)) from exc
    else:
        connection = await get_connection(connection_id)
    if connection is None or connection.service_id != tool.id or connection.agent_id != agent_id or not connection.active:
        raise PermissionError("An active connection belonging to the executing agent is required")
    try:
        config = RestConfig.model_validate(tool.rest_config)
    except ValidationError:
        raise RestRequestRejected("Invalid REST Service configuration") from None
    _, params = await get_params_as_dict(connection)

    def value(name: str) -> str:
        result: Any = params.get(name)
        if result is None or result == "":
            raise RestRequestRejected("A required REST connection parameter is missing")
        return str(result)

    def header_value(name: str) -> str:
        result = value(name)
        if not result.isascii() or "\r" in result or "\n" in result:
            raise RestRequestRejected("A REST connection header parameter is invalid")
        return result

    base = config.base_url
    if base.startswith("${connection:"):
        base = value(base[len("${connection:"):-1])
    try:
        url = _request_url(base, request.path)
    except ValueError:
        raise RestRequestRejected("Invalid REST destination or relative path") from None
    headers = httpx.Headers(request.headers)
    if any(name in headers for name in ("host", "content-length", "transfer-encoding", "connection")):
        raise RestRequestRejected("Transport headers cannot be supplied by a REST caller")
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

    effect: RestEffectIntent | None = None
    supports_receipt = (config.effect_receipt == "n8n_data_table_insert" and auth.type == "header"
        and auth.header_name.lower() == "x-n8n-api-key" and urlsplit(base).path.rstrip("/").endswith("/api/v1"))

    def effect_binding(original: RestRequest, reference: UUID) -> str:
        return fingerprint(("n8n-data-table-insert/v1", reference, tool.id, connection.id, agent_id, base.rstrip("/"),
            dict(headers.items()), original.model_dump(mode="json")))

    if expected_effect is not None:
        intent, original = expected_effect
        if not supports_receipt or not hmac.compare_digest(effect_binding(original, intent.reference), intent.binding):
            raise RestRequestRejected("The original REST connection is unavailable for reconciliation")
    elif admit_effect is not None and supports_receipt and (row := n8n_receipt.insert_row(request)) is not None:
        reference = uuid4()
        effect = RestEffectIntent(reference=reference, binding=effect_binding(request, reference))
        request = n8n_receipt.insert_with_reference(request, row, reference)

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
    try:
        if "json_body" in request.model_fields_set:
            kwargs["content"] = json.dumps(request.json_body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(request, RestToolRequest) and request.file_uri is not None:
            if len(uploads) != 1:
                raise RestRequestRejected("The binary REST body is missing.")
            kwargs["content"] = uploads[0].content
            headers.setdefault("Content-Type", uploads[0].content_type)
        elif isinstance(request, RestToolRequest) and (request.files or request.form is not None):
            if len(uploads) != len(request.files):
                raise RestRequestRejected("A multipart REST file is missing.")
            if uploads:
                if "Content-Type" in headers and headers["Content-Type"].lower() != "multipart/form-data":
                    raise RestRequestRejected("File parts require multipart/form-data with an automatically generated boundary.")
                headers.pop("Content-Type", None)
                kwargs["files"] = [(part.field, (part.filename, part.content, part.content_type)) for part in uploads]
            else:
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            kwargs["data"] = request.form or {}
        elif request.text_body is not None:
            kwargs["content"] = request.text_body.encode("utf-8")
    except RestRequestRejected:
        raise
    except ValueError:
        raise RestRequestRejected("REST request body cannot be encoded") from None
    if effect is not None and admit_effect is not None and not await admit_effect(effect):
        raise RestRequestRejected("The Process stopped before sending the REST request")
    timeout = min(config.timeout, 5) if expected_effect is not None else config.timeout
    try:
        # Query authentication necessarily places a credential in the transport URL.
        # Do not let automatic HTTP instrumentation export that URL to telemetry.
        with logfire.suppress_instrumentation() if auth.type == "query" else nullcontext():
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
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
