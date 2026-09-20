<p align="right"><a href="../../fr/architecture/chat-validation.md">Français</a> · <strong>English</strong></p>

# Chat Validation

Status: `accepted-and-implemented`

Date: August 21, 2026

This validation describes the delivered contract; it replaces the implementation plan that has now been removed.

This document constitutes validations A and B required by the plan. The related contracts, models, and tests remain the source of truth when this document becomes outdated.

## Validation A — modules, facades, and security

`app.chat` owns the user API, private storage, native provider, assertions, room-authorized events, and WebRTC adaptation. It depends only on the public surfaces of `app.messenger`, `app.conversation`, and `app.voice`. The canonical domain `app.messenger` owns ORM reads and mutations and returns `NativeMessenger*` DTOs; no other domain imports the new module.

```text
front/app/chat
  -> API /chat + authorized room WebSocket
  -> app.chat
       -> app.messenger (journal, direct rooms, identities, files)
       -> app.conversation (redacted activity and transitive tree of related Tasks)
       -> app.voice (browser CallTransport)
```

The bootstrap declares the modules in `back/modules.py` and `front/modules.ts`, imports the provider before Messenger resolution, registers the WebSocket policy, and schedules storage reconciliation. The integrated `chat` Tool exposes no MCP tools, auto-connects every active agent, and never reactivates a disabled connection during a later synchronization.

Each route is protected by a global privilege. Routes carrying a room UUID add `ChatRoomAccessAssertion`; internal mutations retain `InternalRoomAccessAssertion`. Human identity comes from the session and the exact `messenger_users.galaris_user_id` match for each external Tool. Authorization parameter merging applies path parameters last, so a body or query cannot mask `room_id` or `file_id`. Services recheck membership under lock before mutations.

| Surface | Privilege | Resource policy |
|---|---|---|
| status, identities, rooms, and history | `CHAT_ACCESS` | SQL collection filtered by linked identity or exact membership |
| publishing and upload | `CHAT_SEND` | exact membership, agent still active |
| opening a 1-to-1 conversation | `CHAT_MANAGE` | active agent, user obtained from the session |
| calling and hanging up | `CHAT_CALL` | membership, correlated connection and call |
| downloading | `CHAT_ACCESS` | room + message carrying the file + file |
| related-task tree | `TASK_ACCESS` or `TASK_EDIT` | exact room membership |
| AI agent perspective | `CHAT_IMPERSONATE` | selected agent is an exact member of every room |

Absent/inaccessible resources return the same `404`. WebSocket emissions do not blindly target a shared room name: before each emission, `core.websocket` rechecks privilege and membership for each socket. The event is only a signal; the store catches up on durable state over HTTP and purges its contents on disconnection or access denial.

The text flow is idempotent by `(connection_id, client_message_id, direction)`. It first persists the canonical message and then admits a `ConversationRound`. For `platform=internal`, the conversation contract preserves the foreground round without its own Task, but exposes the same durable Task admission as Nextcloud Talk. A Task directive or a request classified as long-running work creates a related Task before confirmation; the controller also keeps Process tools available. The activity projection exposes a bounded and sanitized trace, and the related-Task tree is loaded separately under Task privilege; no system prompt or secret crosses these surfaces.

The file flow writes chunks to `.staging`, checks the limit, capacity, declared MIME type, extension, and active signatures, performs an atomic move, and then journals the file with the same UUID as the blob. The reconciler deletes old staging files and orphaned blobs after a grace period. The canonical URI is `chat://<room-locator>/<file-uuid>` and never contains a host path.

The voice flow creates a `BrowserCallTransport` WebRTC instance and then calls the public `app.voice` facade. This facade creates a call session in the current Chat room and voice rounds independent of Tasks. Successive calls therefore share the timeline without sharing their lifecycle. Conferencing and the SFU remain out of scope, in accordance with the plan.

Accepted caveats: the active-call registry is local to the backend process; a multi-replica deployment must use session affinity or evolve this registry before horizontal scaling. No caveat blocks delivery of the reference single-backend deployment.

## Validation B — mapping of existing data

No table is added and no visible content is duplicated. The nullable `messenger_users.galaris_user_id` column links a remote identity to a Galaris account; the uniqueness of `(tool_id, galaris_user_id)` guarantees a single current identity per Tool and account.

| Table | Columns and invariants used | Critical access |
|---|---|---|
| `tools` | `code='chat'`, `messenger_config.service='internal'` | uniqueness of `code` |
| `connections` | `tool_id`, `agent_id`, `active` | uniqueness of `(tool_id, agent_id)`, connection rechecked before admission/call |
| `messenger_rooms` | UUID, connection, external ID, label, direct kind, type, timestamps | uniqueness of `(connection_id, external_id)`, one user-agent pair |
| `messenger_users` | Tool, external ID, `agent_id`, `galaris_user_id`, `is_ai` | uniqueness of `(tool_id, external_id)` and `(tool_id, galaris_user_id)` |
| `messenger_room_users` | room/user, `role`, `joined_at`, `muted`, `last_read_message_id` | exactly the human owner and the agent for the internal UI |
| `messenger_messages` | room, sender, direction, external ID, response, status, dates | canonical idempotence and `(created_at,id)` pagination |
| `messenger_files` / `messenger_attachments` | UUID, connection, untrusted name, MIME, size, order | file accessible only through a message in the room |
| `conversation_rounds` and links | room, messages, status, redacted trace | activity filtered after HTTP membership check |
| `voice_sessions` | conversational room and lifecycle specific to each call | access by room and correlated call |
| `chat_emoji_usages` | user, emoji, count, and last use | uniqueness of `(user_id, emoji)`, cascading deletion with the account |

The historical schema extensions on `messenger_room_users` remain unchanged: `role` identifies the human owner of the direct room, `joined_at` preserves the audit trail, `muted` carries the personal preference, and `last_read_message_id` provides a stable unread cursor. Every `_id` suffix is a real FK, and deleting the read message resets the cursor to `NULL`.

The “My Profile” screen allows users to set or remove the mapping for each external Tool. Chat then displays only the rooms in which that identity is a member. External rooms are viewable, paginated in batches of 100 messages on scroll, and strictly read-only. The source badge distinguishes, in particular, Nextcloud Talk and Telegram. Technical Mail rooms are excluded from this projection: incoming emails remain journaled and are admitted as Tasks without creating a message-visible conversation. The `CHAT_IMPERSONATE` privilege exposes a separate selector for viewing the same projection from the canonical identity of an AI agent.

The emoji picker maintains a private, atomic ranking for each account by frequency and then recency. Its first 25 values form the highlighted “Frequently Used” category; this ranking depends neither on the current room nor on the browser used.

The API exposes no participant addition, removal, or departure. Any historical group rooms remain in the database but are excluded from the internal UI collections and assertions. Messages cannot be edited or deleted in this version. Blobs live under `/data/chat/attachments/<prefix>/<uuid-hex>` and their lifetime follows their canonical row.

PostgreSQL and `/data/chat` form a single coherent backup set. The operator procedure requires a write-free window, a database dump, and a volume copy at the same restore point. After restoration, the reconciler may remove a blob with no row but cannot reconstruct missing bytes: a database-only backup is invalid.
