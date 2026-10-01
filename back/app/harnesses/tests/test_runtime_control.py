"""Human waiting keeps one actor; transport loss and restart cannot replay a write."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from uuid import uuid4

import pytest

from app.harnesses.runtime_support import ActionApprovals, RuntimeRuns, file_precondition


@pytest.fixture
def approval_server():
    state = {"decision": "pending", "calls": [], "receipts": [], "id": str(uuid4())}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/receipt"):
                state["receipts"].append(body)
                response = {"recorded": True}
            else:
                state["calls"].append(body)
                claimed = state["decision"] == "executing" and not state.get("already_claimed")
                if claimed:
                    state["already_claimed"] = True
                    if state.get("lose_claim_reply"):
                        self.close_connection = True
                        return
                response = {"status": state["decision"], "request_id": state["id"], "claimed": claimed}
            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/mcp/synthetic", state
    server.shutdown()
    server.server_close()
    thread.join()


def eventually(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("The bounded runtime transition did not occur")


@pytest.mark.parametrize("allowed", [True, False])
def test_runtime_keeps_the_exact_pending_call_and_never_restarts_it(tmp_path, approval_server, allowed):
    url, server = approval_server
    target = tmp_path / "target.txt"
    target.write_text("before")
    runs = RuntimeRuns(tmp_path / "journal")
    launched = []
    async def events(actor):
        launched.append(actor.identifier)
        actor.approvals = ActionApprovals(mcp_url=url, token="synthetic", run_context="issued-context",
            session=actor.identifier, on_pending=actor.pending, on_running=actor.running)
        arguments = {"path": "target.txt", "content": "after"}
        permit = await asyncio.to_thread(actor.approvals.authorize, "call-1", "write", arguments,
            precondition=lambda: file_precondition(arguments, tmp_path))
        if permit:
            target.write_text("after")
            actor.approvals.finish("call-1", outcome="completed", receipt={"written": True})
        yield "result", {"success": True, "result": "written" if permit else "refused"}
    identifier = runs.start("issued-context", {"objective": "synthetic"}, events)
    eventually(lambda: runs.get(identifier)["status"] == "waiting_for_authorization")
    assert target.read_text() == "before"
    assert runs.get(identifier)["authorization_requests"] == [server["id"]]
    assert runs.start("issued-context", {"objective": "synthetic"}, events) == identifier
    assert len(launched) == 1
    with pytest.raises(PermissionError):
        runs.start("issued-context", {"objective": "changed"}, events)
    server["decision"] = "executing" if allowed else "denied"
    eventually(lambda: runs.get(identifier)["status"] == "completed")
    assert target.read_text() == ("after" if allowed else "before")
    assert len(server["receipts"]) == int(allowed)
    assert all(call == server["calls"][0] for call in server["calls"])
    restarted = RuntimeRuns(tmp_path / "journal")
    assert restarted.start("issued-context", {"objective": "synthetic"}, events) == identifier
    assert restarted.get(identifier)["status"] == "completed"
    assert len(launched) == 1


def test_unfinished_runtime_journal_is_unknown_after_restart_and_never_replays(tmp_path):
    runs = RuntimeRuns(tmp_path / "journal")
    admitted = threading.Event()
    effects = []
    async def events(actor):
        admitted.set()
        while True:
            await asyncio.sleep(0.01)
            if actor.state.get("stop_test"):
                break
        effects.append("one effect")
        yield "result", {"success": True}
    identifier = runs.start("context", {}, events)
    assert admitted.wait(2)
    restarted = RuntimeRuns(tmp_path / "journal")
    assert restarted.start("context", {}, events) == identifier
    assert restarted.get(identifier)["status"] == "outcome_unknown"
    assert effects == []
    runs.cancel(identifier)
    eventually(lambda: runs.get(identifier).get("stopped"))
    assert effects == []


def test_parallel_authorizations_keep_the_actor_waiting_for_remaining_actions(tmp_path):
    from app.harnesses.runtime_support import RuntimeActor
    actor = RuntimeActor("synthetic", tmp_path / "actor.json", "synthetic")
    actor.approvals = ActionApprovals(mcp_url="http://example.test/mcp/synthetic", token="synthetic",
        run_context="issued-context", session=actor.identifier, on_pending=actor.pending, on_running=actor.running)
    actor.approvals._pending("first")
    actor.approvals._pending("second")
    actor.approvals._running("first")
    assert actor.snapshot()["status"] == "waiting_for_authorization"
    assert actor.snapshot()["authorization_requests"] == ["second"]
    actor.approvals._running("second")
    assert actor.snapshot()["status"] == "running"
    assert actor.snapshot()["authorization_requests"] == []


def test_lost_claim_reply_does_not_treat_an_existing_dispatch_as_a_new_permit(approval_server):
    url, server = approval_server
    server.update(decision="executing", lose_claim_reply=True)
    collector = ActionApprovals(mcp_url=url, token="synthetic", run_context="issued-context",
        session="synthetic", on_pending=lambda _identifier: None)
    assert collector.authorize("same-callback", "write", {"content": "synthetic"}) is False
    assert len(server["calls"]) == 2
    assert collector.permits == {} and server["receipts"] == []
