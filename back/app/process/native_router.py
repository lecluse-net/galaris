"""Human WYSIWYG and live-run API using Process-owned definitions and ACLs."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent import AgentManagementScope, current_management_scope
from app.memory import MemoryConflictError, MemoryPermissionError, MemoryNotFoundError
from app.share import SharingUpdate as DocumentSharingLevelUpdate
from core.authorize import authorize, Privileges
from core.util import source_code_response_headers
from core.storage import FileRename

from . import native_definitions as definitions, native_runs as runs, process_service
from . import native_sharing as definition_sharing
from .bpmn import Workflow, compile_bpmn, to_bpmn, validate_graph
from .schemas import ProcessFileInput
from .run_data import RunDataConflictError

routes = APIRouter(prefix="/internal")


async def _preview_actor(agent_id: int | None) -> int | AgentManagementScope:
    scope = await current_management_scope()
    if agent_id is not None:
        scope.require(agent_id)
        return agent_id
    return scope


@contextmanager
def domain_errors() -> Generator[None]:
    try:
        yield
    except (MemoryConflictError, definitions.DefinitionConflictError, RunDataConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (PermissionError, MemoryPermissionError) as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (LookupError, FileNotFoundError, MemoryNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class DefinitionContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph: Workflow | None = None
    xml: str | None = Field(default=None, max_length=2_000_000)


class DefinitionCreate(DefinitionContent):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    agent_id: int = Field(gt=0)
    owner: Literal["user", "agent"] = "user"
    owner_id: int | None = Field(default=None, gt=0)
    code: str | None = None


class DefinitionUpdate(DefinitionContent):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class OwnerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["user", "agent"]
    id: int = Field(gt=0)
    expected_lock_version: int = Field(ge=1)


class RestoreRequest(BaseModel):
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


class LaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    input: dict[str, Any] = Field(default_factory=dict)
    files: list[ProcessFileInput] = Field(default_factory=lambda: list[ProcessFileInput]())
    idempotency_key: str | None = Field(default=None, max_length=255)


class DebuggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "step", "breakpoints"]
    nodes: list[str] = Field(default_factory=list)
    command_key: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=0)


@routes.get("/humans")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_human_options(agent_id: int = Query(..., gt=0)) -> list[dict[str, Any]]:
    from .native_actors import human_options
    with domain_errors():
        (await current_management_scope()).require(agent_id)
        return await human_options(agent_id)


@routes.get("/decision-models")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_decision_models() -> list[dict[str, Any]]:
    from .llm_decisions import model_options
    return await model_options()


@routes.get("/sharing-options")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_sharing_options(agent_id: int = Query(..., gt=0), owner: Literal["user", "agent"] = "user",
    owner_id: int | None = Query(default=None, gt=0)) -> dict[str, Any]:
    with domain_errors():
        scope = await current_management_scope()
        scope.require(agent_id)
        return (await definition_sharing.preview(scope, owner_agent_id=(owner_id or agent_id) if owner == "agent" else None,
            owner_user_id=owner_id if owner == "user" else None)).model_dump(mode="json")


@routes.get("/owner-options")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_owner_options() -> list[dict[str, Any]]:
    with domain_errors():
        scope = await current_management_scope()
        return [{**option.model_dump(mode="json"), "is_current_user": option.kind == "user" and option.id == scope.user_id}
            for option in await definition_sharing.owner_options(scope)]


@routes.post("/validate")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_validate_definition(data: DefinitionContent) -> dict[str, Any]:
    with domain_errors():
        graph = validate_graph(data.graph) if data.graph is not None else compile_bpmn(data.xml or "")
        return {"valid": True, "diagnostics": [], "graph": graph.model_dump(mode="json"), "xml": to_bpmn(graph)}


@routes.get("/agents")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def native_execution_agents() -> list[dict[str, Any]]:
    from .native_definitions import execution_agents_for
    return await execution_agents_for(await current_management_scope())


@routes.get("/definitions")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_list_definitions(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    with domain_errors():
        return await definitions.page_for(await current_management_scope(), page=page, page_size=page_size)


@routes.post("/definitions", status_code=201)
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_create_definition(data: DefinitionCreate) -> dict[str, Any]:
    with domain_errors():
        scope = await current_management_scope()
        scope.require(data.agent_id)
        principal = data.owner_id or (scope.user_id if data.owner == "user" else data.agent_id)
        await definition_sharing.require_owner(scope, data.owner, principal)
        record = await definitions.create(actor_agent_id=principal if data.owner == "agent" else data.agent_id, title=data.title, graph=data.graph,
            xml=data.xml, code=data.code, owner_user_id=principal if data.owner == "user" else None,
            description=data.description)
        return await definitions.read(record.code or "", scope)


@routes.get("/definitions/{code}")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_read_definition(code: str) -> dict[str, Any]:
    with domain_errors():
        return await definitions.read(code, await current_management_scope())


@routes.patch("/definitions/{code}/owner")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_transfer_owner(code: str, data: OwnerUpdate) -> dict[str, object]:
    with domain_errors():
        return await definition_sharing.transfer_owner(code, await current_management_scope(), kind=data.kind,
            principal=data.id, expected_lock_version=data.expected_lock_version)


@routes.get("/resource-preview")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_resource_preview(response: Response, uri: str = Query(max_length=4096),
    agent_id: int | None = Query(default=None, gt=0), thumbnail: bool = False) -> dict[str, Any]:
    from .resource_previews import process_resource_preview
    response.headers["Cache-Control"] = "private, no-store"
    with domain_errors():
        scope = await current_management_scope()
        if agent_id is not None:
            scope.require(agent_id)
        return await process_resource_preview(uri, agent_id if agent_id is not None else scope, thumbnail=thumbnail)


@routes.get("/resource-options")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_resource_options(response: Response, query: str = Query(default="", max_length=200),
    agent_id: int | None = Query(default=None, gt=0)) -> list[dict[str, str]]:
    from .resource_previews import process_resource_options
    response.headers["Cache-Control"] = "private, no-store"
    with domain_errors():
        scope = await current_management_scope()
        if agent_id is not None:
            scope.require(agent_id)
        return await process_resource_options(query, agent_id if agent_id is not None else scope)


@routes.put("/definitions/{code}")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_update_definition(code: str, data: DefinitionUpdate) -> dict[str, Any]:
    with domain_errors():
        return await definitions.update(code, await current_management_scope(), expected_revision=data.expected_revision,
            graph=data.graph, xml=data.xml, title=data.title, description=data.description)


@routes.get("/definitions/{code}/history")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_definition_history(code: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), exclude_current: bool = False) -> dict[str, Any]:
    with domain_errors():
        return await definitions.history(code, await current_management_scope(), offset=(page - 1) * page_size, limit=page_size, exclude_current=exclude_current)


@routes.get("/definitions/{code}/history/{revision}")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_history_detail(code: str, revision: int) -> dict[str, Any]:
    with domain_errors():
        return await definitions.revision_detail(code, await current_management_scope(), revision)


@routes.post("/definitions/{code}/restore")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_restore_definition(code: str, data: RestoreRequest) -> dict[str, Any]:
    with domain_errors():
        return await definitions.restore(code, await current_management_scope(), data.revision, data.expected_revision)


@routes.delete("/definitions/{code}/history/{revision}", status_code=204)
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_delete_revision(code: str, revision: int) -> None:
    with domain_errors():
        await definitions.delete_revision(code, await current_management_scope(), revision)


@routes.get("/definitions/{code}/sharing")
@authorize(privileges=[Privileges.PROCESS_READ, "PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_sharing(code: str) -> dict[str, Any]:
    with domain_errors():
        scope = await current_management_scope()
        return (await definition_sharing.read(code, scope)).model_dump(mode="json")


@routes.put("/definitions/{code}/sharing")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_update_sharing(code: str, data: DocumentSharingLevelUpdate) -> dict[str, Any]:
    with domain_errors():
        scope = await current_management_scope()
        return (await definition_sharing.update(code, scope, data)).model_dump(mode="json")


@routes.post("/definitions/{code}/archive")
@authorize(privileges=["PROCESS_EDIT", Privileges.PROCESS_ADMIN])
async def native_archive_definition(code: str, archived: bool = True) -> dict[str, Any]:
    with domain_errors():
        return await definitions.archive(code, await current_management_scope(), archived)


@routes.post("/definitions/{code}/runs", status_code=202)
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def native_launch(code: str, data: LaunchRequest) -> dict[str, Any]:
    with domain_errors():
        scope = await current_management_scope()
        scope.require(data.agent_id)
        return (await process_service.start_process(agent_id=data.agent_id, workflow_id=code, input_data=data.input,
            files=data.files, idempotency_key=data.idempotency_key, requester_user_id=scope.user_id)).model_dump(mode="json")


@routes.get("/runs")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def native_run_list(code: str | None = None, page: int = Query(1, ge=1),
                          page_size: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    with domain_errors():
        return await runs.list_runs(await current_management_scope(), code=code, page=page, page_size=page_size)


@routes.get("/runs/{identity}")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_inspect_run(identity: UUID, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                      after_event: int = Query(0, ge=0), agent_id: int | None = Query(default=None, gt=0)) -> dict[str, Any]:
    with domain_errors():
        scope = await current_management_scope()
        if agent_id is not None:
            scope.require(agent_id)
        return await runs.inspect_run(identity, agent_id if agent_id is not None else scope,
            page=page, page_size=page_size, after_event=after_event)


@routes.get("/runs/{identity}/nodes/{node_identity}")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_inspect_node(identity: UUID, node_identity: UUID, agent_id: int | None = None) -> dict[str, Any]:
    with domain_errors():
        return await runs.inspect_occurrence(identity, node_identity, await _preview_actor(agent_id))


@routes.patch("/runs/{identity}/files/{file_id}")
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def native_rename_run_file(identity: UUID, file_id: UUID, data: FileRename, agent_id: int | None = None) -> None:
    from .run_resources import rename_run_file
    with domain_errors():
        await rename_run_file(identity, file_id, await _preview_actor(agent_id), data.name)


@routes.get("/runs/{identity}/files/{file_id}", response_class=FileResponse)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_run_file(identity: UUID, file_id: UUID, agent_id: int | None = None) -> FileResponse:
    from .run_resources import run_file_path
    with domain_errors():
        metadata, path = await run_file_path(identity, file_id, await _preview_actor(agent_id))
        if not path.is_file():
            raise HTTPException(404, "Run attachment not found")
        return FileResponse(path, filename=metadata["name"], media_type=metadata["media_type"],
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                **source_code_response_headers(metadata["name"], metadata["media_type"])})


@routes.get("/runs/{identity}/activities/{node_key}")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_activity_occurrences(identity: UUID, node_key: str, body_path: list[str] | None = Query(None),
                                      page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), agent_id: int | None = None) -> dict[str, Any]:
    with domain_errors():
        return await runs.activity_occurrences(identity, node_key, await _preview_actor(agent_id), body_path=body_path, page=page, page_size=page_size)


@routes.get("/runs/{identity}/children")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_run_children(identity: UUID, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), agent_id: int | None = None) -> dict[str, Any]:
    with domain_errors():
        return await runs.children(identity, await _preview_actor(agent_id), page=page, page_size=page_size)


@routes.get("/runs/{identity}/metrics")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.MEMORY_ACCESS, Privileges.PROCESS_ADMIN])
async def native_metrics(identity: UUID, agent_id: int | None = None) -> dict[str, Any]:
    with domain_errors():
        return await runs.run_metrics(identity, await _preview_actor(agent_id))


@routes.post("/runs/{identity}/control")
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def native_control(identity: UUID, data: DebuggerRequest) -> dict[str, Any]:
    with domain_errors():
        return await runs.control_run(identity, await current_management_scope(), data.action, data.nodes,
            command_key=data.command_key, expected_revision=data.expected_revision)


@routes.post("/runs/{identity}/cancel")
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def native_cancel(identity: UUID) -> dict[str, Any]:
    with domain_errors():
        await runs.require_run(identity, await current_management_scope(), control=True)
        run = await process_service.cancel_run(identity)
        return {"id": str(run.id), "status": run.status}


@routes.post("/runs/{identity}/retry")
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def native_retry(identity: UUID) -> dict[str, Any]:
    with domain_errors():
        run = await runs.require_run(identity, await current_management_scope(), control=True)
        if run.status not in TERMINAL_STATUSES:
            raise ValueError("Only a terminal run can be retried")
        return (await process_service.start_process(agent_id=run.launcher_agent_id,
            workflow_id=str(run.launch_snapshot["workflow_id"]), input_data=run.input,
            files=[ProcessFileInput(uri=str(item["uri"]), slot=item.get("slot"), description=str(item.get("description") or ""))
                for item in run.launch_snapshot.get("files", [])],
            requester_user_id=(await current_management_scope()).user_id)).model_dump(mode="json")


from .process_service import TERMINAL_STATUSES
