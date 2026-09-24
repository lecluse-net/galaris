<p align="right"><a href="../../../fr/architecture/flows/messaging.md">Français</a> · <strong>English</strong></p>

# Messaging Flow

`app.messenger` is Galaris’s common language. Bridges own the external protocol,
not the business workflow.

Galaris exposes the native provider in `app.chat`, identified by the built-in `chat` Tool. It
reuses the canonical journal and rooms, without a network listener or secret. The user application
`/chat` is also the unified read-only view of rooms originating from external bridges. The former
local-loop `EmployeeMessenger` and its `galaris_messenger` Tool remain removed.

Chat can embed the full document component beside or below the conversation, with the
same permissions and saves as its dialog. Before sending a message, the client waits for
document saves and includes `displayed_document_id` only when that document has loaded
and remains displayed. Messenger stores its `document://<uuid>` reference in the message
metadata without changing the message text. Turn construction adds this context to the
prompt using only the newest incoming message, never treating an older message's displayed
document as current UI state. Closing the document or losing access removes the indication
from subsequent sends.
The Conversation Tool's `document_show(document=...)` requests opening a document in this same pane
(or the mobile viewer). It accepts a UUID, a `document://` URI or a Galaris URL of the form
`/memory/documents?document_id=...`. Availability requires an active Conversation connection, Conversation
enabled for conversations and a text round in the agent's own internal room. The tool catalog
and prompt share this filter; execution rechecks permissions, document access and round freshness.
The `chat.document_show` event contains only the room and document IDs, changes no sharing grants
and is not a read receipt. The client ignores other rooms and saves current edits before opening;
the document API still enforces viewer access. The action lives in `app.conversation.mcp` with
`task_enabled=False`: all Tasks, including those launched from Chat, and voice exclude this tool.
Memory provides document authorization through its adapter registered at bootstrap; its connection
is not required. The integrated datasets initialize the Conversation Tool (`conversation`) and
its connections as enabled, then preserve administrator-owned activation settings.
This descriptive context must not trigger automatic attachment redelivery; editing
requests still go through the conversation controller.

Each “new conversation” action creates a distinct internal room, including when the user chooses an
agent with whom they already have a thread. The label reuses the agent’s name, then adds `(2)`,
`(3)`, etc. under its connection lock so that two concurrent creations cannot receive the same
name.

For an authorized internal room, the scheduler publishes a `started` event over WebSocket before
calling the controller, followed by an ordered projection of the `AIMessage`s and finally
`finished`. Visible text is grouped into small batches to feed a temporary bubble without creating
one canonical message per delta. Trace types and tool calls are displayed in this bubble. Tool
WebSocket events contain their name, content, success, duration, cost, and bounded structured data.
The technical `thinking` block also carries the reflection content provided by the runtime. This
projection is limited to the authorized room and removes sensitive keys and common credential
forms before emission; system prompts and secrets never cross it. The confirmed response remains
the only durable Messenger message. An HTTP projection attached to the output message then allows
the same cleaned `AIResult` (reflections, tools, bounded parameters and results, final response,
duration, cost, and error) to be expanded in its bubble. The system prompt remains absent. The
`chat.message` signal for this response is published only after the link between the round and the
message is committed. Until that commit, a journal marker also prevents concurrent HTTP reads from
exposing this message. The frontend retains the live `AIResult` until this complete durable
projection has been rendered, then performs an atomic replacement: the two representations are
never displayed together, and no empty frame separates them.

When ingesting a human message, Messenger also freezes the `requester_user_id` derived from
`MessengerUser.galaris_user_id`. Admitted rounds and Tasks propagate this snapshot. A personal
ChatGPT subscription can be used only when this identifier matches its owner; an identity not
associated in “My Profile” remains refused, including in single-user mode. A later directory
change does not alter the authority of historical messages. The `chat.message` event carries
`is_new=true` for a new durable entry and `is_new=false` for a simple update, such as a Topic
correction. The interface rings its chime only for a new message that is neither personal, nor
attached to a muted room, nor observed in impersonation mode.

Unread status is a durable, ordered Messenger state. Each journal entry carries a monotonic
position, its canonical author, and an indicator distinguishing live events from passive history
imports. The user’s membership retains the highest position actually seen. The interface advances
this cursor only for a bubble intersecting a sufficient portion of the conversation area when the
page, window, and mobile panel are visible. The global total is reconciled over HTTP and projected
in navigation and in the application badge.

Listening for new messages belongs to the authenticated shell and therefore remains active outside
the Chat page. Without an active Push subscription, it produces a fallback Quasar notification
after rechecking that the message is still unread, non-personal, and unmuted. With Web Push, the
backend creates a durable delivery per subscription and per message. After a short grace period, it
rechecks the same conditions: a bubble displayed in the meantime or a connected tab that still
renders this room cancels the delivery. The page publishes this visible presence separately from
its simple event subscription and removes it when hidden, when the mobile details panel replaces
the conversation, or when it is unmounted. Subscription endpoints and keys are encrypted at rest;
404/410 responses disable the device, and transient errors are retried with backoff. The PWA
service worker then receives the push even when the application is stopped, displays a system
notification respecting the preview preference, and opens `/chat?room=<uuid>` on click. This path
requires HTTPS, explicit browser authorization, and VAPID keys configured on the instance.

When an agent author has an active TTS voice, each of its text bubbles also exposes a playback
action next to “Reply.” A human bubble never exposes this action. Capabilities are resolved from
the `agent_id`s of authors actually referenced by canonical messages, never from the room
members’ current projection. The API verifies exact access to the room and message, also refuses
any author who is not a linked Galaris agent, prepares the text with the same cleaning as the Voice
pipeline, then streams the synthesized MP3 using the author’s voice without persisting it in the
Messenger journal.

HTTP also provides recovery of round states after reconnection.

