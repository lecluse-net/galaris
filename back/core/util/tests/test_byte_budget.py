import asyncio
import pytest
from core.util import ByteBudget


@pytest.mark.asyncio
@pytest.mark.parametrize("size,children", [(0, 0), (-1, 0), (101, 0), (50, -1), (50, 51)])
async def test_invalid_admission_never_consumes_capacity(size, children):
    budget = ByteBudget(100)
    with pytest.raises(ValueError):
        async with budget.reserve(size, child_bytes=children, owner="invalid"):
            pytest.fail("Invalid buffer was admitted")
    assert budget.used == budget.active == 0 and not budget.owners
    async with budget.reserve(100, owner="valid"):
        assert budget.used == 100


@pytest.mark.asyncio
async def test_detached_child_can_reserve_normally_after_parent_has_finished():
    budget = ByteBudget(100, max_operations=1)
    resume = asyncio.Event()
    async def detached():
        await resume.wait()
        async with budget.reserve(100, owner="detached", timeout=1):
            assert budget.used == 100
    async with budget.reserve(40, child_bytes=60, owner="parent"):
        child = asyncio.create_task(detached())
    resume.set()
    await child
    assert budget.used == budget.active == 0 and not budget.owners


@pytest.mark.asyncio
async def test_byte_admission_limits_aggregate_and_releases_cancelled_operations():
    budget = ByteBudget(100, max_operations=2)
    entered = asyncio.Event()
    async def next_owner():
        async with budget.reserve(50, owner="second"):
            entered.set()
            await asyncio.Event().wait()
    async with budget.reserve(60, owner="first"):
        waiter = asyncio.create_task(next_owner())
        await asyncio.sleep(0)
        assert not entered.is_set() and budget.used == 60
    await asyncio.wait_for(entered.wait(), 1)
    assert budget.used == 50
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert budget.used == budget.active == 0
    async with budget.reserve(100, owner="third"):
        assert budget.used == 100


@pytest.mark.asyncio
async def test_owner_and_deadline_do_not_leak_reservations():
    budget = ByteBudget(100)
    async with budget.reserve(10, owner="one"):
        with pytest.raises(TimeoutError):
            async with budget.reserve(10, owner="one", timeout=0.01):
                pytest.fail("same owner entered twice")
        assert budget.used == 10 and budget.active == 1
    assert not budget.owners


@pytest.mark.asyncio
async def test_explicit_child_allowance_does_not_compete_for_parent_slot():
    budget = ByteBudget(100, max_operations=1)
    async with budget.reserve(40, child_bytes=60, owner="delivery"):
        assert budget.used == 100
        async with budget.reserve(60, owner="adapter", timeout=0.01):
            assert budget.used == 100 and budget.active == 1
        assert budget.used == 100
    assert budget.used == budget.active == 0


@pytest.mark.asyncio
async def test_child_cannot_exceed_its_reserved_allowance():
    budget = ByteBudget(100)
    async with budget.reserve(40, child_bytes=60, owner="parent"):
        with pytest.raises(TimeoutError):
            async with budget.reserve(61, owner="child", timeout=0.01):
                pytest.fail("Child exceeded its allocation")
    assert budget.used == 0


@pytest.mark.asyncio
async def test_cancelled_parent_keeps_child_bytes_reserved_until_child_finishes():
    budget = ByteBudget(100)
    entered, release = asyncio.Event(), asyncio.Event()

    async def child():
        async with budget.reserve(60, owner="child"):
            entered.set()
            await release.wait()

    async def parent():
        async with budget.reserve(40, child_bytes=60, owner="parent"):
            task = asyncio.create_task(child())
            await entered.wait()
            await asyncio.Event().wait()
        await task

    operation = asyncio.create_task(parent())
    await entered.wait()
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    await asyncio.sleep(0)
    assert budget.used == 100 and not operation.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert budget.used == budget.active == 0
