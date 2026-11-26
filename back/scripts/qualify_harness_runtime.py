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
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

ANSWER = "qualification-ok"
calls: list[str] = []
gate: dict[str, Any] = {}


class ModelService(BaseHTTPRequestHandler):
    def message_answer(self, body: dict[str, Any]) -> str:
        return ANSWER

    def message_tool(self, body: dict[str, Any]) -> dict[str, Any] | None:
        return None

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
            self.send({"active": not (gate.get("read_revoked") and gate.get("model_dispatched"))})
        elif "/runtime-authorizations/" in self.path:
            self.send({"status": gate.get("decision", "pending")})
        elif self.path.endswith("/models"):
            self.send({"object": "list", "data": [{"id": "qualification", "object": "model"}]})
        else:
            self.send_error(405)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        calls.append(self.path)
        if ((deep_calls := gate.get("deep_model_calls")) is not None
                and self.path.partition("?")[0].endswith(("/messages", "/responses", "/chat/completions"))):
            deep_calls.append((self.headers.get("X-Galaris-Deep-Context"), body))
        if gate.get("hold_deep") and self.headers.get("X-Galaris-Deep-Context") == gate["hold_deep"]:
            gate["deep_arrived"].set()
            if not gate["deep_release"].wait(15):
                self.send_error(504)
                return
        if "/services/runtime-authorizations" in self.path:
            if self.path.endswith("/receipt"):
                gate.setdefault("receipts", []).append(body)
                self.send({"recorded": True})
            else:
                gate.setdefault("requests", []).append(body)
                # The runtime can observe the request before its HTTP response arrives.
                time.sleep(gate.get("authorization_response_delay", 0))
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
                result = {"tools": [{"name": "qualification_write" if gate.get("deepseek_mcp") else "qualification_echo",
                    "description": "Synthetic qualification tool", "inputSchema": {"type": "object", "properties": {
                        "path": {"type": "string"}, "content": {"type": "string"}} if gate.get("deepseek_mcp") else {}}}]}
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
                    gate["mcp_effects"] = gate.get("mcp_effects", 0) + 1
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
        if parallel := gate.get("parallel_contexts"):
            context = self.headers.get("X-Galaris-Run-Context")
            task = self.headers.get("X-Galaris-Task-Id")
            if task is None or context not in parallel or parallel[context] != task or task not in json.dumps(body):
                self.send_error(403, "Model request did not preserve its runtime identity")
                return
            with gate["parallel_lock"]:
                gate["parallel_seen"].add(context)
                if gate["parallel_seen"] == parallel.keys():
                    gate["parallel_arrived"].set()
            if not gate["parallel_arrived"].wait(25):
                self.send_error(504, "All model calls must be in flight together")
                return
        if "/chat/completions" in self.path and gate.get("network_recovery") and gate.get("model_dispatched"):
            if "Continue the current task from this session" not in json.dumps(body):
                gate["provider_failures"] = gate.get("provider_failures", 0) + 1
                encoded = json.dumps({"error": {"message": "Synthetic provider interruption", "type": "server_error"}}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            gate["continued"] = True
            gate["retained_tool_result"] = any(message.get("role") == "tool" for message in body.get("messages", []))
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
            answer = self.message_answer(body)
            message = {"id": "msg_qualification", "type": "message", "role": "assistant", "model": body.get("model"),
                       "content": [{"type": "text", "text": answer}], "stop_reason": "end_turn", "stop_sequence": None,
                       "usage": {"input_tokens": 10, "output_tokens": 2}}
            tool_use = self.message_tool(body)
            if gate and not gate.get("model_dispatched") and any(tool.get("name") == "Write" for tool in body.get("tools", [])):
                gate["model_dispatched"] = True
                tool_use = {"type": "tool_use", "id": "call_qualification", "name": "Write", "input": {"file_path": gate["path"], "content": "approved"}}
            if tool_use is not None:
                message.update(content=[tool_use], stop_reason="tool_use")
                if body.get("stream"):
                    self.events([
                        ("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}}),
                        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {**tool_use, "input": {}}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_use["input"])}}),
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
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": answer}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}}),
                ("message_stop", {"type": "message_stop"}),
            ])
        elif "/chat/completions" in self.path:
            base = {"id": "chatcmpl-qualification", "created": int(time.time()), "model": body.get("model"),
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
            if gate and not gate.get("model_dispatched"):
                tools = body.get("tools", [])
                gate["offered_tools"] = {tool["function"]["name"] for tool in tools}
                if gate.get("deepseek_mcp"):
                    tools = [tool for tool in tools if "mcp__galaris__" in str(tool.get("function", {}).get("name", ""))]
                selected = next((tool["function"] for tool in tools if (tool.get("function", {}).get("name") == "read"
                    if gate.get("native_read") else "write" in str(tool.get("function", {}).get("name", "")).lower())
                    and any("path" in key.lower() for key in tool.get("function", {}).get("parameters", {}).get("properties", {}))), None)
                assert selected, [tool.get("function", {}).get("name") for tool in tools]
                properties = selected.get("parameters", {}).get("properties", {})
                path_key = next((key for key in properties if "path" in key.lower()), "path")
                content_key = next((key for key in properties if "content" in key.lower()), "content")
                arguments = {path_key: gate["path"]} if gate.get("native_read") else {path_key: gate["path"], content_key: "approved"}
                gate["tool_call"] = {"name": selected["name"], "arguments": arguments}
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


async def qualify_parallel_runs(origin: str, runtime: str) -> None:
    import urllib.request

    parallel_contexts = {f"synthetic-parallel-{index}": str(uuid4()) for index in range(5)}
    gate.update(parallel_contexts=parallel_contexts, parallel_lock=threading.Lock(),
        parallel_seen=set(), parallel_arrived=threading.Event(), model_dispatched=True)

    async def run_parallel(context: str, task: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
            "X-Galaris-Run-Context": context, "X-Galaris-Task-Id": task}
        body = json.dumps({"model": "qualification", "messages": [
            {"role": "user", "content": f"For task {task}, reply qualification-ok"}]}).encode()

        def request_json(url: str, data: bytes | None = None) -> dict[str, Any]:
            request = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)

        url = origin + "/v1/galaris/runs"
        started = await asyncio.to_thread(request_json, url, body)
        status_url = url + "/" + started["runtime_run_id"]
        async with asyncio.timeout(45):
            while True:
                status = await asyncio.to_thread(request_json, status_url)
                if status.get("stopped") is True:
                    return status
                await asyncio.sleep(0.05)

    parallel_runs = await asyncio.gather(*(run_parallel(context, task)
        for context, task in parallel_contexts.items()))
    assert gate["parallel_seen"] == parallel_contexts.keys()
    assert all(run["status"] == "completed" and run["success"] is True for run in parallel_runs), parallel_runs
    print(f"PASS {runtime}: {len(parallel_contexts)} concurrent model calls retained their own run context")

    gate.clear()


