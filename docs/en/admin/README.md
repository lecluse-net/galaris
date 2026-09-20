<p align="right"><a href="../../fr/admin/README.md">Français</a> · <strong>English</strong></p>

# Administrator Guide

This guide covers the deployment, configuration, and operation of Galaris. Commands are run from the repository root.

For a first installation, follow the [three-step guide](installation.md):
**`make install` → configure `.env` → `make update`**. The following sections detail
administration options.

## 1. Prepare the Host

Recommended prerequisites:

- Recent Linux x86-64 or ARM64;
- Docker Engine with the Compose plugin;
- Git, GNU Make, and OpenSSL;
- at least 4 GB of memory for a small deployment;
- a DNS name and a TLS proxy for exposure outside the local network.

The provided setup starts the frontend, backend, SearXNG, and the local SSH Console. By default,
Make also adds PostgreSQL with pgvector from `compose.postgres.yaml`. The
`compose.override.yaml.example` file publishes the frontend with `8484:8484` and defines the
`galaris_data` application volume mounted at `/data`. Adapt the override for an external proxy and
select the database mode in `.env`.

The frontend listens on 8484 in both development (Vite) and production (Nginx).
On existing installations, replace `8484:8000` with `8484:8484` in the override
and update any proxy targeting the frontend container directly to port 8484.
Then apply the configuration with `make update`.

`compose.yaml` always mounts `data/search/settings.yml` and `data/search/limiter.toml`,
initialized by `make start`. These mounts are required for the `search_web` JSON API,
including installations with an older custom override. The initial configuration keeps
the pinned SearXNG version's engine selection without forcing Bing; existing installations
retain their explicit choices. After editing these files,
recreate only the `search` service using your installation's Compose files and verify
an actual JSON search.

`make check-search` sends four synthetic public queries (French, English, German) and
prints the first sources and coverage limitations. The script exits with 0 when every
query has sources without reported degradation, 1 when a query fails or lacks sources,
and 2 when all have sources but some engines are degraded. Make treats both nonzero
codes as failures; read the JSON lines for details. Exit 0 does not certify relevance:
also review titles and URLs. This opt-in probe is separate from the healthcheck and
tests without external network access. To compare an isolated instance:
`make check-search ARGS='--url http://<instance>:8080/search'`.

Older configurations may force Bing. If the corpus confirms unrelated results, remove
that override from `data/search/settings.yml` or set `disabled: true` for this engine,
then recreate only Search. Updates preserve this operator-owned configuration and do
not bypass engine protections.

Each conversation attempt is limited to 15 minutes, including searches and the final
answer. This gives long-reasoning models time to finish after tool calls; cancellation
and lease loss still stop the round immediately.

```bash
git clone <repository-url> galaris
cd galaris
make install
```

`make install`:

1. checks Docker, Compose and OpenSSL;
2. offers to include PostgreSQL (yes by default), then creates `.env` if it does not exist;
3. copies the example Docker override;
4. initializes SearXNG;
5. generates missing secrets.

Then configure `.env` and run `make update` to build images and start Galaris.
The supplied override fits the standard installation.

The installation never replaces an existing `.env`. During an upgrade, an existing
`docker-compose.override.yaml` is automatically renamed to `compose.override.yaml`
without changing its contents.
The existing `POSTGRES_MODE` choice is preserved. For unattended installation
without bundled PostgreSQL, use
`make install POSTGRES_MODE=external`.

## 2. Configure `.env`

Treat `.env` as a secret. Do not commit it or attach it to a bug report. `.env.example` is the
complete reference for deployment settings accepted in `.env`, including advanced options.
Optional settings are commented out with their defaults; uncomment only those you customize.
Installation fills generated values. Reducing configuration means removing or relocating
settings, never hiding an option the code still accepts. Relocated functional settings are
documented and administered in **Preferences**.

### Application and Network

| Variable | Role |
|---|---|
| `APP_NAME` | container prefix and technical name |
| `APP_HOST` | canonical public URL, including scheme |
| `APP_ENV` | Free-form label, default `prod`. Only `dev` enables development; every other value (`pp`, `test`, `demo`…) uses production behavior. |
| `POSTGRES_MODE` | `embedded` (default) for the provided container, `external` for an existing database |
| `TZ` | container time zone |
| `BACK_ALLOWED_HOSTS` | optional additional hostnames or IPs, comma-separated, without scheme or port |

The backend automatically allows `localhost`, `127.0.0.1`, the Docker service name
`backend`, `${APP_NAME}-back`, `${APP_NAME}-front`, and hostnames extracted from `APP_HOST`
and the optional `HARNESS_MANAGER_GALARIS_API_URL`. These addresses work with their respective
ports, directly or through Nginx. Leave `BACK_ALLOWED_HOSTS` empty unless you need other aliases
or IPs, for example `api.internal.example,192.0.2.10`. An explicit `*` remains supported and
disables host filtering, including in production; development adds it automatically.
This setting validates the HTTP `Host` header and does not change CORS, whose allowed origin
remains `APP_HOST`.

`APP_NAME` isolates the technical resources of multiple installations; it does not rename the
product, whose visible identity is always **Galaris**. The application version is not configured in
`.env`: Make derives an exact Git tag when available, otherwise the current branch or detached
commit, and bakes that reference into the backend image for telemetry.

In production, place an HTTPS reverse proxy in front of the frontend and set `APP_HOST` to the
URL actually used by users.

Connect the external proxy only to the frontend. The Compose application network already connects the
frontend, backend, and SearXNG; the backend does not need to join the proxy's shared network. This
topology remains compatible with Caddy, Traefik, or another external TLS terminator.

The external HTTPS proxy must preserve `Host` and overwrite `X-Forwarded-Proto` with the client's
actual protocol (`https`). Nginx forwards this indication to the backend; without it, an API redirect
can point back to HTTP and be blocked by the browser. The frontend must be reachable through this
trusted proxy. For direct HTTP access, omitting this header preserves HTTP.

The provided Nginx accepts up to 1 GiB only on
`/api/chat/rooms/<uuid>/attachments`, 52 MiB for skill package imports, and 16 MiB on
the rest of the API. The business limit per attachment, administrable with
`MESSENGER_CONTENT_MAX_MB`, is 1,000 decimal MB. An external proxy must apply an equivalent
exception to the attachment route: its own limit, if lower, remains authoritative.

Browser audio calls pass directly through WebRTC and do not go through the HTTP proxy.
`compose.turn.yaml` provides a lightweight coturn container on the host network. Make adds
it by default when `WEBRTC_TURN_MODE=embedded`. With `WEBRTC_TURN_HOST=auto`, the backend
derives its public name from `APP_HOST` and uses the dedicated port 3479:

