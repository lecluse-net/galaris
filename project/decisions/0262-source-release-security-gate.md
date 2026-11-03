# 0262 — Source publication requires exact-commit security evidence

Status: superseded by [0263](0263-security-only-release-gate.md). Date: 2026-11-01.

## Context

An image scan can succeed while retaining HIGH/CRITICAL advisories without an available
fix. During 0.3.0 preparation, this included a critical application dependency. The source
scan had a stricter policy, but source publication did not require it or completed CI.
Treating the image result as publication approval allowed a known finding through.

## Decision

Before creating a release tag, `make release-check RELEASE_REF=<commit>` requires the
latest successful Quality and Security executions for that exact repository commit.
Missing, pending, skipped, cancelled, failed, untrusted or mismatched evidence blocks.
The check then scans an archive of the committed source with a freshly downloaded
vulnerability database. Unfixed HIGH/CRITICAL source findings still block unless covered
by a reviewed, expiring exception. Scanner and API errors also block.

GitHub source publication depends on this check. Only the publication job receives
content write permission; its prerequisites cannot publish. Failure evidence is retained
and displayed in Actions before the Release can be created. Immutable bundle creation
also scans its committed source before starting image builds. Image inventory output
distinguishes unfixed critical findings from available fixes and is never release approval.

Browser qualification uses separate Chromium, Firefox and WebKit runners, retaining
three repetitions per journey and an isolated stack per browser. The matrix does not
cancel siblings after a failure. Every browser result contributes to required Quality;
resource isolation cannot turn a failed or missing browser qualification into approval.

## Limits and verification

Direct Git pushes and manual GitHub UI publication can bypass repository scripts;
maintainers must use the guarded path and configure repository protections separately.
Published tags remain immutable. New advisories after a successful scan remain possible.
This gate does not replace application tests, image qualification or user-owned local
validation. Changes require new committed evidence.

Synthetic tests execute the actual scripts with scanner and GitHub API boundaries
replaced. They exercise failures, absent/stale evidence, latest-run selection, source
snapshot identity and publication dependencies. Real source scans verify the published
vulnerable source is rejected; workflow syntax is checked independently.
