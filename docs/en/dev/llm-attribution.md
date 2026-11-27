<p align="right"><a href="../../fr/dev/llm-attribution.md">Français</a> · <strong>English</strong></p>

# LLM call attribution by user

`llm_calls.user_id` identifies the Galaris account charged for a physical call. It is a
nullable foreign key to `users.id`. Deleting the account clears the column.
`requester_user_id` retains its requester semantics for existing execution contracts.
Budget attribution grants no access to the call or its source.

The gateway sets attribution before the call starts, in the transaction that records the
trace. Read the table from top to bottom. Evidence from a higher row takes precedence over
the identity of a later operator or agent. Some sources, such as a shared round,
explicitly leave attribution empty.

| Provenance or available link | Account to charge and how incomplete evidence is handled |
|---|---|
| Lab campaign, candidates and judges | The account that created the Lab run. If an agent launched the evaluation from a task, the originating task is considered. An evaluation may use other users' data without charging them for the experiment. |
| Processes and subprocesses, including `process.exec` and activity tasks | Prefer the root run requester, then the current run requester. If both are missing, the task, round, or message may supply attribution. Automated runs without established human provenance stay empty. |
| Tasks, delegation, Dream task reflections, and Goal tracking | Prefer the root task requester. Follow `parent_id`, or `source_task_id` when there is no parent. With no root requester, use the first known requester starting from the task linked to the call. The requester of that task's Goal is the next fallback. |
| Deep conversation | The requester recorded on the Deep session. |
| Chat, messaging, voice responses, and conversational preparation including dispatch | The associated round requester, linked directly or through the task. A round can have several inputs. Galaris clears the round requester when those inputs have different identities. That round then leaves attribution empty. |
| Batch voice transcription before round creation | The requester of the voice session supplied to transcription. Sessions with no single identified human account stay unassigned. |
| Dream classification and contact discovery, or transcription of a messaging attachment | Follow the durable source. An inbound message supplies its `requester_user_id`, recorded from a linked account at admission. A message with no linked account stays unassigned. A mail `From` header alone supplies no proof. |
| Autonomous Dream or contact maintenance | If the receipt or discovery job points to a task, process, round, or message, apply the preceding rules. Memory maintenance, contact reconciliation, and automatic resource summaries without an identifiable requester stay unassigned. |
| Direct LLM API, personal dictation, one-off Lab operations, document analysis, images, audio summaries, and multimedia | With no higher-priority source, prefer the authenticated account, then the requester stored on the inference, the requester on the call, and finally the identity stored with a multimedia generation. |
| System work, removed source, or insufficient surviving provenance | Use `NULL` when no usable evidence is available. The agent's current manager and the resource owner are never used as fallbacks. |

Admission and the [DbAdmin action](dbadmin.md) share the same projection. Adding the column
triggers a batched backfill after any legacy cost transfer. The backfill covers archived
traces and preserves existing assignments. It uses surviving historical links, so older
voice or messaging transcriptions with no recorded source can remain unassigned.
A `correlation_ref` supplied by a standalone inference client provides no identity evidence.

For budgeting, group by `user_id` and the period of `started_at`. Count every `llm_calls.id`
once, including archived calls and attempts that incurred a cost before failing. `cost` tracks
the amount billed. `inference_cost` preserves the value of inference, including subscription use.
Reports should surface unknown costs and spending without attribution. Provider calls outside
`llm_calls` are outside this scope.