```dotenv
#WEBRTC_TURN_MODE=embedded
#WEBRTC_ICE_URLS=
#WEBRTC_TURN_HOST=auto
#WEBRTC_TURN_PORT=3479
#WEBRTC_TURN_MIN_PORT=47000
#WEBRTC_TURN_MAX_PORT=47100
#WEBRTC_TURN_RELAY_IP=auto
#WEBRTC_TURN_TTL_SECONDS=3600
```

These defaults are commented out in `.env.example`: uncomment only settings you need
to customize. The shared secret and resolved relay address remain automatically populated
in `.env`.

`bin/update-secrets.sh`, called during installation, when embedded mode starts, and before
`make update`, generates
`WEBRTC_TURN_SHARED_SECRET`. This same secret is injected into coturn and the backend, which derives
temporary TURN REST credentials for each authenticated user. The shared secret never leaves the
server. Therefore, no WebRTC variable is required for embedded mode: the browser uses the name
derived from `APP_HOST` and the detected LAN IPv4 address as a fallback path, and the backend
automatically connects to coturn through `host.docker.internal`, including when the application name
is resolved differently by the browser, an internal DNS server, or the Galaris host.
At startup, Compose detects the public address and forces relay sockets onto the primary LAN IPv4
address. It passes this pair to coturn as `--external-ip=<public>/<LAN>` so that candidates announce
the public address without allocating media ports on a Docker bridge. On a host whose first address
is not the one receiving the TURN range from the router,
`WEBRTC_TURN_RELAY_IP` must explicitly contain that LAN IPv4 address.
`bin/update-secrets.sh` resolves `auto` differently from the default IPv4 route and preserves the
machine-specific result in `WEBRTC_TURN_RELAY_IP_RESOLVED`; no LAN address is hardcoded in the
images or repository. The backend publishes the public address and this LAN alias in its ICE
response. It also provides the browser with the numeric LAN TURN locator, which can obtain its own
relay candidate without depending on application-name resolution or NAT hairpinning. A smartphone
on the same network can therefore connect directly to the relay when the router accepts HTTP NAT
hairpinning but not UDP NAT hairpinning.

To reuse an existing TURN server, the administrator changes the mode and replaces the derived
configuration. Make then does not add `compose.turn.yaml`:

```dotenv
WEBRTC_TURN_MODE=external
WEBRTC_ICE_URLS=stun:turn.example.org:3478,turn:turn.example.org:3478?transport=udp,turn:turn.example.org:3478?transport=tcp
WEBRTC_TURN_SHARED_SECRET=<same value as static-auth-secret in coturn>
```

The existing coturn must use `use-auth-secret`. No Galaris TURN container is then required.
`WEBRTC_TURN_MODE=disabled` also excludes the dedicated Compose file and hides the call button in
production, even if old URLs remain in `.env`.

The firewall and, where applicable, the upstream router must publish the
`WEBRTC_TURN_PORT` port over both UDP **and** TCP, as well as the
`WEBRTC_TURN_MIN_PORT`–`WEBRTC_TURN_MAX_PORT` range over UDP, to the Galaris host. The default
values, 3479 and 47000–47100, avoid the usual TURN ports so that another coturn can coexist on
the same host; they can be changed together in `.env`. This opening does not apply to Galaris when
it only reuses an external TURN server.

In a `prod`, `preprod`, or `demo` environment, Galaris hides the call button until an authenticated
`turn:`/`turns:` relay is configured; STUN alone is not a sufficient guarantee behind Docker or on
a mobile network. When a call starts, the backend also verifies that
`aiortc` actually obtained a `relay` candidate and rejects the call if the relay is unavailable,
instead of recording a silent call with a private Docker address.

### PWA and Persistent Sessions

The PWA is generated by the frontend and requires no additional Docker service. For a phone to
install it, the public URL must be served over HTTPS and the frontend and `/api` must remain on the
same origin. The reverse proxy must preserve the `Host` header: the `/api/auth/refresh` and
`/api/auth/logout` routes reject a different origin.

Access tokens last 30 minutes, refresh sessions expire after 30 days of inactivity, and concurrent
refreshes have a fixed 10-second grace period. The refresh cookie is always named
`galaris_refresh`.

`APP_HOST` must begin with `https://` in production so that the cookie is marked
`Secure`. It is also `HttpOnly`, `SameSite=Lax`, and limited to the `/api/auth` path. Never
place the frontend and API on different public domains without reviewing this contract.

At login, the backend creates a session family in `user_refresh_sessions` and stores only the
SHA-256 hash of the opaque token. Each refresh locks the row, replaces the token, and extends the
expiration. Reuse after the short concurrency window is treated as a replay and revokes the
entire family. Logging out revokes the current session; changing a password or disabling the
account revokes all of the user's persistent sessions.

During an update, `make update` automatically creates the declarative table with Atlas before
making the backend available. The provided `nginx.conf` prevents durable caching of `sw.js`
and the manifest; preserve these rules in any proxy that replaces it. The user-facing instructions
are in the [PWA guide](../user/pwa.md).

### Account Hardening

Each user can enable a second TOTP factor from their profile. The secret is encrypted with
`ENCRYPTION_MASTER_KEY`, the ten recovery codes are stored as hashes, and they are displayed only
when generated. A TOTP code already accepted within the same window cannot be replayed.

Login failures trigger a fixed progressive lockout policy per account: after 5 failures, the delay
starts at 30 seconds and grows exponentially up to 1 hour. A successful password and MFA
authentication resets the counter. This protection cannot be weakened through deployment
configuration.

### Required Secrets

| Variable | Usage |
|---|---|
| `ENCRYPTION_MASTER_KEY` | encryption of connection secrets |
| `POSTGRES_PASSWORD` | PostgreSQL account |
| `WEBRTC_TURN_SHARED_SECRET` | temporary credentials for the integrated or external coturn audio relay |

`bin/update-secrets.sh` generates only missing values. Changing
`ENCRYPTION_MASTER_KEY` without a rotation procedure makes already stored secrets
unreadable. **Never change, delete, or regenerate this key after installation: without
the original key, encrypted data is unrecoverable. Back it up alongside the database.**
Changing `AUTH_SECRET_KEY` invalidates current access tokens, but does not replace
revoking persistent sessions recorded in the database.

