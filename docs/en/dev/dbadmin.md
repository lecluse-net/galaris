<p align="right"><a href="../../fr/dev/dbadmin.md">Français</a> · <strong>English</strong></p>

# `core.dbadmin` — database evolution

This document describes the developer contract for `core.dbadmin`, Galaris's sole path for evolving the PostgreSQL `public` schema and permanent data. The
[contracts and tests](../../../back/core/dbadmin/) remain authoritative if this document diverges from the code.

## Principles

- Active SQLAlchemy models fully describe the target `public` schema.
- DbAdmin uses Atlas as a private implementation detail to converge the database toward that target.
- Galaris uses neither Alembic, numbered migrations, nor a linear version history.
- Each synchronization compares the current database with the target of the current branch.
- Special transformations are idempotent actions triggered by the current delta, not by an already-applied revision number.
- Datasets and reconcilers converge the data after the schema; they must not be duplicated in the FastAPI lifespan.

This architecture is intentionally **versionless**. Switching from one branch to another produces a new delta between the local database and the models on that branch, without imposing a global `v1 → v2 → v3` chain.

## Commands and environments

After modifying a model or permanent data during development:

```bash
make sync-db
```

This target is reserved for `APP_ENV=dev` and calls `python -m core.dbadmin synchronize` in the backend container. In production, do not call it separately: `make update` restarts the backend, whose entrypoint runs DbAdmin before Uvicorn.

The useful internal commands are:

```bash
python -m core.dbadmin synchronize --dry-run
python -m core.dbadmin status --latest
```

They must also be run in the container. The dry run displays the Atlas plan, but executes no actions, datasets, or reconcilers and does not persist a run.

## What DbAdmin compares

DbAdmin inspects the tables, columns, nullability, and ENUMs of the PostgreSQL `public` schema, then compares them with the SQLAlchemy metadata. The resulting `SchemaTransitionSet` exposes:

| Signal | Content |
|---|---|
| `added_tables` | tables present in the target but absent from the database |
| `removed_tables` | tables present in the database but absent from the target |
| `added_columns` | `table.column` keys added to an existing table |
| `removed_columns` | `table.column` keys removed from an existing table |
| `required_columns` | new or existing columns that must become `NOT NULL` |
| `enums` | ENUMs whose values or order differ |
| `definitions` | before/after definitions for types, defaults, indexes and foreign keys |

The `table_added()` and `column_added()` helpers cover the two most common cases. The other sets can be queried directly by an action predicate.

Index definitions also carry access method, expressions, observed ordering, included columns,
operator classes, storage options and `NULLS NOT DISTINCT`. Differences are observations,
not proof of a lossless conversion. CHECK/exclusion constraints and other constructs outside
this contract remain in the Atlas plan; no new automatic transformation depends on them.

## Synchronization lifecycle

A non-dry synchronization follows this order:

1. load the `<module>.dbadmin` contributions from active modules;
2. wait for PostgreSQL and acquire a global advisory lock;
3. inspect `public` and calculate the delta toward the canonical target once;
4. create the DbAdmin journal tables if necessary;
5. check unfinished actions and explicitly compatible successors, deferring incompatible optional actions;
6. execute `BEFORE_EXPAND` actions;
7. prepare ENUM changes;
8. apply with Atlas a target in which new required columns are temporarily nullable;
9. execute `AFTER_EXPAND` actions;
10. converge the datasets, then the reconcilers;
11. execute `AFTER_DATASET` actions;
12. make the columns whose backfill is complete `NOT NULL` and reapply the Atlas target;
13. execute `AFTER_CONTRACT` actions;
14. release the lock, calculate the verdict, and persist a bounded summary.

All phases receive the same `SchemaTransitionSet`, calculated before the first Atlas application. An `AFTER_EXPAND` action can react to a planned column removal while the source column is still available for data transfer.

### Action phases

