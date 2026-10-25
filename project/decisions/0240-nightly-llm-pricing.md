# 0240 — Nightly provider-specific LLM pricing

Date: 2026-10-25
Status: accepted

## Guarantee

Configured model input, output and cache-read token prices track published prices
without repricing historical calls or erasing known values during upstream failures.

## Decision

`app.llm` registers maintenance in the existing scheduler. Each model defaults to
automatic pricing, with an explicit manual option in its edit dialog. The most recent
03:00 in the installation's `TZ` is the daily boundary. Persisted attempts permit
catch-up after downtime and retry after 30 minutes. Inactive providers, deleted
resources and voices are excluded. Local models without a published price retain
their configured prices.

The models.dev bridge supplies exact provider/model matches from a fresh catalog;
live provider discovery takes precedence per field. Prices are USD per million
tokens. Only finite nonnegative prices, including explicit zero, are applied.
Missing fields retain both their values and their per-field provenance. Unrelated
pricing units and model capabilities remain intact. Cache write pricing is distinct
and outside this three-rate synchronization contract.

Claims use short row locks and commit before HTTP. Durable attempt timestamps avoid
overlapping requests; revision checks reject responses after an administrator edits
the model or provider. HTTP deadlines bound work. Failed checks preserve the previous
verification date and expose an unavailable status without persisting provider errors
or credentials. Each imported rate records its source and verification date.

Historical call/ledger amounts and their frozen rates remain immutable under this
maintenance. Supplier-reported call charges still precede tariff estimates (0238).

## Verification and limits

Synthetic HTTP and PostgreSQL tests cover provider precedence, cache fallback,
missing/invalid prices, explicit zero, manual mode, cooldown, durable claims,
late responses, history preservation and timezone/DST boundaries. Component tests
cover changing and reopening the automatic-pricing preference on desktop and mobile.
An assembled application journey verifies persistence through the real API and a
page reload. Null, empty and boolean provider prices reproduced an existing parser
defect before correction: `value or 0` had silently declared missing prices free.
The HTTP/DB regression now protects this case alongside explicit zero. Previous
catalog scenarios did not exercise malformed or absent token-price values.

Freshness is that of the upstream catalog, not an invoice guarantee. Private
negotiated pricing must use manual mode. No supplier invoice or local hardware cost
is inferred. Existing models default to automatic pricing after schema convergence:
`make sync-db` in development and normal `make update` for deployment.
