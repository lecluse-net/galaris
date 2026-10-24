# 0226 — Link thumbnails are disposable previews

Status: accepted, 2026-10-24.

A Document attachment represents attached content. A thumbnail derived from a linked
page is a technical preview and must not create a Document attachment, file resource,
or content revision. The old implementation mixed both concepts and its regression
test explicitly required the unwanted attachment.

New web cards persist their text and public HTTPS source URL, marked with
`galaris-web-card`. Renderers load their images through an authenticated preview
endpoint backed by the existing shared WebP cache. The endpoint validates HTTPS and
agent scope; regeneration retains the existing public-network protections. Failed
previews leave usable text cards. Render-time images never enter saved HTML, while
print, PDF and ZIP snapshots embed available previews.

Existing cards and attachment URIs remain readable, including historical revisions.
This change does not delete existing files or rewrite saved Documents. New attached
images and other intentional attachments retain their existing behavior.

Coverage replaces the old attachment requirement with absence-of-attachment checks,
cache reuse and regeneration, authorization, and save/reopen/export browser journeys.
