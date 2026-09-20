"""Provider compatibility is verified at the outgoing HTTP boundary, without paid calls."""

from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import json

import httpx
import httpx2
import anyio
import pytest
from openai.types.chat.completion_create_params import CompletionCreateParamsNonStreaming, CompletionCreateParamsStreaming
from openai.types.responses.response_create_params import ResponseCreateParamsNonStreaming, ResponseCreateParamsStreaming

from app.llm import proxy_service
from app.llm.provider_catalog import PROVIDER_CATALOG, get_provider_profile
from app.llm.provider_facade import (
    ProviderConnection, adapt_request_parameters, request_parameter_policy_for,
)
from app.llm import provider_facade, request_parameters
from app.llm import pydantic_ai_utils
from app.llm.provider_models import LLM, LLMProvider
from pydantic_ai import Agent, PromptedOutput, UsageLimits
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic import BaseModel, Field


# Independent reviewed endpoint vocabulary. Never generate this fixture from production
# policies: a new globally allowed field must fail the strict fake server until reviewed.
CONTRACTS = json.loads((Path(__file__).parent / "fixtures/provider_parameters.json").read_text())
PROBES = [(name, {name: value}) for name, value in CONTRACTS["controls"].items()]
PROBES += [(f"{parent}.{key}", {parent: {key: value}})
    for parent, fields in CONTRACTS["nested"].items() for key, value in fields.items()]


@pytest.fixture(autouse=True)
def forbid_real_provider_http(monkeypatch):
    async def blocked(*args, **kwargs):
        pytest.fail("Provider contract tests must use a simulated HTTP transport; real network is forbidden.")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", blocked)


def assert_review_coverage():
    assert set(CONTRACTS["controls"]) == request_parameters.CONTROL_PARAMETERS, (
        "Every generation parameter needs a reviewed probe in fixtures/provider_parameters.json."
    )
    assert set(CONTRACTS["payload"].split()) == request_parameters.PAYLOAD_PARAMETERS
    assert {name: frozenset(fields) for name, fields in CONTRACTS["nested"].items()} == request_parameters.NESTED_PARAMETERS


def assert_endpoint_contract(code, protocol, body):
    allowed = set(CONTRACTS["envelopes"][protocol].split()) | set(CONTRACTS["providers"][code][protocol].split())
    assert set(body) <= allowed, f"{code}/{protocol}: unreviewed outgoing fields {set(body) - allowed}"
    for name, fields in CONTRACTS["nested"].items():
        if isinstance(body.get(name), dict):
            assert set(body[name]) <= set(fields), f"{code}/{protocol}: unreviewed {name} fields"


def test_every_parameter_has_a_reviewed_probe():
    assert_review_coverage()


@pytest.mark.parametrize("protocol,schemas", [
    ("chat", (CompletionCreateParamsNonStreaming, CompletionCreateParamsStreaming)),
    ("responses", (ResponseCreateParamsNonStreaming, ResponseCreateParamsStreaming)),
])
def test_sdk_extension_fields_are_not_blocked_by_galaris(protocol, schemas):
    fields = set().union(*(schema.__annotations__ for schema in schemas))
    classified = request_parameters.CONTROL_PARAMETERS | request_parameters.PAYLOAD_PARAMETERS
    policy = request_parameters.RequestParameterPolicy()
    for field in fields - classified:
        assert adapt_request_parameters({field: None}, policy, protocol) == {field: None}


def test_review_gate_detects_a_new_control_without_a_probe(monkeypatch):
    monkeypatch.setattr(request_parameters, "CONTROL_PARAMETERS", request_parameters.CONTROL_PARAMETERS | {"future_control"})
    with pytest.raises(AssertionError, match="Every generation parameter"):
        assert_review_coverage()


def test_endpoint_contract_detects_an_accidental_new_global_allowance(monkeypatch):
    monkeypatch.setattr(request_parameters, "CONTROL_PARAMETERS", request_parameters.CONTROL_PARAMETERS | {"future_control"})
    policy = request_parameters.RequestParameterPolicy(chat=frozenset({"future_control"}))
    sent = adapt_request_parameters({"model": "model", "messages": [], "future_control": 1}, policy, "chat")
    with pytest.raises(AssertionError, match="unreviewed outgoing fields"):
        assert_endpoint_contract("groq", "chat", sent)


