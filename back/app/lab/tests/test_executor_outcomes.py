"""Outcome qualification must distinguish useful effects from plausible narration."""

from types import SimpleNamespace

import pytest

from app.lab.mechanism_registry import recording_tools
from app.lab.objective_checks import check_output


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [["conversation_task_status"], []])
async def test_foreground_benchmark_exposes_only_the_declared_capabilities(monkeypatch, available):
    from app.lab import mechanism_registry as registry

    async def infer(**kwargs):
        assert [tool.__name__ for tool in kwargs["tools"]] == available
        return SimpleNamespace(output="No action performed.", cost=0, tool_calls=[])

    monkeypatch.setattr(registry, "run_text_with_tools", infer)
    await registry.evaluate_mechanism(registry.get_mechanism("conversation_executor"),
        input_data={"message": "Check current work.", "available_tools": available},
        llm=SimpleNamespace(), system_prompt_override="Synthetic test.")


def test_unavailable_fixture_cannot_grant_a_foreground_capability():
    with pytest.raises(ValueError, match="unavailable"):
        recording_tools("conversation", {"conversation_task_submit": [{}]}, [],
                        available_tools=["conversation_task_status"])


@pytest.mark.asyncio
async def test_task_fixtures_follow_the_selected_function_and_reject_unavailable_effects():
    transcript = []
    read, edited = {"content": "Original", "revision": 7}, {"revision": 8, "success": True}
    tool, = recording_tools("task", {"file_read": [read], "file_edit": [edited]}, transcript,
                           available_tools=["file_read", "file_edit"])
    # Order comes from the candidate's choices; a write never receives a read's result.
    assert await tool(tool_name="file_edit", arguments={"expected_revision": 7}) == edited
    assert await tool(tool_name="file_read", arguments={}) == read
    with pytest.raises(ValueError, match="exhausted"):
        await tool(tool_name="file_edit", arguments={"expected_revision": 7})
    with pytest.raises(ValueError, match="unavailable"):
        await tool(tool_name="file_create", arguments={})
    assert len(transcript) == 2


@pytest.mark.asyncio
async def test_native_contract_rejects_incomplete_calls_without_consuming_success(monkeypatch):
    import json
    from pydantic_ai import UsageLimits
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel
    from app.llm import structured_service
    from app.lab.mechanism_registry import evaluate_mechanism, get_mechanism

    schema = {"type": "object", "properties": {"expected_revision": {"type": "integer"}, "uri": {"type": "string"}},
              "required": ["expected_revision", "uri"], "additionalProperties": False}
    step = 0

    async def stream(_messages, info):
        nonlocal step
        step += 1
        assert [(tool.name, tool.parameters_json_schema) for tool in info.function_tools] == [("file_edit", schema)]
        if step <= 3:
            arguments = {} if step == 1 else {"expected_revision": 7, "uri": "document://wrong" if step == 2 else "document://synthetic"}
            yield {0: DeltaToolCall(name="file_edit", json_args=json.dumps(arguments))}
        else:
            yield "Verified correction."

    async def build(*_args, **_kwargs):
        return FunctionModel(stream_function=stream)

    monkeypatch.setattr(structured_service, "build_model_for_llm", build)
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0)
    monkeypatch.setattr(structured_service, "UsageLimits", lambda **kw: UsageLimits(**{**kw, "count_tokens_before_request": False}))
    native = {"message": "Correct revision 7.", "available_tools": ["file_edit"], "tool_calls_limit": 4,
              "tool_catalog": [{"name": "file_edit", "parameters": schema}],
              "tool_responses": {"file_edit": [{"success": True, "revision": 8}]},
              "tool_response_arguments": {"file_edit": [{"uri": "document://synthetic", "expected_revision": 7}]}}
    with structured_service.reasoning_effort_scope(None):
        output, _ = await evaluate_mechanism(get_mechanism("task_executor"), input_data=native,
            llm=SimpleNamespace(), system_prompt_override="Synthetic native contracts.", observations={})
    assert output["tool_results"][0]["result"]["error"] == "invalid_tool_arguments"
    assert output["tool_results"][1]["result"]["error"] == "simulation_fixture_unavailable"
    assert output["tool_results"][2]["result"] == {"success": True, "revision": 8}


def test_reading_a_goal_cannot_consume_another_documents_revision_sequence():
    from app.lab.executor_fixtures import ToolFixtureSequence
    sequence = ToolFixtureSequence([{"revision": 7}, {"criteria": "complete"}, {"revision": 8}],
        [{"uri": "document://synthetic"}, {"uri": "galaris://goal/synthetic"}, {"uri": "document://synthetic"}])
    assert sequence.take({"uri": "galaris://goal/synthetic"}) == {"criteria": "complete"}
    assert sequence.take({"uri": "document://other"})["success"] is False
    assert sequence.take({"uri": "document://synthetic"}) == {"revision": 7}
    assert sequence.take({"uri": "document://synthetic"}) == {"revision": 8}
    assert sequence.take({"uri": "document://synthetic"})["success"] is False


