"""Actual workflow benchmarks, with synthetic inputs and optional exact checks."""

import hashlib
import json
from typing import Any, cast
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, or_
from sqlalchemy.orm import load_only

from app.agent import AgentManagementScope, management_scope_for
from app.dataset.facade import create_dataset, dataset_record
from app.process.facade import current_definition, launch_current, run_evidence, stop_run
from app.process import ProcessFileInput
from core.database import get_db
from core.user import get_user_record

from .process_evaluation_models import LabProcessCampaign, LabProcessCase


class ProcessCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: dict[str, Any]
    expected: dict[str, Any] | None = None
    files: list[ProcessFileInput] = Field(default_factory=lambda: list[ProcessFileInput]())


class ProcessSyntheticCases(BaseModel):
    cases: list[ProcessCaseInput] = Field(min_length=1)


async def actor_for(campaign: LabProcessCampaign) -> int | AgentManagementScope:
    if campaign.owner_user_id is None:
        return campaign.owner_agent_id
    user = await get_user_record(campaign.owner_user_id)
    if user is None or not user.is_active:
        raise PermissionError("The campaign owner is inactive")
    return await management_scope_for(user, get_db())


async def create_synthetic_dataset(actor: int | AgentManagementScope, *, agent_id: int, title: str,
                                   cases: list[ProcessCaseInput], invocation_key: str) -> dict[str, Any]:
    if isinstance(actor, AgentManagementScope):
        actor.require(agent_id)
    elif actor != agent_id:
        raise PermissionError("Dataset owner access denied")
    content = json.dumps({"synthetic": True, "cases": [case.model_dump(mode="json") for case in cases]}, allow_nan=False)
    dataset = await create_dataset(actor, title=title, content=content,
        creation_key=f"lab-process-dataset:{agent_id}:{invocation_key}")
    await get_db().commit()
    return {"dataset_uri": f"data://{dataset.id}", "dataset_id": str(dataset.id), "revision": dataset.revision}


async def generate_synthetic_dataset(actor: int | AgentManagementScope, *, agent_id: int, code: str,
                                     title: str, instructions: str, count: int, invocation_key: str) -> dict[str, Any]:
    from app.llm import llm_service, model_usages, run_structured, LLMCallPurpose
    definition = await current_definition(code, actor)
    llm = await llm_service.get_profile_llm_for_agent_id(model_usages.LAB, agent_id)
    if llm is None:
        raise ValueError("Configure a Lab model before generating synthetic inputs")
    inference = await run_structured(llm=llm, output_type=ProcessSyntheticCases,
        system_prompt="Generate entirely invented initial JSON data matching the workflow profile. For galaris.bpmn/v2, honor declared inputs and outputs: each supplied variable is a {type, value} envelope, including nested array/object elements. Omit nullable variables or those with defaults when useful; do not invent reference identities or accessible files. Expected outputs use the same typed contract. For v1 use ordinary JSON. Never use production data, secrets or real identities. Expected outputs are optional human-reviewable exact checks, never claims of truth. Do not invent API responses or mocks.",
        prompt=json.dumps({"count": count, "instructions": instructions, "graph": definition["graph"]}),
        agent_id=agent_id, task_id=None, temperature=0.3, request_limit=3,
        purpose=LLMCallPurpose.LAB_MECHANISM_RUN, model_field=model_usages.LAB)
    if len(inference.output.cases) != count:
        raise ValueError("Synthetic generation did not return the requested case count")
    return await create_synthetic_dataset(actor, agent_id=agent_id, title=title,
        cases=inference.output.cases, invocation_key=invocation_key)


