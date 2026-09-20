<p align="right"><a href="../../fr/architecture/README.md">Français</a> · <strong>English</strong></p>

# Galaris Architecture

This directory complements the [developer guide](../dev/README.md) with two forms of
knowledge: invariants explained by humans and a map automatically reconstructed from the code.

## Recommended Path

| Need | Document |
|---|---|
| Understand non-negotiable rules | [Invariants](invariants.md) |
| Follow a task and its driver | [Agentic Execution](flows/agent-execution.md) |
| Follow a message and its bridge | [Messaging](flows/messaging.md) |
| Audit the internal Messenger | [Architecture and Data Validation](chat-validation.md) |
| Understand session, recall, and consolidation | [Memory](flows/memory.md) |
| Understand opportunistic background maintenance | [Dream](flows/dream.md) |
| Follow a tool or a long-running execution | [Processes](flows/process.md) |
| Understand calendars and their triggers | [Calendars](flows/calendar.md) |
| Understand browser sessions and outputs | [Browser](flows/browser.md) |
| Understand files, media, and resources | [Media and Resources](flows/media-resources.md) |
| Understand the scores, rubrics, and biases of the AI Lab | [AI Lab Evaluation](ai-lab-evaluation.md) |
| Verify durable states | [State Machines](state-machines.md) |
| Find modules, routes, tables, and tools | [Generated Map](generated/project-map.md) |
| Understand why a boundary exists | [Decisions](../../../project/decisions/) |
| Evaluate a proposal not yet delivered | [Plans Index](../../../project/plans/README.md) |

## What Is Authoritative

The generated map is a static index, not a business specification. The order of
confidence remains: contracts and tests, configuration, developer guide and accepted decisions,
generated map, then plans.

Files in `generated/` are never edited by hand:

```bash
make project-context
make project-context-check
make architecture-check
```

The first rebuilds the JSON and Markdown outputs. The second detects drift. The
third also verifies dependency boundaries, skills, required documents, and the plans index.

Module capabilities are derived from source files. Empty directories and local caches do not
change the map: a Git snapshot must produce the same results.

The coupling sections of the map expose fan-in, fan-out, direct cycles, and strongly connected
components for Python and TypeScript/Vue. Human-reviewed backend ceilings live
in `back/architecture.toml`; current mechanical debt lives in the separate baselines
`back/architecture-baseline.json` and `front/architecture-baseline.json`. After removing a
private import, a frontend dependency, or splitting a cycle, `make architecture-baseline` reduces these
baselines.
An increase should be accepted only with an explicit architecture justification in
the review and, if the durable boundary changes, a decision.

## Maintaining This Knowledge

- Modify a state or transition: update `state-machines.md` and its matrix test.
- Modify a cross-domain flow: update the corresponding file in `flows/`.
- Change a durable boundary: add or amend a decision in `project/decisions/`.
- Add a module, route, model, MCP tool, setting, or page: regenerate the
  map.
- Remove a dependency or private import: reduce the manifest and baseline without restoring
  their former ceiling.
- Evolve an intention: update the status and note in `project/plans/README.md`.