@pytest.mark.asyncio
async def test_verification_reads_the_written_content_without_leaking_into_another_case():
    catalog = [
        {"name": "file_create", "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "file_read", "parameters": {"type": "object", "properties": {"uri": {"type": "string"}}, "required": ["uri"]}},
    ]
    transcript = []
    create, read = recording_tools("task", {"file_create": [{"uri": "document://synthetic", "revision": 1}]},
        transcript, available_tools=["file_create", "file_read"], tool_catalog=catalog)
    content = "<p>The candidate's actual content, with source SYN-42.</p>"
    assert await create.function(path="document://", content=content) == {"uri": "document://synthetic", "revision": 1}
    result = await read.function(uri="document://synthetic")
    assert result["content"] == content and result["revision"] == 1
    _, another_read = recording_tools("task", {}, [], available_tools=["file_create", "file_read"], tool_catalog=catalog)
    assert (await another_read.function(uri="document://synthetic"))["success"] is False
    assert len(transcript) == 2


def test_scripted_read_denial_overrides_a_recent_write_and_prevents_cached_retry():
    from app.lab.executor_fixtures import ExecutorToolResponses
    simulation = ExecutorToolResponses(
        {"file_create": [{"uri": "document://synthetic", "revision": 1}],
         "file_read": [{"success": False, "error": "permission_denied"}]},
        {"file_create": [{"path": "document://"}], "file_read": [{"uri": "document://synthetic"}]})
    simulation.take("file_create", {"path": "document://", "content": "<p>Synthetic content.</p>"})
    assert simulation.take("file_read", {"uri": "document://synthetic"}) == {"success": False, "error": "permission_denied"}
    assert simulation.take("file_read", {"uri": "document://synthetic"})["success"] is False


def test_synthetic_reference_validation_accepts_verification_of_its_own_written_content():
    import json
    from pathlib import Path
    from app.lab.synthetic_service import validate_content
    from app.lab.synthetic_schemas import SyntheticContent, SyntheticDatasetRequest

    corpus = json.loads((Path(__file__).parents[1] / "outcome_capabilities_corpus_en.json").read_text())
    case = next(row for row in corpus["cases"] if row["name"] == "necessary-distinct-deliverables-en")
    case["categories"] = ["nominal"]
    output = case["expected_output"]
    uri = output["tool_results"][0]["result"]["uri"]
    content = output["tool_calls"][0]["arguments"]["content"]
    call = {"name": "file_read", "arguments": {"uri": uri}}
    output["tool_calls"].append(call)
    output["tool_results"].append({**call, "result": {"uri": uri, "content": content, "revision": 1, "complete": True}})
    draft = SyntheticContent.model_validate({"description": "Synthetic verification journey.",
        "parameters": corpus["parameters"], "cases": [case]})
    validated = validate_content("task_executor", SyntheticDatasetRequest(name="Verification", count=1, categories=["nominal"]), draft)
    assert validated.cases[0].expected_output["tool_results"][-1]["result"]["content"] == content


@pytest.mark.parametrize("question,valid", [
    ("Current cost: 23 EUR. Early or late?", True),
    ("Current cost: €23. Early or late?", True),
    ("Current cost: 23 USD. Early or late?", False),
    ("Current currency: EUR. Early or late?", False),
    ("Current cost: 23. Early or late?", False),
    ("Current cost: €24. Early or late?", False),
    (None, False),
])
def test_question_facts_accept_explicit_currency_aliases_without_losing_amount_or_currency(question, valid):
    output = _trace([_call("goal_ask_referrer", question=question)])
    expected = {"outcome_checks": {"required_calls": [{
        "tool": "goal_ask_referrer", "argument_values": {"question": ["23"]},
        "argument_any_values": {"question": ["EUR", "€"]},
    }]}}
    checks = check_output("task_executor", {"available_tools": ["goal_ask_referrer"]}, output, expected=expected)
    assert next(row for row in checks if row["code"] == "outcome_call_1")["passed"] is valid


def test_a_refused_write_cannot_satisfy_a_required_effect():
    output = _trace([_call("file_edit", expected_revision=7)])
    output["tool_results"][0]["result"] = {"success": False, "error": "revision_conflict"}
    expected = {"outcome_checks": {"required_calls": [{"tool": "file_edit"}]}}
    assert not all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_edit"]}, output, expected=expected))
    expected["outcome_checks"]["required_calls"][0]["successful"] = False
    assert all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_edit"]}, output, expected=expected))


@pytest.mark.parametrize("content,valid", [
    ('{"quantity":17,"currency":"EUR"}', True),
    ('{"quantity":170,"currency":"EUR"}', False),
    ('{"quantity":"17","currency":"EUR"}', False),
    ('{"quantity":17}', False), ('17 EUR', False),
])
def test_structured_outcome_requires_valid_json_exact_values_and_preserved_fields(content, valid):
    expected = {"outcome_checks": {"required_calls": [{"tool": "file_edit",
        "argument_json": {"content": {"quantity": 17, "currency": "EUR"}}}]}}
    output = _trace([_call("file_edit", content=content)])
    assert all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_edit"]}, output, expected=expected)) is valid


def _trace(calls):
    return {"action": "use_tool", "response": "Verified 17 units.", "tool_calls": calls,
            "tool_results": [{**call, "result": {"success": True}} for call in calls]}


def _call(tool_name, **arguments):
    return {"name": "executor_tool_call", "arguments": {"tool_name": tool_name, "arguments": arguments}}


@pytest.mark.parametrize("defect", [None, "missing", "duplicate", "wrong_target", "wrong_revision", "wrong_order", "lost_fact", "lost_contribution", "forged_receipt"])
def test_outcome_checks_detect_missing_work_and_unnecessary_or_unsafe_writes(defect):
    uri = "document://00000000-0000-0000-0000-000000000017"
    calls = [_call("file_read", uri=uri), _call("file_edit", uri=uri, expected_revision=7, content="17 units, audit PKG-9")]
    expected = {"outcome_checks": {
        "required_calls": [{"tool": "file_read", "arguments": {"uri": uri}},
                           {"tool": "file_edit", "arguments": {"uri": uri, "expected_revision": 7},
                            "argument_values": {"content": ["17", "PKG-9"]}}],
        "forbidden_tools": ["file_create"], "max_tool_calls": 3, "response_values": ["17"],
    }}
    if defect == "missing":
        calls.pop()
    elif defect == "duplicate":
        calls.append(_call("file_create", path="document://"))
    elif defect == "wrong_target":
        calls[1] = _call("file_edit", uri="document://other", expected_revision=7)
    elif defect == "wrong_revision":
        calls[1] = _call("file_edit", uri=uri, expected_revision=6)
    elif defect == "wrong_order":
        calls.reverse()
    elif defect == "lost_contribution":
        calls[1]["arguments"]["arguments"]["content"] = "17 units"
    output = _trace(calls)
    if defect == "lost_fact":
        output["response"] = "Done."
    elif defect == "forged_receipt":
        output["tool_results"][0]["arguments"] = {"tool_name": "file_create"}
    checks = check_output("task_executor", {"available_tools": ["file_read", "file_edit", "file_create"]},
                          output, expected=expected)
    assert all(check["passed"] for check in checks) is (defect is None)


def test_quality_checks_do_not_force_every_result_into_a_document():
    expected = {"outcome_checks": {"max_tool_calls": 0, "response_values": ["56"]}}
    result = {"action": "reply", "response": "56", "tool_calls": [], "tool_results": []}
    assert all(row["passed"] for row in check_output("conversation_executor", {}, result, expected=expected))


def test_preserving_two_deliverables_does_not_allow_a_third_creation():
    expected = {"outcome_checks": {"required_calls": [{"tool": "file_create"}, {"tool": "file_create"}],
                                    "tool_call_limits": {"file_create": 2}}}
    output = _trace([_call("file_create") for _ in range(3)])
    assert not all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_create"]}, output, expected=expected))
    output["tool_calls"].pop(); output["tool_results"].pop()
    assert all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_create"]}, output, expected=expected))


@pytest.mark.parametrize("defect", [None, "reverse", "placeholder", "missing_fact", "audience_leak", "same_resource"])
def test_two_deliverables_preserve_their_facts_and_audiences_in_either_creation_order(defect):
    calls = [_call("file_create", content="<p>09:00, SYN-42</p>"),
             _call("file_create", content="<p>PKG-9 pending, 17 units confirmed.</p>")]
    expected = {"outcome_checks": {"ordered_calls": False, "required_calls": [
        {"tool": "file_create", "argument_values": {"content": ["09:00", "SYN-42"]},
         "argument_forbidden_values": {"content": ["PKG-9"]}},
        {"tool": "file_create", "argument_values": {"content": ["PKG-9", "17"]}},
    ]}}
    if defect == "reverse":
        calls.reverse()
    elif defect == "placeholder":
        calls[0]["arguments"]["arguments"]["content"] = "<p>Content to be supplied.</p>"
    elif defect == "missing_fact":
        calls[1]["arguments"]["arguments"]["content"] = "<p>PKG-9 pending.</p>"
    elif defect == "audience_leak":
        calls[0]["arguments"]["arguments"]["content"] += "<p>Confidential PKG-9.</p>"
    elif defect == "same_resource":
        calls = [_call("file_create", content="09:00 SYN-42 PKG-9 17")]
    output = _trace(calls)
    assert all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_create"]}, output, expected=expected)) is (defect in {None, "reverse"})


def test_unordered_requirements_assign_distinct_calls_even_when_conditions_overlap():
    expected = {"outcome_checks": {"ordered_calls": False, "required_calls": [
        {"tool": "file_create"}, {"tool": "file_create", "arguments": {"name": "Internal"}},
    ]}}
    output = _trace([_call("file_create", name="Internal"), _call("file_create", name="Public")])
    assert all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_create"]}, output, expected=expected))


def test_an_unrelated_tool_receipt_is_not_evidence_of_the_claimed_effect():
    result = _trace([_call("file_edit", expected_revision=7)])
    result["tool_results"][0]["arguments"] = {"tool_name": "file_read"}
    assert not all(row["passed"] for row in check_output("task_executor", {"available_tools": ["file_edit"]}, result))


@pytest.mark.asyncio
async def test_persisted_lab_verdict_rejects_missing_work_even_with_a_perfect_judge(db, monkeypatch):
    from uuid import uuid4
    from sqlalchemy import select
    from pydantic_ai import ModelResponse, TextPart, ToolCallPart, UsageLimits
    from pydantic_ai.models.function import FunctionModel
    from app.llm import LLM, LLMProvider, structured_service
    from app.lab import mechanism_evaluation_service as service
    from app.lab.mechanism_rubrics import get_rubric
    from app.lab.models import LabEvaluationRunCase
    from app.lab.schemas import MechanismDatasetCreate, EvaluationDatasetUpdate, EvaluationCaseCreate, MechanismCaseUpdate, EvaluationRunStart

    def model(_messages, info):
        if info.output_tools:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                "explanation": "Synthetic judge accepts the confident answer.", "critical_failures": [],
                "confidence_percent": 100,
                "dimensions": [{"code": dim.code, "score_percent": 100, "assessment": "Accepted"}
                               for dim in get_rubric("task_executor").dimensions],
            })])
        return ModelResponse(parts=[TextPart("Everything is complete.")])

    async def build(*_args, **_kwargs):
        async def stream(_messages, _info):
            yield "Everything is complete."
        return FunctionModel(model, stream_function=stream)

    monkeypatch.setattr(structured_service, "build_model_for_llm", build)
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0)
    monkeypatch.setattr(structured_service, "UsageLimits", lambda **kw: UsageLimits(**{**kw, "count_tokens_before_request": False}))
    provider = LLMProvider(name="synthetic-" + uuid4().hex, base_url="https://example.test/v1", is_active=True)
    db.add(provider)
    await db.flush()
    llm = LLM(llm_provider_id=provider.id, provider=provider, code="synthetic-" + uuid4().hex,
              llm_name="synthetic", label="Synthetic", service_capabilities=["chat"])
    db.add(llm)
    await db.commit()
    dataset = await service.create_dataset("task_executor", MechanismDatasetCreate(name="Outcome " + uuid4().hex))
    dataset = await service.update_dataset("task_executor", dataset.id, EvaluationDatasetUpdate(
        revision=dataset.revision, name=dataset.name, parameters={"available_tools": ["file_edit"]}))
    case = await service.create_case("task_executor", dataset.id, EvaluationCaseCreate(name="Missing required correction"))
    await service.update_case("task_executor", case.id, MechanismCaseUpdate(revision=case.revision,
        input_data={"variable_value": "<p>Correct the shared quantity.</p>"},
        expected_output={"outcome_checks": {"required_calls": [{"tool": "file_edit"}]}}))
    run = await service.start_run("task_executor", dataset.id, EvaluationRunStart(llm_id=llm.id, judge_llm_id=llm.id))
    assert await service.process_runs() == 1
    assert await service.process_runs() == 1
    row = await db.scalar(select(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == run.id))
    assert row.score_percent == 100 and row.verdict == "fail", (row.error, row.judge_output, row.score_details)
    assert row.actual_output["tool_calls"] == []
    assert any(check["code"] == "outcome_call_1" and not check["passed"] for check in row.score_details["checks"])
