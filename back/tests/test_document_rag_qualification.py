"""Qualification rejects fabricated facts, citations and full-reading claims."""

import pytest

from scripts.qualify_document_rag import Answer, Claim, Citation, check

TEXT = 'QUARTZ termination notice period: 47 days.'


def evidence():
    return [{'tool': 'file_search', 'result': {'index_coverage': {'exhaustive': False}, 'hits': [
        {'resource': {'uri': 'console://Report.pdf'},
         'passages': [{'page': 20, 'start': 100, 'end': 100 + len(TEXT), 'text': TEXT}]}]}}]


@pytest.mark.parametrize('value', ['47', '47 days'])
def test_fact_and_citation_proof_survives_equivalent_numeric_wording(value):
    answer = Answer(claims=[Claim(key='notice', value=value, unit='days', citations=[
        Citation(uri='console://Report.pdf', page=20, start=100, end=100 + len(TEXT))])], limitations='Selected passages only.')
    assert check('tail', answer, evidence())['passed']
    answer.claims[0].citations[0].start = 100 + TEXT.index('47')
    assert check('tail', answer, evidence())['passed']
    answer.claims[0].citations[0].start = 100 + TEXT.index('days')
    assert not check('tail', answer, evidence())['passed']
    answer.claims[0].citations[0].start = 99
    assert not check('tail', answer, evidence())['passed']
    answer.claims[0].citations[0].start = 100
    assert not check('tail', answer, [])['passed']
    answer.claims[0].citations[0].page = 19
    assert not check('tail', answer, evidence())['passed']
    answer.claims[0].citations[0].page = 20
    answer.claims[0].value = '48'
    assert not check('tail', answer, evidence())['passed']


@pytest.mark.parametrize('exhaustive,limitations', [(True, 'Selected passages only.'),
    (False, 'The full text of the report was read and searched.'),
    (False, 'The complete decoded text was inspected.')])
def test_binary_delivery_cannot_prove_an_exhaustive_reading(exhaustive, limitations):
    answer = Answer(claims=[Claim(key='damages_limit', value=None)],
        exhaustive_read=exhaustive, limitations=limitations)
    receipts = [*evidence(), {'tool': 'file_read', 'result': {'encoding': 'base64', 'content': 'Synthetic binary'}}]
    assert 'unproven_exhaustive_read' in check('missing', answer, receipts)['failures']


def test_missing_fact_requires_a_real_search_and_acknowledged_limitations():
    answer = Answer(claims=[Claim(key='damages_limit', value=None)], limitations='No sufficient retrieved evidence.')
    assert check('missing', answer, evidence())['passed']
    assert not check('missing', answer, [])['passed']
    answer.claims[0].value = '47'
    assert not check('missing', answer, evidence())['passed']
