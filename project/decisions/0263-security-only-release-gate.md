# 0263 — Security-only publication and opt-in functional qualification

Status: accepted. Date: 2026-11-02. Supersedes [0262](0262-source-release-security-gate.md).

## Context

The 0.3.1 candidate passed Security, backend and static checks, but a component job
exceeded 45 minutes while repeated browser suites continued for hours. Requiring the
entire functional campaign prevented source publication independently of security.
The maintainer requested lighter default testing and security-only release eligibility.

## Decision

`make release-check RELEASE_REF=<commit>` requires the latest successful Security
workflow for that exact repository commit, followed by a fresh scan of its committed
source. Quality failures, cancellations, pending runs and missing runs do not block
source publication. Missing, stale, untrusted or unsuccessful security evidence, scanner
failures and API failures still block. Publication remains dependent on this gate and
the immutable checked commit; published tags are never replaced.

Dangerous findings are HIGH/CRITICAL vulnerabilities, detected secrets and SAST errors.
Image scans also reject HIGH/CRITICAL findings without an available fix. Their complete
inventories remain available; a missing inventory cannot establish a clean image.
The Security workflow contains source and image scans only. Restore, populated upgrade,
harness-manager and executor rehearsals belong to functional Quality.

Pushes and pull requests run quick static, build, unit and structural checks. Complete
provider, backend, component, browser and recovery suites remain available through
**Quality → Run workflow → full** on GitHub, or a manually started GitLab pipeline with
`FULL_FUNCTIONAL=true`. Full browser qualification runs each journey once on Chromium,
Firefox and WebKit, collects all failures and preserves isolation. Repeated stability
runs remain an explicit local choice. Selected functional failures still fail Quality;
omitted suites are not reported as passing. Local `make quality` and user-owned
`make validate` remain complete opt-in commands.

Quick runs on the same branch replace stale quick runs rather than accumulating per
commit. Explicit full runs have a separate concurrency group and remain distinguishable
from quick runs in the Actions list.

## Verification and limits

The real release scripts are tested with synthetic API and scanner boundaries:
functional failures permit release while every invalid security state and scanner error
blocks. Image findings are tested with and without fixes. The actual Quality result
gate is evaluated for quick/full selections, static failures and browser failures.
Workflow tests retain mandatory publication dependencies and all three full-run browsers.

Security-only eligibility is not a guarantee of functional correctness or absence of
undetected vulnerabilities. Security evidence applies to one commit and one scan time;
deployment and data recovery remain separate authorized operations.
