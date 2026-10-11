<p align="right"><a href="../../fr/dev/process-engines.md">Français</a> · <strong>English</strong></p>

# Integrating an external process engine

This guide describes the current extension points for connecting third-party software to
`app.process` to run durable business workflows, such as validating and registering an invoice.
It does not install an additional engine. Repository Python contracts and tests remain
authoritative; the limitations below are part of the current integration.

## 1. Choose the integration path

| Need | Path |
|---|---|
| Call software from an existing n8n workflow | Follow the [n8n guide](../n8n/README.md); no new Galaris engine is required. |
| Connect an external business workflow engine directly | Add a `bridge.<software>` implementing `ProcessEngine`. |
| Return an immediate result without durable business tracking | Expose an MCP tool in the relevant domain or bridge. |
| Perform a technical operation already owned by a domain | Keep its state in that domain; duration alone does not justify a Process. |

The definition represents a business workflow, even if the external service exposes it as
a single job. Standalone conversion, media generation and Lab evaluation retain their state
in their owning domains. Durable integration requires recovering a workflow's outcome after
interruption, through remote reads or replayable notifications.
A lost HTTP response does not prove that processing never started.

## 2. Responsibilities and identities

`app.process` owns definitions, runs, events, start jobs, transitions, Task waits and
retention. The bridge owns external protocol translation, remote authentication,
business validation and result normalization.
It must not create a second canonical state or mutate Process tables directly.

| Identifier | Current contract |
|---|---|
| `engine.code` / `Tool.code` | The same stable code, such as `example`; the registry selects that engine. |
| `engine_process_id` / `workflow_id` | External operation; `workflow_id` is its public name in launch calls and URIs. |
| `ProcessDefinition.id` | Internal SQL identifier used by administrative CRUD. |
| `run.id` | Canonical Galaris execution UUID. |
| `run.engine_run_id` | External reference, unique per engine among recorded runs. |
| `run.correlation_id` | Stable delivery identity, passed to the software to deduplicate its effects. |
| `run.callback_token` | Per-run secret for callbacks and downloads; never a business result. |

The database enforces uniqueness of active definitions by `(tool_id, engine_process_id)`.
However, personal calls resolve `workflow_id` within the agent's scope without an
engine argument. Choose distinct public identifiers across engines, preferably with a
prefix, to avoid ambiguous resolution. An active definition has a single `agent_id`
assignment, which can be empty; an agent cannot launch an unassigned definition.

Sources: [engine contract](../../../back/app/process/engine.py),
[schemas](../../../back/app/process/schemas.py),
[models](../../../back/app/process/models.py) and
[durable flow](../architecture/flows/process.md).

## 3. Implement the contract

A `ProcessEngine` declares `code`, `supports_cancel` and `cancel_mode`
(`supported`, `best_effort` or `unsupported`), followed by these asynchronous methods:

| Method | Input / output | Responsibility |
|---|---|---|
| `health()` | `ProcessEngineHealth` | Check access and authentication without starting work; describe actual cancellation support. |
| `sync_definitions()` | List of `EngineProcessDefinition` | Return discovered business workflows or a static catalogue with identifier, label, description and active status. |
| `start_run(operation, run, payload)` | `EngineStartResult` | Submit validated input and files, returning acceptance and a recoverable reference. |
| `get_run(run)` | `EngineRunSnapshot` | Observe the exact job; normalize status, output, errors and useful diagnostics. |
| `cancel_run(run)` | `EngineRunSnapshot` | Request a stop; distinguish a pending request from confirmed termination. |

`ProcessStartPayload` contains `input`, `files` and `launch_snapshot`.
The latter is a Galaris checkpoint, not an envelope to forward wholesale to the software:
it can contain internal authorization metadata.
`EngineRunReference` only supplies the UUID, external reference, correlation and token.
The bridge builds its transport from server configuration.

Output is a JSON object, optionally containing result URIs.
`EngineError` carries `code`, `message` and optional `node_name`.
`raw` is a bounded diagnostic sanitized before storage; never copy tokens,
sensitive HTTP bodies or binary files into it. Error codes must remain stable.

The optional `IntegratedProcessEngine` contract adds `prepare_input(agent_id,
workflow_id, input_data)`, `start_timeout_seconds` and `refresh_timeout_seconds`.
It is neither specific to n8n nor required for an external bridge.
Implementing it also changes deduplication and deferred authorization handling;
do not implement it solely to change a timeout. Ordinary engines use
`PROCESS_START_TIMEOUT_SECONDS` and `PROCESS_REFRESH_TIMEOUT_SECONDS`.

