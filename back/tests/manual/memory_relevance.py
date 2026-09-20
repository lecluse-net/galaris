"""Read-only recall diagnostics emitting only counts, ranks and durations.

Set MEMORY_PROBE_AGENT_ID and optionally MEMORY_PROBE_CASES. The bundled cases
are invented examples, not historical measurements. Prepare a dedicated test
corpus and adapt the expected UUIDs in a local, ignored cases file before use.
Never copy live queries, titles, excerpts or resource identifiers into Git.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import text

from app.memory.facade import search_memory_detailed
from app.memory.schemas import MemoryRecallResult
from core.database import get_db
from core.params.params_service import load_params


class ProbeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    query: str = Field(min_length=1)
    expected: frozenset[UUID]


def public_result(result: MemoryRecallResult, expected: frozenset[UUID]) -> dict[str, int | bool | None]:
    """Select numeric evidence; never serialize the result or its free text."""
    return {
        "hit_count": len(result.hits),
        "first_expected_rank": next(
            (rank for rank, hit in enumerate(result.hits, 1) if hit.item.id in expected),
            None,
        ),
        "degraded": result.degraded,
    }


async def main() -> None:
    agent_id = int(os.environ["MEMORY_PROBE_AGENT_ID"])
    if agent_id <= 0:
        raise ValueError("MEMORY_PROBE_AGENT_ID must be positive")
    cases_path = Path(os.environ.get(
        "MEMORY_PROBE_CASES", str(Path(__file__).with_name("memory_relevance_examples.json"))
    ))
    try:
        cases = TypeAdapter(list[ProbeCase]).validate_json(cases_path.read_bytes())
    except Exception:
        raise ValueError("Invalid memory probe cases; private input details omitted") from None
    await load_params()
    await get_db().execute(text("SET TRANSACTION READ ONLY"))
    for number, case in enumerate(cases, 1):
        started = time.perf_counter()
        try:
            result = await search_memory_detailed(
                case.query, agent_id=agent_id, limit=10,
                record_llm_access=False, telemetry_kind="evaluation",
            )
        except Exception:
            # An exception can itself contain a query, endpoint or private value.
            print(json.dumps({"case": number, "failed": True}), flush=True)
            raise RuntimeError("Memory probe failed; private error details omitted") from None
        print(json.dumps({
            "case": number,
            **public_result(result, case.expected),
            "latency_ms": round(1000 * (time.perf_counter() - started)),
        }), flush=True)
