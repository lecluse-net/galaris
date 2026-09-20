from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from core.preview import thumbnails

from app.browser import service as browser_service
from app.browser.schemas import (
    BrowserContent,
    BrowserScreenshot,
    BrowserScreenshotPart,
)
from app.browser.service import (
    BrowserExecutor,
    BrowserExecutorError,
    capture_html_page_thumbnail,
    capture_public_page_thumbnail,
    validate_http_url_shape,
)


def _jpeg_bytes(size: tuple[int, int] = (320, 240)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "#5b7fa3").save(output, format="JPEG", quality=80)
    return output.getvalue()


def test_url_shape_accepts_only_http_without_credentials() -> None:
    assert validate_http_url_shape("https://example.com/path") == (
        "https://example.com/path"
    )
    assert validate_http_url_shape("http://localhost:5173/preview") == (
        "http://localhost:5173/preview"
    )
    assert validate_http_url_shape("http://tool.internal/preview") == (
        "http://tool.internal/preview"
    )
    assert validate_http_url_shape("http://10.1.2.3/preview") == (
        "http://10.1.2.3/preview"
    )
    for value in (
        "",
        "file:///etc/passwd",
        "https://user:secret@example.com",
        "https://example.com:99999",
    ):
        with pytest.raises(BrowserExecutorError) as error:
            validate_http_url_shape(value)
        assert error.value.code == "invalid_url"


@pytest.mark.asyncio
async def test_existing_executor_sends_current_preferences_and_timeout(monkeypatch):
    from core.params import runtime_settings
    calls = []
    async def handler(request):
        calls.append((json.loads(request.content)['settings'], request.extensions['timeout']['read']))
        return httpx.Response(200, json={'session_id': 'session', 'closed': True})
    executor = BrowserExecutor(transport=httpx.MockTransport(handler))
    for width, timeout in [(800, 10.0), (1200, 25.0)]:
        monkeypatch.setattr(runtime_settings, 'BROWSER_VIEWPORT_WIDTH', width)
        monkeypatch.setattr(runtime_settings, 'BROWSER_EXECUTOR_TIMEOUT_SECONDS', timeout)
        monkeypatch.setattr(runtime_settings, 'BROWSER_SESSION_TTL_SECONDS', int(timeout * 10))
        monkeypatch.setattr(runtime_settings, 'BROWSER_MAX_SESSIONS', int(timeout))
        await executor.close(agent_id=7, task_id=None, session_id='session')
        assert calls[-1][0]['viewport_width'] == width
        assert calls[-1][0]['session_ttl_seconds'] == int(timeout * 10)
        assert calls[-1][0]['max_sessions'] == int(timeout)
        assert calls[-1][1] == timeout


@pytest.mark.asyncio
async def test_executor_sends_owner_and_authentication() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-galaris-browser-token"] == "0123456789abcdef"
        body = json.loads(request.content)
        assert body["owner"] == {"agent_id": 7, "task_id": "task-9"}
        assert body["viewport_width"] == 390
        assert body["viewport_height"] == 844
        return httpx.Response(
            200,
            json={
                "session_id": "session-1",
                "url": "https://example.com/",
                "title": "Example",
                "revision": 1,
                "content": "- heading \"Example\"",
                "start": 0,
                "end": 19,
                "total": 19,
                "truncated": False,
                "next_offset": None,
            },
        )

    executor = BrowserExecutor(
        base_url="http://executor.test",
        token="0123456789abcdef",
        transport=httpx.MockTransport(handler),
    )
    result = await executor.open(
        agent_id=7,
        task_id="task-9",
        url="https://example.com/",
        output="content",
        viewport_width=390,
        viewport_height=844,
    )

    assert isinstance(result, BrowserContent)
    assert result.session_id == "session-1"


@pytest.mark.asyncio
async def test_executor_sends_viewport_when_resizing_for_screenshot() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["action"] == "screenshot"
        assert body["viewport_width"] == 390
        assert body["viewport_height"] == 844
        return httpx.Response(
            200,
            json={
                "session_id": "session-mobile",
                "url": "https://example.com/",
                "title": "Example",
                "revision": 2,
                "page_width": 390,
                "page_height": 1_200,
                "captured_height": 1_200,
                "truncated": False,
                "parts": [],
            },
        )

    executor = BrowserExecutor(
        base_url="http://executor.test",
        token="0123456789abcdef",
        transport=httpx.MockTransport(handler),
    )

    result = await executor.action(
        agent_id=7,
        task_id="task-9",
        session_id="session-mobile",
        action="screenshot",
        output="screenshot",
        viewport_width=390,
        viewport_height=844,
    )

    assert isinstance(result, BrowserScreenshot)


