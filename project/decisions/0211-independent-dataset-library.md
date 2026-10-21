# 0211 — Independent Dataset folders with shared library visuals

Date: 2026-10-21

## Context

Datasets need the same personal tree and list interactions as Documents. Their existing
classification tables belong to Dataset, while importing the Memory frontend would create
a dependency cycle through Document applications that consume Datasets.

## Decision

Keep Dataset folders, placements, filters and mutations in `app.dataset`. Tree mutations
serialize per user; organizing readable JSON does not require content write access or alter
resource ownership, sharing or revisions. Branch deletion removes personal classifications
and preserves resources.

Share only visual infrastructure through `core.util`: icon rendering and catalogues, an icon
picker with injected persistence callbacks, splitter handles and keyboard shortcut dispatch.
Memory retains compatibility components and its existing icon persistence API. Dataset
uses its own folder API and stores selected icons in its own records. No frontend domain
imports the other library to obtain these visual primitives.

## Verification

Database tests cover personal isolation, filtered pagination, preserved JSON and permissions,
HTTP denials and concurrent cycle prevention. Browser tests exercise both libraries' icons,
menus and navigation; an assembled Dataset journey verifies persistent classification.
