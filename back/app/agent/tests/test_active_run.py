from uuid import uuid4

from app.agent import active_run
from app.agent import get_current_task


def test_push_current_pop_cycle() -> None:
    agent = 42
    t1, t2 = uuid4(), uuid4()

    assert active_run.get_current_task(agent) is None
    assert active_run.current(agent) is None
    active_run.push(agent, t1)
    assert get_current_task(agent) == t1
    assert active_run.get_current_task(agent) == t1
    assert active_run.current(agent) == t1
    # Concurrent runs make an agent-only fallback ambiguous and therefore unavailable.
    active_run.push(agent, t2)
    assert active_run.get_current_task(agent) is None
    assert active_run.current(agent) is None
    active_run.pop(agent, t2)
    assert active_run.get_current_task(agent) == t1
    assert active_run.current(agent) == t1
    active_run.pop(agent, t1)
    assert active_run.get_current_task(agent) is None
    assert active_run.current(agent) is None


def test_push_none_agent_is_noop() -> None:
    active_run.push(None, uuid4())  # Does not raise.
    active_run.pop(None, uuid4())


def test_pop_unknown_is_safe() -> None:
    active_run.pop(999, uuid4())  # Does not raise.
    assert active_run.get_current_task(999) is None
    assert active_run.current(999) is None