| Phase | Timing | Typical use |
|---|---|---|
| `BEFORE_EXPAND` | before any Atlas intervention | preserve threatened data or prepare a transformation |
| `AFTER_EXPAND` | after the new structure is created | backfill or reinsert into the new model |
| `AFTER_DATASET` | after the datasets and reconcilers | use freshly converged permanent references |
| `AFTER_CONTRACT` | after the final Atlas pass | verify or clean up a transitional state |

The first Atlas pass prevents table and column drops and temporarily keeps the relevant required columns nullable. This does not make type conversions lossless: those still require an appropriate action. A failed indispensable pre-expansion action stops DDL. Deferred contributions preserve source data while allowing additions. Destructive contraction and `AFTER_CONTRACT` actions wait for preparation and required-column backfills to complete.

## Modifying the schema

For an ordinary evolution:

1. modify the SQLAlchemy model under `back/core`, `back/app`, or `back/bridge`;
2. verify that the module is active in `back/modules.py` and that its model is imported;
3. add an action only if existing data requires a special transformation;
4. run `make sync-db`;
5. inspect the result and test the modified contract.

Never:

- run Atlas directly;
- create an Alembic migration;
- execute `public` DDL during FastAPI startup;
- define an application table outside `public` in the `Base` metadata;
- keep a technical table in `public` that is absent from the SQLAlchemy target.

### New required column

A missing backfill is non-blocking: the new column remains nullable, an explicit error is logged, and the process exits with code zero (`STAGED`). The application can populate it, then the next synchronization applies `NOT NULL`. Failed contraction after usable expansion yields `DEGRADED`, also non-blocking. Failure to create indispensable objects remains fatal.

A new `NOT NULL` column without a server default is initially created nullable. An `AFTER_EXPAND` action fills existing rows. DbAdmin tightens the column only when no `NULL` value remains.

```python
from typing import cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminAction,
    DbAdminPhase,
    DbAdminRegistry,
    SchemaTransitionSet,
)


def _needs_backfill(transitions: SchemaTransitionSet) -> bool:
    return any(item.key == "widgets.owner_id" for item in transitions.required_columns)


async def _backfill(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    widgets = cast(Table, Widget.__table__)
    await session.execute(
        update(widgets)
        .where(widgets.c.owner_id.is_(None))
        .values(owner_id=widgets.c.created_by)
    )


async def _is_complete(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    widgets = cast(Table, Widget.__table__)
    missing = await session.scalar(
        select(func.count()).select_from(widgets).where(widgets.c.owner_id.is_(None))
    )
    return int(missing or 0) == 0


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.widget.backfill_owners",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1-created-by",
            predicate=_needs_backfill,
            handler=_backfill,
            postcondition=_is_complete,
        )
    )
```

The checksum is a stable developer fingerprint of the expected behavior. It is neither a migration number nor a global ordering.

### ENUM

Adding an ENUM value is automatic. Removing, renaming, or reordering values requires a complete `DbAdminEnumMapping` for each old value that does not remain valid. DbAdmin prepares the conversion before Atlas and rejects an incomplete destructive transformation.

## Conditional actions

A `DbAdminAction` declares:

| Field | Contract |
|---|---|
| `key` | stable global identity, generally prefixed by the module |
| `phase` | single execution phase |
| `checksum` | behavior identity as long as the action remains unfinished |
| `predicate` | pure decision based on the current delta |
| `handler` | async transformation receiving an `AsyncSession` |
| `postcondition` | async proof that the desired state has been reached |
| `required` | does an exception make the verdict fatal; true by default |

Before the handler, DbAdmin evaluates the postcondition. If it is already true, the action becomes `already_satisfied`. Otherwise, the handler and the second postcondition check run in the same transaction: success is validated by commit, and an exception is canceled by rollback. A crash after the commit but before the status is written can be recovered from through the postcondition on the next run.

The handler must therefore:

- be idempotent;
- process a bounded volume or use an explicit recovery strategy;
- never depend on the journaled status as a business source of truth;
- not write secrets to logs or errors;
- let the postcondition verify the actual state, not merely that the code ran;
- use only the public `core.dbadmin` surface, never `core.dbadmin._internal`.

