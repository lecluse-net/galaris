from unittest.mock import AsyncMock

import pytest

from core.preview import PdfRenderError, render_html_pdf
from core.preview import pdf


@pytest.mark.asyncio
async def test_pdf_transport_rejects_invalid_output_and_oversized_input(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = AsyncMock(return_value=b"<html>Error</html>")
    monkeypatch.setattr(pdf, "post_buffered", transport)
    with pytest.raises(PdfRenderError):
        await render_html_pdf("<p>Document</p>")
    transport.return_value = b"%PDF-1.7\ncontent"
    assert await render_html_pdf("<p>Document</p>") == transport.return_value
    assert transport.call_args.kwargs["json"]["first_page_only"] is False
    await render_html_pdf("<p>Document</p>", first_page_only=True)
    assert transport.call_args.kwargs["json"]["first_page_only"] is True
    transport.reset_mock()
    with pytest.raises(ValueError):
        await render_html_pdf("é" * (pdf.PDF_HTML_MAX_BYTES // 2 + 1))
    transport.assert_not_awaited()
