"""Compact input origins, stored transactionally and read only on explicit demand."""

from datetime import datetime, timezone
from copy import deepcopy
import asyncio
import hashlib
import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, func
from httpx import HTTPError

from app.agent import AgentManagementScope
from core.database import get_db
from .models import ProcessRun, ProcessRunEvent

PROVENANCE_EVENT = "run.inputs.provenance"


class ProvenanceUnavailable(RuntimeError):
    """An interrupted source check must release its database transaction before retry."""


def value_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _reference(reference: str) -> dict[str, str]:
    # Long references stay identifiable without allowing a URI to inflate every row.
    return {"reference": reference} if len(reference.encode()) <= 2048 else {"reference_sha256": hashlib.sha256(reference.encode()).hexdigest()}


async def record_inputs(run: ProcessRun, values: dict[str, Any], *, origins: dict[str, dict[str, Any]] | None = None,
                        metadata: dict[str, dict[str, Any]] | None = None) -> None:
    """Caller owns the run lock/creation transaction. No model or source download."""
    if not values:
        return
    db = get_db()
    current = dict(await db.scalar(select(ProcessRun.input_provenance).where(ProcessRun.id == run.id)) or {})
    supplied = origins or {}
    graph = run.launch_snapshot.get("definition", {}).get("graph", {})
    defaults = {item["name"]: item["default"] for item in graph.get("variables", []) if item.get("default") is not None}
    changes: dict[str, Any] = {}
    now = datetime.now(timezone.utc).isoformat()
    resources: set[str] = set()
    for raw in values.values():
        if isinstance(raw, dict):
            typed = cast(dict[str, Any], raw)
            if typed.get("type") in {"File", "Document"} and isinstance(typed.get("value"), str):
                resources.add(str(typed["value"]))
    from app.file_share.facade import conversion_origins
    conversions = await conversion_origins(run.launcher_agent_id, {uri: str(stamp["checksum"])
        for uri, stamp in (metadata or {}).items() if uri in resources and stamp.get("checksum")})
    for name, value in values.items():
        origin = supplied.get(name)
        if origin is None:
            origin = {"kind": "default", "definition_revision": run.launch_snapshot.get("definition", {}).get("revision")} if defaults.get(name) == value else {"kind": "agent"}
        # Sources are supplied exclusively by owning services, never an MCP argument.
        entry: dict[str, Any] = {"kind": str(origin["kind"]), "value_sha256": value_digest(value)}
        for key in ("actor_user_id", "definition_revision"):
            if origin.get(key) is not None:
                entry[key] = origin[key]
        if origin.get("reference"):
            entry.update(_reference(str(origin["reference"])))
        typed = cast(dict[str, Any], value)
        if typed.get("type") in {"File", "Document"} and isinstance(typed.get("value"), str):
            uri = str(typed["value"])
            entry["resource"] = {**_reference(uri), **(metadata or {}).get(uri, {})}
            if uri in conversions:
                conversion = deepcopy(conversions[uri])
                conversion["source"] = _reference(str(conversion["source"]["reference"]))
                entry["resource"]["conversion"] = conversion
        old = current.get(name)
        if old is not None and {key: item for key, item in old.items() if key != "recorded_at"} == entry:
            continue
        entry["recorded_at"] = now
        current[name] = changes[name] = entry
    if not changes:
        return
    run.input_provenance = current
    # Dedicated readers retrieve this event; ordinary run/event projections exclude it.
    db.add(ProcessRunEvent(run_id=run.id, source="native", event_type=PROVENANCE_EVENT,
        payload={"changes": changes}))


async def read_input_provenance(identity: UUID, actor: int | AgentManagementScope, name: str, *,
                                 before: int | None = None, history: bool = False, page_size: int = 50,
                                 metadata_only: bool = False) -> dict[str, Any]:
    from .native_runs import require_run
    run = await require_run(identity, actor)
    # Source context can be private to the launcher even when the Process is shared.
    if isinstance(actor, int):
        if actor != run.launcher_agent_id:
            raise PermissionError("Input origins belong to the launching agent")
    else:
        actor.require(run.launcher_agent_id)
    graph = run.launch_snapshot.get("definition", {}).get("graph", {})
    names: list[str] = next((cast(list[str], node.get("inputs", [])) for node in graph.get("nodes", []) if node.get("kind") == "start"), list[str]())
    if name not in names:
        raise LookupError("Selected input not found")
    if not 1 <= page_size <= 500:
        raise ValueError("Invalid provenance page size")
    if metadata_only:
        return {"name": name}
    access: dict[str, bool] = {}
    if not history:
        value = await get_db().scalar(select(ProcessRun.input_provenance[name]).where(ProcessRun.id == identity))
        if value is not None and (name not in run.input or value.get("value_sha256") != value_digest(run.input[name])):
            value = None
        return {"name": name, "current": await _visible_origin(value, run, actor, access), "historical": False}
    statement = select(ProcessRunEvent).where(ProcessRunEvent.run_id == identity,
        ProcessRunEvent.event_type == PROVENANCE_EVENT, func.jsonb_exists(ProcessRunEvent.payload["changes"], name))
    if before is not None:
        statement = statement.where(ProcessRunEvent.id < before)
    rows = list(await get_db().scalars(statement.order_by(ProcessRunEvent.id.desc()).limit(page_size + 1)))
    entries = rows[:page_size]
    return {"name": name, "entries": [{"event": item.id, "origin": await _visible_origin(item.payload["changes"][name], run, actor, access)} for item in entries],
        "next_before": entries[-1].id if len(rows) > page_size else None, "historical": True}


async def _visible_origin(value: dict[str, Any] | None, run: ProcessRun, actor: int | AgentManagementScope,
                           access: dict[str, bool]) -> dict[str, Any] | None:
    if value is None:
        return None
    from app.file_share import ResourceContext
    from app.file_share.facade import can_inspect_source
    result = deepcopy(value)
    context = ResourceContext(agent_id=run.launcher_agent_id, runtime="internal",
        management_scope=None if isinstance(actor, int) else actor)
    pending: list[dict[str, Any]] = [result]
    while pending:
        part = pending.pop()
        if isinstance(part.get("resource"), dict):
            pending.append(part["resource"])
        if isinstance(part.get("conversion"), dict):
            pending.append(part["conversion"]["source"])
        if part.get("reference"):
            reference = str(part["reference"])
            if reference not in access and len(access) < 16:
                try:
                    async with asyncio.timeout(2):
                        access[reference] = await can_inspect_source(context, reference)
                except TimeoutError as error:
                    await get_db().rollback()
                    raise ProvenanceUnavailable("Input provenance is temporarily unavailable; retry this read") from error
                except (LookupError, PermissionError, ValueError, OSError, RuntimeError, HTTPError):
                    access[reference] = False
            if access.get(reference, False):
                part["accessible"] = True
            else:
                # A Process grant never reveals a revoked source reference or metadata.
                if part is result:
                    part.pop("reference", None)
                    part["accessible"] = False
                else:
                    part.clear()
                    part["accessible"] = False
    return result
