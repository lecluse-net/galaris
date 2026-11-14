"""Process-owned preparation cannot bypass its frozen selected-input contract."""

# ruff: noqa: F811
from io import BytesIO
from unittest.mock import AsyncMock

from PIL import Image
import pytest
from sqlalchemy import func, select

from app.file_share import ResourceContext, resource_create
from app.process.bpmn import Workflow, Node, Flow
from app.process.facade import validate_launch_input_fields, validate_launch_input_patch, sync_input_run
from app.process.models import ProcessRun
from app.process.native_definitions import create
from app.process.tests.test_native_bpmn import native as native
from app.process.values import Variable, ValueContractError
from core.database import get_db


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 10, 50, 200])
async def test_fields_sharing_a_resource_check_its_live_metadata_once_per_validation(db, native, monkeypatch, count):
    import app.file_share as resources
    owner, _ = native
    source = BytesIO(); Image.new("RGB", (4, 4), "white").save(source, format="PNG")
    file = await resource_create(ResourceContext(agent_id=owner.id, runtime="internal"), "file://", source.getvalue(), name="Synthetic.png")
    declarations = [Variable(name=f"scan_{index}", type="File", nullable=True, mime_type="image/*").model_dump(mode="json") for index in range(count)]
    values = {item["name"]: file.uri for item in declarations}
    read = AsyncMock(wraps=resources.resource_info)
    monkeypatch.setattr(resources, "resource_info", read)
    valid, issues = await validate_launch_input_fields(owner.id, declarations, values)
    assert len(valid) == count and not issues and read.await_count == 1
    # The cache is per validation only; the next call must recheck live access.
    await validate_launch_input_patch(owner.id, declarations, values)
    assert read.await_count == 2
    declarations[-1]["mime_type"] = "application/pdf"
    valid, issues = await validate_launch_input_fields(owner.id, declarations, values)
    assert set(issues) == {declarations[-1]["name"]} and len(valid) == count - 1
    assert read.await_count == 3


@pytest.mark.asyncio
async def test_strict_input_validation_preserves_permission_errors(db, native):
    owner, other = native
    file = await resource_create(ResourceContext(agent_id=other.id, runtime="internal"), "file://", b"Synthetic", name="Synthetic.txt")
    declarations = [Variable(name="scan", type="File", nullable=True).model_dump(mode="json")]
    with pytest.raises(PermissionError):
        await validate_launch_input_patch(owner.id, declarations, {"scan": file.uri})


@pytest.mark.asyncio
async def test_document_format_constraints_distinguish_formats_sharing_a_media_type(db, native, monkeypatch):
    from app.document import formats, DocumentFormatDefinition, DocumentFormatRegistry, register_document_format
    monkeypatch.setattr(formats, "registry", DocumentFormatRegistry())
    monkeypatch.setattr(formats, "_native_registered", False)
    for code in ("example.first", "example.second"):
        register_document_format(DocumentFormatDefinition(code, "application/x-synthetic-shared", "", "description",
            lambda _: None, lambda source: source, provider="example"))
    owner, _ = native
    item = await resource_create(ResourceContext(agent_id=owner.id, runtime="internal"), "document://",
        b"Synthetic structured content", name="Synthetic format input", document_format="example.first")
    declarations = [Variable(name=name, type="Document", nullable=False, document_format=code).model_dump(mode="json")
        for name, code in (("matching", "example.first"), ("different", "example.second"))]
    valid, issues = await validate_launch_input_fields(owner.id, declarations,
        {"matching": item.uri, "different": item.uri})
    assert set(valid) == {"matching"} and set(issues) == {"different"}


async def definition(owner):
    return await create(actor_agent_id=owner.id, title="Synthetic selected inputs", graph=Workflow(schema_version="galaris.bpmn/v2",
        variables=[Variable(name="name", type="string", nullable=True),
            Variable(name="counter", type="int", nullable=False, default={"type": "int", "value": 0})],
        nodes=[Node(id="start", kind="start", inputs=["name"]), Node(id="end", kind="end")],
        flows=[Flow(id="done", source="start", target="end")]))


@pytest.mark.asyncio
async def test_preparation_port_rejects_writing_unselected_runtime_variables_before_mutation(db, native):
    owner, _ = native
    process = await definition(owner)
    with pytest.raises(ValueContractError, match="undeclared variable"):
        await sync_input_run(agent_id=owner.id, workflow_id=process.code, invocation_key="synthetic-invalid",
            values={"counter": {"type": "int", "value": 999}}, missing=["name"], issues={}, question="Synthetic")
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0


@pytest.mark.asyncio
async def test_preparation_port_derives_missing_inputs_and_does_not_revise_unchanged_data(db, native):
    owner, _ = native
    process = await definition(owner)
    run = await sync_input_run(agent_id=owner.id, workflow_id=process.code, invocation_key="synthetic-missing",
        values={}, missing=[], issues={}, question="Synthetic")
    await get_db().commit()
    assert run.engine_metadata["input_preparation"]["missing"] == ["name"]
    assert run.engine_metadata["input_preparation"]["status"] == "collecting"
    revision = run.data_revision
    await sync_input_run(agent_id=owner.id, workflow_id=process.code, invocation_key="synthetic-missing",
        values={}, missing=["name"], issues={}, question="A refreshed synthetic question", identity=run.id)
    await get_db().commit()
    assert run.data_revision == revision and run.data["counter"]["value"] == 0
