<p align="right"><a href="../../fr/admin/installation.md">Français</a> · <strong>English</strong></p>

# Install Galaris

**Clone the repository → `make install` → deploy a qualified bundle → enter your OpenRouter token
in Providers → chat with Galaris.**

On a fresh installation, the models and default profile are preconfigured, and the
**Galaris** agent is created with the first administrator account.

## Prerequisites

A Linux host with Docker running, the Docker Compose plugin, Git, GNU Make, OpenSSL
with `flock` (`util-linux`) for maintenance locks and `ss` (`iproute2`) to check ports.
Python, Node.js and PostgreSQL are provided in containers.

Get the sources from the official repository:

```bash
git clone https://github.com/lecluse-net/galaris.git galaris
cd galaris
```

## 1. Prepare the installation

```bash
make install
```

On a fresh installation, the command asks:

1. Include PostgreSQL? **Yes by default** (`embedded`).
2. Which host port? **8484 by default**. If the TCP port is already used on the host
   or published by Docker, it explains the conflict and asks for another port.

It creates `.env` with `APP_HOST=http://localhost:<port>`, writes `<port>:8484` to
`compose.override.yaml`, prepares configuration and generates secrets. Accepting defaults
prepares a local installation with embedded PostgreSQL at <http://localhost:8484>,
provided that port is available.

Existing files are preserved on reinstallation. If an override exists without `.env`, its
ports are preserved and the script asks you to check that `APP_HOST` matches them.
Images will be built and services started in step 3.
For unattended installation: `make install POSTGRES_MODE=embedded INSTALL_PORT=8484`.
`POSTGRES_MODE=external` selects an external database. An explicit busy or invalid port,
or end of input without a usable port, fails before creating configuration.

## 2. Customize configuration if needed

The generated configuration is ready for a local installation; this step is optional.
Edit `.env` only if needed. Example local configuration:

```dotenv
APP_HOST=http://localhost:8484
APP_ENV=prod
TZ=Europe/Paris
```

- **`APP_HOST`**: the address used to open Galaris. On a server, enter your public URL,
  such as `https://galaris.example.org`, and configure your HTTPS proxy to forward to
  port 8484. This variable does not create a domain or certificate.
- **`TZ`**: your time zone.
- Keep other defaults, including `POSTGRES_MODE=embedded`, and the generated secrets.

By default, `compose.postgres.yaml` provides the database. With `POSTGRES_MODE=external`,
this file is not loaded: configure `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD` for your PostgreSQL database with pgvector.
If needed, customize Docker **ports, volumes and networks** in `compose.override.yaml`.
To change the exposed port later, edit this file before starting
(for example `8585:8484`) and set the corresponding address in `APP_HOST`.
AI providers and their keys are configured later in the interface.

## 3. Start Galaris

```bash
make update RELEASE_DIR=/path/to/qualified-release
```

Production requires qualified immutable images and never rebuilds them during deployment.
Follow the [image qualification workflow](../dev/reliability-operations.md)
to prepare the bundle. Startup prepares the data volume, initializes the database and waits
for complete schema convergence and readiness. Local configuration is preserved.
In development only, `APP_ENV=dev make start` builds sources.

Afterwards, `make start` starts existing containers without building. If a service is missing,
has failed or does not become ready, it attempts one full update. Docker access errors or
configuration inspection errors stop the command.
Production recovery requiring deployment also requires `RELEASE_DIR`; `start` never rebuilds
sources or changes the Git version.

## 4. Enter the OpenRouter token and start chatting

1. Open the address set in `APP_HOST` — <http://localhost:8484> with the values above.
2. Click **Log in** to create the first administrator account. While no user exists,
   this button opens registration; afterwards it opens the usual login form.
   The **Galaris** agent is created automatically for this first administrator.
3. Open **Providers** (`/llm?tab=providers`) and select **OpenRouter**.
4. Enter your **OpenRouter token / API key**, then save.
5. Open **Chat** (`/chat`), choose **Galaris** and send your first message.

**Galaris is ready to chat: your OpenRouter token is the final setting needed.**
On a fresh database, the **OpenRouter** provider, nine models and the **Défaut** profile
are already configured; the Galaris agent uses that profile. You can customize this
configuration later. Use the token from your own OpenRouter account; Galaris ships
no OpenRouter key or account.

Only internal Chat is enabled on installation. To use Nextcloud Talk, Matrix, OneBot,
Telegram or WhatsApp, enable and configure the channel in **Preferences → Messaging**.
Updates preserve previously saved channel choices.

### Bundled configuration

All four text tiers use DeepSeek V4.1 Flash with reasoning efforts `none`, `low`,
`medium` and `high`. The profile also proposes GPT 5.4 Nano for documents, Nemotron 3
Nano Omni for audio and video, Nano Banana Pro for images, Whisper for transcription,
Qwen3 Embedding 4B for embeddings, Jev 1.13 for decisions, Lyria 3 Clip Preview for music
and Hailuo 3 Max for video generation. Sound generation remains unconfigured.
Pricing can be refreshed from the provider.

These defaults can be edited or deleted. Before deleting the profile, create another
one, which may be empty: Galaris always retains at least one profile. Updates do not
restore deleted items or overwrite your settings. Existing installations do not receive
this configuration retroactively.

## Afterwards

