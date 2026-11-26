"""Qualify the benchmark through the live Chat/Task APIs and bundled SDK."""

import json
import re
from pathlib import Path
from uuid import uuid4

from httpx import AsyncClient, MockTransport, Response
import pytest
from sqlalchemy import select

from app.agent import Agent, Title
from app.connection import Connection
from app.connection.models import ConnectionFunctionState
from app.conversation import controller as round_controller
from app.conversation import scheduler as round_scheduler
from app.harness import claude_driver
from app.harness.conversation import HarnessConversationController
from app.llm import profile_service
from app.llm.profile_models import LlmProfile
from app.services import ServiceModel
from app.task import scheduler as task_scheduler
from core.authorize import Assignment, Role
from core.database import middleware
from core.params import runtime_settings
from core.user.auth_service import create_access_token_for_user
from core.user.models import User
from main import app
from scripts.benchmark_embedded_harnesses import Benchmark, Campaign, Case, run
from tests.test_embedded_claude_chat_effects import _http_server
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


def test_changing_an_expected_answer_does_not_create_a_distinct_benchmark_input():
    prompt = "Return my synthetic parcel count."
    with pytest.raises(ValueError, match="distinct model input"):
        Case.model_validate({
            "key": "same-input", "family": "task", "turns": [{"prompt": prompt, "expected": "4"}],
            "variants": [{"turns": [{"prompt": prompt, "expected": answer}]} for answer in ("4", "5")],
        })


@pytest.mark.asyncio
async def test_model_snapshot_ignores_pricing_poll_but_detects_a_changed_binding():
    example = Path(__file__).parents[1] / "lab-embedded-harnesses.example.json"
    campaign = Campaign.model_validate_json(example.read_bytes())
    model = {"id": campaign.model_id, "llm_provider_id": 9, "llm_name": "synthetic-model",
             "input_image": False, "cost_per_input_token": 0, "updated_at": "2026-11-26T10:14:00Z"}
    provider = {"id": 9, "is_active": True, "base_url": "http://127.0.0.1:8081",
                "updated_at": "2026-11-26T10:14:00Z"}

    def respond(request):
        bodies = {f"/api/llm-providers/llms/{model['id']}": model, "/api/llm-providers/9": provider}
        return Response(200, json=bodies[request.url.path])

    async with AsyncClient(transport=MockTransport(respond), base_url="http://127.0.0.1") as client:
        benchmark = Benchmark(client, campaign, lambda _: None)
        original = await benchmark.model_snapshot()
        model.update(updated_at="2026-11-26T10:44:00Z", pricing_last_attempt_at="2026-11-26T10:44:00Z",
                     pricing_refresh_error="unavailable")
        assert await benchmark.model_snapshot() == original

        model["cost_per_input_token"] = 1.5
        assert await benchmark.model_snapshot() != original
        model["cost_per_input_token"] = 0
        model["input_image"] = True
        assert await benchmark.model_snapshot() != original
        model["input_image"] = False
        provider["updated_at"] = "2026-11-26T10:45:00Z"
        assert await benchmark.model_snapshot() != original
        provider["updated_at"] = "2026-11-26T10:14:00Z"
        provider["base_url"] = "http://127.0.0.1:8082"
        assert await benchmark.model_snapshot() != original


