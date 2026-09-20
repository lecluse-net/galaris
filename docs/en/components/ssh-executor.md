<p align="right"><a href="../../fr/components/ssh-executor.md">Français</a> · <strong>English</strong></p>

# Embedded SSH Executor

This Debian service provides the standard persistent Linux environment for `internal` Agents. It
exposes no host port: the backend reaches it through the private Docker network for SSH/SFTP and
through a private Unix socket for the permitted management operations only.

The single `galaris_data` application volume is mounted at `/data` by the backend and this
executor. Embedded Console data is grouped without any additional mount:

- `/data/ssh-executor/home` retains Agent home directories and Git repositories;
- `/data/ssh-executor/state` retains the UID registry, host keys, and authorized public keys;
- `/data/ssh-executor/run` carries the private socket shared with the backend.

This service's `/data` mount is declared alongside the backend mount in `compose.override.yaml`.
The service itself is always defined and started by the standard `compose.yaml`, so every
installation can offer the local Console without a later infrastructure migration. Console
connections to external SSH hosts remain available as well.

An account is created only when an Agent is explicitly provisioned from the Console page. Its
login is exactly `Agent.code`; a code incompatible with Debian is rejected without transformation.
SSH passwords are disabled, and root-controlled public keys remain outside the home directory. The
corresponding private key stays encrypted in Galaris.

Common commands:

```sh
make status-executor
make logs-executor
docker compose exec ssh-executor bash
make restart-service SERVICE=ssh-executor
make backup-executor
```

To use another machine, create or edit the Agent's `console` connection with its SSH and SFTP
parameters and pinned host key. No Driver component changes. Mode is detected automatically: a
target remains in standard mode until a working `galaris-exec --version` is found. After a
successful SSH test, the interface can install or update the versioned helper under
`~/.galaris/bin/galaris-exec` without root access, then verify the
`operation_recovery_available` capability. The button remains available for a v1 helper even
in enhanced mode. Detection prefers an available v2 helper over a v1 user installation.
The external target must provide `/bin/bash` and Python 3.11 or newer; the helper retains
this compatibility independently of the backend's Python version.

Use `console_exec` for short commands. Separate edits from long test suites or builds, launch
those with `console_start`, and follow them with `console_poll` using the same identifier.
During recovery, a `running` receipt acknowledges the launch of `console_start`, but does not
complete an interrupted `console_exec`. An unknown outcome remains blocked; upgrading the
helper cannot recreate missing receipts for older operations.
