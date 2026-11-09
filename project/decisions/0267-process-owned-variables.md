# 0267 — Process-owned variables with isolated run values

- Date: 2026-11-07
- Status: accepted and implemented
- Replaces task-level input/output declarations in the unreleased native v2 profile.

## Decision

The root BPMN graph owns a single ordered `variables` registry. Each declaration contains
its unique name, type, nullability and optional typed default. Activities declare no
variables. Inline FOR/WHILE bodies use the parent registry; called processes own independent
registries and run data. Explicit mappings adapt tool arguments and child results without
creating a second declaration system.

Each run freezes its registry with its admitted graph. Supplied initial values are validated
and defaults are copied once at launch. A variable without an initial value or default stays
absent, including nullable variables. Absence means uninitialized; an explicit typed null is
a value and requires nullability. False, zero, empty strings and empty containers remain values.

Every node carries permitted ordered `inputs` and `outputs` lists containing only
names from that registry. These are references, never declarations or local variables.
Start and IF nodes have no output variables; End nodes have no input variables. The process
input contract is derived exclusively from its root Start node's inputs, with no independent
root input list. Process outputs are derived from the root End nodes' selections, with no
independent root output list. A run returns only initialized outputs selected by End nodes
actually reached. The editor's boundary summary is read-only and the usage lists contain
actual nodes only, never an independent generic Process consumer.
Inline body nodes reference the same root registry. Empty selections mean no variables;
duplicate or unknown references are rejected before saving. Process admission accepts only
selected input names; defaults still initialize declared variables once. Final results
expose initialized selected process outputs, while run inspection retains all business data.

Activities read a snapshot of their selected inputs and submit changes only to their
selected outputs. Preprocessing sees selected inputs; postprocessing cannot write or remove
unselected outputs. Mappings adapt external argument and result names without creating
additional declarations. A configured IF returns only its technical Boolean control decision
and never updates business variables, including a registry variable named `decision`. The
previous IF business-output behavior is intentionally removed. Missing entries
never reset existing values or apply defaults. The engine validates names and types against
the frozen registry before committing data, file links and the integration receipt. Existing
conflict detection, replay identities, cancellation fencing and terminal-state protections
remain.

Human questions select variable names from the process registry and require the selected
fields without reapplying process defaults. Their frozen response
contracts and correlation receipts remain technical execution state. A binary decision is
control flow and does not introduce a business variable named `decision` into the registry.

The editor exposes the registry independently of activity selection. Users configure the
same bindings either in a node inspector or in the variable's input/output consumer lists,
including process boundaries and nested nodes. Renaming or removing a declaration updates
all references; reordering it preserves bindings. Removing a node removes its derived usage.
Run inspection lists
every admitted variable with its type and current value, including uninitialized entries,
under the parent Process's existing access policy.

Variable labels are localized separately from stable transport codes. The shared typed-value
codec covers business references using their existing IDs or resource URIs. Document variables
may constrain `document_type` to text or data; File variables may constrain an exact MIME type
or a MIME family. Constraints survive BPMN snapshots and do not create resource grants.
Process checks constrained resources through File Sharing at admission and before integration,
under the executing agent's identity. Missing updates never recheck or replace an unchanged value.

## Compatibility

This module is under development and has not been distributed. The v2 contract changes
directly; no task-declaration adapter, data migration or new profile version is added.
The historical untyped v1 execution path remains separate. SQL storage already belongs
to Process, so this change requires no database schema alteration.

## Verification

The existing Process suites cover XML persistence, typing, tools, child calls, human replies,
joins, receipts, cancellation and access denials with synthetic data. Additional scenarios
cover partial updates, absent versus null, independent runs and frozen registries after edits.
The frontend journey preserves defaults, invalid drafts and ordering in the single registry;
run-variable inspection verifies values and refreshes across data changes.
