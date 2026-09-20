"""Deterministic editorial projections from canonical Galaris source data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import re
from uuid import UUID

from loguru import logger
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import selectinload

from app.agent import Agent
from app.goal import Goal, GoalCycle, GoalReferrerType, GoalStatus, goal_service
from core.database import get_db

from . import service
from core.util import convert_legacy_to_html, normalize_html
from .contracts import SourceMemoryDocument
from .models import MemoryItem
from .safety import redact_secrets
from .storage import get_storage


AGENT_SOURCE_KIND = "agent"
GOAL_SOURCE_KIND = "goal"
GOAL_CYCLE_SOURCE_KIND = "goal_cycle"
GOAL_CYCLE_PROJECTION_LIMIT = 100
_CYCLE_CLEANUP_BATCH_SIZE = 100
PROJECTION_VERSION = 2
_MISSING = "_Non renseigné._"
_SENSITIVE = "_[contenu sensible retiré]_"


@dataclass(frozen=True)
class SourceMemoryRebuildResult:
    """Auditable aggregate returned by the rebuild procedure."""

    agents_scanned: int = 0
    agents_synced: int = 0
    goals_scanned: int = 0
    goals_synced: int = 0
    orphans_removed: int = 0
    stale_cycles_removed: int = 0
    failures: tuple[str, ...] = ()

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


def _enum_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _iso(value: object | None) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return ""


def _safe_text(value: object | None, *, limit: int = 100_000) -> str:
    raw = str(value or "").strip()
    if not raw:
        return _MISSING
    filtered = redact_secrets(raw)
    if filtered is None:
        return _SENSITIVE
    if len(filtered) <= limit:
        return filtered
    return f"{filtered[:limit].rstrip()}\n\n_[contenu tronqué]_"


def _safe_inline(value: object | None, *, limit: int = 500) -> str:
    text = _safe_text(value, limit=limit)
    return " ".join(text.split())


def _agent_name(agent: Agent | None, fallback_id: int) -> str:
    if agent is None:
        return f"Agent #{fallback_id}"
    return (
        " ".join(
            part
            for part in (
                _safe_inline(agent.first_name),
                _safe_inline(agent.last_name),
            )
            if part and part != _MISSING
        )
        or f"Agent #{fallback_id}"
    )


def _bullet(label: str, value: object | None) -> str:
    return f"- **{label} :** {_safe_inline(value)}"


def agent_to_markdown(agent: Agent) -> str:
    """Render the stable, non-secret professional profile of one agent."""

    title = agent.title.label
    group = agent.group.name if agent.group is not None else None
    display_name = _agent_name(agent, agent.id)
    lines = [
        f"# Profil agent — {display_name}",
        "",
        "> Projection générée automatiquement depuis la fiche Agent de Galaris. ",
        "> La fiche Agent reste la source de vérité.",
        "",
        "## Identité",
        "",
        _bullet("ID Galaris", agent.id),
        _bullet("Code", agent.code),
        _bullet("Civilité", title),
        _bullet("Prénom", agent.first_name),
        _bullet("Nom", agent.last_name),
        _bullet("Groupe", group),
        "",
        "## Fonction",
        "",
        _bullet("Intitulé du poste", agent.job_title),
        _bullet("Moteur agentique", agent.agent_driver),
        "",
        "### Fiche de poste",
        "",
        _safe_text(agent.job_description),
        "",
        "## Personnalité",
        "",
        _safe_text(agent.personality),
        "",
        "## Repères",
        "",
        _bullet("Créé le", _iso(agent.created_at)),
        _bullet("Mis à jour le", _iso(agent.updated_at)),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _goal_referrer(goal: Goal) -> str:
    if goal.referrer_type == GoalReferrerType.AGENT:
        if goal.referrer_agent_id is None:
            return _MISSING
        return _agent_name(goal.referrer_agent, goal.referrer_agent_id)
    if goal.referrer_type == GoalReferrerType.MESSENGER:
        display_name = _safe_inline(goal.referrer_display_name)
        platform = _safe_inline(goal.referrer_platform)
        if platform == _MISSING:
            return display_name
        return f"{display_name} ({platform})"
    return _MISSING


def goal_to_markdown(goal: Goal, *, description: str, tracking: str) -> str:
    """Render one Goal, including its canonical objective and ongoing tracking."""

    lines = [
        f"# Objectif — {_safe_inline(goal.title)}",
        "",
        "> Projection générée automatiquement depuis le Goal Galaris. ",
        "> Le Goal reste la source de vérité.",
        "",
        "## Références",
        "",
        _bullet("Goal UUID", goal.id),
        _bullet("Agent responsable", _agent_name(goal.agent, goal.agent_id)),
        _bullet("Agent ID", goal.agent_id),
        _bullet("Demandeur", _goal_referrer(goal)),
        "",
        "## État",
        "",
        _bullet("Statut", _enum_value(goal.status)),
        _bullet("Révision source", goal.revision),
        _bullet("Délai entre cycles (secondes)", goal.cycle_delay_seconds),
        _bullet("Prochain cycle", _iso(goal.next_cycle_at)),
        _bullet("Terminé le", _iso(goal.completed_at)),
        _bullet("Motif de pause", goal.pause_reason),
        "",
        "## Description de l’objectif",
        "",
        _safe_text(description),
        "",
        "## Suivi courant",
        "",
        _safe_text(tracking, limit=30_000),
        "",
        "## Dernière erreur",
        "",
        _safe_text(goal.last_error, limit=20_000),
        "",
        "## Repères",
        "",
        _bullet("Créé le", _iso(goal.created_at)),
        _bullet("Mis à jour le", _iso(goal.updated_at)),
    ]
    return "\n".join(lines).rstrip() + "\n"


def goal_cycle_to_markdown(cycle: GoalCycle) -> str:
    """Render the durable account of one Goal execution/evaluation cycle."""

    task = cycle.task
    result = task.get_execution_result() if task is not None else None
    task_status = _enum_value(task.status) if task is not None else ""
    tools = [] if result is None else list(dict.fromkeys(result.tools_used))
    evidence = "\n".join(f"- {_safe_inline(item, limit=2_000)}" for item in cycle.evidence)
    if not evidence:
        evidence = _MISSING
    tool_list = "\n".join(f"- `{_safe_inline(tool)}`" for tool in tools) or _MISSING
    task_result = result.result if result is not None else None
    lines = [
        f"# Cycle {cycle.sequence} — {_safe_inline(cycle.goal.title)}",
        "",
        "> Compte rendu généré automatiquement depuis un cycle de Goal Galaris. ",
        "> Le Goal, le cycle et sa Task restent les sources de vérité.",
        "",
        "## Références",
        "",
        _bullet("Cycle UUID", cycle.id),
        _bullet("Goal UUID", cycle.goal_id),
        _bullet("Numéro de cycle", cycle.sequence),
        _bullet("Agent responsable", _agent_name(cycle.goal.agent, cycle.goal.agent_id)),
        _bullet(
            "Ressource Task",
            f"galaris://task/{cycle.task_id}" if cycle.task_id is not None else None,
        ),
        _bullet("Libellé de Task", task.label if task is not None else None),
        "",
        "## État du cycle",
        "",
        _bullet("Statut du cycle", _enum_value(cycle.status)),
        _bullet("Verdict", _enum_value(cycle.verdict)),
        _bullet("Statut de la Task", task_status),
        _bullet("Progression constatée", cycle.progress_changed),
        _bullet("Task terminée le", _iso(cycle.task_finished_at)),
        _bullet("Évaluation terminée le", _iso(cycle.judge_finished_at)),
        "",
        "## Compte rendu de progression",
        "",
        _safe_text(cycle.progress_summary, limit=30_000),
        "",
        "## Résultat de la Task",
        "",
        _safe_text(task_result),
        "",
        "## Éléments de preuve",
        "",
        evidence,
        "",
        "## Motif du verdict",
        "",
        _safe_text(cycle.reason, limit=30_000),
        "",
        "## Contexte de continuation",
        "",
        _safe_text(cycle.continuation_context, limit=30_000),
        "",
        "## Outils utilisés",
        "",
        tool_list,
        "",
        "## Coûts techniques",
        "",
        _bullet("Task", f"{float(cycle.task_cost or 0.0):.6f}"),
        _bullet("Évaluation", f"{float(cycle.judge_cost or 0.0):.6f}"),
        "",
        "## Erreur",
        "",
        _safe_text(cycle.error, limit=20_000),
        "",
        "## Repères",
        "",
        _bullet("Créé le", _iso(cycle.created_at)),
        _bullet("Mis à jour le", _iso(cycle.updated_at)),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _editorial_projection(markdown: str, fragments: tuple[str | None, ...]) -> str:
    replacements: dict[str, str] = {}
    for index, fragment in enumerate(fragments):
        if not fragment:
            continue
        safe = _safe_text(fragment)
        marker = f"GALARISEDITORIALFRAGMENT{index}END"
        if safe not in markdown:
            continue
        markdown = re.sub(r"(?m)^" + re.escape(safe) + r"$", marker, markdown)
        replacements[marker] = normalize_html(fragment)
    # Reports may contain historical resource links outside the editorial
    # allowlist. Keep their labels; the canonical source retains destinations.
    html, _warnings = convert_legacy_to_html(markdown, "text/markdown")
    for marker, fragment in replacements.items():
        html = html.replace(f"<p>{marker}</p>", fragment)
    return normalize_html(html)


def agent_projection(agent: Agent) -> SourceMemoryDocument:
    code = _safe_inline(agent.code).casefold()
    return SourceMemoryDocument(
        source_kind=AGENT_SOURCE_KIND,
        source_ref=f"agent:{agent.id}",
        owner_agent_id=agent.id,
        memory_item_id=agent.memory_item_id,
        title=f"Profil agent — {_agent_name(agent, agent.id)}",
        memory_type="core",
        content=_editorial_projection(
            agent_to_markdown(agent), (agent.job_description, agent.personality)
        ),
        media_type="text/html",
        filename=f"agent-{agent.id}.html",
        keywords=(
            "agent",
            "profile",
            "profil",
            "identity",
            "identité",
            "personality",
            "personnalité",
            "job",
            "poste",
            f"agent:{agent.id}",
            f"agent-code:{code}",
        ),
        metadata={
            "projection_version": PROJECTION_VERSION,
            "source_kind": AGENT_SOURCE_KIND,
            "agent_id": agent.id,
            "agent_code": code,
        },
    )


def goal_projection(goal: Goal, *, description: str, tracking: str) -> SourceMemoryDocument:
    status = _enum_value(goal.status).casefold()
    memory_type = "episodic" if goal.status == GoalStatus.COMPLETED else "working"
    return SourceMemoryDocument(
        source_kind=GOAL_SOURCE_KIND,
        source_ref=f"goal:{goal.id}",
        owner_agent_id=goal.agent_id,
        memory_item_id=goal.memory_item_id,
        title=f"Objectif — {_safe_inline(goal.title)}",
        memory_type=memory_type,
        content=_editorial_projection(
            goal_to_markdown(goal, description=description, tracking=tracking),
            (description, tracking),
        ),
        media_type="text/html",
        filename=f"goal-{goal.id}.html",
        keywords=(
            "goal",
            "objectif",
            "tracking",
            "suivi",
            f"goal:{goal.id}",
            f"agent:{goal.agent_id}",
            f"status:{status}",
        ),
        metadata={
            "projection_version": PROJECTION_VERSION,
            "source_kind": GOAL_SOURCE_KIND,
            "goal_id": str(goal.id),
            "agent_id": goal.agent_id,
            "status": _enum_value(goal.status),
            "source_revision": goal.revision,
        },
    )


def goal_cycle_projection(cycle: GoalCycle) -> SourceMemoryDocument:
    status = _enum_value(cycle.status).casefold()
    verdict = _enum_value(cycle.verdict).casefold()
    keywords = [
        "goal",
        "objectif",
        "cycle",
        "report",
        "compte-rendu",
        "progress",
        "progression",
        f"goal:{cycle.goal_id}",
        f"goal-cycle:{cycle.id}",
        f"cycle:{cycle.sequence}",
        f"agent:{cycle.goal.agent_id}",
        f"status:{status}",
    ]
    if verdict:
        keywords.append(f"verdict:{verdict}")
    return SourceMemoryDocument(
        source_kind=GOAL_CYCLE_SOURCE_KIND,
        source_ref=f"goal-cycle:{cycle.id}",
        owner_agent_id=cycle.goal.agent_id,
        memory_item_id=cycle.memory_item_id,
        title=f"Cycle {cycle.sequence} — {_safe_inline(cycle.goal.title)}",
        memory_type="episodic",
        content=_editorial_projection(
            goal_cycle_to_markdown(cycle), (cycle.task.objective if cycle.task else None,)
        ),
        media_type="text/html",
        filename=f"goal-cycle-{cycle.id}.html",
        keywords=tuple(keywords),
        metadata={
            "projection_version": PROJECTION_VERSION,
            "source_kind": GOAL_CYCLE_SOURCE_KIND,
            "goal_cycle_id": str(cycle.id),
            "goal_id": str(cycle.goal_id),
            "agent_id": cycle.goal.agent_id,
            "sequence": cycle.sequence,
            "status": _enum_value(cycle.status),
            "verdict": _enum_value(cycle.verdict) or None,
            "task_id": str(cycle.task_id) if cycle.task_id is not None else None,
        },
    )


def _agent_query(agent_id: int, *, include_historized: bool = False):
    query = (
        select(Agent)
        .options(selectinload(Agent.title), selectinload(Agent.group))
        .where(Agent.id == agent_id)
    )
    if include_historized:
        query = query.execution_options(include_historized=True)
    return query


def _goal_query(goal_id: UUID, *, include_historized: bool = False):
    query = (
        select(Goal)
        .options(
            selectinload(Goal.agent).selectinload(Agent.title),
            selectinload(Goal.referrer_agent).selectinload(Agent.title),
        )
        .where(Goal.id == goal_id)
    )
    if include_historized:
        query = query.execution_options(include_historized=True)
    return query


async def _recent_goal_cycles(goal_id: UUID) -> list[GoalCycle]:
    """Load only the bounded projection window, including historized Tasks."""

    cycles = list(
        (
            await get_db().scalars(
                select(GoalCycle)
                .options(
                    selectinload(GoalCycle.task),
                    selectinload(GoalCycle.goal).selectinload(Goal.agent).selectinload(Agent.title),
                )
                .where(GoalCycle.goal_id == goal_id)
                .order_by(GoalCycle.sequence.desc(), GoalCycle.id.desc())
                .limit(GOAL_CYCLE_PROJECTION_LIMIT)
                .execution_options(include_historized=True)
            )
        ).all()
    )
    return sorted(cycles, key=lambda cycle: (cycle.sequence, str(cycle.id)))


async def _recent_goal_cycle_ids(goal_id: UUID) -> frozenset[UUID]:
    return frozenset(
        (
            await get_db().scalars(
                select(GoalCycle.id)
                .where(GoalCycle.goal_id == goal_id)
                .order_by(GoalCycle.sequence.desc(), GoalCycle.id.desc())
                .limit(GOAL_CYCLE_PROJECTION_LIMIT)
            )
        ).all()
    )


async def _forget_goal_cycle_projections_outside(
    goal_id: UUID,
    keep_cycle_ids: frozenset[UUID],
) -> int:
    """Bound provider and ORM work while removing projections outside a window."""

    db = get_db()
    removed = 0
    while True:
        query = select(GoalCycle.id, GoalCycle.memory_item_id).where(
            GoalCycle.goal_id == goal_id,
            GoalCycle.memory_item_id.is_not(None),
        )
        if keep_cycle_ids:
            query = query.where(GoalCycle.id.notin_(keep_cycle_ids))
        rows = list(
            (
                await db.execute(
                    query.order_by(GoalCycle.sequence, GoalCycle.id).limit(
                        _CYCLE_CLEANUP_BATCH_SIZE
                    )
                )
            ).all()
        )
        if not rows:
            return removed
        for cycle_id, memory_item_id in rows:
            if memory_item_id is None:
                continue
            await service.forget_source_managed_item(
                source_kind=GOAL_CYCLE_SOURCE_KIND,
                source_ref=f"goal-cycle:{cycle_id}",
                item_id=memory_item_id,
            )
            await db.execute(
                update(GoalCycle)
                .where(
                    GoalCycle.id == cycle_id,
                    GoalCycle.memory_item_id == memory_item_id,
                )
                .values(memory_item_id=None)
            )
            await db.commit()
            removed += 1


async def sync_agent_source(
    agent_id: int,
    *,
    action: str = "upsert",
    provider_code: str | None = None,
    recreate: bool = False,
) -> UUID | None:
    """Synchronize or remove the projection belonging to one Agent row."""

    if action not in {"upsert", "delete"}:
        raise ValueError(f"Unsupported Agent projection action: {action!r}.")
    agent = await get_db().scalar(_agent_query(agent_id, include_historized=action == "delete"))
    source_ref = f"agent:{agent_id}"
    if action == "delete" or agent is None or agent.deleted_at is not None:
        await service.forget_source_managed_item(
            source_kind=AGENT_SOURCE_KIND,
            source_ref=source_ref,
            item_id=agent.memory_item_id if agent is not None else None,
        )
        if agent is not None and agent.memory_item_id is not None:
            agent.memory_item_id = None
            await get_db().commit()
        return None

    item = await service.upsert_source_managed_item(
        agent_projection(agent),
        provider_code=provider_code,
        recreate=recreate,
    )
    if agent.memory_item_id != item.id:
        agent.memory_item_id = item.id
        await get_db().commit()
    return item.id


async def sync_goal_source(
    goal_id: UUID,
    *,
    action: str = "upsert",
    provider_code: str | None = None,
    recreate: bool = False,
) -> UUID | None:
    """Synchronize one Goal and its bounded recent-cycle projection window."""

    if action not in {"upsert", "delete"}:
        raise ValueError(f"Unsupported Goal projection action: {action!r}.")
    goal = await get_db().scalar(_goal_query(goal_id, include_historized=True))
    if action == "delete" or goal is None or goal.deleted_at is not None:
        await _forget_goal_cycle_projections_outside(goal_id, frozenset())
        await service.forget_source_managed_item(
            source_kind=GOAL_SOURCE_KIND,
            source_ref=f"goal:{goal_id}",
            item_id=goal.memory_item_id if goal is not None else None,
        )
        if goal is not None:
            goal.memory_item_id = None
            await get_db().commit()
        return None

    # Goal Tasks may be historized after their retention duty ends. They remain
    # canonical cycle evidence inside the bounded recent window.
    cycles = await _recent_goal_cycles(goal_id)
    markdown = await goal_service.read_markdown(goal)
    goal_item = await service.upsert_source_managed_item(
        goal_projection(
            goal,
            description=markdown.description,
            tracking=markdown.tracking,
        ),
        provider_code=provider_code,
        recreate=recreate,
    )
    goal.memory_item_id = goal_item.id
    await get_db().commit()
    for cycle in cycles:
        cycle_item = await service.upsert_source_managed_item(
            goal_cycle_projection(cycle),
            provider_code=provider_code,
            recreate=recreate,
        )
        cycle.memory_item_id = cycle_item.id
        await get_db().commit()
        await service.ensure_source_managed_link(
            source_item_id=cycle_item.id,
            target_item_id=goal_item.id,
            relation_type="cycle_of",
        )
    await _forget_goal_cycle_projections_outside(
        goal_id,
        frozenset(cycle.id for cycle in cycles),
    )
    return goal_item.id


async def sync_source_projection(
    *,
    source_kind: str,
    source_id: str,
    action: str = "upsert",
    provider_code: str | None = None,
    recreate: bool = False,
) -> UUID | None:
    """Dispatch one durable automation payload to its exact source projector."""

    if source_kind == AGENT_SOURCE_KIND:
        try:
            agent_id = int(source_id)
        except ValueError as exc:
            raise ValueError("An Agent projection requires an integer source ID.") from exc
        return await sync_agent_source(
            agent_id,
            action=action,
            provider_code=provider_code,
            recreate=recreate,
        )
    if source_kind == GOAL_SOURCE_KIND:
        try:
            goal_id = UUID(source_id)
        except ValueError as exc:
            raise ValueError("A Goal projection requires a UUID source ID.") from exc
        return await sync_goal_source(
            goal_id,
            action=action,
            provider_code=provider_code,
            recreate=recreate,
        )
    raise ValueError(f"Unsupported managed memory source kind: {source_kind!r}.")


async def _remove_orphaned_source_memories() -> int:
    """Forget projections whose canonical row (or parent Goal) was deleted."""

    db = get_db()
    agent_refs = {
        f"agent:{agent_id}"
        for agent_id in (await db.scalars(select(Agent.id).where(Agent.deleted_at.is_(None)))).all()
    }
    active_goal_ids = list(
        (await db.scalars(select(Goal.id).where(Goal.deleted_at.is_(None)))).all()
    )
    goal_refs = {f"goal:{goal_id}" for goal_id in active_goal_ids}
    cycle_refs: set[str] = set()
    for goal_id in active_goal_ids:
        cycle_refs.update(
            f"goal-cycle:{cycle_id}" for cycle_id in await _recent_goal_cycle_ids(goal_id)
        )
    valid_refs = {
        AGENT_SOURCE_KIND: agent_refs,
        GOAL_SOURCE_KIND: goal_refs,
        GOAL_CYCLE_SOURCE_KIND: cycle_refs,
    }
    items = list(
        (
            await db.scalars(
                select(MemoryItem)
                .where(
                    MemoryItem.source_managed.is_(True),
                    MemoryItem.managed_source_kind.in_(tuple(valid_refs)),
                )
                .order_by(MemoryItem.managed_source_kind, MemoryItem.managed_source_ref)
            )
        ).all()
    )
    removed = 0
    for item in items:
        source_kind = item.managed_source_kind
        source_ref = item.managed_source_ref
        if source_kind is None or source_ref is None:
            continue
        if source_ref in valid_refs[source_kind]:
            continue
        await service.forget_source_managed_item(
            source_kind=source_kind,
            source_ref=source_ref,
            item_id=item.id,
        )
        if source_kind == AGENT_SOURCE_KIND:
            try:
                source_id = int(source_ref.removeprefix("agent:"))
            except ValueError:
                source_id = 0
            if source_id > 0:
                await db.execute(
                    update(Agent)
                    .where(
                        Agent.id == source_id,
                        Agent.memory_item_id == item.id,
                    )
                    .values(memory_item_id=None)
                )
        elif source_kind == GOAL_SOURCE_KIND:
            try:
                source_uuid = UUID(source_ref.removeprefix("goal:"))
            except ValueError:
                source_uuid = None
            if source_uuid is not None:
                await db.execute(
                    update(Goal)
                    .where(
                        Goal.id == source_uuid,
                        Goal.memory_item_id == item.id,
                    )
                    .values(memory_item_id=None)
                )
        else:
            try:
                source_uuid = UUID(source_ref.removeprefix("goal-cycle:"))
            except ValueError:
                source_uuid = None
            if source_uuid is not None:
                await db.execute(
                    update(GoalCycle)
                    .where(
                        GoalCycle.id == source_uuid,
                        GoalCycle.memory_item_id == item.id,
                    )
                    .values(memory_item_id=None)
                )
        await db.commit()
        removed += 1
    return removed


async def rebuild_source_memories(
    *,
    missing_only: bool = True,
    recreate: bool = False,
    provider_code: str | None = None,
) -> SourceMemoryRebuildResult:
    """Rebuild projections from canonical rows, independently of current resources."""

    if provider_code is not None:
        get_storage(provider_code)
    db = get_db()
    active_goal_ids = list(
        (await db.scalars(select(Goal.id).order_by(Goal.created_at, Goal.id))).all()
    )
    stale_cycles_removed = 0
    for active_goal_id in active_goal_ids:
        stale_cycles_removed += await _forget_goal_cycle_projections_outside(
            active_goal_id,
            await _recent_goal_cycle_ids(active_goal_id),
        )
    orphans_removed = await _remove_orphaned_source_memories()
    agent_query = select(Agent.id).order_by(Agent.id)
    goal_query = select(Goal.id).order_by(Goal.created_at, Goal.id)
    if missing_only and not recreate:
        stale_projection_ids = select(MemoryItem.id).where(
            MemoryItem.source_managed.is_(True),
            or_(
                MemoryItem.metadata_["projection_version"].as_integer().is_(None),
                MemoryItem.metadata_["projection_version"].as_integer() < PROJECTION_VERSION,
            ),
        )
        agent_query = agent_query.where(
            or_(Agent.memory_item_id.is_(None), Agent.memory_item_id.in_(stale_projection_ids))
        )
        recent_cycle_ids = (
            select(GoalCycle.id)
            .where(GoalCycle.goal_id == Goal.id)
            .order_by(GoalCycle.sequence.desc(), GoalCycle.id.desc())
            .limit(GOAL_CYCLE_PROJECTION_LIMIT)
            .correlate(Goal)
        )
        missing_cycle = exists(
            select(GoalCycle.id).where(
                GoalCycle.id.in_(recent_cycle_ids),
                GoalCycle.memory_item_id.is_(None),
            )
        )
        goal_query = goal_query.where(
            or_(
                Goal.memory_item_id.is_(None),
                Goal.memory_item_id.in_(stale_projection_ids),
                missing_cycle,
            )
        )
    agent_ids = list((await db.scalars(agent_query)).all())
    goal_ids = list((await db.scalars(goal_query)).all())
    agent_synced = 0
    goal_synced = 0
    failures: list[str] = []
    for agent_id in agent_ids:
        try:
            await sync_agent_source(
                agent_id,
                provider_code=provider_code,
                recreate=recreate,
            )
            agent_synced += 1
        except Exception:
            await db.rollback()
            failures.append(f"agent:{agent_id}")
            logger.exception("Agent memory projection rebuild failed: agent={}", agent_id)
    for goal_id in goal_ids:
        try:
            await sync_goal_source(
                goal_id,
                provider_code=provider_code,
                recreate=recreate,
            )
            goal_synced += 1
        except Exception:
            await db.rollback()
            failures.append(f"goal:{goal_id}")
            logger.exception("Goal memory projection rebuild failed: goal={}", goal_id)
    return SourceMemoryRebuildResult(
        agents_scanned=len(agent_ids),
        agents_synced=agent_synced,
        goals_scanned=len(goal_ids),
        goals_synced=goal_synced,
        orphans_removed=orphans_removed,
        stale_cycles_removed=stale_cycles_removed,
        failures=tuple(failures),
    )


__all__ = [
    "AGENT_SOURCE_KIND",
    "GOAL_CYCLE_SOURCE_KIND",
    "GOAL_CYCLE_PROJECTION_LIMIT",
    "GOAL_SOURCE_KIND",
    "PROJECTION_VERSION",
    "SourceMemoryRebuildResult",
    "agent_projection",
    "agent_to_markdown",
    "goal_cycle_projection",
    "goal_cycle_to_markdown",
    "goal_projection",
    "goal_to_markdown",
    "rebuild_source_memories",
    "sync_agent_source",
    "sync_goal_source",
    "sync_source_projection",
]
