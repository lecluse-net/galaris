from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.chat import thumbnail_service


@pytest.mark.asyncio
async def test_private_thumbnail_generation_uses_its_own_database_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entered = False
    resource = SimpleNamespace(path=tmp_path / "page.html", cleanup=lambda: None)
    resource.path.write_bytes(b"<h1>Preview</h1>")

    @asynccontextmanager
    async def database_context() -> AsyncIterator[None]:
        nonlocal entered
        entered = True
        yield

    materialize = AsyncMock(return_value=resource)
    capture = AsyncMock(return_value=(b"jpeg", "image/jpeg"))
    monkeypatch.setattr(thumbnail_service, "get_db_session", database_context)
    monkeypatch.setattr(thumbnail_service, "materialize_preview_resource", materialize)
    monkeypatch.setattr(thumbnail_service, "capture_html_page_thumbnail", capture)

    await thumbnail_service._generate_html_thumbnail(  # pyright: ignore[reportPrivateUsage]
        agent_id=7,
        uri="console://page.html",
    )

    assert entered is True
    materialize.assert_awaited_once()
    capture.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_thumbnail_task_does_not_inherit_request_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker: ContextVar[str] = ContextVar("thumbnail_test_marker", default="detached")
    observed = ""

    async def generate(**_kwargs: object) -> None:
        nonlocal observed
        observed = marker.get()

    thumbnail_service._tasks.clear()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(thumbnail_service, "_generate_html_thumbnail", generate)
    token = marker.set("request")
    try:
        thumbnail_service.schedule_html_thumbnail(agent_id=7, uri="console://page.html")
        tasks = tuple(thumbnail_service._tasks.values())  # pyright: ignore[reportPrivateUsage]
        await asyncio.gather(*tasks)
    finally:
        marker.reset(token)

    assert observed == "detached"
