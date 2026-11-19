# 0300 — Transactional installation of signed plugins

Status: accepted for declarative and trusted native bundles. Date: 2026-11-18.

The `app.plugin` domain owns publisher verification, version identity, administrative
privileges and the installation journal. The core composition binds its active presets
to the public Services catalogue port. Services owns validation of portable Service
definitions and continues to create a local Service only when a human saves it.
A local copy records the plugin code and version, and follows ordinary Service ownership.

The frontend uses four public core surfaces. It calls `core/api` for the typed HTTP
requests, `core/authorize` for permission gates, `core/navigation` for the menu
and `core/util` for shared page and dialog components. The reviewed baseline records
these four public edges and preserves an acyclic graph.

The first bundle contract supports signed Service presets. Inspect the ZIP in memory with
bounded reads. Verify an Ed25519 signature against an operator-configured publisher key
and check the signed digest of every declared file. Archive, manifest, normalized presets,
installation and history are stored in PostgreSQL. A transaction publishes a declarative
release and its receipt without a restart. A serialized transaction maintains one selected
version per code and can select an older installed compatible version. A failed transaction
preserves the previous selection. Deactivation removes contributions from the catalogue.
Uninstallation removes the archive while retaining release identity, history and local copies.

Sample sources live in `plugins/sample/<plugin>/`. Each plugin version is a single
distribution unit containing its backend, frontend and data. Drawing demonstrates the
shared source layout through explicit development composition. Its source ZIP is a
reference for authors. The same source directory builds a signed executable ZIP with a
distinct format code so it can coexist with the checkout sample.

The development composition advertises the checkout Samples in the plugin inventory.
They use the checkout's trust boundary and never create installation records. The REST
and MCP presets point to synthetic local targets. A signed release with the same Service
plugin code takes precedence, preserving the explicit registry lifecycle.
Plugin administrators can enable and disable the checkout Samples. The development
instance persists these choices separately from signed releases. Deactivation withdraws
the Drawing format and the Service presets while preserving saved documents and local
Service copies that use the synthetic targets.

Forcing a host range mismatch requires exact development mode and explicit confirmation for
the archive and built Git revision. Missing build revision confines that decision to the
current server process. Publisher trust and contribution compatibility apply to every release.
Manifest version 2 adds document formats, AI provider profiles, preview converters and
JSON data templates and file sharing protocols. Backend entry points and browser modules require both a verified
signature and an explicit operator publisher allowlist. They run with host trust.
The main composition prepares complete replacement registries before committing the
selection and publishes them in the same process. A failed preparation keeps the old
selection and records the failed activation. Startup rebuilds the effective registries
from compatible signed selections and their artifacts in PostgreSQL. Operators can inspect
redacted loading and installation failures in the private update diagnostics directory.
The file sharing protocol registry is published with the other contributions. Removing
one registry entry preserves the Services and Connections that reference it.

Python dependencies are preinstalled at declared versions. External runtimes are
operator-provisioned and bound to a declared image digest and health endpoint. The local
catalogue mirrors signed ZIPs and shares the manual import and confirmation flow.
A curated HTTPS catalogue can distribute digest-addressed archives through the same import.
Its independent signed index has a bounded expiry, a durable sequence watermark and
cumulative revocations. It rechecks both the index and the publisher signature on download.
Third-party isolation, multi-process generation coordination, other protocol families and the
official publication pipeline remain in the [implementation plan](../plans/infrastructure-plugins-galaris.md).
