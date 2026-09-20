from uuid import uuid4
import pytest
from pydantic import ValidationError

from app.agent.models import Agent
from app.harnesses.models import AgentHarness
from app.harnesses.schemas import HarnessCatalogCreate, HarnessSelectionUpdate
from app.harnesses.schemas import HarnessCatalogUpdate


@pytest.mark.parametrize("schema, kwargs", [(HarnessCatalogCreate, {"provider_code": "openai_messages"}), (HarnessCatalogUpdate, {"enabled": True})])
def test_live_activity_source_is_explicit_and_strict(schema, kwargs):
    assert schema(name="Harness", **kwargs).settings["streams_ai_messages"] is True
    assert schema(name="Harness", settings={"streams_ai_messages": False, "custom": 1}, **kwargs).settings == {"streams_ai_messages": False, "custom": 1}
    for invalid in ["false", 0, 1, None]:
        with pytest.raises(ValidationError):
            schema(name="Harness", settings={"streams_ai_messages": invalid}, **kwargs)


def test_agent_selects_a_reusable_catalogue_harness() -> None:
    column = Agent.__table__.c.task_harness_id

    assert column.nullable is True
    assert column.unique is not True
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.target_fullname == "harnesses.id"
    assert foreign_key.ondelete == "SET NULL"


def test_runtime_assignment_is_unique_per_agent() -> None:
    constraints = {constraint.name for constraint in AgentHarness.__table__.constraints}

    assert "uq_agent_harnesses_agent_id" in constraints


def test_catalogue_schema_normalizes_provider_and_selection_only_uses_an_id() -> None:
    data = HarnessCatalogCreate(
        provider_code=" OpenAI_Messages ",
        name=" Network harness ",
        base_url=" https://example.test/v1/ ",
        token=" top-secret ",
    )
    harness_id = uuid4()
    selection = HarnessSelectionUpdate(harness_id=harness_id)

    assert data.provider_code == "openai_messages"
    assert data.name == "Network harness"
    assert data.token == "top-secret"
    assert selection.model_dump() == {"harness_id": harness_id}
