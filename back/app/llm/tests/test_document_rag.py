"""Deterministic capacity admission, source coverage and cited bounded retrieval."""

import base64
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

from core.document import DocumentPage, PreparedDocument
from app.llm import LLM
from app.llm import document_rag, document_input
from app.llm.document_budget import document_input_budget, document_tokens, text_tokens
from app.llm.embedding_facade import ConfiguredEmbeddingModel, EmbeddingNotConfiguredError


def report():
    pages = [DocumentPage(number=number, text=('Unrelated synthetic background. ' * 200 if number < 20
              else 'QUARTZ final cancellation deadline is 47 days.')) for number in range(1, 21)]
    return PreparedDocument(name='Synthetic report.pdf', sha256='a' * 64, media_type='application/pdf', pages=pages)


@pytest.fixture(autouse=True)
def no_default_embedding_provider(monkeypatch):
    monkeypatch.setattr(document_rag, 'require_configured_embedding_model',
                        AsyncMock(side_effect=EmbeddingNotConfiguredError('Synthetic no vector model')))


def test_capacity_includes_other_documents_history_tools_output_and_model_size():
    body = {'messages': [{'role': 'user', 'content': 'Synthetic request'}]}
    small = document_input_budget(4096, body)
    large = document_input_budget(128_000, body)
    required = document_tokens(report(), visual=False)
    assert small < required < large
    assert document_input_budget(4096, {**body, 'max_tokens': 2048}) < small
    assert document_input_budget(4096, {**body, 'tools': [{'description': 'Large schema. ' * 1000}]}) < small
    assert document_input_budget(4096, {'messages': [{'content': 'History ' * 20_000}]}) == 0


@pytest.mark.asyncio
async def test_retrieval_indexes_the_tail_and_returns_source_locations_without_claiming_full_read():
    result = await document_rag.retrieve_prepared_document(report(), 'QUARTZ cancellation deadline', token_budget=1800)
    assert result.mode == 'lexical'
    assert result.indexed_passages > 20
    assert 20 in result.selected_pages
    assert '47 days' in result.text and 'physical page 20' in result.text
    assert 'not the whole document' in result.text
    assert text_tokens(result.text) <= 1800


@pytest.mark.asyncio
async def test_small_retrieval_budget_keeps_the_matching_end_of_a_dense_passage():
    document = PreparedDocument(name='Synthetic.txt', sha256='a' * 64, media_type='text/plain',
        pages=[DocumentPage(number=1, text='Background ' * 140 + 'QUARTZ cancellation deadline is 47 days.')])
    result = await document_rag.retrieve_prepared_document(document, 'cancellation deadline', token_budget=420)
    assert '47 days' in result.text and text_tokens(result.text) <= 420


@pytest.mark.asyncio
async def test_no_matching_text_does_not_claim_absence_or_publish_partial_vectors(monkeypatch):
    model = ConfiguredEmbeddingModel(key='synthetic-failure', code='vector', model_name='vector', base_url='http://unused.invalid')
    monkeypatch.setattr(document_rag, 'require_configured_embedding_model', AsyncMock(return_value=model))
    monkeypatch.setattr(ConfiguredEmbeddingModel, 'embed', AsyncMock(side_effect=TimeoutError))
    cache = AsyncMock()
    cache.load.return_value = None
    result = await document_rag.retrieve_prepared_document(report(), 'unfindable-needle-zzyyxx', token_budget=1800, cache=cache)
    assert result.mode == 'lexical' and result.selected_passages == 0
    assert 'absence is not proven' in result.text and 'embeddings incomplete' in result.text
    cache.save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('similarity', [-1., 0., .2])
async def test_unrelated_semantic_neighbors_are_not_presented_as_relevant_passages(monkeypatch, similarity):
    question = 'How do quantum computers correct errors?'
    document = PreparedDocument(name='Synthetic cake.txt', sha256='a' * 64, media_type='text/plain',
        pages=[DocumentPage(number=1, text='Bake the apple cake for twenty minutes.')])
    model = ConfiguredEmbeddingModel(key='synthetic-relevance', code='vector', model_name='vector', base_url='http://unused.invalid')
    async def embed(self, texts, **kwargs):
        import math
        return [[similarity, math.sqrt(1 - similarity ** 2)] if text == question else [1., 0.] for text in texts]
    monkeypatch.setattr(document_rag, 'require_configured_embedding_model', AsyncMock(return_value=model))
    monkeypatch.setattr(ConfiguredEmbeddingModel, 'embed', embed)
    result = await document_rag.retrieve_prepared_document(document, question, token_budget=1800)
    assert not result.passages
    assert 'absence is not proven' in result.text


