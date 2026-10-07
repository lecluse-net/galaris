"""The synthetic recall benchmark detects meaningful ranking and isolation failures."""

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts.memory_benchmark.generate import Corpus, FAMILIES, export, generate
from scripts.memory_benchmark.io import load
from scripts.memory_benchmark.score import Observation, observations, score
from scripts.memory_benchmark.validate import instant, validate


@pytest.fixture(scope="module")
def corpus():
    return generate(repetitions=1, distractors=4, profile_keys=("manufacturing", "accounting", "family", "sports"))


def _oracle_observations(corpus, stage="injected"):
    # A scoring calibration, explicitly not an engine result.
    return tuple(Observation(a.query_id, {stage: tuple(g.any_of[0] for g in a.required) + a.optional_ids},
                             a.response_mode, 3.0, 100.0) for a in corpus.answers)


def _case(corpus, family):
    q = next(q for q in corpus.queries if q.family == family and q.language == "fr")
    return q, next(a for a in corpus.answers if a.query_id == q.id)


def _overall(report, stage="injected"):
    return report["stages"][stage]["overall"]


def test_catalogue_has_balanced_domains_and_complete_scenarios(corpus):
    summary = validate(corpus)
    assert set(summary["domains"]) == {"enterprise", "independent", "personal", "association"}
    assert len(set(summary["domains"].values())) == 1
    assert summary["queries"] == 4 * len(FAMILIES) * 2 * 2
    assert {q.surface for q in corpus.queries} == {"plain", "paraphrase"}


@pytest.mark.parametrize("seed", [0, 19, 1847, 987654321])
def test_reproducible_export_roundtrip_and_settings_stay_in_one_split(tmp_path, seed):
    kwargs = dict(seed=seed, repetitions=2, distractors=7,
                  profile_keys=("manufacturing", "craft", "repair_cafe"))
    generated = generate(**kwargs)
    assert validate(generated)["valid"] is True
    assert generated == generate(**kwargs)
    assert {q.split for q in generated.queries} == {"development", "validation", "heldout"}
    assert "unaccented" in {q.surface for q in generated.queries}
    destination = tmp_path / "corpus"
    manifest = export(generated, destination, seed=seed, repetitions=2, distractors=7)
    assert load(destination) == generated
    assert manifest["synthetic"] is True
    with pytest.raises(ValueError, match="new directory"):
        export(generated, destination, seed=seed, repetitions=2, distractors=7)
    with (destination / "memories.jsonl").open("a") as stream:
        stream.write("{}\n")
    with pytest.raises(ValueError, match="Checksum"):
        load(destination)


def test_implicit_person_and_yesterday_case_needs_two_distinct_facts(corpus):
    query, answer = _case(corpus, "implicit_person_event")
    assert "me l'a offert hier" in query.message
    assert [group.facet for group in answer.required] == ["identity", "gift_yesterday"]
    memories = {m.id: m for m in corpus.memories}
    event = memories[answer.required[1].any_of[0]]
    assert instant(answer.temporal_start) <= instant(event.event_start) < instant(answer.temporal_end)
    zone = ZoneInfo(query.timezone)
    assert instant(event.recorded_at).astimezone(zone).date() != instant(event.event_start).astimezone(zone).date()


def test_yesterday_uses_calendar_day_across_dst_and_year_boundary():
    generated = generate(repetitions=5, distractors=0, profile_keys=("family",))
    validate(generated)
    durations = set()
    for q, a in zip(generated.queries, generated.answers, strict=True):
        if q.family == "timezone_boundary":
            durations.add((instant(a.temporal_end) - instant(a.temporal_start)).total_seconds() / 3600)
    assert durations == {23.0, 24.0, 25.0}
    assert any(q.timezone == "UTC" and q.timestamp.startswith("2029-01-01") for q in generated.queries)


def test_calibration_oracle_gets_full_recall_without_leaks(corpus):
    report, results = score(corpus, _oracle_observations(corpus))
    summary = _overall(report)
    assert summary["coverage"] == 1.0
    assert summary["facet_recall_at_k"] == summary["complete_recall_at_k"] == 1.0
    assert summary["ndcg_at_k"] == pytest.approx(1.0)
    assert summary["queries_with_forbidden_ids"] == 0
    assert summary["response_mode_accuracy"] == 1.0
    assert all(r.recall is None for r in results if not r.answerable)


