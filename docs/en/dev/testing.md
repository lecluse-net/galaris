<p align="right"><a href="../../fr/dev/testing.md">Français</a> · <strong>English</strong></p>

# Testing behavior and understanding the result

A passing suite validates its scenarios with their inputs and dependencies. It does not
prove every possible interaction. Choose the layer that can observe the failure you want
to detect, and assert the resulting behavior.

## Start from business behavior, module by module

The [functional catalogue](functional-tests.md) connects business responsibilities to existing
suites. It provides starting points, not an exhaustive certification. Describe the actor,
action and observable result first, including denied access or forbidden effects where relevant.
Find the existing proof and strengthen or parameterize it before adding another test.

Keep domain tests alongside their module and cross-domain scenarios in `back/tests/` or
`e2e/specs/`. Integration scenarios use real services, schemas, authorization and persistence;
doubles replace providers, transports and autonomous scheduling. No wholesale relocation or
additional BDD framework is needed.

A narrow viewport is a usage condition: authoring a skill or editing a document must work.
It does not justify freezing button rows, margins or historical colors. Assert geometry only
when it proves a functional requirement, such as unclipped printed tables or commands remaining
reachable while scrolling. Persisted theme preferences and authored document styles are data;
the exact pixels of editing controls are not.

Diagnose failures before changing expectations. Distinguish product regressions, invalid
fixtures and intentional, documented contract changes. Existing Make targets and CI jobs
collect the scenarios. Their success should be required before merging; local workflow YAML
alone does not prove that remote branch protection is enabled.

## Commands

Run toolchains in containers. Backend tests and E2E workflows create their own databases;
never run pytest in the development backend.

| Need | Command | Evidence |
|---|---|---|
| Targeted backend | `make tests ARGS='app/messenger/tests/test_interactions.py'` | Selected contracts and persistence |
| Provider compatibility and admission | `make tests-providers` | SDK → proxy → simulated HTTP composition, output validation and Task persistence; required by CI and `make validate` |
| Full backend with critical coverage | `make tests-coverage` | One full execution with configured line and branch coverage |
| Types, frontend units and translations | `make typecheck` | Pyright, vue-tsc, fast Node tests and catalog consistency |
| Real Vue components in Chromium | `make tests-front-components` | DOM, events, computed styles and explicitly intercepted HTTP requests |
| Selected components | `make tests-front-components ARGS='chat.spec.mjs voice.spec.mjs'` | Selected scenarios in the same isolated environment |
| TypeScript gate effectiveness | `make tests-front-tooling` | Deliberately invalid disposable copies are rejected |
| Full application workflows | `make tests-e2e` | Production frontend, API, PostgreSQL and WebSocket in Chromium, Firefox and WebKit |
| Module boundaries | `make architecture-check` | Current generated map and structural contracts |
| Lifecycle mutations | `make tests-mutations` | Nine faults injected into disposable copies cause behavioral failures |
| Browser collection | `make tests-focus-gates` | Both configurations accept ordinary tests and reject `test.only` |
| Regression evidence | `make regression-check` | Referenced tests passed and their mutations were detected |

To exclude Lab tests, use `make tests-coverage COVERAGE_TEST_ARGS='--ignore=app/lab'`.
Test selection does not change the coverage file configuration. Select E2E files explicitly
through `ARGS` when needed. General CI retains its complete scope.

Inside the frontend container, `npm test` collects `*.test.mjs`. The expensive tooling
test is a `*.check.mjs`, run separately in CI and by `make quality`. Component scenarios
are `*.spec.mjs`, collected by their mandatory Make target and CI job rather than Node.

## Select the layer

- **Unit:** execute the function, complete TypeScript module or real store; replace only
  necessary dependencies. Check outputs, state, requests and forbidden side effects.
- **Database:** `db` and `client` fixtures share an outer transaction with savepoints.
  An application `commit()` does not imply an independent commit. `committed_database`
  supplies independent connections and real commits for locking and visibility tests.
