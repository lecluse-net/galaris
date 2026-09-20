<p align="right"><a href="../../fr/dev/provider-parameters.md">Français</a> · <strong>English</strong></p>

# Provider parameter compatibility

Audit dated September 12, 2026. Sources of truth are the policies under `back/bridge/`,
the contract in `back/app/llm/request_parameters.py` and HTTP scenarios in
`back/tests/test_provider_parameters.py`. The structural decision is
[ADR 0088](../../../project/decisions/0088-provider-request-parameters.md).

## Current contract — September 14, 2026

[ADR 0097](../../../project/decisions/0097-durable-inference-lifecycle.md) supersedes the closed
vocabulary and local model-name tables described in the historical audit below. SDK profiles
and endpoint policies are authoritative. Unknown extensions pass through; an HTTP 400/422
explicitly naming an unsupported optional setting allows that field to be removed and retried.
Budgets, tools, content and schemas are preserved. Timeouts, 429s and partial streams do not
trigger this negotiation.

Generic routers no longer infer profiles from namespaces or suffixes. Perplexity uses SDK
Responses/Chat fallback after the HTTP rejections declared by its bridge. Former version-specific
effort caps are no longer guaranteed: the provider may reject an explicit effort, which then
falls under optional-setting negotiation. Fixtures remain a scenario inventory; their historical
blocked-field lists no longer impose a runtime ban on native extensions.

Calls and events are durable, with pause, stop, resume, readback and accounting per attempt.
`test_protocol_inference.py` supplements the historical matrix by checking negotiation and
preservation of functional requirements.

## Migration history — September 13, 2026

The first stage of [ADR 0095](../../../project/decisions/0095-pydantic-ai-request-ownership.md)
removes the copied Chat builder and SSE reader. Pydantic AI 2.43 builds internal Chat/Responses
requests and its profile merges system messages. The shared transport keeps proxy authorization
and accounting, forwards timeouts, and preserves HTTP status and `Retry-After`. The original
effort is no longer re-injected into SDK-built requests. Cancellation before response headers
finalizes the call and closes the client.

The second stage delegates Codex endpoint restrictions to the official SDK profile:
streaming, `store=false`, and removal of unsupported generic settings before construction.
Groq uses the official profile resolver; DeepSeek reads SDK reasoning capabilities in its
parameter policy, without model-name checks in that policy. Codex encrypted reasoning replay
and compaction remain covered by tests.

This description of the second increment refers to the September 13 stage.
[Decision 0097](../../../project/decisions/0097-durable-inference-lifecycle.md) describes the
removal of the relevant local rules in the following increment. The
[convergence plan](../../../project/plans/convergence-pydantic-ai.md) now retains only open
extensions and qualifications. Do not add new model-name heuristics.

## Shared guarantee

The proxy still adapts controls after model selection. It resolves run effort for external
clients; internal calls have already supplied their settings to the SDK.
This protects Goals, structured calls, the internal harness and external clients using the
gateway. A harness contacting its provider directly remains outside this boundary.

The matrix allows common settings per endpoint, translates effort and token caps, removes
incompatible combinations and preserves messages, tools and output formats. Compaction does
not inherit generation settings. Unknown router aliases do not arbitrarily inherit OpenAI
capabilities. Known functional incompatibilities (such as Astra tools on Chat Completions)
produce an explicit error before sending.

The trace's `reasoning_effort` field retains the canonical Galaris choice; the transmitted
value may be capped or translated. Without documented adjustable effort, it is omitted.
Native extensions and multimodal capabilities retain their dedicated builders and contracts.

## Guards for new parameters

The request vocabulary is closed. Every new top-level field or nested field in `reasoning`,
`text`, `stream_options` or `thinking` must be classified before use. Unknown fields, including
those supplied through `extra_body`, are rejected before HTTP transmission. The gateway returns
a validation error naming fields without exposing their values. User JSON schema properties
and message content are not traversed. Validation runs again after bridge transformation and
during authentication refresh; a late rejection finalizes the trace as an error.

`back/tests/fixtures/provider_parameters.json` contains examples for every control and accepted
field lists for simulated endpoints. It is independent of production policies: never regenerate
it from their allowlists. Tests fail when a control has no example, an outgoing field lacks
review or a catalog provider lacks a scenario. A catalog provider without an explicit policy
cannot infer compatibility from its model name.

The installed OpenAI SDK's Chat/Responses field inventory is also pinned in this fixture.
An upgrade adding or removing a field requires review even if Galaris does not emit it yet.
Known SDK fields without support have an explicit rejection rationale in `sdk_blocked_fields`
and remain rejected at runtime.

Every example runs across the provider/model/protocol matrix, with and without streaming,
through the real proxies. Tests also verify detection of a control added without an example,
an accidental global allowance and a late injection. Real HTTP transports are forbidden in
this suite: no external key or subscription is needed. Only local test containers consume
resources.

To add a parameter:

1. Check endpoint contracts and classify the field in `CONTROL_PARAMETERS`, or its nested
   field in `NESTED_PARAMETERS`. Content fields belong in `PAYLOAD_PARAMETERS`.
2. First check Pydantic AI settings, profiles and integrations. Keep endpoint constraints
   independent of model names in provider configuration. Record SDK gaps in the convergence
   plan instead of adding model-name heuristics. Never silently remove a functional capability.
