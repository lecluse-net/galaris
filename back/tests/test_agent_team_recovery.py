"""Validate the fault injector and its evidence, never script real agent replies."""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.agent_team_pilot.bootstrap import bootstrap
from tests.agent_team_pilot.evidence import assess
from tests.agent_team_pilot import runner


@pytest.mark.parametrize("changed", [None, "identity", "configuration", "manifest", "missing_marker"])
def test_restart_bootstrap_never_reseeds_or_accepts_another_run(tmp_path, changed):
    directory, storage = tmp_path / "artifacts", tmp_path / "data"
    directory.mkdir()
    storage.mkdir()
    calls = []
    def seed():
        calls.append(True)
        (directory / "manifest.json").write_text('{"room_id":"synthetic-room"}')
    config = {"model": "synthetic"}
    bootstrap(directory, storage, "one-run", config, seed)
    if changed == "identity":
        run = "another-run"
    else:
        run = "one-run"
    if changed == "configuration":
        config = {"model": "changed"}
    if changed == "manifest":
        (directory / "manifest.json").write_text('{"room_id":"another-room"}')
    if changed == "missing_marker":
        (storage / "team-pilot-bootstrap.json").unlink()
    if changed:
        with pytest.raises(RuntimeError):
            bootstrap(directory, storage, run, config, seed)
    else:
        bootstrap(directory, storage, run, config, seed)
        assert [json.loads(line)["seeded"] for line in (directory / "boots.jsonl").read_text().splitlines()] == [True, False]
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [False, True])
def test_host_injector_kills_only_its_backend_and_retains_restart_failure(tmp_path, failure):
    executable = tmp_path / "docker"
    executable.write_text(f"#!{sys.executable}\n" + '''import json,os,sys
from pathlib import Path
a=sys.argv[1:]; root=Path(os.environ["TEAM_PILOT_ARTIFACTS"])
with (root/"commands.jsonl").open("a") as f: f.write(json.dumps(a)+"\\n")
if a[0]=="inspect":
 backend=a[-1]=="a"*64; killed=(root/"killed").exists(); resumed=(root/"resumed").exists()
 print(json.dumps(dict(container=a[-1],pid=12 if backend and resumed else 0 if backend and killed else 11 if backend else 20,
   started_at="new" if backend and resumed else "old",status="exited" if backend and killed and not resumed else "running",exit_code=137 if backend and killed and not resumed else 0)))
elif "ps" in a: print(("a" if a[-1]=="backend" else "b")*64)
elif "kill" in a:
 assert a[-1]=="a"*64 and a[a.index("--signal")+1]=="KILL"
 (root/"killed").touch()
elif "up" in a:
 assert a[-1]=="backend" and "--no-deps" in a
 if os.environ["FAIL_START"]=="1": sys.exit(42)
 (root/"resumed").touch()
''')
    executable.chmod(0o755)
    script = Path(__file__).resolve().parents[2] / "bin/agent-team-pilot-restart.sh"
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TEAM_PILOT_RESTART": "1",
                   "TEAM_PILOT_ARTIFACTS": str(tmp_path), "FAIL_START": "1" if failure else "0"}
    prepared = subprocess.run(["bash", str(script), "--prepare", "galaris-team-pilot-synthetic"],
        env=environment, capture_output=True, text=True, timeout=10)
    assert prepared.returncode == 0 and not (tmp_path / "restart-receipt.json").exists()
    result = subprocess.run(["bash", str(script), "galaris-team-pilot-synthetic"],
        env=environment,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == (42 if failure else 0)
    receipt = json.loads((tmp_path / "restart-receipt.json").read_text())
    assert receipt["exit_status"] == result.returncode
    assert receipt["status"] == ("error" if failure else "ready")
    calls = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    assert sum("kill" in call for call in calls) == 1
    assert not any("down" in call or "stop" in call or "rm" in call for call in calls)
    if not failure:
        assert json.loads((tmp_path / "database-before.json").read_text()) == json.loads((tmp_path / "database-after.json").read_text())


@pytest.mark.asyncio
async def test_restart_wait_failure_is_not_reported_as_recovery(tmp_path):
    (tmp_path / "restart-receipt.json").write_text('{"status":"error","exit_status":42}')
    with pytest.raises(RuntimeError, match="restart failed"):
        await runner.await_restart(tmp_path)
    (tmp_path / "restart-receipt.json").unlink()
    with pytest.raises(RuntimeError, match="timeout"):
        await runner.await_restart(tmp_path, timeout=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("write_phase", [False, True])
async def test_observer_waits_for_durable_instruction_and_completed_work_before_restart(tmp_path, monkeypatch, write_phase):
    manifest = {"case": "amendment", "mode": "directed", "leader_id": 1, "peer_ids": [2, 3],
                "criteria": [], "run_id": "one-run", "restart_after_amendment": True, "executable": True,
                "room_id": "room", "document_ids": ["target"], "target_uri": "document://target",
                "amendment": "Synthetic update", "limits": {"timeout_seconds": 60}}
    if write_phase:
        manifest["restart_phase"] = "committed_write"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "_session.json").write_text('{"email":"synthetic@example.com","password":"synthetic-secret"}')
    (tmp_path / "submission.json").write_text('{"message":{"id":"original-message"}}')
    state = {"polls": 0, "submitted": 0, "restarted": 0, "logins": 0}
    def endpoint(request):
        path = request.url.path
        if path == "/api/auth/login-json":
            state["logins"] += 1
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        if path.endswith("/tasks"):
            state["polls"] += 1
            done = bool(state["restarted"])
            return httpx.Response(200, json={"total": 3, "items": [
                {"id": "root", "agent_id": 1, "status": "SUCCESS" if done else "EXEC"},
                {"id": "peer-a", "agent_id": 2, "parent_id": "root", "feedback": "Original analysis",
                 "status": "SUCCESS" if done or state["polls"] >= 2 else "EXEC"},
                {"id": "peer-b", "agent_id": 3, "parent_id": "root", "status": "SUCCESS" if done else "EXEC"}]})
        if request.method == "POST" and path.endswith("/messages"):
            state["submitted"] += 1
            return httpx.Response(200, json={"id": "accepted-amendment"})
        if path.endswith("/messages"):
            messages = [{"id": "original-message", "created_at": "2040-01-01T00:00:00Z"}]
            if state["restarted"]:
                messages.append({"id": "final-message", "created_at": "2040-01-01T00:00:03Z"})
            return httpx.Response(200, json={"total": len(messages), "items": messages})
        if path.endswith("/activity"):
            return httpx.Response(200, json={"total": 1, "items": [{"id": "round", "finished_at": "2040-01-01" if state["restarted"] else None}]})
        if path.endswith("/dataset"):
            return httpx.Response(200, json={"task_amendments": [{"id": "amendment", "applied_at": "2040-01-01T00:00:02Z" if state["restarted"] else None}],
                "task_links": [{"notification_state": "DELIVERED" if state["restarted"] else "PENDING", "notification_message_id": "final-message"}]})
        if path.endswith("/history"):
            return httpx.Response(200, json={"items": [{"id": "one-peer-call", "task_id": "peer-a"}], "total": 1})
        if path == "/api/llm-calls":
            assert request.url.params.get_list("task_ids") == ["peer-a"]
            return httpx.Response(200, json=[{"id": "one-peer-call", "task_id": "peer-a"}])
        if path == "/api/documents/target":
            return httpx.Response(200, json={"item": {"id": "target", "revision": 2 if write_phase else 1, "payload": {"text": "<p>Original</p>"}}})
        if path.endswith("/content-revisions"):
            return httpx.Response(200, json={"has_more": False, "items": [{"revision": 2 if write_phase else 1, "content_hash": "original"}]})
        if path.endswith("/documents"):
            return httpx.Response(200, json={"items": [], "total": 0})
        if path.endswith(("/full", "/budget", "/activity/round")):
            return httpx.Response(200, json={})
        raise AssertionError(f"Unexpected request {request.method} {path}")
    async def host_restart(directory, **_):
        assert state["submitted"] == 1 and not state["restarted"]
        assert (directory / "before-restart.json").exists()
        assert json.loads((directory / "before-restart.json").read_text())["documents"][0]["item"]["revision"] == (2 if write_phase else 1)
        request = json.loads((directory / "restart-request.json").read_text())
        assert request["pending_amendments"][0]["id"] == "amendment" and request["completed_peer_tasks"] == ["peer-a"]
        state["restarted"] += 1
        (directory / "boots.jsonl").write_text('{"seeded":true}\n{"seeded":false}\n')
        db = {"container": "database", "pid": 20}
        return {"status": "ready", "backend-before": {"container": "backend", "pid": 11, "started_at": "old"},
                "backend-after": {"container": "backend", "pid": 12, "started_at": "2040-01-01T00:00:01Z"},
                "backend-killed": {"exit_code": 137, "status": "exited"}, "database-before": db, "database-after": db}
    original = httpx.AsyncClient
    monkeypatch.setattr(runner.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(endpoint), **kwargs))
    monkeypatch.setattr(runner, "await_restart", host_restart)
    assert await runner.observe(tmp_path, "http://backend:8000") == 0
    result = json.loads((tmp_path / "assessment.json").read_text())
    assert result["restart_exercised"] and result["content_acceptance"] == "pending_human_review"
    assert result["recovery_observations"]["target_written_before_fault"] is write_phase
    assert result["recovery_observations"]["completed_peer_tasks_retained_without_new_model_calls"] == ["peer-a"]
    assert state["submitted"] == state["restarted"] == 1 and state["logins"] == 2


