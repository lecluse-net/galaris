"""Opt-in paired measurements of real admission and ranked browsing in test DB."""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median
import time
from datetime import datetime

import pytest
from sqlalchemy import event, insert, select, text
from sqlalchemy.orm import selectinload

from app.memory import admission, service
from app.memory.access import effective_access
from app.memory.models import MemoryItem, MemorySource
from app.memory.schemas import (
    MemoryItemCreate, MemoryItemUpdate, MemoryLinkCreate, MemoryPayload,
    MemorySearchHit, MemorySearchRequest, MemoryTraversalStep,
)
from app.memory.tests.conftest import agents, memory_storage  # noqa: F401
from tests.memory_benchmark_adapter import assert_isolated
from tests.memory_benchmark_reference import load_reference, reference_fingerprints


def identity(hit):
    item = hit.item
    return (item.id, item.revision, item.lock_version, item.content_hash,
            item.semantic_fingerprint, hit.excerpt,
            tuple((step.source_item_id, step.target_item_id, step.relation_type) for step in hit.structural_path))


def quantile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


@pytest.mark.asyncio
async def test_paired_admission_benchmark(request, db, agents, memory_storage):
    reference = request.config.getoption("--memory-benchmark-reference", default="")
    output = request.config.getoption("--memory-benchmark-output", default="")
    if not reference or not output:
        pytest.skip("Opt-in: supply synthetic benchmark reference/output via tests.memory_benchmark_plugin")
    assert_isolated()
    repeats = request.config.getoption("--memory-benchmark-repeats")
    if not 10 <= repeats <= 200:
        raise ValueError("Use 10..200 paired measurements")
    destination = Path(output)
    destination.resolve().relative_to(Path("/repo/artifacts/memory-benchmark").resolve())
    if destination.exists():
        raise ValueError("Benchmark output must be new")
    destination.mkdir(parents=True)
    previous = load_reference(Path(reference), datetime)
    if "admission" not in previous:
        raise ValueError("Admission comparison requires a frozen admission.py")
    fingerprints = reference_fingerprints(Path(reference))
    measurement_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    current_sources = {name: hashlib.sha256((Path(__file__).parents[1] / "app/memory" / name).read_bytes()).hexdigest()
                       for name in ("admission.py", "service.py")}
    owner, peer = agents

    async def hit(item, actor=owner):
        return MemorySearchHit(item=service.item_to_public(item, await effective_access(item, actor.id)),
                               excerpt=item.search_text, score=1.0)

    # A 6k-row corpus, half private to another agent, with actual source refs.
    background = []
    for index in range(6000):
        content = f"Synthetic measurement fact {index}."
        background.append(dict(owner_agent_id=owner.id if index % 2 == 0 else peer.id,
                               search_title=f"Synthetic measurement {index}", memory_resource_id=f"synthetic-{index}",
                               search_text=content, memory_content_hash=hashlib.sha256(content.encode()).hexdigest(),
                               memory_media_type="text/html"))
    await db.execute(insert(MemoryItem), background)
    owned = list((await db.scalars(select(MemoryItem).options(selectinload(MemoryItem.grants))
                                 .where(MemoryItem.owner_agent_id == owner.id)
                                 .order_by(MemoryItem.id).limit(500))).all())
    private = list((await db.scalars(select(MemoryItem).options(selectinload(MemoryItem.grants))
                                   .where(MemoryItem.owner_agent_id == peer.id)
                                   .order_by(MemoryItem.id).limit(24))).all())
    await db.execute(insert(MemorySource), [dict(item_id=item.id, source_kind="synthetic-benchmark",
                                               source_ref=f"synthetic-source-{index}") for index, item in enumerate(owned)])
    await db.execute(text("ANALYZE memory_items"))
    await db.execute(text("ANALYZE memory_sources"))
    current_hits = [await hit(item) for item in owned]
    private_hits = [await hit(item, peer) for item in private]
    cases = [(f"current_{size}", "admission", current_hits[:size], current_hits[:size])
             for size in (1, 8, 48, 100, 500)]
    invalid = [entry.model_copy(update={"item": entry.item.model_copy(update={"revision": 0})})
               for entry in current_hits[24:48]]
    cases.append(("mixed_acl_and_revision_72", "admission",
                  [*current_hits[:24], *private_hits, *invalid], current_hits[:24]))
    root, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Synthetic graph measurement root",
        payload=MemoryPayload(text="<p>A synthetic graph root.</p>"), media_type="text/html"))
    structural = []
    for entry in current_hits[:48]:
        await service.create_link(MemoryLinkCreate(
            source_item_id=root.id, target_item_id=entry.item.id, relation_type="related_to"),
            actor_agent_id=owner.id)
        structural.append(entry.model_copy(update={"structural_path": [MemoryTraversalStep(
            source_item_id=root.id, target_item_id=entry.item.id, relation_type="related_to")]}))
    for size in (8, 48):
        cases.append((f"structural_{size}", "admission", structural[:size], structural[:size]))
    await db.execute(text("ANALYZE memory_links"))
    controls = len(cases)
    # Two independently edited/deleted resources per iteration; permutations
    # are repeated measures, not independent production incidents.
    for index in range(repeats):
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Synthetic revision {index}",
            payload=MemoryPayload(text=f"<p>Synthetic endpoint {index} uses port 1111.</p>"), media_type="text/html"))
        stale = await hit(item)
        item = await service.update_item(item.id, MemoryItemUpdate(
            payload=MemoryPayload(text=f"<p>Synthetic endpoint {index} uses port 2222.</p>")), actor_agent_id=owner.id)
        valid = await hit(item)
        target, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Synthetic graph target {index}",
            payload=MemoryPayload(text=f"<p>Synthetic graph target fact {index}.</p>"), media_type="text/html"))
        source, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Synthetic graph source {index}",
            payload=MemoryPayload(text="<p>Synthetic graph source.</p>"), media_type="text/html"))
        await service.create_link(MemoryLinkCreate(source_item_id=source.id, target_item_id=target.id,
                                                  relation_type="related_to"), actor_agent_id=owner.id)
        direct = await hit(target)
        obsolete_path = direct.model_copy(update={"structural_path": [MemoryTraversalStep(
            source_item_id=source.id, target_item_id=target.id, relation_type="related_to")]})
        assert len(await admission.admit_search_hits(owner.id, [obsolete_path])) == 1
        await service.forget_item(source.id, actor_agent_id=owner.id)
        for reverse in (False, True):
            order = lambda old, new: [new, old] if reverse else [old, new]
            for kind, surface, old, new in (("revision", "admission", stale, valid),
                                           ("path", "admission", obsolete_path, direct),
                                           ("revision", "browse", stale, valid)):
                cases.append((f"overlap_{kind}_{surface}_{reverse}", surface, order(old, new), [new]))

    connection = await db.connection()
    sql_count = 0
    sql_ms = 0.0
    sql_started = 0.0
    measuring = None
    statements = {}
    cache_states = []
    def count(_conn, _cursor, statement, parameters, _context, _many):
        nonlocal sql_count, sql_started
        sql_count += 1
        sql_started = time.perf_counter()
        cache_states.append(str(getattr(_context, "cache_hit", None)))
        if measuring is not None and measuring[0] in ("current_48", "current_500", "structural_48") and "memory_items" in statement:
            statements[measuring] = (statement, parameters)
    def finished(*_args):
        nonlocal sql_ms
        sql_ms += (time.perf_counter() - sql_started) * 1000
    event.listen(connection.sync_connection, "before_cursor_execute", count)
    event.listen(connection.sync_connection, "after_cursor_execute", finished)
    rows = []
    try:
        # Controls have two warmups, then alternating paired repetitions.
        for name, surface, batch, expected in cases[:controls]:
            for version in ("previous", "baseline"):
                fn = previous["admission"].admit_search_hits if version == "previous" else admission.admit_search_hits
                for _ in range(2):
                    assert {identity(h) for h in await fn(owner.id, batch)} == {identity(h) for h in expected}
        expanded = [case for case in cases[:controls] for _ in range(repeats)] + cases[controls:]
        for index, (name, surface, batch, expected) in enumerate(expanded):
            expected_keys = {identity(entry) for entry in expected}
            for version in (("previous", "baseline") if index % 2 == 0 else ("baseline", "previous")):
                measuring = (name, version)
                before = sql_count
                before_cache_states = len(cache_states)
                before_sql_ms = sql_ms
                started = time.perf_counter()
                if surface == "admission":
                    fn = previous["admission"].admit_search_hits if version == "previous" else admission.admit_search_hits
                    result = await fn(owner.id, batch)
                else:
                    fn = previous["service"].search_items if version == "previous" else service.search_items
                    result = (await fn(MemorySearchRequest(agent_id=owner.id, query="synthetic"),
                                       ranked_hits=batch, record_llm_access=False)).hits
                elapsed = (time.perf_counter() - started) * 1000
                actual = {identity(entry) for entry in result}
                row = {"scenario": name, "version": version, "latency_ms": elapsed,
                       "sql_ms": sql_ms - before_sql_ms,
                       "sql_cache_states": cache_states[before_cache_states:],
                       "sql_count": sql_count - before, "input_hits": len(batch),
                       "expected_hits": len(expected), "returned_hits": len(result),
                       "invalid_hits": sum(identity(entry) not in expected_keys for entry in result),
                       "valid_recall": len(actual & expected_keys) / len(expected_keys),
                       "exact_result": actual == expected_keys and len(result) == len(expected)}
                if version == "baseline":
                    assert row["exact_result"], row
                rows.append(row)
            if index % 30 == 0:
                print(json.dumps({"admission_measurements": len(rows), "last_scenario": name}), flush=True)
        measuring = None
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", count)
        event.remove(connection.sync_connection, "after_cursor_execute", finished)
    # Diagnostic plans execute only bounded read queries in the test database,
    # after the measured calls. They do not enter the latency distributions.
    plans = {}
    for (name, version), (statement, parameters) in statements.items():
        plans[f"{name}/{version}"] = (await connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
        )).scalar_one()
    summaries = {}
    for name in sorted({row["scenario"] for row in rows}):
        summaries[name] = {}
        for version in ("previous", "baseline"):
            selected = [row for row in rows if row["scenario"] == name and row["version"] == version]
            latencies = [row["latency_ms"] for row in selected]
            summaries[name][version] = dict(measurements=len(selected), p50_ms=median(latencies),
                p95_ms=quantile(latencies, .95), mean_sql_count=mean(row["sql_count"] for row in selected),
                p50_sql_ms=median(row["sql_ms"] for row in selected),
                p50_outside_sql_ms=median(row["latency_ms"] - row["sql_ms"] for row in selected),
                sql_cache_states=dict(Counter(state for row in selected for state in row["sql_cache_states"])),
                wrong_results=sum(not row["exact_result"] for row in selected),
                invalid_hits=sum(row["invalid_hits"] for row in selected),
                mean_valid_recall=mean(row["valid_recall"] for row in selected))
    assert reference_fingerprints(Path(reference)) == fingerprints
    assert current_sources == {name: hashlib.sha256((Path(__file__).parents[1] / "app/memory" / name).read_bytes()).hexdigest()
                               for name in current_sources}
    provenance = Path(reference) / "provenance.json"
    report = dict(synthetic=True, complete=True, background_rows=6000, repeats=repeats, workers=1,
                  warmups_per_control_and_version=2,
                  measurement_source_sha256=measurement_source_sha256,
                  reference_provenance=json.loads(provenance.read_text()) if provenance.exists() else None,
                  current_sources=current_sources,
                  reference_sources=fingerprints, summaries=summaries,
                  limitations=["Designed stress cases do not estimate production incidence.",
                               "No embeddings or final generated answers; latency is measured on a development host."])
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (destination / "measurements.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (destination / "plans.json").write_text(json.dumps(plans, indent=2) + "\n")
    print(json.dumps(report["summaries"], indent=2), flush=True)
