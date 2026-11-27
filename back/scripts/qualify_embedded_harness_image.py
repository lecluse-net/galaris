"""Verify embedded inference and managed task routing in an isolated backend image."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import socket
from time import monotonic
from typing import Any, AsyncGenerator, AsyncIterator, Literal
from uuid import UUID, uuid4

import claude_agent_sdk
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from starlette.types import ASGIApp
import uvicorn

from scripts.benchmark_embedded_harnesses import poll

ACTIVE_INPUTS = ("SYNTHETIC-FROZEN-A", "SYNTHETIC-FROZEN-B")
AFTER_ROLLBACK = "SYNTHETIC-ROLLBACK-CHAT"
TASK_INPUT = "SYNTHETIC-CLAUDE-TASK"
INTERNAL_CHAT_INPUT = "SYNTHETIC-PYDANTIC-CHAT"
INTERNAL_TASK_INPUT = "SYNTHETIC-PYDANTIC-TASK"
MANAGED_PROVIDERS = ("codex", "deepseek_harness")
MANAGED_CHATS = {provider: f"SYNTHETIC-MANAGED-CHAT-{provider}" for provider in MANAGED_PROVIDERS}
MANAGED_TASKS = {provider: f"SYNTHETIC-MANAGED-TASK-{provider}" for provider in MANAGED_PROVIDERS}
INPUTS = (*ACTIVE_INPUTS, AFTER_ROLLBACK, TASK_INPUT, INTERNAL_CHAT_INPUT, INTERNAL_TASK_INPUT, *MANAGED_CHATS.values())
LINKED_TASK_INPUTS = {driver: f"SYNTHETIC-LINKED-{driver}-INPUT"
                      for driver in ("internal", "claude_embedded", *MANAGED_PROVIDERS)}
TOOL_TASK_INPUTS = {driver: f"SYNTHETIC-TOOL-MISSION-{driver}-INPUT" for driver in LINKED_TASK_INPUTS}
REVIEW_TASK_INPUTS = {decision: {driver: f"SYNTHETIC-TASK-{decision}-{driver}-INPUT"
                               for driver in ("internal", "claude_embedded")} for decision in ("approved", "denied")}
ANSWER = "Synthetic embedded harness image verified."
TASK_ACKNOWLEDGEMENT = "The qualification task was submitted."
TASK_DECLINED = "The qualification task was declined."


@dataclass(frozen=True, slots=True)
class Receipt:
    prompt_marker: str
    identifier: str
    purpose: str | None = None


@dataclass(frozen=True, slots=True)
class ManagedRun:
    provider: str
    task_id: str
    agent_id: int


@asynccontextmanager
async def server(app: ASGIApp, port: int = 0, *, lifespan: Literal["on", "off"] = "off",
                 bind: str = "127.0.0.1") -> AsyncGenerator[str]:
    with socket.socket() as listener:
        listener.bind((bind, port))
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        config = uvicorn.Config(app, lifespan=lifespan, log_level="warning", access_log=False)
        uvicorn_server = uvicorn.Server(config)
        worker = asyncio.create_task(uvicorn_server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(75):
                while not uvicorn_server.started:
                    if worker.done():
                        await worker
                        raise RuntimeError("Qualification server stopped during startup")
                    await asyncio.sleep(0.05)
            yield address
        finally:
            uvicorn_server.should_exit = True
            await worker


def provider_app(receipts: list[Receipt], release: asyncio.Event, load_inputs: frozenset[str],
                 managed_runs: dict[str, ManagedRun], *, real_managed: bool) -> FastAPI:
    provider = FastAPI()
    linked_inputs = frozenset(LINKED_TASK_INPUTS.values())
    tool_inputs = frozenset(TOOL_TASK_INPUTS.values())
    review_inputs = frozenset(marker for cases in REVIEW_TASK_INPUTS.values() for marker in cases.values())
    agent_tool_inputs = tool_inputs | review_inputs
    direct_managed_inputs = frozenset(MANAGED_TASKS.values()) if real_managed else frozenset[str]()

    def managed_markers(code: str) -> tuple[str, ...]:
        return MANAGED_TASKS[code], LINKED_TASK_INPUTS[code], TOOL_TASK_INPUTS[code]

    def managed_answer(code: str) -> str:
        return f"Ran in {code}."

    @provider.post("/v1/chat/completions", response_model=None)
    async def complete(request: Request) -> JSONResponse | StreamingResponse:
        body: dict[str, Any] = await request.json()
        prompt = json.dumps(body["messages"])
        matches = [marker for marker in REVIEW_TASK_INPUTS["denied"].values() if marker in prompt]
        if not matches:
            matches = [marker for marker in REVIEW_TASK_INPUTS["approved"].values() if marker in prompt]
        if not matches:
            matches = [marker for marker in tool_inputs if marker in prompt]
        if not matches:
            matches = [marker for marker in linked_inputs if marker in prompt]
        if not matches:
            matches = [marker for marker in (*INPUTS, *load_inputs, *direct_managed_inputs) if marker in prompt]
        if len(matches) != 1 or (not real_managed and not body.get("stream")):
            raise ValueError(f"Unexpected provider request: markers={matches}, streaming={body.get('stream')}")
        marker = matches[0]
        purpose = None
        delta: dict[str, Any] = {"role": "assistant", "content": ANSWER}
        finish_reason = "stop"
        if marker in linked_inputs or marker in agent_tool_inputs:
            functions: dict[str, dict[str, Any]] = {tool["function"]["name"]: tool["function"] for tool in body.get("tools", [])}
            objective_tool = next((name for name, tool in functions.items()
                                   if {"label", "objective", "write_targets"} <= set(tool["parameters"].get("properties", {}))), None)
            dispatch_tool = next((name for name, tool in functions.items()
                                  if {"route", "effort", "organization"} <= set(tool["parameters"].get("properties", {}))), None)
            name: str | None = None
            arguments: dict[str, object] = {}
            if objective_tool:
                purpose = "conversation.task_objective"
                name, arguments = objective_tool, {
                    "label": marker, "objective": f"<p>Return the qualification result for {marker}.</p>",
                    "write_targets": [],
                }
            elif dispatch_tool:
                purpose = "agent.dispatch"
                name, arguments = dispatch_tool, {"route": "EXEC", "effort": "standard", "organization": "direct", "language": "en"}
            elif marker in agent_tool_inputs and "Answer only the current admitted human message" in prompt:
                purpose = "conversation.text"
                resumed_authorization = "Galaris has resolved the earlier tool authorization" in prompt
                has_tool_result = (any(message["role"] == "tool" for message in body["messages"])
                                   or resumed_authorization)
                if not has_tool_result:
                    [name] = [name for name in functions if name == "task_run" or name.endswith("__task_run")]
                    arguments = {"label": marker, "objective": f"<p>Return the qualification result for {marker}.</p>",
                                 "mode": "exec", "disposition": "CREATE_NEW"}
                else:
                    if marker in review_inputs and "mcp__galaris__task_run" in functions and not resumed_authorization:
                        delta["content"] = "Waiting for the qualification decision."
                    else:
                        delta["content"] = (TASK_DECLINED if marker in REVIEW_TASK_INPUTS["denied"].values()
                                            else TASK_ACKNOWLEDGEMENT)
            else:
                purpose = "agent.exec"
                delta["content"] = (managed_answer("deepseek_harness") if real_managed and
                                    marker == TOOL_TASK_INPUTS["deepseek_harness"] else f"Qualification result for {marker}.")
            if name is not None:
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{uuid4().hex}",
                         "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
                finish_reason = "tool_calls"
        if real_managed and marker in managed_markers("deepseek_harness") and purpose in (None, "agent.exec"):
            purpose = "agent.exec"
            delta["content"] = managed_answer("deepseek_harness")
        receipt = Receipt(marker, f"chatcmpl-qualification-{uuid4().hex}", purpose)
        receipts.append(receipt)
        headers = {"x-request-id": receipt.identifier}
        usage = {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}
        if not body.get("stream"):
            return JSONResponse({"id": receipt.identifier, "object": "chat.completion", "created": 1,
                                 "model": body["model"], "usage": usage, "choices": [
                                 {"index": 0, "message": delta, "finish_reason": finish_reason}]}, headers=headers)

        async def stream() -> AsyncIterator[str]:
            if receipt.prompt_marker in ACTIVE_INPUTS:
                await release.wait()
            if receipt.prompt_marker in load_inputs:
                await asyncio.sleep(0.25)
            for chunk_delta, reason in ((delta, None), ({}, finish_reason)):
                chunk: dict[str, object] = {
                    "id": receipt.identifier, "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                    "choices": [{"index": 0, "delta": chunk_delta, "finish_reason": reason}],
                }
                if reason:
                    chunk["usage"] = usage
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    @provider.post("/v1/responses", response_model=None)
    async def complete_responses(request: Request) -> JSONResponse | StreamingResponse:
        body: dict[str, Any] = await request.json()
        assert real_managed
        prompt = json.dumps(body["input"])
        [marker] = [token for token in managed_markers("codex") if token in prompt]
        receipt = Receipt(marker, f"resp_qualification_{uuid4().hex}", "agent.exec")
        receipts.append(receipt)
        headers = {"x-request-id": receipt.identifier}
        answer = managed_answer("codex")
        part: dict[str, object] = {"type": "output_text", "text": answer, "annotations": []}
        item: dict[str, object] = {"id": f"msg_{uuid4().hex}", "type": "message", "status": "completed",
                                  "role": "assistant", "content": [part]}
        response: dict[str, object] = {"id": receipt.identifier, "object": "response", "created_at": 1,
                                      "status": "completed", "model": body["model"], "output": [item],
                                      "usage": {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16}}
        if not body.get("stream"):
            return JSONResponse(response, headers=headers)

        async def stream() -> AsyncIterator[str]:
            part_ref = {"item_id": item["id"], "output_index": 0, "content_index": 0}
            events: list[tuple[str, dict[str, object]]] = [
                ("response.created", {"response": {**response, "status": "in_progress", "output": []}}),
                ("response.output_item.added", {"output_index": 0, "item": {**item, "status": "in_progress", "content": []}}),
                ("response.content_part.added", {**part_ref, "part": {**part, "text": ""}}),
                ("response.output_text.delta", {**part_ref, "delta": answer}),
                ("response.output_text.done", {**part_ref, "text": answer}),
                ("response.content_part.done", {**part_ref, "part": part}),
                ("response.output_item.done", {"output_index": 0, "item": item}),
                ("response.completed", {"response": response}),
            ]
            for index, (kind, payload) in enumerate(events):
                frame = {"type": kind, "sequence_number": index, **payload}
                yield f"event: {kind}\ndata: {json.dumps(frame)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    @provider.get("/managed/{code}/galaris/capabilities")
    async def capabilities(code: str) -> dict[str, str | bool]:
        assert code in MANAGED_PROVIDERS
        return {"authorization_protocol": "galaris.runtime-authorization/v1", "resumable_runs": True,
                "run_scoped_llm": True}

    @provider.post("/managed/{code}/galaris/runs")
    async def start_managed(code: str, request: Request) -> dict[str, str]:
        body: dict[str, Any] = await request.json()
        prompt = json.dumps(body["messages"])
        assert sum(marker in prompt for marker in managed_markers(code)) == 1
        assert body["model"] == f"synthetic-{code}"
        actor = sha256(request.headers["x-galaris-run-context"].encode()).hexdigest()
        assert actor not in managed_runs
        managed_runs[actor] = ManagedRun(code, request.headers["x-galaris-task-id"],
                                         int(request.headers["x-galaris-agent-id"]))
        return {"runtime_run_id": actor}

    @provider.get("/managed/{code}/galaris/runs/{actor}")
    async def read_managed(code: str, actor: str, request: Request) -> dict[str, str | bool]:
        assert actor == sha256(request.headers["x-galaris-run-context"].encode()).hexdigest()
        run = managed_runs[actor]
        assert run.provider == code and run.task_id == request.headers["x-galaris-task-id"]
        return {"status": "completed", "stopped": True, "success": True, "result": managed_answer(code)}

    return provider


async def seed(model_url: str) -> tuple[int, int, str]:
    from app.agent import Agent, Title
    from app.connection import Connection
    from app.llm.profile_models import LlmProfile
    from app.llm.provider_models import LLM, LLMProvider
    from app.services import ServiceModel
    from core.authorize import Assignment, Role
    from core.database import get_db_session
    from core.params import params_service
    from core.user.auth_service import create_access_token_for_user
    from core.user.models import User

    async with get_db_session() as db:
        if await db.scalar(select(User.id).limit(1)) is not None:
            raise RuntimeError("The image qualification requires an empty disposable database")
        await params_service.load_params()
        owner = User(email="embedded-image@example.test", hashed_password="unused")
        provider = LLMProvider(name="Embedded image fixture", base_url=f"{model_url}/v1",
                               provider_type="openai_compatible", is_active=True, max_concurrent_calls=4)
        db.add_all([owner, provider])
        await db.flush()
        role = await db.scalar(select(Role).where(Role.code == "admin"))
        title = await db.scalar(select(Title.id).limit(1))
        chat = await db.scalar(select(ServiceModel).where(ServiceModel.code == "chat"))
        assert role is not None and title is not None and chat is not None
        model = LLM(llm_provider_id=provider.id, provider=provider, code="embedded-image-model",
                    label="Embedded image fixture", llm_name="synthetic", cost_per_input_token=2, cost_per_output_token=4)
        db.add_all([model, Assignment(user_id=owner.id, role_id=role.id, is_default=True)])
        await db.flush()
        profile = LlmProfile(label="Embedded image fixture", text_low_llm_id=model.id, text_standard_llm_id=model.id)
        db.add(profile)
        await db.flush()
        agent = Agent(user_id=owner.id, title_id=title, code="embedded-image-agent", first_name="Synthetic",
                      last_name="Qualification", profile_id=profile.id, agent_driver="claude_embedded")
        db.add(agent)
        await db.flush()
        db.add(Connection(service_id=chat.id, agent_id=agent.id, active=True))
        token = await create_access_token_for_user(owner, db, role_id=role.id)
        return agent.id, model.id, token


async def seed_comparison_agents(owner_agent: int, url: str, *, real_managed: bool) -> dict[str, int]:
    from app.agent import Agent, agent_skill_revision
    from app.connection import Connection
    from app.harnesses.models import AgentHarness
    from app.mcp import AgentMcpToken, mcp_token_service
    from app.services import ServiceModel
    from core.database import get_db_session
    from core.util.encryption import encrypt_value
    from core.util.token_hash import hash_token

    agents: dict[str, int] = {}
    async with get_db_session() as db:
        reference = await db.get(Agent, owner_agent)
        service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "chat"))
        assert reference is not None and service_id is not None
        for provider in ("internal", *MANAGED_PROVIDERS):
            agent = Agent(user_id=reference.user_id, title_id=reference.title_id, profile_id=reference.profile_id,
                          code=f"synthetic-{provider}", first_name="Synthetic", last_name=provider,
                          agent_driver="internal" if provider == "internal" else "openai_messages")
            db.add(agent)
            await db.flush()
            db.add(Connection(service_id=service_id, agent_id=agent.id, active=True))
            agents[provider] = agent.id
            if provider == "internal":
                continue
            skill_revision = await agent_skill_revision(agent.id)
            base_url, runtime_model = f"{url}/managed/{provider}", f"synthetic-{provider}"
            runtime_token = None
            if real_managed:
                port = 8787 if provider == "codex" else 8080
                base_url, runtime_model = f"http://qualification-{provider}:{port}/v1", "embedded-image-model"
                runtime_token = encrypt_value(f"qualification-api-{provider}")
                mcp_token = f"mcp_qualification_{provider}"
                db.add(AgentMcpToken(agent_id=agent.id, label="Qualification", hidden=True,
                                    token_encrypted=encrypt_value(mcp_token), token_hash=hash_token(mcp_token)))
            db.add(AgentHarness(agent_id=agent.id, provider_code=provider, lifecycle_status="ready",
                                runtime_base_url=base_url, runtime_model=runtime_model, runtime_token_encrypted=runtime_token,
                                provider_metadata={"galaris_extensions": True, "run_scoped_llm": True,
                                                   "skill_revision": skill_revision}))
    if not real_managed:
        async with get_db_session():
            for provider in MANAGED_PROVIDERS:
                await mcp_token_service.ensure_system_token(agents[provider])
    return agents


async def exercise(origin: str, agent: int, model: int, token: str, receipts: list[Receipt],
                   release: asyncio.Event, load: dict[str, tuple[str, ...]], comparison_agents: dict[str, int],
                   managed_runs: dict[str, ManagedRun], *, real_managed: bool,
                   ) -> tuple[list[dict[str, str]], dict[str, dict[str, float | int]], dict[str, str], dict[str, dict[str, str]]]:
    from app.connection import Connection
    from app.connection.connection_service import set_connection_function_state
    from app.connection.models import ConnectionFunctionState
    from app.conversation import ConversationRoundAttempt, ConversationTaskLink
    from app.llm.embedded_runtime import EmbeddedRoundInference
    from app.services import ServiceModel
    from app.services.authorization_models import ActionAuthorization
    from app.task import Task
    from core.database import get_db_session
    from core.params import Params

    async with httpx.AsyncClient(base_url=origin, timeout=15, trust_env=False, headers={
        "Authorization": f"Bearer {token}", "X-Editorial-Profile-Version": "1",
    }) as client:
        async def request(method: str, path: str, **kwargs: Any) -> Any:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def submit(marker: str, agent_id: int = agent, *, text: str | None = None) -> str:
            room = (await request("POST", "/api/chat/rooms", json={"label": marker, "agent_id": agent_id}))["id"]
            message = (await request("POST", f"/api/chat/rooms/{room}/messages", json={
                "text": text or marker, "client_message_id": str(uuid4()), "language": "en",
            }))["id"]

            async def admit() -> str | None:
                activity = await request("GET", f"/api/chat/rooms/{room}/activity")
                return next((str(item["id"]) for item in activity["items"] if message in item["message_ids"]), None)

            return await poll(admit, timeout=20)

        async def terminal(path: str, success: str) -> dict[str, Any]:
            async def completed() -> dict[str, Any] | None:
                row: dict[str, Any] = await request("GET", path)
                if row["status"] in {"ERROR", "ERROR_RESOLVED", "FAILED", "CANCELLED", "INTERRUPTED", "SUPERSEDED"}:
                    execution: dict[str, Any] = row.get("execution_result") or {}
                    failure: dict[str, Any] = execution.get("failure") or {}
                    detail = failure.get("message") or row.get("last_error") or execution.get("result")
                    raise RuntimeError(f"{path} failed with status {row['status']} and code {failure.get('code')}: {detail}")
                return row if row["status"] == success else None

            return await poll(completed, timeout=45)

        async def managed_call(code: str, task_id: str, agent_id: int, metadata: dict[str, Any],
                               round_id: str | None = None) -> dict[str, Any] | None:
            calls = await request("GET", "/api/llm-calls", params={"task_id": task_id})
            execution_calls = [call for call in calls if call["purpose"] == "agent.exec"]
            if not real_managed:
                assert managed_runs[metadata["runtime_run_id"]] == ManagedRun(code, task_id, agent_id)
                assert not execution_calls
                return None
            [call] = execution_calls
            assert metadata["runtime_run_id"] and metadata["attempt_id"]
            assert call["task_id"] == task_id and call["agent_id"] == agent_id and call["llm_id"] == model
            assert call["agent_run_id"] == metadata["run_id"] and call["task_attempt_id"] == metadata["attempt_id"]
            assert call["purpose"] == "agent.exec" and call["status"] == "completed" and call["total_tokens"] == 16
            assert call["conversation_round_id"] == round_id, (code, task_id, call["conversation_round_id"], round_id)
            return call

        old = await asyncio.gather(*(submit(marker) for marker in ACTIVE_INPUTS))
        try:
            async with asyncio.timeout(35):
                while {item.prompt_marker for item in receipts} != set(ACTIVE_INPUTS):
                    await asyncio.sleep(0.05)
            await request("PUT", f"/api/harnesses/agents/{agent}", json={"driver_code": "internal"})
            new = await submit(AFTER_ROLLBACK)
            await request("PUT", f"/api/harnesses/agents/{agent}", json={"driver_code": "claude_embedded"})
        finally:
            release.set()

        async def submit_task(marker: str, agent_id: int) -> str:
            task_id: str = (await request("POST", "/api/tasks", json={
                "agent_id": agent_id, "label": marker, "objective": f"<p>{marker}</p>",
                "forced_route": "EXEC", "forced_effort": "standard",
            }))["id"]
            await request("POST", f"/api/tasks/{task_id}/run")
            return task_id

        task = await submit_task(TASK_INPUT, agent)
        expected = [*zip(ACTIVE_INPUTS, old, ("claude_embedded", "claude_embedded"), strict=True),
                    (AFTER_ROLLBACK, new, "internal"), (TASK_INPUT, task, "claude_embedded")]
        # Finish the reassignment cohort before running independent bursts.
        internal_agent = comparison_agents["internal"]
        owners = {INTERNAL_CHAT_INPUT: internal_agent, INTERNAL_TASK_INPUT: internal_agent}
        burst_results: dict[str, dict[str, Any]] = {}
        burst_metrics: dict[str, dict[str, float | int]] = {}
        if load:
            await asyncio.gather(
                *(terminal(f"/api/conversations/rounds/{identifier}", "SUCCEEDED") for identifier in (*old, new)),
                terminal(f"/api/tasks/{task}", "SUCCESS"),
            )
        for driver, markers in load.items():
            selected_agent = agent if driver == "claude_embedded" else internal_agent
            started = monotonic()
            rounds = await asyncio.gather(*(submit(marker, selected_agent) for marker in markers))
            rows = await asyncio.gather(*(terminal(f"/api/conversations/rounds/{identifier}", "SUCCEEDED")
                                          for identifier in rounds))
            burst_results.update(zip(rounds, rows, strict=True))
            burst_metrics[driver] = {"rounds": len(rounds), "wall_seconds": round(monotonic() - started, 3)}
            expected.extend((marker, identifier, driver) for marker, identifier in zip(markers, rounds, strict=True))
            owners.update((marker, selected_agent) for marker in markers)
        managed_tasks: dict[str, str] = {}
        journal: list[dict[str, str]] = []
        expected.extend(((INTERNAL_CHAT_INPUT, await submit(INTERNAL_CHAT_INPUT, internal_agent), "internal"),
                         (INTERNAL_TASK_INPUT, await submit_task(INTERNAL_TASK_INPUT, internal_agent), "internal")))
        for provider, enable in (("codex", Params.HARNESS_CODEX_ENABLED), ("deepseek_harness", Params.HARNESS_DEEPSEEK_ENABLED)):
            await request("PUT", f"/api/params/{enable}", json={"value": "true"})
            agent_id = comparison_agents[provider]
            marker = MANAGED_CHATS[provider]
            expected.append((marker, await submit(marker, agent_id), "internal"))
            owners[marker] = agent_id
            task_id = await submit_task(MANAGED_TASKS[provider], agent_id)
            row = await terminal(f"/api/tasks/{task_id}", "SUCCESS")
            execution: dict[str, Any] = row["execution_result"]
            metadata: dict[str, Any] = execution["metadata"]
            assert metadata["driver_code"] == "openai_messages" and metadata["agent_id"] == agent_id
            assert execution["result"] == f"Ran in {provider}."
            if call := await managed_call(provider, task_id, agent_id, metadata):
                marker = MANAGED_TASKS[provider]
                [receipt] = [item for item in receipts if item.prompt_marker == marker and item.purpose == "agent.exec"]
                assert call["upstream_request_id"] == receipt.identifier
                journal.append({"marker": marker, "driver": provider, "operation": task_id, "call": call["id"],
                                "purpose": call["purpose"], "upstream_request_id": receipt.identifier})
            managed_tasks[provider] = task_id
        assert len(managed_runs) == (0 if real_managed else len(managed_tasks))
        for marker, identifier, driver in expected:
            agent_id = owners.get(marker, agent)
            is_task = marker in (TASK_INPUT, INTERNAL_TASK_INPUT)
            path = f"/api/tasks/{identifier}" if is_task else f"/api/conversations/rounds/{identifier}"
            row = burst_results.get(identifier) or await terminal(path, "SUCCESS" if is_task else "SUCCEEDED")
            execution: dict[str, Any] = row["execution_result"]
            metadata: dict[str, Any] = execution["metadata"]
            assert metadata["driver_code"] == driver and metadata["agent_id"] == agent_id
            if is_task:
                assert execution["result"] == ANSWER
            else:
                assert row["response_text"] == ANSWER
            owner = "task_id" if is_task else "conversation_round_id"
            calls = await request("GET", "/api/llm-calls", params={owner: identifier})
            assert len(calls) == 1, f"Unexpected physical call count for {marker}"
            call = calls[0]
            assert call[owner] == identifier and call["agent_run_id"] == metadata["run_id"]
            assert call["llm_id"] == model and call["agent_id"] == agent_id and call["total_tokens"] == 16
            assert call["purpose"] == ("agent.exec" if is_task else "conversation.text")
            if is_task:
                assert call["task_attempt_id"] == metadata["attempt_id"] and call["task_attempt_id"]
            if driver == "internal":
                assert call["correlation_ref"] is None
            elif is_task:
                assert call["correlation_ref"] == f"task:{identifier}:attempt:{metadata['attempt_id']}"
            else:
                prefix = f"round:{identifier}:attempt:"
                assert str(call["correlation_ref"]).startswith(prefix)
                round_id = UUID(identifier)
                attempt_id = UUID(str(call["correlation_ref"]).removeprefix(prefix))
                async with get_db_session() as db:
                    attempt = await db.get(ConversationRoundAttempt, attempt_id)
                    assert attempt is not None and attempt.inference_admission is not None
                    request_limit = attempt.inference_admission.get("request_limit")
                    assert type(request_limit) is int and request_limit > 0
                stale = EmbeddedRoundInference(
                    round_id=round_id, attempt_id=attempt_id, run_id=round_id, agent_id=agent_id,
                    model_id=model, model_code="embedded-image-model", driver_code=driver,
                    request_limit=request_limit,
                ).credential()
                rejected = await client.post("/api/llm/anthropic/v1/messages", headers={"x-api-key": stale},
                    json={"model": "embedded-image-model", "max_tokens": 16,
                          "messages": [{"role": "user", "content": marker}]})
                assert rejected.status_code == 403, "A completed turn's credential must be rejected"
            assert [item.identifier for item in receipts if item.prompt_marker == marker] == [call["upstream_request_id"]]
            journal.append({"marker": marker, "driver": driver, "operation": identifier, "call": call["id"],
                            "purpose": call["purpose"], "upstream_request_id": call["upstream_request_id"]})
        assert len(receipts) == len(journal) == len(expected) + (len(managed_tasks) if real_managed else 0)
        linked: dict[str, dict[str, str]] = {}
        task_connections: dict[int, int] = {}
        async with get_db_session() as db:
            task_service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "task"))
            assert task_service_id is not None
            for agent_id in (agent, *comparison_agents.values()):
                task_connection = Connection(service_id=task_service_id, agent_id=agent_id, active=True)
                db.add(task_connection)
                await db.flush()
                task_connections[agent_id] = task_connection.id
                db.add(ConnectionFunctionState(connection_id=task_connection.id, function_name="task_run",
                                               state="enabled", enabled=True))

        async def answer_task_request(round_id: str, marker: str, *, allow: bool) -> str:
            round_path = f"/api/conversations/rounds/{round_id}"
            parked = await terminal(round_path, "WAITING_APPROVAL")
            assert not parked["response_text"] and not parked["effect_started"]
            [authorization_id] = parked["execution_result"]["authorization_requests"]

            async def pending_room_choice() -> str | None:
                async with get_db_session() as db:
                    row = await db.get(ActionAuthorization, UUID(authorization_id))
                    assert row is not None and row.status == "pending"
                    assert row.context_key == f"round:{round_id}" and row.capability_name == "task_run"
                    assert await db.scalar(select(Task.id).where(Task.label == marker)) is None
                    assert await db.scalar(select(ConversationTaskLink.id).where(ConversationTaskLink.round_id == UUID(round_id))) is None
                    return str(row.interaction_id) if row.interaction_id is not None else None

            interaction = await poll(pending_room_choice, timeout=30)
            selected_option = "allow" if allow else "deny"
            answered = await request("POST", f"/api/chat/rooms/{parked['room_id']}/interactions/{interaction}/answer",
                                     json={"option_id": selected_option})
            assert answered["selected_option_id"] == selected_option
            return authorization_id

        def record_linked_calls(marker: str, agent_id: int, owners: list[tuple[dict[str, Any], str, str | None]]) -> None:
            for call, operation, actual_driver in owners:
                assert call["agent_id"] == agent_id and call["llm_id"] == model and call["total_tokens"] == 16
                [provider_receipt] = [receipt for receipt in receipts if receipt.prompt_marker == marker
                                      and receipt.purpose == call["purpose"] and receipt.identifier == call["upstream_request_id"]]
                evidence = {"marker": marker, "operation": operation, "call": call["id"], "purpose": call["purpose"],
                            "upstream_request_id": provider_receipt.identifier}
                if actual_driver is not None:
                    evidence["driver"] = actual_driver
                journal.append(evidence)

        launch_inputs = {"directive": LINKED_TASK_INPUTS, "tool": TOOL_TASK_INPUTS, **REVIEW_TASK_INPUTS}
        cases = [(launch, driver, marker) for launch, inputs in launch_inputs.items() for driver, marker in inputs.items()]
        for launch, driver, marker in cases:
            agent_id = agent if driver == "claude_embedded" else comparison_agents[driver]
            directive = launch == "directive"
            reviewed = launch in REVIEW_TASK_INPUTS
            if reviewed:
                async with get_db_session():
                    await set_connection_function_state(task_connections[agent_id], "task_run", "ask")
            question = (f"@task @exec @standard Return the qualification result for {marker}." if directive
                        else f"Please submit a background task to return the qualification result for {marker}.")
            round_id = await submit(marker, agent_id, text=question)
            authorization_id = await answer_task_request(round_id, marker, allow=launch == "approved") if reviewed else None
            round_row = await terminal(f"/api/conversations/rounds/{round_id}", "SUCCEEDED")
            chat_driver = "claude_embedded" if driver == "claude_embedded" else "internal"
            round_metadata = round_row["execution_result"]["metadata"]
            assert round_metadata["driver_code"] == chat_driver
            round_calls = await request("GET", "/api/llm-calls", params={"conversation_round_id": round_id})
            conversation_calls = [call for call in round_calls if call["purpose"] == "conversation.text"]
            expected_conversation_calls = 0 if directive else 3 if reviewed and chat_driver == "claude_embedded" else 2
            assert len(conversation_calls) == expected_conversation_calls, (launch, driver, len(conversation_calls))
            call_owners: list[tuple[dict[str, Any], str, str | None]] = []
            for chat_call in conversation_calls:
                assert chat_call["agent_run_id"] == chat_call["conversation_round_id"] == round_id
                assert chat_call["task_id"] is None and chat_call["task_attempt_id"] is None
                if chat_driver == "claude_embedded":
                    assert str(chat_call["correlation_ref"]).startswith(f"round:{round_id}:attempt:")
                call_owners.append((chat_call, round_id, chat_driver))
            case_key = driver if directive else f"{launch}:{driver}"
            if authorization_id is not None:
                async with get_db_session() as db:
                    [authorization] = await db.scalars(select(ActionAuthorization).where(
                        ActionAuthorization.context_key == f"round:{round_id}", ActionAuthorization.capability_name == "task_run"))
                    assert str(authorization.id) == authorization_id
                    assert authorization.status == ("denied" if launch == "denied" else "completed")
                    attempts = list((await db.scalars(select(ConversationRoundAttempt)
                        .where(ConversationRoundAttempt.round_id == UUID(round_id))
                        .order_by(ConversationRoundAttempt.attempt_number))).all())
                    assert [attempt.status for attempt in attempts] == ["WAITING_APPROVAL", "SUCCESS"]
                    if chat_driver == "claude_embedded":
                        assert {call["correlation_ref"] for call in conversation_calls} == {
                            f"round:{round_id}:attempt:{attempt.id}" for attempt in attempts}
            if launch == "denied":
                assert round_row["response_text"] == TASK_DECLINED and len(round_calls) == expected_conversation_calls
                async with get_db_session() as db:
                    assert await db.scalar(select(Task.id).where(Task.label == marker)) is None
                    assert await db.scalar(select(ConversationTaskLink.id).where(ConversationTaskLink.round_id == UUID(round_id))) is None
                record_linked_calls(marker, agent_id, call_owners)
                assert authorization_id is not None
                linked[case_key] = {"round": round_id, "conversation_driver": chat_driver, "authorization": authorization_id}
                continue

            submitted: list[dict[str, Any]] = []
            if directive:
                assert round_metadata["deterministic_control"] is True
            else:
                assert round_row["response_text"] == TASK_ACKNOWLEDGEMENT
                assert round_metadata.get("deterministic_control") is not True
                took_action = [item for item in round_row["execution_result"]["messages"] if item["type"] == "tool"]
                submitted = [item for item in took_action if str(item["tool_name"]).endswith("task_run") and item["success"] is True]
            async with get_db_session() as db:
                link_id, task_uuid = (await db.execute(select(ConversationTaskLink.id, ConversationTaskLink.task_id)
                    .where(ConversationTaskLink.round_id == UUID(round_id)))).one()
            task_id = str(task_uuid)
            if not directive:
                [task_receipt] = submitted
                assert task_id in json.dumps(task_receipt)
            task_row = await terminal(f"/api/tasks/{task_id}", "SUCCESS")

            async def delivered() -> str | None:
                async with get_db_session() as db:
                    link = await db.get(ConversationTaskLink, link_id)
                    assert link is not None and link.notification_state != "UNKNOWN", (driver, link_id)
                    if link.notification_state == "DELIVERED":
                        assert link.notification_message_id is not None
                        return str(link.notification_message_id)
                    return None

            message_id = await poll(delivered, timeout=45)
            execution = task_row["execution_result"]
            metadata = execution["metadata"]
            managed = driver in MANAGED_PROVIDERS
            result = f"Ran in {driver}." if managed else f"Qualification result for {marker}."
            assert metadata["agent_id"] == agent_id and execution["result"] == result
            messages = (await request("GET", f"/api/chat/rooms/{round_row['room_id']}/messages"))["items"]
            [notification] = [message for message in messages if message["direction"] == "outbound"
                              and result in message["text"]]
            assert notification["id"] == message_id

            [objective_call] = [call for call in round_calls if call["purpose"] == "conversation.task_objective"]
            assert objective_call["agent_run_id"] == objective_call["conversation_round_id"] == round_id
            assert objective_call["task_id"] is None and objective_call["task_attempt_id"] is None
            call_owners.append((objective_call, round_id, None))
            task_calls = await request("GET", "/api/llm-calls", params={"task_id": task_id})
            dispatch_calls = [call for call in task_calls if call["purpose"] == "agent.dispatch"]
            assert len(dispatch_calls) == (0 if directive else 1)
            for dispatched in dispatch_calls:
                assert dispatched["task_id"] == task_id and dispatched["task_attempt_id"]
                assert dispatched["conversation_round_id"] == round_id
                call_owners.append((dispatched, task_id, None))
            if managed:
                assert metadata["driver_code"] == "openai_messages"
                if exec_call := await managed_call(driver, task_id, agent_id, metadata, round_id):
                    call_owners.append((exec_call, task_id, driver))
            else:
                [exec_call] = [call for call in task_calls if call["purpose"] == "agent.exec"]
                assert metadata["driver_code"] == driver and exec_call["purpose"] == "agent.exec"
                assert exec_call["agent_run_id"] == metadata["run_id"]
                assert exec_call["task_id"] == task_id and exec_call["task_attempt_id"] == metadata["attempt_id"]
                assert exec_call["conversation_round_id"] == round_id
                if driver == "claude_embedded":
                    assert exec_call["correlation_ref"] == f"task:{task_id}:attempt:{metadata['attempt_id']}"
                call_owners.append((exec_call, task_id, driver))
            record_linked_calls(marker, agent_id, call_owners)
            linked[case_key] = {"round": round_id, "task": task_id, "notification": message_id,
                               "conversation_driver": chat_driver, "task_driver": metadata["driver_code"]}
            if authorization_id is not None:
                linked[case_key]["authorization"] = authorization_id
        assert len(managed_runs) == (0 if real_managed else 3 * len(MANAGED_PROVIDERS))
        assert len(receipts) == len(journal) == len({item["call"] for item in journal})
        assert {item["upstream_request_id"] for item in journal} == {receipt.identifier for receipt in receipts}
        return journal, burst_metrics, managed_tasks, linked


async def main() -> None:
    from core.settings import settings

    if settings.APP_ENV != "test" or settings.POSTGRES_HOST != "embedded-harness-db" or settings.POSTGRES_DB != "test_db":
        raise RuntimeError("Embedded harness image qualification requires its isolated database")
    if os.geteuid() == 0:
        raise RuntimeError("Test the image's unprivileged runtime user")
    revision = settings.APP_BUILD_REVISION
    if revision == "unknown" or revision != os.environ["QUALIFICATION_REVISION"]:
        raise RuntimeError("The backend image does not contain the expected source revision")
    from main import app

    binary = Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / "claude"
    child = await asyncio.create_subprocess_exec(str(binary), "--version", stdout=asyncio.subprocess.PIPE)
    output, _ = await asyncio.wait_for(child.communicate(), timeout=10)
    assert child.returncode == 0 and output.strip()
    start = monotonic()
    release = asyncio.Event()
    receipts: list[Receipt] = []
    managed_runs: dict[str, ManagedRun] = {}
    batch_size = int(os.environ.get("QUALIFICATION_BATCH_SIZE", "0"))
    if batch_size and not settings.CONVERSATION_WORKER_CONCURRENCY < batch_size <= 24:
        raise ValueError("The paired load batch must exceed the conversation worker count and contain at most 24 rooms")
    load = {driver: tuple(f"SYNTHETIC-BURST-{driver}-{index:02d}-INPUT" for index in range(batch_size))
            for driver in ("internal", "claude_embedded")} if batch_size else {}
    load_inputs = frozenset(marker for markers in load.values() for marker in markers)
    managed_images = {provider: image for provider in MANAGED_PROVIDERS
                      if (image := os.environ.get(f"QUALIFICATION_IMAGE_{provider}"))}
    if managed_images and set(managed_images) != set(MANAGED_PROVIDERS):
        raise ValueError("Select both real managed runtime images for this qualification")
    real_managed = bool(managed_images)
    async with server(provider_app(receipts, release, load_inputs, managed_runs, real_managed=real_managed)) as model_url:
        agent, model, token = await seed(model_url)
        comparison_agents = await seed_comparison_agents(agent, model_url, real_managed=real_managed)
        async with server(app, port=8000, lifespan="on", bind="0.0.0.0" if real_managed else "127.0.0.1") as origin:
            journal, burst_metrics, managed_tasks, linked = await exercise(origin, agent, model, token, receipts, release,
                                                                          load, comparison_agents, managed_runs,
                                                                          real_managed=real_managed)
    assert not list(Path("/data").glob("claude-turn-*")), "The SDK workspaces must be removed"
    print(json.dumps({"revision": revision, "image": os.environ["QUALIFICATION_BACKEND_IMAGE"],
                      "python": platform.python_version(), "architecture": platform.machine(),
                      "sdk": version("claude-agent-sdk"), "cli": output.decode().strip(),
                      "elapsed_seconds": round(monotonic() - start, 3), "provider_receipts": len(receipts),
                      "unique_journal_calls": len(journal), "operations": journal,
                      "conversation_workers": settings.CONVERSATION_WORKER_CONCURRENCY, "bursts": burst_metrics,
                      "managed_tasks": managed_tasks,
                      "linked_tasks": {key: value for key, value in linked.items() if ":" not in key},
                      "tool_tasks": {key.removeprefix("tool:"): value for key, value in linked.items() if key.startswith("tool:")},
                      "reviewed_tools": {key: value for key, value in linked.items() if key.split(":", 1)[0] in REVIEW_TASK_INPUTS},
                      "managed_images": managed_images}))


if __name__ == "__main__":
    asyncio.run(main())
