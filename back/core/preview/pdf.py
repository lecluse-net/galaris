"""Bounded static PDF rendering through the isolated Chromium service."""

import httpx

from core.settings import settings
from core.secrets import browser_executor_token
from core.util import post_buffered

PDF_HTML_MAX_BYTES = 12 * 1024 * 1024


class PdfRenderError(RuntimeError):
    """The isolated renderer could not produce a complete PDF."""


async def render_html_pdf(html: str, *, first_page_only: bool = False) -> bytes:
    """Render self-contained HTML without network access or document scripts."""
    if not html.strip() or len(html.encode("utf-8")) > PDF_HTML_MAX_BYTES:
        raise ValueError("PDF document is empty or exceeds the size limit")
    try:
        result = await post_buffered(
            f"{settings.BROWSER_EXECUTOR_URL}/v1/render-pdf",
            headers={"x-galaris-browser-token": browser_executor_token()},
            json={"html": html, "first_page_only": first_page_only},
            max_bytes=16 * 1024 * 1024,
            timeout=40,
        )
        if not result.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF response")
        return result
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        raise PdfRenderError("Unable to render the PDF document") from exc