`make stop` stops containers without removing them; `make start` starts them again.
`make build` builds images only, without changing containers.
`make uninstall` removes the project's containers and networks and offers three separate
confirmations, all **defaulting to no**:

- delete Compose-managed volumes: `yes` or `oui` permanently erases their data, including
  embedded PostgreSQL and stored files;
- delete local images generated by Compose for the project (`--rmi local`): these must
  be rebuilt on the next start;
- delete orphan containers belonging to the same project but absent from its current configuration.

Enter, refusal or no input preserves each optional resource. Images with explicit tags,
including PostgreSQL and search, and shared build cache are preserved. No global `prune`
is run. Configuration, host-mounted directories and external databases or volumes are
preserved. If volumes are retained, a later `make start` reuses their data.

`make uninstall FORCE` automatically answers **yes to all three confirmations**, without
reading user input. This permanently deletes volumes and their data, along with the
project's local Compose images and orphan containers.

`make clean` also removes volumes: this command is destructive.

In production, deploy qualified images:

```bash
make update RELEASE_DIR=/path/to/qualified-release
```

In development only, fetch and deploy a tag or branch:

```bash
APP_ENV=dev make update VERSION=0.3.1
```

To list available targets before choosing one:

```bash
make update VERSIONS
```

This queries the configured Git remote and lists all tags (highest versions first), then
all branches alphabetically. It does not modify local sources or start a deployment, and
works before `make install` or with local changes. A Git checkout and remote access are required.

In development, `make update` pulls infrastructure images, including SearXNG, before build and restart.
SearXNG follows the version pinned in `compose.yaml`, preserving
existing configuration. A pull failure stops the update while keeping running services.

Each attempt writes a private `artifacts/updates/update-*.log` file and prints its path.
It retains stages, exit codes, startup command output and all backend logs since the
attempt began, without a tail limit. Fatal and nonfatal DbAdmin errors remain available
in that file even when the backend cannot start or the next attempt recreates its
container. Recognized secrets are redacted before writing; the latest 100 journals
are retained. Send this file when reporting a failure; no SQL query is needed to read
these errors. Incomplete collection is reported and fails an otherwise successful
update, while preserving any original failure. At the next startup, DbAdmin also
prints the recorded causes of unfinished actions before retrying them, allowing
an earlier failure to appear in the new journal after the old container was replaced.
Older journals containing only stage
metadata cannot reconstruct output they did not record.

In development without `VERSION`, no Git fetching or selection takes place: existing sources are used,
including local changes, detached tags or branches without an upstream.
With `VERSION`, `.git` must exist in the installation (directory or worktree file).
An exact tag takes priority over a branch
with the same name; an unknown reference fails before any container changes.

Local source modifications block Git synchronization; ignored `.env` and override files
are preserved. Redeploy the qualified bundle to apply production configuration changes.
Without `.git`, development continues building existing sources and rejects `VERSION`.

If an update separating Memory from Documents stopped on a `memory_items.share_id` or
`share_kind` constraint while creating contacts, fetch the fix and run `make update` again.
DbAdmin automatically resumes the transfer and prepares the retained columns; existing
archives and permissions remain preserved.
Distribution through an image registry is not yet supported by this path.

## Backup and restore

```bash
make save
make save FILE=/backups/galaris.tar.gz
make restore /backups/galaris.tar.gz
# Equivalent, including paths with spaces:
make restore FILE=/backups/galaris.tar.gz
```

Without `FILE`, the archive is stored under `artifacts/backups/`. It includes a complete
PostgreSQL dump (all schemas, including migration archives), `/data` except **`/data/files`**,
configuration, recovery keys, a manifest and SHA-256 checksums. Symlinks are preserved without
following their targets. Sockets are transient and are not archived. Archives contain secrets,
use mode `0600`, are not encrypted and must remain in protected storage.

The command uses the installed backend image without running DbAdmin. It temporarily stops
running application services to quiesce their writers; PostgreSQL remains available. Save
resumes those services even if copying fails. A shared lock prevents concurrent backup,
restore and deployment commands.

To capture `/data/files` at the same logical point, run `make save KEEP_STOPPED=1`.
Application services remain stopped after the archive; perform the separate rsync, then
run `make start`. PostgreSQL stays active. This option also retains the stopped state on
backup failure so recovery remains an explicit operator decision.

Restore verifies integrity, archive paths, the PostgreSQL major version and encryption key
before downtime. If the key differs, recover `ENCRYPTION_MASTER_KEY` from the archive's
`secrets.json` member and configure it in `.env` before retrying. A `before-restore-*.tar.gz`
archive retains the current state. The dump is restored into a temporary database before
database/data replacement. Handled failures attempt to restore the previous state and retain
diagnostics. The database role must be able to create and rename databases; PostgreSQL roles
referenced by dump ACLs must already exist. Privileges are never automatically elevated.

Services remain stopped after restoration. `/data/files` is neither saved nor modified:
coordinate its **separate rsync** snapshot and select a compatible application binary before
starting. A recovery archive on the same disk does not protect against losing that disk;
keep an off-host copy. `make tests-backup` exercises the public commands on a fully synthetic
Docker installation.

If startup fails, check `make logs-back` or `make logs`.

[Advanced configuration and operations](README.md) ·
[User guide](../user/README.md) · [All Make commands](../dev/make-commands.md)