The Messenger right pane projects only Tasks directly linked to the room’s rounds, followed by all
their transitive descendants. The recursive projection follows the `parent_id` hierarchy and
`source_task_id` causality: a delegation to another agent therefore remains visible, along with
all of its descendants, with no depth limit and no agent filter. The `/chat/rooms/{room_id}/tasks`
endpoint requires both exact access to the room and an ordinary Task privilege. The pane consumes
the canonical `task.create/update/delete/restore/cleanup` WebSocket events, then reconciles the tree
over HTTP after each event batch and each reconnection. The `TaskDetail` view opens in a local
modal within Messenger so as not to leave the conversation. No Messenger-specific tracking state
is persisted. The API returns Tasks from newest to oldest in pages of ten; the pane loads the first
chunk, then adds ten earlier Tasks when scrolling reaches the top.

This projection follows the message window actually loaded by the interface: the client sends the
identifier of the oldest displayed message, and the Tasks, working documents, and Process
endpoints retain only rounds that touch the corresponding chronological slice. Progressive loading
of a portion of history moves this boundary backward and extends all three lists; an old room
therefore does not immediately expose all of its work history. Documents group the `document://`
references from messages, successful tool traces, and active Working Sets from projected Tasks.
Their content and modification continue to go through the ACLs and optimistic revisions of
`app.memory`. Processes group runs linked directly to visible rounds and those attached to the
corresponding Task tree.

Document and Process lists also follow a newest-first order and load older items while scrolling,
in chunks of ten, without any visible pagination control.

For external bridges, a user sees a room only if the remote identity associated with their account
in “My Profile” is a member of it. This mapping also enriches the contact projection in memory.
With `CHAT_IMPERSONATE`, the same screen can take the perspective of an AI agent and then filters
rooms by its exact canonical membership; writing remains disabled. The displayed name and
visibility of the last-message preview are preferences local to the canonical member: they
therefore also apply to external rooms without modifying or losing the name supplied by the bridge.
Hiding the preview does not prevent opening authorized history. The room avatar remains that of the
agent owning its connection, regardless of the custom name, and new-message notifications retain
their normal behavior.

The Chat list hides rooms originating from external messaging and archived rooms by default. A
menu provides two independent toggles to include them in the search. Archiving is a local
preference of the canonical member and remains reversible from the conversation dialog; it does
not alter the room or its visibility for other members. Rooms remain paginated server-side, but
the interface loads the next page at the bottom of the scroll and displays no pagination controls.

Nextcloud Talk history is synchronized on demand in chunks. Opening a room and returning to the
bottom of the thread import the most recent remote chunk. The response provides an opaque cursor;
when the user reaches the top, the frontend sends it back to import one older chunk, then retains
the next cursor. Canonical journaling makes these overlaps idempotent, so scrolling does not depend
on a prior global import.

When the bridge declares the `UNREAD` capability, the Chat list additionally requests counters
from the provider, once per connection and per page load. The result supplements the canonical
counter without ever reducing it: the provider observes the bridge’s count, whose perspective may
differ from that of the Galaris user. A room is marked read only after the last durable message has
been rendered in a genuinely visible conversation; the marker sends the exact provider identifier
of that message. A hidden tab, the mobile details panel, or impersonation mode never changes read
status. If the provider is unavailable, the local canonical cursor remains the fallback, and its
failure does not prevent display.

Each Messenger room may carry an optional persistent Topic. A message’s effective Topic is resolved
in the following order: explicit message override, room default Topic, then the message’s
historical or Dream classification. The canonical column distinguishing an explicit override
prevents a later room change from overwriting choices made with `@topic`. Conversely, messages
without an override immediately reflect the room’s new Topic, without rewriting their durable
journal. In the absence of a room Topic, historical classification retains its behavior.

When the effective profile selects a Decision model, authorized incoming text messages also
start topic classification alongside admission. This uses Dream's existing mechanism and
receipt without waiting for idle maintenance; Dream skips applied results and recovers failures.
Manual and room topics keep priority, and a late result from an older input cannot replace a
newer input's topic. The harness and memory tools read an available late topic without waiting
for the model or replaying a completed search.
See [ADR 0130](../../../../project/decisions/0130-live-message-topic-decisions.md).

Creating an internal conversation atomically persists the recipient agent, its label, its optional
Topic, and the owner’s preference indicating whether the last message may be displayed in the
list. Older clients that provide only the agent retain the numbered label derived from it and
preview enabled. Choosing a Topic at creation requires the same `TOPIC_EDIT` privilege as a later
modification.

The internal Messenger opens the override selector for the next message with `@topic`. The
selector becomes empty again after each successful send. An explicit override exempts that message
from Dream classification. The round and every Task it launches receive the effective Topic of
the last human triggering message. The agent response copies the Topic provenance of that message:
it therefore remains aligned during streaming, after persistence, and after a room Topic change,
while retaining any explicit override.

From a bubble’s audit view, a user with `TOPIC_EDIT` can manually correct the Topic of that single
message or of that message and all chronologically subsequent messages in the same room that still
carry its original Topic. Earlier messages and messages assigned to another Topic are not modified.
This correction acts on canonical messages and remains distinct from the round’s historical Topic.
In the absence of a corresponding Dream decision, it appears as a manual assignment in the audit.

## Active Bridges

| Bridge | Primary reception | Adaptation |
|---|---|---|
| OneBot | Reverse-push WebSocket | OneBot v11 payload to private observation, then persisted `Message` |
| Matrix | Sync loop; voice events on the same stream | Matrix client to canonical message, media, or call |
| Nextcloud Talk | Polling or signaling | Talk conversation to canonical message/call |
| Telegram | Long polling | Bot API update to canonical message |
| WhatsApp | Webhook push | Graph API to canonical message and delivery statuses |
| Mail | IMAP polling | Incoming UID to canonical journal, then direct reading Task |
| Internal | Galaris API + WebSocket per room | Native human message to foreground round; long work to linked Task |