async def start_campaign(actor: int | AgentManagementScope, *, agent_id: int, code: str,
                         dataset_id: UUID, title: str, invocation_key: str) -> LabProcessCampaign:
    definition = await current_definition(code, actor)
    if definition["archived"]:
        raise ValueError("An archived workflow cannot be benchmarked")
    if isinstance(actor, AgentManagementScope):
        actor.require(agent_id)
    else:
        if actor != agent_id:
            raise PermissionError("Campaign launcher access denied")
        from app.connection.facade import has_active_tool_function
        if not await has_active_tool_function(actor, "galaris", "process_start"):
            raise PermissionError("The campaign agent requires the process_start capability")
    source = await dataset_record(dataset_id, actor)
    value = json.loads(source.content)
    if not isinstance(value, dict) or cast(dict[str, Any], value).get("synthetic") is not True:
        raise ValueError("Use a Dataset explicitly containing synthetic cases")
    cases = ProcessSyntheticCases.model_validate({"cases": cast(dict[str, Any], value).get("cases")}).cases
    digest = hashlib.sha256(json.dumps({"code": code, "dataset": str(dataset_id), "revision": source.revision, "cases": [case.model_dump() for case in cases]}, sort_keys=True).encode()).hexdigest()
    await get_db().execute(select(func.pg_advisory_xact_lock(int.from_bytes(hashlib.sha256(f"lab-process:{agent_id}:{invocation_key}".encode()).digest()[:8], "big", signed=True))))
    existing = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.owner_agent_id == agent_id, LabProcessCampaign.invocation_key == invocation_key))
    if existing:
        if existing.fingerprint != digest:
            raise ValueError("This invocation key belongs to different campaign inputs")
        return existing
    campaign = LabProcessCampaign(owner_agent_id=agent_id, owner_user_id=actor.user_id if isinstance(actor, AgentManagementScope) else None,
        dataset_id=dataset_id, process_code=code, title=title, invocation_key=invocation_key, fingerprint=digest)
    get_db().add(campaign)
    await get_db().flush()
    get_db().add_all([LabProcessCase(campaign_id=campaign.id, position=index, input=case.input, expected=case.expected,
        files=[item.model_dump(mode="json") for item in case.files]) for index, case in enumerate(cases)])
    await get_db().commit()
    return campaign


async def require_campaign(identity: UUID, actor: int | AgentManagementScope) -> LabProcessCampaign:
    campaign = await get_db().get(LabProcessCampaign, identity)
    if campaign is None:
        raise LookupError("Lab process campaign not found")
    if isinstance(actor, int):
        allowed = actor == campaign.owner_agent_id
    else:
        allowed = actor.allows(campaign.owner_agent_id) or actor.user_id == campaign.owner_user_id
    if not allowed:
        raise PermissionError("Campaign access denied")
    return campaign


async def inspect_campaign(identity: UUID, actor: int | AgentManagementScope, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    campaign = await require_campaign(identity, actor)
    rows = list(await get_db().scalars(select(LabProcessCase).options(load_only(
        LabProcessCase.id, LabProcessCase.position, LabProcessCase.status, LabProcessCase.run_id, LabProcessCase.evidence,
        raiseload=True,
    )).where(LabProcessCase.campaign_id == identity).order_by(LabProcessCase.position).offset((page - 1) * page_size).limit(page_size)))
    total = await get_db().scalar(select(func.count()).select_from(LabProcessCase).where(LabProcessCase.campaign_id == identity))
    return {"id": str(campaign.id), "title": campaign.title, "code": campaign.process_code, "status": campaign.status,
        "dataset_uri": f"data://{campaign.dataset_id}" if campaign.dataset_id is not None else f"document://{campaign.dataset_document_id}",
        "total": total, "page": page, "page_size": page_size,
        "items": [{"id": str(case.id), "position": case.position, "status": case.status, "run_id": str(case.run_id) if case.run_id else None, "evidence": case.evidence} for case in rows]}


async def cancel_campaign(identity: UUID, actor: int | AgentManagementScope) -> None:
    campaign = await require_campaign(identity, actor)
    campaign = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.id == identity).with_for_update().execution_options(populate_existing=True))
    assert campaign is not None
    active = await get_db().scalar(select(LabProcessCase.id).where(LabProcessCase.campaign_id == identity,
        LabProcessCase.run_id.is_not(None), LabProcessCase.status == "running").limit(1))
    if campaign.status not in {"completed", "cancelled"} and (campaign.status != "failed" or active is not None):
        campaign.status = "cancelling"
        await get_db().commit()