def test_policy_cannot_allow_an_unclassified_parameter():
    with pytest.raises(ValueError, match="Unreviewed policy parameters"):
        request_parameters.RequestParameterPolicy(chat=frozenset({"future_control"}))


def test_catalog_provider_cannot_infer_capabilities_when_its_policy_is_missing(monkeypatch):
    monkeypatch.delitem(provider_facade._parameter_policies, "groq")
    with pytest.raises(ValueError, match="no request parameter policy"):
        request_parameter_policy_for(connection("groq"), "openai/gpt-oss-120b")


@pytest.mark.parametrize("protocol", ["chat", "responses", "compact"])
def test_unknown_parameters_pass_through_without_traversing_user_content(protocol):
    policy = request_parameter_policy_for(connection("openai-api"), "gpt-5.6-sol")
    schema = {"type": "object", "properties": {"future_control": {"type": "string"}}}
    body = {"input": [{"role": "user", "content": "future_control"}],
        "text": {"format": {"type": "json_schema", "name": "report", "schema": schema}},
        "tools": [{"type": "function", "name": "report", "parameters": schema}]}
    assert adapt_request_parameters(body, policy, protocol) == body
    extended = {**body, "future_control": True}
    assert adapt_request_parameters(extended, policy, protocol) == extended


@pytest.mark.asyncio
async def test_contract_suite_cannot_accidentally_make_a_paid_http_call():
    for client in (httpx.AsyncClient, httpx2.AsyncClient):
        async with client() as http:
            with pytest.raises(pytest.fail.Exception, match="real network is forbidden"):
                await http.post("https://provider.invalid/v1/responses", json={"input": "work"})


# Each row is an observable serving constraint, not an assertion about policy internals.
CASES = [
    ("openai-api", "gpt-6-astra", "max", None, "max"),
    ("openai-api", "gpt-6-astra", "none", None, "low"),
    ("openai-api", "gpt-5.6-sol", "high", None, "high"),
    ("openai-api", "gpt-5.6-sol", "none", 0.2, "none"),
    ("openai-api", "gpt-5.6-sol", "max", None, "max"),
    ("openai-api", "gpt-5.1", "max", None, "max"),
    ("openai-api", "gpt-5", "xhigh", None, "xhigh"),
    ("openai-api", "gpt-5-pro", "low", None, "low"),
    ("openai-api", "gpt-4.1", "high", 0.2, None),
    ("openai-api", "gpt-unknown-future", "high", 0.2, None),
    ("openai-codex", "gpt-6-astra", "high", None, "high"),
    ("openrouter", "openai/gpt-6-astra", "high", 0.2, "high"),
    ("openrouter", "anthropic/claude-opus-4.7", "high", 0.2, "high"),
    ("openrouter", "google/gemini-3.1-pro-preview", "max", 0.2, "max"),
    ("mammouth", "gpt-6-astra", "high", 0.2, "high"),
    ("mammouth", "mammouth-recommended", "high", 0.2, "high"),
    ("anthropic-api", "claude-opus-4-7", "high", None, None),
    ("anthropic-api", "claude-sonnet-4-6", "high", 0.2, None),
    ("anthropic-api", "claude-unknown-future", "high", 0.2, None),
    ("deepseek", "deepseek-v4-pro", "medium", None, "high"),
    ("deepseek", "deepseek-v4-pro", "none", 0.2, "none"),
    ("deepseek", "deepseek-reasoner", "high", None, None),
    ("fireworks", "accounts/fireworks/models/gpt-oss-120b", "max", 0.2, "max"),
    ("groq", "openai/gpt-oss-120b", "max", 0.2, "high"),
    ("groq", "qwen/qwen3-32b", "medium", 0.2, "default"),
    ("groq", "qwen/qwen3.8-27b", "medium", 0.2, "default"),
    ("groq", "qwen/qwen3.8-27b", "none", 0.2, "none"),
    ("groq", "llama-3.3-70b-versatile", "high", 0.2, None),
    ("mistral", "mistral-small-latest", "medium", 0.2, "high"),
    ("together", "openai/gpt-oss-120b", "none", 0.2, "none"),
    ("cerebras", "gpt-oss-120b", "xhigh", 0.2, "high"),
    ("cerebras", "zai-glm-4.7", "high", 0.2, None),
    ("gemini", "gemini-3.1-pro-preview", "none", 0.2, "low"),
    ("gemini", "gemini-2.5-flash", "none", 0.2, "none"),
    ("xai", "grok-4.6", "max", 0.2, "high"),
    ("nvidia", "openai/gpt-oss-120b", "max", 0.2, "max"),
    ("huggingface", "openai/gpt-oss-120b:groq", "max", 0.2, "max"),
    ("cohere", "command-a-reasoning-08-2025", "medium", 0.2, "high"),
    ("cohere", "command-a-03-2025", "medium", 0.2, None),
    ("perplexity", "sonar", "high", 0.2, "high"),
    ("perplexity", "openai/gpt-6-astra", "high", 0.2, "high"),
    ("ollama", "qwen3:8b", "max", 0.2, "high"),
]