The native provider retains the technical kind `internal`, while its public Tool is `chat`.
Its attachment URIs therefore use the `chat://` scheme.

The exact list of parameters, capabilities, and incoming modes comes from each `BridgeSpec`
registered in the bridge package.
The same contract also declares `identity_param`, the remote-account key that links an observed
identity to its agent’s `Connection`. Messenger then applies the Tool’s `param_map` before
searching: Nextcloud thus uses its `login`, while Matrix and OneBot use `user_id`. This resolution
takes place during ingestion and when hydrating old rows, so Chat, avatars, and TTS all consume
the same canonical `agent_id`.

All these bridges may be active for the same agent. Messenger is an optional capability of a
`Tool`, at the same level as MCP and File Share. `messenger_config.service` selects the bridge,
`settings` carries server values common to all connections of that Tool, and `param_map` links the
bridge contract to the connection parameters specific to the agent. Tool code never implicitly
selects a bridge.

Per-connection parameters are `login`/`password` for Nextcloud Talk,
`user_id`/`token`/`password` for Matrix (token and password individually optional),
`token` for Telegram, `access_token`/`phone_number_id` for WhatsApp, and `user_id`/`token` for
OneBot. The required Tool settings are respectively `base_url`, `homeserver`, none,
`app_secret`/`verify_token`, and `platform`.

Each messaging Tool directly declares this contract. `MESSENGER_DRIVER` configures the service of
the generic `messenger` Tool when it is enabled; bridge-specific Tools declare their service
explicitly.

`MESSENGER_ENABLED_CHANNELS` is the global availability indicator. It contains a duplicate-free
subset of supported kinds and equals the full list on a new installation. A bridge removed from
this list retains its settings and connections, but disappears from messaging searches, tools, and
connections. Its MCP aliases, webhooks, WebSockets, text/voice listeners, and active calls are
stopped or refused. It remains visible only in preferences, where its tab allows it to be
reactivated. A non-messaging function provided by the same tool, such as WebDAV for Nextcloud,
remains available independently.

## Canonical Reception

```text
external transport
  → authentication and validation in bridge.*
  → conversion to app.messenger.models.Message
  → app.messenger.inbound.dispatch_incoming
  → durable journal + recent deduplication
  → message_received signal
  → app.messenger.service
  → private projection of the human contact into Memory
  → human with exact connection + room: app.conversation
  → AI identity or incomplete legacy entry: existing collaboration/Task
```

The durable key for a message is `(connection_id, remote_message_id, direction)`. The connection
is part of the identity because one Tool may represent multiple accounts. A duplicate webhook
already `admitted` is acknowledged according to the protocol but does not retrigger business
processing.

Before any interaction, round, or Task, canonical admission applies a permanent rule to instant
messaging bridges: a message more than one hour old is marked `admitted` with the audited
`dream_only` disposition, remains visible in the journal and eligible for Dream mechanisms, but
does not trigger a Conversation or Task run. This rule also applies to crash recovery and complete
history imports. Mail is explicitly exempt because its asynchronous contract is
`inbound_admission="task"`.

A Task resulting directly from an admission additionally retains the canonical message UUID in a
unique column. Journal status is therefore never the sole barrier: a redelivery after a crash
between Task creation and the `admitted` acknowledgment finds the same Task and cannot duplicate
the business effect. Conversation admission has the same guarantee through the durable unique link
from the message to its round.

During cutover from the old journal, DbAdmin closes historical entries that remain at `received`
before listeners start. It also quarantines still-active Tasks and rounds whose creation is more
than one hour later than the canonical timestamp of the entry: because admission is synchronous,
this gap proves historical readmission. Already-terminal results remain intact for auditing.

Human admission is part of the durable receipt: an exception after journaling marks the message
`failed`, and a redelivery resumes admission until the round is actually created. The Nextcloud
listener advances its room cursor only after this admission; on restart, it replays its bounded
recent history, deduplicated by the canonical journal.

### Human Conversation Admission

A human entry with an exact connection and room is admitted directly from the canonical Messenger
`Message`. The lock applies to its internal `Room`, and the message is linked to a frozen
`ConversationRound` for that room. In a group, all authors share the same room but remain
identified on their own message. The `app.conversation` scheduler is independent of the Task
scheduler: a room runs only one round at a time, while different rooms may progress in parallel.

The latest unprocessed message is the round’s LIFO anchor. All unconsumed incoming messages are
linked to the round, then rendered chronologically. A new message arriving before the first effect
supersedes the round without consuming its entries; they are regrouped into its successor. After a
durable effect, the old free-form response is deleted and the new message forms the next round.
Each input link receives `consumed_at` when it is definitively consumed. Old mailboxes, entries, and
outbox are no longer written; they remain temporarily present to drain and control data from before
the switchover before Atlas removes them.

The short controller is always internal and uses text level `low` in the agent’s sole effective
profile. There is no fallback to the executor or to another profile. It does not depend on the
executor driver and consumes no Task slot. Long work creates a linked Task that uses the ordinary
scheduler and driver; a Process is launched without waiting. The conversational link projects the
Task’s successful result after termination. Its permanent failure returns through a localized
message exposing the persisted cause after common secrets are masked. This sending and terminal
Process results use a notification state carried directly by the Task or Process link; no agent
driver implicitly publishes its terminal text. In the event of a transport error after potential
dispatch, delivery becomes `UNKNOWN` and is not blindly replayed.

Its dedicated prompt preserves the agent’s persona—identity, personality, position, and job
description—but replaces long-execution rules with a rapid-response policy. It receives the exact
projection of native conversational functions as well as the identifiers, labels, and descriptions
of assigned Processes. It responds directly after a few short calls, launches the corresponding
Process if the need is already modeled, or otherwise creates an autonomous Task; it never blocks
the conversation while waiting for their result.