def test_one_relevant_person_does_not_hide_missing_yesterday(corpus):
    query, answer = _case(corpus, "implicit_person_event")
    observed = (Observation(query.id, {"injected": (answer.required[0].any_of[0],)}, "answer", None, None),)
    report, results = score(corpus, observed)
    result = next(r for r in results if r.query_id == query.id)
    assert result.mrr == 1.0
    assert result.recall == 0.5
    assert result.complete is False and result.complete_mrr == 0.0
    assert _overall(report)["observed"] == 1
    assert _overall(report)["coverage"] < 0.01
    assert _overall(report)["complete_recall_at_k"] == 0.0


def test_different_stages_locate_loss_between_retrieval_and_injection(corpus):
    query, answer = _case(corpus, "implicit_person_event")
    all_ids = tuple(g.any_of[0] for g in answer.required)
    observed = (Observation(query.id, {"candidates": all_ids, "retrieved": all_ids,
                                      "injected": all_ids[:1]}, None, None, None),)
    _, results = score(corpus, observed)
    rows = {r.stage: r for r in results if r.query_id == query.id}
    assert rows["candidates"].recall == rows["retrieved"].recall == 1.0
    assert rows["injected"].recall == 0.5


@pytest.mark.parametrize("family,reason", [("contact_isolation", "access"), ("agent_isolation", "access"),
                                           ("revoked_access", "access"), ("forgotten_memory", "forgotten"),
                                           ("correction", "obsolete")])
def test_forbidden_fact_is_detected_even_beyond_top_k(corpus, family, reason):
    query, answer = _case(corpus, family)
    memories = {m.id: m for m in corpus.memories}
    def matches(identity):
        m = memories[identity]
        if family == "contact_isolation":
            return m.contact_scope not in (None, query.contact_id)
        if family == "agent_isolation":
            return m.state == "active" and query.actor_id not in m.allowed_actor_ids
        if family == "revoked_access":
            return m.state == "revoked"
        return True
    forbidden = next(i for i, r in answer.forbidden.items() if r == reason and matches(i))
    good = tuple(g.any_of[0] for g in answer.required)
    observed = (Observation(query.id, {"injected": good + (forbidden,)}, None, None, None),)
    _, results = score(corpus, observed, k=max(1, len(good)))
    row = next(r for r in results if r.query_id == query.id)
    assert row.violation_reasons == {reason: 1}
    assert row.forbidden_ids == (forbidden,)


def test_unknown_and_cross_world_ids_are_not_silently_accepted(corpus):
    query, answer = _case(corpus, "person_reference")
    other_world = next(m.id for m in corpus.memories if m.world_id != query.world_id)
    observed = (Observation(query.id, {"injected": (answer.required[0].any_of[0], other_world, "absent-id")},
                            None, None, None),)
    _, results = score(corpus, observed)
    row = next(r for r in results if r.query_id == query.id)
    assert row.recall == 1.0
    assert row.precision == pytest.approx(1 / 3)
    assert row.violation_reasons == {"world": 1, "unknown_id": 1}


def test_duplicate_results_consume_budget_without_inflating_recall(corpus):
    query, answer = _case(corpus, "implicit_person_event")
    first, second = (g.any_of[0] for g in answer.required)
    observed = (Observation(query.id, {"injected": (first, first, second)}, None, None, None),)
    _, results = score(corpus, observed, k=2)
    row = next(r for r in results if r.query_id == query.id)
    assert row.recall == row.precision == 0.5 and row.duplicate_count == 1


@pytest.mark.parametrize("family", ["location", "historical_state"])
def test_equivalent_fact_in_another_record_is_accepted(corpus, family):
    query, answer = _case(corpus, family)
    alternative = answer.required[0].any_of[-1]
    observed = (Observation(query.id, {"injected": (alternative,)}, None, None, None),)
    _, results = score(corpus, observed)
    row = next(r for r in results if r.query_id == query.id)
    assert row.recall == 1.0 and row.complete is True and not row.forbidden_ids


