<p align="right"><a href="../../fr/components/deepseek-harness.md">Français</a> · <strong>English</strong></p>

# DeepSeek Harness

This bridge provisions one DeepSeek Harness instance per Agent through the generic
`bridge.harness` manager. Execution returns exclusively through the shared `app.harnesses` Chat
Completions client, so `app.agent` depends on neither the Python SDK nor DSH's native JSON-RPC.

The Galaris profile uses `llm-pi-ai` with the `openai-completions` protocol for the LLM
gateway. The native DeepSeek adapters, which speak Messages exclusively, are disabled.
The current model is passed to the profile for each execution.

The container builds the DSH revision pinned by `harness_provider.py`, then exposes:

- `GET /v1/models`;
- `POST /v1/chat/completions`, streamed or non-streamed;
- `GET /healthz` for Compose.

DSH 0.2.1-rc.2 uses Node 24.22.1 and pnpm 11.28.5 for this build.
The Node version and digest are pinned to keep the runtime reproducible.

The build also compiles the native Landlock launcher before staging the runtime.
The shell retains `workspace-write` mode: workspace writes are allowed, while writes
to other mounts remain denied. Existing instances must rebuild their image to receive
this launcher.

The image disables the temporary native cache (`NARB_DISABLE_NATIVE_CACHE=1`):
the SDK loads the library directly from the installed package. It therefore does not
try to load a copy from `/tmp`, which remains non-executable.

SSE mode subscribes to the SDK's official `on_notification` callback. It immediately relays
`assistant/chunk` events as Chat Completions deltas, completed reasoning and `tool/result` as
`galaris.agent-message/v1`, then publishes `galaris.agent-result/v1` with the exact final response.
Keepalive comments are now used only while the SDK produces no event; content is never fabricated
by splitting the response afterward.

The provisioner injects two distinct secrets into `.env` on the Harness Manager host: the Harness
API token, stored encrypted by `app.harnesses`, and an MCP system token retained during
synchronization. A manager failure after configuration preparation therefore does not
invalidate the running container's identity. Runtime removal revokes this token;
per-run authority remains independent. The MCP token
authenticates both `/api/mcp/{agent_code}` and the `/api/llm/openai` gateway. No LLM-provider or
business-connection credential enters the container.

Before any model call, the adapter requires a loaded Galaris MCP catalogue. The SDK may
contain an optional plugin failure despite `failOnStartupError`: the adapter retries its
initialization up to three times, before any business action. Without a catalogue, it returns
an explicit error instead of letting the agent produce a false result without tools.
Existing provisioned instances need their image rebuilt to apply this check.

An HTTP 401/403 rejection during the initial identity check becomes a configuration
failure before SDK startup, with effects confirmed absent. It does not become an unknown
delivery outcome and exposes neither the secret nor the remote response body.

The MCP run context retains the `deepseek_harness` provider for authorization.
During human waiting, the proxy immediately sends headers and keepalives: SSE comments for
MCP calls, JSON whitespace for native authorization. The SDK client therefore does not abandon
the call after five minutes without a response. One final response resumes the original call
after the decision; keepalives never create another tool call. The SDK's wall-clock RPC deadline
is disabled for managed actors: run cancellation and authorization expiry bound their waiting.
Unmanaged calls retain their timeout. Existing instances need their image rebuilt for this fix.

The tool catalogue
uses the validated assignment's `openai_messages` driver; the Task comes from the server-issued
context, allowing Process activities to ask a human question and record results in their own run.

The technical context rendered by the adapter keeps the Task and run identifiers in the prompt
sent to the gateway; its extractors therefore restore them on every `LLMCall`, even when the
DeepSeek SDK does not allow arbitrary HTTP headers. At termination, the shared client aggregates
these persisted traces and their qualified cost. Partial SDK counters are used only as a fallback
when no correlated call exists.

Actually authorized Skills are copied under `data/skills`; the DSH filesystem provider is isolated
with `includeDefaultRoots: false`. Durable memory, canonical files, and external effects pass
through Galaris MCP. The local DSH workspace is a compute area: a file becomes durable only when a
Galaris Tool records its URI and effect.

The native `read` tool validates the current run context without requesting a mutation
permit, including when reading a projected Skill outside the workspace. A revoked context
still blocks that read. Qualification uses the real SDK to check both cases; write-only
scenarios did not cover this native tool name.

The first image build downloads and compiles the pinned DSH revision and may therefore take a long
time. In Galaris supervision, **Restart** or **Update** recreates the selected runtime with
its credentials; **Refresh** only requests Skill projection. To repair an older container
with a stale token, use **Restart**, wait until it is ready, then retry the Task. This
management operation does not retry any delivery. Only one run is admitted at a time per
instance, in accordance with the
current per-Agent Task serialization.
