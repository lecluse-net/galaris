# Galaris — development agent guide

Galaris is a self-hosted platform that orchestrates autonomous AI agents, their tasks,
tools, goals, workspaces, and messaging channels. This file is the lasting entry point
for any agent modifying the repository.

## Start with the right sources

When sources disagree, use this order of authority:

1. Contracts, models, implementation, and tests in the repository.
2. `.env.example`, `back/core/settings.py`, and module declarations.
3. `docs/fr/dev/README.md` and accepted decisions in `project/decisions/`.
4. `docs/fr/architecture/generated/project-map.md`, regenerated from the code.
5. Files in `project/plans/`, which describe intent and whose status is indexed in
   `project/plans/README.md`.

Before any work:

- Read `git status --short` and preserve unrelated changes.
- Never create a commit without an explicit user request in the current message;
  earlier authorization does not cover subsequent changes.
- Write all new commit messages exclusively in English, including both subject and body,
  to make international contributions easier.
- Consult the generated project map, then the contracts and tests for the relevant domain.
- Use `rg` or `rg --files` to locate the actual implementation surfaces.
- Verify assumptions against the code: a plan or historical example is not authoritative.

## Environment and commands

NEVER edit files directly on the production server, even for an urgent fix, diagnosis,
or recovery. Prepare all changes in the development repository. Any production
intervention requires an explicit user request; a request to fix an issue or documentation
of production commands does not grant that permission. A deployment request does not
authorize direct file edits on the server.

`APP_ENV` is a free-form label that defaults to `prod`. The only derived application mode
is `is_dev = (APP_ENV == "dev")`: only the exact value `dev` enables development mode.
Any other value (`prod`, `pp`, `test`, `demo`, unknown, or empty) applies production behavior
and protections. Preserve the `APP_ENV` label for future environment-specific branding.
Automated test adaptations belong in their isolated infrastructure; `APP_ENV=test` does
not disable any application protection.

Development is fully containerized. Do not look for or run Python, Node, npm, uv, Atlas,
or PostgreSQL on the host.

```bash
APP_ENV=dev make start
make logs-back
make tests
make tests ARGS='app/agent/tests/test_registry.py'
make typecheck
make architecture-check
make project-context        # Regenerate the deterministic project map
make project-context-check  # Check that it still matches the code
make docs-prepare           # Regenerate maps and check the FR/EN documentation corpus
make docs-update            # Dev: preparation + active corpus check + text index
make architecture-baseline  # Reduce/update coupling debt after reviewing the diff
make sync-db                # Dev only: DbAdmin schema/datasets, without restarting
make update                 # Dev/prod: images + restart + DB sync + readiness check
```

- Use `make` targets whenever they exist.
- The backend and frontend support hot reload: do not restart after a simple edit.
- Backend tests use an ephemeral PostgreSQL database. Never run `pytest` in the development
  container.
- The `public` schema is declarative and derived from SQLAlchemy models by `core.dbadmin`,
  which wraps Atlas. There is no Alembic, handwritten migration, or `make migration` target.
  In development, `make sync-db` applies changes without restarting the stack; in production,
  `make update` applies them when the backend restarts and waits until it is healthy.
- `make clean` deletes volumes and is never a routine diagnostic step.

Reference stack: Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 17 and
pgvector; Vue 3, Quasar 2, Pinia 3, Vue Router 5, vue-i18n 11 and TypeScript; Pydantic AI,
MCP/FastMCP and Docker Compose.

## Repository architecture

The two activation lists are authoritative: `back/modules.py` and `front/modules.ts`.

| Layer | Responsibility | Dependency rule |
|---|---|---|
| `back/core` | Reusable infrastructure: DB, API, auth, RBAC, i18n, websocket | Never depends on `app` or `bridge` |
| `back/app` | Galaris business domains | Consumes other domains' public interfaces |
| `back/bridge` | External system adapters | Translates external protocols into Galaris contracts |
| `front/core` | Shell, API, auth, navigation, i18n | Contains no application business logic |
| `front/app` | Domain pages and state | Declared modules and file-based routes |
| `front/bridge` | External system configuration and guides | Contributes to generic screens without duplicating business domains |

A stable cross-module interface is exposed through the root package or a public module named
`contracts.py`, `facade.py`, or `interface.py`. Avoid importing another domain's internal
service or ORM model. Composition imports during bootstrap are an exception, not a precedent
for business logic.

### Agent execution

- `app.agent` is the single facade and contract: drivers, registry, dispatcher, planner,
  briefing, model resolution, streaming, and result application.
