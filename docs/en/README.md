<p align="right"><a href="../fr/README.md">Français</a> · <strong>English</strong></p>

# Galaris Documentation

The documentation is organized according to the responsibility of the person reading it. It is
not necessary to understand the architecture to use Galaris, nor to know the code to administer it.

## Discover the Platform

[Discover Galaris in use](features.md)

This tour shows how capabilities combine in everyday work. The guides below explain the actions
to perform and remain the home of their respective procedures.

The [exhaustive functional catalogue](reference/functional-catalogue.md) remains a separate reference,
particularly for preparing the product website: detailed capabilities, conditions, limits and inventories.

## 1. User and Beginner

[Read the user guide](user/README.md)

[Find a screen, menu or tab](user/navigation.md)

This path explains, with examples:

- what an Agent is and what Galaris actually orchestrates;
- how to [install Galaris as an application](user/pwa.md) on Android or iPhone and keep
  your session;
- how to chat, request an action, and start background work;
- how to separately track text conversations, voice calls, Tasks, and background processes;
- how to have a meeting or YouTube video summarized from a file or URL;
- how to use memory, Working Set documents, and thematic folders;
- the difference between the `standard` and `high` levels;
- how to interpret a task, step, question, or failure;
- how to obtain a reliable result without learning technical vocabulary;
- how to use the [AI Lab](user/lab-ai.md) to analyze a task, build a dataset, and
  interpret a benchmark.

## 2. Administrator

[Read the administrator guide](admin/README.md)

[Install and operate Galaris](admin/installation.md)

[Give any agent knowledge of Galaris](admin/product-knowledge.md)

This path covers installation and operations:

- Docker, `.env`, secrets, the PostgreSQL database, and Atlas updates;
- LLM providers and the models used by each function;
- execution harness selection and configuration;
- messaging, Tools, durable Goals, Skills, multimedia and YouTube transcription, n8n, voice,
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

1. contracts and tests present in the repository;
2. `.env.example` and configuration templates;
3. this documentation;
4. the generated map, as a static index of the code;
5. plans, old tickets, screenshots, or discussions.

A page that mentions LangGraph, Alembic, an `employee` module, or a direct call to
`app.harness` from a business feature is obsolete: the
current architecture does not use any of these paths.
