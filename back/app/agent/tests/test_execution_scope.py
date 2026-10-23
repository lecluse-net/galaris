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


@pytest.mark.parametrize("actor", [None, 0, 31])
@pytest.mark.parametrize("target,private", [
    ("galaris://skill/personnal/31/procedure/SKILL.md", True),
    ("galaris://skill/personnal/31/procedure/", True),
    ("galaris://skill/personnal/310/procedure/SKILL.md", False),
    ("galaris://skill/personnal/32/procedure/SKILL.md", False),
    ("galaris://skill/personnal/", False),
    ("galaris://skill/procedure/SKILL.md", False),
    ("galaris://task/new", False),
    ("synthetic://external/procedure/SKILL.md", False),
])
def test_personal_creation_uses_server_identity_and_preserves_other_namespaces(actor, target, private):
    from app.file_share.mcp import create_file

    descriptor = create_file.__galaris_mcp_tool__.effect_descriptor
    scope = admitted_scope(uuid4(), "<p>Create a reusable personal procedure.</p>")
    decision = preflight(scope, descriptor, "file_create", {"path": target}, actor_agent_id=actor)
    assert decision.decision == ("allow" if private and actor == 31 else "clarify")
    assert decision.targets == (target,)
    # Private creation must not silently authorize replacing an existing file.
    mutation = descriptor.model_copy(update={"kind": "mutate", "capability": "file.write"})
    assert preflight(scope, mutation, "file_write", {"path": target}, actor_agent_id=actor).decision == "clarify"


@pytest.mark.parametrize("grant", ["run", "collection", "other_run", "none"])
def test_run_attachment_creation_requires_its_exact_sourced_parent(grant):
    from app.file_share.mcp import create_file

    parent = f"galaris://processes/runs/{uuid4()}"
    target = parent + "/attachments/"
    source = {"run": parent, "collection": target,
              "other_run": f"galaris://processes/runs/{uuid4()}", "none": ""}[grant]
    scope = admitted_scope(uuid4(), f"<p>Prepare a report for <code>{source}</code>.</p>")
    descriptor = create_file.__galaris_mcp_tool__.effect_descriptor
    assert preflight(scope, descriptor, "file_create", {"path": target}).decision == (
        "allow" if grant in {"run", "collection"} else "clarify")
    # Naming a run permits no arbitrary child creation or change of its data.
    assert preflight(scope, descriptor, "file_create", {"path": parent + "/data"}).decision == "clarify"
    assert preflight(scope, descriptor, "file_create", {"path": target + "nested/"}).decision == "clarify"
    if grant == "run":
        write_only = scope.model_copy(update={"grants": tuple(
            item.model_copy(update={"capability": "file.write"}) for item in scope.grants)})
        assert preflight(write_only, descriptor, "file_create", {"path": target}).decision == "clarify"
        mutation = descriptor.model_copy(update={"kind": "mutate", "capability": "file.write"})
        assert preflight(scope, mutation, "file_write", {"path": target}).decision == "clarify"
    external = "synthetic://external"
    scope = admitted_scope(uuid4(), f"<p>Prepare a report for <code>{external}</code>.</p>")
    assert preflight(scope, descriptor, "file_create", {"path": external + "/attachments/"}).decision == "clarify"


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
