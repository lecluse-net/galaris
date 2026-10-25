<p align="right"><a href="../../fr/dev/file-share-navigation.md">Français</a> · <strong>English</strong></p>

# Compare File Share navigation with a real harness

This experiment compares the current MCP tools with a local copy of the same corpus,
using the upstream Hermes SDK pinned by the bridge Dockerfile. It installs no FUSE
mount and creates no Task or business resource in the application instance.

## Prepare and measure

Use the active development stack and a configured, metered OpenRouter Chat Completions
model. The model code belongs to that installation; the last argument explicitly
selects an OpenRouter endpoint, without automatic fallback. Provider account
guardrails continue to apply.

```bash
make file-share-navigation ARGS="pilot $NAVIGATION_MODEL_CODE deepinfra"
make file-share-navigation ARGS="decision $NAVIGATION_MODEL_CODE deepinfra"
```

The pilot uses two missions, one repetition and both access modes. A decision campaign
requires a fully successful pilot with matching sources, images, model and corpus.
It reserves twelve other missions, five repetitions per access mode and a paired order
frozen before results exist. The launcher and containers execute a frozen source copy;
checkout edits do not change prepared runs. Reporting rejects changed executed sources
or corpus bytes.

Each invocation creates a directory under `artifacts/file-share-navigation/` containing
`manifest.json`, `source.tar.gz`, `results/`, `metrics/`, `scores.json` and `summary.json`. An interrupted
campaign retains acquired evidence and cannot produce a qualified decision. Start a
new campaign after correcting an infrastructure error; do not selectively replace
unfavorable results.
The archive retains backend and launcher sources without Git-ignored files, preserving
the calculation corresponding to the manifest's source fingerprint.

## Isolation and evidence

Every execution gets a fresh container without history. Only the directory arm receives
the read-only corpus. Both arms have the same native file and terminal tools; A has no
on-disk corpus access. The five MCP tools are discovered before inference. Their execution
calls `app.file_share.mcp`, the facade and a synthetic external transport. Expected answers
and the manifest are never mounted in the harness.

The harness has access only to an internal Docker network. Only the relay receives the
provider key, in a private temporary directory deleted on exit. It has no application
database access. Initial configuration capture checks `is_dev` and reads no conversation,
document or agent profile. Traces retain invented missions and files, tool results and
measurements only. The SDK's root UID has no capabilities; sources and corpus are read-only,
with bounded tmpfs mounts for workspace and home.

Required fields are compared exactly, including types, values and URIs. An explanation
around one JSON object does not invalidate a correct answer; contradictory objects,
incorrect identities or an inaccessible collection reported as complete fail. Actual
MCP execution provides access evidence. The relay retains provider-reported tokens and
costs, including failed runs. Missing or partial accounting prevents a qualified decision.

The manifest freezes the thresholds: 10 percentage points more success, or 20% less
cost per verified success with a 5-point success noninferiority margin; paired 95%
intervals resample missions. Repetitions do not become independent missions. Identity
confusion or silent access failures prevent continuation. No further favorable campaign
is sought after inspecting results.

## Limits and verification

Task snapshots and Mail/Messenger trees are invented files in the campaign provider;
they do not qualify domain ACLs or adapters. Local directory latency is optimistic.
Provider caches are observed, not reset. Large binaries, video reads, FUSE and real
remote transports are outside this experiment's qualification scope.
Business dates are explicit and instructions supply a reference clock; the
container's system clock is not virtualized.

```bash
make tests ARGS='tests/test_file_share_navigation.py'
```

These tests check instrumentation, pagination, bounded reads, failures, access isolation,
costs and decision calculations. They call no real model and do not replace the campaign.