An action belongs to a single phase. To bracket Atlas, register two distinct actions with their own keys and postconditions.

## Temporary backup and reinsertion

A complex transformation may require preserving the old representation before building the new one:

```text
BEFORE_EXPAND
  old structure
        ↓ idempotent copy
  galaris_migration.widget_backup

first Atlas application
        ↓
AFTER_EXPAND
  read the backup
        ↓ transformation
  write to the new public model

final Atlas pass
        ↓
AFTER_CONTRACT
  final validation or explicit cleanup
```

Two different sessions execute the actions before and after Atlas. A PostgreSQL `TEMP` table therefore cannot carry data between phases. A temporary table not declared in `public` would also be removed by Atlas.

For a durable backup between phases:

- use a schema outside the target, such as `galaris_migration`;
- create the table and copy the data idempotently;
- do not add it to the SQLAlchemy `Base` metadata, which accepts only `public`;
- define a key that allows resumption without duplicates;
- verify completeness and integrity in the postcondition;
- explicitly decide whether the backup is retained for auditing or deleted after validation.

The two actions can share a predicate based on the initial delta:

```python
def _moves_legacy_payload(transitions: SchemaTransitionSet) -> bool:
    return (
        "records.payload" in transitions.removed_columns
        and "records.document_id" in transitions.added_columns
    )
```

### Effective barriers and limits

An exception from a `required=True` action in `BEFORE_EXPAND` stops the pipeline before Atlas.
A postcondition that is still false produces a non-blocking deferred state: expansion can create
new objects while preserving source tables and columns. After expansion or datasets, an
indispensable failure prevents contraction; a non-fatal issue preserves sources and keeps the
usable schema operational. `AFTER_CONTRACT` waits for convergence.

These barriers and recovery are tested on PostgreSQL. They are not a global transaction:
a successful expansion remains applied if a later phase fails. Type changes can also lose data;
preventing table/column drops does not make those changes safe. Keep the old representation,
back up and backfill before removing it in a subsequent release for these transformations.

## Datasets, reconcilers, or actions?

| Need | Contract |
|---|---|
| permanent set of rows described by a natural key | `DbAdminDataset` |
| fully reconstructible derived projection | `DbAdminReconciler` |
| transformation conditioned on a schema change | `DbAdminAction` |
| table, column, index, or constraint change | SQLAlchemy model, applied by Atlas |

Datasets are ordered by `depends_on`. Reconcilers then run and may also depend on datasets or other reconcilers. Actions have no dependency graph: their primary order is their phase, then their sorted key in the registry. If two transformations must be atomically ordered within the same phase, combine them in a coherent handler instead of artificially relying on lexical sorting.

### Initial data subsequently owned by administrators

The `app.agent.initial_galaris` dataset proposes **Galaris** once, managed by the
first active administrator, using the internal Harness, the current default LLM
profile, an active `galaris_admin` connection (including documentation access), and an
individual authorization for the `galaris-lab` and `galaris-knowledge` skills. Their global defaults remain disabled.
If no administrator exists yet, the first signup replays the same dataset.
The internal `agents.initialization_key` marker survives renaming and soft deletion:
later synchronizations neither recreate the agent nor reset its settings or revoked
grants. Existing installations also receive this proposal. See
[decision 0135](../../../project/decisions/0135-default-galaris-agent.md).

The `app.skill.galaris_category` and `app.skill.galaris_category_assignments` datasets
create the **Galaris** category and assign uncategorized Galaris system skills to it.
Assignments use `update_only_null=True` to preserve custom classifications.
Global and individual authorizations are preserved; any existing Galaris category rules
apply to skills joining that category.

