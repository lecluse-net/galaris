"""Same-origin streaming gateway with one-use tickets and scoped IDE cookies."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
import secrets
import json
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, SecretStr
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.typing import Origin, Subprotocol

from core.authorize import independent_auth, public
from core.database import get_db, get_db_session
from core.settings import settings

from .contracts import runtime
from .models import CodeSession
from .service import authorize_session, digest, editor_origin, session_config, validate_target

router = APIRouter(prefix="/gateway", tags=["code-gateway"])
COOKIE = "galaris_code"
REVOCATION_CHECK_SECONDS = 10
FILTER = frozenset({"host", "cookie", "authorization", "connection", "upgrade", "keep-alive",
    "proxy-authorization", "proxy-authenticate", "transfer-encoding", "te", "trailer", "content-length",
    "set-cookie", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol",
    "forwarded", "x-forwarded-host", "x-forwarded-proto", "x-galaris-application-origin"})


def check_origin(request: Request | WebSocket, *, websocket: bool = False) -> None:
    configured = urlsplit(editor_origin())
    if request.headers.get("host") != configured.netloc:
        raise PermissionError("Use the application origin")
    origin = request.headers.get("origin")
    if (websocket or origin is not None) and origin != editor_origin():
        raise PermissionError("Invalid editor origin")


@router.get("/{identifier}/launch")
@public("Static IDE ticket bootstrap; contains no repository or session data and requires a separate authenticated POST")
async def launch_page(identifier: UUID, request: Request) -> HTMLResponse:
    try:
        check_origin(request)
    except PermissionError:
        raise HTTPException(403, "Use the application origin") from None
    nonce = secrets.token_urlsafe(24)
    failed = json.dumps({"type": "galaris.code.failed", "session": str(identifier)})
    application_origin = json.dumps(settings.APP_HOST.rstrip("/")).replace("<", "\\u003c")
    return HTMLResponse(f'''<!doctype html><meta charset="utf-8"><script nonce="{nonce}">
const ticket = new URLSearchParams(location.hash.slice(1)).get('ticket');
history.replaceState(null, '', location.pathname);
fetch(location.pathname, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{ticket}})}})
 .then(response => {{ if (!response.ok) throw new Error('Editor session unavailable'); return response.json() }})
 .then(data => location.replace(data.url)).catch(() => {{ parent.postMessage({failed}, {application_origin}); }});
</script>''', headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; frame-ancestors {settings.APP_HOST.rstrip('/')}"})


class LaunchTicket(BaseModel):
    ticket: SecretStr


@router.post("/{identifier}/launch")
@independent_auth("Single-use, 60-second IDE launch ticket on the application origin")
async def launch(identifier: UUID, request: Request, body: LaunchTicket) -> JSONResponse:
    try:
        check_origin(request)
        await get_db().get(CodeSession, identifier, with_for_update=True)
        session, workspace = await authorize_session(identifier, body.ticket.get_secret_value(), ticket=True)
        await validate_target(workspace)
        cookie = secrets.token_urlsafe(32)
        session.cookie_digest, session.ticket_digest = digest(cookie), None
        await get_db().commit()
    except (PermissionError, FileNotFoundError, ValueError):
        raise HTTPException(403, "Invalid or expired editor launch") from None
    except (RuntimeError, OSError):
        raise HTTPException(503, "Editor target unavailable") from None
    path = f"/api/code/gateway/{identifier}/"
    response = JSONResponse({"url": path + "editor/"},
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    response.set_cookie(COOKIE, cookie, path=path, httponly=True,
        secure=editor_origin().startswith("https://"), samesite="strict", max_age=86400)
    return response


async def _watch(identifier: UUID, cookie: str) -> None:
    while True:
        await asyncio.sleep(REVOCATION_CHECK_SECONDS)
        async with get_db_session():
            _, workspace = await authorize_session(identifier, cookie)
            await session_config(workspace)


def validate_proxy_path(path: str) -> None:
    decoded = unquote(path)
    if "\\" in decoded or ".." in decoded.split("/") or any(ord(value) < 32 for value in decoded):
        raise PermissionError("Invalid editor path")


def response_headers(headers: httpx.Headers, prefix: str) -> dict[str, str]:
    result = {key: value for key, value in headers.items() if key.lower() not in FILTER and key.lower() not in {"content-security-policy", "x-frame-options"}}
    location = result.get("location")
    if location and location.startswith("/") and not location.startswith("//"):
        result["location"] = prefix + location.lstrip("/")
    # Native worker and webview frames have both the IDE and application ancestors.
    result["content-security-policy"] = f"frame-ancestors 'self' {settings.APP_HOST.rstrip('/')}"
    result["x-frame-options"] = "SAMEORIGIN"
    result["referrer-policy"] = "no-referrer"
    result["cache-control"] = "no-store"
    return result


@router.api_route("/{identifier}/editor/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@independent_auth("Scoped IDE HttpOnly cookie; current repository grants checked for every stream")
async def editor_http(identifier: UUID, path: str, request: Request) -> StreamingResponse:
    cookie = request.cookies.get(COOKIE, "")
    try:
        check_origin(request)
        validate_proxy_path(path)
        _, workspace = await authorize_session(identifier, cookie)
        config = await session_config(workspace)
    except (PermissionError, FileNotFoundError, ValueError):
        raise HTTPException(403, "Editor access unavailable") from None
    await get_db().commit()
    endpoint_context = runtime().endpoint(config)
    try:
        endpoint = await endpoint_context.__aenter__()
    except (RuntimeError, OSError):
        raise HTTPException(503, "Editor transport unavailable") from None
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), trust_env=False)
    headers = {key: value for key, value in request.headers.items() if key.lower() not in FILTER}
    headers["Authorization"] = f"Bearer {endpoint.credential}"
    headers["X-Forwarded-Host"] = urlsplit(editor_origin()).netloc
    headers["X-Forwarded-Proto"] = urlsplit(editor_origin()).scheme
    headers["X-Galaris-Application-Origin"] = settings.APP_HOST.rstrip("/")
    url = endpoint.url + f"/sessions/{identifier}/editor/" + quote(path, safe="/._-")
    if request.url.query:
        url += "?" + request.url.query
    try:
        upstream = await client.send(client.build_request(request.method, url, headers=headers,
            content=request.stream()), stream=True)
    except (httpx.HTTPError, RuntimeError, OSError):
        await client.aclose()
        await endpoint_context.__aexit__(None, None, None)
        raise HTTPException(503, "Editor runtime unavailable") from None
    except BaseException:
        await client.aclose()
        await endpoint_context.__aexit__(None, None, None)
        raise

    async def body() -> AsyncGenerator[bytes]:
        watcher = asyncio.create_task(_watch(identifier, cookie))
        iterator = upstream.aiter_raw(65536).__aiter__()
        pending: asyncio.Task[bytes] | None = None
        async def next_chunk() -> bytes:
            return await anext(iterator)
        try:
            while True:
                pending = asyncio.create_task(next_chunk())
                done, _ = await asyncio.wait([pending, watcher], return_when=asyncio.FIRST_COMPLETED)
                if watcher in done:
                    with suppress(PermissionError, FileNotFoundError, ValueError):
                        watcher.result()
                    break
                try:
                    yield pending.result()
                except StopAsyncIteration:
                    break
        finally:
            watcher.cancel()
            if pending is not None:
                pending.cancel()
            await asyncio.gather(watcher, *([pending] if pending is not None else []), return_exceptions=True)
            await upstream.aclose()
            await client.aclose()
            await endpoint_context.__aexit__(None, None, None)
    return StreamingResponse(body(), status_code=upstream.status_code,
        headers=response_headers(upstream.headers, f"/api/code/gateway/{identifier}/editor/"))


@router.websocket("/{identifier}/editor/{path:path}")
async def editor_ws(identifier: UUID, path: str, websocket: WebSocket) -> None:
    cookie = websocket.cookies.get(COOKIE, "")
    try:
        check_origin(websocket, websocket=True)
        validate_proxy_path(path)
        async with get_db_session():
            _, workspace = await authorize_session(identifier, cookie)
            config = await session_config(workspace)
        async with runtime().endpoint(config) as endpoint:
            url = endpoint.url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + f"/sessions/{identifier}/editor/" + quote(path, safe="/._-")
            if websocket.url.query:
                url += "?" + websocket.url.query
            protocols = [Subprotocol(value.strip()) for value in websocket.headers.get("sec-websocket-protocol", "").split(",") if value.strip()]
            async with connect(url, origin=Origin(editor_origin()), additional_headers={"Authorization": f"Bearer {endpoint.credential}",
                    "X-Forwarded-Host": urlsplit(editor_origin()).netloc, "X-Forwarded-Proto": urlsplit(editor_origin()).scheme},
                    subprotocols=protocols or None, max_size=16 * 1024 * 1024, open_timeout=10) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)

                async def incoming() -> None:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        payload = message.get("bytes") if message.get("bytes") is not None else message.get("text")
                        if isinstance(payload, (bytes, str)):
                            await upstream.send(payload)

                async def outgoing() -> None:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing()), asyncio.create_task(_watch(identifier, cookie))]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
    except (PermissionError, FileNotFoundError, ValueError, ConnectionClosed, InvalidHandshake, WebSocketDisconnect, OSError, RuntimeError):
        pass
    finally:
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=1008)
