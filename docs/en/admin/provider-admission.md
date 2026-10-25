<p align="right"><a href="../../fr/admin/provider-admission.md">Français</a> · <strong>English</strong></p>

# Regulate calls to AI providers

Under **Configure → Providers & models → Providers**, open a provider configuration
and set **Maximum concurrent calls**. This limit is shared by all its models, profiles,
agents and users. It applies to physical calls traced by Galaris, rather than the number
of open Tasks or conversations.

## Choose a limit

| Value | Effect |
|---|---|
| `0` | No concurrency cap imposed by Galaris; the provider's own limits still apply. |
| `1` | One physical call at a time for this connection. |
| Positive `N` | At most N simultaneous calls, with protected capacity for conversations. |

The default is **10** for a catalogue connection other than Ollama and **1** for
a custom or Ollama connection. A saved value, including zero, survives edits and upgrades. The field
accepts only a non-negative integer. Each connection has its own limit; two configurations
using the same remote account therefore do not share a Galaris cap.

Save and reopen the configuration to verify its value. Normal provider autosave rules
still apply; see the [configuration workflow](../user/navigation.md).

## Understand waiting and priorities

When capacity is full, requests wait before being sent to the provider. Voice conversations
take priority, followed by text conversations, then other work. Aging and rotation between
contexts limit queue monopolization. Priority does not preempt an already running call.

Live dialogue transcription gets voice priority as soon as audio arrives; file
transcription remains background work. A Task launched from a conversation also
remains background work. Each Task has its own rotation context, even when several
Tasks originate from the same round. A direct call without a Task uses its round
or, if absent, its agent run when known.
Other work uses its media generation, Process run or server-owned source when
available, then falls back to the agent or requester. Users sharing a profile are
therefore not grouped under that profile's name. This attribution changes neither
their priority nor their permissions.

With at least three places, one voice and one text place are protected. With two places,
background work uses at most one. With a single place, admission orders the next departure;
a slow call can still delay a conversation. Raising the limit does not guarantee better
throughput when the provider or machine is already saturated.

A streaming call keeps its place until finalization. Waiting for a tool, human response
or next turn does not reserve the provider's capacity for an entire run. Lowering the
limit lets active calls finish; raising it or setting zero can release waiting requests.
Other providers continue independently.

## Observe, interrupt and resume

Use **Supervise → Activity → LLM activity** and inference details to distinguish waiting
from execution time. Waiting alone consumes no model tokens. The physical timeout starts
when the call departs; an explicit global inference deadline also includes queueing,
pauses and resumes.

Pause and stop commands remove admissions that must no longer depart. Resume still checks
rights, provider activation and the durable inference policy. For an effect already
engaged, a missing response does not prove remote cancellation or authorize automatic replay.

An agent's **secondary profile** handles a different situation: it provides failover
when the primary provider fails under the supported conditions. It does not bypass an
ordinary capacity wait. Configure matching usages in both profiles; see the
[user guide](../user/README.md).

## Scope and verification

The current coordinator belongs to `app.llm.provider_scheduler` and assumes the supplied
single-worker backend. Independent backends would require distributed coordination.
Persistent audio sessions that are not traced as `LLMCall` are not counted as physical
Chat/Responses calls. Model discovery, credit reads and authentication are not generations.

The [scheduler tests](../../../back/app/llm/tests/test_provider_scheduler.py) cover concurrency,
priorities, protected capacity, cancellation, live configuration changes and provider
independence. The [accepted contract](../../../project/decisions/0181-provider-llm-admission.md)
describes other paths and qualification limits. [Provider parameters](../dev/provider-parameters.md)
and [usage readers](../dev/provider-quotas.md) remain separate contracts.