3. Add its example and justified permissions to the independent fixture. The entire matrix
   will automatically exercise it; add a specific scenario for interactions with other fields.
4. Run `make tests-providers`, then the usual checks. This suite is also collected by
   `make tests`, `make tests-coverage` and the GitHub/GitLab backend CI jobs.

This closed vocabulary replaces unrestricted forwarding of undeclared native extensions on
the text gateway. Legitimate extensions now require a contract and a scenario.

## Audited matrix

Rows describe the main adaptations; complete control sets and recognized families live in
code, without a discovery request on every generation.

| Provider | Main adaptation | Reference |
|---|---|---|
| OpenAI API | Astra: no sampling; GPT-5: version/effort restrictions; native token caps | [OpenAI](https://developers.openai.com/api/docs/guides/latest-model), [GPT-5.1](https://developers.openai.com/api/docs/models/gpt-5.1), [GPT-5.6](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6) |
| ChatGPT (`openai-codex`) | Additional endpoint restrictions, including temperature, top-p and output cap | `back/bridge/openai/codex.py`, `back/tests/test_codex_provider.py`; reproduced production rejection |
| Anthropic API | OpenAI compatibility without adjustable effort; generation-specific sampling, temperature ≤ 1, temperature/top-p exclusion | [Claude compatibility](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) |
| DeepSeek | V4: separate Chat effort and thinking toggle; sampling removed with thinking; forced tools rejected with thinking | [Thinking](https://api-docs.deepseek.com/guides/thinking_mode/), [Responses](https://api-docs.deepseek.com/api/create-response/) |
| Gemini | Gemini effort scale; disabling restricted to relevant models; temperature preserved | [Google compatibility](https://ai.google.dev/gemini-api/docs/openai) |
| xAI | Grok effort; penalties and stop removed with reasoning; temperature preserved | [Grok reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning) |
| Groq | Logprobs, logit_bias and penalties removed; separate GPT-OSS/Qwen efforts | [Compatibility](https://console.groq.com/docs/openai), [API](https://console.groq.com/docs/api-reference) |
| Cerebras | Logit_bias removed; GPT-OSS efforts and documented GLM disabling | [API](https://inference-docs.cerebras.ai/api-reference/chat-completions) |
| Mistral | Binary effort for adjustable families; undeclared OpenAI controls omitted | [Reasoning](https://docs.mistral.ai/studio/conversations/reasoning) |
| Cohere | Binary Command A effort; controls absent from compatibility contract removed | [Compatibility](https://docs.cohere.com/docs/compatibility-api) |
| Together | Service-specific GPT-OSS and DeepSeek V4 efforts | [Reasoning](https://docs.together.ai/docs/inference/chat/reasoning) |
| Fireworks | Effort enums per served family | [Chat](https://docs.fireworks.ai/api-reference/post-completions), [Responses](https://docs.fireworks.ai/api-reference/post-responses) |
| NVIDIA NIM | Common NIM controls; recognized GPT-OSS effort, other efforts omitted | [NIM API](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html) |
| Ollama | Compatible Chat contract; thinking levels only for recognized families | [Compatibility](https://docs.ollama.com/api/openai-compatibility) |
| OpenRouter | Family policy and unified `reasoning` object, including Claude budget | [Reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) |
| Hugging Face | Author policy, recognized routing suffix, router-specific token cap field | [Responses](https://huggingface.co/docs/inference-providers/en/guides/responses-api) |
| Mammouth | Recognized models: family policy; opaque presets: conservative settings | [API](https://info.mammouth.ai/docs/api-quick-start/) |
| Perplexity | Sonar Chat distinct from qualified Agent API models; `/responses` remains an alias | [Agent API](https://docs.perplexity.ai/docs/agent-api/quickstart) |

ElevenLabs, Google Cloud TTS, Azure Speech, Suno and BytePlus do not use Goal text generation:
their payloads are built by bridge-specific media services. Embeddings send their dedicated
contract; `models_dev` supplies metadata without inference. Inspection of these paths is not
live qualification of every media API.

## Validation and maintenance

SDK construction and HTTP validation use the same provider policy. Restrictions on forced
tool choice with reasoning are projected into internal Chat and Responses profiles before
request construction. Structured output retains its schema and validators when the SDK must
leave tool choice automatic.

The matrix exercises real proxies with a simulated HTTP transport, with and without streaming.
It checks transmitted parameters and preserved content. LLM and Goal suites cover business
workflows; internal model tests also protect against valid settings being removed by the SDK.
These tests require no paid requests.

The composition matrix lets the installed SDK construct requests: Chat and Responses,
automatic/none/high/max effort, and tool/prompted JSON/text output. It requires correction of
invalid structured output and preservation of resource URIs. The database admission workflow
checks persisted Tasks, redelivery without duplication, and no Task on failure.
`make tests-providers` writes `artifacts/provider-contracts.xml`; CI and `make validate`
require it to pass. A mutation indexed in `project/regressions.json` verifies that removing
SDK adaptation actually makes the suite fail.

When adding a provider or model family, check endpoint documentation, add its policy and an
outgoing request scenario. Actual router or NIM capabilities can vary by model and deployment:
simulated tests do not prove acceptance by every remote account. External HTTP failures remain
visible.
