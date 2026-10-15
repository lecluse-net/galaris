import pytest

from app.dataset.values import VALUE_TYPES, ValueContractError, Variable, normalize, validate_value


@pytest.mark.parametrize("kind", sorted(VALUE_TYPES))
def test_every_type_accepts_explicit_null_only_when_declared_nullable(kind):
    value = {"type": kind, "value": None}
    assert normalize([Variable(name="answer", type=kind, nullable=True)], {"answer": value}, path="values") == {"answer": value}
    with pytest.raises(ValueContractError, match="null is not allowed"):
        normalize([Variable(name="answer", type=kind, nullable=False)], {"answer": value}, path="values")


def test_dataset_reference_is_distinct_from_document_and_transport_file():
    uri = "data://00000000-0000-4000-8000-000000000001"
    assert validate_value({"type": "Dataset", "value": uri})["value"] == uri
    with pytest.raises(ValueContractError):
        validate_value({"type": "Document", "value": uri})
    with pytest.raises(ValueContractError):
        validate_value({"type": "Dataset", "value": "document://00000000-0000-4000-8000-000000000001"})
    from app.process.values import validate_value as legacy_value, validate_declarations, Variable
    with pytest.raises(ValueContractError, match="newer Process profile"):
        legacy_value({"type": "object", "value": {"dataset": {"type": "Dataset", "value": uri}}})
    with pytest.raises(ValueContractError, match="Process v2"):
        validate_declarations([Variable(name="dataset", type="Dataset", nullable=True)], path="inputs")
