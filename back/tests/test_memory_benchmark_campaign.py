"""Opt-in measurement campaign; ordinary pytest runs retain a small DB smoke test."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import mean

import pytest
from sqlalchemy import event, select, text

from app.memory.models import MemoryItem
from core.database import engine, get_db_session
from core.params import RuntimeSettings, runtime_settings
from scripts.memory_benchmark.experiments import VARIANTS
from scripts.memory_benchmark.generate import Corpus, generate
from scripts.memory_benchmark.io import load
from scripts.memory_benchmark.score import observations, score
from scripts.memory_benchmark.validate import validate
from tests.memory_benchmark_adapter import CURRENT, fixture_identity, install_adapter, load_world, observe
from tests.memory_benchmark_reference import reference_fingerprints


def select_worlds(corpus, limit):
    if limit < 0:
        raise ValueError("World limit must be nonnegative")
    by_profile = defaultdict(list)
    world_queries = defaultdict(list)
    for q in corpus.queries:
        world_queries[q.world_id].append(q)
    for world, queries in world_queries.items():
        by_profile[(queries[0].domain, queries[0].profile)].append(world)
    domains = sorted({domain for domain, _ in by_profile})
    queues = {}
    for domain in domains:
        profiles = [worlds for (d, _), worlds in by_profile.items() if d == domain]
        queues[domain] = [worlds[i] for i in range(max(map(len, profiles))) for worlds in profiles if i < len(worlds)]
    ordered = [queues[d][i] for i in range(max(map(len, queues.values()))) for d in domains if i < len(queues[d])]
    selected = set(ordered[:limit] if limit else ordered)
    queries = tuple(q for q in corpus.queries if q.world_id in selected)
    query_ids = {q.id for q in queries}
    return Corpus(tuple(m for m in corpus.memories if m.world_id in selected), queries,
                  tuple(a for a in corpus.answers if a.query_id in query_ids))


def profile_sample(corpus):
    worlds = defaultdict(dict)
    for q in corpus.queries:
        worlds[(q.domain, q.profile)].setdefault(q.world_id, q)
    selected = {list(rows)[index % len(rows)] for index, (_, rows) in enumerate(sorted(worlds.items()))}
    queries = tuple(q for q in corpus.queries if q.world_id in selected)
    qids = {q.id for q in queries}
    return Corpus(tuple(m for m in corpus.memories if m.world_id in selected), queries,
                  tuple(a for a in corpus.answers if a.query_id in qids))


def test_profile_sample_keeps_whole_worlds_and_covers_profiles_and_calendar_regimes():
    corpus = generate(repetitions=5, distractors=0,
                      profile_keys=("manufacturing", "craft", "family", "sports", "repair_cafe"))
    sample = profile_sample(corpus)
    assert {q.profile for q in sample.queries} == {q.profile for q in corpus.queries}
    assert len(sample.queries) == 5 * 132
    assert len({q.timestamp for q in sample.queries}) == 5
    for world in {q.world_id for q in sample.queries}:
        assert {q.id for q in sample.queries if q.world_id == world} == {q.id for q in corpus.queries if q.world_id == world}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _p95(values):
    return sorted(values)[max(0, math.ceil(len(values) * .95) - 1)] if values else None


def source_fingerprints(reference_sources=None):
    current = {str(path): hashlib.sha256((Path(__file__).parents[1] / path).read_bytes()).hexdigest()
            for path in (Path("app/memory/retrieval.py"), Path("app/memory/context.py"),
                         Path("app/memory/service.py"), Path("app/memory/admission.py"),
                         Path("app/memory/access.py"), Path("app/memory/source_access.py"),
                         Path("app/memory/goal_folders.py"), Path("app/memory/library_queries.py"),
                         Path("app/memory/bootstrap.py"), Path("app/agent/context.py"),
                         Path("app/memory/relevance.py"), Path("app/memory/models.py"),
                         Path("app/memory/lexical_normalization.py"),
                         Path("app/file_share/catalogue.py"),
                         Path("tests/memory_benchmark_adapter.py"),
                         Path("tests/memory_benchmark_reference.py"),
                         Path("tests/test_memory_benchmark_campaign.py"),
                         Path("scripts/memory_benchmark/experiments.py"))}
    return {**current, **(reference_fingerprints(reference_sources) if reference_sources else {})}


async def run_campaign(corpus, output, variants, workers, monkeypatch, root, reference_sources=None):
    fingerprints = source_fingerprints(reference_sources)
    validate(corpus)
    if not variants or set(variants) - set(VARIANTS) or len(set(variants)) != len(variants):
        raise ValueError("Invalid or duplicate variants")
    if not 1 <= workers <= 8:
        raise ValueError("Use 1..8 workers")
    if output.exists() or output.is_symlink():
        raise ValueError("Campaign output must be a new directory")
    output.resolve().relative_to(Path("/repo/artifacts").resolve())
    output.mkdir(parents=True)
    if ('previous' in variants) != (reference_sources is not None):
        raise ValueError('Previous algorithm requires frozen reference sources')
    install_adapter(monkeypatch, root, reference_sources)
    defaults = RuntimeSettings()
    for key in type(defaults).model_fields:
        if key.startswith(("MEMORY_CONTEXT_", "MEMORY_RECALL_", "MEMORY_TEMPORAL_")):
            monkeypatch.setattr(runtime_settings, key, getattr(defaults, key))
    user_id, title_id = await fixture_identity()
    by_world, memory_worlds = defaultdict(list), defaultdict(list)
    for q in corpus.queries:
        by_world[q.world_id].append(q)
    for m in corpus.memories:
        memory_worlds[m.world_id].append(m)
    semaphore = asyncio.Semaphore(workers)
    started = time.perf_counter()
    snapshots = {}

    async def prepare(world):
        async with semaphore:
            snapshots[world] = await load_world(tuple(memory_worlds[world]), tuple(by_world[world]), root,
                                                user_id=user_id, title_id=title_id)
    await asyncio.gather(*(prepare(world) for world in by_world))
    async with get_db_session() as db:
        await db.execute(text("ANALYZE memory_items"))
        await db.execute(text("ANALYZE memory_sources"))
    loaded_ms = (time.perf_counter() - started) * 1000
    records, details = {v: [] for v in variants}, {v: [] for v in variants}
    streams = {v: (output / f"{v}-observations.jsonl").open("w", encoding="utf-8") for v in variants}
    detail_streams = {v: (output / f"{v}-trace.jsonl").open("w", encoding="utf-8") for v in variants}
    completed = 0

    def sql_counter(*_args):
        trace = CURRENT.get()
        if trace is not None:
            trace.sql_count += 1
    event.listen(engine.sync_engine, "before_cursor_execute", sql_counter)

    async def world_run(world):
        nonlocal completed
        async with semaphore:
            async with get_db_session() as db:
                for q in by_world[world]:
                    # Rotate order, so the baseline is not systematically the
                    # first/cold call. Every variant sees the same immutable fixture.
                    offset = int(q.id.replace("-", "")[:8], 16) % len(variants)
                    for variant in (*variants[offset:], *variants[:offset]):
                        observation, detail = await observe(q, variant, snapshots[world], db)
                        if len(observation["injected"]) > defaults.MEMORY_CONTEXT_MAX_ITEMS:
                            raise AssertionError("Context item budget exceeded")
                        if detail["memory_brief_chars"] > defaults.MEMORY_CONTEXT_MAX_CHARS:
                            raise AssertionError("Memory character budget exceeded")
                        records[variant].append(observation)
                        details[variant].append(detail)
                        streams[variant].write(json.dumps(observation, ensure_ascii=False) + "\n")
                        detail_streams[variant].write(json.dumps(detail, ensure_ascii=False) + "\n")
                    await db.rollback()  # Release read locks and discard the root transaction.
                    completed += 1
                for stream in (*streams.values(), *detail_streams.values()):
                    stream.flush()
                _write_json(output / "progress.json", {"complete": False, "completed_queries": completed,
                                                       "total_queries": len(corpus.queries), "variants": variants,
                                                       "elapsed_seconds": time.perf_counter() - started})
                print(json.dumps({"benchmark_progress": completed, "total": len(corpus.queries),
                                  "elapsed_seconds": round(time.perf_counter() - started, 1)}), flush=True)
    try:
        await asyncio.gather(*(world_run(world) for world in by_world))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", sql_counter)
        for stream in (*streams.values(), *detail_streams.values()):
            stream.close()
    summaries = {}
    reports = {}
    for variant in variants:
        report, per_query = score(corpus, observations(records[variant]), k=defaults.MEMORY_CONTEXT_MAX_ITEMS,
                                  stages=("retrieved", "injected"))
        reports[variant] = report
        _write_json(output / f"{variant}-report.json", report)
        _write_jsonl(output / f"{variant}-per-query.jsonl", (asdict(r) for r in per_query))
        answer_by_id = {a.query_id: a for a in corpus.answers}
        positives = [row for row in records[variant] if answer_by_id[row["query_id"]].required]
        candidate_complete = sum(all(set(g.any_of) & set(row["candidates"]) for g in answer_by_id[row["query_id"]].required)
                                 for row in positives) / len(positives)
        detail_rows = details[variant]
        summaries[variant] = {
            "retrieved": report["stages"]["retrieved"]["overall"],
            "injected": report["stages"]["injected"]["overall"],
            "complete_facet_availability_in_candidate_union": candidate_complete,
            "latency_p95_ms": _p95([r["latency_ms"] for r in records[variant]]),
            "mean_sql_statements": mean(r["sql_count"] for r in detail_rows),
            "mean_search_calls": mean(len(r["searches"]) for r in detail_rows),
            "mean_memory_context_chars": mean(r["memory_context_chars"] for r in detail_rows),
            "max_memory_brief_chars": max(r["memory_brief_chars"] for r in detail_rows),
            "retrieval_modes": dict(Counter(s["mode"] for r in detail_rows for s in r["searches"])),
            "degradation_reasons": dict(Counter(s["reason"] for r in detail_rows for s in r["searches"])),
            "queries_with_provider_errors": sum(bool(r["provider_errors"]) for r in detail_rows),
            "provider_errors": dict(Counter(str(v) for r in detail_rows for v in r["provider_errors"].values())),
            "calendar_saturated_queries": sum(len(r["upcoming_ids"]) >= defaults.MEMORY_CONTEXT_MAX_ITEMS for r in detail_rows),
        }
    if source_fingerprints(reference_sources) != fingerprints:
        raise RuntimeError("Benchmark source changed during campaign; observations remain diagnostic only")
    manifest = {
        "complete": True, "synthetic": True, "engine": "Galaris actual lexical fallback and agent context capsule",
        "queries": len(corpus.queries), "memories": len(corpus.memories), "worlds": len(by_world),
        "domains": dict(Counter(q.domain for q in corpus.queries)), "variants": variants, "workers": workers,
        "memory_item_budget": defaults.MEMORY_CONTEXT_MAX_ITEMS, "memory_char_budget": defaults.MEMORY_CONTEXT_MAX_CHARS,
        "candidate_limit_per_search": defaults.MEMORY_RECALL_CANDIDATE_LIMIT,
        "parameters": {k: getattr(defaults, k) for k in type(defaults).model_fields
                       if k.startswith(("MEMORY_CONTEXT_", "MEMORY_RECALL_", "MEMORY_TEMPORAL_"))},
        "source_sha256": fingerprints,
        "fixture_loading_ms": loaded_ms, "elapsed_seconds": time.perf_counter() - started,
        "results": summaries,
        "limitations": ["No real embedding model, vector index or generated final LLM response was evaluated.",
                        "History enters the real AgentContextRequest boundary; messaging transport/scheduler are not run.",
                        "Experiments use message/history/declared language/timezone/time and admitted hits, never expected facts or family/split/surface labels.",
                        "Structured episode dates and source languages are copied from synthetic input metadata.",
                        "Every world deliberately has more upcoming calendar matches than the context item budget.",
                        "All selected worlds are loaded before measurement; database indexes contain their combined rows.",
                        "Latency includes shared load at the reported concurrency; token counts are not estimated from characters.",
                        "Ordinary retrieved ranking and final injected context are separate; candidates are an unordered channel union.",
                        "Observed context is the real driver-neutral prepared payload, not proof of model attention or answer quality.",
                        "Provider failures are observed empty contexts and recall misses; all failed cases remain in denominators and errors are counted."],
    }
    _write_json(output / "campaign.json", manifest)
    _write_json(output / "progress.json", {"complete": True, "completed_queries": completed,
                                           "total_queries": len(corpus.queries), "variants": variants})
    # Deterministic review candidates: both successful and failing examples where
    # available, balanced by domain/family/language. These are not human verdicts.
    qmap = {q.id: q for q in corpus.queries}
    amap = {a.query_id: a for a in corpus.answers}
    variant = "combined" if "combined" in variants else variants[0]
    rmap = {r["query_id"]: r for r in details[variant]}
    buckets = defaultdict(list)
    for row in records[variant]:
        q, a = qmap[row["query_id"]], amap[row["query_id"]]
        complete = all(set(g.any_of) & set(row["injected"]) for g in a.required) if a.required else None
        buckets[(q.domain, q.family, q.language, complete)].append(row)
    review = []
    for key, rows in sorted(buckets.items(), key=lambda item: str(item[0])):
        row = min(rows, key=lambda r: r["query_id"])
        q, a = qmap[row["query_id"]], amap[row["query_id"]]
        review.append({"domain": q.domain, "family": q.family, "language": q.language,
                       "query_id": q.id, "message": q.message, "history": q.history,
                       "required": [asdict(g) for g in a.required], "mode": a.response_mode,
                       "injected": row["injected"], "excerpts": rmap[q.id]["excerpts"],
                       "review_status": "pending-human-review"})
    _write_jsonl(output / "review-candidates.jsonl", review)
    return manifest


@pytest.mark.asyncio
async def test_campaign_on_synthetic_corpus(request, monkeypatch, tmp_path):
    corpus_path = request.config.getoption("--memory-benchmark-corpus", default="")
    if not corpus_path:
        pytest.skip("Opt-in campaign: load tests.memory_benchmark_plugin and supply a synthetic corpus/output")
    output = Path(request.config.getoption("--memory-benchmark-output"))
    full_corpus = load(Path(corpus_path))
    sampled = request.config.getoption("--memory-benchmark-profile-sample")
    selected = profile_sample(full_corpus) if sampled else select_worlds(full_corpus, request.config.getoption("--memory-benchmark-worlds"))
    shards = request.config.getoption("--memory-benchmark-shards")
    shard = request.config.getoption("--memory-benchmark-shard")
    if not 1 <= shards <= 16 or not 0 <= shard < shards:
        raise ValueError("Invalid database partition")
    worlds = list(dict.fromkeys(q.world_id for q in selected.queries))
    world_set = set(worlds[shard::shards])
    qids = {q.id for q in selected.queries if q.world_id in world_set}
    selected = Corpus(tuple(m for m in selected.memories if m.world_id in world_set),
                      tuple(q for q in selected.queries if q.id in qids),
                      tuple(a for a in selected.answers if a.query_id in qids))
    variants = tuple(request.config.getoption("--memory-benchmark-variants").split(","))
    reference = request.config.getoption("--memory-benchmark-reference")
    manifest = await run_campaign(selected, output, variants, request.config.getoption("--memory-benchmark-workers"),
                                  monkeypatch, tmp_path / "resources", Path(reference) if reference else None)
    manifest["corpus_manifest_sha256"] = hashlib.sha256((Path(corpus_path) / "manifest.json").read_bytes()).hexdigest()
    manifest["shards"] = shards
    manifest["shard"] = shard
    manifest["sampling"] = "one-world-per-profile-rotating-calendar" if sampled else "world-limit"
    _write_json(output / "campaign.json", manifest)


@pytest.mark.asyncio
async def test_real_adapter_preserves_scope_clock_and_context_budget(monkeypatch, tmp_path, db):
    from scripts.memory_benchmark.score import observations as parse

    install_adapter(monkeypatch, tmp_path / "resources")
    user_id, title_id = await fixture_identity()
    corpus = generate(repetitions=1, distractors=2, profile_keys=("family",))
    agent = await load_world(corpus.memories, corpus.queries, tmp_path / "resources",
                             user_id=user_id, title_id=title_id)
    query = next(q for q in corpus.queries if q.family == "implicit_person_event" and q.language == "fr")
    async with get_db_session() as db:
        first, details = await observe(query, "baseline", agent, db)
        repeated, _ = await observe(query, "baseline", agent, db)
        candidate, _ = await observe(query, "combined", agent, db)
        assert first["injected"] == repeated["injected"]
        assert len(first["injected"]) <= 8
        assert details["upcoming_ids"]
        assert all(s["mode"] == "lexical" for s in details["searches"])
        # Usage effects were rolled back, despite going through the real renderer.
        assert all(v == 0 for v in await db.scalars(select(MemoryItem.access_count).where(MemoryItem.owner_agent_id == agent.id)))
    for row in (first, candidate):
        report, _ = score(corpus, parse([row]), stages=("injected",))
        assert report["stages"]["injected"]["overall"]["queries_with_forbidden_ids"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("calendar_regime", range(5))
async def test_scenario_clock_reaches_final_admission_of_current_and_expired_facts(monkeypatch, tmp_path, db, calendar_regime):
    from app.memory import search_memory_detailed
    from tests.memory_benchmark_adapter import Trace

    install_adapter(monkeypatch, tmp_path / "resources")
    user_id, title_id = await fixture_identity()
    complete = generate(repetitions=5, distractors=0, profile_keys=("family",))
    world = list(dict.fromkeys(q.world_id for q in complete.queries))[calendar_regime]
    corpus = Corpus(tuple(m for m in complete.memories if m.world_id == world),
                    tuple(q for q in complete.queries if q.world_id == world),
                    tuple(a for a in complete.answers if a.query_id in {q.id for q in complete.queries if q.world_id == world}))
    agent = await load_world(corpus.memories, corpus.queries, tmp_path / "resources", user_id=user_id, title_id=title_id)
    query = next(q for q in corpus.queries if q.family == "correction" and q.language == "fr")
    current = next(m for m in corpus.memories if m.language == "fr" and m.valid_from and not m.valid_until)
    expired = next(m for m in corpus.memories if m.language == "fr" and m.valid_until)
    token = CURRENT.set(Trace(query, "baseline"))
    try:
        async with get_db_session():
            page = await search_memory_detailed(current.title, agent_id=agent.id)
            assert current.id in {str(h.item.id) for h in page.hits}
            old = await search_memory_detailed(expired.title, agent_id=agent.id)
            assert expired.id not in {str(h.item.id) for h in old.hits}
    finally:
        CURRENT.reset(token)


@pytest.mark.asyncio
async def test_provider_failure_is_an_observed_miss_with_no_stale_memory(monkeypatch, tmp_path, db):
    from app.agent.contracts import AgentContextContribution
    from sqlalchemy.exc import CompileError

    install_adapter(monkeypatch, tmp_path / "resources")
    user_id, title_id = await fixture_identity()
    corpus = generate(repetitions=1, distractors=0, profile_keys=("family",))
    agent = await load_world(corpus.memories, corpus.queries, tmp_path / "resources", user_id=user_id, title_id=title_id)
    query = corpus.queries[0]

    async def failed_provider(_request) -> AgentContextContribution:
        raise CompileError("Synthetic provider failure")

    async with get_db_session() as session:
        previous, _ = await observe(query, "baseline", agent, session)
        assert previous["injected"]
        from app.agent.context import register_context_provider
        register_context_provider("long_term_memory", failed_provider, priority=20)
        failed, trace = await observe(query, "baseline", agent, session)
    assert failed["injected"] == []
    assert trace["provider_errors"] == {"long_term_memory_error": "CompileError"}
    _, scored = score(corpus, observations([failed]), stages=("injected",))
    row = next(r for r in scored if r.query_id == query.id)
    assert row.observed and row.recall == 0 and row.complete is False
