# ADR 0209 — Business object references in Documents

Date: 2026-10-20

Status: accepted

Documents cite Tasks, Goals, Topics, Messenger rooms, text rounds, voice sessions and
voice turns through the existing rich-content contribution contract. Each domain owns
canonicalization, title lookup, search, compact card construction and the authorized API
used by its detail view. The application composition root selects modal components;
core does not import domain implementations.

Task and Goal identities remain `galaris://task/<uuid>` and `galaris://goal/<uuid>`.
Text and voice turns retain `galaris://text/<uuid>` and `galaris://voice/<uuid>`.
Topics, rooms and voice sessions use `galaris://topic/<uuid>`, `galaris://room/<uuid>`
and `galaris://voice_session/<uuid>`. These additional identities are navigation
references, not declarations of file-provider support. Their exact UUID locators pass
both editorial HTML validators. Same-installation URLs normalize to these identities.

Cards are portable authored HTML snapshots. Task and exchange cards contain essential
list metadata, never a generated summary, objective, request, transcript or response.
Rendering does not poll the target or write a refreshed status into the Document.
The modal reads current data under the reader's own authorization. References do not
copy resources, create attachments or grant access. Topic details share one component
between their page and modal, preserving their tabs and related-resource actions.

Copy commands are available in source context menus and detail toolbars. The Document
picker has separate resource-browser and business-object tabs. Editor context actions
and toolbar actions switch links and cards without discarding authored surrounding text;
readers provide Open and Copy through a context menu. Existing Document navigation and
Process diagram behavior retain their contracts.