For a human sender, the short dispatcher returns `EXEC standard` directly, without a model,
on every text channel. The executor retains the choice to admit a Process or Task. The controller
delivers a successful result without checking admission afterward or judging its wording.
It passes execution errors to the scheduler, which retains its bounded retry and protections
against repeated effects. A terminal error produces the fallback response with its category and
details after masking common secret forms. The admitted Task retains the agent, room, and
ordinary driver; Hermes can execute it without participating in the internal conversation controller.

Before admission, the controller strictly distinguishes an amendment from new work. An amendment
retains the same artifact or primary target and substantially identical success criteria. A
different target, repository, resource, deliverable, or independently verifiable result receives a
new Task, even if the request stems from the same incident. The URI of an amended Task remains
unique, but the round exposes its `TaskAmendment` as an audit lineage. When an amendment interrupts
an execution, the new dispatcher and new briefing see the merged objective; the checkpoint retains
only its anti-replay effects journal and abandons the old provider history. A result or checkpoint
bearing the fingerprint of a previous objective is refused before terminal persistence. The
scheduler then closes the old attempt as canceled, without consuming a retry or recording an error
on the revised Task.

Recent context exposes a bounded number of active Tasks and resources. Generic run labels are not
used as the subject for memory recall: the request is built from the current human message and its
structured identity.

The recent session is reconstructed from the canonical Messenger journal and retains, for each
entry, the internal UUIDs of the message, room, and files, the external identifiers, sender, and
attachments. Each file remains nested within its message and carries the reference
`<tool.code>://<room-locator-provider>/<file-uuid-local>`; a message with no text containing only a
file remains a complete chronological entry. This same projection is frozen in every Task admitted
from the round: a planner or driver therefore receives the complete authorized Messenger history,
not only the latest text. An explicit request to attach a version already present is resolved by
attachment UUID before the dispatcher, then the existing bytes are copied to the room. It creates
no Task, and the admission service refuses any attempt to turn it into a new generation.

When a human message admitted into a conversation carries one or more audio files, Messenger
resolves the effective profile’s text level `low` before creating the round. If this model does not
declare `input_audio` and a usable `transcription_llm_id` is configured, each file is transcribed
immediately. Transcriptions are retained in the message metadata and added to its text only in
projections intended for models, including the history of subsequent turns. Visible text and the
audio’s canonical URI remain unchanged. An audio-capable conversational model does not trigger
this automatic STT; missing or failed STT remains fail-open and never prevents message admission.

The registry is part of the execution context. A text round is presented as the continuation of a
chat, never as an email: it does not repeat a greeting, a courtesy paraphrase, or a signature in
every message. A voice turn is presented as the continuation of a call whose initial greeting is
handled separately: it adapts its length to the request and moment while maintaining natural
spoken phrasing, does not reread the transcription, and concludes with a goodbye only when the
caller actually ends the conversation.

Senders recognized as AI agents retain the Task collaboration workflow. A human entry without an
exact reply address temporarily remains on the legacy path to avoid silent loss.

Mail declares a transport-specific `task` admission policy: each newly journaled email immediately
creates a Task that receives its `mail_get` reference, without passing through the short
conversational controller. This exception remains owned by `app.messenger`; the IMAP bridge never
creates a Task itself. The terminal result is not implicitly returned over SMTP, because every
response must remain an explicit and idempotent effect of a `mail_*` tool.

Technical rooms created for these emails remain in the canonical journal but are excluded from the
Chat projection, including in an agent’s view, so that an IMAP stream does not create a message
conversation visible in Chat.

The sender is observed as a Memory contact with its normalized address and any MIME name. After a
confirmed SMTP send, recipients are observed through the same public surface. Each account retains
its own source item; a future Dream reconciliation may add links but cannot merge these identities.

The **Execution Tracking → Text Conversations** supervision view reads these durable projections
through `/conversations/messages`. Each received human message produces a paginated row, with the
corresponding round response in the same cell, on a second truncated line. Counters follow this
order: updated, pending, and in-progress conversations, then conversations that encountered an
error. The last counter filters messages covered by an `ERROR_RESOLVED` round, regardless of the
state of the other rounds in their room.

When a round aggregates multiple messages, each retains its own row and references the shared
response. A click loads only that round through `/conversations/rounds/{id}` and opens a modal with
the complete aggregated block, response, and associated `/llm-calls` calls. A failed round displays
the fallback response sent, its status and error, and the driver’s partial trace for each attempt.

The two modals have a shared action bar. The routes
`/conversations/rounds/{id}/dataset` and `/voice/conversations/turns/{id}/dataset` expose the same
complete dataset as administrative inspection for copying as JSON. Deletion is restricted to
`TASK_EDIT` and accepts the round regardless of its state. It locks the round, immediately
cancels its local worker if one exists, then deletes the durable row; a worker on another instance
then loses its lease and interrupts its action at the next heartbeat. It removes the run from
history without deleting canonical Messenger messages. Already-created Tasks and ProcessRuns are
not deleted. `LLMCall`s remain in the global journal after their conversational key is detached;
those still `running` are closed as `cancelled`, with their counters, costs, and partial outputs
intact.

The unique identifier of a text or voice processing is `ConversationRound.id`. The modals display
this primary UUID and copy it to the clipboard when clicked. The optional `galaris_admin` MCP
package, inactive by default, exposes `conversation_round_get`. Each function still requires an
active connection at call time and returns all data persisted directly for that turn, as well as
all correlated LLM calls. A voice turn does not contain audio bytes, which are not persisted in
this conversation dataset.

The same bar allows sending a turn to an AI Lab benchmark if the user has `EVALUATION_EDIT`. The
action always requests the target dataset, even when only one dataset exists; if none exists, the
user may create one before copying. A text round may feed only the **Conversational Executor**,
and a voice turn only the **Voice Executor**. The case receives a working copy of the input and
output, together with a standalone source snapshot containing all evidence persisted at transfer
time. The benchmark never replays the turn, and its fake tools produce no real Task or Process.

