"""Run inside a real Harness image against a deterministic loopback model service.

No Galaris credentials, Docker socket, production mounts or external network are used.
The actual installed SDK/binary executes the turn; only the model provider is replaced.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ANSWER = "qualification-ok"
calls: list[str] = []
gate: dict[str, Any] = {}


class ModelService(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send(self, payload: object) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def events(self, events: list[tuple[str | None, object]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for name, payload in events:
            if name:
                self.wfile.write(f"event: {name}\n".encode())
            data = payload if isinstance(payload, str) else json.dumps(payload)
            self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def do_GET(self) -> None:
        if self.path.endswith("/runtime-authorizations/context"):
            self.send({"active": True})
        elif "/runtime-authorizations/" in self.path:
            self.send({"status": gate.get("decision", "pending")})
        elif self.path.endswith("/models"):
            self.send({"object": "list", "data": [{"id": "qualification", "object": "model"}]})
        else:
            self.send_error(405)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        calls.append(self.path)
        if "/tools/runtime-authorizations" in self.path:
            if self.path.endswith("/receipt"):
                gate.setdefault("receipts", []).append(body)
                self.send({"recorded": True})
            else:
                gate.setdefault("requests", []).append(body)
                self.send({"status": gate.get("decision", "pending"), "claimed": gate.get("decision") == "executing",
                    "request_id": "00000000-0000-0000-0000-000000000001"})
            return
        if self.path == "/mcp" or self.path.startswith("/mcp/"):
            method = body.get("method")
            if "id" not in body:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            result: dict[str, Any]
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "qualification", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": []}
            elif method == "tools/call" and gate.get("managed_mcp"):
                parameters = body.get("params", {})
                metadata = parameters.get("_meta", {})
                gate.setdefault("mcp_requests", []).append(parameters)
                if not metadata.get("galaris.authorization/v1", {}).get("continuation"):
                    result = {"content": [], "isError": True, "_meta": {"galaris.authorization/v1": {
                        "disposition": "authorization_required", "request_id": "00000000-0000-0000-0000-000000000001",
                        "continuation": "synthetic-exact-continuation"}}}
                elif gate.get("decision") == "approved":
                    Path(gate["path"]).write_text("approved")
                    result = {"content": [{"type": "text", "text": "written"}], "isError": False}
                else:
                    result = {"content": [{"type": "text", "text": "denied"}], "isError": True}
            else:
                result = {}
            self.send({"jsonrpc": "2.0", "id": body.get("id"), "result": result})
            return
        if "count_tokens" in self.path:
            self.send({"input_tokens": 10})
            return
        if "/responses" in self.path:
            item: dict[str, Any] = {"id": "msg_qualification", "type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": ANSWER, "annotations": []}]}
            response: dict[str, Any] = {"id": "resp_qualification", "object": "response", "created_at": int(time.time()),
                        "status": "completed", "model": "qualification", "output": [item],
                        "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}
            if gate and not gate.get("model_dispatched"):
                gate["model_dispatched"] = True
                tools = body.get("tools", [])
                names = [tool.get("name") or tool.get("function", {}).get("name") for tool in tools]
                name = next((name for name in names if name in {"exec_command", "shell_command", "shell"}), None)
                assert name, names
                args: dict[str, Any] = {"cmd": f"printf approved > {gate['path']}", "workdir": "/workspace", "max_output_tokens": 100,
                    "sandbox_permissions": "require_escalated", "justification": "Synthetic approval qualification"}
                if name == "shell_command":
                    args["command"] = args.pop("cmd")
                elif name == "shell":
                    args["command"] = ["sh", "-c", args.pop("cmd")]
                item = {"id": "fc_qualification", "type": "function_call", "call_id": "call_qualification", "name": name,
                    "arguments": json.dumps(args), "status": "completed"}
                response["output"] = [item]
                self.events([
                    ("response.created", {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}}),
                    ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": {**item, "arguments": ""}}),
                    ("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": item["id"], "output_index": 0, "delta": item["arguments"]}),
                    ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
                    ("response.completed", {"type": "response.completed", "response": response}),
                ])
                return
            if not body.get("stream"):
                self.send(response)
                return
            types: list[tuple[str, dict[str, Any]]] = [
                ("response.created", {"response": {**response, "status": "in_progress", "output": []}}),
                ("response.output_item.added", {"output_index": 0, "item": {**item, "status": "in_progress", "content": []}}),
                ("response.content_part.added", {"item_id": item["id"], "output_index": 0, "content_index": 0,
                                                 "part": {"type": "output_text", "text": "", "annotations": []}}),
                ("response.output_text.delta", {"item_id": item["id"], "output_index": 0, "content_index": 0, "delta": ANSWER}),
                ("response.output_text.done", {"item_id": item["id"], "output_index": 0, "content_index": 0, "text": ANSWER}),
                ("response.output_item.done", {"output_index": 0, "item": item}),
                ("response.completed", {"response": response}),
            ]
            self.events([(kind, {"type": kind, "sequence_number": i, **payload}) for i, (kind, payload) in enumerate(types)])
        elif "/messages" in self.path:
            message = {"id": "msg_qualification", "type": "message", "role": "assistant", "model": body.get("model"),
                       "content": [{"type": "text", "text": ANSWER}], "stop_reason": "end_turn", "stop_sequence": None,
                       "usage": {"input_tokens": 10, "output_tokens": 2}}
            if gate and not gate.get("model_dispatched") and any(tool.get("name") == "Write" for tool in body.get("tools", [])):
                gate["model_dispatched"] = True
                item = {"type": "tool_use", "id": "call_qualification", "name": "Write", "input": {"file_path": gate["path"], "content": "approved"}}
                message.update(content=[item], stop_reason="tool_use")
                if body.get("stream"):
                    self.events([
                        ("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}}),
                        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {**item, "input": {}}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": json.dumps(item["input"])}}),
                        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 2}}),
                        ("message_stop", {"type": "message_stop"}),
                    ])
                else:
                    self.send(message)
                return
            if not body.get("stream"):
                self.send(message)
                return
            self.events([
                ("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ANSWER}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}}),
                ("message_stop", {"type": "message_stop"}),
            ])
        elif "/chat/completions" in self.path:
            base = {"id": "chatcmpl-qualification", "created": int(time.time()), "model": body.get("model"),
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
            if gate and not gate.get("model_dispatched"):
                tools = body.get("tools", [])
                selected = next((tool["function"] for tool in tools if "write" in str(tool.get("function", {}).get("name", "")).lower()
                    and any("path" in key.lower() for key in tool.get("function", {}).get("parameters", {}).get("properties", {}))), None)
                assert selected, [tool.get("function", {}).get("name") for tool in tools]
                properties = selected.get("parameters", {}).get("properties", {})
                path_key = next((key for key in properties if "path" in key.lower()), "path")
                content_key = next((key for key in properties if "content" in key.lower()), "content")
                arguments = {path_key: gate["path"], content_key: "approved"}
                item = {"id": "call_qualification", "type": "function", "function": {"name": selected["name"], "arguments": json.dumps(arguments)}}
                gate["model_dispatched"] = True
                if body.get("stream"):
                    self.events([(None, {**base, "object": "chat.completion.chunk", "choices": [{"index": 0,
                        "delta": {"role": "assistant", "tool_calls": [{"index": 0, **item}]}, "finish_reason": None}]}),
                        (None, {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}), (None, "[DONE]")])
                else:
                    self.send({**base, "object": "chat.completion", "choices": [{"index": 0,
                        "message": {"role": "assistant", "content": None, "tool_calls": [item]}, "finish_reason": "tool_calls"}]})
                return
            if body.get("stream"):
                self.events([
                    (None, {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ANSWER}, "finish_reason": None}]}),
                    (None, {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                    (None, "[DONE]"),
                ])
            else:
                self.send({**base, "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": ANSWER}, "finish_reason": "stop"}]})
        else:
            self.send_error(404)


def module_from_file(path: str) -> Any:
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("qualification_adapter", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


async def qualify_hermes_managed(origin: str) -> None:
    """Exercise the real SDK's native and MCP boundaries with the run-bound collector."""
    from types import SimpleNamespace
    authorization = importlib.import_module("galaris_authorization")
    handlers = importlib.import_module("tools.mcp_tool_handlers")
    for mcp_call in (False, True):
        for allowed in (False, True):
            gate.clear()
            target = Path(f"/workspace/hermes-managed-{mcp_call}-{allowed}.txt")
            gate.update(path=str(target), requests=[], receipts=[], managed_mcp=mcp_call)
            loop = asyncio.get_running_loop()
            statuses: list[dict[str, Any]] = []
            events: list[dict[str, Any]] = []
            def set_status(run_id: str, status: str, _statuses: list[dict[str, Any]] = statuses, **fields: Any) -> None:
                _statuses.append({"status": status, **fields})
            host = SimpleNamespace(_galaris_authorization_loops={"managed": loop}, _set_run_status=set_status)
            run = SimpleNamespace(galaris_run_context="issued-synthetic-context", run_id="managed", put_event=events.append)
            def work(host: Any = host, run: Any = run, mcp_call: bool = mcp_call, target: Path = target) -> Any:
                token = authorization.bind_run(host, run)
                try:
                    if mcp_call:
                        # The actual SDK helper must use the opaque Galaris continuation.
                        return asyncio.run(handlers._call_tool_racing_stdio_death(
                            SimpleNamespace(session=None), "galaris", "synthetic_write", {"path": str(target), "content": "approved"}))
                    writer = importlib.import_module("run_agent").AIAgent(
                        base_url=origin + "/v1", api_key="qualification-token", provider="custom", api_mode="chat_completions",
                        model="qualification", max_iterations=3, enabled_toolsets=["file"], quiet_mode=True,
                        skip_context_files=True, skip_memory=True, skip_background_review=True)
                    return writer.run_conversation("Perform the synthetic write, then reply qualification-ok")
                finally:
                    authorization.reset_run(token)
            worker = asyncio.create_task(asyncio.to_thread(work))
            async with asyncio.timeout(25):
                while not events:
                    if worker.done():
                        await worker
                        raise AssertionError("Hermes completed without publishing its exact pending authorization")
                    await asyncio.sleep(0.02)
                assert not target.exists(), "Managed Hermes executed before agreement"
                assert statuses[-1]["status"] == "waiting_for_authorization"
                gate["decision"] = ("approved" if mcp_call else "executing") if allowed else "denied"
                result = await worker
            assert target.exists() is allowed
            if allowed:
                assert target.read_text() == "approved"
            assert statuses[-1]["status"] == "running"
            if mcp_call:
                requests = gate["mcp_requests"]
                assert len(requests) == 2 and requests[0]["arguments"] == requests[1]["arguments"]
                assert requests[0]["_meta"]["galaris.execution/v1"] == requests[1]["_meta"]["galaris.execution/v1"]
                assert result.is_error is (not allowed)
            else:
                assert ANSWER in json.dumps(result)
                assert len(gate["receipts"]) == int(allowed)
            print(f"PASS Hermes managed {'MCP continuation' if mcp_call else 'SDK local write'}: {'approved' if allowed else 'denied'}")


