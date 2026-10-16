"""Bounded Python-subset execution in Monty workers, without host capabilities."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID
import keyword
import textwrap
import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from .engine import ProcessEngineError


def dataset_program(source: str, dataset: dict[str, Any]) -> str:
    """Build source for the isolated runner; no user source executes here.

    Non-identifiers and reserved names remain accessible through dataset[name].
    Every invocation receives a detached JSON snapshot, never a live DB object.
    """
    names = sorted(name for name in dataset if name.isidentifier() and not keyword.iskeyword(name)
        and not name.startswith("_") and name != "dataset" and unicodedata.normalize("NFKC", name) == name)
    parameters = ", ".join(["dataset", *names])
    arguments = ", ".join(["dataset", *(f"dataset[{name!r}]" for name in names)])
    return f"def _galaris_activity({parameters}):\n{textwrap.indent(source, '    ')}\n\noutput = _galaris_activity({arguments})\n"


@dataclass(frozen=True, slots=True)
class CodeInvocation:
    id: UUID
    run_id: UUID
    occurrence_id: UUID
    agent_id: int
    phase: Literal["preprocess", "activity", "postprocess"]
    source: str
    values: dict[str, Any]


class CodeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["queued", "running", "success", "error", "cancelled", "unknown"]
    stopped: bool = False
    result: dict[str, Any] = Field(default_factory=dict)
    diagnostic: str = Field(default="", max_length=2000)


class IsolatedCodeRunner(Protocol):
    """An adapter owns bounds and per-execution isolation.

    submit compares immutable requests on duplicate keys. Only explicitly pure
    computation adapters may recompute after losing their in-memory receipt.
    A terminal observation becomes usable only after physical stop is confirmed.
    Calls return promptly; waiting for a sandbox must not hold the Process worker.
    """

    async def submit(self, invocation: CodeInvocation) -> CodeObservation: ...
    async def observe(self, invocation_id: UUID) -> CodeObservation: ...
    async def cancel(self, invocation_id: UUID) -> CodeObservation: ...


class MontyCodeRunner:
    """Pure computations can be replayed after a lost receipt; effects are forbidden.

    A fresh native worker and VM are discarded after every invocation. No mounts,
    external functions, host objects or OS handlers are exposed. Result integration
    stays in Process/Memory and uses its durable idempotency receipt.
    """

    replay_safe = True

    def __init__(self) -> None:
        self._cache: OrderedDict[UUID, tuple[str, CodeObservation]] = OrderedDict()
        self._active: dict[UUID, tuple[str, asyncio.Task[CodeObservation]]] = {}
        self._slots = asyncio.Semaphore(2)

    async def submit(self, invocation: CodeInvocation) -> CodeObservation:
        encoded = json.dumps({"source": invocation.source, "values": invocation.values, "phase": invocation.phase,
            "run": str(invocation.run_id), "occurrence": str(invocation.occurrence_id), "agent": invocation.agent_id},
            ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode()) > 2_000_000 or len(invocation.source) > 200_000:
            raise ValueError("Sandbox input exceeds its size limit")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        cached = self._cache.get(invocation.id)
        active = self._active.get(invocation.id)
        if cached is not None:
            if cached[0] != digest:
                raise ValueError("Sandbox invocation key already has different inputs")
            self._cache.move_to_end(invocation.id)
            return cached[1].model_copy(deep=True)
        if active is not None and active[0] != digest:
            raise ValueError("Sandbox invocation key already has different inputs")
        if active is None:
            if len(self._active) >= 32:
                return CodeObservation(status="queued")
            frozen = CodeInvocation(invocation.id, invocation.run_id, invocation.occurrence_id, invocation.agent_id,
                invocation.phase, invocation.source, json.loads(encoded)["values"])
            task = asyncio.create_task(self._execute(frozen))
            self._active[invocation.id] = digest, task
            def completed(finished: asyncio.Task[CodeObservation]) -> None:
                observation = CodeObservation(status="cancelled", stopped=True) if finished.cancelled() else finished.result()
                self._active.pop(invocation.id, None)
                self._cache[invocation.id] = digest, observation
                while len(self._cache) > 16:
                    self._cache.popitem(last=False)
            task.add_done_callback(completed)
            return CodeObservation(status="queued")
        return CodeObservation(status="running")

    async def _execute(self, invocation: CodeInvocation) -> CodeObservation:
        names = {"preprocess": ("input", "input_files"), "activity": ("output", "output_files"),
            "postprocess": ("data", "files")}[invocation.phase]
        # Only known protocol outputs are collected; no Python host introspection.
        inputs = json.loads(json.dumps(invocation.values, allow_nan=False))
        for name in names:
            inputs.setdefault(name, [] if name.endswith("files") else {})
        source = invocation.source + "\n" + "{" + ", ".join(f"{name!r}: {name}" for name in names) + "}\n"
        try:
            from pydantic_monty import AsyncMonty
            async with self._slots:
                async with AsyncMonty(min_processes=1, max_processes=1, request_timeout=3) as pool:
                    async with pool.checkout(limits={"max_memory": 32_000_000, "max_feed_duration_secs": 1.0,
                        "max_turn_duration_secs": 1.0, "max_recursion_depth": 128, "max_suspensions": 32,
                        "max_total_sleep_secs": 0}, os_policy={"datetime": datetime(2026, 1, 1, tzinfo=timezone.utc),
                            "sleep": "zero", "random_start": {"seed": 0}}) as session:
                        result = await session.feed_run(source, inputs=inputs, print_callback=lambda _stream, _text: None)
            if not isinstance(result, dict):
                raise ValueError("Sandbox output must be a JSON object")
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(serialized.encode()) > 2_000_000:
                raise ValueError("Sandbox output exceeds its size limit")
            return CodeObservation(status="success", stopped=True, result=json.loads(serialized))
        except Exception as error:
            return CodeObservation(status="error", stopped=True, diagnostic=str(error)[:2000])

    async def observe(self, invocation_id: UUID) -> CodeObservation:
        cached = self._cache.get(invocation_id)
        return cached[1].model_copy(deep=True) if cached else CodeObservation(status="running" if invocation_id in self._active else "unknown")

    async def cancel(self, invocation_id: UUID) -> CodeObservation:
        active = self._active.get(invocation_id)
        if active is not None:
            active[1].cancel()
            await asyncio.gather(active[1], return_exceptions=True)
            self._active.pop(invocation_id, None)
            observation = CodeObservation(status="cancelled", stopped=True)
            self._cache[invocation_id] = active[0], observation
            return observation
        cached = self._cache.get(invocation_id)
        return cached[1].model_copy(deep=True) if cached else CodeObservation(status="cancelled", stopped=True)


_runner: IsolatedCodeRunner | None = MontyCodeRunner()


def register_isolated_code_runner(runner: IsolatedCodeRunner | None) -> None:
    global _runner
    _runner = runner


def isolated_code_runner() -> IsolatedCodeRunner | None:
    return _runner


def require_isolated_code_runner() -> IsolatedCodeRunner:
    if _runner is None:
        raise ProcessEngineError("isolated_runner_unavailable", "The isolated Python runner is unavailable; no CPython backend fallback is permitted")
    return _runner