Phone calls are the parent rows of their turns, permanently displayed as subtasks and without an
accordion. Only a turn row is clickable; its modal contains only that turn, its transcription,
response, and LLM calls. The voice page loads the turns for the calls on the current page in one
grouped backend request. All traces remain linked by `conversation_round_id`.

The supervision projection is paginated from canonical incoming messages. The API bounds requested
pages so that a room containing thousands of messages cannot produce an uncontrolled read. Export,
Lab transfer, and deletion actions remain explicit administrative operations; they do not
intervene in admission or scheduler leases.

Nextcloud is a unified bridge: `bridge.nextcloud` registers both the Talk adapter with
`app.messenger` and the WebDAV transport with `app.file_share`. A single Tool may enable MCP, File
Share, and Messenger. The two bridge capabilities nevertheless remain independent: each has its
own service selector, URL, and `param_map`. A connection can therefore use two Nextcloud servers
or two different parameter pairs for files and messaging.

The journal retains text, identities, conversation, bounded attachment metadata, canonical date,
and status. `messenger_files` normalizes this metadata with an internal UUID, never storing bytes
or extracted content: these remain in the originating messaging system and are downloaded on
demand. Listener cursors and health are also persisted per connection.
`messenger_room_history` traverses history in pages, from newest to oldest. Each page remains
chronological and provides an opaque cursor to pass to the next call. Matrix and Nextcloud use the
native history cursor to reach messages predating the Galaris journal as well; Telegram, WhatsApp,
and OneBot paginate the durable journal, as their protocols do not all provide arbitrary,
portable remote history.

After server-side resolution of the connection and actual kind, Messenger enriches the current
sender with the AI identity directory. A non-empty human sender is projected through Memory’s
public facade before resolving an interaction or creating a Task. A human response consumed by a
choice therefore also creates a profile. Writing is fail-open: its failure is logged without a
native identifier or content and never changes conversational processing.

A response that unambiguously designates a number, identifier, label, or alias of a pending
interaction remains deterministically resolved before the conversational controller. If the text
does not match any option, it is neither lost nor forced into a choice: it becomes a normal round.
The round then receives the bounded projection of interactions still active for the exact
connection, Tool, room, agent, and sender. The conversational LLM may call
`conversation_choice_resolve` with the reference and identifier of a persisted option, or ask a
question if the intent remains ambiguous. The command relocks the same scope, refuses any invented
option, and returns resolution to the original idempotent handler. A redirection can therefore
refuse an approval that has become obsolete and then amend the relevant Task in the same round.

Internal Chat also projects choice messages as structured titles, bodies, options and durable
states, without domain metadata or processing tokens. Buttons are reserved for the human
recipient and retain the selected option after reloading. The answer command checks the room,
connection, Tool, agent and recipient, then calls the deterministic resolver directly, without
a round or LLM. Submitting the same choice twice is idempotent; a different or expired choice is
rejected. Capturing a button answer also journals a human message containing the selected label,
question and reference. It belongs to the history supplied to agents and to the canonical contact,
without creating a round or Task. The message and decision commit together before the handler;
retrying that handler does not duplicate the answer, even after a processing failure.
State changes invalidate the message in other views, including after a textual reply.
Canonical numbered text remains unchanged for external messengers; free-text-only interactions
continue to use the ordinary composer.

The social address is `(messaging_id, user_id)`, where `messaging_id` here is the bridge’s
canonical code and `user_id` the exact, case-sensitive native identifier. The connection, room,
and message are transport data and are not part of this identity. Memory adds only
`owner_agent_id` to its technical key to isolate the private memories of two agents. Two
connections of the same agent and bridge therefore converge on one profile, while two agents
remain distinct. Two channels converge automatically only when they carry the same proven
`galaris_user_id`. Administration may also explicitly merge two contacts belonging to the same
agent: the addresses then become durable aliases of the retained contact, and future observations
do not recreate the duplicate. This merge repoints sealed memories, Topic/contact scopes, memory
edges, messages, rounds, and Tasks in one transaction before forgetting the old projection.

Administration may also explicitly forget a contact. Memories sealed to that contact are forgotten
along with their revisions and resources, references from messages, rounds, and Tasks are cleared,
and then the projection and its identities are purged. A new interaction with the same address
creates a new contact and does not reactivate any forgotten data.

`messenger_users` is the canonical repository of observable remote identities. A row is internally
identified by UUID and remains unique by `(tool_id, external_id)`; it retains the display name
provided by the remote system and its history. Its nullable `agent_id` may explicitly link it to a
Galaris agent; multiple remote identities may designate the same agent. The `is_ai` Boolean, false
by default, explicitly qualifies an automated identity without requiring that it already be linked
to an agent. A constraint guarantees that a non-null `agent_id` always implies `is_ai = true`,
without imposing the converse for external AI agents.

Two identities belonging to different Tools remain two Messenger rows, even when they designate the
same person. Their association with a shared Memory contact is a proven Galaris identity or an
explicit administrative decision; name similarity is never sufficient.

`messenger_rooms` similarly constitutes the room repository by `(connection_id, external_id)`.
The current `messenger_room_users` table links local room and user UUIDs; it is not itself
historized. The disappearance of an association is applied only when a bridge has provided the
complete participant list for that room.

The Messenger facade synchronizes all remote data before exposing it to the rest of Galaris. Room
lists, directories, incoming histories, and send responses are inserted or refreshed
idempotently, then rebuilt from local rows. Local UUIDs are carried by `local_id`; remote
identifiers remain necessary for bridges but are not used as Galaris primary keys.

An accepted outgoing response must carry a non-empty remote reference before its canonical
reconstruction. Nextcloud’s file-sharing OCS endpoint does not directly expose the identifier of
the Talk message it creates: the bridge therefore rereads recent history using the random, unique
DAV name, then returns the actually observed message and attachments. If propagation is delayed,
it logs a unique share reference rather than an empty identifier that would collide with all
previous uploads. An error after remote acceptance remains `UNKNOWN` and never authorizes a blind
retry; provider history is used to confirm the effect and then create the delivery receipt.