`AUTH_SECRET_KEY` is now an encrypted internal parameter, created once by DbAdmin and loaded
before the API serves requests. It is omitted from Preferences and their API. When the internal
parameter is absent, the first update generates a new key without reading `.env`, invalidating
old access tokens and MFA recovery codes. Subsequent updates preserve it. An invalid persistent
value stops startup instead of silently rotating the key.

The generic `/api/webhook/*` endpoint is disabled and `AUTH_WEBHOOK_TOKEN` is retired.
Messaging bridge callbacks and user tokens remain independent. After verifying persistent
credentials, `make update` removes the legacy `AUTH_SECRET_KEY`, `BROWSER_EXECUTOR_TOKEN` and
`AUTH_WEBHOOK_TOKEN` variables from `.env`. `ENCRYPTION_MASTER_KEY` remains in `.env`, with its
value and loading mechanism unchanged.

Web Push keys are also generated once as encrypted internal parameters, without importing
old environment variables. Updates remove the four `WEB_PUSH_*` variables from `.env` after
verifying the internal keys. On the first transition, reload the app on each device, then
disable and re-enable notifications using the Chat bell. Subscriptions remain valid across
subsequent updates. Configure the contact
and delivery delay in **Preferences → Messaging → Chat**. New installations generate
their pair automatically; set a `mailto:` or HTTPS contact appropriate for the instance.

Messaging, n8n, and Hermes secrets are entered in Preferences, encrypted with
`ENCRYPTION_MASTER_KEY`, and are never returned in clear text by the API. The private SearXNG
secret is generated directly in `data/search/settings.yml`.

### Centralized Observability

`LOG_LEVEL` stays in `.env` so it applies immediately at startup, before database access.
`LOG_LEVEL=DEBUG` or `TRACE` also enables the sanitized WebSocket diagnostic middleware; there is
no separate application debug flag.

`LOGFIRE_TOKEN` is optional and configured in **Preferences → System**. It is encrypted at rest
and never returned in plaintext by the API. Adding, replacing, or clearing it applies without
restarting. Local logs start before the database; remote export starts only after preferences
load. An existing `.env` token is imported once if the parameter is absent, then `make update`
removes its old line. When provided, the backend exports FastAPI traces, SQLAlchemy and
HTTPX spans, Pydantic AI events, system metrics, and Loguru logs to the corresponding Logfire
project. Headers, HTTP bodies, prompts, and binary contents are not collected by this
instrumentation. Without a token, no Logfire export is enabled. Automated tests explicitly
isolate telemetry; the `APP_ENV=test` label alone does not alter application behavior.

### Database

The default `POSTGRES_MODE=embedded` adds `compose.postgres.yaml` and waits for its service to become
healthy before starting the backend:

```dotenv
POSTGRES_MODE=embedded
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=galaris
POSTGRES_USER=galaris
POSTGRES_PASSWORD=<secret>
```

To use an existing database, disable only the provided container and specify an address reachable
from the backend. `compose.postgres.yaml` is then not loaded:

```dotenv
POSTGRES_MODE=external
POSTGRES_HOST=postgres.example.net
```

Also configure the port, database, user and password; pgvector must be available.
The PostgreSQL service and volume belong to `compose.postgres.yaml`, never to the installation
override. When switching to an external database, start and stop commands remove only the old
PostgreSQL container, without deleting its volume.

The backend still requires PostgreSQL, and `make update` continues to apply the declarative schema
and datasets through DbAdmin. External mode therefore does not disable synchronization.

`DB_POOL_SIZE + DB_MAX_OVERFLOW` must remain greater than the maximum number of simultaneous
Tasks, with headroom for the API, WebSockets, and administrative operations.
The `DB_POOL_PRE_PING=true` setting is especially important with a remote database.

These advanced settings are optional and listed as comments in `.env.example`.
When no corresponding line exists in `.env`, the backend uses these defaults:

| Setting | Default |
|---|---|
| `DB_POOL_SIZE` | 20 connections |
| `DB_MAX_OVERFLOW` | 20 additional connections |
| `DB_POOL_TIMEOUT` | 30 seconds |
| `DB_POOL_RECYCLE` | 1800 seconds |
| `DB_POOL_PRE_PING` | `true` |
| `DB_STATEMENT_TIMEOUT_MS` | 120000 ms |
| `DB_LOCK_TIMEOUT_MS` | 10000 ms |
| `DBADMIN_COMMAND_TIMEOUT_SECONDS` | 600 seconds |

Commented lines or values matching these defaults can be removed without changing
behavior. Startup overrides remain available when needed: database connections and
DbAdmin operations must work before preferences can be read. SQL and lock deadlines
bound individual operations, not entire agent runs; Atlas and target materialization
use the separate DbAdmin deadline.

### Language and Search

- **Preferences → Language** configures the fallback language for Tasks without a user, as
  well as the location given to Agents to contextualize date and time. A new installation
  uses English and `Paris, France`, respectively.
- **Preferences → Search** configures, among other things, the language used by SearXNG.
- The current profile's **Vector** usage enables semantic Memory recall. Its dimension is recorded
  with each projection and is not a Memory setting.

All prompts in Preferences use the same Markdown editor. The badge indicates whether they follow
the Galaris default or are customized. **See differences** compares the edited version with the
current default, and **Revert to default** re-enables automatic tracking. After an update that
changes a default, a customization is never overwritten: the editor asks whether to keep the
instance version or adopt the newly provided version.

A change of vector model triggers an asynchronous rebuild. Until it is complete, deep recall
explicitly falls back to lexical search.
The text chunks of each memory are sent to the selected provider: select an external provider only
if its privacy policy permits it. Leaving
Vector usage empty preserves lexical operation without sending any embeddings.

### Agent Memory

**Preferences → Memory** separately controls:

- the number of messages and characters from the recent session reconstructed from Messenger;
- enabling and budgeting the durable brief injected before an execution;
- the acquisition worker's frequency and number of attempts.

**Preferences → Dream** controls the opportunistic scanner, its leases, retries, and learning mode.
The `ai.memory-extraction-system-prompt` setting controls the extractor's complete prompt.
It applies to Tasks, text rounds, and transcribed audio turns that already have a Topic;
the Lab copies the value when creating a dataset, then allows that copy to evolve independently.
The **Topic folder creation** setting offers three policies: **Prohibit** reuses only existing
folders; **Ask for authorization** (the default) sends the original user a persistent choice between
creation, reuse, and no classification; and **Create automatically** creates one immediately only
after enhanced reuse checks fail. A proposal without an exploitable human conversation is never
created implicitly. The **Dream** usage, selected under **AI Models → Usages**, must reference a
small text model. Without a selected model, no subject requiring inference is requested. Dream
executes one mechanism at a time, without a driver or Tool, yields priority to Tasks, and stops as
soon as a Voice conversation begins.