@pytest.mark.asyncio
async def test_benchmark_pairs_real_harnesses_at_both_normal_entry_points(runtime, committed_database, monkeypatch, tmp_path):
    db, model, physical_requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(round_controller, "_controller", HarnessConversationController())
    mode["concurrent"] = True
    model.provider.max_concurrent_calls = 3

    user = User(email=f"bench-{uuid4().hex}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic comparison", text_low_llm_id=model.id, text_standard_llm_id=model.id,
                         text_low_reasoning_effort="low", text_standard_reasoning_effort="low")
    db.add_all([user, profile])
    await db.flush()
    role = await db.scalar(select(Role).where(Role.code == "admin"))
    title = await db.scalar(select(Title.id).limit(1))
    service = await db.scalar(select(ServiceModel).where(ServiceModel.code == "chat"))
    files = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    assert role is not None and title is not None and service is not None and files is not None
    db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
    agents = [Agent(user_id=user.id, title_id=title, code=f"bench-{uuid4().hex}", first_name="Synthetic",
                    last_name="Benchmark", profile_id=profile.id, agent_driver=driver)
              for driver in ("internal", "claude_embedded")]
    db.add_all(agents)
    await db.flush()
    db.add_all(Connection(service_id=service.id, agent_id=agent.id, active=True) for agent in agents)
    file_connections = [Connection(service_id=files.id, agent_id=agent.id, active=True) for agent in agents]
    db.add_all(file_connections)
    await db.flush()
    db.add_all(ConnectionFunctionState(connection_id=connection.id, function_name="file_create", state="enabled", enabled=True)
               for connection in file_connections)
    await db.commit()
    assert await profile_service.set_current_profile_id(profile.id)
    token = await create_access_token_for_user(user, db, role_id=role.id)
    await db.commit()

    content = {"count": 7, "complete": False}

    def choose_tools(body):
        messages = body["messages"]
        if any(message["role"] == "tool" for message in messages):
            return []
        marker = re.search(r"Harness-dataset-write-[0-9a-f]{32}", json.dumps(messages))
        if marker is None:
            return []
        [name] = [item["function"]["name"] for item in body["tools"]
                  if item["function"]["name"].endswith("file_create")]
        return [("synthetic-dataset-create", name,
                 {"path": "data://", "name": marker.group(), "content": json.dumps(content)})]

    mode["tool_calls_for"] = choose_tools
    campaign = Campaign.model_validate({
        "image_revision": "synthetic-image", "internal_agent": agents[0].id, "claude_agent": agents[1].id,
        "model_id": model.id, "model_site": "local", "repetitions": 2, "max_legs": 16,
        "max_observed_cost": 100, "operation_timeout": 25,
        "cases": [
            {"key": "chat-pilot", "family": "conversation", "turns": [
                {"prompt": "Synthetic first utterance", "expected": "Bonjour !"},
                {"prompt": "Synthetic follow-up utterance", "expected": "Bonjour !"},
            ], "variants": [{"turns": [
                {"prompt": f"Synthetic {marker} first utterance", "expected": "Bonjour !"},
                {"prompt": "Synthetic follow-up utterance", "expected": "Bonjour !"},
            ]} for marker in ("QUILL", "MAPLE")]},
            {"key": "task-pilot", "family": "task", "turns": [
                {"prompt": "Synthetic direct objective", "expected": "Bonjour !"},
            ]},
            {"key": "dataset-write", "family": "task", "expected_dataset": content, "turns": [
                {"prompt": "Create the synthetic Data document, then say Bonjour !", "expected": "Bonjour !"},
            ]},
            {"key": "dataset-omitted", "family": "task", "expected_dataset": content, "turns": [
                {"prompt": "Create the other synthetic Data document, then say Bonjour !", "expected": "Bonjour !"},
            ]},
        ],
    })
    evidence = []
    round_scheduler.start()
    task_scheduler.start()
    try:
        async with _http_server(app) as origin, AsyncClient(
            base_url=origin, headers={"Authorization": f"Bearer {token}", "X-Editorial-Profile-Version": "1"},
            timeout=30, trust_env=False,
        ) as client:
            monkeypatch.setattr(claude_driver, "CLAUDE_GATEWAY", f"{origin}/api/llm/anthropic")
            await run(Benchmark(client, campaign, evidence.append), evidence.append)
    finally:
        await round_scheduler.stop()
        await task_scheduler.stop()

    orders = [(row["pair"], row["driver"]) for row in evidence if row["event"] == "leg_started"]
    assert orders == [
        ("chat-pilot/1", "internal"), ("chat-pilot/1", "claude_embedded"),
        ("task-pilot/1", "claude_embedded"), ("task-pilot/1", "internal"),
        ("dataset-write/1", "internal"), ("dataset-write/1", "claude_embedded"),
        ("dataset-omitted/1", "claude_embedded"), ("dataset-omitted/1", "internal"),
        ("chat-pilot/2", "claude_embedded"), ("chat-pilot/2", "internal"),
        ("task-pilot/2", "internal"), ("task-pilot/2", "claude_embedded"),
        ("dataset-write/2", "claude_embedded"), ("dataset-write/2", "internal"),
        ("dataset-omitted/2", "internal"), ("dataset-omitted/2", "claude_embedded"),
    ]
    observations = [item for row in evidence if row["event"] == "leg_finished" for item in row["observations"]]
    assert len({item["operation_id"] for item in observations}) == 20
    assert all(item["matched"] for item in observations)
    # The provider sends reasoning before its first text fragment or tool call.
    assert all(0 <= item["first_token_seconds"] < item["first_output_seconds"] <= item["elapsed_seconds"]
               for item in observations)
    assert len(physical_requests) >= len(observations)
    writes = [row for row in evidence if row["event"] == "leg_finished" and row["pair"].startswith("dataset-write/")]
    assert len(writes) == 4 and all(row["metrics"]["passed"] for row in writes)
    proofs = [row["observations"][0]["dataset"] for row in writes]
    assert {proof["status"] for proof in proofs} == {"confirmed"}
    assert len({proof["new_ids"][0] for proof in proofs}) == 4
    assert proofs[0]["title"] == proofs[1]["title"] != proofs[2]["title"] == proofs[3]["title"]
    omissions = [row for row in evidence if row["event"] == "leg_finished" and row["pair"].startswith("dataset-omitted/")]
    assert len(omissions) == 4
    assert all(row["metrics"]["false_success"] and not row["metrics"]["passed"] for row in omissions)
    assert all(row["observations"][0]["dataset"]["status"] == "missing" for row in omissions)
    assert evidence[-1]["event"] == "summary" and evidence[-1]["pairs"] == 8
    assert all(not family["discordant"] for family in evidence[-1]["families"].values())
    chat_pairs = [row for row in evidence if row["event"] == "leg_finished" and row["pair"].startswith("chat-pilot/")]
    assert chat_pairs[0]["input_sha256"] == chat_pairs[1]["input_sha256"]
    assert chat_pairs[2]["input_sha256"] == chat_pairs[3]["input_sha256"] != chat_pairs[0]["input_sha256"]
    for marker in ("QUILL", "MAPLE"):
        initial = f"Synthetic {marker} first utterance"
        assert sum(initial in json.dumps(body["messages"]) for body in physical_requests) >= 2
    assert all("Synthetic first utterance" not in json.dumps(body["messages"]) for body in physical_requests)
    families = evidence[-1]["families"]
    for family in families.values():
        for driver in ("internal", "claude_embedded"):
            timing = family[driver]
            assert timing["first_output_samples"] == timing["first_token_samples"] > 0
            assert timing["first_output_median_seconds"] > timing["first_token_median_seconds"]
            assert timing["first_output_p95_seconds"] > timing["first_token_p95_seconds"]
    varied = families["conversation"]["scenarios"]["chat-pilot"]
    repeated = families["task"]["scenarios"]["dataset-write"]
    assert varied["distinct_inputs"] == 2 and varied["success_rate_interval_95"] is not None
    assert repeated["distinct_inputs"] == 1 and repeated["success_rate_interval_95"] is None
    assert repeated["success_noninferiority_supported"] is False
