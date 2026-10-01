"""Exercise the managed HTTP actor, replacing only the SDK and remote authority."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from bridge.deepseek_harness import runtime_adapter as runtime
from .test_runtime_adapter import _config


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("decision", ["allow", "deny", "revoke", "cancel"])
def test_managed_actor_keeps_native_authorization_and_cannot_replay(tmp_path, monkeypatch, decision):
    state = {"active": True, "decision": None, "receipts": [], "calls": 0}
    ready, proceed = threading.Event(), threading.Event()
    destination = tmp_path / "workspace" / "approved.txt"

    class Authority(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, payload, status=200):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            assert self.headers["X-Galaris-Run-Context"] == "server-issued-context"
            self.respond({"active": state["active"]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/receipt"):
                state["receipts"].append(body)
                self.respond({"recorded": True})
            elif "/mcp/" in self.path:
                self.respond({"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})
            elif state["decision"] is None:
                self.respond({"status": "pending", "request_id": "human-question"})
            elif state["decision"] == "allow":
                self.respond({"status": "executing", "request_id": "human-question", "claimed": True})
            else:
                self.respond({"status": "denied", "request_id": "human-question"})

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Authority)) as authority:
        monkeypatch.setenv("GALARIS_MCP_TOKEN", "synthetic-mcp-token")
        monkeypatch.setenv("GALARIS_MCP_URL", authority + "/api/mcp/synthetic")
        server = runtime.HarnessHTTPServer(("127.0.0.1", 0), _config(tmp_path))
        with serving(server) as base:
            class SDKBoundary:
                def __init__(self, **options):
                    self.environment = options["env"]

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def close(self):
                    proceed.set()

                def run(self, _prompt, *, session_id, on_notification):
                    state["calls"] += 1
                    assert self.environment["GALARIS_RUN_CONTEXT"] == "server-issued-context"
                    actor_id = self.environment["GALARIS_AUTHORIZATION_PROXY"].rsplit("/", 1)[1]
                    headers = {"Authorization": "Bearer synthetic-mcp-token",
                               "X-Galaris-Run-Context": "server-issued-context"}
                    ready.set()
                    assert proceed.wait(timeout=10)
                    with httpx.Client(base_url=base, timeout=15) as sdk:
                        context = sdk.post(f"/local/{actor_id}/context", headers=headers, json={})
                        if context.status_code == 409:
                            return SimpleNamespace(final_response="Stopped after revocation", finish_reason="completed")
                        assert context.json() == {"active": True}
                        assert sdk.post(f"/local/{actor_id}/context", headers={**headers,
                            "X-Galaris-Run-Context": "foreign-context"}, json={}).status_code == 409
                        allowed = sdk.post(f"/local/{actor_id}", headers=headers,
                            json={"callback": "original-call", "name": "file_write",
                                  "arguments": {"file_path": "approved.txt", "content": "approved"}}).json()["allowed"]
                        if allowed:
                            destination.write_text("approved", encoding="utf-8")
                            assert sdk.post(f"/local/{actor_id}/receipt", headers=headers,
                                json={"callback": "original-call", "outcome": "completed", "receipt": {"written": True}}).status_code == 200
                            assert sdk.post(f"/mcp/{actor_id}", headers=headers,
                                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200
                    on_notification(SimpleNamespace(method="session.event", payload={"event": {
                        "type": "assistant/chunk", "data": {"chunk": {"type": "text-delta", "text": "Finished"}}}}))
                    return SimpleNamespace(final_response="Finished", finish_reason="completed")

            monkeypatch.setattr(runtime, "_harness_factory", lambda: SDKBoundary)
            headers = {"Authorization": "Bearer secret", "X-Galaris-Run-Context": "server-issued-context"}
            payload = {"model": "executor-model", "messages": [{"role": "user", "content": "Prepare result"}]}
            with httpx.Client(base_url=base, timeout=15) as client:
                assert client.get("/healthz").status_code == 200
                assert client.get("/v1/models").status_code == 401
                assert client.get("/v1/models", headers=headers).json()["data"][0]["id"] == "executor-model"
                assert client.get("/v1/galaris/capabilities", headers=headers).json()["resumable_runs"] is True
                assert client.get("/v1/galaris/runs/unknown", headers=headers).status_code == 404
                assert client.post("/v1/galaris/runs", json=payload).status_code == 401
                assert client.post("/local/unknown/context", json={}).status_code == 401
                assert client.post("/v1/galaris/runs", headers=headers, content="broken").status_code == 409
                identifier = client.post("/v1/galaris/runs", headers=headers, json=payload).json()["runtime_run_id"]
                assert ready.wait(timeout=5)
                assert client.post("/local/unknown/context", headers={"Authorization": "Bearer synthetic-mcp-token"}, json={}).status_code == 409
                if decision == "revoke":
                    state["active"] = False
                proceed.set()
                endpoint = f"/v1/galaris/runs/{identifier}"
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    observed = client.get(endpoint, headers=headers).json()
                    if decision != "revoke" and observed["status"] == "waiting_for_authorization":
                        assert not destination.exists()
                        if decision == "cancel":
                            assert client.post(endpoint + "/cancel", headers=headers, json={}).status_code == 200
                        else:
                            state["decision"] = decision
                    if observed.get("stopped"):
                        break
                    time.sleep(0.02)
                assert observed.get("stopped"), observed
                assert destination.exists() is (decision == "allow")
                assert len(state["receipts"]) == (1 if decision == "allow" else 0)
                assert client.post("/v1/galaris/runs", headers=headers, json=payload).json()["runtime_run_id"] == identifier
                assert state["calls"] == 1
                assert client.post("/v1/galaris/runs", headers=headers,
                    json={**payload, "model": "changed"}).status_code == 409
