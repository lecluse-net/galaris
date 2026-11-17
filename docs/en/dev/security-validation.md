<p align="right"><a href="../../fr/dev/security-validation.md">Français</a> · <strong>English</strong></p>

# Security validation

## Dependency audit and available versions

```bash
make dependencies-audit
make dependencies-audit FAIL_ON=MEDIUM
make dependencies-audit ALL_VERSIONS=1
make dependencies-audit REFRESH_VERSIONS=1
make dependencies-audit IMAGES='galaris-backend galaris-frontend my-harness-image'
make tests-dependencies-audit
```

Docker, Git, jq and access to public registries are required. The application stack
does not need to run. The audit changes no manifest, lockfile or installed package
and executes no package installation scripts. It scans a snapshot of Git-visible
files, including uncommitted changes; `.env`, data, caches, external references and
symbolic links are excluded.

Each run writes `artifacts/dependencies/audit-*/summary.md` and `report.json`, alongside
the inventory, raw Trivy reports and individual scan logs. Reports list every severity,
advisory identifiers and links, installed versions, published fixes or their absence,
and the latest published PyPI/npm versions for direct and vulnerable dependencies.
`ALL_VERSIONS=1` adds available versions for every transitive dependency; registry
lookups are paced to avoid overwhelming the service. Vulnerability analysis always
covers every locked version. A different version is not automatically
compatible: the JSON retains Python/Node requirements and declared ranges still need review.
Public version metadata is cached for at most one hour with its timestamp;
`REFRESH_VERSIONS=1` forces a fresh lookup. Failures are not cached and a failed refresh
never silently reuses an old answer. This cache does not replace Trivy's updated
vulnerability database.

Discovery walks every subproject: backend, frontend, desktop, Harness manager,
executors, tests and documentation tooling. `uv.lock`, `package-lock.json` and
`npm-shrinkwrap.json` cover transitive and development dependencies; `requirements*.txt`
and Python/npm versions installed directly in Dockerfiles cover explicit declarations.
A new project declaring dependencies without a supported lockfile, or a dependency
file missing from scanner output, produces a coverage error.

Base images, tools copied from images, scanners, Git sources downloaded during builds
and GitHub Actions are also inventoried. Actions are compared with their
latest published release. Docker Hub lookups report the current digest of the same
tag, without selecting another major series or following every tag. Local images,
variable references and other registries explicitly require a built-image scan.
For downloaded Git sources, the report shows the latest published release or the
default-branch HEAD when no release exists. Resolved dependencies are still scanned
in the built image, without executing these sources during the audit.

`IMAGES` accepts space-separated images **already present locally**. They are exported
and scanned without exposing the Docker socket to the scanner. This adds system
packages and dependencies actually installed by SDKs or external images, which a
lockfile-only audit cannot see. Transitive dependencies of plain requirements and
sources downloaded during builds need this additional scan. Host packages and the
host kernel are outside its scope.

Exit codes are **0** when no finding reaches the requested threshold, **1** when at
least one does, and **2** for an incomplete audit (network, scanner, missing image,
invalid report or missing coverage). The default threshold is `HIGH`: unfixed
HIGH/CRITICAL findings fail too. Lower severities remain visible. The maintenance
report retains raw findings without the publication exceptions/VEX described below.

The **Dependency audit** workflow runs manually in Actions, each Tuesday at 06:41 UTC,
and on PRs changing dependencies or their tooling. It retains reports for 30 days
and does not change the publication Security workflow rules. A registry error never
means that no vulnerabilities were found.

## Source and shipped-image checks

Python lockfiles enforce `opentelemetry-api>=1.45.2` to fix
[CVE-2026-126360](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg).
The resolver keeps compatible SDK and instrumentation versions together.
Frontend and desktop projects override vulnerable `minimatch` series (7 through 10)
with 11.0.9; the frontend also overrides `glob` 9 through 13 with 14.0.6.
These overrides address [CVE-2026-118764](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249)
and [CVE-2026-118773](https://github.com/isaacs/node-glob/security/advisories/GHSA-3g3m-2fjr-6pw4)
while retaining older `minimatch` 3/5 and `glob` 7 consumers outside those advisories.
Validation includes the PWA build, frontend lint/tests, desktop tests and packaging.
Remove these overrides once parent dependencies naturally accept corrected versions.

Advisory databases are not always synchronized. The npm check on November 17, 2026
also reports [CVE-2026-112366 / picomatch](https://github.com/advisories/GHSA-fc5q-39xc-vjpf),
absent from the initial Trivy report. The latest published version, 4.0.7, remains
affected and the advisory lists no patched release. This finding remains open;
it is neither excluded nor considered fixed by the updates above.

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
`artifacts/security/` and fails on every active HIGH/CRITICAL vulnerability, even
without a fix. Every cause is also printed in CI logs. Reports are retained for 30 days.

Backend and SSH use Ubuntu 26.04 LTS with Python 3.14. PostgreSQL clients remain 17
through the signed official PGDG repository. Backend builds exclude the host virtual
environment and have no system pip; uv owns the application environment. Browser npm and its dependencies are
updated without changing browser network policies.
Unused GStreamer Bad codecs are removed from the Chromium executor.

SSH scans retain a raw inventory and may apply VEX only to reviewed kernel CVEs for
the exact `linux-libc-dev` version. Verification of the immutable image proves that
the package contains non-executable headers and no kernel/modules are present.
The review expires; assessed findings remain visible in reports and logs. A new
version/CVE, missing proof or lost finding blocks. Host-kernel vulnerabilities are
outside this artifact assessment. See
[decision 0264](../../../project/decisions/0264-lts-runtime-security-assessment.md).

Require **Quality required** and **Security required** in the main branch rules.
These aggregate jobs also fail when required dependencies are cancelled or skipped.
Workflow YAML defines the checks; making them mandatory is a separate GitHub setting.

Prepare sources with `make docs-prepare`. For complete functional qualification, the user
can run `make validate` on an isolated worktree snapshot. `make validate-stability` adds three E2E repetitions per
browser. Read `artifacts/validation/*/summary.txt` and its failures; later edits invalidate
validation. `make security-check` and `make tests-restore` can also run separately for
targeted verification.

## Before publication

After pushing the final commit to `main`, wait for Security, then run
**before creating or pushing the tag**:

```bash
make release-check RELEASE_REF=HEAD
```

This requires Docker and jq. It uses GitHub CLI (`gh`) with Actions read access; when
`gh` is absent, curl queries the public API read-only. Private repositories require
authenticated `gh`. `GH_REPO=owner/repository` can specify the repository. It checks the latest execution of
Security for the exact commit, then runs fresh Trivy and Semgrep scans on its Git
archive, independently of uncommitted files. Missing, failed, cancelled, skipped or
pending CI blocks publication; success for another commit cannot qualify. New changes
must be committed, pushed and checked again.

**Publish release** requires the same check before creating the GitHub Release. It can
wait up to forty minutes for Security, then performs the fresh source scan. Errors appear
in Actions annotations and the step summary; logs and CI results are retained in the
`release-check` artifact. Network or scanner failures also block publication.
`make build-release` also scans committed sources before building images. None of these
checks creates a tag.

Source and image scans block active HIGH/CRITICAL findings even without a fix. Only
the precise verified VEX conclusions above can establish that a finding does not
affect the artifact. A passing image scan never substitutes for source checks.

Creating a Release manually in GitHub bypasses the workflow: use **Publish release**.
Branch and tag protections remain separate GitHub settings. The check cannot establish
the absence of still-unknown vulnerabilities. The
[publication decision](../../../project/decisions/0263-security-only-release-gate.md)
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
