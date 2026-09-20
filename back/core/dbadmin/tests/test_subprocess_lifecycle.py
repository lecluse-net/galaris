import asyncio
import sys

import pytest

from core.dbadmin._internal.atlas import _communicate
from core import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_subprocess_is_reaped_on_timeout_and_cancellation(monkeypatch, cancel):
    monkeypatch.setattr(settings, "DBADMIN_COMMAND_TIMEOUT_SECONDS", 0.05 if not cancel else 30)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(60)",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    task = asyncio.create_task(_communicate(process))
    if cancel:
        await asyncio.sleep(0.01)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    assert process.returncode is not None
