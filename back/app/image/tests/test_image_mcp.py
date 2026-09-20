from pathlib import Path
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from PIL import Image

from app.llm import ImageDimensionsError
from app.tools import RecoverableToolError
from fastmcp import FastMCP

from app.file_share import MaterializedResource, ResourceContext
from app.image import mcp as image_mcp
from app.image.mcp import _as_attachment_refs
from app.tools.mcp_loader import McpToolContext, add_galaris_tools


def test_generate_image_normalizes_attachment_references() -> None:
    assert _as_attachment_refs(None) == []
    assert _as_attachment_refs("") == []
    assert _as_attachment_refs("source.png") == ["source.png"]
    assert _as_attachment_refs([" a.png ", "", "b.png"]) == ["a.png", "b.png"]


def test_generate_image_keeps_paths_for_transport_aware_normalization() -> None:
    assert _as_attachment_refs("/opt/data/galaris/source.png") == [
        "/opt/data/galaris/source.png"
    ]


@pytest.mark.asyncio
async def test_private_image_url_is_rejected_with_canonical_uri_guidance(monkeypatch):
    from app.file_share import web_transport

    class Resolver:
        async def getaddrinfo(self, *_args, **_kwargs):
            return [(None, None, None, None, ("127.0.0.1", 443))]

    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(web_transport.asyncio, "get_running_loop", lambda: Resolver())
    connection = AsyncMock()
    describe = AsyncMock()
    monkeypatch.setattr(web_transport, "_new_client", connection)
    monkeypatch.setattr(image_mcp.image_service, "describe_image", describe)
    with pytest.raises(RecoverableToolError) as failure:
        await image_mcp.describe_image(McpToolContext(agent_id=17, runtime="internal"), "https://files.example/image.png")
    assert "non-public" in str(failure.value)
    assert "canonical file URI" in str(failure.value)
    connection.assert_not_called()
    describe.assert_not_awaited()


def test_generated_image_defaults_to_console_or_requires_a_destination() -> None:
    console_context = ResourceContext(
        agent_id=17,
        runtime="internal",
        console_resource=object(),
    )
    provider_only_context = ResourceContext(agent_id=17, runtime="hermes")

    console, _ = image_mcp._destination(  # pyright: ignore[reportPrivateUsage]
        console_context, "", "generated_image.png"
    )
    assert str(console) == "console://generated_image.png"
    with pytest.raises(RuntimeError, match="No local filesystem"):
        image_mcp._destination(  # pyright: ignore[reportPrivateUsage]
            provider_only_context, "", "generated_image.png"
        )


@pytest.mark.asyncio
async def test_generate_image_schema_accepts_flexible_optional_args() -> None:
    mcp = FastMCP("test")
    add_galaris_tools(mcp, 1, runtime="internal", enabled_tool_codes={"image"})

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    schema = tools["image_generate"].parameters

    assert schema["required"] == ["prompt"]
    assert schema["properties"]["prompt"]["type"] == "string"
    assert "type" not in schema["properties"]["attachments"]
    assert "type" not in schema["properties"]["destination"]
    for dimension in ("width", "height"):
        prop = schema["properties"][dimension]
        assert prop["default"] is None
        integer = next(choice for choice in prop["anyOf"] if choice["type"] == "integer")
        assert integer["minimum"] == 1
        assert "maximum" not in integer