- `app.harness` is the concrete Pydantic AI implementation.
- `app.task` owns persistence, transitions, leases, attempts, and the scheduler. It provides
  a port to `app.agent`; `app.agent` never imports `app.task`.
- `bridge.hermes` adapts Hermes to the `AgentDriver` contract; a bridge must not bypass the
  agent facade.
- A stream produces zero or more message events, followed by exactly one terminal result,
  with no events after that result.

Read `docs/fr/architecture/flows/agent-execution.md`,
`docs/fr/architecture/state-machines.md`, and the `galaris-agent-execution` skill before
modifying this critical path.

### Messaging and media

`app.messenger` is the canonical model for conversations, messages, capabilities, the inbound
journal, and dispatch. Matrix, Nextcloud Talk, OneBot, Telegram, and WhatsApp are bridges:
they convert their protocol, then call the canonical facade. Do not reimplement the task
workflow inside a bridge.

Incoming files and media retain the URI of the Tool that received them. A runtime receives
only a bounded temporary materialization when a library requires bytes; that temporary
materialization is neither durable nor addressable by the agent. Consult the
`galaris-messaging-bridges` skill and the `messaging.md` and `media-resources.md` flows.

### Tools and processes

MCP tools, connections, files, and long-running executions use the contracts of `app.tools`,
`app.mcp`, `app.connection`, `app.file_share`, and `app.process`. n8n remains an external
bridge. Callbacks and process transitions must be idempotent, and terminal states must be
immutable. Consult the `galaris-process-tools` skill.

## Repository skills

Codex skills are versioned in `.agents/skills/`. Read the applicable `SKILL.md` in full
before acting, then load only the references you need.

| Work | Skills to use |
|---|---|
| Any modification | `general` |
| Module architecture or declaration | `modules`; `create-module` for complete CRUD functionality |
| Backend Python, SQLAlchemy, RBAC | `back-conventions`; add `database` when the schema changes |
| Data migrations, permanent datasets, or actions triggered by model deltas | `core-dbadmin` with `database` and `back-conventions` |
| Vue/Quasar | `front-ui-conventions`, `vue-skilld`, `quasar-skilld` |
| Pinia, routes, or translations | `pinia-skilld`, `vue-router-skilld`, `vue-i18n-skilld` depending on imports |
| Agent, task, driver, planner, briefing | `galaris-agent-execution`; add `building-pydantic-ai-agents` for the internal harness |
| Messaging or conversational bridges | `galaris-messaging-bridges`; add `onebot-11` for OneBot |
| MCP, tools, processes, n8n, files | `galaris-process-tools` |
| Logfire | The `logfire-*` skill matching instrumentation, querying, or UI work |

Use the system `skill-creator` skill to create or evolve a skill; do not duplicate that skill
in the repository. A local skill contains at least `SKILL.md`, with only `name` and
`description` in its frontmatter. Add `agents/openai.yaml` when discovery in the UI warrants
an explicit label or prompt.

## Code conventions

### Backend

- Pyright is strict for production code: type parameters and return values, and restrict
  `Any` to genuinely dynamic boundaries.
- Use SQLAlchemy 2 with `Mapped[T]`, `mapped_column`, async queries, and the contextual session
  provided by `core.database`.
- A primary key is either an auto-incrementing integer or a UUID. A column whose name ends
  in `_id` is exclusively a real foreign key to another table's primary key, with the same
  type. Identifiers provided by an external system use an explicit name such as `external_id`,
  and never the `_id` suffix on a table that does not carry them as its primary key.
- Business logic belongs in domain functions/services; routers validate, authorize,
  and delegate.
- Protect endpoints with the existing RBAC mechanism and test denials as well as successes.
- Use Loguru for application logs; do not leave `print` calls in production.

### Frontend

- The **Solaire** palette is the mandatory color reference throughout the application:
  [values and usage rules](docs/fr/dev/palette-solaire.md). Use its 11 accents and their exact
  light/dark backgrounds for icons, components, states, and charts. Do not use historical
  colors or approximate Quasar shades as a reference, or reintroduce discarded colors.
  Any palette change must be reflected in this shared reference.
- Keep components and pages focused; place API calls in services and shared state in Pinia.
- Routes are derived from `pages/`; do not maintain a second route table.
- `mobile` mode means exclusively a viewport width below 1024 CSS px (`$q.screen.lt.md`);
  `desktop` mode starts at 1024 px, regardless of orientation or device type.