A remote absence is proof of deletion only in an explicitly exhaustive snapshot. By default,
bridges declare their lists non-authoritative. A search filter, incomplete pagination, a room
loaded without all participants, or a window of the last N messages can therefore never
historize what was not returned. When a bridge instead certifies a complete snapshot, absent rooms
or users receive `deleted_at` set to the observation date and `deleted_by = NULL`; they no longer
appear in current reads. A later observation of the same remote key restores the existing row
rather than creating a duplicate.

The journal allows missed observations to be repaired. `make rebuild-messenger-contacts` rereads
the latest incoming senders from each connection in batches, resolves the Tool, durable kind, and
AI identity again, then calls the same projector as the runtime. The journal’s historical
`platform` field is never authoritative. Deleting a connection does not delete a profile already
known: the technical route is not the source of the human identity.

Matrix reloads its `next_batch` from this durable state. The first `/sync` is handled like the
subsequent ones, and its new cursor is recorded only after the batch has been fully admitted into
the canonical journal. A stop before recording replays the batch from the old cursor; the durable
message constraint and call-event deduplication then prevent a second emission. This boundary
acknowledges admission to the journal, not yet successful business processing by all consumers:
generic journal → Task recovery and its dead-letter queue remain a separate effort.

The Matrix bridge optionally filters rooms, senders, and mentions. Automatic invitation acceptance
is disabled by default, requires an allowlist, and refuses rooms announced as encrypted.
Automated notices, edits, and echoes from the bot account do not enter the Task workflow. Replies
retain `m.in_reply_to`; images, documents, videos, and audio remain canonical `File`s downloaded
on demand. Because the bridge does not handle Megolm, any send to an encrypted room fails before
transfer instead of emitting plaintext content.

## Session Projection

Before an agentic execution, `app.messenger.session` reconstructs a view bounded by
`(connection_id, room_id)`. It reads the durable journal in canonical order, excludes the message
that triggers the Task and every later line, then applies two configurable limits: message count
and character count. Before this read, the connection is verified as belonging to the agent; a
foreign or invalid reference produces no history. The cursor, scope, and truncation indicator
accompany the snapshot.

Upon admission, `app.conversation` persists this bounded historical projection in
`Task.messages`, followed by the triggering message or messages. Plan children inherit the same
snapshot and cursor. When the journal contains the corresponding lines, it remains the
authoritative source for reconstructing the projection at the same position; `Task.messages`
serves as an inspectable trace and fallback if the journal is empty or no longer available. This
rule prevents duplicates, prohibits future-message injection, and allows changing drivers without
losing the conversation. The shared context provider then gives both drivers the same authorized
turns. For a human Task whose contact is proven, this projection follows the canonical contact
across rooms and connections and excludes every other participant. It feeds a frozen capsule with
the same contact’s Tasks, resources, and memories; Dream’s late Topic is not consulted. Without a
proven contact, no collective room history is injected.

The complete scope and journal cursor remain in server metadata. The context rendered to the model
exposes the platform and room useful to tools, never the connection identifier or internal scope.
For Hermes, this scope produces two distinct values: a condensed, stable logical key for
`X-Hermes-Session-Key`, then an opaque transcript ID that follows compaction rotations. An
external room ID is never used as a new transcript ID.

## Canonical Sending

1. The facade resolves the connection and constructs the Messenger registered for its `kind`.
2. The domain verifies the requested `Capability`.
3. The facade resolves the persisted `Message`, `Room`, `MessengerUser`, and `File` models, then
   the bridge converts their private observations to the external protocol.
4. The response is journaled with its remote identifier.
5. Delivery receipts may only advance `accepted → sent → delivered → read`; a late notification
   never regresses the status.

An optional undeclared operation raises `NotSupported`; it is not simulated by a successful
response.

### Response from a Legacy Task

A Messenger Task persists an exact address:

```text
Task.messenger_connection_id + Task.message_platform + Task.message_group_id
```

The connection is the source of truth, the platform serves as a consistency check, and the room
remains opaque. Plan children, waits, interactions, Goals, and drivers inherit this address. Two
rooms named `42` on two connections therefore share neither session, await, nor response guard. The
connection remains server data and is never added to the context block visible to the model.

This address provides the runtime with the context for attachments, interactions, and Messenger
tools, but does not trigger any automatic terminal send. A direct legacy Messenger Task without a
`ConversationTaskLink` can respond in the room only by explicitly executing a Messenger tool. The
Internal, direct Hermes, and Hermes Kanban drivers all return their `ExecutionResult` without
calling the transport themselves.

A Task created by `app.conversation` also retains this address and its complete Messenger
contract. Conversation and Task are two modes of the same agentic identity: its planner and
interactions directly publish the initial planning notice, questions, and authorizations. Enabling
each step does not publish a `Step x/y` message: durable progress remains viewable on the Task
without polluting the conversation. The terminal result is guaranteed by the conversational link,
independently of the Harness: after `SUCCESS`, it is sent if the trace does not prove that this
same result has already been delivered by Messenger; after `ERROR`, an alert is sent. A successful
explicit delivery of the same result marks the notification `SKIPPED`, while a separate progress
message does not suppress it. Processes launched by a round use the same durable notification
principle without copying their content into an outbox. For a Task, claiming requires a released
lease and a final terminal attempt; it therefore ignores automatic retries and cancellations. An
ambiguous delivery becomes `UNKNOWN` and is not replayed. A human retry carries a higher attempt
number and re-arms the terminal projection.

OneBot namespaces its rooms as `group:<id>` and `direct:<id>` before entering this contract. Old
unprefixed IDs continue to be interpreted as groups to allow their delivery, but every new event or
direct send explicitly retains its kind. The upgrade prefixes old persisted groups in Tasks, the
journal, interactions, and Hermes bindings; it does not attempt to invent a private room absent
from old events.

