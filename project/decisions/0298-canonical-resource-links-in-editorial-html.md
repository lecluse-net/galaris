# 0298 — Canonical resource links in editorial HTML

Status: accepted. Date: 2026-11-16.

## Context

Editorial links used a closed list of schemes while File Sharing already exposed arbitrary
connected Service namespaces. An agent could read a source but could not cite it as a link.
Allowing a scheme alone was insufficient: the HTML sanitizer treated opaque Messenger
room locators as invalid browser hosts and silently removed their hrefs.

## Decision

Both editorial profiles accept canonical resource URI syntax independently of current
Service installation or availability. The dependency-free URI parser lives in `core.util`;
the existing `app.file_share.resource_uri` surface reexports its contract. Canonical native
file/document shapes remain validated. Business existence and provider-specific locators
are checked by their owning providers on access. Executable protocols and host filesystem
paths do not become resource links.

Validated provider hrefs pass through HTML sanitization using temporary, per-call Web
placeholders. Restoration happens before returning content; no placeholder is fetched or
persisted. The frontend preserves canonical hrefs during editing and serialization.

Specialized business views retain precedence. A fallback File Sharing contribution maps
other references to the existing Files browser, retaining the exact URI through initial
agent selection. The browser checks current source metadata before reopening cached
previews for every Service scheme. Caching bytes does not grant continued access.

This adds no transport endpoint, connection, ACL, copy, public URL or permission. A link
is a citation; archiving still requires an explicit copy. Unknown/unavailable providers
remain referencable and report their access failure when opened.
Converted document imports retain validated provider links through their own inert
sanitization pass. Markdown readers map canonical references through the same navigation
contributions; legacy Markdown editing keeps source URIs in its stored content.

## Verification and limits

Synthetic tests cover native and custom schemes, opaque Chat locators, encoded names,
normalization, unsafe protocols, editing and reopening, source denial and retry, agent
selection and revocation before cached preview reuse. Existing File Sharing HTTP tests
cover source-domain privileges, managed-agent scope and private-file isolation. Browser
interaction coverage uses isolated components with HTTP fixtures; it does not connect to
live third-party providers.
