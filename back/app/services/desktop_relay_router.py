"""HTTPS polling from the desktop and the backend's Streamable HTTP endpoint."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import JsonValue, ValidationError

from core.authorize import Privileges, authorize, independent_auth
from core.user import require_web_session
from . import desktop_relay as relay


router = APIRouter(prefix="/desktop-mcp")
MAX_BODY_BYTES = 1024 * 1024
SESSION_HEADER = "Mcp-Session-Id"


async def _body(request: Request) -> bytearray:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413, "MCP message is too large")
        data.extend(chunk)
    return data


@router.post("", dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.SERVICE_EDIT)
async def register_desktop_relay(data: relay.Registration, request: Request) -> dict[str, int]:
    try:
        service_id = await relay.register(data, request.headers.get(relay.DESKTOP_HEADER, ""))
    except PermissionError as exc:
        raise HTTPException(403, "Invalid desktop registration") from exc
    except ValueError as exc:
        raise HTTPException(422, "Invalid Service label") from exc
    return {"service_id": service_id}


@router.post("/{identifier}/poll", response_model=relay.Delivery | None)
@independent_auth("Per-Service desktop credential; claims only jobs bound to this relay.")
async def poll_desktop_relay(identifier: UUID, request: Request, offline: bool = False) -> relay.Delivery | None:
    token = request.headers.get(relay.DESKTOP_HEADER, "")
    try:
        if offline:
            await relay.presence(identifier, token, online=False)
            return None
        return await relay.poll(identifier, token)
    except PermissionError as exc:
        raise HTTPException(403) from exc


@router.post("/{identifier}/complete", status_code=204)
@independent_auth("Per-Service desktop credential; accepts replies to claimed jobs for this relay.")
async def complete_desktop_relay(identifier: UUID, request: Request) -> Response:
    try:
        data = relay.Completion.model_validate_json(await _body(request))
        await relay.complete(identifier, request.headers.get(relay.DESKTOP_HEADER, ""), data)
    except ValidationError as exc:
        raise HTTPException(400, "Invalid MCP reply") from exc
    except PermissionError as exc:
        raise HTTPException(403) from exc
    return Response(status_code=204)


@router.api_route("/{identifier}/mcp", methods=["POST", "DELETE"])
@independent_auth("Streamable HTTP authenticated by a separate capability stored on the bound Service.")
async def desktop_relay_mcp(identifier: UUID, request: Request) -> Response:
    token = request.headers.get(relay.SERVICE_HEADER, "")
    if request.headers.get("origin"):
        raise HTTPException(403)
    message: dict[str, JsonValue] | None = None
    if request.method == "POST":
        try:
            message = relay.message_adapter.validate_json(await _body(request))
        except ValidationError as exc:
            raise HTTPException(400, "Invalid MCP message") from exc
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            raise HTTPException(400, "Invalid MCP request")
    initialize = message is not None and message["method"] == "initialize"
    session_header = request.headers.get(SESSION_HEADER)
    try:
        session = uuid4() if initialize and session_header is None else UUID(session_header or "")
    except ValueError as exc:
        raise HTTPException(400, "Invalid MCP session") from exc
    if initialize and session_header is not None:
        raise HTTPException(400, "MCP session already specified")
    try:
        # Only response-bearing calls and session closure need a desktop round trip.
        if message is not None and "id" not in message:
            await relay.authorize_service(identifier, token)
            return Response(status_code=202)
        if message is not None and type(message["id"]) not in {str, int}:
            raise HTTPException(400, "Invalid MCP request identifier")
        reply = await relay.request_desktop(identifier, token, session, message)
    except PermissionError as exc:
        raise HTTPException(403) from exc
    except relay.RelayUnavailable as exc:
        raise HTTPException(503, "Desktop MCP unavailable") from exc
    if reply.get("missing") is True:
        raise HTTPException(404, "Desktop MCP session expired")
    if message is None:
        return Response(status_code=204)
    if isinstance(reply.get("error"), dict):
        return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "error": reply["error"]})
    if not isinstance(reply.get("result"), dict):
        raise HTTPException(502, "Invalid desktop MCP result")
    return JSONResponse(
        {"jsonrpc": "2.0", "id": message["id"], "result": reply["result"]},
        headers={SESSION_HEADER: str(session)} if initialize else None,
    )
