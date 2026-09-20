<p align="right"><a href="../../fr/components/harness-manager.md">Français</a> · <strong>English</strong></p>

# Containerized Harness Manager

## Runtime versions

Codex and Claude Agent builds install the Python SDK versions pinned in their respective
`requirements.txt` files. The image's `requirements-resolved.txt` records the versions actually
installed. Each new version is qualified before changing these references.
Updates occur during explicit builds/rebuilds, never in the middle of a Task.
Changing the code alone does not update existing containers.

As of September 17, 2026, Hermes targets `v2026.9.14` (0.21.3), and DeepSeek Harness targets
`dsh-v0.1.6-alpha.1`, commit `0a15e36e7f82b6ed45af6fa9759f29b40dcd965d`.
DeepSeek remains a prerelease; both references stay pinned.
Codex uses `openai-codex==0.154.0` and Claude Agent uses `claude-agent-sdk==0.2.154`.

## Responsibilities

Supervision responses provide `available_actions`, derived from the durable lifecycle, observed
status and current provider capabilities. Agent cards consume this projection instead of maintaining
a separate action matrix. `absent` offers Create through `restart`, `stopped` offers `start`, and
`provisioning`/`deprovisioning` offer no concurrent commands. Server-side guards on non-terminal
Tasks remain authoritative when rebuilding a runtime.

This generic FastAPI service lets Galaris create, control, and delete directory-isolated Harness
instances. It runs on the Docker host outside the Galaris stack and confines every operation to
`BASE_DIR`.

It knows no specific runtime: neither Hermes, Claude Code, Codex, nor DSH. Each runtime's backend
bridge builds its files, Compose project, and configuration, then uses this manager only for
lifecycle operations and file transport.

```text
bridge.<runtime> in Galaris
       │ authenticated HTTP requests
       ▼
harness_manager on the host
       │ bounded files and Make actions
       ▼
BASE_DIR/<instance> ──► Docker Compose ──► selected Harness
```

## Contract

The service announces `bridge.harness` and the `compose-lifecycle` and `file-share` capabilities
on `GET /`. Its public routes are deliberately generic:

| Route | Purpose |
|---|---|
| `GET /instances` | list instances |
| `POST /instances` | create an empty directory or create one from a template |
| `DELETE /instances/{id}` | stop and then delete an instance |
| `GET /instances/{id}/status` | read Docker Compose status |
| `GET /instances/{id}/logs` | read the latest log lines |
| `POST /instances/{id}/actions/{action}` | run `start`, `stop`, `restart`, or `update` |
| `/instances/{id}/files/...` | read, write, or delete a small encrypted text file |
| `/instances/{id}/raw/...` | stream an authenticated binary file |
| `DELETE /instances/{id}/trees/...` | purge a bounded directory tree |

Each instance provides its own `Makefile`; only the four actions listed above are accepted. The
manager runs no Harness-specific CLI and creates no business directory. Those responsibilities
belong to the consuming bridge. `restart` is convergent: when the instance has no Compose
container yet, the manager runs its `start` action to create one.

## Installation

Prerequisites: Linux, Docker Engine with the Compose plugin, GNU Make, Python 3, and `curl`.

```bash
cd harness_manager
make install
make start
```

`make install` installs `uv` and the environment under `.local/`, creates `.env` if missing,
generates a Fernet key, and initializes `~/galaris-harnesses` as `BASE_DIR` by default. Review
`.env` before exposing the service on the network.

For durable operation:

```bash
make service-install
make service-status
```

Configure **Preferences → Harnesses → Managed harnesses → Configure the Harness Manager** in Galaris: manager URL, optional
API URL seen by harnesses, and shared secret. Preferences are stored in the database and apply
immediately; the secret is encrypted and masked on ordinary reads. No manager variables are
needed in the Galaris `.env`.

