# ADR 0175 — Same Messenger route for authorization and delivery

- Status: Accepted
- Date: 2026-10-11
- Supersedes: ADR 0011's refusal to select a default outgoing channel

## Problem

Messenger delivery resolved the Task's exact connection, while native authorization required
a single active Messenger connection without consulting that Task. An agent with internal Chat
and an external bridge could therefore have every Messenger call rejected before dispatch,
even when a Goal cycle carried an exact referrer connection. Existing routing tests invoked
the domain functions directly and did not exercise this authorization boundary.

## Decision

Resolve a concrete connection before native authorization and reuse that selection for dispatch.
The call receives a copy of its context; parallel calls never overwrite shared run resources.
The common MCP wrapper applies this to every driver, including runtimes that only provide a Task UUID.

An explicit channel wins. Otherwise preserve the Task's exact pin or the current conversation.
Without a fixed route, use the recipient's most recent inbound exchange with an exact identity
match. If no usable exchange exists, prefer internal Chat, then the oldest available connection.
Connection and function permissions remain authoritative. A fixed or explicit unavailable channel
fails without switching channels. Audio delivery requires a recent room on the selected connection.

## Verification

A synthetic integration scenario uses real MCP, authorization, the internal Messenger and PostgreSQL
with two active channels. It checks a Goal-style Task pin in its column or legacy data, default
internal delivery, both internal and Hermes MCP contexts, and refused sends without receipts.
The scenario fails before the correction. Journal and routing tests cover recent inbound selection,
strict explicit channels, immutable per-call contexts and reuse of the authorized connection.
