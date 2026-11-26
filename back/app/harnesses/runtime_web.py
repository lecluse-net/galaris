# pyright: reportUnusedFunction=false
"""HTTP control endpoints shipped into the FastAPI managed runtimes."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from runtime_support import ActionApprovals, PROTOCOL, RuntimeActor, RuntimeRuns  # pyright: ignore[reportMissingImports]


@asynccontextmanager
async def deep_approvals(request: Request) -> AsyncGenerator[Any, None]:
    """Adapt an already authorized session to the current runtime HTTP stream."""
    credential = request.headers.get("X-Galaris-Deep-Control", "")
    if not credential:
        raise HTTPException(403, "Deep session control is required")
    identity = uuid4().hex
    approvals = ActionApprovals(mcp_url=os.environ.get("GALARIS_MCP_URL", ""),
        token=os.environ.get("GALARIS_MCP_TOKEN", ""), run_context=credential, session=identity,
        on_pending=lambda _: None)
    await asyncio.to_thread(approvals.validate)
    actor = SimpleNamespace(identifier=identity, approvals=approvals)
    actors = request.app.state.deep_actors
    actors[identity] = actor
    try:
        yield actor
    finally:
        approvals.cancelled.set()
        actors.pop(identity, None)


def install_control(app: FastAPI, *, root: Path, authenticate: Callable[[Request], None],
                    events: Callable[[dict[str, Any], Request, Any], AsyncIterator[tuple[str, dict[str, Any]]]]) -> Any:
    runs = RuntimeRuns(root)
    app.state.deep_actors = {}

    @app.get("/v1/galaris/capabilities")
    async def capabilities(request: Request) -> dict[str, Any]:
        authenticate(request)
        return {"authorization_protocol": PROTOCOL, "resumable_runs": True, "run_scoped_llm": True, "deep_sessions": True}

    def prepare(request: Request, body: dict[str, Any]) -> tuple[str, Callable[[RuntimeActor], AsyncIterator[tuple[str, dict[str, Any]]]]]:
        credential = request.headers.get("X-Galaris-Run-Context", "")
        def factory(actor: RuntimeActor) -> AsyncIterator[tuple[str, dict[str, Any]]]:
            actor.approvals = ActionApprovals(mcp_url=os.environ.get("GALARIS_MCP_URL", ""),
                token=os.environ.get("GALARIS_MCP_TOKEN", ""), run_context=credential,
                session=actor.identifier, on_pending=actor.pending, on_running=actor.running, on_children=actor.children)
            actor.approvals.validate()
            return events(body, request, actor)
        return credential, factory

    @app.post("/v1/galaris/runs")
    async def start(request: Request, body: dict[str, Any]) -> dict[str, str]:
        authenticate(request)
        credential, factory = prepare(request, body)
        try:
            identifier = runs.start(credential, body, factory)
        except (PermissionError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error
        return {"runtime_run_id": identifier}

    @app.post("/v1/galaris/runs/{identifier}/resume")
    async def resume(identifier: str, request: Request, body: dict[str, Any]) -> dict[str, str]:
        authenticate(request)
        credential, factory = prepare(request, body)
        try:
            runs.resume(identifier, credential, factory)
        except LookupError as error:
            raise HTTPException(404, "Runtime run not found") from error
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
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
        if actor is None:
            actor = app.state.deep_actors.get(identifier)
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
