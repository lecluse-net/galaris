# 0258 — Contextual resource identity in Memory recall

Status: accepted. Date: 2026-10-30.

## Context

Ordinary semantic ranking could omit the known correspondent's card for “my email”.
A short acknowledgement could replace the named subject of a follow-up, and canonical
resource URIs inside prose or beyond the concise query budget could disappear from recall.
All three defects reproduced against real SQL and the assembled Memory context provider.

## Decision

Memory query evidence version 14 treats explicit `memory://` and `document://` references
as identity anchors before candidate limits. Their spelling is preserved whole when bounding
context queries, including references in an explicit Task objective with a different label.
Up to five canonical UUID URIs fit the existing 240-character query budget. Recognition never
grants access or bypasses validity, source evidence or revision admission. Several requested
resources remain separate; an inaccessible reference cannot hide an authorized one.
Subresource URIs are not promoted to the identity of a parent Document.

First-person coordinate queries use the server-owned contact UUID, never a guessed name.
Candidate generation and ranking favor that actual private Contact card. Strict contact
scope admits that card for this query while retaining isolation of ordinary facts. Business
identifiers, another person's coordinates and address-book requests do not select the sender.

A simple coordinate lookup with no additional subject, and a standalone exact resource
identity, use an indexed scoped lookup. They skip embeddings and graph reranking but retain
final admission, conflict annotation and actual-use accounting. More complex questions and
broader semantic context keep the full hybrid path.

Conversational continuity skips standalone acknowledgements such as “oui” or “thanks” while
looking for the last human subject inside the existing bounded history window. Explicit topic
resets remain barriers; assistant, tool and system messages do not redefine the human subject.

## Verification and limits

Regression tests cover French/English, lexical outages, hybrid retrieval, short replies,
strict scope, long requests, multiple URIs, inaccessible sources and business identifiers.
A fixed synthetic qualification runs 51 queries in each of two modes against six Contact
cards, three Documents and 24 distracting notes. Uniform embeddings deliberately cannot
rescue an identity error. It reports top-one recall, reciprocal rank, leakage, SQL statement
count and latency; model/network latency is excluded. Passing this corpus establishes its
explicit guarantees, not infallibility for every natural-language question or homonym.