def test_observation_contract_rejects_duplicates_unknown_queries_and_invalid_measurements(corpus):
    query = corpus.queries[0]
    with pytest.raises(ValueError, match="Duplicate"):
        score(corpus, (Observation(query.id, {"injected": ()}, None, None, None),) * 2)
    with pytest.raises(ValueError, match="unknown"):
        score(corpus, (Observation("no-such-query", {"injected": ()}, None, None, None),))
    for value in (-1, float("nan"), True):
        with pytest.raises(ValueError, match="nonnegative"):
            observations([{"query_id": query.id, "injected": [], "latency_ms": value}])
    with pytest.raises(ValueError, match="JSON string"):
        observations([{"query_id": query.id, "injected": [None]}])


def test_validator_rejects_mutated_time_window_missing_acl_and_partition_leaks(corpus):
    query, answer = _case(corpus, "implicit_person_event")
    changed = replace(answer, temporal_start=(instant(answer.temporal_start) + timedelta(days=7)).isoformat(),
                      temporal_end=(instant(answer.temporal_end) + timedelta(days=7)).isoformat())
    broken = Corpus(corpus.memories, corpus.queries, tuple(changed if a.query_id == query.id else a for a in corpus.answers))
    with pytest.raises(ValueError, match="outside oracle"):
        validate(broken)
    changed = replace(answer, forbidden={})
    broken = replace(corpus, answers=tuple(changed if a.query_id == query.id else a for a in corpus.answers))
    with pytest.raises(ValueError, match="omits access"):
        validate(broken)
    changed_query = replace(query, split="heldout")
    broken = replace(corpus, queries=tuple(changed_query if q.id == query.id else q for q in corpus.queries))
    with pytest.raises(ValueError, match="crosses evaluation"):
        validate(broken)


def test_empty_run_is_not_a_success_and_requested_missing_stage_is_a_miss(corpus):
    report, _ = score(corpus, (), stages=("injected",))
    summary = _overall(report)
    assert summary["coverage"] == summary["facet_recall_at_k"] == 0.0
    report, _ = score(corpus, _oracle_observations(corpus, "retrieved"), stages=("injected",))
    assert _overall(report)["coverage"] == _overall(report)["facet_recall_at_k"] == 0.0


def test_reports_are_json_serializable_and_heldout_does_not_include_other_splits():
    generated = generate(repetitions=1, distractors=0, profile_keys=("manufacturing", "craft", "repair_cafe"))
    report, results = score(generated, _oracle_observations(generated), splits=("heldout",))
    assert {r.profile for r in results} == {"repair_cafe"}
    assert report["query_count"] == 132
    json.dumps(report, allow_nan=False)


def test_relative_date_prototype_uses_local_calendar_days_and_prior_week():
    from scripts.memory_benchmark.experiments import relative_window

    spring = relative_window("C'est elle qui me l'a offert hier", "2028-03-26T22:30:00+00:00", "Europe/Paris")
    assert spring.dates() == ("2028-03-26",)
    assert (spring.end.astimezone(ZoneInfo("UTC")) - spring.start.astimezone(ZoneInfo("UTC"))).total_seconds() == 23 * 3600
    week = relative_window("Find last week's discussion", "2028-11-06T05:30:00+00:00", "America/New_York")
    assert week.dates() == ("2028-10-30", "2028-10-31", "2028-11-01", "2028-11-02", "2028-11-03", "2028-11-04", "2028-11-05")
    assert relative_window("Retrouve l'ancien horaire", "2028-11-06T05:30:00+00:00", "America/New_York") is None


def test_query_prototype_uses_history_but_respects_an_explicit_topic_switch():
    from scripts.memory_benchmark.experiments import plan

    inputs = dict(history=("Oraline Vélor prepared the ochre notebook.",), timestamp="2028-03-27T00:30:00+00:00",
                  timezone="UTC")
    baseline = plan("baseline", message="She gave it to me yesterday.", baseline_query="She gave it to me yesterday.", **inputs)
    expanded = plan("combined", message="She gave it to me yesterday.", baseline_query="She gave it to me yesterday.", **inputs)
    assert baseline.entities == () and baseline.window is None and not baseline.relevant_first
    assert "Oraline Vélor" in expanded.lexical and "Oraline Vélor" in expanded.entities
    switched = plan("combined", message="New topic: how should I write to Bréliane Oméris?",
                    baseline_query="New topic: how should I write to Bréliane Oméris?", **inputs)
    assert "Oraline" not in switched.lexical and "Oraline Vélor" not in switched.entities


