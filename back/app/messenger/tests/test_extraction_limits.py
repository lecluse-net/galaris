import asyncio
import io
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter

from app.messenger import ingest
from app.messenger import pdf_extract


def test_raw_cache_is_bounded_by_bytes_and_does_not_retain_oversized_entries(monkeypatch):
    monkeypatch.setattr(ingest, "_CACHE_MAX_BYTES", 10)
    cache = OrderedDict()
    ingest._cache_put(cache, "one", b"123456")
    ingest._cache_put(cache, "two", b"123456")
    assert list(cache) == ["two"]
    ingest._cache_put(cache, "huge", b"x" * 11)
    assert list(cache) == ["two"]


def test_pdf_stops_extracting_when_text_budget_is_full(monkeypatch):
    import pypdf
    def pages():
        yield SimpleNamespace(extract_text=lambda: "x" * 30_000)
        pytest.fail("must not read further pages once budget is consumed")
    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(pages=pages()))
    assert len(pdf_extract.extract_pdf_text(b"fake")) == 20_000


@pytest.mark.asyncio
async def test_pdf_worker_runs_in_separate_process(monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    data = io.BytesIO()
    writer.write(data)
    monkeypatch.setattr(ingest, "fetch_bytes", AsyncMock(return_value=data.getvalue()))
    attachment = SimpleNamespace(size_bytes=len(data.getvalue()), name="blank.pdf", kind="document", mime_type="application/pdf", external_identifier="test")
    progress = 0
    async def heartbeat():
        nonlocal progress
        while True:
            progress += 1
            await asyncio.sleep(0.001)
    task = asyncio.create_task(heartbeat())
    try:
        result = await ingest._extract_pdf(SimpleNamespace(), attachment, "en")
        assert result
        assert progress > 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
