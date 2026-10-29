"""Opt-in paired native Dataset discovery; all evidence is invented here."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

from app.dataset import service
from app.file_share import ResourceContext, parse_resource_uri, resource_search
from app.memory.tests.conftest import agents as agents


@pytest.mark.asyncio
async def test_native_dataset_discovery_campaign(request, db, agents):
    destination = request.config.getoption("--memory-benchmark-output", default="")
    reference = request.config.getoption("--memory-benchmark-reference", default="")
    if not destination or not reference:
        pytest.skip("Explicit isolated Dataset campaign output and reference required")
    from tests.memory_benchmark_adapter import assert_isolated
    assert_isolated()
    paths = [Path(__file__).parents[1] / 'app' / 'dataset' / name for name in (
        'provider.py', 'search.py', 'search_index.py', 'search_predicates.py',
        'passages.py', 'query.py', 'models.py', 'access.py')]
    paths.append(Path(__file__))
    def fingerprints():
        return {str(path.relative_to(Path(__file__).parents[1])):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    source_fingerprints = fingerprints()
    output, source = Path(destination), Path(reference) / "dataset_provider.py"
    output.resolve().relative_to(Path('/repo/artifacts/memory-benchmark').resolve())
    source.resolve().relative_to(Path('/repo/artifacts/memory-benchmark').resolve())
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('app.dataset._benchmark_previous_provider', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    previous = module.DatasetProvider()
    owner, peer = agents
    cases = []
    for title, material, location, quantity in (
        ('Mineral inventory', 'quartz', 'northern', 17),
        ('Botanical samples', 'pollen', 'greenhouse', 23),
        ('Workshop supplies', 'rivets', 'repair', 41),
        ('Library holdings', 'atlases', 'reading', 13),
        ('Garden equipment', 'spades', 'orchard', 19),
        ('Festival equipment', 'lanterns', 'stage', 29),
        ('Tissue stock', 'linen', 'sewing', 31),
        ('Kitchen inventory', 'lentils', 'pantry', 37),
    ):
        dataset = await service.create(owner.id, title=title, content=json.dumps({'rows':
            [{'description': 'Ordinary synthetic record', 'quantity': 0}] * 80
            + [{'material': material, 'warehouse': location, 'quantity': quantity}]}))
        for label, query in (('single-material', material), ('single-place', location),
            ('two-terms', f'{material} {location}'), ('reversed', f'{location} {material}'),
            ('key-value', f'material {material}'), ('place-key', f'warehouse {location}'),
            ('numeric-key', f'quantity {material}'), ('title', title),
            ('unknown', f'absent-{material} missing'), ('denied', material)):
            cases.append((label, query, dataset, material, quantity))
    observations = []
    for index, (label, query, dataset, material, quantity) in enumerate(cases):
        actor = peer.id if label == 'denied' else owner.id
        context = ResourceContext(agent_id=actor, runtime='internal')
        expected = label not in ('denied', 'unknown')
        for variant in (('previous', 'current') if index % 2 == 0 else ('current', 'previous')):
            started = time.perf_counter()
            result = (await previous.search(context, parse_resource_uri('data://', allow_empty=True), query, mode='text', max_results=10)
                      if variant == 'previous' else await resource_search(context, 'data://', query, mode='text', max_results=10))
            uri = f'data://{dataset.id}'
            found = next((hit for hit in result.hits if hit.resource.uri == uri), None)
            observations.append({'case': index, 'family': label, 'variant': variant, 'answerable': expected,
                'discovered': found is not None, 'evidence_expected': expected and label != 'title',
                'evidence_found': found is not None and material in found.excerpt and str(quantity) in found.excerpt,
                'leak': label == 'denied' and bool(result.hits),
                'latency_ms': (time.perf_counter() - started) * 1000})
    summaries = {}
    for variant in ('previous', 'current'):
        rows = [r for r in observations if r['variant'] == variant]
        positive = [r for r in rows if r['answerable']]
        evidence = [r for r in rows if r['evidence_expected']]
        summaries[variant] = {'queries': len(rows), 'answerable': len(positive),
            'discovery_recall': sum(r['discovered'] for r in positive) / len(positive),
            'evidence_cases': len(evidence), 'evidence_recall': sum(r['evidence_found'] for r in evidence) / len(evidence),
            'forbidden_results': sum(r['leak'] for r in rows)}
    large = await service.create(owner.id, title='Synthetic report data', content=json.dumps(
        [{'amount': 0.1, 'body': 'Synthetic verbose descriptive content. ' * 10} for _ in range(500)]))
    from app.dataset.query import DatasetQuery, query_dataset
    result = await query_dataset(large.id, owner.id, DatasetQuery.model_validate({'include_rows': False,
        'aggregates': [{'name': 'total', 'op': 'sum', 'path': '/amount'}]}))
    assert result['aggregates']['total']['value'] == '50.0'
    if fingerprints() != source_fingerprints:
        raise RuntimeError('Dataset benchmark sources changed during measurement')
    report = {'complete': True, 'synthetic': True, 'scope': 'paired native provider text discovery, not semantic quality',
        'source_fingerprints': source_fingerprints,
        'reference_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'results': summaries,
        'aggregate_transfer': {'source_bytes': len(large.content.encode()), 'result_bytes': len(json.dumps(result).encode())}}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'observations.json').write_text(json.dumps(observations, indent=2) + '\n')
    assert summaries['current']['discovery_recall'] == 1.0
    assert summaries['current']['evidence_recall'] == 1.0
    assert not summaries['current']['forbidden_results']
