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
        if self.path.endswith("/models"):
            self.send({"object": "list", "data": [{"id": "qualification", "object": "model"}]})
        else:
            self.send_error(405)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        calls.append(self.path)
        if self.path == "/mcp":
            method = body.get("method")
            result: dict[str, Any]
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "qualification", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": []}
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


async def http_adapter(runtime: str) -> None:
    import socket
    import urllib.error
    import urllib.request

    uvicorn = importlib.import_module("uvicorn")

    root = Path("/opt/codex-harness" if runtime == "codex" else "/opt/claude-agent")
    sys.path.insert(0, str(root))
    module = module_from_file(str(root / "server.py"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
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
        "GALARIS_LLM_URL": origin + "/v1", "GALARIS_MCP_URL": origin + "/mcp",
        "GALARIS_MCP_TOKEN": "qualification-token", "HARNESS_API_TOKEN": "qualification-token",
        "CLAUDE_AGENT_API_TOKEN": "qualification-token", "ANTHROPIC_API_KEY": "qualification-token",
        "ANTHROPIC_BASE_URL": origin, "ANTHROPIC_AUTH_TOKEN": "qualification-token",
        "DEEPSEEK_API_KEY": "qualification-token", "DEEPSEEK_BASE_URL": origin,
        "HARNESS_MODEL": "qualification", "HERMES_HOME": "/tmp/hermes",
    })
    if runtime in {"codex", "claude_agent"}:
        asyncio.run(http_adapter(runtime))
    elif runtime == "hermes":
        agent = importlib.import_module("run_agent").AIAgent(
            base_url=origin + "/v1", api_key="qualification-token", provider="custom", api_mode="chat_completions",
            model="qualification", max_iterations=2, enabled_toolsets=[], quiet_mode=True,
            skip_context_files=True, skip_memory=True, skip_background_review=True,
        )
        result = agent.run_conversation("Reply qualification-ok")
        assert ANSWER in json.dumps(result), str(result)[:2000]
    elif runtime == "deepseek_harness":
        module = module_from_file("/opt/galaris/runtime_adapter.py")
        result = module.run_completion(
            {"model": "qualification", "messages": [{"role": "user", "content": "Reply qualification-ok"}]},
            module.AdapterConfig.from_environment(),
        )
        assert result.content == ANSWER, result
        assert "/mcp" in calls, "The runtime did not load the Galaris MCP connection"
        assert "/chat/completions" in calls, calls
        assert not any("/messages" in path for path in calls), calls
    else:
        raise ValueError(runtime)
    assert any(path.endswith(("/responses", "/chat/completions")) or "/messages" in path for path in calls), calls
    print(json.dumps({"runtime": runtime, "status": "passed", "model_requests": len(calls)}))
    server.shutdown()


if __name__ == "__main__":
    main()