For a new installation, generate a Fernet key in the UI, save the preferences, then generate
the host manager `.env`. Review the listening IP/port, source IP filter, instance directory and
file limits. Copy or download the file and save it as `.env` under `harness_manager` on the target
host. Create `BASE_DIR` with service-user write permissions and follow the displayed commands.
Protect the secret file with `chmod 600 .env`. Exporting does not modify the remote host.

**Download ready-to-install ZIP** packages the source and prepared `.env` together. This private
archive requires preference editing rights; the separate source ZIP contains no secret.
The generated `GALARIS_UPDATE_URL` can be changed in the host options and must be reachable
from the manager host. The included README supports installation without the full repository.

For an existing manager, preserve its key and directory. DbAdmin imports legacy
`HARNESS_MANAGER_URL`, `HARNESS_MANAGER_GALARIS_API_URL` and `HARNESS_MANAGER_SECRET` once,
only when the corresponding preference is missing. After synchronization, remove these variables
from the Galaris `.env`; database preferences take precedence.

Provision the secret over a secure channel: no Galaris checkout reads the manager's `.env`.
Galaris derives injected API URLs from `HARNESS_MANAGER_GALARIS_API_URL`, falling back to `APP_HOST/api`
when empty. On a local isolated network, `http://backend:8000/api` avoids public DNS and reverse
proxy dependencies. Remote managers require a URL reachable from their containers. Configure networks
explicitly in the shared Compose section of **Preferences → Harnesses → Managed harnesses** (`harness.default.compose`). These overrides
are shared by Hermes, Codex, Claude Agent and DeepSeek Harness; `services.agent` targets their main
service. No network is appended from backend environment settings. The historical
`HARNESS_MANAGER_DOCKER_NETWORK` variable no longer attaches a network. The backend still calls
runtimes through stable container names: the operator topology must provide this route, without
assuming a shared host. DbAdmin transfers the old `hermes.default.compose` value to the shared
parameter without overwriting an existing shared value. Move any Hermes-specific settings into
individual overrides before recreating other harnesses. After saving the UI configuration,
run from the Galaris checkout:

```bash
make test-harness-management
```

This test writes no database Param and loads no Hermes option.

## Guided diagnostics

**Preferences → Harnesses → Managed harnesses** keeps connectivity, connection fields and
manager versions visible. **Prepare installation** opens ZIP and `.env` options; **Update manager**
opens update instructions and the source ZIP. **Connection help** opens the two guides,
**Manager on this machine** and **Remote manager**. Each guide covers installation, listener
address, shared secret, API URL, networks and final verification. Standard backend Compose
provides `host.docker.internal:host-gateway`; this alias attaches no harness network and
does not replace manager service configuration.

`GET /api/harness-manager/diagnostics` requires configuration privileges. It distinguishes
missing/invalid secrets, DNS, TLS, timeouts, HTTP denials and incompatible services. It never
returns secrets, tokens or remote error bodies. Displayed URLs exclude credentials, query
parameters and fragments.

Checks run every 30 seconds and can also be requested manually. Successful manager connectivity
does not prove that containers can reach Galaris: this second direction remains explicitly
**not checked** until tested from a harness. Diagnostics execute no MCP tool and change neither
configuration nor containers.

## Configuration

| Variable | Initial Value | Purpose |
|---|---|---|
| `API_HOST` | `127.0.0.1` | listen address |
| `API_PORT` | `8485` | listen port |
| `ALLOWED_IP` | empty | client accepted in addition to localhost |
| `HARNESS_MANAGER_SECRET` | generated | Fernet key shared with authorized clients |
| `GALARIS_UPDATE_URL` | endpoint supplied by Galaris in the prepared ZIP | manager update endpoint |
| `BASE_DIR` | `~/galaris-harnesses` after installation | absolute instance root |
| `IGNORE_DIRS` | empty | children of `BASE_DIR` protected from every operation |
| `MAX_FILE_SIZE_MB` | `1` | encrypted text-write limit |
| `MAX_RAW_FILE_SIZE_MB` | `512` | binary upload ceiling, checked during streaming |

