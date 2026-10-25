"""Campaign-only MCP provider and metered model relay, with no application database."""

from __future__ import annotations

import asyncio
import functools
import inspect
import importlib
import json
import mimetypes
import math
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Awaitable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from loguru import logger

# Register module composition without entering its database/runtime lifespan.
importlib.import_module("main")

from app.file_share import mcp as file_tools, resource_service
from app.file_share.file_contracts import FileEntry, FileListing
from app.file_share.resource_contracts import ResourceContext
from app.tools.mcp_loader import McpToolContext

from .corpus import save

current_run: ContextVar[str] = ContextVar("navigation_run")


class FixtureTransport:
    """Only the external storage boundary is synthetic; the facade is unmodified."""

    def __init__(self, root: Path, metrics: dict[str, Any]) -> None:
        self.root = root
        self.metrics = metrics

    def path(self, value: str) -> Path:
        target = (self.root / value.lstrip("/")).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise PermissionError("Outside fixture")
        return target

    def entry(self, path: Path) -> FileEntry:
        return FileEntry(
            path=path.relative_to(self.root).as_posix(),
            is_dir=path.is_dir(),
            size=path.stat().st_size if path.is_file() else 0,
            modified_at="2026-01-01T00:00:00Z",
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )

    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        return self.entry(self.path(path))

    async def resource_list(self, path: str, *, recursive: bool, limit: int) -> FileListing:
        return await self.resource_list_page(path, recursive=recursive, limit=limit)

    async def resource_list_page(
        self, path: str, *, recursive: bool, limit: int, cursor: str | None = None
    ) -> FileListing:
        base = self.path(path)
        if base == self.root / "faults/interrupted":
            raise PermissionError("Synthetic enumeration failure; collection completeness unknown")
        if not base.is_dir():
            raise NotADirectoryError(path)
        paths = sorted(base.rglob("*") if recursive else base.iterdir())
        offset = int(cursor or 0)
        if offset < 0 or offset > len(paths):
            raise ValueError("Invalid continuation")
        page = paths[offset : offset + limit]
        end = offset + len(page)
        return FileListing(
            path,
            tuple(self.entry(p) for p in page),
            end < len(paths),
            str(end) if end < len(paths) else None,
        )

    async def download_to(
        self, remote: str, dest: Path, *, target: str = "", max_bytes: int = 512 * 1024 * 1024
    ) -> int:
        data = self.path(remote).read_bytes()
        if len(data) > max_bytes:
            raise ValueError("Transfer budget exceeded")
        dest.write_bytes(data)
        self.metrics[current_run.get()]["transferred_bytes"] += len(data)
        return len(data)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        raise PermissionError("Read-only campaign")


