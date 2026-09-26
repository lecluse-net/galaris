<p align="right"><a href="../../fr/dev/make-commands.md">Français</a> · <strong>English</strong></p>

# Make command catalog

The targets below come from the repository's six `Makefile` files. At the root, use
`make help` for current help and `make <target>` to run a command.
The `Makefile` remains authoritative. Standard installation: **`make install` → configure
`.env` and `compose.override.yaml` → `make start`**; see the [installation guide](../admin/installation.md).

## Stack and operations

| Target | Purpose |
|---|---|
| `help` | List public commands. |
| `install` | Choose PostgreSQL and an available port (8484 by default), prepare configuration and secrets; `INSTALL_PORT` supports automation. |
| `build` | Build images with cache without changing containers. |
| `start` | Start existing containers; call `update` if absent, incomplete or failed. |
| `stop` | Stop the stack while preserving containers. |
| `uninstall` | Remove project containers and networks; separately offer deletion of volumes, local Compose images and orphan containers (default: no). |
| `uninstall FORCE` | Automatically accept all three confirmations: delete volumes and their data, local Compose images and orphan containers belonging to the project. |
| `restart` | Run `stop`, then `start`. |
| `restart-service` | Restart one service without rebuilding; `SERVICE` is required. |
| `status` | Display container status; optionally filter with `SERVICE`. |
| `update` | Regenerate documentation, build and deploy existing sources, then refresh the documentation index; only `VERSION` triggers fetching a Git tag or branch. Accepts `RELEASE_DIR` outside dev, without Git, using the bundle's packaged documentation. |
| `update VERSIONS` | List all tags (highest versions first), then all branches alphabetically, from the configured Git remote, without deploying or modifying local sources. |
| `logs` | Follow all logs. |
| `logs-back`, `logs-front`, `logs-search` | Follow the selected service's logs. |
| `check-search` | Probe sources and degradation using four real public queries; opt-in diagnostic, separate from the healthcheck. |
| `logs-browser` | Follow isolated browser logs. |
| `status-executor` | Inspect the SSH executor and run its health check. |
| `logs-executor` | Follow SSH executor logs. |
| `backup-executor` | Back up executor homes, keys and registry to `backups/`. |
| `clean` | Delete stack containers and volumes. Destructive. |

Hot reload handles Python/Vue edits in development. `update` applies new sources and
configuration. `start` and `restart` do not build when containers are reusable; a failed
start triggers at most one `update GIT_UPDATE=0`. `restart-service` restarts one service without building.
`uninstall` asks separately before deleting volumes, local images (`--rmi local`) and orphan
containers of the project. Explicitly tagged images and shared cache are preserved; no global
`prune` is run. `clean` deletes volumes without confirmation.
`make uninstall FORCE` automatically accepts every proposed deletion without user input,
including permanent deletion of volume data.

```bash
make status
make status SERVICE=browser-executor
make restart-service SERVICE=browser-executor
make restart-service SERVICE=ssh-executor
```

These commands use the Compose files selected for the current environment.
`status-executor` adds an SSH health check to container status.

## Development and maintenance

| Target | Purpose |
|---|---|
| `sync-db` | Synchronize schema and datasets without restarting, only with `APP_ENV=dev`. |
| `upgrade-deps-back` | Refresh the backend lockfile and synchronize the environment with uv. |
| `upgrade-deps-front` | Update and install npm dependencies. |
| `rebuild-source-memory` | Rebuild Agent/Goal memory projections; options through `ARGS`. |
| `rebuild-messenger-contacts` | Rebuild contact memories from the Messenger journal. |
| `rebuild-memory-index` | Queue semantic index rebuilds; options through `ARGS`. |
| `rebuild-memory-links` | Reconcile derived memory links; options through `ARGS`. |
| `project-context` | Regenerate the project and frontend menu maps from code, offline. |
| `project-context-check` | Check project and menu map freshness. |
| `docs-prepare` | Regenerate maps and check the FR/EN corpus offline before validation. |
| `docs-check` | Check maps, documentation sources and links without regeneration. |
| `docs-update` | In development, prepare documentation, verify the live corpus and synchronize lexical retrieval. |
| `architecture-baseline` | Update debt baselines after reviewing the diff; only these two JSON outputs are writable. |
| `architecture-check` | Check the map, boundaries and architecture tests. |
| `test-hermes-management` | Diagnose Hermes adapter configuration and connectivity. |
| `test-harness-management` | Diagnose the generic harness manager. |
| `qualify-lab` | Start an explicitly budgeted Lab exercise or compare runs; `ARGS`, `LAB_ACCESS_TOKEN`. |
| `qualify-matrix` | Send synthetic text/file to an explicitly authorized Matrix test room. |

Management diagnostics use the active backend. Manual scripts remain available through
their Python runner in that container:

```bash
docker compose exec backend python scripts/manual_test.py tests/manual/<script>.py
```

