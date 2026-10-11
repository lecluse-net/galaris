<p align="right"><a href="../../fr/dev/security-validation.md">Français</a> · <strong>English</strong></p>

# Security validation

`make security-check` exports Git-visible project files to a temporary directory,
excluding live data, `.env`, external reference repositories and local environments.
Trivy checks locked dependencies and secrets; Semgrep checks Python, JavaScript and
TypeScript. Scanners run in Docker without its daemon socket or writable source
access. Docker and jq are required.

The Security workflow runs on PRs, main pushes, manual dispatch and each Monday.
HIGH/CRITICAL source findings block even when no fix exists, except for reviewed,
expiring entries in `security/trivy-ignore.yaml`. DbAdmin SAST exceptions are local
to generated or explicitly escaped SQL identifiers and literals.

Backend, frontend, browser and SSH images are rebuilt with security updates.
`bash bin/security-check.sh image IMAGE` saves the complete inventory under
`artifacts/security/` and fails if an available HIGH/CRITICAL fix remains unapplied.
Unfixed findings still require review: a passing gate does not certify an image as
vulnerability-free. CI retains reports for 30 days.

The backend build excludes the host virtual environment and removes the unused
system pip from production, which uses uv. Browser npm and its dependencies are
updated without changing browser network policies.

Require **Quality required** and **Security required** in the main branch rules.
These aggregate jobs also fail when required dependencies are cancelled or skipped.
Workflow YAML defines the checks; making them mandatory is a separate GitHub setting.

Before publication, prepare sources with `make docs-prepare`, then run `make validate`
on an isolated worktree snapshot. `make validate-stability` adds three E2E repetitions per
browser. Read `artifacts/validation/*/summary.txt` and its failures; later edits invalidate
validation. `make security-check` and `make tests-restore` can also run separately for
targeted verification.

## Repeatable restore rehearsal

`make tests-restore` exclusively uses `compose.test.yaml`, a unique Docker project
and temporary directories. It initializes the real schema using DbAdmin, seeds test
files and encrypted/signed canaries with test keys, dumps PostgreSQL in custom format,
archives files and keys, and checks SHA-256 sums. It restores into a second empty
database with `pg_restore --exit-on-error`, verifies restored files, decryption and
signatures, and removes only its own project and temporary files.

This verifies the procedure, not your actual production backups. Rehearse those on a
separate instance following the [administration procedure](../admin/README.md), using
a consistent dump, persistent volumes and the original keys; verify login and an
authorized attachment download afterwards.

## Initial image inventory — 5 September 2026

At this historical review, no HIGH/CRITICAL fix then available remained unapplied.
Distribution advisories reported these findings without a fixed package version; these
counts do not describe current images and must be measured again before publication:

| Image | Package/advisory occurrences | Distinct advisory identifiers |
|---|---:|---:|
| Backend | 141 | 47 |
| Frontend | 0 | 0 |
| Browser | 2 | 1 |
| SSH | 200 | 103 |

Some OS findings are critical. This inventory does not establish exploitability in
Galaris; findings still require review and upstream fixes. JSON reports retain the
package, version, severity, status and available fix. Counts overlap across images.