- Every visible string goes through vue-i18n. English and French catalogs must retain
  matching keys, types, and parameters.
- Enforce privileges in navigation and in the API; hiding a button never replaces backend
  authorization.
- Every modal must close when its backdrop is clicked. Never use `persistent`,
  `no-backdrop-dismiss`, or an equivalent option on a Quasar dialog.
- Every paginated list defaults to 50 items and offers exactly `[10, 20, 50, 100, 500]`.
  For server-side pagination, the API contract must accept 500 items.

## Tests, documentation, and delivery

- Write the root `AGENTS.md`, `INSTALL.md`, and `CHANGELOG.md` files exclusively in English.
- Maintain `CHANGELOG.md` starting with the first actually published release. Before that
  release, do not add change entries, an anticipated version, or reconstructed history.
  At the first release, record its version and actual publication date. From then on,
  systematically accompany every notable user- or administrator-facing change with an English
  entry under `Unreleased`, then group these entries under the version and date when it is
  published. Describe observable effects, incompatibilities, and required upgrade actions
  without copying the Git log.
- Test fixtures intended for the repository must be entirely synthetic. Do not copy production
  conversations, profiles, document titles, or screenshots and merely change their names.
  Public audits retain aggregate measurements and technical conclusions; remove individual
  data, real identifiers, captured commands, and installation-specific paths. Local diagnostics
  write outside the source tree or under `artifacts/`, never into a versioned file. Preserve
  credits and copyrights.

- For an optimization or cross-cutting fix (API, lazy loading, cache, session, shared component),
  inventory its consumers and write down the guarantees to preserve before generalizing the
  change. Verify one complete user journey first, then expand by groups of consumers. Cover
  opening, reopening, existing data, errors, late responses, and context changes where relevant.
- Keep stabilization fixes narrowly scoped: separate related refactors. A passing targeted suite
  does not qualify a cross-cutting change for publication.
- Without CI, run `make validate` before publication: it tests an isolated snapshot including
  uncommitted changes. Any subsequent edit invalidates validation of the current code. Read
  `artifacts/validation/*/summary.txt` and the failures; do not treat a partial run as complete
  validation. The command neither commits nor deploys.
- Start from business behavior: first state an observable guarantee, then choose the most direct
  test that proves it. Consult the catalog in `docs/fr/dev/functional-tests.md`.
- A test must survive code reorganization that preserves its guarantee. Do not freeze a width,
  color, button order, or the presence of a source fragment to immortalize an old presentation
  request. Test usable actions, preserved content, permissions, and durable effects. A dimension
  is a valid assertion only when it represents a functional contract, such as no clipped content
  when printing.
- Use unit tests for pure rules, integration tests with real services/DB for workflows, real
  components for interactions, and a few E2E tests for the assembled system. Replace external
  boundaries, not internal services in the tested workflow.
- Before adding a test, look for existing coverage of the guarantee. Strengthen or parameterize
  a relevant scenario instead of duplicating it. Before deleting a test, document where its
  guarantee is covered or which incidental constraint is being dropped. Do not create one test
  per function or module.
- A failing test requires diagnosis: fix the product if the guarantee is broken; change the
  expectation only when the contract change is intentional and documented. For a bug, verify
  that the scenario reproduces the defect before fixing it.
- Add tests at the level of the changed contract: unit tests for logic, DB integration tests
  for persistence, AST tests for architecture boundaries.
- Run targeted tests first, then `make typecheck`, `make architecture-check`, and suites
  proportionate to the risk.
- Regenerate `docs/fr/architecture/generated/` and `docs/en/architecture/generated/` with
  `make project-context`; do not edit their files by hand.
- After documentation or navigation changes, update the FR/EN user journeys and run
  `make docs-prepare` in development before committing and validation. Commit generated maps
  with their source changes. Use `make docs-update` to propagate these sources to shared search
  in development. In every environment, `make update` consumes prepared documentation without
  regenerating it or running static documentation checks. After startup, it refreshes the active
  backend's index and checks the result before reporting success; do not bypass indexing failures
  by copying files into a container or changing agent permissions.
- Reduce `back/architecture.toml` and `back/architecture-baseline.json` when a dependency,
  private import, or cycle disappears. Never increase the baseline without explicit review.
- Add or update a decision in `project/decisions/` when a structural choice changes.
- Update `project/plans/README.md` when a plan changes status. A `design` or `approved` plan
  does not necessarily describe the current runtime yet.
- Finish with `git diff --check` and review the diff without overwriting others' changes.