async def qualify_deep_sessions(origin: str, runtime: str) -> None:
    import urllib.request

    contexts = {str(uuid4()): f"synthetic-deep-{index}" for index in range(5)}
    model_calls: list[tuple[str | None, dict[str, Any]]] = []
    gate.update(deep_model_calls=model_calls, model_dispatched=True)
    text = "Reply qualification-ok"
    follow_up = "Continue with qualification-ok"

    def profile(context: str) -> str:
        return f"<p>Synthetic Deep profile {context} with {{{{literal}}}} braces.</p>"

    def talk(session: str, context: str, native: str | None = None) -> str:
        headers = {"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
            "X-Galaris-Deep-Session": session, "X-Galaris-Deep-Context": context,
            "X-Galaris-Deep-Control": f"{context}-control"}
        if native is not None:
            headers["X-Galaris-Deep-Native-Session"] = native
        body = json.dumps({"model": "qualification", "stream": True, "messages": [
            {"role": "system", "content": profile(context)},
            {"role": "user", "content": follow_up if native else text}]}).encode()
        request = urllib.request.Request(origin + "/v1/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=45) as response:
            response_text = response.read().decode()
        assert ANSWER in response_text, response_text[:1200]
        reference = next((line for line in response_text.splitlines() if line.startswith('data: {"session"')), "")
        assert reference, "Deep runtime did not expose its native session reference"
        return str(json.loads(reference[6:])["session"])

    references = await asyncio.gather(*(asyncio.to_thread(talk, session, context)
        for session, context in contexts.items()))
    assert len(set(references)) == len(contexts)
    session, context = next(iter(contexts.items()))
    assert await asyncio.to_thread(talk, session, context, references[0]) == references[0]
    assert {context for context, _ in model_calls} == set(contexts.values())
    verified_prompts: set[tuple[str, str]] = set()
    for context, payload in model_calls:
        assert context is not None
        messages = payload.get("messages", payload.get("input", []))
        user_messages = [message["content"] for message in messages if message.get("role") == "user"]
        user_texts = [part for content in user_messages for part in (
            [content] if isinstance(content, str) else [block.get("text", "") for block in content]
        )]
        received = {text, follow_up}.intersection(user_texts)
        if not received:
            continue  # A native SDK may make its own ancillary call, for example to name a session.
        system = [payload.get("system"), payload.get("instructions"),
            *[message.get("content") for message in messages if message.get("role") in {"system", "developer"}]]
        assert profile(context) in json.dumps(system), (runtime, context)
        assert not any("the Galaris task" in item or "<galaris_message_context>" in item for item in user_texts)
        verified_prompts.update((context, message) for message in received)
    expected_prompts = {(context, text) for context in contexts.values()} | {(contexts[session], follow_up)}
    assert verified_prompts == expected_prompts, (runtime, verified_prompts)
    print(f"PASS {runtime}: five independent Deep sessions and native continuation")
    if runtime == "codex":
        hold, arrived, release = "synthetic-deep-live", threading.Event(), threading.Event()
        gate.update(hold_deep=hold, deep_arrived=arrived, deep_release=release)
        session = str(uuid4())
        active = asyncio.create_task(asyncio.to_thread(talk, session, hold))

        def steer() -> int:
            request = urllib.request.Request(origin + f"/v1/galaris/deep/{session}/steer",
                data=json.dumps({"text": "Continue with the synthetic check"}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
                    "X-Galaris-Deep-Control": f"{hold}-control"})
            with urllib.request.urlopen(request, timeout=10) as response:
                return int(response.status)

        try:
            assert await asyncio.to_thread(arrived.wait, 10)
            assert await asyncio.to_thread(steer) == 204
        finally:
            release.set()
            await active
        print("PASS Codex: the pinned SDK accepted a new instruction on an active Deep turn")
    gate.clear()


async def qualify_hermes_deep_scope(origin: str) -> None:
    from types import SimpleNamespace

    authorization = importlib.import_module("galaris_authorization")
    agent_class = importlib.import_module("run_agent").AIAgent
    model_calls: list[tuple[str | None, dict[str, Any]]] = []
    gate.update(deep_model_calls=model_calls, model_dispatched=True)
    loop = asyncio.get_running_loop()

    def talk(context: str) -> Any:
        host = SimpleNamespace(_galaris_authorization_loops={context: loop})
        run = SimpleNamespace(galaris_run_context="synthetic-deep-control", galaris_deep_context=context, run_id=context)
        token = authorization.bind_run(host, run)
        try:
            agent = agent_class(base_url=origin + "/llm/openai", api_key="qualification-token", provider="custom",
                api_mode="chat_completions", model="qualification", max_iterations=2, enabled_toolsets=[],
                quiet_mode=True, skip_context_files=True, skip_memory=True, skip_background_review=True)
            return agent.run_conversation("Reply qualification-ok")
        finally:
            authorization.reset_run(token)

    contexts = {"synthetic-hermes-one", "synthetic-hermes-two"}
    results = await asyncio.gather(*(asyncio.to_thread(talk, context) for context in contexts))
    assert all(ANSWER in json.dumps(result) for result in results)
    assert {context for context, _ in model_calls} == contexts, model_calls
    print("PASS Hermes: concurrent native calls retain the Deep session scope")
    gate.clear()


async def http_adapter(runtime: str, *, approval_delay: int = 0) -> None:
    import socket
    import urllib.error
    import urllib.request

    uvicorn = importlib.import_module("uvicorn")

    def child_processes() -> set[int]:
        parents: dict[int, int] = {}
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = path.read_text().rsplit(") ", 1)[1].split()
                if fields[0] != "Z":
                    parents[int(path.parent.name)] = int(fields[1])
            except (FileNotFoundError, ProcessLookupError):
                continue
        descendants = {os.getpid()}
        while added := {pid for pid, parent in parents.items() if parent in descendants} - descendants:
            descendants.update(added)
        return descendants - {os.getpid()}

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
            await qualify_parallel_runs(origin, runtime)
            await qualify_deep_sessions(origin, runtime)
            status: dict[str, Any] = {}
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
                while time.monotonic() < deadline:
                    with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                        status = json.load(response)
                    if status["status"] == "waiting_for_authorization" and (
                        runtime != "claude_agent" or status.get("stopped") is True
                    ):
                        break
                    await asyncio.sleep(0.05)
                assert status["status"] == "waiting_for_authorization", status
                if runtime == "claude_agent":
                    assert status.get("approval_parked") is True and status.get("stopped") is True, status
                    if allowed:
                        with module._runs.lock:
                            parked = module._runs.actors.pop(identifier)
                        os.unlink(parked.continuation["transcript_path"])
                if allowed and approval_delay:
                    approve_at = time.monotonic() + approval_delay
                    while time.monotonic() < approve_at:
                        await asyncio.sleep(min(1, max(0, approve_at - time.monotonic())))
                        with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                            status = json.load(response)
                        assert status["status"] == "waiting_for_authorization", status
                        assert not target.exists() and not gate["receipts"], "The SDK effect happened before approval"
                    deadline = time.monotonic() + 25
                gate["decision"] = "executing" if allowed else "denied"
                if status.get("approval_parked"):
                    resumed = urllib.request.Request(status_url + "/resume", data=request.data, headers=headers)
                    with urllib.request.urlopen(resumed, timeout=10) as response:
                        assert json.load(response)["runtime_run_id"] == identifier
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
                tools = [message for message in status["messages"]
                         if message.get("type") == "tool" and message.get("tool_name") not in {"thinking", "approval"}]
                assert tools, f"{runtime} discarded the actual SDK tool details: {status}"
                tool = tools[-1]
                assert tool["tool_arguments"] and str(target) in json.dumps(tool["tool_arguments"]), tool
                assert tool["tool_result"] and tool["content"], tool
                assert tool["tool_call_external_id"], tool
                assert tool["success"] is allowed, tool
                print(json.dumps({"runtime": runtime, "authorization": "allow" if allowed else "deny", "effect": target.exists()}))
                gate.clear()
            gate.clear()
            target = Path("/workspace" if runtime == "codex" else "/data/workspace") / "cancelled-write.txt"
            gate.update(path=str(target), decision="pending", requests=[], receipts=[])
            headers = {"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
                "X-Galaris-Run-Context": "synthetic-cancelled-context"}
            body = json.dumps({"model": "qualification", "messages": [
                {"role": "user", "content": "Perform the synthetic write, then reply qualification-ok"}]}).encode()
            request = urllib.request.Request(origin + "/v1/galaris/runs", data=body, headers=headers)
            existing_children = child_processes()
            with urllib.request.urlopen(request, timeout=10) as response:
                identifier = json.load(response)["runtime_run_id"]
            status_url = origin + "/v1/galaris/runs/" + identifier
            deadline = time.monotonic() + 20
            while not gate["requests"] and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert gate["requests"] and not target.exists(), "Cancellation must exercise a real pending SDK action"
            if runtime == "claude_agent":
                while time.monotonic() < deadline:
                    with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                        status = json.load(response)
                    if status.get("stopped") is True:
                        break
                    await asyncio.sleep(0.05)
                assert status.get("approval_parked") is True and status.get("stopped") is True, status
            sdk_children = child_processes() - existing_children
            assert bool(sdk_children) is (runtime != "claude_agent"), sdk_children
            started = time.monotonic()
            for _ in range(2):
                with urllib.request.urlopen(urllib.request.Request(status_url + "/cancel", data=b"{}", headers=headers), timeout=10) as response:
                    assert json.load(response)["cancelled"] is True
            while time.monotonic() < deadline:
                with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                    status = json.load(response)
                if status.get("stopped") is True:
                    break
                await asyncio.sleep(0.05)
            assert status.get("stopped") is True and status.get("success") is False, status
            assert not (sdk_children & child_processes()), "The runtime announced stopped with a live SDK subprocess"
            stopped_seconds = time.monotonic() - started
            # A late human answer must not authorize the cancelled SDK's write.
            gate["decision"] = "executing"
            with urllib.request.urlopen(request, timeout=10) as response:
                assert json.load(response)["runtime_run_id"] == identifier
            await asyncio.sleep(0.3)
            with urllib.request.urlopen(urllib.request.Request(status_url, headers=headers), timeout=10) as response:
                assert json.load(response) == status, "A duplicate launch reopened a stopped run"
            assert not target.exists() and not gate["receipts"], gate
            print(json.dumps({"runtime": runtime, "cancellation": "confirmed", "stopped_seconds": stopped_seconds,
                "late_approval_effect": False, "duplicate_launch_replayed": False}))
            gate.clear()
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def serve_process_claude() -> None:
    """Expose the real managed Claude runtime with a loopback model for the BPMN test."""
    observations: dict[str, list[str]] = {}

    class ProcessModel(ModelService):
        def message_answer(self, body: dict[str, Any]) -> str:
            prompt = json.dumps(body.get("messages", []), ensure_ascii=False)
            task = self.headers.get("X-Galaris-Task-Id")
            if task:
                observations.setdefault(task, []).append(prompt)
            if "qualification-mcp-output" in prompt:
                return "Synthetic review finished."
            accepted = ({"type": "string", "value": "invalid"} if "qualification-invalid-output" in prompt
                        else {"type": "bool", "value": True})
            return json.dumps({"accepted": accepted})

        def message_tool(self, body: dict[str, Any]) -> dict[str, Any] | None:
            messages = body.get("messages", [])
            prompt = json.dumps(messages, ensure_ascii=False)
            if "qualification-mcp-output" not in prompt:
                return None
            results = {block["tool_use_id"]: block for message in messages
                if isinstance(message.get("content"), list)
                for block in message["content"] if block.get("type") == "tool_result"}
            if "toolu_submit_review" in results:
                return None
            if "toolu_read_attachment" in results:
                read_result = results["toolu_read_attachment"]
                if read_result.get("is_error") or "Synthetic attachment content" not in json.dumps(read_result):
                    return None
                return {"type": "tool_use", "id": "toolu_submit_review", "name": "mcp__galaris__process_activity_complete",
                    "input": {"output": {"accepted": True}, "message": "Synthetic MCP receipt"}}
            attachment = re.search(r"file://[0-9a-f-]{36}", prompt)
            if attachment is None:
                return None
            return {"type": "tool_use", "id": "toolu_read_attachment", "name": "mcp__galaris__file_read",
                "input": {"uri": attachment[0]}}

    with ThreadingHTTPServer(("127.0.0.1", 0), ProcessModel) as server:
        origin = f"http://127.0.0.1:{server.server_port}"
        os.environ.update({"ANTHROPIC_BASE_URL": origin, "ANTHROPIC_AUTH_TOKEN": "qualification-token",
            "CLAUDE_AGENT_API_TOKEN": "qualification-token", "ENABLE_TOOL_SEARCH": "false"})
        Path.home().mkdir(parents=True, exist_ok=True)
        for directory in ("skills", "workspace", "claude"):
            (Path("/data") / directory).mkdir(exist_ok=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        root = Path("/opt/claude-agent")
        sys.path.insert(0, str(root))
        module = module_from_file(str(root / "server.py"))

        @module.app.get("/__qualification/model-requests/{task_id}")
        def model_request(task_id: str) -> dict[str, list[str]]:
            return {"prompts": observations.get(task_id, [])}

        @module.app.post("/__qualification/configure-mcp")
        def configure_mcp(settings: dict[str, str]) -> dict[str, bool]:
            url = settings["url"]
            if not re.fullmatch(r"http://backend:[0-9]+/api/mcp/[a-zA-Z0-9_-]+", url):
                raise ValueError("Expected the isolated qualification backend")
            os.environ.update({"GALARIS_MCP_URL": url, "GALARIS_MCP_TOKEN": settings["token"]})
            return {"configured": True}

        importlib.import_module("uvicorn").run(module.app, host="0.0.0.0", port=8642, log_level="warning")


def main() -> None:
    runtime = sys.argv[1]
    if runtime == "process_claude":
        serve_process_claude()
        return
    # The pinned CLI has a ten-minute default PreToolUse timeout.
    approval_delay = 610 if sys.argv[1:] == ["claude_agent", "--delayed-approval"] else 0
    signal.alarm(90 + approval_delay)
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
        asyncio.run(http_adapter(runtime, approval_delay=approval_delay))
    elif runtime == "hermes":
        cancellation_probe = module_from_file("/probe_hermes_cancellation.py")
        asyncio.run(cancellation_probe.qualify())
        cancellation_probe.qualify_gateway(origin, gate)
        gate.clear()
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
            history = results[0]["messages"]
            native_calls = [call for message in history if message.get("role") == "assistant"
                            for call in message.get("tool_calls", [])]
            native_results = [message for message in history if message.get("role") == "tool"]
            assert native_calls and native_results, history
            assert native_calls[0]["function"]["name"], native_calls
            assert str(target) in json.dumps(native_calls[0]["function"]["arguments"]), native_calls
            assert native_results[0]["tool_call_id"] == native_calls[0]["id"], native_results
            assert native_results[0]["content"], native_results
            print(f"PASS Hermes real SDK local write: {'approved' if allowed else 'denied'}")
        asyncio.run(qualify_hermes_managed(origin))
        asyncio.run(qualify_hermes_deep_scope(origin))
    elif runtime == "deepseek_harness":
        import subprocess

        # A file-write SDK test does not exercise shell confinement. Check the
        # shipped launcher on writable mounts, under the runtime's real limits.
        subprocess.run(["node", "--input-type=module", "-e", """
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {existsSync, writeFileSync} from 'node:fs';
import {grantArgs, launcherPath, probe} from '@deepseek-ai/node-addon-system/landlock-run';
assert.notEqual(probe(), 'unusable', 'The packaged Landlock launcher must be usable');
writeFileSync('/sessions/sandbox-control.txt', 'writable without confinement');
const result = spawnSync(launcherPath(), [...grantArgs({readOnly: ['/'], readWrite: ['/workspace', '/tmp', '/dev/null']}),
  '--', 'bash', '-c', 'printf allowed > /workspace/sandbox-ok.txt; printf forbidden > /sessions/sandbox-denied.txt'],
  {encoding: 'utf8', timeout: 10000});
assert.equal(result.error, undefined);
assert.notEqual(result.status, 0, 'An out-of-workspace write must fail');
assert.ok(existsSync('/workspace/sandbox-ok.txt'), result.stderr);
assert.ok(!existsSync('/sessions/sandbox-denied.txt'));
console.log('PASS DeepSeek shell confinement: workspace write allowed, sessions write denied');
"""], cwd="/opt/dsh/python/deepseek_harness_runtime/runtime/node", check=True, timeout=15)
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
        gate.update(network_recovery=True, model_dispatched=True)
        recovered = module.run_completion({
            "model": "qualification", "messages": [{"role": "user", "content": "Reply qualification-ok after recovery"}],
            "galaris_network_retry": {"max_attempts": 2, "base_seconds": 0, "max_seconds": 0},
        }, module.AdapterConfig.from_environment())
        assert recovered.content == ANSWER, recovered
        assert gate.get("provider_failures") and gate.get("continued"), gate
        print(json.dumps({"runtime": runtime, "automatic_provider_recovery": "passed"}))
        gate.clear()
        config = module.AdapterConfig.from_environment()
        config.workspace.mkdir(parents=True, exist_ok=True)
        adapter_server = module.HarnessHTTPServer(("127.0.0.1", 8080), config)
        adapter_thread = threading.Thread(target=adapter_server.serve_forever, daemon=True)
        adapter_thread.start()
        import urllib.request
        try:
            asyncio.run(qualify_parallel_runs("http://127.0.0.1:8080", runtime))
            asyncio.run(qualify_deep_sessions("http://127.0.0.1:8080", runtime))
            # Projected skills live outside the workspace. A native text read
            # validates the run context but must not request a mutation permit.
            for revoked in (False, True):
                source = Path("/sessions/synthetic-read.txt")
                source.write_text("synthetic-read-only")
                gate.update(native_read=True, path=str(source), read_revoked=revoked,
                    decision="pending", requests=[], receipts=[])
                request = urllib.request.Request("http://127.0.0.1:8080/v1/galaris/runs", headers={
                    "Content-Type": "application/json", "Authorization": "Bearer qualification-token",
                    "X-Galaris-Run-Context": f"synthetic-native-read-context-{revoked}"},
                    data=json.dumps({"model": "qualification", "messages": [{"role": "user", "content": "Read the synthetic fixture."}]}).encode())
                with urllib.request.urlopen(request, timeout=10) as response:
                    identifier = json.load(response)["runtime_run_id"]
                deadline = time.monotonic() + 25
                status = adapter_server.runs.get(identifier)
                while time.monotonic() < deadline:
                    status = adapter_server.runs.get(identifier)
                    if status["status"] != "running":
                        break
                    time.sleep(0.05)
                assert status["status"] == "completed", status
                reads = [message for message in status["messages"] if message.get("type") == "tool" and message.get("tool_name") == "read"]
                assert len(reads) == 1 and reads[0]["success"] is not revoked, reads
                assert ("synthetic-read-only" in reads[0]["content"]) is not revoked, reads
                assert gate["requests"] == [] and gate["receipts"] == [], gate
                offered = gate["offered_tools"]
                assert {"read", "mcp__galaris__qualification_echo"} <= offered, offered
                assert not offered & {"ask_user_question", "plugin_manager", "present", "run_code", "web_fetch", "web_search"}, offered
                assert not any(name.startswith(("office_", "schedule_", "team_task_")) for name in offered), offered
                print(f"PASS DeepSeek native read without mutation consent: revoked={revoked}")
                gate.clear()
            for managed_mcp, allowed in ((False, False), (False, True), (True, False), (True, True)):
                gate.clear()
                target = config.workspace / f"approval-{managed_mcp}-{allowed}.txt"
                gate.update(path=str(target), decision="pending", requests=[], receipts=[], authorization_response_delay=0.1,
                    network_recovery=allowed and not managed_mcp, managed_mcp=managed_mcp, deepseek_mcp=managed_mcp)
                headers = {"Content-Type": "application/json", "Authorization": "Bearer qualification-token",
                    "X-Galaris-Run-Context": f"synthetic-context-{managed_mcp}-{allowed}"}
                request = urllib.request.Request("http://127.0.0.1:8080/v1/galaris/runs", headers=headers,
                    data=json.dumps({"model": "qualification", "messages": [{"role": "user", "content": "Perform the synthetic write, then reply qualification-ok"}],
                        "galaris_network_retry": {"max_attempts": 2, "base_seconds": 0, "max_seconds": 0}}).encode())
                with urllib.request.urlopen(request, timeout=10) as response:
                    identifier = json.load(response)["runtime_run_id"]
                deadline = time.monotonic() + 25
                request_key = "mcp_requests" if managed_mcp else "requests"
                while not gate.get(request_key) and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert gate.get(request_key), "The actual DeepSeek SDK did not intercept its write"
                assert not target.exists(), "The DeepSeek effect happened before agreement"
                status = adapter_server.runs.get(identifier)
                while status["status"] == "running" and time.monotonic() < deadline:
                    time.sleep(0.05)
                    status = adapter_server.runs.get(identifier)
                assert status["status"] == "waiting_for_authorization", status
                assert not target.exists(), "The DeepSeek effect happened while awaiting agreement"
                time.sleep(0.5)
                gate["decision"] = ("approved" if managed_mcp else "executing") if allowed else "denied"
                status = adapter_server.runs.get(identifier)
                while time.monotonic() < deadline:
                    status = adapter_server.runs.get(identifier)
                    if status["status"] in {"completed", "failed", "outcome_unknown"}:
                        break
                    time.sleep(0.05)
                assert status["status"] == "completed", status
                assert target.exists() is allowed, (allowed, status)
                if allowed:
                    assert target.read_text() == "approved"
                    if managed_mcp:
                        assert gate["mcp_effects"] == 1 and len(gate["mcp_requests"]) == 2
                    else:
                        assert len(gate["receipts"]) == 1
                        assert gate.get("provider_failures") and gate.get("continued") and gate.get("retained_tool_result"), gate
                tools = [message for message in status["messages"]
                         if message.get("type") == "tool" and message.get("tool_name") != "thinking"]
                assert len(tools) == 1, tools
                tool = tools[0]
                assert tool["tool_name"] == gate["tool_call"]["name"], tool
                assert tool["tool_arguments"] == gate["tool_call"]["arguments"], tool
                assert tool["tool_call_external_id"] == "call_qualification", tool
                assert tool["content"] and tool["content"] != "Tool completed", tool
                # Native DeepSeek Messages nests a tool-result block; the generic
                # OpenAI route returns the SDK's ordinary role=tool message.
                result_message = tool["tool_result"]
                assert result_message["source"]["callId"] == tool["tool_call_external_id"], tool
                assert result_message["content"], tool
                assert result_message.get("toolCallId") == tool["tool_call_external_id"] or (
                    result_message["content"][0].get("toolCallId") == tool["tool_call_external_id"]
                ), tool
                assert tool["success"] is allowed, tool
                print(json.dumps({"runtime": runtime, "transport": "mcp" if managed_mcp else "native",
                    "authorization": "allow" if allowed else "deny", "effect": target.exists()}))
                gate.clear()
        finally:
            # An assertion must not leave SDK workers waiting for a human decision.
            gate["decision"] = "denied"
            for identifier in list(adapter_server.runs.actors):
                if adapter_server.runs.get(identifier)["status"] in {"running", "waiting_for_authorization"}:
                    adapter_server.runs.cancel(identifier)
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