### Search and New Message to a User

Messenger search traverses all active connections of available bridges that expose the
`SEARCH_USERS` capability. Each remote directory is queried, results are synchronized into
`messenger_users`, and the response is rebuilt from this repository. Each result separately
retains `user_id`, `messaging_id` (the exact connection), `tool_id`, and the platform. Two identical
identifiers on two connections remain two distinct routes, even if their local row is shared at
the Tool level. This historical API field `messaging_id: int` is a route selector equivalent to
`connection_id`; it must not be confused with the `messaging_id: str` of the projected social
address, which is the bridge code.

A filtered search enriches the repository but never removes a row: absences are out of scope, not
deletions. An unfiltered search becomes authoritative only if the bridge certifies that its
response actually covers its entire directory. Synchronization creates neither cross-channel
matching nor a preferred channel; only observation of an incoming human message feeds the Memory
projection. Protocols without a queryable directory, such as Telegram Bot or WhatsApp Cloud,
produce no result until a dedicated technical cache is defined.

For a new send, the Task’s exact connection is used when one exists. Outside that context, or to
change platforms, the caller explicitly provides the channel obtained through search. A missing,
ambiguous, or incapable channel fails without cross-channel fallback. Messages, files, and voice
notes follow the same rule; no exchange history implicitly selects a platform.

## Media and Voice

Attachment metadata remains canonical, while bytes are retrieved on demand. Bridges capable of
streaming override file methods to avoid loading everything into memory. A native voice note goes
through the bounded normalization described in [Media and Resources](media-resources.md).

Matrix uses v3 media upload, authenticated Client-Server API download, and a compatibility fallback
for older homeservers. `mxc://` URIs, announced sizes, and transferred bytes are validated; voice
notes are sent as OGG/Opus in the form `m.audio`.

A real-time call carries `connection_id + kind + room_id` to a durable
`VoiceConversationSession`. When launched from a canonical conversation, the session reuses its
`messenger_room`: successive calls each have their own lifecycle but continue the same visible
timeline and context. A transport without a known canonical room retains a dedicated audio room.
The initial greeting, each speaking turn, and each agent message are journaled separately in
`messenger_messages`. An audio commit without a transcription retains an incoming message with
empty text rather than making the intervention disappear. Agent-stream fragments continue feeding
speech synthesis immediately, but are concatenated into a single response `Message`: a token or
word delta is never a conversational boundary. Conversely, multiple explicitly distinct responses
retain their order through `response_sequence` and `sequence`.

For browser transport, the API provides the client and `aiortc` with the same ICE relay and the
same temporary identifiers. In integrated mode without an explicit URL, their locators differ: the
browser receives the name derived from `APP_HOST` and the detected LAN IPv4, while `aiortc` joins
the same coturn through `host.docker.internal`. The browser can therefore bypass internal DNS, an
application proxy, or a hairpin NAT that would make the nominal locator unsuitable for TURN. In an
environment treated as production, this list must contain an authenticated TURN relay. Like a
native mobile client, the browser immediately sends its offer and then transmits ICE candidates
to the backend, up to the end-of-gathering marker. Pending candidates are grouped into ordered
batches of at most 50, including those received during an in-flight request, so a burst of routes
does not exhaust the HTTP quota. The API also accepts older single-candidate requests with the
same permission and call-scope checks. Signaling failures are reported without automatically
hanging up: WebRTC state determines closure, including when another route already works.
Late TURN candidates are therefore
no longer lost behind the first local candidate, and the PWA does not block call creation while
waiting for complete gathering. The dedicated
`compose.turn.yaml`
provides coturn by default in
`embedded` mode, but its presence is not part of the application contract: `external` mode
excludes it and uses the URLs and REST secret of an existing TURN server. In integrated mode,
allocations are tied to the single LAN IPv4 published by the router and never to a Docker bridge
interface; the public relay candidate replaces this IPv4 with the detected public address. The
SDP response also retains a relay alias for the LAN IPv4 resolved at startup: local clients
therefore do not depend on the router’s UDP hairpin NAT, while remote clients always use the public
candidate. In both cases, the backend derives a time-limited TURN REST identifier for each user.
Before recording the call, it verifies that its SDP response actually contains a `relay`
candidate, and fails explicitly otherwise. Hanging up first closes the local tracks and peer,
then notifies the server registry through an idempotent operation: a mobile network loss therefore
cannot keep the microphone open or leave the interface blocked.

The browser transport checks permissions before starting, then monitors them in an independent
coroutine, one second after each check. Incoming and outgoing frames do not wait for these
database queries. Each check has a one-second deadline: denial, failure, or timeout closes the
call and clears queued audio, even without speech activity. Hanging up also stops the monitor.

After removing a call from the active registry, Voice publishes its termination to the canonical
Chat room when one exists. The client then refreshes the call’s authoritative state so that the
header action immediately becomes available again, including when the agent hangs up.

The short greeting (“hello?” in French) is emitted only after actual receipt of the first remote
PCM frame. The transport must never invite the caller to speak while its incoming subscriber is
still negotiating: as soon as the greeting is audible, listening is already operational.

Each validated transcript creates a `ConversationRound` and an `AgentRunRequest(task_id=None)`:
a spoken intervention is therefore not a Task and does not appear as an error when the user
resumes speaking. `conversation_round_messages` links the round to its input and output messages;
its two FKs cascade, without placing a conversational FK in the Messenger model.
`conversation_round_id` correlates the agent run and its LLM calls without attaching them to a
concurrent agent task.

A technical error that ends the call is persisted on the session, including when it occurs before
the first speaking turn. The supervision projection exposes it in the conversation details so the
modal can display the useful provider message without depending on logs.

