<p align="right"><a href="../../fr/dev/agent-team-qualification.md">Français</a> · <strong>English</strong></p>

# Qualifying teamwork with real agents

This pilot prepares and observes a fictional mission in the assembled application. Chat,
permissions, inbound journaling, Tasks, scheduling and the internal harness are real. Agent
decisions and replies are not scripted. This is neither a Lab benchmark nor a deterministic
E2E suite. Collaboration gains remain to be measured.

## Prepare without provider inference

Prerequisite: the development backend image `galaris-backend` must already exist.
`GALARIS_TEAM_BACKEND_IMAGE` selects another compatible image. Run from the development checkout
using Docker; no host toolchain is needed.

```bash
make agent-team-pilot ARGS='prepare'
make agent-team-pilot ARGS='prepare --case conflict --mode directed'
```

Each command owns a separate Compose project, empty database/storage, three fictional agents
(leader, logistics, finance), three HTML sources and an existing summary. The agents belong
to a dedicated three-member team with no global access to other agents.
Preflight checks team memberships before submission; document read grants to colleagues
remain separate. For preparation only, the provider is
disabled, Dream is off and fixtures do not provision SSH consoles. Preparation checks
authentication and resource reads, then opens the actual Chat in
Chromium and saves a screenshot. It submits no mission. `prepare --api-only` checks backend
preparation only and supplies no browser evidence. `APP_ENV=qualification` retains production
protections.

Services do not reuse the application's `.env`, an existing database, or external messaging
connections. Agent tools are limited to the dossier. Existing agents' profiles and provider
credentials are not copied.

## Run a real mission

Copy `back/tests/agent_team_pilot/provider.example.json` under local `artifacts/` or outside
the checkout. Set `base_url` and `model` for an OpenAI Chat compatible endpoint supporting tools
and structured output. One model serves all three agents and text-based structured choices.
The profile uses public capability validation, with no specialized native Decisions binding;
preflight verifies these selections before submission. There is no automatic model discovery
or fallback. OAuth/subscription models and external harnesses are outside this
first version's coverage.

Keep the provider key in a separate `0600` file, never in JSON, command arguments or tracked files.
For a local endpoint without a key, explicitly set `allow_no_api_key: true`. Optional
`input_usd_per_million` and `output_usd_per_million` enable estimated cost tracking. Missing prices
do not imply free inference. `max_tokens` and `timeout_seconds` bound admission; an engaged call
may exceed an estimate. They are not provider billing caps.

```bash
make agent-team-pilot ARGS='run --case baseline --mode spontaneous --config /absolute/provider.json --key-file /absolute/provider-key'
make agent-team-pilot ARGS='run --case conflict --mode directed --config /absolute/provider.json --key-file /absolute/provider-key'
make agent-team-pilot ARGS='run --case amendment --mode directed --config /absolute/provider.json --key-file /absolute/provider-key'
```

`run` requests real inference and incurs its costs. A single mission is submitted through the
actual Chat composer with `@task`. The application chooses calls, delegations, objectives and
synthesis. The observer creates no subtasks and fabricates no colleague answers. It collects the
authenticated Chat and Task APIs; the normal backend exposes no pilot fixture routes.

A browser error after the submission receipt never resubmits the mission: the pilot collects
the admitted work before cleanup. The primary failure code and browser diagnostics survive
even if observation or capture also fails. Missing receipts never trigger automatic resubmission.

## Scenarios and organization

| Scenario | Situation | Human acceptance |
|---|---|---|
| `baseline` | Complementary sources, known uncommitted transport quote | Complete sourced summary and preserved facts; delegation observed or explicitly absent |
| `missing` | Missing transport cost | Unknown identified; useful follow-up or precise limitation, no invented figure |
| `conflict` | 60 announced participants for 48 seats | Sourced disagreement, no invented human decision |
| `amendment` | Budget changes during contributions | Updated envelope/balance, instruction propagation, other facts preserved |
| `amendments` | Two instructions: 7200 → 6800 → 6500 EUR | Ordered admissions, latest budget and 200 EUR reserve, no reconfirmation of the settled budget |
| `peer_failure` | Finance provider unavailable | Actual failure, Logistics retained, recovery or precise limitation without invented validation |
| `comparison` | Two costed options, commitments and capacities | Same rubric for `directed` and `solo`: fidelity, arithmetic, time, cost and interventions |

The brief prohibits **new** bookings and explicitly preserves the already confirmed booking.
An instruction not to act therefore does not conflict with that existing state. Review also
checks unknowns proposed by colleagues: the sources provide the EUR currency, while the
tax-inclusive or tax-exclusive status remains unspecified.

`spontaneous` leaves collaboration choices to the leader. `directed` requests leadership of both
colleagues without scripting a tool order. `solo` disables delegation functions. Agents actually
reason and work in each mode. The initial corpus and missions are French; this version does not
establish English agent behavior.

For `amendment`, the observer sends one human instruction only after observing two distinct
colleagues executing (`EXEC`), without a pause. A queued task does not trigger submission.
It retains the trigger, Tasks and accepted message. Without overlapping contributions,
the instruction is not sent and this run does not qualify a mid-work change. `amendment/solo` is
rejected. Message submissions are never automatically retried after an uncertain outcome.

