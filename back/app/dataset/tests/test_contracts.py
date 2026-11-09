import pytest

from app.dataset.values import VALUE_TYPES, ValueContractError, Variable, normalize, validate_value


@pytest.mark.parametrize("kind", sorted(VALUE_TYPES))
def test_every_type_accepts_explicit_null_only_when_declared_nullable(kind):
    value = {"type": kind, "value": None}
    assert normalize([Variable(name="answer", type=kind, nullable=True)], {"answer": value}, path="values") == {"answer": value}
    with pytest.raises(ValueContractError, match="null is not allowed"):
        normalize([Variable(name="answer", type=kind, nullable=False)], {"answer": value}, path="values")


def test_data_documents_keep_their_uri_and_can_be_selected_as_a_document_subtype():
    uri = "data://00000000-0000-4000-8000-000000000001"
    assert validate_value({"type": "Dataset", "value": uri})["value"] == uri
    assert validate_value({"type": "Document", "value": uri})["value"] == uri
    with pytest.raises(ValueContractError):
        validate_value({"type": "Dataset", "value": "document://00000000-0000-4000-8000-000000000001"})
    from app.process.values import validate_value as process_value
    nested = {"type": "object", "value": {"data": {"type": "Document", "value": uri}}}
    assert process_value(nested) == nested
    value = {"answer": {"type": "Document", "value": uri}}
    assert normalize([Variable(name="answer", type="Document", nullable=True, document_type="data")], value, path="values") == value
    with pytest.raises(ValueContractError, match="expected a text document"):
        normalize([Variable(name="answer", type="Document", nullable=True, document_type="text")], value, path="values")