## 4. Minimal example independent of n8n

The fictional workflow validates an invoice, produces its PDF and registers it. These steps belong to the remote service; the adapter translates its overall state.

The following example implements an adapter for a **fictional service**. Its routes
are not Galaris endpoints or a standard protocol third-party software must implement:

| Fictional service route | Expected response |
|---|---|
| `GET /health` | HTTP 2xx without business effects. |
| `POST /jobs` | Accepts `operation`, `input`, `files`, `callback`; atomically deduplicates `Idempotency-Key` and returns the same job. |
| `GET /jobs/{reference}` | Returns the job, including after a restart. |
| `POST /jobs/{reference}/cancel` | Idempotently requests a stop and returns the observed state. |

A job is an object such as `{"external_id": "job-42", "operation": "invoice-intake",
"state": "processing"}`. Success can add
`"output": {"result_uri": "https://processor.example/results/report.pdf"}`.
That URI must be durable and readable with the required permissions; a remote disk
path is not a Galaris resource. To publish into a Galaris provider, use
`app.file_share` with its authorized context.

Place the adapter in `back/bridge/example/engine.py`. The imports are current public
exports; `Any` is restricted to dynamic business JSON. Integrate this example's
configuration and messages into settings and i18n catalogues before shipping a bridge.
The `transport` argument supports checks with `httpx.MockTransport` without
contacting a real service.

```python
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.process import (
    EngineError, EngineProcessDefinition, EngineRunReference,
    EngineRunSnapshot, EngineStartResult, ProcessEngineError,
    ProcessEngineHealth, ProcessStartPayload,
)
from app.process.schemas import ProcessStatus


class InvoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["pdf"]


class RemoteJob(BaseModel):
    external_id: str = Field(min_length=1)
    operation: Literal["invoice-intake"]
    state: str
    output: dict[str, Any] | None = None


class ExampleProcessEngine:
    code = "example"
    supports_cancel = True
    cancel_mode = "supported"

    def __init__(
        self, base_url: str, api_token: str, callback_base_url: str,
        *, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.callback_base_url = callback_base_url.rstrip("/")
        self.transport = transport

    async def _request(
        self, method: str, path: str, *,
        body: dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> bytes:
        headers = {"Authorization": f"Bearer {self.api_token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=4.0,
                follow_redirects=False, transport=self.transport,
            ) as client:
                async with client.stream(
                    method, path, json=body, headers=headers,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        status = response.status_code
                        raise ProcessEngineError(
                            "unauthorized" if status in {401, 403} else "remote_http_error",
                            f"External service HTTP {status}",
                            retryable=status == 429 or status >= 500,
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 64_000:
                            raise ProcessEngineError("response_too_large", "Response exceeds 64 kB")
                        data.extend(chunk)
                    return bytes(data)
        except httpx.HTTPError as exc:
            raise ProcessEngineError(
                "engine_unreachable", "External service unavailable", retryable=True,
            ) from exc

    @staticmethod
    def _job(data: bytes) -> RemoteJob:
        try:
            return RemoteJob.model_validate_json(data)
        except ValidationError as exc:
            raise ProcessEngineError("invalid_response", "Invalid job response") from exc

    @staticmethod
    def _snapshot(job: RemoteJob) -> EngineRunSnapshot:
        statuses: dict[str, ProcessStatus] = {
            "pending": "queued", "processing": "running", "paused": "waiting",
            "done": "success", "failed": "error", "stopped": "cancelled",
        }
        status = statuses.get(job.state, "unknown")
        return EngineRunSnapshot(
            status=status, engine_run_id=job.external_id,
            output=job.output if status == "success" else None,
            error=EngineError(code="remote_failed", message="External processing failed")
                if status == "error" else None,
            raw={"workflowId": f"example:{job.operation}"},
        )

    async def health(self) -> ProcessEngineHealth:
        try:
            await self._request("GET", "/health")
        except ProcessEngineError as exc:
            return ProcessEngineHealth(
                tool_code=self.code, status="error",
                reachable=exc.code != "engine_unreachable",
                authenticated=exc.code != "unauthorized",
                supports_cancel=True, cancel_mode="supported",
                message=exc.message, checked_at=datetime.now(timezone.utc),
            )
        return ProcessEngineHealth(
            tool_code=self.code, status="healthy", reachable=True, authenticated=True,
            supports_cancel=True, cancel_mode="supported",
            message="External service available", checked_at=datetime.now(timezone.utc),
        )

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return [EngineProcessDefinition(
            engine_process_id="example:invoice-intake", label="Validate and register an invoice",
            description="Input: format=pdf; files: one text/plain source URI. Output: result_uri.",
            active=True,
        )]

    async def start_run(
        self, engine_process_id: str, run: EngineRunReference,
        payload: ProcessStartPayload,
    ) -> EngineStartResult:
        if engine_process_id != "example:invoice-intake":
            raise ProcessEngineError("invalid_operation", "Unknown invoice workflow")
        try:
            validated = InvoiceInput.model_validate(payload.input)
        except ValidationError as exc:
            raise ProcessEngineError("invalid_input", "Expected format=pdf") from exc
        if len(payload.files) != 1 or payload.files[0].content_type != "text/plain":
            raise ProcessEngineError("invalid_files", "Expected one text/plain source file")
        body: dict[str, object] = {
            "operation": "invoice-intake", "input": validated.model_dump(),
            "files": [item.model_dump(mode="json", exclude={"uri", "runtime", "task_id"})
                for item in payload.files],
            "callback": {
                "url": f"{self.callback_base_url}/api/processes/runs/{run.id}/events",
                "headers": {"Authorization": f"Bearer {run.callback_token}"},
            },
        }
        job = self._job(await self._request(
            "POST", "/jobs", body=body, idempotency_key=run.correlation_id,
        ))
        return EngineStartResult(accepted=True, engine_run_id=job.external_id)

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        if not run.engine_run_id:
            return EngineRunSnapshot(status="unknown")
        job = self._job(await self._request(
            "GET", f"/jobs/{quote(run.engine_run_id, safe='')}",
        ))
        return self._snapshot(job)

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        if not run.engine_run_id:
            raise ProcessEngineError("cancel_unsupported", "Remote job identity is unknown")
        snapshot = self._snapshot(self._job(await self._request(
            "POST", f"/jobs/{quote(run.engine_run_id, safe='')}/cancel",
            idempotency_key=f"{run.correlation_id}:cancel",
        )))
        if snapshot.status not in {"success", "error", "cancelled"}:
            return EngineRunSnapshot(status="cancelling", engine_run_id=run.engine_run_id)
        return snapshot
```