Instance names accept lowercase ASCII letters, digits, hyphens, and underscores. A name must begin
with a letter or digit. Templates may have any name but must remain under `BASE_DIR`.

## Security and Files

Every request must provide `X-Harness-Token`, a Fernet nonce encrypted with the shared secret and
valid for 60 seconds. Small text files are encrypted a second time in their body. The binary
channel is streamed without additional application-level encryption, so it must remain on a
private network or use TLS. A text write may request only `0600`, `0644`, or `0755`; the file is
prepared with that mode and then replaced atomically. Bridges notably use `0600` for SSH
credentials materialized in a runtime.

The service also enforces:

- an optional IP policy;
- canonical path resolution and traversal rejection;
- prohibition of directories listed in `IGNORE_DIRS`;
- a closed list of lifecycle actions;
- exclusion of manager variables from Compose subprocesses;
- explicit timeouts for Docker, Make, and logs.

Deletion stops the instance and removes its declared Compose volumes, then atomically renames its
directory to a hidden directory before erasing its data. The canonical name is therefore released
immediately even if a container left files the host user cannot delete. Those remnants stay in
quarantine and are reported in the manager log instead of blocking recreation. Declared
`external` Compose volumes naturally remain outside this cleanup.

If Docker shutdown or cleanup fails, the canonical directory remains and its identity cannot
be reused. Inter-process locks protect concurrent creation, deletion and commands; a conflicting
operation returns HTTP 409.

The `raw` channel enforces a configurable 512 MiB default ceiling, including uploads with no
declared size. Clients must also stream and enforce any stricter limits required by their domain.

## Updating

The manager has its own deployment lifecycle and may live on a different host from Galaris.
Its fixed version comes from `harness_manager/pyproject.toml` (currently `1.1.0`) and is reported
by `GET /`. Preferences show installed and available versions, warning about available updates,
newer installed versions or unknown versions without marking the connection as failed.
From its directory on the Docker host, as the service user:

```bash
cd harness_manager
make update
```

The Galaris repository's `make update` target never updates or restarts the manager. Each
deployment must coordinate their versions separately and keep network coordinates and the shared
secret consistent.

The command uses `GALARIS_UPDATE_URL` from `.env`; a one-off override is available through
`make update UPDATE_URL=https://galaris.example/api/harness-manager/updates`. Downloads use
the shared key. Before changing files, the client verifies the authenticated manifest,
version and SHA-256 checksum. Redirects and downgrades are refused. Only the explicit source
file list can be replaced; `.env`, instances and other local files are preserved.

Previous source files are backed up under `.local/backup-<version>-…`. The updater installs
locked dependencies and restarts an active manager in its original mode (user systemd or
background process), then verifies its version. On failure it attempts to restore the old
code and environment, reporting the backup path if recovery fails. A stopped manager stays
stopped. Harness containers are not rebuilt. Avoid management operations during the interruption.

For an older installation without this command, stop the service, extract the **source-only ZIP**
into its existing directory once, run `make install` and restart the service. Add the endpoint
shown by Galaris as `GALARIS_UPDATE_URL` in the existing `.env`, preserving its key and `BASE_DIR`.

The backend image includes the distributed sources. Rebuild it when introducing this feature;
in development, recreate the backend container to activate the manager source bind mount.
Subsequent source edits use that mount.

Renaming from the former Hermes server is deliberately incompatible: the directory, secret
variable, authentication header, and routes changed. Reinstalling the service and reconfiguring
its consumers is the expected procedure.

If the moved local directory already contains an `.env`, `make install` preserves it. Explicitly
replace `GALARIS_BRIDGE_HERMES_SECRET` with `HARNESS_MANAGER_SECRET` and check `BASE_DIR`, or
archive the old file before a fresh installation. Do not retain both variables as a compatibility
mechanism.

If the old user systemd service was installed, stop it before enabling the new one:

```bash
systemctl --user disable --now galaris-bridge-hermes.service
cd harness_manager
make service-install
```