The **Dream** page displays its current state, the requested mechanism and subject, phase,
memories created, retries, errors, and cost in real time.
Each witness can be opened to view the source Task and the prepared structured output. The
page is read-only, requires `TASK_ACCESS`, and refreshes its data only while open.

The **Memory** page allows selecting an Agent identity and then searching its memories with its
actual permissions. Its **Search** tab always uses hybrid deep recall, without a local selector.
Weights, the candidate pool, and diversity are configured globally in the **Memory** preferences
section. The engine maintains an automatic lexical fallback when the semantic path is unavailable.
Recall is limited to
20 results and is never launched while typing. The page also exposes content, revisions,
provenance, relationships, direct access, and, unambiguously, the owning Agent. There is no memory
space: inter-Agent access is granted directly on the relevant memory, while automatic acquisition
remains private. Eligible acquisitions are applied immediately and refusals are automatic: this
page is for viewing, correcting, explicitly sharing, archiving, or forgetting, never for approving
an entry. The three privileges are `MEMORY_ACCESS`, `MEMORY_EDIT`, and
`MEMORY_ADMIN`.

Markdown working documents use the same storage and ACLs, but are neither deduplicated with ordinary
memories nor forgotten due to simple inactivity. Their direct `read` or `edit` sharing is
administered by the owner, and each revision preserves the Agent and authoring Task when one exists.

The **Topic Folders** page administers global subjects used to connect Memory, Tasks, and
conversations independently of their channel. Dream first classifies Tasks and Voice turns, then
projects the memory links. A manual correction changes the assignment without modifying the
sources; automatic merging and splitting are not part of the current contract.

Agent records, Goals, and cycle reports also appear as generated documents.
Their banner clearly indicates this, and their owner remains visible. They are private, read-only,
not shareable, and not deletable from this page, including by an administrator:
modify or delete the source Agent record or Goal to change them. Keywords and
content are recalculated automatically; no human approval is required.

The list uses the application's standard pagination: 50 rows by default, with a choice of
10, 20, 50, 100, or 500 rows. Markdown content is rendered in the viewing window, and
ordinary Markdown memories can be edited with the visual editor.
To permanently bound the volume, only the last 100 cycles of each Goal have a
memory projection; older business cycles remain unchanged in their canonical table.

`DREAM_SKILL_LEARNING_MODE` is set to `off`, `observe`, or `learn` and remains `off` by default.
`observe` preserves evidence and proposals in Dream receipts without modifying skills; `learn`
creates, strengthens, revises, or weakens candidates belonging to the Agent. Dream also processes
all historical terminal Tasks progressively and idempotently, one operation per pass. A candidate
becomes an injectable skill in addition to assigned skills when the number of distinct
Tasks confirming the same procedure reaches `DREAM_SKILL_MIN_EVIDENCE` (3 by default)
and its score reaches `DREAM_SKILL_ACTIVATION_SCORE`, subject to
`DREAM_SKILL_MAX_ACTIVE`. These thresholds are configurable in **Preferences → Dream**. The
**Skills → Auto-learned** page, hidden when the mode is `off`, exposes score, evidence, and
injection state, and allows a procedure to be suspended immediately. Dream no longer creates a
Memory `experience` node, and old nodes are no longer injected.

The native provider's content resides under the fixed `/data/memory` directory, with
a maximum size per resource defined by `MEMORY_RESOURCE_MAX_BYTES`. In production, this path is in
the `galaris_data` Compose volume; in development, it corresponds to `./data/memory`. A
consistent backup must capture PostgreSQL and this volume at the same logical point:
database revisions contain opaque pointers to resources in the volume.

Archiving preserves the content but removes it from ordinary recall. **Permanently forget** deletes
the current content, all its revisions, sources, ACLs, links, vector chunks, and usage traces;
only a contentless tombstone remains. This action is irreversible. Memory installation and updates
to its models are applied automatically by `make update` before the backend is declared healthy.

To repair only sources whose memory link is missing:

```bash
make rebuild-source-memory
```

This reconciliation also forgets generated documents whose Agent record, Goal, or
parent Goal of the cycle no longer exists, for example after a temporarily missed deletion event.

To verify and refresh all projections without changing their UUIDs:

```bash
make rebuild-source-memory ARGS='--all'
```

When changing providers, first register the new provider, then recreate the
projections from the canonical sources:

```bash
make rebuild-source-memory ARGS='--recreate --provider CODE_DU_PROVIDER'
```

This last command deletes old projected resources, creates new items, and updates
the UUIDs in the Agent, Goal, and GoalCycle tables. It does not alter business data.

To repair the current semantic index without recalculating chunks that are already up to date:

```bash
make rebuild-memory-index
```

To force a complete recalculation after a controlled provider change or for diagnostic purposes:

```bash
make rebuild-memory-index ARGS='--all'
```

After accidental deletion of graph edges, rebuild the deterministic links
from their canonical sources with:

```bash
make rebuild-memory-links
```

The command creates no links until a Task or Voice session carrying memory provenance has a topic
folder. It puts exhausted classifications back into a pending state: then let
Dream finish the classifications and rerun the command. It rebuilds the
`cycle_of`, `result_of`, and `topic_contains` links; manual links or links resulting from a
consolidation decision cannot be recovered after a complete SQL deletion.

The `rebuild-memory-index` commands do not calculate anything in the CLI process: they register
durable jobs that the worker processes in the background. Without a Vector model in the current
profile, they perform no mutation. `rebuild-memory-links`, however, reconciles the edges
immediately and displays the number of links recreated.

## 3. Start and Initialize

```bash
make update
make logs-back
```

The backend entrypoint is idempotent. Before starting the API, it:

- compares the SQLAlchemy models with the PostgreSQL schema using Atlas;
- applies the declarative evolution;
- synchronizes privileges, settings, and system Tools;
- synchronizes reference data and repairable projections.

Then open `APP_HOST`. The first registered user is automatically assigned the `admin` role
if that role exists. Create this account in a controlled window, then verify
assignments in the administration interface.

## 4. Configure Language Models

Providers and models are administered in the LLM interface. A model contains the
name expected by the provider, its cost parameters, and its potential embedding
capability.

Assignments exist exclusively in model profiles. The global
`llm_profile_id` parameter contains no model: it only points to the current profile. An Agent
can choose a personal profile or retain “Current profile”; the latter choice is persisted
with a null `profile_id` and immediately follows any change to the current profile.