- **HTTP:** a direct service call does not prove router authorization. Test denied requests
  as well as success. The ordinary ASGI client does not replace full startup, lifespan
  and workers exercised by E2E workflows.
- **Browser component:** mount real Vue, Quasar, Pinia, i18n and services. Fixtures replace
  HTTP responses rather than application functions. An unexpected API request fails the
  test. Exercise keyboard input, dismissal, permissions, delayed requests, revisions and
  relevant viewport sizes.
- **Static contract:** use AST, evaluated configuration or parsed catalogs when structure
  is the actual requirement. Finding a `v-if`, CSS class or comment does not prove UI behavior.

Component tests run on an internal Docker network, without backend, host ports or external
accounts. Audio input is synthetic. Socket.IO events are injected into the listeners actually
registered by the application; E2E tests additionally exercise network transport. Component
navigation uses a memory router; full workflows exercise production routing.

The runner removes only its own project and volumes. Failure traces, screenshots, HTML reports
and service logs remain in `artifacts/front-components/<project>/`. Source is copied to a temporary
directory at startup so concurrent edits cannot reload an active test. Dependencies live in a Docker volume.

## External bridges and AI quality

Mock transports, SDK doubles and recorded responses protect local contracts: URLs, emitted
authentication, payloads, conversion, retries, denial and durable effects. Keep these tests
for WhatsApp, Telegram, Matrix, Talk, OneBot, n8n and other adapters. They do not prove that a
real account can connect to today's remote service or that a remote user received a message.
Such qualification requires dedicated accounts and delivery evidence. `make qualify-matrix`
provides a first live workflow: two distinct accounts, an authorized room, synthetic text and
a file whose bytes the second account verifies. It does not qualify other bridges or inbound
Task admission. General CI does not configure real accounts.

Deterministic agent and memory evaluations protect wiring, rules, isolation and output formats.
Controlled responses do not measure a real model's general judgment. Real Lab evaluations
remain separate from deterministic tests of its forms, authorization and publication.

## Interpret metrics

`back/coverage-critical.ini` requires **95% over an aggregate subset**, including branches.
This is neither whole-application coverage nor a minimum for each bridge. Nine detected
mutations are not a global mutation score.

Removing exact margin, color or comment assertions does not create a functional guarantee.
Record what a replacement actually exercises and which incidental constraints were retired.
Scripts under `back/tests/manual/` remain operator diagnostics rather than automated CI evidence.

The [implementation report](../../../project/audits/2026-09-07-test-suite-improvements.md)
records replacements, removals and completed validation runs.

## Regressions and interruptions

For each product regression: describe the guarantee, reproduce before fixing, preserve the
principal scenario and populate `regression_test` in Incident. Weak tests follow the same
process. `project/regressions.json` links cases with permanent mutations to their audit and
test. `make regression-check` verifies their JUnit and mutation results. Purely external
incidents do not require artificial tests or fabricated fix references.

Task and Process callback sequences use multiple fixed seeds and report their seed and
history on failure. `test_crash_recovery.py` kills a Python process after a callback commit
or a simulated provider effect, then starts a fresh process against the same ephemeral
DB. It checks results, waiting tasks, journal entries and idempotency keys. The simulated
provider has a durable ledger; this does not establish idempotency support in real providers.

Backend/browser JUnit, Playwright JSON, mutations and domain coverage remain CI artifacts.
Track first attempts, skipped tests, durations and recurring Incidents. A successful second
attempt does not erase the first failure. Browser retries remain zero, with three E2E
repetitions in CI.

## Domain coverage

`make validate` runs local pre-publication checks without a CI server or a running development
stack. It captures tracked and non-ignored new files, including uncommitted edits and deletions,
in an isolated local clone. Test configuration comes from `.env.example`, never the deployment
`.env`. It does not commit, restart the application, contact messaging accounts or make paid AI calls.

It runs static checks and builds, backend coverage, real component tests, mutations and incident
evidence, executors and E2E workflows repeated three times per browser. Independent stages continue
after failures. Results and logs live in `artifacts/validation/<run>/`; detailed reports and traces
are under `source/artifacts/`. Source copies and archives remain available for diagnosis; allow
disk space for them and remove old validation directories when no longer needed.

