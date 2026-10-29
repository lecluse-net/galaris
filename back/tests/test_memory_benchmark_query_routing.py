"""Paired measurements must isolate query construction, even with overlapping arms."""

import asyncio
from types import SimpleNamespace

import pytest

from app.memory import bootstrap, context, retrieval
from tests import memory_benchmark_reference
from tests.memory_benchmark_adapter import CURRENT, Trace, install_adapter
from scripts.memory_benchmark.generate import generate


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_signature', [False, True])
async def test_each_concurrent_arm_uses_its_own_query_builder(monkeypatch, tmp_path, legacy_signature):
    def previous_query(*, label, objective, contact_terms=()):
        return 'previous lexical'

    if not legacy_signature:
        def previous_query(*, label, objective, contact_terms=(), conversation_history=()):
            return f'previous lexical {len(conversation_history)}'

    def previous_semantic(*, label, objective, conversation_history=()):
        return f'previous semantic {len(conversation_history)}'

    previous = {
        'retrieval': SimpleNamespace(_weighted_rank=retrieval._weighted_rank),
        'context': SimpleNamespace(build_memory_brief=context.build_memory_brief,
            memory_context_query=previous_query, memory_context_semantic_query=previous_semantic),
    }
    monkeypatch.setattr(memory_benchmark_reference, 'load_reference', lambda *_: previous)
    install_adapter(monkeypatch, tmp_path, tmp_path / 'reference')
    query = generate(repetitions=1, distractors=0, profile_keys=('family',)).queries[0]
    args = dict(label='Conversation', objective='Et sa limite ?',
                conversation_history=({'role': 'user', 'text': 'Solstice avec Ariane.'},))

    async def build(variant):
        token = CURRENT.set(Trace(query, variant))
        try:
            await asyncio.sleep(0)
            lexical = bootstrap.memory_context_query(**args)
            await asyncio.sleep(0)
            return lexical, bootstrap.memory_context_semantic_query(**args)
        finally:
            CURRENT.reset(token)

    pairs = await asyncio.gather(*(build(variant) for variant in ('previous', 'baseline') * 8))
    for previous_pair, current_pair in zip(pairs[::2], pairs[1::2], strict=True):
        assert previous_pair == ('previous lexical' if legacy_signature else 'previous lexical 1',
                                 'previous semantic 1')
        assert 'Solstice' in current_pair[0]
        assert 'Solstice' in current_pair[1]
        assert not any('previous' in value for value in current_pair)
    assert CURRENT.get() is None