@pytest.mark.parametrize("missing", ["restart", "boots", "before-restart", "applied_before_fault"])
def test_success_states_do_not_invent_restart_or_preserved_work(missing):
    manifest = {"case": "amendment", "mode": "directed", "leader_id": 1, "peer_ids": [2, 3],
                "criteria": [], "restart_after_amendment": True}
    backend = {"container": "backend", "pid": 11, "started_at": "old"}
    db = {"container": "database", "pid": 20}
    evidence = {"termination": "completed", "amendment_sent": True, "tasks": [],
        "restart": {"backend-before": backend, "backend-after": {**backend, "pid": 12, "started_at": "new"},
                    "backend-killed": {"exit_code": 137, "status": "exited"}, "database-before": db, "database-after": db},
        "boots": [{"seeded": True}, {"seeded": False}],
        "restart_request": {"pending_amendments": [{"id": "amendment", "applied_at": None}]},
        "after-restart": {"round_inspections": [{"task_amendments": [{"id": "amendment", "applied_at": None}]}]},
        "before-restart": {"tasks": [{"id": "peer", "agent_id": 2, "status": "SUCCESS"}]}}
    assert assess(manifest, evidence)["restart_exercised"]
    if missing == "applied_before_fault":
        evidence["restart"]["backend-after"]["started_at"] = "2040-01-01T00:00:01Z"
        evidence["after-restart"]["round_inspections"][0]["task_amendments"][0]["applied_at"] = "2040-01-01T00:00:00Z"
    else:
        del evidence[missing]
    result = assess(manifest, evidence)
    assert not result["restart_exercised"] and not result["scenario_exercised"]
    assert result["content_acceptance"] == "pending_human_review"


