# 0228 — Work discovery, guided first mission and memory continuity

Status: accepted, 2026-10-24.

Home retains unread conversations, usage indicators and Recent activity. A separate work
follow-up block would duplicate Recent activity and is omitted, along with its dedicated
Task projection. Waits, failures and recovery commands remain in Activity monitoring;
approvals remain in Permissions. The home summary concerns unread conversation messages
and does not imply that all Tasks are complete or accepted by a human.

Search remains in the individual resource screens. The application shell has no global
search page or shortcut. The guided first mission belongs to Welcome, without a Home shortcut.

Dream extraction can ENRICH an editable personal memory with complementary information,
or CONTRADICT an existing fact while preserving both sides. ENRICH records an ordinary
acquisition update with an explicit mode, expected revision and unchanged temporal scope.
The Memory service reads and retains the complete previous content and keywords before
adding the new information and source. Source-managed nodes and other agents' memories
cannot be enriched. Revision conflicts preserve the pending proposal for diagnosis and
require reconsideration; they do not silently overwrite current content. Existing
acquisition identities make partial application replayable. No schema change is required.
CREATE and LINK keep their existing behavior; this decision does not establish semantic
equivalence from embeddings or resolve conflicting evidence automatically.

After required configuration, Welcome offers editable synthetic first-mission examples.
An explicit user action creates a canonical Chat room and sends a Task request using the
normal admission path. A tab-local, per-user checkpoint retains the room and client message
identity before sending. Retrying an uncertain send reuses that identity. Progress uses
persisted conversation Task links and Document sources. Completion requires both successful
Tasks and an available associated Document; its editorial quality still requires review.
The journey grants no additional tools, resource access or action approvals.

The conversation Document listing and creation routes use Document privileges, matching
their frontend consumers. A route-metadata regression test first reproduced their legacy
Memory privilege requirement; the corrected contract preserves the room assertion and
resource ACLs. Guided mission preflight checks Chat creation/sending, Task reading and
Document reading before making any request.

Evidence: Dream acquisition and concurrency tests,
component journeys for session changes and uncertain-send replay, and an
assembled browser journey over the real API/database with the model boundary scripted.
Real-provider editorial quality remains a separate qualification.
