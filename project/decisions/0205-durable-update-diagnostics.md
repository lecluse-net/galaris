# 0205 — Durable update diagnostics independent of application logs

Date: 2026-10-18
Status: accepted

## Context

An external editor upgrade discarded Docker stderr and replaced its exception with a
generic error. Its process ran through `docker compose exec`, whose output is returned
to the caller rather than appended to the container's main-process logs. A simulated
Docker boundary also accepted a `top` format that real Docker rejects without PID.

## Decision

Source-build and prepared-release deployments share a host stage journal under
`artifacts/updates/`. They record UTC time, stage, status and the original exit code,
without copying arbitrary command output, arguments or environment variables. Journal
creation must succeed before deployment starts. Retain the latest 100 journals.

External editor maintenance preserves failed Docker commands, exit codes and bounded
stdout/stderr in a structured SSH failure receipt. Unexpected exceptions and failures
during cleanup retain their cause chain and code locations. The backend maintenance CLI
redacts and persists these diagnostics under `/data/update-diagnostics/` in its existing
data volume, prints the exact diagnostic path, and continues independent targets. Keep
the latest 100 records with directory mode 0700 and file mode 0600. Never capture local
variables or source lines. If diagnostic storage fails, print the redacted evidence to
stderr and preserve the unsuccessful maintenance result.

This evidence does not depend on the API process, database availability or a telemetry
exporter. Existing application telemetry remains complementary. Ordinary Docker output
still streams to the operator; the host journal is deliberately metadata only. Git
selection/preflight and installation keep their existing direct diagnostics.

## Verification and limits

Inject failures at source deployment stages and release editor maintenance; require a
failed journal, the correct stage, preserved exit status and no success announcement.
Test unexpected exceptions, primary plus cleanup failures, redaction, permissions,
bounded retention and unwritable storage. The Code qualification also runs the real
Docker `top` contract against a disposable paused container, alongside its unit boundary.

These guarantees cover handled failures and normal process termination. They cannot
guarantee recording after SIGKILL, power loss, loss of the storage volume or host failure.
Redaction intentionally removes credentials and opaque values; a diagnostic can remain
incomplete if the external command supplies no explanation. No live deployment or
production intervention is performed by the test suites.
