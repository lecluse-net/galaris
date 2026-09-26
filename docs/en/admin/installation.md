<p align="right"><a href="../../fr/admin/installation.md">Français</a> · <strong>English</strong></p>

# Install Galaris

**Clone the repository → `make install` → `make start` → enter your OpenRouter token
in Providers → chat with Galaris.**

On a fresh installation, the models and default profile are preconfigured, and the
**Galaris** agent is created with the first administrator account.

## Prerequisites

A Linux host with Docker running, the Docker Compose plugin, Git, GNU Make, OpenSSL
and `ss` (the `iproute2` package) to check ports.
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
make start
```

On first start, the command builds images from existing sources, prepares permissions
on the shared application volume, creates containers, initializes the database and waits
for readiness. Settings in `.env` and `compose.override.yaml` are
preserved. The first run may take several minutes.

Afterwards, `make start` starts existing containers without building. If a service is missing,
has failed or does not become ready, it attempts one full update. Docker access errors or
configuration inspection errors stop the command.
Recovery uses the sources already present: `start` never changes the Git version.

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

To update the current branch, fetch the sources and deploy them:

```bash
git pull --ff-only
make update
```

Or fetch and deploy a specific tag or branch in one command (replace `v1.2.3` with the desired reference):

```bash
make update VERSION=v1.2.3
```

To list available targets before choosing one:

```bash
make update VERSIONS
```

This queries the configured Git remote and lists all tags (highest versions first), then
all branches alphabetically. It does not modify local sources or start a deployment, and
works before `make install` or with local changes. A Git checkout and remote access are required.

Without `VERSION`, no Git fetching or selection takes place: existing sources are used,
including local changes, detached tags or branches without an upstream.
With `VERSION`, `.git` must exist in the installation (directory or worktree file).
An exact tag takes priority over a branch
with the same name; an unknown reference fails before any container changes.

Local source modifications block Git synchronization; ignored `.env` and override files
are preserved. Use `make update` to apply configuration changes only.
Without `.git`, `update` continues building existing sources and rejects `VERSION`.
Distribution through an image registry is not yet supported by this path.

If startup fails, check `make logs-back` or `make logs`.

[Advanced configuration and operations](README.md) ·
[User guide](../user/README.md) · [All Make commands](../dev/make-commands.md)