The example accepts only `format=pdf` and a `text/plain` source before the POST.
For a real conversion, adapt validation to the formats actually supported.
The actual service's DTOs, limits and idempotency guarantees replace those in this
example. Do not advertise `cancel_mode="supported"` unless that service confirms
physical termination.

## 5. Register, configure and assign

1. Add the bridge package to `back/modules.py`. Its `__init__.py` registers a
   configured instance with `registry.register(engine)`, as in
   [the n8n bridge](../../../back/bridge/n8n/__init__.py). Loading must not perform
   network calls or create jobs. All engines must be registered before bootstrap
   calls `register_scheduler_jobs()`.
2. Supply URLs and secrets server-side. Use the existing encrypted parameter
   infrastructure with suitable declarations and configuration UI. The example's
   `base_url`, `api_token` and `callback_base_url` are Python arguments, not new
   settings already available in Galaris. Never place a secret in the definition,
   `input`, launch snapshot or description visible to the model.
3. Create a Tool whose `code` matches the engine. For a shipped contribution,
   declare this data through its owner's DbAdmin mechanism; for an installation,
   use authorized Tool CRUD. A Tool row does not load engine code, and Python
   registration does not create that row.
4. With administrative rights, read `GET /api/processes/tools`, check
   `GET /api/processes/tools/example/health`, then call
   `POST /api/processes/definitions/sync?tool_code=example`.
   “Synchronization” returns the external catalogue; it does not automatically
   create or assign a `ProcessDefinition`.
5. Explicitly create the definition with `POST /api/processes/definitions`:
   `{"tool_id": 123, "engine_process_id": "example:invoice-intake", "label": "Invoice intake",
   "description": "Input format; one source file; output result_uri.", "agent_id": 7}`.
   These numbers are synthetic: use the actual authorized Tool and agent.
   CRUD uses `PROCESS_ADMIN` and the management scope; global HTTP discovery
   also requires the global scope.