@pytest.mark.parametrize("defect", ("missing", "duplicate", "different_source", "different_corpus", "incomplete"))
def test_campaign_aggregation_rejects_invalid_comparisons(tmp_path, defect):
    from scripts.memory_benchmark.aggregate import checked_manifests

    paths = [tmp_path / "shard-0", tmp_path / "shard-1"]
    for index, path in enumerate(paths):
        path.mkdir()
        value = {"complete": True, "synthetic": True, "shards": 2, "shard": index,
                 "corpus_manifest_sha256": "synthetic-hash", "source_sha256": {"engine": "v1"}}
        if index == 1:
            if defect == "duplicate":
                value["shard"] = 0
            elif defect == "different_source":
                value["source_sha256"] = {"engine": "v2"}
            elif defect == "different_corpus":
                value["corpus_manifest_sha256"] = "other"
            elif defect == "incomplete":
                value["complete"] = False
        (path / "campaign.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        checked_manifests(paths[:1] if defect == "missing" else paths, "synthetic-hash")


def test_aggregation_preserves_full_coverage_and_recomputes_scores(tmp_path):
    from scripts.memory_benchmark.aggregate import aggregate

    corpus = generate(repetitions=1, distractors=0, profile_keys=("family",))
    source = tmp_path / "corpus"
    export(corpus, source, seed=1847, repetitions=1, distractors=0)
    partition = tmp_path / "campaign" / "shard-0"
    partition.mkdir(parents=True)
    manifest = {"complete": True, "synthetic": True, "shards": 1, "shard": 0,
                "engine": "SCORER CALIBRATION NOT REAL ENGINE", "variants": ["previous", "baseline"], "workers": 1,
                "memory_item_budget": 8, "memory_char_budget": 12000, "parameters": {}, "source_sha256": {},
                "queries": len(corpus.queries), "memories": len(corpus.memories), "limitations": [],
                "corpus_manifest_sha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()}
    (partition / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")
    observations_file = partition / "baseline-observations.jsonl"
    traces_file = partition / "baseline-trace.jsonl"
    rows, traces = [], []
    for answer in corpus.answers:
        ids = [g.any_of[0] for g in answer.required]
        rows.append({"query_id": answer.query_id, "candidates": ids, "retrieved": ids, "injected": ids, "latency_ms": 1})
        traces.append({"query_id": answer.query_id, "sql_count": 0, "searches": [], "memory_context_chars": 0,
                       "memory_brief_chars": 0, "upcoming_ids": []})
    observations_file.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    traces_file.write_text("".join(json.dumps(r) + "\n" for r in traces), encoding="utf-8")
    # Both contexts contain the same calendar results; only ordinary retrieval
    # improves. Aggregation must report the change at the appropriate stage.
    (partition / "previous-observations.jsonl").write_text(
        "".join(json.dumps({**r, "retrieved": []}) + "\n" for r in rows), encoding="utf-8")
    (partition / "previous-trace.jsonl").write_text(traces_file.read_text(), encoding="utf-8")
    (partition / "review-candidates.jsonl").write_text("", encoding="utf-8")
    summary = aggregate(source, partition.parent, tmp_path / "report")
    assert summary["queries"] == 132
    report = json.loads((tmp_path / "report" / "baseline-report.json").read_text())
    assert report["stages"]["injected"]["overall"]["coverage"] == 1
    assert report["stages"]["injected"]["overall"]["complete_recall_at_k"] == 1
    campaign = json.loads((tmp_path / "report" / "campaign.json").read_text())
    positives = sum(bool(a.required) for a in corpus.answers)
    assert campaign["paired_retrieved"]["baseline"]["previous"]["complete_recall_changes"] == {"improved": positives}
    assert campaign["paired"]["baseline"]["previous"]["facet_recall_changes"] == {"unchanged": positives}
    observations_file.write_text("".join(json.dumps(r) + "\n" for r in rows[:-1]), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing, duplicate or unknown"):
        aggregate(source, partition.parent, tmp_path / "incomplete-report")
