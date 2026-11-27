<p align="right"><a href="../fr/README.md">Français</a> · <strong>English</strong></p>

# Galaris Documentation

## Where should I start?

| Your situation | Start here |
|---|---|
| I received an invitation | [Activate my account and find my team’s agents](user/README.md#first-login) |
| I have access to an agent and want to try it | [Turn notes into a document with the guided first mission](user/README.md#first-mission) |
| I need help using a Galaris screen | [Ask an agent about the installed documentation](user/README.md#ask-about-galaris) |
| I’m setting up Galaris for my team | [Install the platform and configure the first provider](admin/installation.md) |
| I’m exploring possibilities or looking for a specific feature | [Explore everyday uses](features.md) · [Browse the functional catalogue](reference/functional-catalogue.md) |

## 1. User and Beginner

[Read the user guide](user/README.md)

[Find a screen, menu or tab](user/navigation.md)

[Assigning and following a Task](user/tasks.md)

| Workflow | Guide |
|---|---|
| Accept an invitation, find your team and open an agent profile | [Home and accounts](user/navigation.md), [teams](user/teams.md) |
| Understand an inference limit and request credit | [Usage and renewals](user/usage.md#request-credit) |
| Choose the harness for Chat and Tasks | [Embedded Claude Agent](components/claude-agent.md) |
| Share a local MCP or a screenshot from your computer | [Windows/Linux client](user/desktop.md) |
| Find a document mentioned in Chat and get access | [Document results](user/documents.md#find-deliverable) |
| Answer an agent or understand a waiting Task | [Questions and resumption](user/tasks.md#reply-to-task) |
| Find a file or retrieve an email attachment | [Agent files](user/files.md#browse-files), [mailboxes](user/files.md#browse-mail) |
| Connect an API or find out why a tool is missing | [Connect the Service](user/services.md#connect-service), [check access](user/services.md#service-access) |
| Write, cite an object, share or export | [Rich content](user/rich-content.md) |
| Create and reuse JSON | [Data documents](user/datasets.md) |
| Manage generic and personal agent methods | [Skills](user/skills.md) |
| Work on a Git checkout with an agent | [Code editor](user/code-editor.md) |
| Design and monitor a BPMN workflow | [Internal Processes](user/internal-processes.md) |

This path explains, with examples:

- what an Agent is and what Galaris actually orchestrates;
- how to [install Galaris as an application](user/pwa.md) on Android or iPhone and keep
  your session;
- how to chat, request an action, and start background work;
- how to separately track text conversations, voice calls, Tasks, and background processes;
- how to have a meeting or YouTube video summarized from a file or URL;
- how to use memory, Working Set documents, and thematic folders;
- the difference between `standard`/`high` effort, milestone tracking and Task plans;
- how to interpret a task, step, question, or failure;
- how to obtain a reliable result without learning technical vocabulary;
- how to use the [AI Lab](user/lab-ai.md) to analyze a task, build a dataset, and
  interpret a benchmark.

## 2. Administrator

[Read the administrator guide](admin/README.md)

[Install and operate Galaris](admin/installation.md)

[Give any agent knowledge of Galaris](admin/product-knowledge.md)

[Configure AI provider admission and concurrency](admin/provider-admission.md)

[Delegate privileges and settings by function](admin/privileges.md)

This path covers installation and operations:

- Docker, `.env`, secrets, the PostgreSQL database, and Atlas updates;
- LLM providers and the models used by each function;
- execution harness selection and configuration;
- messaging, Services, durable Goals, Skills, multimedia and YouTube transcription, n8n, voice,
  permissions, and accounts;
- hybrid memory, Dream, learning, isolated browser, and real-time supervision;
- scheduler tuning, backups, logs, and troubleshooting.

## 3. Developer

[Read the developer guide](dev/README.md)

This path describes the code contract:

- `core`, `app`, and `bridge` modularity;
- separation of `app.agent`, `app.harness`, `bridge.hermes`, and `app.task`;
- control planes for text and voice conversations, governed memory, Dream, and AI Lab;
- creation of a module and a future `AgentDriver`;
- SQLAlchemy, Atlas, RBAC, API, MCP toolsets, Vue, Pinia, and i18n;
- isolated tests, strict typing, and contribution rules.

Before publishing the tag, run `make release-check RELEASE_REF=<commit>`. This requires a successful Security workflow for that exact commit and a fresh source scan. Quality results are reported separately. [Pre-publication checks](dev/security-validation.md)

For maintenance-oriented navigation, also consult
[`docs/en/architecture`](architecture/README.md): invariants, flows, state machines, and the
[generated map](architecture/generated/project-map.md) of modules, routes, tables,
dependencies, and MCP tools. Structural choices and their rationale are maintained separately
in the [project decisions](../../project/decisions/README.md).

## Component Technical Documentation

- [Hermes bridge](components/hermes.md)
- [Claude Agent Harness](components/claude-agent.md)
- [DeepSeek Harness](components/deepseek-harness.md)
- [Containerized Harness Manager](components/harness-manager.md)
- [Embedded SSH Executor](components/ssh-executor.md)

## What Takes Precedence

In case of discrepancies, the order of trust is as follows:

1. contracts, models, implementation and tests present in the repository;
2. `.env.example`, `back/core/settings.py` and module declarations;
3. this documentation and accepted decisions;
4. the generated map, as a static index of the code;
5. plans, old tickets, screenshots, or discussions.

A page that recommends LangGraph, Alembic, an `employee` module, or a direct call to
`app.harness` from a business feature is obsolete: the
current architecture does not use any of these paths.