Read the [manual diagnostics guide](../../../back/tests/manual/README.md) before running them.
They do not replace automated tests with an ephemeral database.
See [Testing behavior](testing.md).

## Validation and delivery

| Target | Purpose |
|---|---|
| `typecheck` | Pyright, vue-tsc, frontend unit tests and i18n parity. |
| `lint` | Backend Ruff and frontend lint. |
| `format-check` | Check formatting within the dedicated script's scope. |
| `tests` | Backend tests with ephemeral PostgreSQL; selection through `ARGS`. |
| `tests-recovery` | Selected recovery, durable receipt, retry and attempt ownership tests. |
| `tests-harness-contracts` | Harness contracts, adapters and Task integration. |
| `tests-harness-runtimes` | Real pinned SDKs with an isolated deterministic model. |
| `tests-providers` | Provider contracts without external API calls. |
| `tests-dbadmin-load` | Schema transitions and indexing on 100,000 isolated rows. |
| `tests-load` | Mixed local WebRTC, HTTP and file load while maintaining the lease. |
| `tests-browser` | Browser executor unit tests. |
| `tests-executor` | SSH registry concurrency and real Unix permissions. |
| `tests-harness-manager` | Harness manager tests in Docker. |
| `tests-front-tooling` | Verify that the TypeScript gate rejects invalid code. |
| `tests-front-components` | Real Vue/Quasar component interactions in an isolated browser. |
| `tests-focus-gates` | Verify that Playwright configurations reject focused tests. |
| `tests-e2e` | Browser workflows and PWA updates in an isolated stack. |
| `tests-update` | Verify installation, preserved configuration, updates and failures with simulated Docker. |
| `tests-documentation` | Verify the offline documentation runner, then its confinement in real containers. |
| `tests-install` | Install an isolated copy with new volumes, check HTTP readiness and preserve containers across stop/start. Test port defaults to `INSTALL_TEST_PORT=18484`. |
| `tests-validation-source` | Verify preservation and fingerprinting of uncommitted changes during validation. |
| `tests-coverage` | Run backend coverage, produce reports and enforce thresholds. |
| `coverage-check` | Check existing coverage reports and changed branches. |
| `tests-mutations` | Check selected mutations on disposable source copies. |
| `regression-check` | Check links between regressions and successful test/mutation reports. |
| `quality` | Run local checks; some require the active development stack. |
| `validate` | Qualify an isolated snapshot, including uncommitted changes, without the development stack. |
| `security-check` | Scan dependencies, secrets and sensitive code. |
| `tests-restore` | Rehearse database, file and key restoration on isolated data. |
| `tests-upgrade` | Rehearse an isolated upgrade from `UPGRADE_PREVIOUS_IMAGE` or `UPGRADE_FROM`. |
| `build-release` | Build/export immutable images from `RELEASE_REF` (committed HEAD by default). |
| `tests-release` | Qualify the exact production images in `RELEASE_DIR`. |

`validate` and `quality` use different environments and steps. Before publishing without CI,
run `make validate` and read its report; `make quality` is not a substitute.

## Harness Makefiles

Run these targets in their own directory, for example `make -C harness_manager help`.
They also support instance management and are not aliases for the root stack.

| Directory | Targets |
|---|---|
| `harness_manager/` | `help`, `install`, `create-secret`, `uninstall`, `start`, `stop`, `restart`, `logs`, `service-file`, `service-install`, `service-uninstall`, `service-status`, `service-logs` |
| `back/bridge/claude_agent/default-agent/` | `start`, `stop`, `restart`, `update` |
| `back/bridge/deepseek_harness/default-agent/` | `start`, `stop`, `restart`, `update` |
| `back/bridge/codex/default-agent/` | `start`, `stop`, `restart`, `update`, `logs` |
| `back/bridge/hermes/default-agent/` | `help`, `start`, `prepare-delete`, `stop`, `restart`, `update`, `hermes`, `logs`, `clean` |

For Hermes, `prepare-delete` returns data ownership to the manager before deletion.
Its `clean` performs a global Docker cleanup after confirmation; its scope exceeds
that of the root `clean` target.

For occasional shell access, use `docker compose exec ssh-executor bash` from the root,
or `docker compose exec agent /bin/bash` from the Hermes instance directory.

## Retained scope

The `logs-*` shortcuts remain available. Targeted inspection and restarts use `status`
and `restart-service` with `SERVICE`; the `status-executor` diagnostic remains distinct.

`quality` is retained for checks against the existing development environment.
`validate` freezes sources and runs checks in isolation; it also qualifies real harness SDKs.
These workflows are not aliases.

Rebuild commands repair data; Hermes and generic manager diagnostics target distinct layers.
Test targets support focused checks, CI or release qualification. A target called by another
target remains useful for rerunning a single check.

The offline documentation commands go through neither the application Compose file nor its
`.env`: they analyse a filtered snapshot of the sources and write only the expected outputs.
Details in [Tests and typing](README.md) and decision
[0137](../../../project/decisions/0137-offline-documentation-toolchain.md).