@pytest.mark.parametrize("defect", [None, "lost_revision", "changed_hash", "delivered_before_restart"])
def test_committed_write_requires_its_original_revision_and_delivery_after_restart(defect):
    manifest = {"case": "amendment", "mode": "directed", "leader_id": 1, "peer_ids": [2, 3],
                "criteria": [], "restart_after_amendment": True, "restart_phase": "committed_write",
                "target_uri": "document://target"}
    revision = {"revision": 2, "content_hash": "synthetic-committed-content"}
    database = {"container": "database", "pid": 20}
    evidence = {"termination": "completed", "amendment_sent": True, "tasks": [],
        "restart": {"backend-before": {"container": "backend", "pid": 11, "started_at": "old"},
                    "backend-after": {"container": "backend", "pid": 12, "started_at": "2040-01-01T00:00:01Z"},
                    "backend-killed": {"exit_code": 137, "status": "exited"},
                    "database-before": database, "database-after": database},
        "boots": [{"seeded": True}, {"seeded": False}],
        "before-restart": {"documents": [{"item": {"id": "target", "revision": 2}}],
                           "document_revisions": {"target": [revision]}},
        "after-restart": {"document_revisions": {"target": [dict(revision)]}},
        "delivery_links": [{"notification_state": "DELIVERED", "notification_message_id": "final"}],
        "messages": [{"id": "final", "created_at": "2040-01-01T00:00:03Z"}]}
    if defect == "lost_revision":
        evidence["after-restart"]["document_revisions"]["target"] = []
    elif defect == "changed_hash":
        evidence["after-restart"]["document_revisions"]["target"][0]["content_hash"] = "changed"
    elif defect == "delivered_before_restart":
        evidence["messages"][0]["created_at"] = "2040-01-01T00:00:00Z"
    result = assess(manifest, evidence)
    assert result["restart_exercised"] is (defect is None)
    assert result["content_acceptance"] == "pending_human_review"
