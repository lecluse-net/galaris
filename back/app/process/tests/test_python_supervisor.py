"""Recovery contracts at the Docker boundary of the separate Python runner."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize("lose_docker_replies", [False, True])
def test_cancel_reconciles_after_docker_remains_unavailable_across_retries(tmp_path, monkeypatch, lose_docker_replies):
    source = Path(__file__).resolve().parents[4] / "process-runner/supervisor.py"
    spec = spec_from_file_location("process_python_supervisor_test", source)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    identity = str(uuid4())
    name = f"galaris-python-{identity}"
    created = Event()
    release_creation = Event()
    prolonged_outage = Event()
    docker_ready = Event()
    removed = Event()
    calls = []
    failures = 0
    payload = {"phase": "activity", "source": "output = {}", "values": {}, "handles": {}}

    def docker(*args):
        nonlocal failures
        calls.append(args[:2])
        result = ""
        if args[0] == "info":
            result = '{"runsc": {}}'
        elif args[:2] == ("container", "create"):
            created.set()
            assert release_creation.wait(5)
            if lose_docker_replies:
                raise subprocess.TimeoutExpired(args, 10)
        elif args[:2] == ("container", "ls") and created.is_set():
            if not docker_ready.is_set():
                failures += 1
                if failures == 3:
                    prolonged_outage.set()
                raise subprocess.CalledProcessError(1, args)
            if not removed.is_set():
                result = name
        elif args[:2] == ("container", "rm"):
            assert args[2:] == ("--force", name)
            removed.set()
            if lose_docker_replies:
                raise subprocess.TimeoutExpired(args, 10)
        return SimpleNamespace(stdout=result)

    def wait_before_retry(_delay):
        if prolonged_outage.is_set():
            assert docker_ready.wait(5)

    monkeypatch.setattr(module, "docker", docker)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=time.time, sleep=wait_before_retry))
    supervisor = module.Supervisor("sandbox@sha256:" + "a" * 64, tmp_path)
    assert not supervisor.submit(identity, payload)["stopped"]
    try:
        assert created.wait(5)
        assert not supervisor.cancel(identity)["stopped"]
        release_creation.set()
        assert prolonged_outage.wait(5)
        assert not supervisor.observe(identity)["stopped"]
    finally:
        release_creation.set()
        docker_ready.set()

    deadline = time.monotonic() + 2
    receipt = supervisor.observe(identity)
    while not receipt["stopped"] and time.monotonic() < deadline:
        time.sleep(.01)
        receipt = supervisor.observe(identity)
    assert receipt == {"status": "cancelled", "stopped": True}
    assert supervisor.submit(identity, payload) == receipt
    assert removed.is_set()
    assert calls.count(("container", "create")) == calls.count(("container", "rm")) == 1
