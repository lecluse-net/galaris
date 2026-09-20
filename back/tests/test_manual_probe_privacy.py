"""Manual diagnostic output preserves evidence without publishing source data."""

import json
from types import SimpleNamespace
from uuid import uuid4

from tests.manual.memory_relevance import public_result


def test_recall_diagnostic_does_not_export_private_result_fields():
    first_id, expected_id = uuid4(), uuid4()
    private_text = "PRIVATE_SENTINEL: a confidential conversation and document title"
    result = SimpleNamespace(
        query=private_text,
        degradation_reason=private_text,
        index_coverage=SimpleNamespace(model_code=private_text),
        degraded=True,
        hits=[SimpleNamespace(
            item=SimpleNamespace(id=identity, title=private_text),
            excerpt=private_text,
            passages=[{"text": private_text}],
        ) for identity in (first_id, expected_id)],
    )

    output = public_result(result, frozenset({expected_id}))

    assert output == {"hit_count": 2, "first_expected_rank": 2, "degraded": True}
    encoded = json.dumps(output)
    assert private_text not in encoded
    assert str(first_id) not in encoded
    assert str(expected_id) not in encoded
    assert public_result(result, frozenset())["first_expected_rank"] is None
