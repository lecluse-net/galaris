"""Public reference cases stay executable through the same Lab contracts as the UI."""
import json
from pathlib import Path

import pytest

from app.lab import mechanism_evaluation_service as service
from app.lab.models import LabEvaluationDataset
from app.lab.schemas import EvaluationCaseCreate, MechanismCaseUpdate
from app.lab.contracts import resolve_input
from app.lab.objective_checks import check_output


@pytest.mark.asyncio
@pytest.mark.parametrize("corpus_name, count", [
    ("reference", 6), ("latency-fr", 4), ("latency-en", 4), ("dispatcher-boundaries", 10),
])
async def test_reference_import_uses_http_authorization_and_never_overwrites(client, corpus_name, count):
    import httpx
    from scripts.import_lab_reference import install

    with pytest.raises(httpx.HTTPStatusError):
        await install(client, corpus_name)
    credentials = {"email": "reference-admin@example.com", "password": "reference-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    result = await install(client, corpus_name)
    assert result["cases"] == count
    assert result["model_calls"] == 0
    with pytest.raises(ValueError, match="already exists"):
        await install(client, corpus_name)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", [
    "reference_corpus.json", "latency_corpus_fr.json", "latency_corpus_en.json",
    "dispatcher_boundaries_corpus.json",
])
async def test_reference_corpus_can_be_saved_resolved_and_checked(db, filename):
    corpus = json.loads((Path(__file__).parents[1] / filename).read_text())
    dataset = LabEvaluationDataset(
        name=corpus["name"], mechanism=corpus["mechanism"],
        purpose=corpus["purpose"], parameters=corpus["parameters"],
    )
    db.add(dataset)
    await db.commit()
    for case in corpus["cases"]:
        saved = await service.create_case(corpus["mechanism"], dataset.id, EvaluationCaseCreate(name=case["name"]))
        saved = await service.update_case(corpus["mechanism"], saved.id, MechanismCaseUpdate(
            revision=saved.revision, **case,
        ))
        _, native = resolve_input(corpus["mechanism"], saved.input_data, corpus["parameters"])
        if corpus["mechanism"] in {"dispatcher"}:
            assert native["objective"].startswith("<p>")
        else:
            assert native["message"] == case["input_data"]["variable_value"]
            assert native["tool_responses"] == corpus["parameters"]["tool_responses"]
        assert "expected_output" not in native
        checks = check_output(corpus["mechanism"], native, saved.expected_output)
        assert all(row["passed"] for row in checks), checks
        assert saved.categories == case["categories"]


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["fr", "en"])
async def test_latency_campaign_uses_native_effect_free_tools_and_separate_measurements(monkeypatch, language):
    from types import SimpleNamespace
    from pydantic_ai import UsageLimits
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel
    from app.llm import structured_service
    from app.lab.mechanism_registry import evaluate_mechanism, get_mechanism

    corpus = json.loads((Path(__file__).parents[1] / f"latency_corpus_{language}.json").read_text())
    calls = [None, ("memory_search", {"query": "Orbe"}),
        ("conversation_task_status", {"task_id": "galaris://task/00000000-0000-0000-0000-000000000041"}),
        ("conversation_task_submit", {"objective": "<p>Compare Orbe, Nacre and Sillage, sources, costs and final report.</p>"})]
    monkeypatch.setattr(structured_service, "UsageLimits", lambda **kw: UsageLimits(**{**kw, "count_tokens_before_request": False}))
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0.01)
    for case, proposed in zip(corpus["cases"], calls, strict=True):
        step = 0

        async def stream(_messages, _info):
            nonlocal step
            step += 1
            if proposed and step == 1:
                yield {0: DeltaToolCall(name=proposed[0], json_args=json.dumps(proposed[1]))}
            else:
                yield "Synthetic final answer."

        async def build(*_args, **_kwargs):
            return FunctionModel(stream_function=stream)

        monkeypatch.setattr(structured_service, "build_model_for_llm", build)
        _, native = resolve_input(corpus["mechanism"], case["input_data"], corpus["parameters"])
        observations = {}
        with structured_service.reasoning_effort_scope(None):
            actual, cost = await evaluate_mechanism(get_mechanism(corpus["mechanism"]), input_data=native,
                llm=SimpleNamespace(), system_prompt_override="Synthetic conversation benchmark.", observations=observations)
        assert actual["action"] == case["expected_output"]["action"]
        assert cost == 0.01
        assert observations["performance"]["first_output_seconds"] >= 0
        assert "performance" not in actual
        if proposed:
            assert actual["tool_calls"] == [{"name": proposed[0], "arguments": proposed[1]}]
            assert actual["tool_results"][0]["result"] == corpus["parameters"]["tool_responses"][proposed[0]][0]
        else:
            assert actual["tool_calls"] == actual["tool_results"] == []
