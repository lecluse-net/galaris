"""Bounded PDF rasterization without OCR, inference, or persistent storage."""

import asyncio
import json
from pathlib import Path
import sys

from pydantic import BaseModel, Field
from core.util import complete_await

_slots = asyncio.Semaphore(2)


class PdfPageImage(BaseModel):
    page: int = Field(ge=1)
    page_count: int = Field(ge=1)
    width: int = Field(ge=1, le=3000)
    height: int = Field(ge=1, le=3000)


async def render_pdf_page(source: Path, destination: Path, *, page: int = 1) -> PdfPageImage:
    """Render exactly one page; drain the worker before callers remove temporaries."""
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive physical page number")
    async with _slots:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "core.document.pdf_page_worker", str(source), str(destination), str(page),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(60):
                output, _ = await process.communicate()
            if process.returncode != 0:
                try:
                    error = str(json.loads(output).get("error", ""))
                except (ValueError, TypeError, AttributeError):
                    error = ""
                raise ValueError(error or "PDF rendering failed; check format, encryption and rendering limits")
            return PdfPageImage.model_validate_json(output)
        except TimeoutError as error:
            raise ValueError("PDF rendering exceeded its time budget") from error
        finally:
            if process.returncode is None:
                process.kill()
            await complete_await(process.wait())