@pytest.mark.asyncio
async def test_multiple_large_uploads_each_supply_tail_evidence_with_one_bounded_provider_call():
    content = [{'type': 'text', 'text': 'Compare QUARTZ cancellation deadlines.'}]
    for number in range(3):
        source = ('Synthetic background. ' * 1500 + f'\nQUARTZ cancellation deadline is {47 + number} days.').encode()
        content.append({'type': 'file', 'file': {'filename': f'Synthetic-{number}.txt',
            'file_data': 'data:text/plain;base64,' + base64.b64encode(source).decode()}})
    requests = []
    async def send(payload):
        requests.append(payload)
        return JSONResponse({'choices': [{'message': {'content': 'Synthetic comparison'}}]})
    response = await document_input.route_documents({'messages': [{'role': 'user', 'content': content}]},
        LLM(context_length=4096, input_file=False, input_image=False), send)
    assert response.status_code == 200 and len(requests) == 1
    wire = json.dumps(requests[0])
    assert all(f'{number} days' in wire for number in [47, 48, 49])
    assert 'file_data' not in wire


@pytest.mark.asyncio
async def test_semantic_index_reuses_complete_vectors_and_rebuilds_a_corrupt_generation(monkeypatch):
    calls = []
    async def embed(self, texts, **kwargs):
        calls.append(list(texts))
        return [[1., 0.] if '47 days' in text or 'termination' in text else [0., 1.] for text in texts]
    model = ConfiguredEmbeddingModel(key='synthetic-model', code='vector', model_name='vector', base_url='http://unused.invalid')
    monkeypatch.setattr(document_rag, 'require_configured_embedding_model', AsyncMock(return_value=model))
    monkeypatch.setattr(ConfiguredEmbeddingModel, 'embed', embed)
    class Cache:
        payload = None
        async def load(self, fingerprint):
            return self.payload
        async def save(self, fingerprint, payload):
            self.payload = payload
    cache = Cache()
    first = await document_rag.retrieve_prepared_document(report(), 'termination', token_budget=1800, cache=cache)
    assert first.mode == 'hybrid' and 20 in first.selected_pages
    initial = len(calls)
    again = await document_rag.retrieve_prepared_document(report(), 'termination', token_budget=1800, cache=cache)
    assert again.selected_pages == first.selected_pages and len(calls) == initial + 1
    cache.payload['vectors'].pop()
    await document_rag.retrieve_prepared_document(report(), 'termination', token_budget=1800, cache=cache)
    assert len(calls) > initial + 2


@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', ['chat', 'responses'])
@pytest.mark.parametrize('context', [4096, 128_000])
async def test_protocol_chooses_direct_or_rag_locally_preserving_tools_and_the_selected_protocol(protocol, context):
    source = ('Synthetic background. ' * 1400 + '\nQUARTZ cancellation deadline is 47 days.').encode()
    data = 'data:text/plain;base64,' + base64.b64encode(source).decode()
    tools = [{'type': 'function', 'function': {'name': 'synthetic_tool', 'parameters': {'type': 'object'}}}]
    body = {'model': 'synthetic', 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'What is the QUARTZ cancellation deadline?'},
        {'type': 'file', 'file': {'filename': 'Synthetic.txt', 'file_data': data}},
    ]}], 'tools': tools}
    requests = []
    async def send(payload):
        requests.append(payload)
        return JSONResponse({'choices': [{'message': {'content': 'Synthetic answer'}}]})
    llm = LLM(input_file=True, input_image=False, context_length=context)
    if protocol == 'responses':
        from app.llm.document_responses import route_response_documents
        stateful = [{'type': 'function_call', 'call_id': 'synthetic-call', 'name': 'synthetic_tool', 'arguments': '{}'},
                    {'type': 'function_call_output', 'call_id': 'synthetic-call', 'output': 'Synthetic tool result'}]
        body['input'] = [*stateful, {'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'What is the QUARTZ cancellation deadline?'},
            {'type': 'input_file', 'filename': 'Synthetic.txt', 'file_data': data},
        ]}]
        del body['messages']
        response = await route_response_documents(body, llm, send)
    else:
        response = await document_input.route_documents(body, llm, send)
    assert response.status_code == 200
    assert response.headers['X-Galaris-Document-Mode'] == ('rag' if context == 4096 else 'prepared')
    assert len(requests) == 1 and requests[0]['tools'] == tools
    assert ('input' in requests[0]) is (protocol == 'responses')
    if protocol == 'responses':
        assert requests[0]['input'][:2] == stateful
    wire = json.dumps(requests[0])
    assert '47 days' in wire
    if context == 4096:
        assert response.headers['X-Galaris-Document-Coverage'] == 'retrieved-passages'
        assert 'file_data' not in wire and len(wire) < len(source) // 2