6. The agent uses `process_list`, `process_get`, then `process_start` from the
   base `galaris` package. Those functions and the assignment must be authorized.
   The conversation controller uses `conversation_process_start`.
   The optional `process_admin` package, inactive by default, provides administrative
   equivalents; supply `tool_code="example"` because several defaults remain `n8n`.
7. Regenerate and check documentation and architecture. In development,
   `make sync-db` applies declared data. Adding a module or its activation
   configuration requires loading it during bootstrap; ordinary hot reload of
   an already loaded method does not replace that step.

See the [developer guide](README.md) and [DbAdmin guide](dbadmin.md).

In `__init__.py`, after resolving and validating all three values server-side:

```python
from app.process import registry
from .engine import ExampleProcessEngine

registry.register(ExampleProcessEngine(base_url, api_token, callback_base_url))
```

Human endpoints follow RBAC and management scope; personal tools filter by calling
agent. An engine's presence does not grant access to every operation.
Assignment, Tool and definition identifier can be changed through authorized CRUD
with uniqueness validation; do not change them during an active execution.

## 6. Launch, recovery and network errors

Admission writes a `queued` run and a `ProcessStartJob` before any external effect.
It deduplicates by explicit key or, without one, by input fingerprint within
`PROCESS_IDEMPOTENCY_WINDOW_SECONDS` (300 seconds by default).
An explicit key is unique per agent and definition. Delivery correlation stays
the same when a job is recovered.

Workers acquire recoverable leases using SQL locks and handle up to four concurrent
starts per engine, spreading work across agents. Durable jobs survive restarts;
they do not guarantee that an external POST executed only once.
The remote service must deduplicate **before** any effect and retain its reference
and result. An in-memory idempotency ledger is insufficient.

Raise `ProcessEngineError(code, message, retryable=...)` for expected failures.
Classify validation/authentication errors as permanent and transient unavailability
according to the protocol. Recoverable starts use bounded backoff and
`PROCESS_START_MAX_RETRIES`. An effect submitted under deferred authorization with
a lost response can become `unknown` with `authorization_outcome_unknown`, instead
of being automatically replayed: its outcome must be reconciled.

Observation failure does not prove that the remote job failed. Polling retains its
recovery opportunities, adds diagnostics and can move to `unknown` after degradation.
`get_run` should be a repeatable read; if observing triggers further effects,
use appropriate authorization protections and durable checkpoints.
The bridge client must bound deadlines, response sizes and diagnostics.

## 7. Statuses, callbacks and cancellation

| Galaris status | Meaning |
|---|---|
| `queued` | Admitted; start or execution still pending. |
| `running` | Processing in progress. |
| `waiting` | Remote job waiting for an event or dependency. |
| `unknown` | Uncertain outcome or observation; not terminal. |
| `cancelling` | Stop requested; confirmation pending. |
| `success`, `error`, `cancelled` | Terminal; late observations cannot replace status or output. |

The effective matrix is in [state machines](../architecture/state-machines.md)
and `process_service.TRANSITIONS`. A callback can finish the run before the initial
POST response; the worker preserves that terminal. Polling reloads state under lock
after the remote call. Completion resolves any waiting Task, with idempotent
recovery of that resolution.

A service can send `POST /api/processes/runs/{UUID}/events` with
`Authorization: Bearer <run token>`. The configured
`PROCESS_N8N_CALLBACK_AUTH_HEADER` is also accepted despite its n8n-specific name;
when present, it takes precedence over Bearer. The adapter decides how to deliver
the URL and token to the software; `ProcessEngine` imposes no universal
network envelope.

```json
{
  "event_id": "job-42-completed",
  "status": "success",
  "engine_run_id": "job-42",
  "event_type": "conversion.completed",
  "output": {"result_uri": "https://processor.example/results/report.pdf"},
  "occurred_at": "2026-10-01T10:00:00Z"
}
```

Callbacks accept only `running`, `waiting`, `success`, `error` and
`cancelled`, although polling snapshots support additional statuses.
For errors, supply `error: {"code": "conversion_failed", "message": "..."}`.
Keep the same `event_id` when redelivering the same event: uniqueness is per run.
UUIDs and job references do not replace the token.
The former `/api/processus` prefix is a deprecated alias.

