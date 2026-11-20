# 0305 — Deep sessions own direct harness dialogue

The Messenger journal remains the source for user messages and final replies.
Conversation owns Deep mode, harness session bindings, input receipts and a
sequenced activity journal. A room lock linearizes toggles and selected session
changes. A Deep input bypasses normal conversation admission. Queued inputs are
claimed in journal order, with one active submission per session. Expired leases
preserve observed activity and record interruption without replaying effects.

An internal call inherits the active Deep session from its async context. A
managed inference gateway accepts session attribution only after authenticating
both the runtime principal and the session credential. The durable protocol
inference carries this identity to the worker. `LLMCall.deep_session_id` is a
foreign key and the originating room is projected from it. Session replacement
preserves that relationship for old calls. Provider calls outside Galaris have
no Galaris inference record.

Deep builds its transport input and system instructions from the current user
message and the agent's personality and job description. Capabilities and
authorization remain attached to the session. An adapter that needs to seed
history uses prior Deep turns. Once the native session is available, its
history provides continuity. A linked checkout adds its working directory to
the turn so the harness can use the Console there.

Managed effect authorization follows the existing service policy and uses a grant
issued for the Deep session. The scope proves that the assigned harness and live
room access are current. SDK processes retain their local sandbox. When the user
links an editable Code checkout, the harness receives the checked Console working
directory. Its local sandbox directory remains isolated from that Console checkout.

The private Chat reads activity at a persisted cursor. Runtime-specific parent
references let it group tools with the subagent that actually invoked them.
