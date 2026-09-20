from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest
import httpx
from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from app.browser import mcp as browser_mcp
from app.browser.schemas import BrowserContent, BrowserScreenshot, BrowserScreenshotPart
from app.browser.service import BrowserExecutor
from app.tools.mcp_loader import (
    McpToolContext,
    add_galaris_tools,
    mcp_tool_names_by_tool_code,
)
from app.harness.run_control import RunResources


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["fr", "en"])
async def test_missing_session_never_replays_an_action_and_allows_explicit_reopening(monkeypatch, language):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/v1/action":
            return httpx.Response(404, json={"error": {"code": "session_not_found"}})
        return httpx.Response(200, json={"session_id": "new-session", "url": "https://example.org/",
            "title": "Public page", "revision": 1, "content": "Page reopened", "start": 0,
            "end": 13, "total": 13, "truncated": False, "next_offset": None})

    monkeypatch.setattr(browser_mcp, "browser_executor", BrowserExecutor(
        base_url="http://executor.test", token="synthetic-token", transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(browser_mcp, "context_language", AsyncMock(return_value=language))
    ctx = McpToolContext(agent_id=9, runtime="internal")
    failure = await browser_mcp.browser_press(ctx, "expired-session", "Enter", output="content")
    assert "session" in failure.lower()
    assert len(requests) == 1 and requests[0][0] == "/v1/action"
    result = await browser_mcp.browser_open(ctx, "https://example.org/", output="content")
    assert "new-session" in result and "Page reopened" in result
    assert [path for path, _ in requests] == ["/v1/action", "/v1/open"]
    assert all(payload['owner'] == {'agent_id': 9, 'task_id': None} for _, payload in requests)


def test_browser_native_tool_family_is_complete() -> None:
    assert set(mcp_tool_names_by_tool_code()["browser"]) == {
        "browser_open",
        "browser_navigate",
        "browser_content",
        "browser_screenshot",
        "browser_click",
        "browser_type",
        "browser_press",
        "browser_scroll",
        "browser_back",
        "browser_close",
    }


@pytest.mark.asyncio
async def test_browser_tool_schema_exposes_bounded_optional_viewport() -> None:
    mcp = FastMCP("test")
    add_galaris_tools(mcp, 1, runtime="internal", enabled_tool_codes={"browser"})

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert "local and private-network URLs" in (tools["browser_open"].description or "")
    screenshot_description = tools["browser_screenshot"].description or ""
    assert "browser_open with output='content'" in screenshot_description
    assert "browser_content to verify" in screenshot_description
    assert "session_not_found" in screenshot_description
    assert "1440x900" in screenshot_description
    assert "390x844" in screenshot_description
    assert "independently of local file storage" in screenshot_description
    assert "path=null" in screenshot_description
    for tool_name in ("browser_open", "browser_screenshot"):
        properties = tools[tool_name].parameters["properties"]
        width = next(
            option
            for option in properties["viewport_width"]["anyOf"]
            if option.get("type") == "integer"
        )
        height = next(
            option
            for option in properties["viewport_height"]["anyOf"]
            if option.get("type") == "integer"
        )
        assert width == {"maximum": 3_840, "minimum": 320, "type": "integer"}
        assert height == {"maximum": 2_160, "minimum": 240, "type": "integer"}


def test_content_output_includes_session_and_continuation() -> None:
    result = browser_mcp._content_text(  # pyright: ignore[reportPrivateUsage]
        browser_mcp.BrowserContent(
            session_id="session-1",
            url="https://example.com",
            title="Example",
            revision=2,
            content="- button \"Next\" [ref=e3]",
            start=0,
            end=24,
            total=48,
            truncated=True,
            next_offset=24,
        )
    )

    assert '"session_id": "session-1"' in result
    assert '"next_offset": 24' in result
    assert '[ref=e3]' in result


def test_context_keeps_task_owner_boundary() -> None:
    context = McpToolContext(agent_id=9, runtime="internal")
    assert context.agent_id == 9


@pytest.mark.asyncio
async def test_browser_open_registers_owner_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = RunResources()
    opened = BrowserContent(
        session_id="session-1",
        url="https://example.com",
        title="Example",
        revision=1,
        content="Example",
        start=0,
        end=7,
        total=7,
        truncated=False,
    )
    open_call = AsyncMock(return_value=opened)
    close_owner = AsyncMock()
    monkeypatch.setattr(browser_mcp.browser_executor, "open", open_call)
    monkeypatch.setattr(browser_mcp.browser_executor, "close_owner", close_owner)

    await browser_mcp.browser_open(
        McpToolContext(
            agent_id=9,
            runtime="internal",
            task_id=None,
            resources={"run": resources},
        ),
        "https://example.com",
        "content",
        390,
        844,
    )
    await resources.close()

    open_call.assert_awaited_once_with(
        agent_id=9,
        task_id=None,
        url="https://example.com",
        output="content",
        viewport_width=390,
        viewport_height=844,
    )
    close_owner.assert_awaited_once_with(agent_id=9, task_id=None)


@pytest.mark.asyncio
async def test_browser_screenshot_can_select_mobile_viewport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = BrowserScreenshot(
        session_id="session-mobile",
        url="https://example.com",
        title="Example",
        revision=2,
        page_width=390,
        page_height=1_200,
        captured_height=1_200,
        truncated=False,
        parts=[],
    )
    action_call = AsyncMock(return_value=screenshot)
    monkeypatch.setattr(browser_mcp.browser_executor, "action", action_call)

    result = await browser_mcp.browser_screenshot(
        McpToolContext(agent_id=9, runtime="internal", task_id="task-1"),
        "session-mobile",
        "png",
        390,
        844,
    )

    assert isinstance(result, ToolResult)
    action_call.assert_awaited_once_with(
        agent_id=9,
        task_id="task-1",
        session_id="session-mobile",
        action="screenshot",
        output="screenshot",
        image_format="png",
        viewport_width=390,
        viewport_height=844,
    )


@pytest.mark.asyncio
async def test_screenshot_returns_image_block_and_console_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def write_part(
        _ctx: McpToolContext,
        destination: str,
        data: bytes,
    ) -> str:
        assert destination.endswith("capture-r3-part-001.jpg")
        assert data == b"jpeg-bytes"
        return f"console://{destination}"

    monkeypatch.setattr(browser_mcp, "_write_part", write_part)
    screenshot = BrowserScreenshot(
        session_id="session-1",
        url="https://example.com",
        title="Example",
        revision=3,
        page_width=1_440,
        page_height=4_000,
        captured_height=3_000,
        truncated=True,
        parts=[
            BrowserScreenshotPart(
                index=0,
                y=0,
                width=1_440,
                height=3_000,
                mime_type="image/jpeg",
                data=base64.b64encode(b"jpeg-bytes").decode(),
            )
        ],
    )

    result = await browser_mcp._screenshot_result(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(
            agent_id=9,
            runtime="internal",
            resources={"console": object()},
        ),
        screenshot,
    )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.structured_content["truncated"] is True
    assert result.structured_content["parts"][0]["path"].endswith(
        "capture-r3-part-001.jpg"
    )


@pytest.mark.asyncio
async def test_screenshot_without_console_still_returns_image_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_part = AsyncMock()
    monkeypatch.setattr(browser_mcp, "_write_part", write_part)
    screenshot = BrowserScreenshot(
        session_id="session-1",
        url="https://example.com",
        title="Example",
        revision=3,
        page_width=1_440,
        page_height=900,
        captured_height=900,
        truncated=False,
        parts=[
            BrowserScreenshotPart(
                index=0,
                y=0,
                width=1_440,
                height=900,
                mime_type="image/jpeg",
                data=base64.b64encode(b"jpeg-bytes").decode(),
            )
        ],
    )

    result = await browser_mcp._screenshot_result(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(agent_id=9, runtime="internal"),
        screenshot,
    )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.structured_content["parts"][0]["path"] is None
    write_part.assert_not_awaited()


@pytest.mark.asyncio
async def test_screenshot_storage_failure_does_not_hide_captured_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_mcp,
        "_write_part",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    )
    screenshot = BrowserScreenshot(
        session_id="session-1",
        url="https://example.com",
        title="Example",
        revision=3,
        page_width=1_440,
        page_height=900,
        captured_height=900,
        truncated=False,
        parts=[
            BrowserScreenshotPart(
                index=0,
                y=0,
                width=1_440,
                height=900,
                mime_type="image/jpeg",
                data=base64.b64encode(b"jpeg-bytes").decode(),
            )
        ],
    )

    result = await browser_mcp._screenshot_result(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(
            agent_id=9,
            runtime="internal",
            resources={"console": object()},
        ),
        screenshot,
    )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.structured_content["parts"][0]["path"] is None


@pytest.mark.asyncio
async def test_screenshot_storage_defaults_to_console_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def create(
        _ctx: object,
        uri: object,
        data: bytes,
    ) -> object:
        captured.update(uri=uri, data=data)
        return type("Mutation", (), {"uri": str(uri)})()

    monkeypatch.setattr(browser_mcp, "resource_create", create)
    monkeypatch.setattr(
        browser_mcp,
        "context_language",
        AsyncMock(return_value="en"),
    )

    result = await browser_mcp._write_part(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(
            agent_id=9,
            runtime="internal",
            resources={"console": object()},
        ),
        "browser/session/capture.jpg",
        b"jpeg",
    )

    assert result == "console://browser/session/capture.jpg"
    assert captured == {
        "uri": "console://browser/session/capture.jpg",
        "data": b"jpeg",
    }