@pytest.mark.asyncio
async def test_describe_image_propagates_agent_and_task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    context = McpToolContext(agent_id=17, runtime="internal", task_id=task_id)
    received: dict[str, object] = {}
    temporary_paths: list[Path] = []

    async def fake_language(ctx: McpToolContext) -> str:  # noqa: ARG001
        return "fr"

    resource_context = ResourceContext(agent_id=17, runtime="internal", task_id=task_id)

    async def fake_resource_context(
        ctx: McpToolContext, language: str
    ) -> ResourceContext:
        assert ctx is context
        assert language == "fr"
        return resource_context

    async def fake_materialize(
        received_ctx: ResourceContext,
        uri: object,
        destination: Path,
        *,
        max_bytes: int,
    ) -> MaterializedResource:
        assert received_ctx is resource_context
        assert uri == "nextcloud://Photos/illustration.png"
        assert max_bytes == image_mcp._MAX_IMAGE_RESOURCE_BYTES
        temporary_paths.append(destination)
        destination.write_bytes(b"image")
        return MaterializedResource(
            uri=str(uri),
            name="illustration.png",
            media_type="application/octet-stream",
            size=5,
        )

    async def fake_describe(
        data: bytes,  # noqa: ARG001
        mime: str,
        instruction: str,
        *,
        language: str,
        task_id: object,
        agent_id: int,
    ) -> str:
        received.update({
            "mime": mime,
            "instruction": instruction,
            "language": language,
            "task_id": task_id,
            "agent_id": agent_id,
        })
        return "Image correcte"

    monkeypatch.setattr(image_mcp, "_context_language", fake_language)
    monkeypatch.setattr(image_mcp, "_resource_context", fake_resource_context)
    monkeypatch.setattr(image_mcp, "materialize_resource", fake_materialize)
    monkeypatch.setattr(image_mcp.image_service, "describe_image", fake_describe)
    async def fake_record(ctx: ResourceContext, uri: str, description: str):
        assert ctx is resource_context
        assert uri == "nextcloud://Photos/illustration.png"
        assert description == "Image correcte"
        return uuid4()
    monkeypatch.setattr(image_mcp, "record_resource_description", fake_record)

    result = await image_mcp.describe_image(
        context,
        "nextcloud://Photos/illustration.png",
        "Contrôler",
    )

    assert result == "Image correcte"
    assert temporary_paths and not temporary_paths[0].exists()
    assert received == {
        "mime": "image/png",
        "instruction": "Contrôler",
        "language": "fr",
        "task_id": task_id,
        "agent_id": 17,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("dimensions", [{}, {"width": 1920, "height": 1080}, {"width": 100000, "height": 100000}])
async def test_generate_image_propagates_agent_and_task_context(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: dict[str, int],
) -> None:
    task_id = uuid4()
    context = McpToolContext(agent_id=17, runtime="internal", task_id=task_id)
    received: dict[str, object] = {}

    async def fake_language(ctx: McpToolContext) -> str:  # noqa: ARG001
        return "fr"

    resource_context = ResourceContext(agent_id=17, runtime="internal", task_id=task_id)
    output = BytesIO()
    Image.new("RGB", (1200, 896)).save(output, format="PNG")
    image_content = output.getvalue()

    async def fake_resource_context(
        ctx: McpToolContext, language: str
    ) -> ResourceContext:
        assert ctx is context
        assert language == "fr"
        return resource_context

    async def fake_generate(
        prompt: str,
        sources: object,
        *,
        width: int | None,
        height: int | None,
        language: str,
        task_id: object,
        agent_id: int,
    ) -> tuple[bytes, str]:
        received.update({
            "prompt": prompt,
            "sources": sources,
            "width": width,
            "height": height,
            "language": language,
            "task_id": task_id,
            "agent_id": agent_id,
        })
        return image_content, "image/png"

    async def fake_store(
        received_ctx: ResourceContext,
        out: str,
        data: bytes,
        *,
        default_name: str,
    ) -> str:
        assert received_ctx is resource_context
        assert data == image_content
        assert default_name == "generated_image.png"
        return out

    monkeypatch.setattr(image_mcp, "_context_language", fake_language)
    monkeypatch.setattr(image_mcp, "_resource_context", fake_resource_context)
    monkeypatch.setattr(image_mcp.image_service, "generate_image_bytes", fake_generate)
    monkeypatch.setattr(image_mcp, "_store_image", fake_store)

    result = await image_mcp.generate_image(
        context,
        "Créer une affiche",
        destination="nextcloud://Shared/poster.png",
        **dimensions,
    )

    assert "nextcloud://Shared/poster.png" in result
    assert "1200 × 896" in result
    assert received == {
        "prompt": "Créer une affiche",
        "sources": None,
        "width": dimensions.get("width"),
        "height": dimensions.get("height"),
        "language": "fr",
        "task_id": task_id,
        "agent_id": 17,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("dimensions", [
    {"width": 100},
    {"height": 100},
    {"width": 0, "height": 100},
    {"width": 100, "height": -1},
    {"width": True, "height": 100},
    {"width": 100.5, "height": 100},
])
async def test_invalid_dimensions_fail_before_resource_or_provider_access(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: dict[str, object],
) -> None:
    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    resource_context = AsyncMock()
    generate = AsyncMock()
    monkeypatch.setattr(image_mcp, "_resource_context", resource_context)
    monkeypatch.setattr(image_mcp.image_service, "generate_image_bytes", generate)

    with pytest.raises(ValidationError):
        await image_mcp.generate_image(
            McpToolContext(agent_id=17, runtime="internal"),
            "A poster",
            **dimensions,
        )
    resource_context.assert_not_awaited()
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_generation_failure_never_writes_destination(monkeypatch):
    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(image_mcp, "_resource_context", AsyncMock(return_value=ResourceContext(agent_id=17, runtime="internal")))
    monkeypatch.setattr(image_mcp.image_service, "generate_image_bytes", AsyncMock(
        side_effect=ImageDimensionsError("Image provider has no usable image configuration"),
    ))
    store = AsyncMock()
    monkeypatch.setattr(image_mcp, "_store_image", store)

    with pytest.raises(RecoverableToolError, match="no usable image configuration") as caught:
        await image_mcp.generate_image(
            McpToolContext(agent_id=17, runtime="internal"), "An image",
            destination="nextcloud://Shared/existing.png", width=1024, height=1024,
        )
    assert "Do not replace it with SVG/code artwork" in str(caught.value)
    store.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
@pytest.mark.parametrize("failure", [
    ImageDimensionsError("Image model has no usable configuration; check the selected model"),
    RuntimeError("Provider error with private credential=secret-value"),
])
async def test_image_failure_is_an_mcp_error_without_artifact_effects(monkeypatch, runtime, failure):
    from fastmcp import Client, FastMCP
    from app.tools import mcp_loader, resource_effects

    # This scenario tests media failure semantics. Harness policy persistence has
    # its own database tests; permit execution at that external domain boundary.
    monkeypatch.setattr("app.agent.effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))

    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(image_mcp.image_service, "generate_image_bytes", AsyncMock(side_effect=failure))
    store = AsyncMock()
    effects = AsyncMock()
    monkeypatch.setattr(image_mcp, "_store_image", store)
    monkeypatch.setattr(resource_effects, "record_tool_resources", effects)
    definition = mcp_loader.McpToolDefinition(
        tool_code="image", name="image_generate", description="Generate an image.",
        required_capabilities=frozenset(), function=image_mcp.generate_image,
    )
    wrapper = mcp_loader._wrap_tool(definition, McpToolContext(agent_id=17, runtime=runtime))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    server = FastMCP("image-failure-regression")
    server.tool(name="image_generate")(wrapper)
    async with Client(server) as client:
        result = await client.call_tool("image_generate", {
            "prompt": "Chaumière", "width": 640, "height": 480,
            "destination": "nextcloud://chaumiere.png",
        }, raise_on_error=False)
    assert result.is_error
    message = str(result.content)
    assert "SVG/code artwork" in message
    assert "explicit user approval" in message
    assert "secret-value" not in message
    if isinstance(failure, ImageDimensionsError):
        assert "no usable configuration" in message
    store.assert_not_awaited()
    effects.assert_not_awaited()