@pytest.mark.asyncio
async def test_executor_rejects_viewport_outside_policy_before_request() -> None:
    executor = BrowserExecutor(
        base_url="http://executor.test",
        token="0123456789abcdef",
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("The executor request must not be sent")
        ),
    )

    with pytest.raises(BrowserExecutorError) as error:
        await executor.open(
            agent_id=7,
            task_id="task-9",
            url="https://example.com/",
            output="content",
            viewport_width=319,
        )

    assert error.value.code == "invalid_viewport"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, expected", [
    ({"error": {"code": "blocked_url", "message": "sensitive detail"}}, "blocked_url"),
    ({"error": {"code": "unauthorized", "message": "sensitive detail"}}, "unauthorized"),
    ({"error": {"code": "https://private.invalid/?token=SECRET", "message": "sensitive detail"}}, "executor_failed"),
    ({"error": {"code": {"token": "SECRET"}}}, "executor_failed"),
    ([{"token": "SECRET"}], "executor_failed"),
    (None, "executor_failed"),
])
async def test_executor_exposes_only_stable_remote_error_code(payload, expected) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            403,
            json=payload,
        )
    )
    executor = BrowserExecutor(
        base_url="http://executor.test",
        token="0123456789abcdef",
        transport=transport,
    )

    with pytest.raises(BrowserExecutorError) as error:
        await executor.open(
            agent_id=1,
            task_id=None,
            url="https://example.com/",
            output="content",
        )

    assert error.value.code == expected
    assert error.value.status_code == 403
    assert "SECRET" not in str(error.value)
    assert "sensitive detail" not in str(error.value)


@pytest.mark.asyncio
async def test_executor_can_close_every_session_owned_by_a_run() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/close-owner"
        assert json.loads(request.content)["owner"] == {
            "agent_id": 7,
            "task_id": "task-9",
        }
        return httpx.Response(200, json={"closed": 2})

    executor = BrowserExecutor(
        base_url="http://executor.test",
        token="0123456789abcdef",
        transport=httpx.MockTransport(handler),
    )

    result = await executor.close_owner(agent_id=7, task_id="task-9")

    assert result.closed == 2


@pytest.mark.asyncio
async def test_executor_sends_private_html_as_bounded_base64() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/render-html"
        body = json.loads(request.content)
        assert body["owner"] == {"agent_id": 7, "task_id": None}
        assert base64.b64decode(body["html_base64"]) == b"<h1>Private page</h1>"
        return httpx.Response(
            200,
            json={
                "session_id": "session-html",
                "url": "about:blank",
                "title": "",
                "revision": 1,
                "page_width": 1_440,
                "page_height": 900,
                "captured_height": 900,
                "truncated": False,
                "parts": [],
            },
        )

    executor = BrowserExecutor(
        base_url="http://executor.test",
        token="0123456789abcdef",
        transport=httpx.MockTransport(handler),
    )

    result = await executor.render_html(
        agent_id=7,
        task_id=None,
        content=b"<h1>Private page</h1>",
    )

    assert result.session_id == "session-html"


