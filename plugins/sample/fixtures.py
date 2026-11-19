"""Read-only synthetic targets for the two development Service samples."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, Header, HTTPException, Response
from fastmcp import Client, FastMCP
import httpx

from core.authorize import Privileges, authorize, independent_auth

from .inventory import MCP_ENDPOINT, REST_ENDPOINT, REST_TOKEN


def mount(app: FastAPI) -> None:
    router = APIRouter(prefix="/api/plugin-samples", include_in_schema=False)
    server = FastMCP("Sample MCP")

    @server.tool()
    def sample_value() -> str:
        """Return a deterministic synthetic value."""
        return "sample-ok"

    @router.get("/rest/status")
    @independent_auth("Synthetic development-only REST bearer check")
    async def rest_status(authorization: Annotated[str | None, Header()] = None) -> dict[str, str]:
        if authorization != f"Bearer {REST_TOKEN}":
            raise HTTPException(status_code=401)
        return {"value": "sample-ok"}

    @router.api_route("/storage/note.txt", methods=["GET", "HEAD"])
    @independent_auth("Synthetic development-only storage bearer check")
    async def storage_sample(authorization: Annotated[str | None, Header()] = None) -> Response:
        if authorization != f"Bearer {REST_TOKEN}":
            raise HTTPException(status_code=401)
        return Response("sample-ok\n", media_type="text/plain")

    @router.get("/provider/v1/models")
    @independent_auth("Synthetic development-only provider bearer check")
    async def provider_models(authorization: Annotated[str | None, Header()] = None) -> dict[str, object]:
        if authorization != f"Bearer {REST_TOKEN}":
            raise HTTPException(status_code=401)
        return {"object": "list", "data": [{"id": "sample-model", "object": "model", "created": 0, "owned_by": "sample"}]}

    @router.post("/provider/v1/chat/completions")
    @independent_auth("Synthetic development-only provider bearer check")
    async def provider_chat(authorization: Annotated[str | None, Header()] = None) -> dict[str, object]:
        if authorization != f"Bearer {REST_TOKEN}":
            raise HTTPException(status_code=401)
        return {"id": "sample-completion", "object": "chat.completion", "created": 0, "model": "sample-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "sample-ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    @router.post("/{target}/probe")
    @authorize(privileges=[Privileges.PLUGIN_ACCESS, Privileges.PLUGIN_EDIT])
    async def probe(target: Literal["rest", "mcp"]) -> dict[str, str]:
        if target == "rest":
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(f"{REST_ENDPOINT}/status", headers={"Authorization": f"Bearer {REST_TOKEN}"})
                response.raise_for_status()
                if response.json() == {"value": "sample-ok"}:
                    return {"value": "sample-ok"}
        else:
            async with Client(MCP_ENDPOINT, timeout=5) as client:
                result = await client.call_tool("sample_value")
                if result.data == "sample-ok":
                    return {"value": "sample-ok"}
        raise HTTPException(status_code=502)

    mcp_app = server.http_app(path="/", stateless_http=True)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[Mapping[str, object]]:
        async with original_lifespan(application) as state, mcp_app.lifespan(mcp_app):
            yield state if state is not None else {}

    app.router.lifespan_context = lifespan
    app.include_router(router)
    app.mount("/api/plugin-samples/mcp", mcp_app)