async def http_adapter(runtime: str) -> None:
    import socket
    import urllib.error
    import urllib.request

    uvicorn = importlib.import_module("uvicorn")

    root = Path("/opt/codex-harness" if runtime == "codex" else "/opt/claude-agent")
    sys.path.insert(0, str(root))
    module = module_from_file(str(root / "server.py"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 8787 if runtime == "codex" else 8642))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(module.app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started, "Adapter did not become ready"
        try:
            for streaming, authorized in ((False, False), (False, True), (True, True)):
                body = {"model": "qualification", "stream": streaming, "messages": [{"role": "user", "content": "Reply qualification-ok"}]}
                headers = {"Content-Type": "application/json"}
                if authorized:
                    headers["Authorization"] = "Bearer qualification-token"
                request = urllib.request.Request(origin + "/v1/chat/completions", data=json.dumps(body).encode(), headers=headers)
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        text = response.read().decode()
                        assert authorized and response.status == 200, text[:2000]
                        assert ANSWER in text, text[:2000]
                        if streaming:
                            assert text.count("data: [DONE]") == 1, text[:2000]
                except urllib.error.HTTPError as exc:
                    assert not authorized and exc.code == 401, exc.read().decode()[:2000]
            for allowed in (False, True):
                gate.clear()
                target = Path("/workspace" if runtime == "codex" else "/data/workspace") / f"approval-{allowed}.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                gate.update(path=str(target), decision="pending", requests=[], receipts=[])
                headers = {"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
                    "X-Galaris-Run-Context": f"synthetic-context-{allowed}"}
                request = urllib.request.Request(origin + "/v1/galaris/runs", data=json.dumps({"model": "qualification",
                    "messages": [{"role": "user", "content": "Perform the synthetic write, then reply qualification-ok"}]}).encode(), headers=headers)
                with urllib.request.urlopen(request, timeout=10) as response:
                    identifier = json.load(response)["runtime_run_id"]
                status_url = origin + "/v1/galaris/runs/" + identifier
                deadline = time.monotonic() + 25
                while not gate["requests"] and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
                assert gate["requests"], f"{runtime} did not intercept its actual SDK write"
                assert not target.exists(), "The SDK effect happened before approval"
                with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                    status = json.load(response)
                assert status["status"] == "waiting_for_authorization", status
                gate["decision"] = "executing" if allowed else "denied"
                while time.monotonic() < deadline:
                    with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                        status = json.load(response)
                    if status["status"] in {"completed", "outcome_unknown"}:
                        break
                    await asyncio.sleep(0.05)
                assert status["status"] == "completed", status
                assert target.exists() is allowed, (allowed, status)
                if allowed:
                    assert target.read_text() == "approved"
                    assert len(gate["receipts"]) == 1, gate["receipts"]
                assert all(item == gate["requests"][0] for item in gate["requests"]), "The approved SDK arguments changed"
                print(json.dumps({"runtime": runtime, "authorization": "allow" if allowed else "deny", "effect": target.exists()}))
                gate.clear()
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def main() -> None:
    signal.alarm(90)
    runtime = sys.argv[1]
    Path.home().mkdir(parents=True, exist_ok=True)
    Path("/data/skills").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelService)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    os.environ.update({
        "GALARIS_LLM_URL": origin + "/v1", "GALARIS_MCP_URL": origin + "/mcp/qualification",
        "GALARIS_MCP_TOKEN": "qualification-token", "HARNESS_API_TOKEN": "qualification-token",
        "CLAUDE_AGENT_API_TOKEN": "qualification-token", "ANTHROPIC_API_KEY": "qualification-token",
        "ANTHROPIC_BASE_URL": origin, "ANTHROPIC_AUTH_TOKEN": "qualification-token",
        "DEEPSEEK_API_KEY": "qualification-token", "DEEPSEEK_BASE_URL": origin,
        "HARNESS_MODEL": "qualification", "HERMES_HOME": "/tmp/hermes",
    })
    if runtime in {"codex", "claude_agent"}:
        asyncio.run(http_adapter(runtime))
    elif runtime == "hermes":
        cancellation_probe = module_from_file("/probe_hermes_cancellation.py")
        asyncio.run(cancellation_probe.qualify())
        agent = importlib.import_module("run_agent").AIAgent(
            base_url=origin + "/v1", api_key="qualification-token", provider="custom", api_mode="chat_completions",
            model="qualification", max_iterations=2, enabled_toolsets=[], quiet_mode=True,
            skip_context_files=True, skip_memory=True, skip_background_review=True,
        )
        result = agent.run_conversation("Reply qualification-ok")
        assert ANSWER in json.dumps(result), str(result)[:2000]
        # The pinned dispatcher, file tool, collector and model transport are real.
        # Only the responsible human's once/deny decision is synthetic.
        approvals = importlib.import_module("tools.approval")
        approval_context = importlib.import_module("tools.approval_context")
        os.environ.update(TERMINAL_CWD="/workspace", TERMINAL_ENV="local", HERMES_WRITE_SAFE_ROOT="/workspace")
        for allowed in (False, True):
            gate.clear()
            target = Path(f"/workspace/hermes-approval-{allowed}.txt")
            gate.update(path=str(target), requests=[], receipts=[])
            session = f"qualification-hermes-{allowed}"
            errors: list[BaseException] = []
            results: list[Any] = []
            def notified(data: dict[str, Any]) -> None:
                gate["requests"].append(data)
            def work(session: str = session, results: list[Any] = results, errors: list[BaseException] = errors) -> None:
                token = approval_context.set_current_session_key(session)
                approvals.register_gateway_notify(session, notified)
                try:
                    writer = importlib.import_module("run_agent").AIAgent(
                        base_url=origin + "/v1", api_key="qualification-token", provider="custom", api_mode="chat_completions",
                        model="qualification", max_iterations=3, enabled_toolsets=["file"], quiet_mode=True,
                        skip_context_files=True, skip_memory=True, skip_background_review=True,
                    )
                    result = writer.run_conversation("Perform the synthetic write, then reply qualification-ok")
                    results.append(result)
                    assert ANSWER in json.dumps(result), str(result)[:2000]
                except BaseException as error:
                    errors.append(error)
                finally:
                    approvals.unregister_gateway_notify(session)
                    approval_context.reset_current_session_key(token)
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            deadline = time.monotonic() + 25
            while not gate["requests"] and not errors and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not errors, errors
            assert gate["requests"], "The actual Hermes SDK did not intercept its write"
            assert not target.exists(), "The Hermes effect happened before agreement"
            approval = gate["requests"][0]
            assert approval["arguments_fingerprint"] and approval["arguments"], approval
            assert approval["allow_session"] is False and approval["allow_permanent"] is False
            assert approvals.resolve_gateway_approval(session, "once", request_id="obsolete-callback") == 0
            assert not target.exists()
            assert approvals.resolve_gateway_approval(session, "once" if allowed else "deny", request_id=approval["request_id"]) == 1
            worker.join(max(0.0, deadline - time.monotonic()))
            assert not worker.is_alive() and not errors, errors
            assert target.exists() is allowed, f"Hermes did not honor the exact human decision: {json.dumps(results)[:6000]}"
            if allowed:
                assert target.read_text() == "approved"
            assert len(gate["requests"]) == 1, "The SDK asked again after common one-action authorization"
            print(f"PASS Hermes real SDK local write: {'approved' if allowed else 'denied'}")
        asyncio.run(qualify_hermes_managed(origin))
    elif runtime == "deepseek_harness":
        sys.path.insert(0, "/opt/galaris")
        module = module_from_file("/opt/galaris/runtime_adapter.py")
        result = module.run_completion(
            {"model": "qualification", "messages": [{"role": "user", "content": "Reply qualification-ok"}]},
            module.AdapterConfig.from_environment(),
        )
        assert result.content == ANSWER, result
        assert "/mcp/qualification" in calls, "The runtime did not load the Galaris MCP connection"
        assert "/chat/completions" in calls, calls
        assert not any("/messages" in path for path in calls), calls
        config = module.AdapterConfig.from_environment()
        config.workspace.mkdir(parents=True, exist_ok=True)
        adapter_server = module.HarnessHTTPServer(("127.0.0.1", 8080), config)
        adapter_thread = threading.Thread(target=adapter_server.serve_forever, daemon=True)
        adapter_thread.start()
        import urllib.request
        try:
            for allowed in (False, True):
                gate.clear()
                target = config.workspace / f"approval-{allowed}.txt"
                gate.update(path=str(target), decision="pending", requests=[], receipts=[])
                headers = {"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
                    "X-Galaris-Run-Context": f"synthetic-context-{allowed}"}
                request = urllib.request.Request("http://127.0.0.1:8080/v1/galaris/runs", headers=headers,
                    data=json.dumps({"model": "qualification", "messages": [{"role": "user", "content": "Perform the synthetic write, then reply qualification-ok"}]}).encode())
                with urllib.request.urlopen(request, timeout=10) as response:
                    identifier = json.load(response)["runtime_run_id"]
                deadline = time.monotonic() + 25
                while not gate["requests"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert gate["requests"], "The actual DeepSeek SDK did not intercept its write"
                assert not target.exists(), "The DeepSeek effect happened before agreement"
                assert adapter_server.runs.get(identifier)["status"] == "waiting_for_authorization"
                gate["decision"] = "executing" if allowed else "denied"
                status = adapter_server.runs.get(identifier)
                while time.monotonic() < deadline:
                    status = adapter_server.runs.get(identifier)
                    if status["status"] in {"completed", "failed", "outcome_unknown"}:
                        break
                    time.sleep(0.05)
                assert status["status"] == "completed", status
                assert target.exists() is allowed, (allowed, status)
                if allowed:
                    assert target.read_text() == "approved" and len(gate["receipts"]) == 1
                print(json.dumps({"runtime": runtime, "authorization": "allow" if allowed else "deny", "effect": target.exists()}))
                gate.clear()
        finally:
            adapter_server.shutdown()
            adapter_server.server_close()
            adapter_thread.join(timeout=5)
    else:
        raise ValueError(runtime)
    assert any(path.endswith(("/responses", "/chat/completions")) or "/messages" in path for path in calls), calls
    print(json.dumps({"runtime": runtime, "status": "passed", "model_requests": len(calls)}))
    server.shutdown()


if __name__ == "__main__":
    main()