| Profile usage | Function |
|---|---|
| Executor | `standard` execution of the internal harness |
| Executor high | `high` execution, with the only permitted fallback being the standard executor from the same profile |
| Conversation | quick responses from the text conversation control plane |
| Dispatcher | `EXEC`/`PLAN` selection and Task effort; it does not execute conversations |
| Planner | plan creation and final synthesis |
| Briefing | mechanism retained for the Lab and possible reactivation; disabled in production |
| Goal | judgment and tracking of Goal cycles |
| Lab | Task analysis, reference proposal, judgment, and analysis of AI Lab benchmarks |
| Dream | Dream classification, extraction, and learning |
| Vector | Memory embeddings |
| Vision | image analysis |
| Document | document analysis |
| Audio | multimodal audio understanding when supported by the provider |
| Video | multimodal video understanding when supported by the provider |
| Image | image generation and editing |
| Transcription | dedicated STT model for voice messages and the `audio_transcribe` Tool |

An empty usage remains empty in the selected profile. A personal profile never borrows a value
from the current profile. The absence of an executor or conversation model prevents the relevant
path; it is never masked by an implicitly selected model.

### AI Lab Model

Select the **Lab** usage under **Providers & Models → Usages**. The model must have the
`chat` capability and reliably produce the requested structured outputs. It fills four deliberately
centralized roles:

- analyze Task evidence;
- propose an editable reference output;
- judge each semantic dimension of a benchmark;
- produce the Markdown report for a terminal run.

Choose a model powerful enough to judge candidate models. Its cost is added to
each case: a generic benchmark normally calls the candidate once and the judge once,
then an optional analysis makes one additional call for the run. Case contents
are sent to the Lab model provider; apply the same privacy policy as
for business Tasks.

Running the same model as both candidate and judge is allowed but increases the risk of
self-preference. Before using scores as a delivery gate, calibrate the judge against
human-scored outputs. The [operator guide](../user/lab-ai.md) describes the procedure, and the
[architecture documentation](../architecture/ai-lab-evaluation.md) details the biases and
formulas.

If the Lab model is absent, the proposal, benchmark, and analysis buttons are disabled or
return an explicit error. A judge failure must not be interpreted as a poor candidate result:
semantic mechanisms then display a missing score and a `partial` run.

## 5. Agent Drivers

The internal harness is always available. An external driver is offered on an Agent's
record only when it is enabled and correctly configured in **Preferences → Harnesses**.

This page has three tabs, using the same presentation as the Agents page, with no per-harness submenu:

- **Managed harnesses**: directly visible Harness Manager information and configuration, activation switches and Hermes settings
  shown as soon as Hermes is enabled. Disabling requires confirmation and returns assigned
  agents to the internal harness. Shared Compose settings are collapsed in this tab.
- **External harnesses**: a list of independent services, with creation and editing in a dialog.
- **Advanced settings**: harness reliability and capabilities, available to administrators
  allowed to edit preferences.

### Internal Harness

Code: `internal`.

Under **Preferences → Harnesses → Advanced settings**, the maximum binary file size sent
to the model defaults to 20 MiB (20,971,520 bytes). Changes apply to subsequent files
without restarting; excluded files remain accessible by reference. This setting applies
only to the internal Pydantic AI harness.

- execution by Pydantic AI in the backend;
- no implicit local-storage facade; local files pass exclusively through an
  active Console;
- planner enabled;
- briefing retained but disabled during autonomous goal evaluation;
- standard/high models resolved in the Galaris configuration.

### Hermes Driver

Code: `hermes`.

Hermes remains an autonomous runtime. Galaris sends it a normalized request and supervises
the result, but does not impose either a planner or briefing on it in order to avoid two
competing reasoning systems.

The effort level selects the model, not a second scheduler:

| Effort | Execution |
|---|---|
| `standard` | direct run in the usual Hermes session (`/v1/runs`) |
| `high` | direct `/v1/runs` run with the High model |

Kanban is disabled by an internal constant in the Hermes driver code. This choice is not
configurable in `.env`, the settings, or the administration interface. The Kanban code and routes
remain available only to resume a card created before deactivation and to enable a future
reactivation. Briefing is not currently enabled by any harness.

Configure the manager in **Preferences → Harnesses → Managed harnesses → Configure the Harness Manager**: URL, shared secret
and API URL seen by harnesses. These preferences apply without restarting Galaris. The form also
generates the host manager `.env` for copying or downloading and installing on its host.
Local/remote guides and diagnostics help verify connectivity.

No manager variables are needed in the Galaris `.env`. Legacy values are imported once during
DbAdmin synchronization. Without an API override, `APP_HOST/api` remains the default and must be
reachable from managed containers. Networks belong in the shared Compose configuration.
`make test-harness-management` checks the generic service, not remote runtime or MCP execution.
See the [installation guide](../components/harness-manager.md).

The **OpenAI Codex** provider automatically reuses the **OpenAI — ChatGPT** provider configured
and connected in Galaris, and accepts an optional model (`gpt-5.4` by default). Galaris remains the
owner of the OAuth refresh token: the runtime requests a short-lived access token through an
internal route protected by its system token, then injects it into the Codex App Server without
persisting it in its `.env` or volume. The same broker responds to refresh requests issued during
a long turn. No additional key is therefore requested when adding or updating it. Because the
`chatgptAuthTokens` handoff remains an unstable App Server surface, the SDK and Codex binary are
pinned together and their compatibility is checked at build time.
The container is non-root, resource-limited, connected to the Harness Manager network, and
receives the MCP, skills, and persistent working directory specific to that Agent's runtime. This
directory is not a `file_share` provider and is never announced as file storage.

The **Hermes configuration** section in **Managed harnesses** contains instance defaults.
It appears whenever the harness is enabled, even with no assigned agents. Its settings are
retained when Hermes is disabled. Configure each agent in the **Hermes** tab of its own page;
an information banner in preferences explains this path.

Each Hermes Agent has its own instance, volume, and `<agent.code>-agent` container.
The generic harness manager is only the control plane for these instances and does not execute
any Hermes CLI. The historical Kanban transport is explicitly rejected and is no longer used
for a new `high` Task.

Conversation files retain their provider URI and do not pass through the Hermes file API,
which is limited to 100 MiB. Compatible consumers read them through `file_share`, and technical
materializations remain temporary. Compose overrides remain limited to the Agent's instance, and
its update remains independent. The deployment contract is detailed in
[`docs/en/components/hermes.md`](../components/hermes.md). The generic host
server is documented in
[`docs/en/components/harness-manager.md`](../components/harness-manager.md).