An agent configured in `realtime` mode replaces this split with a persistent audio session. Each
VAD commit still creates a `ConversationRound`, without inventing a transcript or textual
objective: the audio is interpreted directly by the provider model. The room’s recent history is
projected as an unreliable conversational transcript at the start of each new call. Core memory
is injected at startup, `memory_search` completes context on demand, and `task_submit` creates a
durable Task through the agent port.

After the conversation, Dream may progressively extract durable facts from completed turns that
have a textual `effective_objective`. This extraction is never on the Voice path. It associates
each retained memory with the hashed structural node of the conversation, without storing the
connection or room in Memory. Audio realtime turns without a transcript are not guessed:
memorization occurs through an explicit call to the Memory tool. Creation of all these links is
deterministic and involves no inference.

The agent exposes a single voice choice. A synthesis resource, particularly ElevenLabs, enables
the STT → agent → TTS pipeline. A native voice discovered for an STS model directly enables the
associated provider audio session; it is not registered as an additional LLM. The messaging or
call bridge knows neither OpenAI nor ElevenLabs: it continues only to transport canonical PCM.

Barge-in moves the turn to `INTERRUPTED` and retains its `effective_objective` in the session.
The following transcript is concatenated with this pending objective before the new run. A
complete response consumes the whole set; successive interruptions accumulate it without
duplicating raw messages in the history provided to the model. `source_turn_id` and
`resolved_by_turn_id` make this resumption causally inspectable.

The direct voice engine retains pre-roll before confirming the beginning of speech. Its size
is bounded by PCM duration, independently of the transport's frame sizes. Continuous
speech may be split into bounded audio blocks, but these blocks remain one turn: only silence,
stream stoppage, or its end validate the transcript and trigger the response. A technical
interruption must therefore neither restart barge-in nor remove the beginning of the message.

When the selected resource exposes native streaming, each incoming frame feeds STT exactly once,
including before local speech confirmation and below the detector threshold. Local VAD decides only
the manual commit point; it never filters the stream sent to the transcriber. The detected PCM
turn remains available for a batch fallback if the real-time session fails. The agent starts only
after this commit so that a transcript correction never reexecutes a side-effecting tool.

The agent output is already a delta stream. For an ElevenLabs voice, speakable segments are sent
over a single TTS WebSocket using the low-latency model and raw 24 kHz PCM resampled on the fly to
the transport’s 48 kHz; frames are played without waiting for a complete MP3 file to be generated.
Other providers, or a failure before the first frame, retain the existing encoded TTS path.
Barge-in cancels inference, synthesis, and still-pending frames in both cases through the same
generation number. An explicit hang-up request arms a graceful end on the voice domain side, even
if the model does not call `voice_call_stop`. The current turn finishes producing its response,
then the engine waits for application and WebRTC queues to drain before leaving the transport; a
service shutdown or administrative stop instead retains immediate cancellation.
`voice_call_stop` also remains a mandatory control for both voice runtimes: the conversational
pipeline targets it with the room and connection from server context, and the realtime surface
arms it without an argument supplied by the model. After it succeeds, realtime allows one last
brief response, waits for audio to drain, and then actually leaves the transport.
A call has no application-level maximum duration: it remains active until a participant hangs up,
a `voice_call_stop` request is made, or the service owning the session stops.

Choice scope combines the canonical room UUID with the participant's external identifier,
connection, Tool and agent. Dream approvals follow the same contract: an unambiguous numeric
answer applies the choice without a conversation round or LLM call. DbAdmin repairs pending
classification requests whose recipient was an internal UUID only when the source message proves
the same identity and scope, without capturing a decision. Chat sends its UI language with text
and attachment messages; the journal preserves it for admission and recovery. Dream proposals use
the source round's language, then the message language, and finally the instance default.

Only human inputs in a round can trigger a `topic_id` choice.
Text and audio replies inherit the last input's topic without any LLM call, even when their
content appears to change the subject. When the topic is unknown, outputs remain unclassified
until classification or the human transcript arrives and synchronizes them.
The Lab detector applies the same free inheritance; a greeting without a known topic produces `null`.
The canonical journal collector retains at most ten room messages, including voice transcripts,
without inventing remote timestamps during backfill. A proposed new Topic
blocks the remainder of this stream until human resolution, but only for the approval’s validity
period. An expired `PENDING` interaction remains in the audit and can no longer immobilize the
room or its message backlog; a `PROCESSING` interaction remains blocking until its idempotent
handler resumes.

In Dream rotation, classification of a claimable message always precedes classification of a Task.
This precedence does not reorder the other mechanisms among themselves and ends as soon as the
message collector finds no claimable subject.

A Task launched by a round immediately receives that round’s Topic and contact. The creation tool
rereads the persisted scope at effect time to cover concurrent classification. If classification
of the message or Voice turn completes only after creation, applying it updates the derived Task
in the same pass; no additional Dream turn is reserved for Task inheritance.

The exact remote identity observed at entry is projected into a Memory contact and then copied onto
the message, round, and derived Tasks. Voice transports populate this identity only when they prove
a single remote participant. Multiple participants or an absent identity leave the contact null
and disable memory capture for the turn, without heuristic cross-platform matching.

## Where to Intervene

- Common contract: `back/app/messenger/interface.py`, `models.py`, `facade.py`.
- Reception: `inbound.py`, `journal.py`, `service.py`.
- Observed contacts and replay: `contact_memory.py`.
- Shared session: `session.py` and `tests/test_session.py`.
- User search and outbound routing: `service.py`, `mcp.py`, `router.py`.
- Adaptation: `back/bridge/<transport>/`.
- Attachment transfer: `back/app/file_share/messenger_transport.py`.
- Canonical file reference: `<tool.code>://<room-locator-provider>/<attachment-uuid-local>`,
  resolved by `app.file_share` with connection, room, and agent checks. Messenger remains a Tool
  capability and owns no dedicated schema.

Test the canonical contract and protocol fixtures separately. A new transport must converge on
`dispatch_incoming` and register with a `BridgeSpec`.