@pytest.mark.asyncio
async def test_page_thumbnail_is_cached_under_the_canonical_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    url = "https://example.com/page?q=thumbnail"
    generated_jpeg = _jpeg_bytes()
    screenshot = BrowserScreenshot(
        session_id="session-thumbnail",
        url=url,
        title="Example",
        description="Site description",
        site_name="Publisher",
        revision=1,
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
                data=base64.b64encode(generated_jpeg).decode("ascii"),
            )
        ],
    )
    open_call = AsyncMock(return_value=screenshot)
    close_call = AsyncMock()
    monkeypatch.setattr(
        type(browser_service.settings),
        "GALARIS_THUMBNAIL_ROOT",
        str(tmp_path),
    )
    monkeypatch.setattr(browser_service.browser_executor, "open", open_call)
    monkeypatch.setattr(browser_service.browser_executor, "close", close_call)

    first = await capture_public_page_thumbnail(agent_id=7, url=url)
    second = await capture_public_page_thumbnail(agent_id=7, url=url)

    generated_png = thumbnails.from_image(BytesIO(generated_jpeg))
    assert first == (generated_png, "image/png")
    assert second == first
    cached = thumbnails.cache_path(url)
    assert cached.read_bytes() == generated_png
    assert cached.stat().st_mode & 0o777 == 0o644
    metadata = await browser_service.read_cached_page_metadata(reference=url)
    assert metadata is not None
    assert metadata.description == "Site description"
    assert metadata.site_name == "Publisher"
    open_call.assert_awaited_once_with(
        agent_id=7,
        task_id=None,
        url=url,
        output="screenshot",
        image_format="jpeg",
        max_width=1_440,
        max_height=900,
    )
    close_call.assert_awaited_once_with(
        agent_id=7,
        task_id=None,
        session_id="session-thumbnail",
    )


@pytest.mark.asyncio
async def test_private_html_thumbnail_is_cached_under_the_canonical_uri(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    uri = "console://reports/private.html"
    private_jpeg = _jpeg_bytes()
    screenshot = BrowserScreenshot(
        session_id="session-private-html",
        url="about:blank",
        title="Private",
        revision=1,
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
                data=base64.b64encode(private_jpeg).decode("ascii"),
            )
        ],
    )
    render_call = AsyncMock(return_value=screenshot)
    close_call = AsyncMock()
    monkeypatch.setattr(
        type(browser_service.settings),
        "GALARIS_THUMBNAIL_ROOT",
        str(tmp_path),
    )
    monkeypatch.setattr(browser_service.browser_executor, "render_html", render_call)
    monkeypatch.setattr(browser_service.browser_executor, "close", close_call)

    result = await capture_html_page_thumbnail(
        agent_id=7,
        reference=uri,
        content=b"<h1>Private</h1>",
    )

    private_png = thumbnails.from_image(BytesIO(private_jpeg))
    assert result == (private_png, "image/png")
    cached = thumbnails.cache_path(uri)
    assert cached.read_bytes() == private_png
    assert cached.stat().st_mode & 0o777 == 0o644
    render_call.assert_awaited_once_with(
        agent_id=7,
        task_id=None,
        content=b"<h1>Private</h1>",
        max_width=1_440,
        max_height=900,
    )
    close_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_thumbnail_bytes_are_constrained_to_shared_bounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    url = "https://example.com/oversized"
    oversized = _jpeg_bytes((1_440, 900))
    screenshot = BrowserScreenshot(
        session_id="session-oversized",
        url=url,
        title="Oversized",
        revision=1,
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
                data=base64.b64encode(oversized).decode("ascii"),
            )
        ],
    )
    monkeypatch.setattr(
        type(browser_service.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path)
    )
    monkeypatch.setattr(browser_service.browser_executor, "open", AsyncMock(return_value=screenshot))
    monkeypatch.setattr(browser_service.browser_executor, "close", AsyncMock())

    result = await capture_public_page_thumbnail(agent_id=7, url=url)

    assert result is not None
    with Image.open(BytesIO(result[0])) as image:
        assert image.size == (512, 320)
        assert image.format == "PNG"
    assert result[1] == "image/png"


@pytest.mark.asyncio
async def test_page_thumbnail_generation_is_backgrounded_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    captures = 0

    async def capture(**_kwargs: object) -> tuple[bytes, str]:
        nonlocal captures
        captures += 1
        started.set()
        await release.wait()
        return b"jpeg", "image/jpeg"

    browser_service._thumbnail_tasks.clear()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(browser_service, "capture_public_page_thumbnail", capture)

    browser_service.schedule_public_page_thumbnail(
        agent_id=7,
        url="https://example.com/background",
    )
    browser_service.schedule_public_page_thumbnail(
        agent_id=7,
        url="https://example.com/background",
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    assert captures == 1
    release.set()
    tasks = tuple(browser_service._thumbnail_tasks.values())  # pyright: ignore[reportPrivateUsage]
    await asyncio.gather(*tasks)
