"""A one-time, user-owned Galaris agent proposal, merged through DbAdmin."""

from typing import cast

from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import Assignment, Role
from core.database import get_db
from core.dbadmin import DbAdminDataset, DbAdminDatasetResult, reconcile_dataset
from core.user import UserModel, register_user_access_observer

from .models import Agent, Title
from .observers import notify_agent_profile


async def _rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    # Signup and DbAdmin may overlap in different workers. The lock and all seed
    # effects belong to the same transaction; failed initialization can retry.
    await session.execute(text("SELECT pg_advisory_xact_lock(719362840125)"))
    if await session.scalar(
        select(Agent.id).where(Agent.initialization_key == "galaris")
        .execution_options(include_historized=True)
    ) is not None:
        return ()
    manager_id = await session.scalar(
        select(UserModel.id)
        .join(Assignment, Assignment.user_id == UserModel.id)
        .join(Role, Role.id == Assignment.role_id)
        .where(UserModel.is_active.is_(True), Role.code == "admin")
        .order_by(UserModel.id).limit(1)
    )
    title_id = await session.scalar(select(Title.id).order_by(Title.id).limit(1))
    if manager_id is None or title_id is None:
        return ()
    occupied = set((await session.scalars(
        select(Agent.code).execution_options(include_historized=True)
    )).all())
    code = "galaris"
    suffix = 2
    while code in occupied:
        code = f"galaris-{suffix}"
        suffix += 1
    return ({
        "initialization_key": "galaris", "code": code,
        "first_name": "Galaris", "last_name": "",
        "user_id": manager_id, "title_id": title_id,
        "agent_driver": "internal", "task_harness_id": None, "profile_id": None,
        "profile_media_type": "text/html",
        "job_title": "Galaris assistant",
        "job_description": (
            "<p>Help the user understand, configure and administer Galaris. "
            "Consult the Galaris documentation for product behavior and configuration, "
            "and use the available administration tools to carry out their requests.</p>"
        ),
    },)


async def _after_merge(session: AsyncSession, result: DbAdminDatasetResult) -> None:
    if not result.inserted:
        return
    from app.skill import skill_service
    from app.tools import initialize_admin_agent_connections

    agent_id = (await session.scalars(
        select(Agent.id).where(Agent.initialization_key == "galaris")
    )).one()
    await initialize_admin_agent_connections(agent_id)
    await skill_service.ensure_assignment_matrix(agent_id=agent_id)


def default_agent_dataset() -> DbAdminDataset:
    return DbAdminDataset(
        key="app.agent.initial_galaris",
        table=cast(Table, Agent.__table__),
        natural_key=("initialization_key",),
        rows=_rows,
        update_columns=(),
        after_merge=_after_merge,
        depends_on=("app.llm.current_profile", "app.skill.assignments", "core.authorize.admin_role"),
    )


async def _on_user_access_changed(_user_id: int | None) -> None:
    # Fresh installations have no manager when DbAdmin first runs. Reuse the
    # exact same dataset once signup has committed the administrator account.
    session = get_db()
    # User lifecycle observers isolate failures: never leave a partial seed for
    # another observer (or the request middleware) to accidentally commit.
    async with session.begin_nested():
        result = await reconcile_dataset(session, default_agent_dataset())
    await session.commit()
    if result.inserted:
        agent_id = (await session.scalars(
            select(Agent.id).where(Agent.initialization_key == "galaris")
        )).one()
        await notify_agent_profile(agent_id, "create")


def register_default_agent() -> None:
    register_user_access_observer("agent_default_proposal", _on_user_access_changed)