def connection(code):
    profile = get_provider_profile(code)
    return ProviderConnection(
        id=2, name=code, catalog_code=code if profile else None,
        provider_type=profile.provider_type if profile else code,
        base_url=profile.base_url if profile else "http://ollama.test/v1",
    )


def test_every_text_provider_has_a_wire_compatibility_scenario():
    assert {profile.code for profile in PROVIDER_CATALOG if "chat" in profile.capabilities} <= {
        row[0] for row in CASES
    }
    assert {row[0] for row in CASES} == set(CONTRACTS["providers"])


def preferred_protocol(code, model):
    profile = get_provider_profile(code)
    return "responses" if profile and profile.supports_responses else "chat"


WIRE_CASES = [(*row, preferred_protocol(row[0], row[1])) for row in CASES]
WIRE_CASES += [("perplexity", "sonar", "high", 0.2, None, "chat")]
WIRE_CASES += [(*row, "chat") for row in CASES if preferred_protocol(row[0], row[1]) == "responses"
    and row[0] not in {"openai-codex", "perplexity"}
    and not (row[0] == "openai-api" and row[1] in {"gpt-6-astra", "gpt-5-pro"})]


@pytest.mark.parametrize("code,model,effort,temperature,wire_effort,protocol", WIRE_CASES)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_provider_request_preserves_work_and_sends_compatible_controls(
    monkeypatch, code, model, effort, temperature, wire_effort, protocol, stream,
):
    profile = get_provider_profile(code)
    provider = SimpleNamespace(
        id=2, name=code, catalog_code=code if profile else None,
        provider_type=profile.provider_type if profile else code,
        base_url=connection(code).base_url, is_active=True, configuration={},
    )
    llm = SimpleNamespace(
        id=12, code="stable-goal-model", llm_name=model, llm_provider_id=2,
        cost_per_input_token=None, cost_per_cached_input_token=None,
        cost_per_output_token=None, is_subscription=False,
    )
    requests = []
    active_probe = None
    reject_auth_once = False

    def upstream(request):
        sent = json.loads(request.content)
        requests.append(sent)
        if reject_auth_once and len(requests) == 1:
            return httpx.Response(401, json={"error": "Refresh required"})
        assert_endpoint_contract(code, protocol, sent)
        if active_probe in CONTRACTS["providers"][code]["preserve"].split() and model != "gpt-unknown-future":
            assert sent[active_probe] == CONTRACTS["controls"][active_probe]
        # Simulate a strict endpoint: this is the production failure, at the HTTP boundary.
        assert sent.get("temperature") == temperature
        actual_effort = sent.get("reasoning_effort", sent.get("reasoning", {}).get("effort"))
        if code == "deepseek" and protocol == "chat" and wire_effort == "none":
            assert actual_effort is None
            assert sent["thinking"] == {"type": "disabled"}
        else:
            assert actual_effort == wire_effort
        assert sent["model"] == model
        assert sent["tools"] == body["tools"]
        assert sent["input" if protocol == "responses" else "messages"] == original_content
        if code == "openai-codex":
            assert "max_output_tokens" not in sent
        else:
            limit_key = "max_output_tokens" if protocol == "responses" else "max_tokens"
            if code == "openai-api" and protocol == "chat":
                limit_key = "max_completion_tokens"
            assert sent[limit_key] == 256
        if protocol == "responses":
            terminal = {"id": "resp_test", "object": "response", "created_at": 1,
                "model": model, "status": "completed", "output": [{"id": "msg_test",
                "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "done", "annotations": []}]}]}
            if sent.get("stream"):
                return httpx.Response(200, headers={"content-type": "text/event-stream"},
                    content=f'data: {json.dumps({"type": "response.completed", "response": terminal})}\n\n')
            return httpx.Response(200, json=terminal)
        if sent.get("stream"):
            chunk = {"id": "chat_test", "object": "chat.completion.chunk", "created": 1,
                "model": model, "choices": [{"index": 0, "delta": {"content": "done"}, "finish_reason": "stop"}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", lambda **kw: client_class(
        transport=httpx.MockTransport(upstream), **kw,
    ))
    @asynccontextmanager
    async def session():
        yield None
    monkeypatch.setattr(proxy_service, "get_db_session", session)
    monkeypatch.setattr(proxy_service, "enforce_subscription_access", AsyncMock(return_value=1))
    monkeypatch.setattr(proxy_service.llm_provider_service, "get_provider_with_decrypted_key", AsyncMock(return_value=(provider, "test-key")))
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", AsyncMock())
    monkeypatch.setattr(proxy_service.llm_call_service, "update_running_call", AsyncMock())
    if code == "openai-codex":
        from bridge.openai import codex_oauth
        monkeypatch.setattr(codex_oauth, "get_access_token", AsyncMock(return_value="test-token"))
    original_content = [{"role": "user", "content": "Evaluate the goal, preserving this content."}]
    tool = {"name": "report", "description": "Report progress", "parameters": {"type": "object", "properties": {}}}
    body = {
        "model": "stable-goal-model", "stream": stream, "temperature": 0.2,
        "top_p": 0.9, "max_tokens": 256,
        "input" if protocol == "responses" else "messages": original_content,
        "tools": [{"type": "function", **tool} if protocol == "responses" else {"type": "function", "function": tool}],
    }
    original = deepcopy(body)
    call = proxy_service.proxy_responses if protocol == "responses" else proxy_service.proxy_chat_completion
    # Native extension pass-through is exercised by test_protocol_inference.
    reject_auth_once = False
    # Exercise every reviewed control on every serving scenario, through the real proxy.
    # One control per request avoids manufacturing invalid combinations in the test itself.
    for active_probe, extra in [(None, {}), *PROBES]:
        candidate = {**body, **deepcopy(extra)}
        before = deepcopy(candidate)
        response = await call(candidate, task_id=None, llm_override=llm,
            route_executor_model=False, reasoning_effort=effort)
        if stream:
            assert b"done" in b"".join([chunk async for chunk in response.body_iterator])
        else:
            assert response.status_code == 200
        assert candidate == before
    assert len(requests) == 1 + len(PROBES)
    assert body == original


def test_controls_do_not_overwrite_native_content_or_budget_and_are_idempotent():
    policy = request_parameter_policy_for(connection("openai-api"), "gpt-5.6-sol")
    body = {"model": "gpt-5.6-sol", "max_tokens": 200, "max_completion_tokens": 100,
        "temperature": 0.0, "reasoning_effort": "high", "tools": [{"type": "function"}],
        "messages": [{"role": "assistant", "content": "History", "tool_calls": [{"id": "call_1"}]}]}
    original = deepcopy(body)
    normalized = adapt_request_parameters(body, policy, "chat")
    assert normalized["max_completion_tokens"] == 100
    assert "max_tokens" not in normalized
    assert normalized["messages"] == body["messages"]
    assert normalized["tools"] == body["tools"]
    assert adapt_request_parameters(normalized, policy, "chat") == normalized
    assert body == original


def test_unknown_model_preserves_functional_payload_without_speculative_tuning():
    policy = request_parameter_policy_for(connection("mammouth"), "new-router-preset")
    body = {"model": "new-router-preset", "input": "Work", "temperature": 0,
        "reasoning": {"effort": "max"}, "max_output_tokens": 200,
        "text": {"format": {"type": "json_object"}}, "tools": [{"type": "function"}]}
    result = adapt_request_parameters(body, policy, "responses")
    assert result == body


@pytest.mark.parametrize("code,model,protocol,removed", [
    ("groq", "openai/gpt-oss-120b", "chat", {"logprobs", "top_logprobs", "logit_bias", "presence_penalty", "frequency_penalty"}),
    ("cerebras", "gpt-oss-120b", "chat", {"logit_bias"}),
    ("xai", "grok-4.6", "chat", {"presence_penalty", "frequency_penalty", "stop"}),
    ("cohere", "command-a-reasoning-08-2025", "chat", {"logprobs", "top_logprobs", "logit_bias", "parallel_tool_calls"}),
    ("openai-api", "gpt-6-astra", "responses", {"logprobs", "top_logprobs", "logit_bias", "presence_penalty", "frequency_penalty", "temperature", "top_p"}),
    ("openai-api", "o3", "chat", {"stop", "prediction"}),
])
def test_unsupported_controls_and_logprob_include_are_removed_together(code, model, protocol, removed):
    policy = request_parameter_policy_for(connection(code), model)
    body = {"temperature": 0.2, "top_p": 0.9, "logprobs": True, "top_logprobs": 3,
        "logit_bias": {"1": 100}, "presence_penalty": 0.3, "frequency_penalty": 0.4,
        "stop": ["END"], "prediction": {"type": "content", "content": "draft"},
        "parallel_tool_calls": True, "reasoning_effort": "high",
        "include": ["message.output_text.logprobs", "reasoning.encrypted_content"],
        "text": {"format": {"type": "json_object"}}, "tools": [{"type": "function"}]}
    result = adapt_request_parameters(body, policy, protocol)
    assert not removed.intersection(result)
    if "top_logprobs" in removed:
        assert "message.output_text.logprobs" not in result["include"]
    assert "reasoning.encrypted_content" in result["include"]
    assert result["text"] == body["text"]
    assert result["tools"] == body["tools"]


def test_unsupported_functional_feature_is_rejected_without_dropping_tools():
    # A declared endpoint restriction is enforced; a model name is not evidence.
    policy = request_parameters.RequestParameterPolicy(chat_supports_tools=False)
    body = {"tools": [{"type": "function", "function": {"name": "report"}}]}
    with pytest.raises(ValueError, match="Responses API for tool calls"):
        adapt_request_parameters(body, policy, "chat")
    assert body["tools"][0]["function"]["name"] == "report"


@pytest.mark.parametrize("code,model,effort,temperature,wire_effort", CASES)
def test_normalization_is_stable_when_a_request_is_retried(code, model, effort, temperature, wire_effort):
    policy = request_parameter_policy_for(connection(code), model)
    body = {"temperature": 0.2, "top_p": 0.9, "reasoning_effort": effort, "max_tokens": 200}
    for protocol in ("chat", "responses"):
        adapted = adapt_request_parameters(body, policy, protocol)
        assert adapt_request_parameters(adapted, policy, protocol) == adapted


def test_compaction_never_inherits_generation_settings():
    policy = request_parameter_policy_for(connection("openai-api"), "gpt-6-astra")
    assert adapt_request_parameters({"model": "gpt-6-astra", "input": [], "instructions": "Keep context",
        "temperature": 0, "max_output_tokens": 500, "reasoning": {"effort": "high"}}, policy, "compact") == {
        "model": "gpt-6-astra", "input": [], "instructions": "Keep context",
    }


def test_unsupported_thinking_toggle_cannot_reenable_sampling_on_astra():
    policy = request_parameter_policy_for(connection("openai-api"), "gpt-6-astra")
    body = {"temperature": 0, "reasoning": {"enabled": False}, "thinking": {"type": "disabled"}}
    assert adapt_request_parameters(body, policy, "responses") == {}


@pytest.mark.parametrize("model", ["anthropic/claude-sonnet-4.6", "deepseek/new-model", "opaque-preset"])
def test_openrouter_parameters_are_delegated_without_guessing_the_model_author(model):
    policy = request_parameter_policy_for(connection("openrouter"), model)
    body = {"temperature": 0, "reasoning": {"max_tokens": 1024}}
    assert adapt_request_parameters(body, policy, "chat") == body


def test_deepseek_forced_tool_choice_requires_thinking_off():
    policy = request_parameter_policy_for(connection("deepseek"), "deepseek-v4-pro")
    body = {"tools": [{"type": "function", "function": {"name": "report"}}], "tool_choice": "required"}
    with pytest.raises(ValueError, match="forced tool_choice"):
        adapt_request_parameters(body, policy, "chat")
    disabled = adapt_request_parameters({**body, "reasoning_effort": "none"}, policy, "chat")
    assert disabled["thinking"] == {"type": "disabled"}
    assert disabled["tool_choice"] == "required"


@pytest.mark.parametrize("thinking", ["adjustable", "always", "unsupported"])
def test_deepseek_parameter_controls_follow_sdk_capabilities_for_opaque_model(monkeypatch, thinking):
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    from pydantic_ai.providers.deepseek import DeepSeekProvider

    def profile(model_name):
        assert model_name == "opaque-deployment"
        return OpenAIModelProfile(
            supports_thinking=thinking != "unsupported",
            thinking_always_enabled=thinking == "always",
            openai_reasoning_enabled_by_default=thinking == "adjustable",
            openai_supports_forced_tool_choice_with_thinking=thinking != "adjustable",
        )

    monkeypatch.setattr(DeepSeekProvider, "model_profile", staticmethod(profile))
    policy = request_parameter_policy_for(connection("deepseek"), "opaque-deployment")
    sent = adapt_request_parameters({"temperature": 0.2, "reasoning_effort": "medium"}, policy, "chat")
    if thinking == "adjustable":
        assert sent == {"reasoning_effort": "high", "thinking": {"type": "enabled"}}
        disabled = adapt_request_parameters({"temperature": 0.2, "reasoning_effort": "none",
            "tool_choice": "required"}, policy, "chat")
        assert disabled == {"temperature": 0.2, "thinking": {"type": "disabled"}, "tool_choice": "required"}
    elif thinking == "always":
        assert sent == {}
    else:
        assert sent == {"temperature": 0.2}


@pytest.mark.parametrize("budget", [0, -1, True, "200"])
def test_invalid_budget_is_rejected_instead_of_becoming_an_unbounded_request(budget):
    policy = request_parameter_policy_for(connection("openai-api"), "gpt-4.1")
    with pytest.raises(ValueError, match="positive integer"):
        adapt_request_parameters({"max_tokens": budget}, policy, "chat")


# Reuse the reviewed serving scenarios, but let the installed SDK build the requests.
# Gateway routes for the incident's model family must also traverse this composition.
INFERENCE_ROUTES = sorted({(row[0], row[1], row[-1]) for row in WIRE_CASES} | {
    ("openrouter", "deepseek/deepseek-v4-flash-0731", "responses"),
    ("openrouter", "deepseek/deepseek-v4-flash-0731", "chat"),
    ("huggingface", "deepseek-ai/deepseek-v4-pro", "responses"),
    ("mammouth", "deepseek-v4-pro", "responses"),
})


class InferenceReport(BaseModel):
    """A nonempty structured result, including a resource that must survive transport."""

    conclusion: str = Field(min_length=1)
    resources: list[str]


@pytest.mark.asyncio
@pytest.mark.parametrize("code,model_name,protocol", INFERENCE_ROUTES)
@pytest.mark.parametrize("effort", [None, "none", "high", "max"])
@pytest.mark.parametrize("output_mode", ["tool", "prompted", "text"])
async def test_sdk_inference_composes_with_provider_contract(
    monkeypatch, code, model_name, protocol, effort, output_mode, responses_sse,
):
    """A valid SDK request reaches HTTP and a corrected result survives validation."""
    profile = get_provider_profile(code)
    provider = LLMProvider(
        id=2, name=code, catalog_code=code if profile else None,
        provider_type=profile.provider_type if profile else code,
        base_url=connection(code).base_url, is_active=True, configuration={},
    )
    llm = LLM(id=12, code="contract-model", llm_name=model_name, llm_provider_id=2,
        label=model_name, is_subscription=False, cost_per_input_token=0,
        cost_per_cached_input_token=0, cost_per_output_token=0)
    llm.provider = provider
    requests = []
    resource = "document://report/current"
    expected = {"conclusion": "Report completed", "resources": [resource]}

    def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        assert_endpoint_contract(code, protocol, body)
        assert body["model"] == model_name
        assert resource in json.dumps(body)
        if code == "deepseek" and "deepseek-v4" in model_name:
            reasoning = body.get("reasoning_effort", body.get("reasoning", {}).get("effort"))
            thinking_off = reasoning == "none" or body.get("thinking", {}).get("type") == "disabled"
            if not thinking_off:
                assert body.get("tool_choice") not in ("required",), "Forced tool use is incompatible with thinking"
                assert not isinstance(body.get("tool_choice"), dict)
        if effort in {"high", "max"} and code == "openrouter" and "deepseek-v4" in model_name:
            assert body["reasoning"]["effort"] == effort
        # An invalid first result must cause a bounded retry, never silent acceptance.
        value = {**expected, "conclusion": ""} if len(requests) == 1 else expected
        content = "Report completed" if output_mode == "text" else json.dumps(value)
        tools = body.get("tools", [])
        if output_mode == "tool":
            assert tools, "Structured output must preserve its output tool/schema"
            tool = tools[0] if protocol == "responses" else tools[0]["function"]
            assert set(tool["parameters"]["properties"]) == {"conclusion", "resources"}
        else:
            assert not tools, "Text and prompted output must not introduce tool effects"
        if protocol == "responses":
            output = ([{"type": "function_call", "id": f"fc_{len(requests)}",
                "call_id": f"call_{len(requests)}", "name": tool["name"],
                "arguments": content, "status": "completed"}] if output_mode == "tool" else
                [{"type": "message", "id": f"msg_{len(requests)}", "role": "assistant",
                  "status": "completed", "content": [{"type": "output_text", "text": content, "annotations": []}]}])
            terminal = {"id": f"resp_{len(requests)}", "object": "response",
                "created_at": 1, "model": model_name, "status": "completed", "output": output}
            if body.get("stream"):
                return httpx.Response(200, headers={"content-type": "text/event-stream"},
                    content=responses_sse(terminal))
            return httpx.Response(200, json=terminal)
        delta = ({"tool_calls": [{"index": 0, "id": f"call_{len(requests)}", "type": "function",
            "function": {"name": tool["name"], "arguments": content}}]} if output_mode == "tool" else {"content": content})
        chunk = {"id": f"chat_{len(requests)}", "object": "chat.completion.chunk", "created": 1,
            "model": model_name, "choices": [{"index": 0, "delta": delta,
            "finish_reason": "tool_calls" if output_mode == "tool" else "stop"}]}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")

    class ProviderClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    @asynccontextmanager
    async def session():
        yield None
    monkeypatch.setattr(proxy_service, "get_db_session", session)
    monkeypatch.setattr(proxy_service, "enforce_subscription_access", AsyncMock(return_value=1))
    monkeypatch.setattr(proxy_service.llm_provider_service, "get_provider_with_decrypted_key", AsyncMock(return_value=(provider, "test-key")))
    create_trace = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", create_trace)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", AsyncMock())
    monkeypatch.setattr(proxy_service.llm_call_service, "update_running_call", AsyncMock())
    if code == "openai-codex":
        from bridge.openai import codex_oauth
        monkeypatch.setattr(codex_oauth, "get_access_token", AsyncMock(return_value="test-token"))
    round_id = uuid4()
    options = {"reasoning_effort": effort, "conversation_round_id": round_id, "purpose": "contract.inference"}
    # This serialization matrix replaces DB/accounting. The durable gateway itself
    # is exercised with real commits in test_protocol_inference.
    from app.llm import protocol_inference

    monkeypatch.setattr(protocol_inference, "proxy_chat_completion", proxy_service.proxy_chat_completion)
    monkeypatch.setattr(protocol_inference, "proxy_responses", proxy_service.proxy_responses)
    if protocol == preferred_protocol(code, model_name):
        model = await pydantic_ai_utils.build_model_for_llm(llm, **options)
        from pydantic_ai.models.fallback import FallbackModel

        primary = model.models[0] if isinstance(model, FallbackModel) else model
        assert isinstance(primary, pydantic_ai_utils.InternalLLMResponsesModel) == (protocol == "responses")
    else:
        model = pydantic_ai_utils.InternalLLMChatModel(llm, **options)
    output_type = str if output_mode == "text" else PromptedOutput(InferenceReport) if output_mode == "prompted" else InferenceReport
    agent = Agent(model, output_type=output_type, retries={"output": 1})
    try:
        result = await agent.run(f"Report on {resource}", usage_limits=UsageLimits(request_limit=2, count_tokens_before_request=True))
    except Exception as exc:
        pytest.fail(f"A compatible {code}/{model_name}/{protocol} inference failed: {type(exc).__name__}: {exc}")
    assert result.output == ("Report completed" if output_mode == "text" else InferenceReport(**expected))
    assert len(requests) == (1 if output_mode == "text" else 2)
    assert all(call.kwargs["conversation_round_id"] == round_id for call in create_trace.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["chat", "responses"])
@pytest.mark.parametrize("outcome", ["limited", "timeout", "external_timeout", "cancel", "resolved"])
async def test_sdk_transport_preserves_errors_timeouts_cancellation_and_resolved_settings(
    monkeypatch, protocol, outcome,
):
    """Use the SDK and real proxy; replace only DB/accounting and the external HTTP peer."""
    provider = LLMProvider(id=2, name="OpenAI", catalog_code="openai-api",
        provider_type="openai_compatible", base_url="https://provider.invalid/v1", is_active=True)
    llm = LLM(id=12, code="frozen", llm_name="gpt-5.1", llm_provider_id=2, label="Frozen")
    llm.provider = provider
    clients = []
    requests = []

    async def upstream(request):
        requests.append(request)
        assert request.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 0.25)
        if outcome == "cancel":
            await anyio.sleep_forever()
        if outcome in {"timeout", "external_timeout"}:
            raise httpx.ReadTimeout("upstream timeout", request=request)
        return httpx.Response(429, json={"error": {"message": "rate limited"}},
            headers={"Retry-After": "17", "X-Request-Id": "upstream-id", "Set-Cookie": "private-cookie"})

    class ProviderClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(upstream), **kwargs)
            clients.append(self)

    @asynccontextmanager
    async def session():
        yield None

    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    monkeypatch.setattr(proxy_service, "get_db_session", session)
    monkeypatch.setattr(proxy_service, "enforce_subscription_access", AsyncMock(return_value=1))
    monkeypatch.setattr(proxy_service.llm_provider_service, "get_provider_with_decrypted_key",
        AsyncMock(return_value=(provider, "test-key")))
    create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    finalize = AsyncMock()
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", create)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", finalize)
    cls = pydantic_ai_utils.InternalLLMChatModel if protocol == "chat" else pydantic_ai_utils.InternalLLMResponsesModel
    model = cls(llm, reasoning_effort="high")
    settings = {"timeout": 0.25}
    if outcome == "resolved":
        # A call clears the model default before SDK serialization; the proxy must not
        # re-inject the model's original effort from accounting metadata.
        settings["openai_reasoning_effort"] = None
    messages = [ModelRequest(parts=[UserPromptPart(content="Work")])]
    if outcome == "cancel":
        with anyio.move_on_after(0.05) as scope:
            await model.request(messages, settings, ModelRequestParameters())
        assert scope.cancel_called
    elif outcome == "timeout":
        with pytest.raises(ModelAPIError, match="timed out"):
            await model.request(messages, settings, ModelRequestParameters())
    elif outcome == "external_timeout":
        # The public gateway still exposes connection errors as RuntimeError -> HTTP 502.
        proxy = proxy_service.proxy_chat_completion if protocol == "chat" else proxy_service.proxy_responses
        content_key = "messages" if protocol == "chat" else "input"
        with pytest.raises(RuntimeError, match="upstream timeout"):
            await proxy({"model": llm.code, content_key: [{"role": "user", "content": "Work"}]},
                task_id=None, llm_override=llm, reasoning_effort="high", route_executor_model=False,
                request_timeout=dict.fromkeys(("connect", "read", "write", "pool"), 0.25))
    else:
        with pytest.raises(ModelHTTPError) as caught:
            await model.request(messages, settings, ModelRequestParameters())
        assert caught.value.status_code == 429
        assert caught.value.retry_after == 17
        assert caught.value.headers["x-request-id"] == "upstream-id"
        assert "set-cookie" not in caught.value.headers
    assert len(requests) == 1  # No additional paid retry layer.
    assert all(client.is_closed for client in clients)
    assert finalize.await_count == 1
    assert finalize.await_args.kwargs["status"] == ("cancelled" if outcome == "cancel" else "error")
    assert create.await_args.kwargs["reasoning_effort"] == "high"
    if outcome == "resolved":
        body = json.loads(requests[0].content)
        assert "reasoning_effort" not in body
        assert "effort" not in body.get("reasoning", {})
