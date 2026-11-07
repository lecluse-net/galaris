# 0268 — Isolate the identified Galaris assistant from peer requests

Status: accepted. Date: 2026-11-07.

## Decision

The internal `galaris.agent_id` parameter identifies the installed assistant, independently
of its mutable name and code. An ordinary agent named Galaris does not acquire its identity.
The existing parameter remains the identity after renaming or soft deletion; setup never
recreates the assistant merely because its original name is available.

Other agents cannot exchange messages or delegated Tasks with that assistant, in either
direction. The agent domain owns a shared rejection based on this identity. Messaging applies
it at its canonical contact boundary, including direct delivery, rooms and media. A shared
team, global contact scope or administrative Tool connection cannot override this prohibition.
The caller receives an explicit permission error mentioning Galaris.

Task admission checks the requester and the parent/source agents, even when the request
inherits an administrator's human identity. The scheduler rechecks before routing, execution
and planning, so historical queued peer work cannot bypass the new rule. Such an execution
refusal is terminal and non-retryable. Human requests and same-agent plan steps retain their
existing permissions; this decision does not introduce administrator-only human contact.

At initial creation only, the assistant receives active connections to native tools that do
not require a separately configured external account, including Topics, enabled native
functions and maximum management scopes. Console, Mail and Calendar still require their own
connection configuration. Function authorization does not remove resource ACLs, human-only
administrative delegation rules or model/provider prerequisites.

Updates preserve subsequent human changes to the assistant, its connections, function rules
and scopes. This is neither immutable superuser status nor an automatic elevation of an
already installed assistant.

## Verification

Synthetic PostgreSQL tests cover both contact directions with none/team/all scopes, shared
and separate teams, direct messages, rooms, media and invitations. Task tests cover native
MCP admission, service admission, inherited origins and historical scheduler phases, including
an administrator-owned caller and a renamed assistant. Ordinary same-named agents, human
requests and same-agent plan steps remain valid. Installation tests cover native function
permissions, maximum scopes, rollback, concurrent setup and preservation of later restrictions.
