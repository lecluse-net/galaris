<p align="right"><a href="../../fr/components/deepseek-harness.md">Français</a> · <strong>English</strong></p>

# DeepSeek Harness

This bridge provisions one DeepSeek Harness instance per Agent through the generic
`bridge.harness` manager. Execution returns exclusively through the shared `app.harnesses` Chat
Completions client, so `app.agent` depends on neither the Python SDK nor DSH's native JSON-RPC.

The Galaris profile explicitly sets `llm-deepseek.protocol: chat-completions` for the LLM
gateway. DSH 0.1.6 defaults to Messages, which does not match the OpenAI URL injected by
the provisioner.

The container builds the DSH revision pinned by `harness_provider.py`, then exposes:

- `GET /v1/models`;
- `POST /v1/chat/completions`, streamed or non-streamed;
- `GET /healthz` for Compose.

SSE mode subscribes to the SDK's official `on_notification` callback. It immediately relays
`assistant/chunk` events as Chat Completions deltas, completed reasoning and `tool/result` as
`galaris.agent-message/v1`, then publishes `galaris.agent-result/v1` with the exact final response.
Keepalive comments are now used only while the SDK produces no event; content is never fabricated
by splitting the response afterward.

The provisioner injects two distinct secrets into `.env` on the Harness Manager host: the Harness
API token, stored encrypted by `app.harnesses`, and a rotating MCP system token. The latter
authenticates both `/api/mcp/{agent_code}` and the `/api/llm/openai` gateway. No LLM-provider or
business-connection credential enters the container.

The technical context rendered by the adapter keeps the Task and run identifiers in the prompt
sent to the gateway; its extractors therefore restore them on every `LLMCall`, even when the
DeepSeek SDK does not allow arbitrary HTTP headers. At termination, the shared client aggregates
these persisted traces and their qualified cost. Partial SDK counters are used only as a fallback
when no correlated call exists.

Actually authorized Skills are copied under `data/skills`; the DSH filesystem provider is isolated
with `includeDefaultRoots: false`. Durable memory, canonical files, and external effects pass
through Galaris MCP. The local DSH workspace is a compute area: a file becomes durable only when a
Galaris Tool records its URI and effect.

The first image build downloads and compiles the pinned DSH revision and may therefore take a long
time. `update` rebuilds the image; `refresh` resynchronizes the model, MCP token, and Skills, then
restarts the instance. Only one run is admitted at a time per instance, in accordance with the
current per-Agent Task serialization.
