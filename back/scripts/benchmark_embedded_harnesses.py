"""Run a paired benchmark through the normal Chat and Task APIs of an isolated instance."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from datetime import datetime
import hashlib
from html import escape
from importlib.metadata import version
import json
from math import ceil, sqrt
import os
from pathlib import Path
import platform
from random import Random
from statistics import mean, median
import sys
from time import monotonic
from typing import Any, Literal, TypeVar, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Driver = Literal["internal", "claude_embedded"]
DRIVERS: tuple[Driver, Driver] = ("internal", "claude_embedded")
CHAT_TERMINAL = {"SUCCEEDED", "SUPERSEDED", "ERROR", "ERROR_RESOLVED", "CANCELLED", "FAILED", "INTERRUPTED"}
MAX_CALL_ROWS = 500
MODEL_OBSERVATION_FIELDS = {
    "created_at", "updated_at", "pricing_updated_at", "pricing_last_attempt_at",
    "pricing_refresh_error", "pricing_provenance",
}
T = TypeVar("T")


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prompt: str = Field(min_length=1, max_length=8000)
    expected: str = Field(min_length=1, max_length=8000)


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    turns: list[Turn] = Field(min_length=1, max_length=12)
    expected_dataset: dict[str, JsonValue] | None = None

    def input_digest(self) -> str:
        values = {"prompts": [turn.prompt for turn in self.turns], "dataset_payload": self.expected_dataset}
        frozen = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(frozen.encode()).hexdigest()


class Case(CaseInput):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    family: Literal["conversation", "task"]
    variants: list[CaseInput] = Field(default_factory=list[CaseInput], max_length=200)
    success_noninferiority_margin: float = Field(default=0.05, ge=0, le=0.30)
    minimum_useful_latency_gain_seconds: float = Field(default=1, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_turns(self) -> Case:
        for sample in (self, *self.variants):
            if self.family == "task" and len(sample.turns) != 1:
                raise ValueError("A Task case must have one objective and one oracle")
            if self.family == "conversation" and len(sample.turns) < 2:
                raise ValueError("A Chat case must exercise at least two turns in the same room")
            if (sample.expected_dataset is None) != (self.expected_dataset is None):
                raise ValueError("All variants must use the same kind of effect oracle")
            if sample.expected_dataset is not None:
                if self.family != "task":
                    raise ValueError("A Data document creation case must run through Tasks")
                if len(canonical_json(sample.expected_dataset)) > 4_000:
                    raise ValueError("The synthetic Data document must occupy at most 4000 characters")
        if len({sample.input_digest() for sample in self.variants}) != len(self.variants):
            raise ValueError("Every declared variant must have distinct model input")
        return self


class Campaign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_revision: str = Field(min_length=7, max_length=100)
    internal_agent: int = Field(gt=0)
    claude_agent: int = Field(gt=0)
    model_id: int = Field(gt=0)
    model_site: Literal["local", "remote"]
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    repetitions: int = Field(ge=2, le=200)
    max_legs: int = Field(ge=4, le=1000)
    max_observed_cost: float = Field(gt=0, allow_inf_nan=False)
    operation_timeout: float = Field(default=120, ge=5, le=600, allow_inf_nan=False)
    cases: list[Case] = Field(min_length=2, max_length=50)

    @model_validator(mode="after")
    def validate_campaign(self) -> Campaign:
        if self.internal_agent == self.claude_agent:
            raise ValueError("Use two dedicated agents")
        if len({case.key for case in self.cases}) != len(self.cases):
            raise ValueError("Case keys must be unique")
        if {case.family for case in self.cases} != {"conversation", "task"}:
            raise ValueError("Include both Chat and Task cases")
        if len(self.cases) * self.repetitions * len(DRIVERS) > self.max_legs:
            raise ValueError("Planned legs exceed max_legs")
        if any(case.variants and len(case.variants) != self.repetitions for case in self.cases):
            raise ValueError("A case with variants requires exactly one variant per repetition")
        return self


class Call(BaseModel):
    """Export only the physical-call evidence needed by the benchmark."""

    id: UUID
    purpose: str | None
    agent_id: int | None
    task_id: UUID | None
    task_attempt_id: UUID | None
    conversation_round_id: UUID | None
    agent_run_id: UUID | None
    correlation_ref: str | None
    llm_id: int | None
    provider_code: str | None
    effective_model: str
    reasoning_effort: str | None
    status: str
    total_tokens: int = Field(ge=0)
    cost: float = Field(ge=0, allow_inf_nan=False)
    inference_cost: float = Field(ge=0, allow_inf_nan=False)
    first_token_at: datetime | None

    def binding(self) -> tuple[int | None, str | None, str, str | None]:
        return self.llm_id, self.provider_code, self.effective_model, self.reasoning_effort


class DatasetEvidence(BaseModel):
    title: str
    status: Literal["confirmed", "missing", "duplicated", "wrong_owner", "wrong_content", "wrong_revision",
                    "missing_receipt", "changed_existing"]
    new_ids: list[UUID]


class Observation(BaseModel):
    operation_id: UUID
    actual: str
    matched: bool
    status: str
    driver: str | None
    elapsed_seconds: float
    first_token_seconds: float | None
    first_output_seconds: float | None = None
    calls: list[Call]
    dataset: DatasetEvidence | None = None

    @property
    def passed(self) -> bool:
        return (self.matched and self.status in {"SUCCESS", "SUCCEEDED"}
                and (self.dataset is None or self.dataset.status == "confirmed"))


class BenchmarkMismatch(ValueError):
    """The observed operation cannot support a comparison between the two drivers."""


def canonical_json(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def has_creation_receipt(execution: dict[str, Any], uri: str) -> bool:
    for message in execution.get("messages") or ():
        if (message.get("type") != "tool" or message.get("tool_name") != "file_create"
                or message.get("success") is not True):
            continue
        receipt = message.get("tool_result")
        if not isinstance(receipt, dict) or "uri" not in receipt:
            try:
                receipt = json.loads(message.get("content") or "")
            except (TypeError, ValueError):
                continue
        if isinstance(receipt, dict):
            fields = cast(dict[str, Any], receipt)
            if fields.get("uri") == uri and fields.get("operation") == "create" and fields.get("state") == "created":
                return True
    return False


async def poll(check: Callable[[], Awaitable[T | None]], *, timeout: float) -> T:
    async with asyncio.timeout(timeout):
        while (result := await check()) is None:
            await asyncio.sleep(0.2)
        return result


class Benchmark:
    def __init__(self, client: httpx.AsyncClient, campaign: Campaign, write: Callable[[dict[str, Any]], None]) -> None:
        self.client = client
        self.campaign = campaign
        self.write = write
        self.agents: dict[Driver, int] = {"internal": campaign.internal_agent, "claude_embedded": campaign.claude_agent}
        self.calls_seen: set[UUID] = set()
        self.model_binding: tuple[int | None, str | None, str, str | None] | None = None

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def preflight(self) -> None:
        agent_definitions: list[dict[str, Any]] = []
        tool_policies: list[list[tuple[int, list[tuple[str, str, str, bool]]]]] = []
        for driver, identifier in self.agents.items():
            agent = await self.request("GET", f"/api/agents/{identifier}")
            if agent["agent_driver"] != driver or agent.get("task_harness_id") is not None:
                raise BenchmarkMismatch(f"Agent {identifier} does not have the expected embedded driver {driver}")
            if agent.get("profile_id") is None or agent.get("fallback_profile_id") is not None:
                raise BenchmarkMismatch("Use an explicit shared profile without an agent fallback")
            fields = ("title_id", "first_name", "last_name", "personality", "job_title", "job_description",
                      "user_id", "profile_id", "team_ids")
            agent_definitions.append({field: agent.get(field) for field in fields})
            tool_policies.append(await self.tool_policy(identifier))
        if agent_definitions[0] != agent_definitions[1]:
            raise BenchmarkMismatch("Agent identities, manager, teams, instructions and profile must match")
        if tool_policies[0] != tool_policies[1]:
            raise BenchmarkMismatch("Agent connections and effective tool permissions must match")
        if any(case.expected_dataset is not None for case in self.campaign.cases) and not any(
            name == "file_create" and state == "enabled" for _, functions in tool_policies[0]
            for _, name, state, _ in functions
        ):
            raise BenchmarkMismatch("Enable file_create for both test agents before running Data document cases")
        profile_id = agent_definitions[0]["profile_id"]
        profile = await self.request("GET", f"/api/llm-profiles/{profile_id}")
        for slot in ("text_low", "text_standard"):
            if (profile.get(f"{slot}_llm_id") != self.campaign.model_id
                or profile.get(f"{slot}_reasoning_effort") != self.campaign.reasoning_effort):
                raise BenchmarkMismatch(f"Configure the campaign model and reasoning effort in {slot}")

    async def tool_policy(self, agent_id: int) -> list[tuple[int, list[tuple[str, str, str, bool]]]]:
        connections = await self.request("GET", "/api/connections", params={"agent_id": agent_id, "active_only": "true", "limit": 500})
        if len(connections) >= 500:
            raise BenchmarkMismatch("The tool policy listing may be incomplete")
        policy: list[tuple[int, list[tuple[str, str, str, bool]]]] = []
        for connection in connections:
            functions = await self.request("GET", f"/api/connections/{connection['id']}/functions")
            if not functions["success"]:
                raise BenchmarkMismatch("Could not read an agent's effective tool permissions")
            policy.append((connection["service_id"], sorted((
                item["capability_kind"], item["name"], item["effective_state"], item["conversation_enabled"],
            ) for item in functions["functions"])))
        return sorted(policy)

    async def model_snapshot(self) -> str:
        model = await self.request("GET", f"/api/llm-providers/llms/{self.campaign.model_id}")
        provider = await self.request("GET", f"/api/llm-providers/{model['llm_provider_id']}")
        if not provider["is_active"]:
            raise BenchmarkMismatch("The benchmark model's provider is inactive")
        # A pricing poll updates the model row even when it learns no price.
        # Hash the settings and billed rates, excluding observation timestamps
        # and diagnostics. The provider revision still fences credential changes.
        identity = {"model": {key: value for key, value in model.items() if key not in MODEL_OBSERVATION_FIELDS},
                    "provider": provider["id"], "endpoint": provider["base_url"],
                    "provider_revision": provider.get("updated_at")}
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    async def round_for(self, room: str, message: str) -> dict[str, Any] | None:
        activity = await self.request("GET", f"/api/chat/rooms/{room}/activity", params={"page_size": 50})
        matches = [item for item in activity["items"] if message in item["message_ids"]]
        if len(matches) > 1:
            raise BenchmarkMismatch("A submitted Chat message has more than one owning round")
        return matches[0] if matches else None

    async def conversation(self, case: Case, driver: Driver) -> list[Observation]:
        agent = self.agents[driver]
        room = (await self.request("POST", "/api/chat/rooms", json={
            "agent_id": agent, "label": f"Harness benchmark · {case.key}",
        }))["id"]
        observations: list[Observation] = []
        for turn in case.turns:
            started = monotonic()
            message = (await self.request("POST", f"/api/chat/rooms/{room}/messages", json={
                "client_message_id": str(uuid4()), "text": turn.prompt, "language": "en",
            }))["id"]
            self.write({"event": "message_submitted", "room_id": room, "message_id": message})

            async def terminal_round() -> dict[str, Any] | None:
                item = await self.round_for(room, message)
                return item if item is not None and item["status"] in CHAT_TERMINAL else None

            try:
                activity = await poll(terminal_round, timeout=self.campaign.operation_timeout)
            except TimeoutError:
                # Cleanup is best effort, and the evidence still identifies the active work.
                try:
                    pending = await self.round_for(room, message)
                    if pending is not None and "stop" in pending["available_actions"]:
                        round_id = pending["id"]
                        await self.request("POST", f"/api/chat/rooms/{room}/activity/{round_id}/control",
                                           json={"action": "stop", "expected_attempt": pending["attempt"]})
                        self.write({"event": "stop_requested", "operation_id": round_id})
                except httpx.HTTPError as exc:
                    self.write({"event": "stop_failed", "error_type": type(exc).__name__})
                raise
            operation_id = UUID(activity["id"])
            record = await self.request("GET", f"/api/conversations/rounds/{operation_id}")
            if record["room_id"] != room or record["agent_id"] != agent:
                raise BenchmarkMismatch("The Chat result belongs to a different room or agent")
            observations.append(await self.observe(
                operation_id, "conversation", driver, turn, record, monotonic() - started,
            ))
            if observations[-1].status != "SUCCEEDED":
                break
        return observations

    async def datasets_named(self, title: str) -> dict[UUID, dict[str, Any]]:
        page = await self.request("GET", "/api/datasets", params={"q": title, "page_size": 50})
        if page["total"] > len(page["items"]):
            raise BenchmarkMismatch("The Data document listing is incomplete")
        return {UUID(row["id"]): row for row in page["items"] if row["title"] == title}

    async def observe_dataset(
        self, title: str, before: dict[UUID, dict[str, Any]], expected: dict[str, JsonValue],
        driver: Driver, execution: dict[str, Any],
    ) -> DatasetEvidence:
        after = await self.datasets_named(title)
        new_ids = sorted(after.keys() - before.keys())
        keys = ("checksum", "revision", "owner_agent_id", "owner_user_id")
        if any(identity not in after or any(row[key] != after[identity][key] for key in keys)
               for identity, row in before.items()):
            return DatasetEvidence(title=title, status="changed_existing", new_ids=new_ids)
        if len(new_ids) != 1:
            return DatasetEvidence(title=title, status="duplicated" if new_ids else "missing", new_ids=new_ids)
        identity = new_ids[0]
        stored = await self.request("GET", f"/api/datasets/{identity}")
        if stored["owner_agent_id"] != self.agents[driver]:
            status = "wrong_owner"
        elif stored["revision"] != 1:
            status = "wrong_revision"
        elif canonical_json(json.loads(stored["content"])) != canonical_json(expected):
            status = "wrong_content"
        elif not has_creation_receipt(execution, f"data://{identity}"):
            status = "missing_receipt"
        else:
            status = "confirmed"
        return DatasetEvidence(title=title, status=status, new_ids=new_ids)

    async def task(self, case: Case, driver: Driver, dataset_title: str | None) -> list[Observation]:
        turn = case.turns[0]
        objective = f"<p>{escape(turn.prompt)}</p>"
        before: dict[UUID, dict[str, Any]] = {}
        if dataset_title is not None and case.expected_dataset is not None:
            before = await self.datasets_named(dataset_title)
            objective += (f'<p>Use file_create with path="data://".</p><p>Dataset title: {dataset_title}</p>'
                          + f"<p>Complete JSON content: {escape(canonical_json(case.expected_dataset))}</p>")
        started = monotonic()
        task = await self.request("POST", "/api/tasks", json={
            "agent_id": self.agents[driver], "label": f"Harness benchmark · {case.key}",
            "objective": objective,
            "forced_route": "EXEC", "forced_effort": "standard",
            "reasoning_effort_override": self.campaign.reasoning_effort,
        })
        operation_id = UUID(task["id"])
        self.write({"event": "task_created", "operation_id": str(operation_id)})
        path = f"/api/tasks/{operation_id}"
        await self.request("POST", f"{path}/run")

        async def terminal_task() -> dict[str, Any] | None:
            record = await self.request("GET", path)
            return record if record["status"] in {"SUCCESS", "ERROR"} else None

        try:
            record = await poll(terminal_task, timeout=self.campaign.operation_timeout)
        except TimeoutError:
            try:
                pending = await self.request("GET", path)
                if pending["status"] not in {"SUCCESS", "ERROR"}:
                    await self.request("POST", f"{path}/cancel", json={"expected_revision": pending["revision"]})
                    self.write({"event": "stop_requested", "operation_id": str(operation_id)})
            except httpx.HTTPError as exc:
                self.write({"event": "stop_failed", "error_type": type(exc).__name__})
            raise
        elapsed = monotonic() - started
        activity = await self.request("POST", "/api/tasks/activity", json={"task_ids": [str(operation_id)]})
        if len(activity) != 1 or activity[0]["task_id"] != str(operation_id):
            raise BenchmarkMismatch(f"Could not read timing for task {operation_id}")
        startup = cast(dict[str, object] | None, activity[0].get("startup_timing"))
        record["execution_timing"] = startup.get("execution_timing") if startup else None
        observation = await self.observe(operation_id, "task", driver, turn, record, elapsed)
        if dataset_title is not None and case.expected_dataset is not None:
            observation.dataset = await self.observe_dataset(dataset_title, before, case.expected_dataset, driver,
                                                            record.get("execution_result") or {})
        return [observation]

    async def observe(
        self, operation_id: UUID, family: Literal["conversation", "task"], driver: Driver,
        turn: Turn, record: dict[str, Any], elapsed: float,
    ) -> Observation:
        is_chat = family == "conversation"
        owner_field = "conversation_round_id" if is_chat else "task_id"
        purpose = "conversation.text" if is_chat else "agent.exec"
        execution: dict[str, Any] = record.get("execution_result") or {}
        metadata: dict[str, Any] = execution.get("metadata") or {}
        calls = [Call.model_validate(row) for row in await self.request("GET", "/api/llm-calls", params={
            owner_field: str(operation_id), "limit": MAX_CALL_ROWS,
        })]
        if len(calls) == MAX_CALL_ROWS or any(call.status == "running" for call in calls):
            raise BenchmarkMismatch(f"The call journal for {operation_id} may be incomplete")
        if any(getattr(call, owner_field) != operation_id for call in calls):
            raise BenchmarkMismatch(f"The call journal includes calls from another operation for {operation_id}")
        identities = {call.id for call in calls}
        if len(identities) != len(calls) or identities & self.calls_seen:
            raise BenchmarkMismatch(f"A physical call was counted more than once for {operation_id}")
        self.calls_seen.update(identities)
        primary = [call for call in calls if call.purpose == purpose]
        run = metadata.get("run_id")
        if not primary or not run or metadata.get("driver_code") != driver or metadata.get("agent_id") != self.agents[driver]:
            raise BenchmarkMismatch(f"Cannot prove execution by {driver} for {operation_id}")
        if is_chat and str(operation_id) != run:
            raise BenchmarkMismatch(f"Chat round {operation_id} has a different run identity")
        for call in primary:
            attempt_ref = (f"round:{operation_id}:attempt:" if is_chat else f"task:{operation_id}:attempt:{call.task_attempt_id}")
            if (call.agent_id != self.agents[driver] or str(call.agent_run_id) != run
                or call.llm_id != self.campaign.model_id
                or call.reasoning_effort != self.campaign.reasoning_effort):
                raise BenchmarkMismatch(f"Incompatible run identity or model settings for {call.id}")
            if not is_chat and call.task_attempt_id is None:
                raise BenchmarkMismatch(f"Task call {call.id} has no owning attempt")
            if driver == "claude_embedded":
                try:
                    if is_chat and call.correlation_ref and call.correlation_ref.startswith(attempt_ref):
                        UUID(call.correlation_ref.removeprefix(attempt_ref))
                    elif is_chat or call.correlation_ref != attempt_ref:
                        raise ValueError("Unexpected embedded origin")
                except ValueError as exc:
                    raise BenchmarkMismatch(f"Claude call {call.id} lacks its exact origin") from exc
            binding = call.binding()
            if self.model_binding is not None and binding != self.model_binding:
                raise BenchmarkMismatch(f"Physical model binding changed at {call.id}")
            self.model_binding = binding
        first_token_at = min((call.first_token_at for call in primary if call.first_token_at), default=None)
        operation_created = datetime.fromisoformat(record["created_at"])
        first_token = (first_token_at - operation_created).total_seconds() if first_token_at else None
        execution_timing = cast(dict[str, object] | None, record.get("execution_timing"))
        first_output_at = execution_timing.get("first_output_at") if execution_timing else None
        first_output = ((datetime.fromisoformat(first_output_at) - operation_created).total_seconds()
                        if isinstance(first_output_at, str) else None)
        actual = ((record.get("response_text") if is_chat else execution.get("result")) or "").strip()
        return Observation(operation_id=operation_id, actual=actual, matched=actual == turn.expected,
                           status=record["status"], driver=metadata.get("driver_code"), elapsed_seconds=elapsed,
                           first_token_seconds=first_token if first_token is not None and first_token >= 0 else None,
                           first_output_seconds=first_output if first_output is not None and first_output >= 0 else None,
                           calls=calls)


def leg_metrics(observations: list[Observation], expected_count: int) -> dict[str, Any]:
    calls = [call for observation in observations for call in observation.calls]
    datasets = [item.dataset for item in observations if item.dataset is not None]
    completed = len(observations) == expected_count and all(observation.passed for observation in observations)
    return {"passed": completed, "false_success": any(item.status in {"SUCCESS", "SUCCEEDED"} and not item.passed
                                                        for item in observations),
            "cost": sum(call.cost for call in calls), "inference_cost": sum(call.inference_cost for call in calls),
            "tokens": sum(call.total_tokens for call in calls), "call_count": len(calls),
            "datasets_expected": len(datasets), "datasets_confirmed": sum(item.status == "confirmed" for item in datasets),
            "elapsed_seconds": sum(item.elapsed_seconds for item in observations),
            "first_token_seconds": [item.first_token_seconds for item in observations if item.first_token_seconds is not None],
            "first_output_seconds": [item.first_output_seconds for item in observations if item.first_output_seconds is not None]}


def paired_interval(deltas: list[float]) -> list[float] | None:
    if len(deltas) < 5:
        return None
    random = Random(104729)
    resampled = sorted(mean(random.choices(deltas, k=len(deltas))) for _ in range(4000))
    return [resampled[99], resampled[3899]]


def paired_success_interval(deltas: list[float]) -> list[float]:
    """Bound both discordant proportions with Bonferroni-adjusted Wilson intervals."""
    z = 2.2414
    n = len(deltas)

    def wilson(count: int) -> tuple[float, float]:
        proportion = count / n
        denominator = 1 + z * z / n
        center = (proportion + z * z / (2 * n)) / denominator
        half_width = z * sqrt((proportion * (1 - proportion) + z * z / (4 * n)) / n) / denominator
        return max(0.0, center - half_width), min(1.0, center + half_width)

    candidate = wilson(deltas.count(1))
    baseline = wilson(deltas.count(-1))
    return [candidate[0] - baseline[1], candidate[1] - baseline[0]]


def summary(pairs: list[dict[str, Any]], cases: list[Case]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for family in ("conversation", "task"):
        family_pairs = [pair for pair in pairs if pair["family"] == family]
        if not family_pairs:
            continue
        result: dict[str, Any] = {"discordant": [pair["pair"] for pair in family_pairs
                       if pair[DRIVERS[0]]["passed"] != pair[DRIVERS[1]]["passed"]]}
        for driver in DRIVERS:
            legs = [pair[driver] for pair in family_pairs]
            successes = sum(leg["passed"] for leg in legs)
            timing = sorted(leg["elapsed_seconds"] for leg in legs)
            result[driver] = {"legs": len(legs), "successes": successes, "false_successes": sum(leg["false_success"] for leg in legs),
                              "cost_per_success": sum(leg["cost"] for leg in legs) / successes if successes else None,
                              "elapsed_median_seconds": median(timing), "elapsed_p95_seconds": timing[ceil(0.95 * len(timing)) - 1]}
            for measure in ("first_token", "first_output"):
                samples = sorted(value for leg in legs for value in leg[f"{measure}_seconds"])
                result[driver][f"{measure}_samples"] = len(samples)
                result[driver][f"{measure}_median_seconds"] = median(samples) if samples else None
                result[driver][f"{measure}_p95_seconds"] = samples[ceil(0.95 * len(samples)) - 1] if samples else None
        result["paired_mean_elapsed_delta_seconds"] = mean(pair[DRIVERS[1]]["elapsed_seconds"] - pair[DRIVERS[0]]["elapsed_seconds"]
                                                           for pair in family_pairs)
        scenarios = {}
        for case in (item for item in cases if item.family == family):
            attempts = [pair for pair in family_pairs if pair["case"] == case.key]
            if not attempts:
                continue
            success_deltas = [float(pair[DRIVERS[1]]["passed"]) - float(pair[DRIVERS[0]]["passed"]) for pair in attempts]
            latency_deltas = [pair[DRIVERS[1]]["elapsed_seconds"] - pair[DRIVERS[0]]["elapsed_seconds"] for pair in attempts]
            distinct_inputs = len({pair["input_sha256"] for pair in attempts})
            distinct_samples = distinct_inputs == len(attempts)
            success_interval = paired_success_interval(success_deltas) if distinct_samples else None
            elapsed_interval = paired_interval(latency_deltas)
            scenarios[case.key] = {
                "pairs": len(attempts), "distinct_inputs": distinct_inputs, "success_rate_delta": mean(success_deltas),
                "successes": {driver: sum(pair[driver]["passed"] for pair in attempts) for driver in DRIVERS},
                "success_rate_interval_95": success_interval,
                "success_noninferiority_supported": (success_interval is not None
                                                     and success_interval[0] >= -case.success_noninferiority_margin),
                "elapsed_delta_seconds": mean(latency_deltas), "elapsed_interval_95_seconds": elapsed_interval,
                "useful_latency_gain_supported": (elapsed_interval is not None
                    and elapsed_interval[1] <= -case.minimum_useful_latency_gain_seconds),
            }
            if case.expected_dataset is not None:
                scenarios[case.key]["datasets_confirmed"] = {
                    driver: sum(pair[driver]["datasets_confirmed"] for pair in attempts) for driver in DRIVERS
                }
        result["scenarios"] = scenarios
        report[family] = result
    return report


async def run(benchmark: Benchmark, write: Callable[[dict[str, Any]], None]) -> None:
    await benchmark.preflight()
    model_snapshot = await benchmark.model_snapshot()
    write({"event": "model_binding", "sha256": model_snapshot})
    campaign = benchmark.campaign
    pairs: list[dict[str, Any]] = []
    observed_cost = 0.0
    for repetition in range(campaign.repetitions):
        for index, case in enumerate(campaign.cases):
            order = DRIVERS if (repetition + index) % 2 == 0 else DRIVERS[::-1]
            if case.variants:
                sample = case.variants[repetition]
                case = case.model_copy(update={"turns": sample.turns, "expected_dataset": sample.expected_dataset})
            pair: dict[str, Any] = {"pair": f"{case.key}/{repetition + 1}", "case": case.key, "family": case.family,
                                    "input_sha256": case.input_digest()}
            dataset_title = f"Harness-{case.key}-{uuid4().hex}" if case.expected_dataset is not None else None
            for driver in order:
                if observed_cost >= campaign.max_observed_cost:
                    raise BenchmarkMismatch("The observed campaign cost reached its limit")
                write({"event": "leg_started", "pair": pair["pair"], "driver": driver, "input_sha256": pair["input_sha256"],
                       **({"dataset_title": dataset_title} if dataset_title is not None else {})})
                if case.family == "conversation":
                    observations = await benchmark.conversation(case, driver)
                else:
                    observations = await benchmark.task(case, driver, dataset_title)
                if await benchmark.model_snapshot() != model_snapshot:
                    raise BenchmarkMismatch("Model endpoint or configuration changed during the campaign")
                metrics = leg_metrics(observations, len(case.turns))
                observed_cost += metrics["cost"]
                pair[driver] = metrics
                write({"event": "leg_finished", "pair": pair["pair"], "driver": driver, "metrics": metrics,
                       "input_sha256": pair["input_sha256"],
                       "observations": [item.model_dump(mode="json") for item in observations]})
            pairs.append(pair)
    write({"event": "summary", "observed_cost": observed_cost, "within_cost_limit": observed_cost <= campaign.max_observed_cost,
           "pairs": len(pairs), "families": summary(pairs, campaign.cases)})
    if observed_cost > campaign.max_observed_cost:
        raise BenchmarkMismatch("Observed cost exceeded the campaign limit on the last leg")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True, help="Read the JSON manifest from '-' for stdin")
    parser.add_argument("--output", type=Path, required=True, help="Write JSON Lines to '-' for stdout")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run", action="store_true", help="Send model requests on a dedicated benchmark instance")
    args = parser.parse_args()
    campaign = Campaign.model_validate_json(sys.stdin.buffer.read() if args.campaign == Path("-") else args.campaign.read_bytes())
    address = urlsplit(str(args.base_url))
    if (address.scheme not in {"http", "https"} or address.hostname not in {"127.0.0.1", "::1", "localhost"}
        or address.username or address.password or address.path not in {"", "/"} or address.query or address.fragment):
        parser.error("Use the loopback HTTP(S) address of the isolated instance")
    token = os.environ.get("LAB_ACCESS_TOKEN")
    if args.run and not token:
        parser.error("LAB_ACCESS_TOKEN is required for execution")
    if args.run and os.environ.get("APP_ENV") != "qualification":
        parser.error("Run the campaign inside the isolated backend with APP_ENV=qualification")
    runtime: dict[str, str] = {}
    if args.run:
        from core.settings import settings

        if settings.APP_BUILD_REVISION == "unknown" or settings.APP_BUILD_REVISION != campaign.image_revision:
            parser.error("The manifest must identify the running candidate image revision")
        runtime = {"image_revision": settings.APP_BUILD_REVISION, "python": platform.python_version(),
                   "architecture": platform.machine(), "claude_agent_sdk": version("claude-agent-sdk"),
                   "pydantic_ai": version("pydantic-ai")}
    with nullcontext(sys.stdout) if args.output == Path("-") else args.output.open("x", encoding="utf-8") as report:
        def write(event: dict[str, Any]) -> None:
            report.write(json.dumps(event, ensure_ascii=False) + "\n")
            report.flush()

        write({"event": "campaign", "execute": args.run, "configuration": campaign.model_dump(mode="json"),
               "sha256": hashlib.sha256(campaign.model_dump_json().encode()).hexdigest(), "runtime": runtime})
        if args.run:
            async with httpx.AsyncClient(base_url=args.base_url, headers={"Authorization": f"Bearer {token}",
                                         "X-Editorial-Profile-Version": "1"}, timeout=30, trust_env=False) as client:
                try:
                    await run(Benchmark(client, campaign, write), write)
                except (BenchmarkMismatch, TimeoutError, httpx.HTTPError) as exc:
                    write({"event": "campaign_failed", "error_type": type(exc).__name__, "reason": str(exc)})
                    raise


if __name__ == "__main__":
    asyncio.run(main())