Cancellation can be local for a job not yet submitted. Otherwise, the engine receives
the request; HTTP acceptance of a stop is not evidence of physical termination.
When cancellation is unavailable, the ordinary core can mark a run locally
`cancelled` with `remote_may_continue=true`. Integrated operations may reject
such cancellation and keep tracking instead. Task replacement remains blocked while
remote termination is uncertain. See [the Process flow](../architecture/flows/process.md).

## 8. Files and provenance

Inputs use `files=[{"uri": "https://source.example/report.txt",
"description": "Invoice source"}]`. A URI can also belong to an authorized
Galaris provider; it does not itself grant access.
The snapshot preserves the source URI and name. The bridge receives
`ProcessFileRef` objects with name, type, size, expiry and `download_url`.

The software downloads that URL using the run token through Bearer or the configured
header. Access is bound to the file, run and expiry and reuses the agent's authorized
context. The source is materialized on demand into a bounded temporary file,
deleted after the response. The current Process limit is 512 MiB per file;
TTL defaults to 3,600 seconds and is not automatically renewed on each attempt.
Never forward host paths or provider credentials.

Large outputs stay in an appropriate provider; JSON output retains their URIs and
metadata within sanitizer limits. See
[media and resources](../architecture/flows/media-resources.md).
If the software calls Galaris LLM or Agent gateways, supply ProcessRun correlation
according to [the Process flow](../architecture/flows/process.md) and Agent token
permissions: a callback token does not grant gateway access.

An execution started elsewhere can be attached through
`POST /api/processes/workflows/{workflow_id}/runs/{engine_run_id}/sync`.
The engine must then read the external reference without a pre-existing local checkpoint.
The service checks `raw.workflowId` when supplied; the bridge must also guarantee
that the job belongs to the expected operation and scope.

## 9. Verify the integration

| Guarantee to verify | Scenario |
|---|---|
| Isolation | Assigned agent allowed, other agent denied; discovery and reads without leaks. |
| Validation before effects | Invalid input, file or operation: no remote POST. |
| Remote deduplication | Same correlation, concurrent submissions and lost response: one business effect. |
| Recovery | Restart the worker after submission, before local receipt and after terminal commit before Task resumption. |
| Event ordering | Terminal callback before start response; redelivery; late observations preserve the terminal. |
| Degraded observation | Timeout, 429, invalid response, prolonged outage then recovery: no invented business success or failure. |
| Cancellation | Unsubmitted job, pending remote stop, confirmed stop, unavailable API and concurrent completion. |
| Files | Authorized URI, token download, wrong token/run, expiry, size limit and cleanup. |
| Operations | Health without launch, secret-free logs, correlatable references and accessible results. |

Replace the bridge's network boundary in tests with `httpx.MockTransport`.
Use Process DB tests for durable workflows, then exercise a complete synthetic job
with the actual software: source file, output, recovery and cancellation.
A health check or simulated transport does not validate that real integration.

```bash
make tests ARGS='bridge/n8n/tests app/process/tests'
make typecheck
make architecture-check
APP_ENV=dev make docs-prepare
git diff --check
```

The test command above checks existing references; add the new bridge's tests to the
selection. Consult
[the functional test catalogue](functional-tests.md) before duplicating a guarantee.
Before publication without CI, run `make validate` against final sources.
`APP_ENV=dev make docs-update` propagates prepared documentation to development shared
search; the normal `make update` deployment indexes prepared sources.

## 10. Current limitations and references

- The registry accepts multiple engines and the scheduler creates jobs per engine.
  The default engine setting remains restricted to `n8n`; a new engine is selected
  by its definition's Tool rather than by changing that setting.
- `ProcessDefinition` has no engine connection/instance field.
  Multiple installations of the same software require an explicit bridge strategy
  and collision-free identities; there is no ready-made multi-instance setting.
- The catalogue does not publish per-definition input/output schemas. Describe
  input in the definition's description and validate it in the adapter.
- Discovery is neither authorization nor automatic import.
  Deleted definitions cannot be launched; their historical runs remain tracked.
- The n8n bridge selects the first webhook node and requires an execution reference;
  these are bridge-specific constraints, not `ProcessEngine` requirements.

Concrete references:
[n8n adapter](../../../back/bridge/n8n/engine.py),
[workers](../../../back/app/process/workers.py),
[Process service](../../../back/app/process/process_service.py),
[recovery tests](../../../back/app/process/tests/test_recovery.py) and
[crash tests](../../../back/app/process/tests/test_crash_recovery.py).
