"""Human Lab campaigns use real current process launches and resource assertions."""

from typing import Any, ClassVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.agent import current_management_scope
from app.dataset.facade import DatasetPermissionError, DatasetNotFoundError, DatasetConflictError
from core.authorize import authorize, BaseAssertion, AssertionContext, check_privilege

from . import process_evaluation as service

routes = APIRouter(prefix="/process-campaigns")


class ProcessLabAssertion(BaseAssertion):
    launch: ClassVar[bool] = False

    async def assert_(self, context: AssertionContext) -> bool:
        return context.db is not None and await check_privilege(context.user,
            ["PROCESS_LAUNCH", "PROCESS_ADMIN"] if self.launch else ["PROCESS_READ", "PROCESS_ADMIN"], context.db)


class ProcessLabLaunchAssertion(ProcessLabAssertion):
    launch = True


class SyntheticInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=300)
    invocation_key: str = Field(min_length=1, max_length=200)
    cases: list[service.ProcessCaseInput] = Field(min_length=1)


class SyntheticGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    code: str
    title: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=6000)
    count: int = Field(default=8, ge=1, le=20)
    invocation_key: str = Field(min_length=1, max_length=200)


class CampaignStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    code: str
    dataset_id: UUID = Field(validation_alias=AliasChoices("dataset_id", "dataset_document_id"))
    title: str = Field(min_length=1, max_length=300)
    invocation_key: str = Field(min_length=1, max_length=200)


def domain_error(error: Exception) -> HTTPException:
    return HTTPException(status_code=403 if isinstance(error, (PermissionError, DatasetPermissionError)) else
        404 if isinstance(error, (LookupError, DatasetNotFoundError)) else
        409 if isinstance(error, DatasetConflictError) else 422, detail=str(error))


@routes.post("/datasets", status_code=201)
@authorize(privileges="PROCESS_EVALUATION_EDIT", assertion=ProcessLabAssertion)
async def lab_process_dataset_create(data: SyntheticInputs) -> dict[str, Any]:
    try:
        return await service.create_synthetic_dataset(await current_management_scope(), **data.model_dump(exclude={"cases"}), cases=data.cases)
    except (ValueError, PermissionError, LookupError, DatasetNotFoundError, DatasetConflictError) as error:
        raise domain_error(error) from error


@routes.post("/datasets/generate", status_code=201)
@authorize(privileges="PROCESS_EVALUATION_EDIT", assertion=ProcessLabAssertion)
async def lab_process_dataset_generate(data: SyntheticGenerate) -> dict[str, Any]:
    try:
        scope = await current_management_scope()
        scope.require(data.agent_id)
        return await service.generate_synthetic_dataset(scope, **data.model_dump())
    except (ValueError, PermissionError, LookupError, DatasetNotFoundError, DatasetConflictError) as error:
        raise domain_error(error) from error


@routes.post("", status_code=202)
@authorize(privileges="PROCESS_EVALUATION_EDIT", assertion=ProcessLabLaunchAssertion)
async def lab_process_campaign_start(data: CampaignStart) -> dict[str, Any]:
    try:
        campaign = await service.start_campaign(await current_management_scope(), **data.model_dump())
        return await service.inspect_campaign(campaign.id, await current_management_scope())
    except (ValueError, PermissionError, LookupError, DatasetNotFoundError, DatasetConflictError) as error:
        raise domain_error(error) from error


@routes.get("/{identity}")
@authorize(privileges=["PROCESS_EVALUATION_ACCESS", "PROCESS_EVALUATION_EDIT"], assertion=ProcessLabAssertion)
async def lab_process_campaign_get(identity: UUID, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    try:
        return await service.inspect_campaign(identity, await current_management_scope(), page=page, page_size=page_size)
    except (ValueError, PermissionError, LookupError) as error:
        raise domain_error(error) from error


@routes.post("/{identity}/cancel", status_code=202)
@authorize(privileges="PROCESS_EVALUATION_EDIT", assertion=ProcessLabLaunchAssertion)
async def lab_process_campaign_cancel(identity: UUID) -> dict[str, Any]:
    try:
        await service.cancel_campaign(identity, await current_management_scope())
        return await service.inspect_campaign(identity, await current_management_scope())
    except (ValueError, PermissionError, LookupError) as error:
        raise domain_error(error) from error