An active **Console** connection in external mode also becomes the target of Hermes's native SSH
terminal when the Agent is synchronized. Galaris projects the private key and `known_hosts`
into the instance-specific volume with `0600` permissions, forces strict host-key verification,
and never places the key in `config.yaml`. Embedded Console mode retains the operator-configured
Hermes terminal. Disabling the external connection removes the projected files and restores this
previous configuration.

Use `make test-hermes-management` to then check the selected Hermes adapter. Hermes
administration screens can call its bridge directly; all business
executions, however, pass through `app.agent`.

Historical Hermes fields in the Agent table are retained during migration.
The driver-specific configuration table is the execution source; backfilling is
idempotent and never logs secrets.

Each Hermes Agent has a **Use a Galaris-provided LLM** setting:

| Mode | Effective configuration | Visibility in Galaris |
|---|---|---|
| enabled, default value | Galaris injects its OpenAI endpoint, the selected model, and a limited token into `config.yaml` and `data/.env` | LLM calls, tools observed by the proxy, costs, and errors are traced |
| disabled | the LLM sections of `config.yaml`, the keys in `data/.env`, and Docker Compose variables remain managed by Hermes | runs remain visible, but not LLM calls or their detailed cost |

In Galaris LLM mode, the run context carries the Task, run, and model identifiers:
calls therefore remain attached to the correct Task even if another execution of the same Agent exists.
When the LLM is configured directly in Hermes, this detailed trace remains unavailable.

When switching to the LLM configured directly in Hermes, synchronization removes only
an old LLM injection that it recognizes as generated by Galaris. The global YAML
and Agent-specific YAML values are then reapplied. Therefore, enter the provider, model, and
secrets in the Hermes configuration before restarting the instance. Galaris MCP tools
remain injected with both LLM configurations.

## 6. Scheduler and Reliability

All Task settings are located under **Preferences → Tasks**. This advanced tab
groups them by intent:

- scheduler, parallelism, leases, and maximum action duration;
- short retries for application errors and a long window for network failures;
- plan depth, number of steps, and number of plan leaves;
- model requests, Tool calls, and cumulative token budgets;
- waiting and number of turns during collaboration between Agents.

Start with few simultaneous Tasks, then increase them while monitoring the connection pool,
LLM quotas, and Tool load. A lease that is too short may make an action
recoverable while it is still working; a lease that is too long delays recovery after
a crash. Changes apply to new actions without restarting the backend.

The Dispatcher processes only Tasks and produces only `EXEC` or `PLAN`. Short exchanges
use the conversational control plane with the effective profile's Conversation model, its aggregation limits,
and an AI→AI response guard based on a fresh request. To diagnose a loop, inspect conversation
rounds rather than Dispatcher results.

Leases and retries are persisted. After a crash, an expired lease can be
recovered, and a plan parent can be reconciled with a completed child step.

The internal and Hermes drivers explicitly announce their cancellation capability. The internal
driver cancels the run, cleans up Console/MCP/Browser sessions, and resumes from persisted
Tool checkpoints; Hermes relays cancellation to the correlated run. **Force finish** remains a
recovery operation when normal cancellation can no longer reach the runtime.

## 7. Messaging, Tools, and Processes

The common settings under **Preferences → Messaging** limit attachments included directly
in model requests to 4 MiB by default. This limit is independent of the maximum download
size. Larger files remain available through tools. Changes apply to subsequent processing
without restarting.

Nextcloud Talk, Matrix, OneBot, Telegram, and WhatsApp can be active simultaneously for the
same Agent. In **Preferences → Messaging**, configure and enable each platform. A response
always uses the exact connection and room from the original conversation. To initiate an
exchange outside a conversation, search for the user, then provide their remote identifier and
the selected channel; an unavailable channel fails without silent fallback.

Create a separate connection per platform under **Tools → Messaging**. The health check aggregates
all active accounts, and each listener is supervised independently. The historical
`MESSENGER_DRIVER` setting is no longer an active-platform selector; it remains only for
compatibility with old generic connections.

User search queries all active connections whose protocol exposes a directory. Results separately
indicate the platform, user identifier, and connection identifier. They are ephemeral: Galaris
does not manage, merge, or persist any contact record. Telegram Bot and WhatsApp Cloud do not
provide an arbitrary directory and therefore cannot complete this search without a future
technical cache.

Common settings are stored in the `params` table; Agent-specific credentials
remain in their encrypted connections.

For Nextcloud Talk, configure at least the base URL and incoming mode (`polling` or
`signaling`). General voice settings are under **Preferences → Voice**.

Built-in Tools are synchronized when the backend starts. Per-Agent activation and disabled
functions are managed in the interface. A driver obtains a native function
only if its capability profile authorizes it; missing capability results in a default
denial. Personal process functions are part of the `galaris` base. The
`process_admin` technical package is reserved for global administration and remains inactive by
default.

The catalog sent to the driver first respects the Agent's permissions and disabled functions.
When the runtime allows it, discovery is deferred: the model receives a bounded index and then
loads only relevant packages. An Tool search never bypasses an
inactive connection or a missing privilege. Use the MCP connection diagnostic in
**Tools** to distinguish a network, authentication, or discovery error.

### Real-Time Conversations and Voice

Galaris has three executor prompt profiles: Task, text conversation, and voice. Their
administrable suffix is configured in **Preferences** with `ai.executor-system-prompt`,
`ai.conversation-executor-system-prompt`, and `ai.voice-executor-system-prompt`; the rest of the
JSON tree is built by the code. Lab datasets reuse the same categories,
copy the current suffix when created, then can customize and freeze it per run.

For each Agent, the voice selector combines two families:

- an active TTS resource enables the STT → Agent → TTS pipeline and requires the
  **Transcription** usage in the Agent's effective profile;
- a native voice from a `realtime_conversation` model enables that provider's speech-to-speech
  session. The initial implementation is provided by the OpenAI bridge.

This selector feeds a single durable value on the Agent: `tts:<id>` or
`realtime:<id>:<encoded-voice-code>`. All other models are resolved from its LLM profile.

Matrix and Nextcloud Talk carry real-time calls. Telegram and WhatsApp carry
their voice notes as incoming media, without thereby becoming call transports. A
speech-to-speech session may produce no user transcription; in that case, supervise the native
audio turn and its function calls rather than waiting for intermediate text.

### Isolated Agent Browser

