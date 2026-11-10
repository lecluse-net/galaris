# Agent portrait resources

Status: accepted

## Context

The shared agent directory and `agent_get` already expose peer profiles without
dialogue or AgentAdmin delegation. The `galaris://agent/<id>` projection previously
allowed only the current agent, making directory references unusable for peers.
Photos were available through the human API, but had no canonical file resource.

## Decision

Expose the live photo at `galaris://agent/<id>/avatar`, owned by `app.agent` and
routed by `app.file_share`. Profiles, photos and the generic profile collection use
the existing shared-directory read policy: an active caller can read non-deleted
agents. Profile and photo reads share the same domain authorization check. This
does not grant communication, management or write rights.

Agent API JSON, `agent_list` and profile snapshots include `avatar_uri`, using
`null` when no photo exists; `agent_get` advertises the URI when present.
File metadata exposes the actual image type, size and content checksum.
Generic reads return bounded base64, while image tools and transfers use bounded
server-side materialization. Legacy stored image formats remain readable. The URI
is stable across replacement; deletion immediately makes it unavailable.

Keep photos in the existing Agent storage. Do not add a Document, duplicate binary,
public HTTP endpoint, persistent temporary path or database schema.

## Verification

`app/agent/tests/test_avatar_resources.py` covers peer discovery, profile and photo
reads, binary materialization, read-only enforcement, replacement, deletion and
denial for missing/deleted callers. Existing avatar and file-provider suites cover
normalization and other native resource behavior.
