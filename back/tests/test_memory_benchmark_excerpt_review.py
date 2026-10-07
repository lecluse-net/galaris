"""Opt-in replay of selected fictional cases, recording ordinary search excerpts."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.database import get_db_session
from core.params import RuntimeSettings, runtime_settings
from scripts.memory_benchmark.io import load
from tests import memory_benchmark_adapter as adapter
from tests.test_memory_benchmark_campaign import source_fingerprints


@pytest.mark.asyncio
async def test_selected_synthetic_excerpt_review(monkeypatch, tmp_path, request):
    corpus_option = request.config.getoption("--memory-benchmark-corpus", default="")
    if not corpus_option:
        pytest.skip("Opt-in synthetic excerpt replay")
    corpus_path = Path(corpus_option)
    reference = Path(request.config.getoption("--memory-benchmark-reference"))
    output = Path(request.config.getoption("--memory-benchmark-output"))
    output.resolve().relative_to(Path("/repo/artifacts/memory-benchmark").resolve())
    if output.exists():
        raise ValueError("Review output must be a new directory")
    selection_path = output.parent / "qualitative-review.json"
    selected = json.loads(selection_path.read_text())
    corpus = load(corpus_path)
    query_map = {q.id: q for q in corpus.queries}
    assert len(selected) == 32 and all(row["query_id"] in query_map for row in selected)
    fingerprint = source_fingerprints(reference)
    review_fingerprint = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    primary = json.loads((output.parent / "aggregate/campaign.json").read_text())
    assert fingerprint == primary["source_sha256"]
    captured = []

    @dataclass
    class CapturedTrace(adapter.Trace):
        def __post_init__(self):
            captured.append(self)

    monkeypatch.setattr(adapter, "Trace", CapturedTrace)
    root = tmp_path / "resources"
    adapter.install_adapter(monkeypatch, root, reference)
    defaults = RuntimeSettings()
    for key in type(defaults).model_fields:
        if key.startswith(("MEMORY_CONTEXT_", "MEMORY_RECALL_", "MEMORY_TEMPORAL_")):
            monkeypatch.setattr(runtime_settings, key, getattr(defaults, key))
    user_id, title_id = await adapter.fixture_identity()
    snapshots = {}
    for world in sorted({query_map[row["query_id"]].world_id for row in selected}):
        snapshots[world] = await adapter.load_world(
            tuple(m for m in corpus.memories if m.world_id == world),
            tuple(q for q in corpus.queries if q.world_id == world), root,
            user_id=user_id, title_id=title_id,
        )
    results = []
    for row in selected:
        query = query_map[row["query_id"]]
        for variant in ("previous", "baseline"):
            async with get_db_session() as session:
                observation, detail = await adapter.observe(query, variant, snapshots[query.world_id], session)
                await session.rollback()
            trace = captured.pop()
            results.append({"query_id": query.id, "variant": variant,
                            "retrieved": observation["retrieved"],
                            "retrieved_excerpts": {identity: trace.excerpts[identity]
                                                   for identity in observation["retrieved"]},
                            "provider_errors": detail["provider_errors"]})
    assert source_fingerprints(reference) == fingerprint
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == review_fingerprint
    output.mkdir()
    (output / "excerpts.json").write_text(json.dumps({
        "synthetic": True, "complete": True, "queries": len(selected), "results": results,
        "source_sha256": fingerprint,
        "review_test_sha256": review_fingerprint,
        "selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "corpus_manifest_sha256": hashlib.sha256((corpus_path / "manifest.json").read_bytes()).hexdigest(),
        "limitations": ["Selected-case replay, not a new aggregate latency measurement.",
                        "All selected worlds share this isolated database; retrieved IDs are checked against the main measurement."],
    }, ensure_ascii=False, indent=2) + "\n")