The integrated **Browser** connection is inactive by default and must be enabled per Agent.
The `browser-executor` sidecar hosts Chromium, but each Agent/Task pair receives a
private, ephemeral `BrowserContext`. Sessions expire automatically and are closed when
the run is canceled.

The `browser-secrets` initializer creates the shared credential once in the Docker
`browser_credentials` volume, without importing a legacy environment token.
The backend and browser mount that volume read-only; only the initializer can write it.
The initializer has no network or access to other backend secrets. Include the volume in
backups. Idle time (120 seconds by default), maximum sessions (32 by default), operation
timeouts, content and HTML limits, screenshots and default dimensions are configured
under **Preferences → Browser**, visible when an agent has an active Browser connection.
Changes apply to subsequent operations without restarting; default dimensions affect new windows.
Lowering capacity preserves existing sessions and limits new admissions. Each session adopts
the current idle timeout on its next action. The
`browser_egress` network and the sidecar's proxy reject private or reserved destinations after
DNS resolution; do not connect the container directly to an administration network.

The normal text result is an accessible paginated snapshot. Visual captures are split
into tiles, written under `console://browser/…` when a Console is active, and
explicitly truncated if they exceed the limits. Without a Console, no implicit local
destination is available. When this Tool is active for Hermes, its native browser is disabled in order to
preserve a single authorization policy.

### Reserve Administration Capabilities for Specialized Agents

Three specialized built-in packages are created for each Agent with an **inactive**
connection:

| Technical code | Label | Functions |
|---|---|---|
| `goal_management` | Goal management | `goal_create`, `goal_list`, `goal_get`, `goal_update`, `goal_pause`, `goal_resume`, `goal_complete`, `goal_run_now`, `goal_delete` |
| `skill_management` | Skill management | `skills_list`, `skill_read` |
| `process_admin` | Process administration | CRUD for definitions and run management for all Agents |

After `make update`:

1. open the DRH Agent's connections;
2. enable **Goal management**, **Skill management**, and, if necessary,
   **Process administration** only for this Agent;
3. leave these connections inactive on the other Agents;
4. optionally disable certain functions at the connection level, for example
   `goal_delete`, if the DRH must supervise without being able to delete.

Activating a connection controls what the model can call. HTTP RBAC controls which
users can modify this configuration in the interface: these are two distinct and cumulative
levels.

`goal_create` explicitly chooses the owning Agent and a different referring Agent. The
modification and cycle commands use `expected_revision`, obtained with `goal_get`, to
prevent concurrent overwrites. `goal_get` also exposes Markdown tracking, the current
Task, verdicts, evidence, errors, costs, and latest cycles. `goal_complete` preserves history and
stops future cycles; `goal_delete` performs a soft deletion and rejects a Goal
that still has an unfinished cycle.

`skills_list` returns by default only skills that are present, valid, and actually authorized
for the requested Agent. Its `include_unavailable` option enables a complete audit of global and
individual states. `skill_read` reads only the `SKILL.md` of a skill indexed in the central
library; it exposes no other file in the package.

### Transcription of Audio and Video Files and YouTube Links

The built-in `audio` Tool exposes the following MCP function:

```text
audio_transcribe(file: str, destination: str = "", language: str = "") -> str
```

`file` accepts a readable canonical URI announced by `file_schemes`, or an HTTPS URL for a YouTube video. There
is no separate YouTube function: this single contract allows Agents to handle an audio
attachment, a video attachment, or a link received in a conversation in the same way.

After the update that introduces the function:

1. `make update` automatically synchronizes the Tool and creates missing connections;
2. activate the integrated **Audio** connection on each Agent authorized to use it;
3. for audio or video files, configure an active provider capable of transcription;
4. add or select a resource with the `transcription` capability;
5. assign it to the **Transcription** usage of the relevant profile.

The Audio connection is created inactive by default, like the other specialized capabilities. If
it is activated without a configured STT model, an audio or video file produces an explicit error
instead of selecting an implicit model. The service supports OpenRouter, ElevenLabs, and
OpenAI-compatible providers according to their configured transcription endpoint. A YouTube URL
with subtitles does not require an STT model, but still requires the **Audio** connection.

An Agent asked to perform a transcription must therefore have its **Audio** connection active. If
the Tool is absent, the executor stops with a configuration error. For a local file, it
also stops if dedicated STT is not configured; it must never attempt a fallback through the
Console or its own chat model.

The source file remains with its provider. The backend temporarily materializes it through
`file_share`, uses PyAV to open the container, select its first audio track, and
ignore video streams. It always produces a
32 kHz mono MP3 at 96 kbit/s before the provider call. Compatible multipart uploads are read
from disk; OpenRouter still requires base64 encoding of the normalized MP3. Temporary files are
deleted after both success and failure.

For a YouTube URL, `bridge.youtube` strictly validates the HTTPS scheme and YouTube hosts,
extracts the video identifier, then uses `youtube-transcript-api` to retrieve a manual or
automatic track. No video or audio file is downloaded and no STT call is
made. The default transcript is `youtube-<identifier>.txt`. Videos longer than ten
minutes follow the same hierarchical reduction and produce
`youtube-<identifier>.summary.md` with a prompt adapted to video content.

This retrieval uses the subtitle interface of the YouTube web client, which is not a
guaranteed public API. YouTube may change its behavior, request proof of origin, or
block a server's IP address, particularly on some cloud hosting providers. Galaris
then returns an explicit error. It uses no YouTube account, cookie, or proxy, and does
not download audio as a fallback. The video must be public and expose accessible
subtitles.

Starting at 10 minutes, the encoder produces several numbered MP3s of approximately 10 minutes.
The room receives a single progress message indicating the duration and estimated number of
segments, without this message replacing the Task's final response. Each partial transcription is
immediately summarized by the Task's executor model; a hierarchical reduction then consolidates
these summaries and writes `<name>.summary.md`. The complete timestamped verbatim remains in
`<name>.txt`, but only the summary file should be reread by the Agent.

The original media is never added as multimodal input to the executor model, even if that
model declares that it accepts audio or video and even if the file is smaller than the
generic upload limit. The prompt receives only the canonical URI of the source; only the normalized
MP3 is sent to the dedicated STT provider. This separation prevents media from being counted
again in the context on every Tool turn and exhausting the Task's cumulative token budget before
transcription.

Provide enough temporary space for the source media and normalized MP3, as well as a provider
timeout compatible with long meetings. Conversion reduces network usage for videos,
PCM sources, and high-bitrate media, but most STT services bill by duration:
it therefore does not guarantee a lower transcription price.

