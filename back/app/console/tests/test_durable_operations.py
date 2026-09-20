"""Real-process crash tests for at-most-once console dispatch and durable receipts."""

import json
import os
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

HELPER = Path(__file__).parents[1] / "assets" / "galaris-exec"


@pytest.fixture
def operation():
    run_id = str(uuid4())
    with tempfile.TemporaryDirectory(prefix="console-proof-", dir=Path.home()) as work:
        yield run_id, Path(work)
    session = Path.home() / ".galaris" / "sessions" / run_id
    if session.exists():
        subprocess.run(
            [sys.executable, str(HELPER), "stop", "--run-id", run_id], capture_output=True
        )
        shutil.rmtree(session)


def invoke(*args):
    result = subprocess.run(
        [sys.executable, str(HELPER), *args], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def terminal(run_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = invoke("poll", "--run-id", run_id)
        if result["status"] != "running":
            return result
        time.sleep(0.03)
    raise AssertionError("Command never produced its durable result")


def test_concurrent_duplicate_dispatch_and_lost_ack_execute_once(operation):
    run_id, work = operation
    args = (
        "start",
        "--run-id",
        run_id,
        "--cwd",
        str(work),
        "--",
        "printf x >> effect; printf result",
    )
    with ThreadPoolExecutor(max_workers=5) as pool:
        replies = list(pool.map(lambda _: invoke(*args), range(5)))
    assert {reply["run_id"] for reply in replies} == {run_id}
    result = terminal(run_id)
    assert result["status"] == "completed"
    assert result["stdout"] == "result"
    assert (work / "effect").read_text() == "x"
    assert invoke(*args)["stdout"] == "result"
    assert (work / "effect").read_text() == "x"
    conflict = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "start",
            "--run-id",
            run_id,
            "--cwd",
            str(work),
            "--",
            "printf y >> effect",
        ],
        capture_output=True,
    )
    assert conflict.returncode != 0
    assert (work / "effect").read_text() == "x"


def test_launcher_killed_after_intent_is_recovered_without_duplicate(operation):
    run_id, work = operation
    script = "import runpy,sys,os; module=runpy.run_path(sys.argv.pop(1)); module['start'].__globals__['_launch_supervisor']=lambda _: os._exit(42); module['main']()"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(HELPER),
            "start",
            "--run-id",
            run_id,
            "--cwd",
            str(work),
            "--",
            "printf x >> effect",
        ],
        capture_output=True,
    )
    assert result.returncode == 42
    assert not (work / "effect").exists()
    assert terminal(run_id)["status"] == "completed"
    assert (work / "effect").read_text() == "x"


def test_supervisor_killed_after_effect_never_reexecutes_unknown_work(operation):
    run_id, work = operation
    args = ("start", "--run-id", run_id, "--cwd", str(work), "--", "printf x >> effect; sleep 60")
    invoke(*args)
    deadline = time.monotonic() + 10
    while not (work / "effect").exists() and time.monotonic() < deadline:
        time.sleep(0.03)
    assert (work / "effect").read_text() == "x"
    metadata = json.loads(
        (Path.home() / ".galaris" / "sessions" / run_id / "metadata.json").read_text()
    )
    os.killpg(metadata["pid"], signal.SIGKILL)
    assert terminal(run_id)["status"] == "outcome_unknown"
    assert invoke(*args)["status"] == "outcome_unknown"
    assert (work / "effect").read_text() == "x"


@pytest.mark.parametrize("command,code", [("exit 7", 7), ("exec /bin/false", 1)])
def test_shell_exit_and_exec_preserve_terminal_receipt(operation, command, code):
    run_id, work = operation
    invoke("start", "--run-id", run_id, "--cwd", str(work), "--", command)
    result = terminal(run_id)
    assert result["status"] == "failed"
    assert result["exit_code"] == code
    assert invoke("stop", "--run-id", run_id) == result


def test_control_characters_in_both_streams_fit_in_the_ssh_envelope(operation):
    run_id, work = operation
    program = "import os; os.write(1, bytes(65536)); os.write(2, bytes(65536))"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}"
    invoke("start", "--run-id", run_id, "--cwd", str(work), "--", command)
    result = terminal(run_id)
    assert result["status"] == "completed"
    assert result["stdout_truncated"] and result["stderr_truncated"]
    assert len(json.dumps(result).encode()) < 512 * 1024
    following = invoke("poll", "--run-id", run_id, "--cursor", str(result["cursor"]))
    assert len(result["stdout"] + following["stdout"]) == 65536
    assert len(result["stderr"] + following["stderr"]) == 65536
