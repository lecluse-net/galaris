# pyright: reportUnusedFunction=false
"""HTTP control endpoints shipped into the FastAPI managed runtimes."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from runtime_support import ActionApprovals, PROTOCOL, RuntimeActor, RuntimeRuns  # pyright: ignore[reportMissingImports]


def install_control(app: FastAPI, *, root: Path, authenticate: Callable[[Request], None],
                    events: Callable[[dict[str, Any], Request, Any], AsyncIterator[tuple[str, dict[str, Any]]]]) -> Any:
    runs = RuntimeRuns(root)

    @app.get("/v1/galaris/capabilities")
    async def capabilities(request: Request) -> dict[str, Any]:
        authenticate(request)
        return {"authorization_protocol": PROTOCOL, "resumable_runs": True}

    @app.post("/v1/galaris/runs")
    async def start(request: Request, body: dict[str, Any]) -> dict[str, str]:
        authenticate(request)
        credential = request.headers.get("X-Galaris-Run-Context", "")
        def factory(actor: RuntimeActor) -> AsyncIterator[tuple[str, dict[str, Any]]]:
            actor.approvals = ActionApprovals(mcp_url=os.environ.get("GALARIS_MCP_URL", ""),
                token=os.environ.get("GALARIS_MCP_TOKEN", ""), run_context=credential,
                session=actor.identifier, on_pending=actor.pending, on_running=actor.running)
            actor.approvals.validate()
            return events(body, request, actor)
        try:
            identifier = runs.start(credential, body, factory)
        except (PermissionError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error
        return {"runtime_run_id": identifier}

    @app.get("/v1/galaris/runs/{identifier}")
    async def status(identifier: str, request: Request) -> dict[str, Any]:
        authenticate(request)
        try:
            return runs.get(identifier)
        except LookupError as error:
            raise HTTPException(404, "Runtime run not found") from error

    @app.post("/v1/galaris/runs/{identifier}/cancel")
    async def cancel(identifier: str, request: Request) -> dict[str, bool]:
        authenticate(request)
        try:
            runs.cancel(identifier)
        except LookupError as error:
            raise HTTPException(404, "Runtime run not found") from error
        return {"cancelled": True}

    @app.post("/mcp/{identifier}")
    async def mcp(identifier: str, request: Request) -> Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = os.environ.get("GALARIS_MCP_TOKEN", "")
        if not expected or not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Invalid MCP principal")
        with runs.lock:
            actor = runs.actors.get(identifier)
        if actor is None or actor.approvals is None:
            raise HTTPException(404, "Runtime continuation not available")
        raw = await request.body()
        if len(raw) > 1_000_000:
            raise HTTPException(413, "MCP request exceeded its limit")
        import json
        try:
            status, payload = await asyncio.to_thread(actor.approvals.mcp, json.loads(raw))
        except (OSError, PermissionError, ValueError) as error:
            raise HTTPException(502, "MCP continuation failed without replay") from error
        return Response(payload, status_code=status, media_type="application/json")
    return runs
