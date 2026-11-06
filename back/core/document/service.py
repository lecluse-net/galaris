"""Run conversions outside the API event loop, with cancellation and resource limits."""

import asyncio
from pathlib import Path
import sys

from .contracts import PreparedDocument

_slots = asyncio.Semaphore(2)


async def prepare_document(
    path: Path, name: str, media_type: str, directory: Path,
    *, preview_only: bool = False, editable: bool = False,
) -> PreparedDocument:
    """Prepare LLM evidence, a thumbnail, or editable HTML and its extracted media."""
    if preview_only and editable:
        raise ValueError("Preview and editable preparation are separate modes")
    async with _slots:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "core.document.worker", str(path), name,
            media_type, str(directory), *(["preview"] if preview_only else ["editable"] if editable else []),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        try:
            async with asyncio.timeout(120 if preview_only else 1200):
                output, _ = await process.communicate()
            if process.returncode != 0:
                raise ValueError("Document preparation failed; format, encryption or conversion limits")
            return PreparedDocument.model_validate_json(output)
        except TimeoutError as error:
            raise ValueError("Document preparation exceeded its time budget") from error
        finally:
            import os
            import signal

            # Reap converter descendants too, even when the worker exited first.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.returncode is None:
                await process.wait()
