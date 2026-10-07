"""Merge complete isolated database partitions, rejecting incomplete comparisons."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any, cast

from .io import json_records, load
from .generate import Corpus
from .score import Result, observations, score


# Dynamic boundary: campaign JSON contains nested operational measurements and
# scorer reports. Corpus/query/result objects retain their typed contracts.
JsonMap = dict[str, Any]


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _lines(path: Path, rows: Iterable[object]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _paired(results: dict[str, dict[str, Result]]) -> JsonMap:
    paired: JsonMap = {}
    for variant, rows in results.items():
        comparison: JsonMap = {}
        for reference in ("previous", "baseline", "relevance_first"):
            if reference == variant or reference not in results or variant == "previous":
                continue
            counts: Counter[str] = Counter()
            complete_counts: Counter[str] = Counter()
            families: defaultdict[str, Counter[str]] = defaultdict(Counter)
            for identity, row in rows.items():
                previous = results[reference][identity]
                if not row.answerable or row.recall is None:
                    continue
                if previous.recall is None:
                    raise ValueError("Inconsistent paired recall availability")
                outcome = "improved" if row.recall > previous.recall else "regressed" if row.recall < previous.recall else "unchanged"
                complete_outcome = "improved" if row.complete and not previous.complete else "regressed" if previous.complete and not row.complete else "unchanged"
                counts[outcome] += 1
                complete_counts[complete_outcome] += 1
                families[row.family][outcome] += 1
            comparison[reference] = {"facet_recall_changes": dict(counts),
                                     "complete_recall_changes": dict(complete_counts),
                                     "by_family": {k: dict(v) for k, v in sorted(families.items())}}
        paired[variant] = comparison
    return paired


def checked_manifests(paths: list[Path], corpus_hash: str) -> list[JsonMap]:
    manifests = [cast(JsonMap, json.loads((path / "campaign.json").read_text(encoding="utf-8"))) for path in paths]
    if not manifests:
        raise ValueError("No database partitions")
    first = manifests[0]
    matching = ("engine", "variants", "workers", "memory_item_budget", "memory_char_budget",
                "parameters", "source_sha256", "shards", "corpus_manifest_sha256", "sampling")
    for manifest in manifests:
        if not manifest.get("complete") or not manifest.get("synthetic") or manifest.get("diagnostic_only"):
            raise ValueError("Incomplete or diagnostic partition")
        if manifest.get("corpus_manifest_sha256") != corpus_hash:
            raise ValueError("Corpus fingerprint mismatch")
        if any(manifest.get(key) != first.get(key) for key in matching):
            raise ValueError("Partition configurations or source fingerprints differ")
    shard_ids = [m["shard"] for m in manifests]
    if len(shard_ids) != first["shards"] or set(shard_ids) != set(range(first["shards"])):
        raise ValueError("Missing or duplicate database partitions")
    return manifests


def aggregate(corpus_path: Path, campaign_path: Path, output: Path, *, expected_queries: int | None = None) -> JsonMap:
    if output.exists() or output.is_symlink():
        raise ValueError("Aggregate output must be a new directory")
    corpus = load(corpus_path)
    corpus_hash = hashlib.sha256((corpus_path / "manifest.json").read_bytes()).hexdigest()
    paths = sorted(campaign_path.glob("shard-*"))
    manifests = checked_manifests(paths, corpus_hash)
    if expected_queries is not None:
        ids = {str(row["query_id"]) for path in paths
               for row in json_records(path / f"{manifests[0]['variants'][0]}-observations.jsonl")}
        selected = tuple(q for q in corpus.queries if q.id in ids)
        worlds = {q.world_id for q in selected}
        if len(selected) != expected_queries or ids != {q.id for q in selected}:
            raise ValueError("Unexpected sample query coverage")
        if {q.id for q in corpus.queries if q.world_id in worlds} != ids:
            raise ValueError("Sample must contain complete worlds")
        if manifests[0].get("sampling") == "one-world-per-profile-rotating-calendar":
            if {q.profile for q in selected} != {q.profile for q in corpus.queries} or len(worlds) != len({q.profile for q in selected}):
                raise ValueError("Profile sample does not cover exactly one world per profile")
        corpus = Corpus(tuple(m for m in corpus.memories if m.world_id in worlds), selected,
                        tuple(a for a in corpus.answers if a.query_id in ids))
    if sum(m["queries"] for m in manifests) != len(corpus.queries):
        raise ValueError("Partitions do not cover the complete corpus")
    output.mkdir(parents=True)
    qmap = {q.id: q for q in corpus.queries}
    amap = {a.query_id: a for a in corpus.answers}
    summaries: dict[str, JsonMap] = {}
    paired_results: dict[str, dict[str, Result]] = {}
    retrieved_results: dict[str, dict[str, Result]] = {}
    variants = tuple(str(v) for v in manifests[0]["variants"])
    for variant in variants:
        rows = [cast(JsonMap, row) for path in paths for row in json_records(path / f"{variant}-observations.jsonl")]
        if len(rows) != len(qmap) or {r["query_id"] for r in rows} != set(qmap):
            raise ValueError(f"Missing, duplicate or unknown queries in {variant}")
        typed_report, results = score(corpus, observations(rows), k=manifests[0]["memory_item_budget"],
                                stages=("retrieved", "injected"))
        report = cast(JsonMap, typed_report)
        report["provenance"] = {"corpus_manifest_sha256": corpus_hash, "source_sha256": manifests[0]["source_sha256"],
                                "database_partitions": len(paths), "variant": variant}
        _write(output / f"{variant}-report.json", report)
        _lines(output / f"{variant}-observations.jsonl", rows)
        _lines(output / f"{variant}-per-query.jsonl", (asdict(r) for r in results))
        positives = [r for r in rows if amap[r["query_id"]].required]
        candidate_complete = mean(all(set(g.any_of) & set(r["candidates"]) for g in amap[r["query_id"]].required)
                                  for r in positives)
        sql: list[int] = []
        calls: list[int] = []
        chars: list[int] = []
        latencies = sorted(float(r["latency_ms"]) for r in rows)
        modes: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        error_queries = 0
        maximum_brief = 0
        saturated = 0
        trace_ids: set[str] = set()
        for path in paths:
            for raw in json_records(path / f"{variant}-trace.jsonl"):
                row = cast(JsonMap, raw)
                identity = row["query_id"]
                if identity in trace_ids or identity not in qmap:
                    raise ValueError("Duplicate or unknown trace")
                trace_ids.add(identity)
                sql.append(row["sql_count"])
                calls.append(len(row["searches"]))
                chars.append(row["memory_context_chars"])
                maximum_brief = max(maximum_brief, row["memory_brief_chars"])
                saturated += len(row["upcoming_ids"]) >= manifests[0]["memory_item_budget"]
                modes.update(str(s["mode"]) for s in row["searches"])
                reasons.update(str(s["reason"]) for s in row["searches"])
                error_queries += bool(row.get("provider_errors"))
                errors.update(str(value) for value in row.get("provider_errors", {}).values())
        if trace_ids != set(qmap):
            raise ValueError("Incomplete trace coverage")
        summaries[variant] = {
            "retrieved": report["stages"]["retrieved"]["overall"],
            "injected": report["stages"]["injected"]["overall"],
            "complete_facet_availability_in_candidate_union": candidate_complete,
            "latency_p95_ms": latencies[math.ceil(len(latencies) * .95) - 1],
            "latency_p50_ms": latencies[math.ceil(len(latencies) * .50) - 1],
            "latency_p99_ms": latencies[math.ceil(len(latencies) * .99) - 1],
            "mean_sql_statements": mean(sql), "mean_search_calls": mean(calls),
            "mean_memory_context_chars": mean(chars), "max_memory_brief_chars": maximum_brief,
            "retrieval_modes": dict(modes), "degradation_reasons": dict(reasons),
            "queries_with_provider_errors": error_queries, "provider_errors": dict(errors),
            "calendar_saturated_queries": saturated,
        }
        paired_results[variant] = {r.query_id: r for r in results if r.stage == "injected"}
        retrieved_results[variant] = {r.query_id: r for r in results if r.stage == "retrieved"}
    manifest = {
        "complete": True, "synthetic": True, "queries": len(corpus.queries), "memories": len(corpus.memories),
        "worlds": len({q.world_id for q in corpus.queries}), "variants": variants,
        "database_partitions": len(paths), "workers_per_partition": manifests[0]["workers"],
        "corpus_memories_per_partition": [m["memories"] for m in manifests],
        "memory_item_budget": manifests[0]["memory_item_budget"], "memory_char_budget": manifests[0]["memory_char_budget"],
        "parameters": manifests[0]["parameters"], "source_sha256": manifests[0]["source_sha256"],
        "corpus_manifest_sha256": corpus_hash, "results": summaries, "paired": _paired(paired_results),
        "paired_retrieved": _paired(retrieved_results),
        "limitations": [*manifests[0]["limitations"],
                        "Databases were partitioned and measured concurrently, not as one 56,000-memory index.",
                        "Only relevance_first/history/entities/time/combined experiments change calendar priority; baseline and previous preserve it.",
                        "Repeated templates/worlds are correlated; no independent-sample significance claim is made.",
                        "Review candidates are pending qualitative review, not independent human validation."],
    }
    _write(output / "campaign.json", manifest)
    buckets: dict[tuple[str, str, str, bool | None], JsonMap] = {}
    for path in paths:
        for raw in json_records(path / "review-candidates.jsonl"):
            row = cast(JsonMap, raw)
            key = (row["domain"], row["family"], row["language"],
                   all(set(g["any_of"]) & set(row["injected"]) for g in row["required"]) if row["required"] else None)
            if key not in buckets or row["query_id"] < buckets[key]["query_id"]:
                buckets[key] = row
    _lines(output / "review-candidates.jsonl", (buckets[k] for k in sorted(buckets, key=str)))
    lines = ["# Mesure du rappel mémoire Galaris", "",
             f"{len(corpus.queries):,} messages entièrement synthétiques ; {len(corpus.memories):,} souvenirs ; {len(variants)} variantes.", "",
             "Vraie recherche lexicale, contrôles d’accès, rendu mémoire et capsule de contexte. Aucun modèle vectoriel ni réponse finale LLM évalués.", "",
             "Tous les mondes saturent volontairement le calendrier. Ces taux décrivent ce test de résistance, pas la fréquence des erreurs en usage réel.", "",
             "| Variante | Rappel complet retrouvé | Rappel complet injecté | Rappel des facettes injectées | Requêtes SQL moyennes | Recherches moyennes | Latence p95 ms | Interdits injectés | Appels avec erreur |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for variant, s in summaries.items():
        i, r = s["injected"], s["retrieved"]
        lines.append(f"| {variant} | {r['complete_recall_at_k']:.1%} | {i['complete_recall_at_k']:.1%} | {i['facet_recall_at_k']:.1%} | {s['mean_sql_statements']:.1f} | {s['mean_search_calls']:.2f} | {s['latency_p95_ms']:.0f} | {i['forbidden_id_count_full_list']} | {s['queries_with_provider_errors']} |")
    lines += ["", "Budget commun : 8 souvenirs et 12 000 caractères de mémoire. Ordre des variantes alterné ; état réinitialisé entre appels.", "",
              "Comparer entities/time/history/combined à relevance_first permet de distinguer l’effet de recherche de celui de la priorité au contexte pertinent.", "",
              f"Mesure répartie sur {len(paths)} bases éphémères ; {manifests[0]['workers']} workers par base. La latence inclut cette charge partagée et ne prédit pas celle d’un index unique.", "",
              "Les rapports JSON détaillent domaines, familles, langues et partitions ; paired et paired_retrieved distinguent les gains et régressions du contexte et de la recherche sur les mêmes messages.", "",
              "review-candidates.jsonl contient les messages et extraits synthétiques pour revue. Les identifiants retrouvés ne suffisent pas à prouver la qualité des extraits ou de la réponse finale.", ""]
    (output / "rapport.md").write_text("\n".join(lines), encoding="utf-8")
    return {"output": str(output), "queries": len(corpus.queries), "variants": variants, "database_partitions": len(paths)}
