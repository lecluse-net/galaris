# 0265 — Strict schema convergence, qualified deployments and offline backups

Date: 2026-11-04
Status: accepted

## Decision

A successful update must leave the declared schema complete. Only the DbAdmin `converged`
verdict returns zero; staged backfills, degraded preparation and contraction failures block
startup. Partial progress and historical sources remain available for forward recovery.
Atlas checks expansion before subsequent actions and compares the final live schema to the
unfiltered canonical target after postprocessing. Actions may declare public table/column
requirements for both callbacks; these are checked before either callback executes.

This does not make arbitrary data transformations infallible. Upgrade qualification must
seed synthetic data with the real historical binary; retaining new columns in a reconstructed
old schema previously concealed a pre-expansion destination dependency. The typed Document
transfer now declares its destination requirements explicitly.

SQL objects absent from the current SQLAlchemy target, including application functions and
triggers, explicitly prevent a full-convergence verdict. Extension members are distinct.
Declarative support for these objects requires a separate tooling choice; silent omission
is not accepted as complete-schema verification.

`make update` builds the current checkout for every branch, tag and application mode.
`VERSION` explicitly selects any Git tag or branch; `APP_ENV` controls application behavior
and Compose configuration, independently of source provenance. `RELEASE_DIR` is an optional
immutable delivery path whose bundle identity, upgrade and restoration gates remain mandatory.
Publication of source releases retains its separate security-only policy.

`make save` archives the complete database and `/data` excluding exactly the root `files`
subtree. Configuration, recovery keys and payload checksums accompany the archive. Running
application services stop during capture and are resumed afterward. A shared host maintenance
lock serializes backup, restore and deployments. The installed backend image supplies the
PostgreSQL clients; the helper never invokes DbAdmin.

`make restore <archive>` and `make restore FILE=<archive>` validate before downtime, save
the current state, restore a temporary database, then replace database/data. Handled failures
attempt rollback while preserving the primary error, cleanup evidence and recovery archive.
Services stay stopped for application-version and separate `/data/files` rsync coordination.
The command requires database creation/rename privileges and the same PostgreSQL major.
Archives are private but not encrypted. Host failure and SIGKILL cannot provide an atomic
transaction spanning PostgreSQL and the filesystem; retained recovery evidence remains essential.

## Verification

Real PostgreSQL/Atlas tests cover incomplete backfills, failed contractions, schema changes
introduced by postprocessing, explicit unrepresented-object refusal and action prerequisites.
Backup tests exercise real database replacement, data/permission preservation, rsync exclusion,
unsafe archive rejection, restore failure, connection failure after commit and secondary cleanup
failure. `make tests-backup` additionally exercises public Make commands with real Docker.
`make tests-update` verifies source deployment in every application mode and the optional
qualified-bundle gates.

## Regression prevention

An earlier blanket `APP_ENV` gate incorrectly made source deployment unavailable outside
development mode. Tests had been changed to reject that valid workflow, so they preserved
the regression instead of detecting it. The Git update tests now exercise conventional and
arbitrary branch names, tags and detached HEAD with production-mode labels, preserving local
configuration. Source installation must not require enabling development behavior.
