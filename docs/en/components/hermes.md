<p align="right"><a href="../../fr/components/hermes.md">Français</a> · <strong>English</strong></p>

# Hermes Backend Bridge

This package contains only Hermes-specific behavior: the session and run client, the `app.agent`
Driver, configuration generation, LLM/MCP/memory/voice integration, and transport of
runtime-specific files.

The embedded MemoryProvider calls the private `/memory/provider/*` endpoints, which are also owned
by this bridge. The ephemeral brief already classified by `app.memory` is attached to the current
Hermes run in the backend process; explicit writes go back through the governed `app.memory`
facade.

Host-side management of directories, Docker Compose containers, and files belongs to the generic
[`harness_manager`](harness-manager.md) service. Each Hermes Agent uses an instance named after its
code, with its own Compose project, volume, and `<code>-agent` container. Several Harness types may
share the manager, but runtimes never share an instance.

## Instance Management

The package generates the Compose configuration and all Hermes files, then calls the generic
Harness Manager to create, start, stop, update, and delete the instance. Data are projected into
`BASE_DIR/<code>/data` on the manager and mounted at `/opt/data` in that Agent's sole container.

Execution uses the structured Hermes APIs (`/api/sessions`, `/v1/runs`, and run cancellation).
The Harness Manager never receives a Hermes command, Kanban payload, or agentic execution decision.

## Harness Manager Configuration

Configure the manager URL, optional API URL and shared secret in
**Preferences → Harnesses → Managed harnesses → Configure the Harness Manager**. These database Params are shared by all
harnesses; the secret is encrypted. No manager variables are needed in the Galaris `.env`.
The UI also prepares the host service `.env` for copying to the local or remote host.
See the [manager guide](harness-manager.md) for installation and existing deployments.

Configure `compose.yaml` in **Preferences → Harnesses**, shared by all containerized providers.
No network is appended after operator settings. Hermes `config.yaml` and secrets remain
on the Hermes page. Individual Compose overrides take precedence over shared configuration.
API addresses must be reachable from the containers; backend → runtime connectivity must
also be provided by the deployment topology.

Each Galaris deployment provisions this configuration and secret explicitly over a secure channel.
It never reads the manager's `.env`, which may be on another host. After the backend adopts the new
environment, `make test-harness-management` checks the generic contract without loading Hermes
parameters.

Hermes selects this already-configured generic client. The Galaris URL injected into containers is
therefore shared by all managed runtimes and is not a Hermes parameter.

The `back/bridge/harness` client sends a short Fernet nonce in `X-Harness-Token`. Consumed routes
live under `/instances/{agent.code}`. Creation deliberately produces an empty directory;
`_sync_config` then projects the `Makefile`, Compose file, `.env`, `data/config.yaml`,
`data/SOUL.md`, scripts, plugins, and Hermes Skills. Compose overrides remain specific to the
affected Agent.

## Native Tools

Synchronization maintains a single authority for capabilities already provided by Galaris. When
the MCP functions `image_generate` or `image_read` are actually visible to the Hermes Agent, the
corresponding native `image_gen` or `vision` toolsets are added to `agent.disabled_toolsets`.
Removing them is reversible if the Galaris function is disabled, and an explicit override in the
global or Agent configuration remains respected.

Native Hermes Skills remain available on demand alongside the Skills assigned and projected by
Galaris under `skills/galaris/`. Galaris does not disable them globally and preserves explicit
operator choices in `skills.disabled`.

## External Console and SSH Terminal

When an Agent has an active external **Console** connection, synchronization configures the
Hermes native terminal's `ssh` backend with the same target. The terminal, native file operations,
and `execute_code` then work in the remote SSH home instead of the Hermes container. An embedded
Console (`ssh-executor`) does not trigger this projection.

The private key is decrypted only during synchronization, exported without a passphrase for the
non-interactive OpenSSH client, then written with mode `0600` under the managed
`data/.galaris/ssh/` directory. It is never written to `config.yaml`. Per-instance `known_hosts`
and `ssh`/`scp` wrappers enforce `StrictHostKeyChecking=yes`, the host key configured in Galaris,
and the connection timeout. Hermes reads them at `/opt/data/.galaris/ssh` in its dedicated
container.

If the external connection is disabled, deleted, or replaced by the embedded executor, the
materialized credentials are removed and the previous terminal values are restored. A
materialization failure stops synchronization so Hermes cannot silently fall back to a local
Console.

## Kanban

Kanban-based `high` execution is disabled by ADR 0013. The Harness Manager exposes no Kanban CLI
translation, and the bridge no longer has a shared backend for that transport. A legacy Kanban
checkpoint is therefore rejected explicitly instead of being converted into a direct run or
reintroducing a specific command into the generic server.