For n8n, open **Preferences → Processes**, enter the URL, API token, and callback URLs
visible from each side, then use the test button. Callback tokens are specific to runs; do not use
a global secret as a public file parameter. Each call also supplies an idempotency key,
the run identifier, and its callback URL in headers. The complete contract and
importable template are described in the [n8n documentation](../n8n/README.md).

## 8. Accounts, Roles, and Privileges

Galaris applies RBAC at three levels:

1. a privilege protects an operation or resource;
2. a role groups privileges;
3. an assignment links a user and a role.

Privileges are generated from the code and then synchronized when the backend starts. After an
update, always verify the administrator role and custom roles. Grant connection-management
privileges carefully: they provide access to modifying secrets, even though the values are not
returned in clear text.

## 9. Backup and Restore

A fully isolated rehearsal is available with `make tests-restore`: PostgreSQL dump and
restore, files, encryption keys and signing keys. See
[security validation](../dev/security-validation.md).

Back up together:

- PostgreSQL;
- `.env` in a secure vault;
- the Docker `browser_credentials` volume, preserving ownership and permissions;
- the `data` volume or directory, especially workspaces, media, and embedded SSH Executor data;
- the Hermes bridge and n8n configuration when they are external.

Example using the provided PostgreSQL service:

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > galaris.dump
```

Restoration is an intrusive operation: stop writes, restore into an empty database of the same
major version, then start the corresponding code version. Its entrypoint
synchronizes the schema and dataset before the API. Regularly test the procedure in a
separate environment.

### Consistency of Internal Messenger Attachments

The `messenger_files` rows contain only metadata. The internal channel's bytes are
in `/data/chat`, and therefore in the `data` volume of
the standard installation. PostgreSQL and this directory constitute a single restoration point.

For a consistent backup, place the installation in a maintenance window with no new uploads,
produce the PostgreSQL dump, then archive the `chat` directory before reopening
writes. Keep the dump, archive, Git version, and date together. During restoration,
restore the database and directory first with their owners and permissions, then launch the
corresponding code version. Next, verify an authorized download and let the
reconciliation job remove only genuinely orphaned blobs.

A PostgreSQL backup without this directory is incomplete and leaves messages whose attachments
cannot be recovered. A copy of the directory without the database is not usable either.
Do not use `make clean` to prepare or test this procedure: this target deletes
volumes.

## 10. Update

```bash
make update
# Or select an exact tag, otherwise a remote branch:
make update VERSION=v1.2.3
```

Without `VERSION`, `make update` builds and deploys existing sources without fetching Git
changes, including local modifications or a detached tag. With `VERSION` and a `.git` entry,
it fetches remote references and gives an exact tag priority over a branch of the same name.
Unknown references, divergent branches and local source changes stop this selection before
any Docker action. Ignored `.env` and override files are preserved. Automatic `start` recovery
also keeps existing sources. The `RELEASE_DIR` path skips Git and cannot be combined with `VERSION`.

To review changes before deployment, fetch them separately and use `make update`.
`make update` completes missing secrets,
prepares SearXNG, pulls images and rebuilds using the Docker cache. After a successful build,
it recreates the backend and frontend, then waits for the backend entrypoint to synchronize
Atlas and reference data and for services to become ready. The frontend and SearXNG have HTTP
healthchecks; PostgreSQL restarts automatically with Docker unless explicitly stopped.
Unchanged infrastructure services remain running, without taking down the whole stack.
The command is idempotent and is the only upgrade path in production.
It does not decide new business options for you; do not replace declarative synchronization with
manual SQL changes.

Unchanged Docker layers are reused, including dependencies and executors. Frontend source changes
trigger recompilation; an unchanged frontend can retain its image and PWA cache. Each frontend
compilation renews every resource in the PWA cache. Visible tabs check for an update
every minute, when returning to the tab and when coming back online, then reload automatically
after installation. Obsolete precached files are deleted; cookies, sessions and user data
are preserved. Save open forms before deployment: the reload replaces the page.
With `RELEASE_DIR`, the previously qualified images are deployed unchanged, without rebuilding.

The harness manager has an independent deployment cycle and may reside on another
machine. `make update` never updates it and does not restart any external host service. Its
update is performed on its own host with the `harness_manager` Makefile, explicitly coordinating
compatibility with the Galaris deployments that consume it.

## 11. Monitoring and Troubleshooting

Non-destructive commands:

```bash
docker compose ps
make logs-back
make logs-front
make logs-search
make typecheck
```

`make typecheck` checks Pyright, TypeScript, and parity of all English and
French frontend keys. `make tests` also checks parity and placeholders in the
backend catalogs against an ephemeral PostgreSQL database.

Quick diagnosis:

| Symptom | Checks |
|---|---|
| no Task starts | available driver, configured executor, active scheduler, non-saturated DB pool |
| a Task remains running | lease, action timeout, LLM/MCP calls, provider connectivity |
| Hermes unavailable | Agent instance status, `<code>-agent` container, harness manager URL and authentication, MCP URL as seen from Hermes |
| pgvector error | selected embedding model and Memory semantic-index status |
| browser unavailable | sidecar health, shared token, session limits, public destination, and egress proxy |
| action claimed but not performed | Tool trace and “response without action” guard |
| conversation without a response | room and round status, pending messages, effective profile's Conversation usage, delivery through the original connection |
| loops between Agents | conversational control-plane response guard, request freshness, and message origin |
| voice call without transcript | check whether the selected voice uses a native speech-to-speech session; this mode may normally have no user text |
| permission denied | current role, synchronized privileges, active assignment |
| PWA not offered for installation | HTTPS, accessible manifest and service worker, browser not in private browsing |
| login requested at every launch | cookie allowed, `APP_HOST` over HTTPS, stable hostname, `/api/auth/refresh` route without a 401/403 error |

To report an incident, provide the Git version, Task identifier, time with
time zone, and redacted logs. Never provide `.env`, an authorization header, or
a Hermes configuration containing a key.

## 12. Risky Commands

- `make clean` deletes Docker volumes and therefore potentially PostgreSQL.
- a restore overwrites data; validate the target and backup.
- manually reducing a schema bypasses Atlas and may make the models incompatible.
- running pytest directly in the development container is rejected: use
  `make tests`, which creates an isolated ephemeral database.

The host procedure, security model, and systemd service for the harness manager are detailed
in [`docs/en/components/harness-manager.md`](../components/harness-manager.md). Hermes-specific
details remain in
[`docs/en/components/hermes.md`](../components/hermes.md).
