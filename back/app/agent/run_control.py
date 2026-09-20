"""Process-local driver ownership; durable Task leases remain the authority across workers."""

import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from collections.abc import Generator
from uuid import UUID

from .contracts import (
    AgentDriver, AgentRunRequest, DriverCancellationControl, HarnessCancellationReceipt,
)
from .execution_errors import HarnessProtocolError

_active: dict[UUID, tuple[AgentDriver, AgentRunRequest]] = {}
_receipts: OrderedDict[tuple[str, UUID], HarnessCancellationReceipt] = OrderedDict()
_pending: dict[tuple[str, UUID], asyncio.Task[HarnessCancellationReceipt]] = {}


def active_driver(driver_code: str, run_id: UUID) -> AgentDriver | None:
    active = _active.get(run_id)
    if active is None:
        return None
    if active[1].driver_code != driver_code:
        raise HarnessProtocolError("The active run belongs to a different driver.")
    return active[0]


@contextmanager
def own_run(driver: AgentDriver, request: AgentRunRequest) -> Generator[None]:
    if request.run_id in _active:
        raise HarnessProtocolError("This run is already active in this worker.")
    _receipts.pop((request.driver_code, request.run_id), None)
    _active[request.run_id] = (driver, request)
    try:
        yield
    finally:
        _active.pop(request.run_id, None)


async def request_cancellation(driver: AgentDriver, run_id: UUID) -> HarnessCancellationReceipt:
    key = (driver.spec.code, run_id)
    pending = _pending.get(key)
    if pending is None:
        pending = asyncio.create_task(_perform_cancellation(driver, run_id))
        _pending[key] = pending
        pending.add_done_callback(lambda _: _pending.pop(key, None))
    return await asyncio.shield(pending)


async def _perform_cancellation(driver: AgentDriver, run_id: UUID) -> HarnessCancellationReceipt:
    key = (driver.spec.code, run_id)
    cached = _receipts.get(key)
    if cached is not None and (cached.state == "confirmed" or (
        cached.state == "requested" and not isinstance(driver, DriverCancellationControl)
    )):
        return cached
    active = _active.get(run_id)
    timeout = driver.spec.stream_close_timeout_seconds
    if active is not None:
        driver, request = active
        if request.driver_code != key[0]:
            raise HarnessProtocolError("The active run belongs to a different driver.")
        descriptor = request.target.descriptor if request.target is not None else None
        if descriptor is not None:
            if "cancellation" not in descriptor.effective:
                raise HarnessProtocolError("Cancellation is disabled for this run.")
            timeout = min(timeout, descriptor.policy.stream_close_timeout_seconds)
    try:
        async with asyncio.timeout(timeout):
            if isinstance(driver, DriverCancellationControl):
                receipt = await driver.request_cancellation(run_id)
                receipt = HarnessCancellationReceipt.model_validate(receipt.model_dump())
                if receipt.run_id != run_id:
                    raise HarnessProtocolError("Cancellation acknowledged a different run.")
            else:
                await driver.cancel(run_id)
                receipt = HarnessCancellationReceipt(run_id=run_id, scope="remote", state="requested")
    except HarnessProtocolError:
        raise
    except Exception:
        # A lost reply cannot prove that a remote effect stopped.
        receipt = HarnessCancellationReceipt(run_id=run_id, scope="remote", state="unknown")
    _receipts[key] = receipt
    while len(_receipts) > 1024:
        _receipts.popitem(last=False)
    return receipt
