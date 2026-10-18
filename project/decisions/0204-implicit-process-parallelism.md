# 0204 — Parallel execution through ordinary Process links

Date: 2026-10-18
Status: accepted

## Decision

The native Process editor expresses parallel execution with ordinary sequence flows.
An activity with several outgoing flows admits all successor branches. An activity with
several incoming flows waits for the activated predecessors and executes once. An IF
continues to select one branch; an unselected branch cannot block convergence.

The editor no longer offers a dedicated parallel gateway when adding activities,
including inside loop bodies. Its existing branch and connection actions are the
authoring interface for splits and joins. The harness still controls actual Task
concurrency.

## Compatibility and verification

The v2 engine already implements implicit splits and joins, so its execution rules
remain unchanged. Existing `parallel` nodes, historical BPMN, saved revisions and frozen
run snapshots retain their interpretation and rendering. Removing the authoring option
requires no data migration or rewrite of saved definitions.

The existing convergence integration scenario covers ordinary nested activities,
every completion order, duplicate completion receipts and one execution of the successor.
Legacy gateways retain a compatibility case. The browser journey constructs a split and
join using ordinary activities and verifies the resulting graph without a gateway.
