<p align="right"><a href="../../fr/n8n/README.md">Français</a> · <strong>English</strong></p>

# Connect n8n to Galaris

Galaris treats n8n as an external process engine. It discovers workflows, triggers their webhook, stores each execution in PostgreSQL, and then retrieves its status through the public n8n API. The [`invoice_recording.json`](invoice_recording.json) file is a minimal importable template; it is not a production-ready accounting integration.

```text
Galaris Agent ──► Galaris process ──► n8n webhook
       ▲                                      │
       └──── result, status, and events ◄────┘
```

## 1. Configure both services

Create an API key in n8n, then open **Preferences → Processes → Connect n8n**.
Enter the **n8n URL** and **n8n API key**, then select **Test connection**.
The button saves changes before checking API access and listing workflows. It never starts
a workflow and does not validate webhooks, execution tracking or callbacks. **Save** also lets
you save without testing.

Calculated addresses appear below the two fields. Open **Advanced addresses and authentication**
to override them or generate a webhook secret. Copy the secret into the n8n Header Auth
credential before saving: saved secrets are never shown again. An empty secret field preserves
its value; its delete button requests removal when the form is saved.

The corresponding parameters are:

```text
PROCESS_ENGINE_DEFAULT=n8n
PROCESS_N8N_BASE_URL=https://n8n.example.net
PROCESS_N8N_API_TOKEN=<n8n API key>
PROCESS_N8N_WEBHOOK_BASE_URL=https://n8n.example.net
PROCESS_GALARIS_BASE_URL=https://galaris.example.net
PROCESS_N8N_WEBHOOK_AUTH_HEADER=X-Galaris-Webhook-Token
PROCESS_N8N_WEBHOOK_AUTH_TOKEN=<incoming n8n secret>
PROCESS_N8N_CALLBACK_AUTH_HEADER=X-Galaris-Callback-Token
```

`PROCESS_N8N_BASE_URL` must be reachable from the Galaris backend.
`PROCESS_N8N_WEBHOOK_BASE_URL` is optional: use it when the public webhook URL differs from the API URL. `PROCESS_GALARIS_BASE_URL` must be reachable from n8n if the workflow downloads a file or sends a callback.

Use **Open processes**, then synchronize the workflows in process administration. No restart is required. A Galaris definition then associates a workflow, a tool, and an agent; these three values are immutable after creation.

## 2. Import the template

In n8n:

1. import `invoice_recording.json`;
2. create a **Header Auth** credential whose name and value match `PROCESS_N8N_WEBHOOK_AUTH_HEADER` and `PROCESS_N8N_WEBHOOK_AUTH_TOKEN`;
3. assign this credential to the `Galaris Webhook` node;
4. replace `Record invoice` with the actual business operations;
5. keep the `Return execution ID` node and its immediate response;
6. activate the workflow, then run synchronization again in Galaris.

The template webhook responds in the following form:

```json
{ "executionId": "12345" }
```

Galaris also accepts `execution_id` or `id`. Without an identifier, startup is considered an unrecoverable failure because Galaris would not be able to track the remote run.

## 3. Input contract

The JSON body received by the webhook is the `input` object provided at launch. Galaris does not add a business envelope:

```json
{
  "invoice_number": "INV-2026-0042",
  "amount": 120.5
}
```

If the call contains files, a `files` property is added. Each entry provides, among other things, a name, MIME type, size, temporary URL, and expiration date. To download a file, reuse in the HTTP request the value of the incoming header named by `PROCESS_N8N_CALLBACK_AUTH_HEADER`.

Galaris also adds the following headers:

| Header | Purpose |
|---|---|
| `Idempotency-Key` | stable correlation for a retried delivery |
| `X-Galaris-Run-Id` | Galaris run UUID |
| `X-Galaris-Callback-Url` | optional event notification URL |
| `PROCESS_N8N_CALLBACK_AUTH_HEADER` | unique token limited to this run |

The name of the last header is configurable; its value must never be copied into a log or business result.

## 4. Mandatory idempotency

The outbox delivers starts **at least once**. A timeout may occur after n8n has accepted the webhook but before Galaris receives its response. The next attempt then carries the same `Idempotency-Key`.

Before any irreversible effect, the workflow must:

1. record this key in shared storage with a uniqueness constraint;
2. reuse the result of an already known execution;
3. create the invoice, payment, or message only after this check.

The template shows the contract, but idempotency storage depends on your business system. A static variable in an n8n worker is not sufficient when multiple workers or restarts are possible.

## 5. Result, tracking, and callback

Without a callback, Galaris periodically queries the execution through the n8n API. On success, it retains the first JSON object produced by the last executed node. Therefore, make the workflow end with a node that explicitly emits the useful result.

To reduce latency, a workflow can send an event to the URL received in `X-Galaris-Callback-Url`, using the incoming token in the configured header. Example body:

```json
{
  "event_id": "12345-completed",
  "status": "success",
  "engine_run_id": "12345",
  "event_type": "workflow.completed",
  "output": { "invoice_id": "INV-2026-0042" },
  "occurred_at": "2026-07-14T10:30:00Z"
}
```

`event_id` makes callbacks idempotent. Accepted statuses are `running`, `waiting`, `success`, `error`, and `cancelled`. For an error, send an `error` object containing at least `code` and `message`.

The old `/api/processus/...` route remains accepted as a deprecated alias, but all new integrations must use `/api/processes/...`.

## 6. Cancellation and limits

Galaris attempts `POST /api/v1/executions/{id}/stop`. Depending on the n8n version and configuration, this API may not be available. The interface then indicates that the remote execution may continue despite local cancellation. Design long-running steps so that they are interruptible and idempotent.

n8n snapshots are cleaned up and bounded before storage. Set their retention using the `PROCESS_RETENTION_*` variables, without retaining sensitive business data indefinitely.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| no workflows discovered | API URL, `X-N8N-API-KEY`, active workflow |
| “no webhook” | presence of a Webhook node with a non-empty path |
| 401/403 on startup | Header Auth credential and incoming secret |
| run without an identifier | immediate response containing `executionId` |
| duplicate business effect | durable, atomic storage of `Idempotency-Key` missing |
| stuck status | access to the execution API, callback, refresh interval |
| inaccessible file | `PROCESS_GALARIS_BASE_URL`, expiration, and run token |
| local cancellation only | stop endpoint unavailable in this n8n version |

The complete operational configuration is provided in the
[administrator guide](../admin/README.md#7-messageries-outils-et-processus). The
engine contract and contribution rules are provided in the
[developer guide](../dev/README.md).