An instruction accepted during delegation is retained in `task_amendments` with `applied_at=null`
and a `deferred=true` receipt. Colleagues finish their contributions; fan-in applies instructions
in admission order before resuming synthesis. A materialized plan on the root Task remains
non-amendable. Human pauses retain priority; an incompatible checkpoint blocks resumption
without losing the instruction. An accepted message, `SUCCESS` Tasks or an updated finance
source does not prove the final document correct: inspect the target, amendments and contributions.

## Inspect evidence

In `amendments`, the second instruction is sent only after observing the first durable admission
and while work remains nonterminal. Both sends retain distinct receipts. In `peer_failure`, only
Finance uses a local endpoint without a server: the real harness encounters its connection failure.
Task states and peer contributions are never fabricated. The `amendments/solo` and
`peer_failure/solo` combinations are rejected.

Run `comparison` in `directed` and `solo` with identical sources, model, parameters and frozen code.
Review both documents against the same rubric, then compare physical calls, cost, duration and
requests for human intervention. One pair remains exploratory, without statistical evidence of gains.
Inspect the primary table and final message, not merely whether correct figures appear in an appendix.
A known uncommitted quote remains a provisional forecast cost within the compared scope; an
arithmetically correct partial total may still mislead the decision.

### Interrupt the backend process

```bash
make agent-team-pilot ARGS='run --case amendment --mode directed --restart-after-amendment --config /absolute/provider.json --key-file /absolute/provider-key'
make agent-team-pilot ARGS='run --case amendment --mode directed --restart-after-write --config /absolute/provider.json --key-file /absolute/provider-key'
```

The observer waits for a durable unapplied instruction and at least one completed contribution.
It records a snapshot and rechecks the instruction before requesting interruption. The host
controller sends one `SIGKILL` to this Compose project's backend, keeps the database and restarts
the same container. A private volume preserves `/data`; bootstrap verifies the run identity,
configuration and manifest and never reseeds fixtures on restart. Final cleanup removes the
volume and containers of this pilot project only.

`before-restart.json`, `after-restart.json`, `boots.jsonl`, `backend-*.json`, `database-*.json`
and `restart-receipt.json` distinguish interruption, resumption and storage preservation.
Normal recovery waits for lease expiry without shortening those deadlines. Post-restart timestamps
must confirm that the instruction had not already been applied before interruption; the last
pre-fault read alone is insufficient. A fault before the first document write does not qualify
recovery of a committed write. If the instruction
is applied before the interruption window, the scenario is unexercised and the command fails
without injecting a late fault. Interrupted inference calls may resume and incur cost: inspect
durable effects rather than treating every new inference as a duplicate. Effect observations
cover the pilot's Documents.

### Retained results

`--restart-after-write` targets a separate window: the target must have a committed revision above
its initial revision before final delivery. The same revision and content hash must survive restart,
and the final message must be dated after the new process started. A message already delivered before
the crash does not qualify. Repeated hashes are reported; reviewing different content for duplicated
passages remains necessary. The two fault windows are distinct.

Each invocation prints its private `artifacts/agent-team/run.…/` directory:

- `manifest.json`: mission, criteria withheld from candidate context, settings and resources;
- `scenario.md`: readable mission and fictional sources before execution;
- `preflight.json`: preparation without a mission;
- `submission.json`: actual submitted-message receipt;
- `timeline.jsonl`: timestamped observed changes;
- `evidence.json`: messages, round traces, full Tasks, budgets and documents;
- `assessment.json` and `report.md`: observations, final document text, messages and an unfilled human checklist;
- `browser-*.png` and `browser-*-errors.json`: screenshots and browser errors;
- source hashes, `services.log`, `exit-status.txt`, `cleanup.log`: provenance and diagnostics.

`browser-*-state.json` records the secure context and room-subscription submission.
`preflight.json` also verifies that no model call was recorded. If sources change during the
pilot, `source-changed.txt` records this and the command exits unsuccessfully: observations do
not qualify a fixed checkout. Execution evidence retains physical calls and recorded inference
cost; estimates or absent prices must still be interpreted accordingly.

Ephemeral login credentials are removed during cleanup. Keys and tokens are redacted from
diagnostics. Evidence contains only this pilot's fictional resources and remains local. Never
replace these fixtures with copied data from another installation.

The report separates absent delegation, one/two colleagues observed, timeout and collection
failure. Exit zero means execution/collection completed, not content acceptance. `SUCCESS` never
automatically satisfies criteria. Human review must identify relevant content and events; the
evidence hash fixes what was reviewed. Task costs may include descendants and are not summed.

`editorial_observations` records whether the target document was observed and flags consecutive
identical headings; an absent target is not a successful check. This observation neither
rewrites nor accepts content. Review must also verify that contradictions rely on incompatible
claims about the same subject/time/scope, that unknowns remain unknown and that real conflicts
are preserved.

Removing the project stops local workers, not necessarily a physical provider call. Interruptions
and collection failures retain available evidence without reporting success. Cleanup affects only
the current invocation's Compose project.

## Extend after the first walkthrough

Review one complete mission first. Repeat with comparable models, inputs and budgets, measuring
errors, human corrections, duration and cost per accepted result. `tests/test_agent_team_pilot.py`
protects evidence collection, isolation and conservative conclusions; it proves no agent ability.
Crash recovery and interactive human authorizations remain additional qualification work and are
not exercised automatically.
