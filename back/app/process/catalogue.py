"""Compact human catalogue: one page of definitions and authorized run summaries."""

from typing import Literal

from sqlalchemy import and_, case, exists, func, literal, or_, select, true
from sqlalchemy.orm import aliased

from app.agent import Agent, AgentManagementScope
from app.tools import ToolModel
from core.database import get_db

from .models import ProcessDefinition as Definition, ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from .native_access import accessible_clause
from .process_service import TERMINAL_STATUSES
from .query_policy import prepare_process_read
from .schemas import ProcessCatalogueItem, ProcessCataloguePage, ProcessCatalogueRun


async def page_for(
    scope: AgentManagementScope, *, page: int = 1, page_size: int = 50,
    search: str = "", kind: Literal["all", "native", "external"] = "all",
    archive: Literal["all", "active", "archived"] = "active", agent_id: int | None = None,
    sort_by: Literal["label", "tool", "agent", "description"] = "label", descending: bool = False,
) -> ProcessCataloguePage:
    await prepare_process_read()
    db = get_db()
    external_scope = true() if scope.agent_ids is None else or_(
        Definition.agent_id.is_(None), Definition.agent_id.in_(scope.agent_ids))
    allowed = or_(
        and_(accessible_clause(scope), Definition.bpmn_xml.is_not(None)),
        and_(Definition.code.is_(None), external_scope),
    )
    tool = case((Definition.code.is_not(None), literal("Galaris")), else_=ToolModel.label)
    catalogue_agent = aliased(Agent)
    agent = func.nullif(func.concat_ws(" ", catalogue_agent.first_name, catalogue_agent.last_name), "")
    query = select(Definition.id, Definition.code, Definition.label, Definition.description,
        Definition.archived, tool.label("tool"), agent.label("agent")).outerjoin(
        ToolModel, ToolModel.id == Definition.tool_id).outerjoin(catalogue_agent, catalogue_agent.id == Definition.agent_id).where(allowed)
    if kind != "all":
        query = query.where(Definition.code.is_not(None) if kind == "native" else Definition.code.is_(None))
    if archive != "all":
        query = query.where(Definition.archived.is_(archive == "archived"))
    if agent_id is not None:
        # The existing agent selector applies exclusively to external definitions.
        query = query.where(or_(Definition.code.is_not(None), Definition.agent_id == agent_id))
    if search.strip():
        term = search.strip()
        query = query.where(or_(Definition.label.icontains(term, autoescape=True),
            Definition.description.icontains(term, autoescape=True), tool.icontains(term, autoescape=True),
            agent.icontains(term, autoescape=True)))
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    page = min(page, max(1, (total + page_size - 1) // page_size))
    column = {"label": Definition.label, "description": Definition.description, "tool": tool, "agent": agent}[sort_by]
    ordering = column.desc() if descending else column.asc()
    records = await db.execute(query.order_by(ordering.nulls_last(), Definition.id)
        .offset((page - 1) * page_size).limit(page_size))
    items = [ProcessCatalogueItem.model_validate(row) for row in records.mappings()]
    if items:
        await _run_summaries(items, scope)
    return ProcessCataloguePage(items=items, total=total, page=page, page_size=page_size)


async def _run_summaries(items: list[ProcessCatalogueItem], scope: AgentManagementScope) -> None:
    db = get_db()
    visible = ProcessRun.process_id.in_([item.id for item in items])
    if scope.agent_ids is not None:
        # Native runs inherit definition ACLs; external runs retain launcher scope.
        visible = and_(visible, or_(ProcessRun.engine_code == "galaris",
            ProcessRun.launcher_agent_id.in_(scope.agent_ids)))
    latest_attempt = select(ProcessNodeAttempt.status).where(
        ProcessNodeAttempt.node_run_id == ProcessNodeRun.id).order_by(
        ProcessNodeAttempt.number.desc()).limit(1).correlate(ProcessNodeRun).scalar_subquery()
    human_reply = exists(select(ProcessNodeRun.id).where(ProcessNodeRun.run_id == ProcessRun.id,
        ProcessNodeRun.status == "waiting", or_(
            ProcessNodeRun.context["activity_question"]["status"].as_string() == "pending",
            latest_attempt == "human_waiting"))).correlate(ProcessRun)
    active = ProcessRun.status.not_in(TERMINAL_STATUSES)
    counts = {identity: (int(active_count), int(human_count)) for identity, active_count, human_count in
        (await db.execute(select(ProcessRun.process_id, func.count().filter(active),
            func.count().filter(and_(active, human_reply))).where(visible).group_by(ProcessRun.process_id))).all()}
    latest = {identity: ProcessCatalogueRun(id=identity_run, status=status, created_at=created_at)
        for identity, identity_run, status, created_at in (await db.execute(select(ProcessRun.process_id,
            ProcessRun.id, ProcessRun.status, ProcessRun.created_at).where(visible).distinct(ProcessRun.process_id)
            .order_by(ProcessRun.process_id, ProcessRun.created_at.desc(), ProcessRun.id.desc()))).all()}
    for item in items:
        item.active_runs, item.human_waiting_runs = counts.get(item.id, (0, 0))
        item.latest_run = latest.get(item.id)
