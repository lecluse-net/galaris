<p align="right">
  <strong>English</strong> · <a href="README-fr.md">Français</a>
</p>

<p align="center">
  <img src="resources/galaris.svg" width="170" alt="Galaris logo">
</p>

<h1 align="center">Galaris</h1>

<p align="center"><strong>Stop chatting with AI. Put it to work.</strong></p>

<p align="center">
  The self-hosted control plane for agents that act, collaborate, remember and improve.<br>
  Your models, your tools, your data, your rules.
</p>

<p align="center">
  <a href="#quick-start"><strong>Launch Galaris</strong></a> ·
  <a href="#what-galaris-delivers">Explore the platform</a> ·
  <a href="docs/en/features.md">Full feature tour</a> ·
  <a href="docs/en/README.md">Documentation</a>
</p>

<p align="center">
  <img alt="Self-hosted" src="https://img.shields.io/badge/deployment-self--hosted-0f766e">
  <img alt="Docker ready" src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white">
  <img alt="PWA for Android and iOS" src="https://img.shields.io/badge/PWA-Android%20%26%20iOS-5A0FC8?logo=pwa&logoColor=white">
  <img alt="CeCILL license" src="https://img.shields.io/badge/license-CeCILL-2563eb">
</p>

A model can reason. A production AI workforce also needs identity, permissions, tools, memory,
coordination, durable execution and a way to prove what actually happened.

**Galaris is that operating layer.** Give named agents a role, a model, skills, tools and long-term
goals. Let them answer in your team’s channels, delegate bounded work, use browsers and business
systems, recover from failures, and build governed knowledge from completed work.

> **Models answer. Galaris delivers — and keeps the evidence.**

<a id="what-galaris-delivers"></a>

## What Galaris delivers

| From | To |
|---|---|
| Isolated prompts | Named agents with stable identity, instructions, skills, tools and private workspaces |
| Ephemeral chat | Text and voice conversations with durable history, live supervision and background-task handoff |
| One-shot answers | Persisted tasks, multi-step plans, delegation, retries, cancellation, safe checkpoints and recovery |
| Rebuilt context | Shared session context plus governed long-term memory, revisions, provenance, ACLs and hybrid recall |
| Scattered notes | Collaborative working documents and global thematic dossiers that connect knowledge across channels |
| Static agents | Optional Dream maintenance that consolidates memories and learns evidence-backed experience from outcomes |
| Opaque automation | Inspectable LLM/tool traces, process runs, costs, failures and reproducible AI Lab benchmarks |
| One provider’s ecosystem | Internal Pydantic AI or Hermès runtimes, provider bridges, MCP tools and n8n behind one control plane |

### Turn complex work into a durable operation

Ask Galaris to compare proposals, research risks, verify totals, build a decision matrix and send
the recommendation for approval. It can route the request to direct execution or a durable plan,
delegate specialist steps, pause for missing information and resume after a restart. Tasks,
attempts, process runs and deliverables remain linked and inspectable.

### Make every conversation actionable

Agents can respond through the web app, the Android/iOS PWA, Matrix, Nextcloud Talk, OneBot,
Telegram and WhatsApp Business. Short exchanges use a dedicated conversation control plane that
aggregates bursts and prevents reply loops; real work becomes a durable Task or Process without
blocking the conversation. Live voice supports both a composable STT → agent → TTS pipeline and
native speech-to-speech providers where configured.

### Build knowledge instead of losing context

Galaris combines recent conversation context with private, governed memory. Agents can search
lexically or semantically, maintain collaborative Markdown documents, preserve provenance and
organize knowledge into thematic dossiers independent of a single room. Dream can use idle time to
deduplicate and consolidate memories, then retain lessons only when task evidence supports them.

### Measure AI behavior before trusting it

The AI Lab turns real Tasks, text rounds and voice turns into versioned datasets. Benchmark the
Dispatcher, Briefing, Planner, Task/Conversation/Voice executors and Dream/Goal mechanisms with
semantic rubrics, frozen cases, resumable runs and explicit judge diagnostics.

## Built-in action surface

- MCP tool catalog with per-agent connections, per-function restrictions and rights-aware deferred
  discovery;
- local web search plus an isolated Chromium browser with private sessions, accessible snapshots
  and bounded full-page captures;
- shared and private files, image generation/editing/analysis, and controlled SSH execution;
- audio/video transcription, long-recording segmentation and hierarchical summaries; public
  YouTube captions use the same workflow without downloading the video;
- durable personal and administrative processes, including idempotent n8n runs, callbacks,
  cancellation and linked Task tracking;
- long-running Goals with owners, referrers, schedules, cycles, evidence and manual controls.

Capabilities are governed per agent, and specialized ones remain inactive by default. The runtime
sees only the tools and functions permitted by its active connections and the current user’s
rights.

<a id="quick-start"></a>

## Quick start

Prerequisites: Docker with Compose, GNU Make, Git and OpenSSL.

Replace `<repository-url>` with the repository URL.

```bash
git clone '<repository-url>' galaris
cd galaris
make install
```

Open `.env` in your editor: check `APP_HOST` (the Galaris address) and `TZ` (your time zone).
Keep the other defaults and generated secrets.

```bash
make update
```

Open the address set in `APP_HOST` (<http://localhost:8484> by default).
The first account becomes the administrator. The onboarding journey
then guides you through connecting a model, creating an agent, granting tools and adding a
messaging channel.

`make update` builds images, starts services, synchronizes the database and waits for readiness.
Reuse it after editing `.env` or fetching a new repository version.

No host-level Python, Node.js or PostgreSQL installation is required. For a production deployment,
read the [installation and operations guide](docs/en/admin/installation.md) before exposing the instance.

## One control plane, the whole AI stack

```text
Web · PWA · API · Matrix · Nextcloud · OneBot · Telegram · WhatsApp
                              │
                              ▼
                    GALARIS CONTROL PLANE
       identity · RBAC · conversations · tasks · goals · processes
          planning · delegation · recovery · approvals · traces
                 memory · topics · Dream · evaluation
                              │
             ┌────────────────┼─────────────────┐
             ▼                ▼                 ▼
       Pydantic AI         Hermès          MCP · n8n · files
      internal agents   external runtime   browser · media · SSH
             └────────────────┴─────────────────┘
                              │
                              ▼
              cloud or local models · your infrastructure
```

Galaris provides native bridges for major model ecosystems—including OpenAI, Anthropic, Google,
Mistral, OpenRouter, Ollama and other compatible providers—without making provider choice the
architecture of your agents.

## Documentation

- [Complete feature tour](docs/en/features.md)
- [French product overview](README-fr.md)
- [Installation and operations](docs/en/admin/installation.md)
- [Documentation portal](docs/en/README.md)
- [User guide](docs/en/user/README.md)
- [Administrator guide](docs/en/admin/README.md)
- [Developer and architecture guide](docs/en/dev/README.md)
- [Architecture maps and flows](docs/en/architecture/README.md)
- [Project decisions](project/decisions/README.md)

The complete documentation is available in both [English](docs/en/README.md) and
[French](docs/fr/README.md), with matching paths and a language switch on every page.

## Your models are capable. Make them operational.

Build agents that can act, converse, recover, remember and improve while you keep control of the
infrastructure, permissions and evidence.

**Clone Galaris. Connect a model. Give it a mission.**

Galaris is distributed under the CeCILL free-software license. See [LICENSE.md](LICENSE.md) and
[LICENSE-FR.md](LICENSE-FR.md).