def application(root: Path, credentials: dict[str, Any], controls: dict[str, str]) -> FastAPI:
    manifest = json.loads((root / "manifest.json").read_text())
    runs = {r["id"]: r for r in manifest["runs"]}
    tokens = {value: key for key, value in controls.items()}
    metrics: dict[str, Any] = {
        key: dict(
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            usage_verified=True,
            file_calls=[],
            transferred_bytes=0,
            model_calls=0,
            provider_seconds=0.0,
            tool_seconds=0.0,
            usage=[],
        )
        for key in runs
    }
    transport = FixtureTransport(root / "corpus", metrics)
    mcp = FastMCP("Galaris synthetic File Share navigation")

    def authorized(token: str) -> str:
        if token not in tokens:
            raise HTTPException(403)
        return tokens[token]

    def persist(run: str) -> None:
        save(root / "metrics" / (run + ".json"), metrics[run])

    async def context(_ctx: McpToolContext) -> ResourceContext:
        return ResourceContext(agent_id=1, runtime="hermes", language="en")

    async def resolve(_agent: int, scheme: str, _path: str, **kwargs: Any) -> Any:
        if scheme != "fixture":
            raise PermissionError("Only the synthetic provider is connected")
        return transport, "fixture"

    async def targets(*args: Any, **kwargs: Any) -> Any:
        return [
            dict(
                code="fixture",
                label="Synthetic campaign",
                service="fixture",
                has_file_share=True,
                has_messenger=False,
                file_indexing_mode="excluded",
            )
        ]

    # Substitute server-owned identity and external provider resolution only.
    setattr(file_tools, "_resource_context", context)
    resource_service.resolve_resource_transport_with_service = resolve
    resource_service.describe_targets = targets

    def expose(function: Callable[..., Awaitable[str]]) -> None:
        definition: Any = getattr(function, "__galaris_mcp_tool__")

        @functools.wraps(function)
        async def call(**arguments: Any) -> str:
            request = get_http_request()
            run = authorized(request.headers.get("authorization", "").removeprefix("Bearer "))
            if runs[run]["arm"] != "mcp":
                raise PermissionError("MCP corpus access is disabled for the directory arm")
            for key in ("uri",):
                if key in arguments and not arguments[key].startswith("fixture://"):
                    raise PermissionError("Only fixture:// is in scope")
            token = current_run.set(run)
            started = time.monotonic()
            event: dict[str, Any] = dict(tool=definition.name, arguments=arguments)
            metrics[run]["file_calls"].append(event)
            try:
                answer = await function(McpToolContext(agent_id=1, runtime="hermes"), **arguments)
                event["response_bytes"] = len(answer.encode())
                event["result"] = json.loads(answer)
                return answer
            except Exception as error:
                event["error"] = type(error).__name__
                raise
            finally:
                metrics[run]["tool_seconds"] += time.monotonic() - started
                persist(run)
                current_run.reset(token)

        setattr(
            call,
            "__signature__",
            inspect.signature(function).replace(
                parameters=[
                    p for p in inspect.signature(function).parameters.values() if p.name != "ctx"
                ]
            ),
        )
        mcp.tool(name=definition.name, description=definition.description)(call)

    for function in (
        file_tools.file_schemes,
        file_tools.list_files,
        file_tools.file_info,
        file_tools.search_files,
        file_tools.read_file,
    ):
        expose(function)
    mcp_app = mcp.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with mcp_app.lifespan(app):
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", mcp_app)
    lock = asyncio.Lock()

    async def health() -> dict[str, bool]:
        return {"ready": True}

    app.add_api_route("/health", health, methods=["GET"])

    async def completion(token: str, request: Request) -> Response:
        run = authorized(token)
        # Serialization keeps the aggregate token reservation meaningful.
        async with lock:
            incoming = await request.body()
            if len(incoming) > 2_000_000:
                raise HTTPException(413)
            body: dict[str, Any] = json.loads(incoming)
            stream = body.pop("stream", False)
            body.pop("stream_options", None)
            body["model"] = credentials["model"]
            body["max_tokens"] = manifest["limits"]["max_completion_tokens"]
            body.pop("max_completion_tokens", None)
            body["temperature"] = 0
            body.pop("reasoning_effort", None)
            body["reasoning"] = {"effort": "none"}
            if "openrouter.ai" in credentials["base_url"]:
                body["provider"] = {"allow_fallbacks": False, "order": [credentials["upstream"]]}
            used = sum(m["input_tokens"] + m["output_tokens"] for m in metrics.values())
            # Reserve against the complete submitted prompt plus bounded output.
            reservation = len(incoming) + body["max_tokens"]
            if used + reservation > manifest["limits"]["max_campaign_tokens"]:
                raise HTTPException(429, "Frozen campaign token budget exhausted")
            started = time.monotonic()
            metrics[run]["model_calls"] += 1
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        credentials["base_url"].rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + credentials["api_key"]},
                        json=body,
                    )
                if response.status_code != 200:
                    metrics[run]["usage_verified"] = False
                    metrics[run]["provider_status"] = response.status_code
                    try:
                        detail = response.json().get("error", {})
                        metrics[run]["provider_error"] = str(detail.get("message", "")).replace(
                            credentials["api_key"], "[redacted]"
                        )[:500]
                    except ValueError, AttributeError:
                        pass
                    raise HTTPException(
                        response.status_code,
                        "Provider request failed; see redacted campaign metrics",
                    )
                value = response.json()
                usage = value.get("usage", {})
                verified = all(
                    type(usage.get(k)) is int and usage[k] >= 0
                    for k in ("prompt_tokens", "completion_tokens")
                )
                metrics[run]["usage_verified"] &= verified
                metrics[run]["input_tokens"] += usage.get("prompt_tokens", 0)
                metrics[run]["output_tokens"] += usage.get("completion_tokens", 0)
                metrics[run]["usage"].append(
                    dict(usage=usage, model=value.get("model"), provider=value.get("provider"))
                )
                cost = usage.get("cost")
                if (
                    type(cost) not in (int, float)
                    or not math.isfinite(cost)
                    or cost < 0
                    or metrics[run]["cost_usd"] is None
                ):
                    metrics[run]["cost_usd"] = None
                else:
                    metrics[run]["cost_usd"] += cost
            except HTTPException:
                raise
            except Exception:
                metrics[run]["usage_verified"] = False
                raise HTTPException(502, "Provider transport failure") from None
            finally:
                metrics[run]["provider_seconds"] += time.monotonic() - started
                persist(run)
        if not stream:
            return JSONResponse(value)

        async def events() -> AsyncIterator[str]:
            choice = value["choices"][0]
            message = choice["message"]
            delta = {k: v for k, v in message.items() if v is not None}
            if delta.get("tool_calls"):
                delta["tool_calls"] = [
                    {"index": i, **call} for i, call in enumerate(delta["tool_calls"])
                ]
            base = {k: value[k] for k in ("id", "created", "model") if k in value}
            chunks: list[dict[str, Any]] = [
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": choice.get("finish_reason", "stop"),
                        }
                    ],
                    "usage": usage,
                },
            ]
            for chunk in chunks:
                yield "data: " + json.dumps(chunk) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    app.add_api_route("/v1/{token}/chat/completions", completion, methods=["POST"])
    return app


def main() -> None:
    import uvicorn

    logger.remove()
    credentials = json.loads(Path("/credentials/config.json").read_text())
    controls = json.loads(Path("/controls/tokens.json").read_text())
    uvicorn.run(
        application(Path("/campaign"), credentials, controls),
        host="0.0.0.0",
        port=8099,
        access_log=False,
        log_level="error",
    )


if __name__ == "__main__":
    main()
