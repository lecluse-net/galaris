<p align="right"><a href="../../fr/components/claude-agent.md">Français</a> · <strong>English</strong></p>

# Claude Agent Harness

This bridge provisions an isolated Claude Agent SDK instance per Agent through the generic
`bridge.harness` manager. Galaris executes it through the shared `app.harnesses` Chat Completions
client; neither the Claude SDK nor its internal protocol leaks into `app.agent`.

The container exposes:

- `GET /health` for Compose health;
- `GET /v1/models` for the provider probe;
- `POST /v1/chat/completions`, as JSON or SSE.

The requested model is the execution model already resolved by `app.agent`. The SDK must use
`/api/llm/anthropic` with a rotating system token. Galaris internal models therefore remain
available, and every LLM call is correlated with the Task and run. The same token grants access to
the Agent's sole MCP endpoint. No direct Anthropic credential enters the container.

Authorized Skills are projected under `data/skills/.claude/skills`, the workspace under
`data/workspace`, and Claude state under `data/claude`. The container is unprivileged, read-only
outside the `data` volume, has no Linux capabilities, and has process, CPU, and memory limits.

## Telemetry

The transport remains compatible with an ordinary Chat Completions server. For this provider,
Galaris additionally enables two named and versioned SSE events:

- `galaris.agent-message/v1` carries completed Tool calls and public reasoning blocks normalized
  as `AIMessage`;
- `galaris.agent-result/v1` carries the authoritative final response, usage, cost, SDK session,
  terminal status, and permission denials for the single `ExecutionResult`.

Text deltas remain standard OpenAI chunks and may contain provisional progress before a Tool call.
At close, `ResultMessage.result` replaces that text in the durable result; the UI therefore receives
live progress followed by the exact final response. In parallel, calls to the Anthropic gateway
populate `LLMCall` records correlated with the `run_id` throughout execution. At termination, the
shared client aggregates these persisted traces and treats them as the primary token and cost
source. SDK usage remains a `partial` fallback when the gateway produced no trace; it therefore
cannot hide an exact provider cost or a pricing estimate explicitly qualified by Galaris.

A Task with automatic approval uses `bypassPermissions`. In every other case, the permission
callback rejects the operation instead of allowing the runtime to simulate human approval. Turn
and Tool counts follow the limits frozen in `AgentRunEnvelopeV1`.

`start`, `restart`, and `update` build or recreate the image pinned by `requirements.txt`.
`refresh` reprojects configuration, MCP token, and Skills before restarting. Deleting the Harness
destroys the instance and revokes its system tokens.