async def tick() -> None:
    identities = list(await get_db().scalars(select(LabProcessCampaign.id).where(LabProcessCampaign.status.in_(("running", "cancelling"))).order_by(LabProcessCampaign.created_at).limit(50)))
    for identity in identities:
        campaign = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.id == identity,
            or_(LabProcessCampaign.lease_until.is_(None), LabProcessCampaign.lease_until < datetime.now(timezone.utc)))
            .with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if campaign is None:
            await get_db().commit()
            continue
        token = uuid4()
        campaign.lease_token = token
        campaign.lease_until = datetime.now(timezone.utc) + timedelta(seconds=120)
        await get_db().commit()
        try:
            actor = await actor_for(campaign)
            cases = list(await get_db().scalars(select(LabProcessCase).where(LabProcessCase.campaign_id == identity, LabProcessCase.status.in_(("queued", "running"))).order_by(LabProcessCase.position).limit(50)))
            for case in cases:
                campaign = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.id == identity,
                    LabProcessCampaign.lease_token == token, LabProcessCampaign.lease_until > datetime.now(timezone.utc))
                    .with_for_update().execution_options(populate_existing=True))
                if campaign is None:
                    break
                if campaign.status == "cancelling" and case.run_id is None:
                    case.status = "cancelled"
                    continue
                if case.run_id is None:
                    if isinstance(actor, int):
                        from app.connection.facade import has_active_tool_function
                        if not await has_active_tool_function(actor, "galaris", "process_start"):
                            raise PermissionError("The campaign agent requires the process_start capability")
                    # Durable case ID is the admission key even if the reply was lost.
                    case.run_id = await launch_current(campaign.process_code, actor, agent_id=campaign.owner_agent_id,
                        input_data=case.input, files=[ProcessFileInput.model_validate(item) for item in case.files], invocation_key=f"lab-process-case:{case.id}")
                    case.status = "running"
                    await get_db().commit()
                    campaign = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.id == identity,
                        LabProcessCampaign.lease_token == token).with_for_update().execution_options(populate_existing=True))
                    if campaign is None:
                        break
                if campaign.status == "cancelling":
                    await stop_run(case.run_id, actor)
                evidence = await run_evidence(case.run_id, actor)
                if evidence["status"] in {"success", "error", "cancelled"}:
                    case.status = evidence["status"]
                    case.evidence = {**evidence, "exact_check": evidence["output"] == case.expected if case.expected is not None else None}
                    await get_db().commit()
            campaign = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.id == identity,
                LabProcessCampaign.lease_token == token).with_for_update().execution_options(populate_existing=True))
            if campaign is None:
                await get_db().commit()
                continue
            remaining = await get_db().scalar(select(func.count()).select_from(LabProcessCase).where(LabProcessCase.campaign_id == identity, LabProcessCase.status.in_(("queued", "running"))))
            if not remaining:
                campaign.status = "cancelled" if campaign.status == "cancelling" else "completed"
            campaign.lease_token = None
            campaign.lease_until = None
            await get_db().commit()
        except (ValueError, PermissionError, LookupError) as error:
            await get_db().rollback()
            campaign = await get_db().scalar(select(LabProcessCampaign).where(LabProcessCampaign.id == identity,
                LabProcessCampaign.lease_token == token).with_for_update().execution_options(populate_existing=True))
            if campaign is None:
                await get_db().commit()
                continue
            campaign.status = "failed"
            pending = list(await get_db().scalars(select(LabProcessCase).where(LabProcessCase.campaign_id == identity, LabProcessCase.status.in_(("queued", "running")))))
            for case in pending:
                # An admission is real even when observation loses permission.
                # Never report an active process as physically failed/stopped.
                if case.run_id is None:
                    case.status = "error"
                case.evidence = {"error": str(error)}
            campaign.lease_token = None
            campaign.lease_until = None
            await get_db().commit()