Agent titles (`titles`) are initialized with i18n keys `agent_titles.mr` (`M`) and
`agent_titles.ms` (`F`) in the existing `label` field by
`app.agent.initial_titles`, in the `AFTER_EXPAND` phase, only when the table is first created.
This is not a permanent dataset: `update_columns=()` would preserve values but recreate
deleted or renamed rows on later synchronizations. Subsequent starts and updates therefore
leave this reference data unchanged, even when all rows have been removed. Databases where
the table already exists are not seeded retroactively. PostgreSQL assigns the identifiers;
no title identifier is imposed.
The interface displays **Mr/Ms**, **Monsieur/Madame**, or **先生/女士** according to its locale.
Saving without changing the label preserves its key; renaming replaces it with literal text
displayed in every language. Translation belongs exclusively to the frontend; the backend
stores and exposes raw values.

## Journal, resumption, and branch changes

DbAdmin retains:

- a summary of each run in `dbadmin_runs`;
- up to one hundred bounded issues in `dbadmin_issues`;
- the latest state of each action in `dbadmin_actions`.

Action statuses are `running`, `deferred`, `failed`, `applied`, and `already_satisfied`. When an action is `running`, `deferred`, or `failed`:

- its code must remain registered;
- its checksum must not change;
- its postcondition must allow idempotent resumption.
- it remains applicable to subsequent synchronizations even when the initial schema delta has disappeared; the durable journal then carries the obligation until the postcondition is validated.

Removing or incompatibly changing an unfinished required action stops synchronization.
For an optional action, DbAdmin reports a non-blocking issue, preserves its old journal and
source data, and permits expansion without executing the incompatible handler. A successor
declares resumable old checksums in `compatible_checksums` and rechecks its postcondition.
`dbadmin_action_revisions` records the criticality of admitted behavior. For legacy journals,
the current declaration supplies criticality; a missing action of unknown criticality remains
blocking. Compatibility is an explicit guarantee about partially transformed data, never
permission to bypass destructive-transition checks. Completed actions may run again when
the current delta and postcondition require it, including after switching branches.

The PostgreSQL advisory lock prevents two concurrent DbAdmin synchronizations. Each action, dataset, and reconciler uses its own transaction; they do not form a global transaction with Atlas.

## Verdicts

| Verdict | Meaning |
|---|---|
| `converged` | no anomaly and no required column pending |
| `staged` | no anomaly, but a column remains nullable because backfill is incomplete |
| `degraded` | at least one non-fatal anomaly |
| `fatal` | at least one fatal anomaly; the command returns a nonzero code |

The verdict describes the final result of the run. A fatal verdict after expansion does not undo
successful intermediate changes; see the barriers and limits above.

## Testing and validation

An evolution must test at minimum:

- the predicate on an applicable and non-applicable `SchemaTransitionSet`;
- handler idempotence;
- the postcondition before and after the transformation;
- rollback in the event of an exception;
- the actual PostgreSQL scenario for any sensitive expansion/contraction;
- data preservation during a relevant round trip between schema states.

Then run:

```bash
make tests ARGS='core/dbadmin/tests app/<module>/tests/test_dbadmin.py'
make typecheck
make architecture-check
git diff --check
```

Backend tests always go through `make tests` and its ephemeral PostgreSQL database. Never run `pytest` in the development container.

## Code references

- [public contracts](../../../back/core/dbadmin/contracts.py) ;
- [action and reconciler registry](../../../back/core/dbadmin/registry.py) ;
- [delta calculation](../../../back/core/dbadmin/snapshot.py) ;
- [orchestrator](../../../back/core/dbadmin/orchestrator.py) ;
- [action execution and tracking](../../../back/core/dbadmin/actions.py) ;
- [datasets](../../../back/core/dbadmin/dataset.py) ;
- [adapted SQLAlchemy target](../../../back/core/dbadmin/_internal/target.py) ;
- [PostgreSQL tests](../../../back/core/dbadmin/tests/test_postgresql_transitions.py).

## Observed definitions

`SchemaTransitionSet.definitions` records observed before/after changes to column types,
server defaults, indexes and foreign keys. These are informational: textual SQL differences may
be representational and do not prove SQL-expression equivalence. They grant no new
conversion or deletion authority; Atlas and preservation barriers still own application.
Multimedia JSON checkpoints separately use a versioned schema; an unsupported future version
fails its own run, not global application startup.
