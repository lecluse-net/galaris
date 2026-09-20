"""Background thumbnail orchestration for private Chat HTML resources."""

from __future__ import annotations

import asyncio
from contextvars import Context

from loguru import logger

from app.browser import BrowserExecutorError, capture_html_page_thumbnail
from app.messenger import materialize_preview_resource
from core.database import get_db_session
from core.params import runtime_settings


_tasks: dict[str, asyncio.Task[None]] = {}


async def _generate_html_thumbnail(*, agent_id: int, uri: str) -> None:
    # Background tasks must never reuse the request-scoped SQLAlchemy session.
    # Resource resolution may query connection settings, so give the detached
    # task its own short-lived database context.
    async with get_db_session():
        resource = await materialize_preview_resource(
            uri,
            agent_id=agent_id,
            max_bytes=runtime_settings.BROWSER_HTML_MAX_BYTES,
        )
    if resource is None:
        return
    try:
        content = await asyncio.to_thread(resource.path.read_bytes)
        await capture_html_page_thumbnail(
            agent_id=agent_id,
            reference=uri,
            content=content,
        )
    except BrowserExecutorError as exc:
        logger.debug("Private HTML thumbnail generation failed (code={})", exc.code)
    except Exception as exc:
        logger.warning(
            "Private HTML thumbnail generation failed (error_type={})",
            type(exc).__name__,
        )
    finally:
        resource.cleanup()


def schedule_html_thumbnail(*, agent_id: int, uri: str) -> None:
    """Start at most one private HTML capture per URI without blocking Chat."""

    if uri in _tasks:
        return
    task = asyncio.create_task(
        _generate_html_thumbnail(agent_id=agent_id, uri=uri),
        name="chat-private-html-thumbnail",
        context=Context(),
    )
    _tasks[uri] = task

    def forget(completed: asyncio.Task[None]) -> None:
        if _tasks.get(uri) is completed:
            _tasks.pop(uri, None)

    task.add_done_callback(forget)


__all__ = ["schedule_html_thumbnail"]
