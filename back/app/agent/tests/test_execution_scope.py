"""A context suggestion cannot acquire the authority of an admitted demand."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.execution_scope import admitted_scope, amend_scope, parse_scope, preflight, validate_plan_scope
from app.agent.scope_contracts import EffectDescriptorV1
from app.agent.planner_contracts import PlanStep


@pytest.mark.parametrize("kind", ["mutate", "transport", "delete", "process"])
def test_effect_requires_exact_sourced_target(kind):
    scope = admitted_scope(uuid4(), '<p>Update <a href="synthetic://requested">the requested resource</a>.</p>')
    descriptor = EffectDescriptorV1(capability="synthetic.update", kind=kind, target_arguments=("uri",))
    assert preflight(scope, descriptor, "synthetic_update", {"uri": "synthetic://requested"}).decision == "allow"
    assert preflight(scope, descriptor, "synthetic_update", {"uri": "synthetic://profile-suggestion"}).decision == "clarify"
    assert preflight(scope, descriptor, "synthetic_update", {}).decision == "clarify"


def test_ordinary_reads_and_creation_preserve_autonomy_without_publication_grants():
    scope = admitted_scope(uuid4(), "<p>Produce a report.</p>")
    read = EffectDescriptorV1(capability="file.read", kind="read", target_arguments=("uri",))
    create = EffectDescriptorV1(capability="file.create", kind="create", target_arguments=("uri",), ordinary_creation_schemes=("document",))
    mutate = EffectDescriptorV1(capability="file.write", kind="mutate", target_arguments=("uri",))
    assert preflight(scope, read, "file_read", {"uri": "synthetic://discovered"}).decision == "allow"
    assert preflight(scope, mutate, "file_write", {"uri": "synthetic://discovered"}).decision == "clarify"
    assert preflight(scope, create, "file_create", {"uri": "document://"}).decision == "allow"
    assert preflight(scope, create, "file_create", {"uri": "synthetic://external"}).decision == "clarify"
    assert preflight(scope, None, "legacy_tool", {}).decision == "allow_and_record"
    assert preflight(None, mutate, "file_write", {}).decision == "allow_and_record"


def test_scope_amendment_keeps_requirements_and_only_adds_sourced_grants():
    scope = admitted_scope(uuid4(), "<p>Prepare the report.</p>")
    amended = amend_scope(scope, "<p>Send to synthetic://requested</p>", "galaris://task/amendment/verified")
    assert amended.revision == scope.revision + 1
    assert amended.requirements[0] == scope.requirements[0]
    assert amended.grants[0].source_reference == amended.requirements[1].source_reference
    assert parse_scope({"execution_scope": amended.model_dump(mode="json")}) == amended
    invalid = amended.model_dump(mode="json") | {"schema_version": "galaris.execution-scope/v99"}
    with pytest.raises(ValidationError):
        parse_scope({"execution_scope": invalid})


def test_owner_assigned_selection_preserves_abstract_requests_but_not_explicit_target_drift():
    descriptor = EffectDescriptorV1(capability="process.start", kind="process", target_arguments=("workflow_id",),
        target_prefix="galaris://process/", domain_assigned_selection=True)
    scope = admitted_scope(uuid4(), "<p>Prepare a report using the assigned workflow.</p>")
    assert preflight(scope, descriptor, "process_start", {"workflow_id": "assigned-report"}).decision == "allow_and_record"
    explicit = admitted_scope(uuid4(), "<p>Run galaris://process/requested-report</p>")
    assert preflight(explicit, descriptor, "process_start", {"workflow_id": "another-report"}).decision == "clarify"
    assert preflight(explicit, descriptor, "process_start", {"workflow_id": "requested-report"}).decision == "allow"


@pytest.mark.parametrize("defect", ["omitted", "unknown", "unsourced", "nested_omission"])
def test_plan_validator_rejects_semantic_drift(defect):
    scope = amend_scope(admitted_scope(uuid4(), "<p>Write report.</p>"), "<p>Also summarize it.</p>", "galaris://task/amendment/1")
    keys = [requirement.key for requirement in scope.requirements]
    valid = PlanStep(objective="<p>Write and summarize.</p>", label="Report", requirement_ids=keys)
    validate_plan_scope(scope, [valid])
    # Groups may omit redundant keys; the requirement coverage belongs to leaves.
    validate_plan_scope(scope, [valid.model_copy(update={"requirement_ids": [], "steps": [
        valid.model_copy(update={"requirement_ids": [key]}) for key in keys
    ]})])
    if defect == "omitted":
        invalid = valid.model_copy(update={"requirement_ids": keys[:1]})
    elif defect == "unknown":
        invalid = valid.model_copy(update={"requirement_ids": [*keys, "profile-request"]})
    elif defect == "unsourced":
        invalid = valid.model_copy(update={"target_refs": ["synthetic://profile-target"]})
    else:
        invalid = valid.model_copy(update={"steps": [valid.model_copy(update={"requirement_ids": keys[:1]})]})
    with pytest.raises(ValueError):
        validate_plan_scope(scope, [invalid])