A nonzero exit code means the run is not a complete validation. Source edits during execution
produce `STALE` and require a new run. For already committed work, use
`VALIDATION_BASE=<commit before the change> make validate`; the default compares local changes
against HEAD. External accounts, deployment HTTPS, upgrades and restoration require their
separate qualification workflows.

`make tests-coverage` now measures every backend `core`, `app` and `bridge` source, including
files never imported by tests. `artifacts/coverage-full.xml`, `artifacts/coverage-full.json` and
`artifacts/coverage-html/index.html` report missing lines and branches by domain. Tests and
embedded `default-agent` runtimes are excluded. `back/coverage-all-domains.json` records initial
per-domain floors rounded down to whole percentages from the September 12 full run. Drops below
these floors, missing domains and new domains without a floor fail the check. Raise floors after
review, never automatically. The more precise critical floors still apply. The critical 95%
threshold is not a global coverage claim. Both reports come from the same pytest execution.

`back/coverage-domains.json` enforces separate line and branch floors for ten critical domains.
A missing domain or unassigned measured file fails the gate. Setting
`COVERAGE_DIFF_BASE=<commit> make coverage-check` also rejects changed critical branches that
are not fully covered. Reports describe the measured subset. The explicit
`check_critical_coverage.py --record` command proposes floors for diff review; CI never runs
it. Do not lower floors to pass a change without explaining the preserved guarantee and the
reason for revision.

## Model and bridge qualification

`back/lab-qualification.json` requires three repetitions, a minimum category mean of 80,
a maximum five-point drop in score or pass rate, and no security failures. Nominal, robustness
and security categories are required. Captured cases, repetitions, judge and scoring version
must match. Incomplete runs, missing budgets, unusable judgments and exceeded budgets cannot
qualify a candidate. Lab budgets remain admission thresholds that in-flight calls can exceed;
the comparator then rejects qualification.

Install the versioned corpus with `scripts/import_lab_reference.py`, then use
`make qualify-lab` with `LAB_ACCESS_TOKEN` in the environment and `--base-url <URL>` in
`ARGS`. The `--start-dataset <uuid> --llm-id <id> --judge-llm-id <id> --max-cost <USD>` mode
explicitly starts a campaign. `--baseline <uuid> --candidate <uuid>` compares completed runs.
The report is `artifacts/lab-qualification.json`. Model judgments do not prove external
delivery; retain independent human review for critical errors.

For Matrix, supply `MATRIX_QUALIFICATION_SENDER_TOKEN` and `MATRIX_QUALIFICATION_OBSERVER_TOKEN`
through the environment, then run `make qualify-matrix` with these `ARGS`:
`--homeserver <HTTPS> --sender <test-account> --observer <second-test-account>
--send-to-room <test-room> --output /repo/artifacts/matrix-run.json`, on one line.
Only dedicated accounts and destinations are appropriate. Partial receipts survive lost
responses; reusing the same evidence file cannot resubmit messages. General CI never runs
these live commands automatically.

## GitLab activation

The `perso/genial` remote uses GitLab. `.gitlab-ci.yml` provides typing/build, testing,
security, restoration and upgrade gates. It requires a dedicated Shell runner tagged
`galaris-quality`, with Docker Compose, Make, Bash, Git and jq; Python and Node remain
inside Docker. A GitLab schedule adds load tests. Manual release qualification requires the
previously deployed image and does not deploy anything. GitHub workflows remain usable
for a mirror.

A Maintainer must enable `only_allow_merge_if_pipeline_succeeds`, reject skipped pipelines
and restrict `main` changes to validated merges. On September 11, 2026, remote inspection
showed the first setting disabled and Maintainer pushes allowed. GitLab validated the syntax;
the Developer account cannot enable these settings or simulate a pipeline on `main`.
Versioned YAML alone does not mean the gates are active.
