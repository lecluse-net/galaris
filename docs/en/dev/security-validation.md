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

Application JWTs use PyJWT with a fixed HS256 algorithm list and a private secret.
python-jose and its unused ecdsa dependency are removed, along with the old associated
Trivy exception. The [functional guarantees](functional-tests.md) cover existing-token
compatibility and rejection of a DER public key used as an HMAC secret. Migration SAST
annotations justify each statement through closed identifier lists, declared models or
escaped names; external values remain bound parameters. They do not disable the global
SQL rule and require review when interpolated fragments change.

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

## Before publication

After pushing the final commit to `main`, wait for Quality and Security, then run
**before creating or pushing the tag**:

```bash
make release-check RELEASE_REF=HEAD
```

This requires Docker and jq. It uses GitHub CLI (`gh`) with Actions read access; when
`gh` is absent, curl queries the public API read-only. Private repositories require
authenticated `gh`. `GH_REPO=owner/repository` can specify the repository. It checks the latest execution of
each workflow for the exact commit, then runs fresh Trivy and Semgrep scans on its Git
archive, independently of uncommitted files. Missing, failed, cancelled, skipped or
pending CI blocks publication; success for another commit cannot qualify. New changes
must be committed, pushed and checked again.

**Publish release** requires the same check before creating the GitHub Release. It can
wait up to four hours for running CI, then performs the fresh source scan. Errors appear
in Actions annotations and the step summary; logs and CI results are retained in the
`release-check` artifact. Network or scanner failures also block publication.
`make build-release` also scans committed sources before building images. None of these
checks creates a tag.

Source scans block HIGH/CRITICAL findings even without a fix. Image scans retain their
policy for unfixed system packages and display the number of unfixed critical findings;
a passing image scan never substitutes for source checks. These provide different
guarantees.

Creating a Release manually in GitHub bypasses the workflow: use **Publish release**.
Branch and tag protections remain separate GitHub settings. The check cannot establish
the absence of still-unknown vulnerabilities. The
[publication decision](../../../project/decisions/0262-source-release-security-gate.md)
records the sequencing defect and the chosen contract.

## Repeatable restore rehearsal

`make tests-restore` exclusively uses `compose.test.yaml`, a unique Docker project
and temporary directories. It initializes the real schema using DbAdmin, seeds test
files and encrypted/signed canaries with test keys, dumps PostgreSQL in custom format,
archives files and keys, and checks SHA-256 sums. It restores into a second empty
database with `pg_restore --exit-on-error`, verifies restored files, decryption and
signatures, and removes only its own project and temporary files.
The current Document API must also return the exact current content, historical
version, manual summary, keywords and attachment, while denying an unrelated user.

This verifies the procedure, not your actual production backups. Rehearse those on a
separate instance following the [administration procedure](../admin/README.md), using
a consistent dump, persistent volumes and the original keys; verify login and an
authorized attachment download afterwards.

`UPGRADE_FROM=reference make tests-upgrade` and `UPGRADE_SOURCE=path make tests-upgrade`
build the historical backend with its own Dockerfile, locked dependencies and bundled
sources. CI selects the latest semantic tag among the candidate parent's ancestors,
rather than just the previous commit. That same historical environment seeds data and verifies rollback; it does not
reuse candidate dependencies. An immutable image supplied with `UPGRADE_PREVIOUS_IMAGE`
is reused unchanged. `make tests-release-check` protects that separation, stopping on
build failures and retaining supplied images. The complete rehearsal still uses temporary
databases and files without touching the application instance.

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
