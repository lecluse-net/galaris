"""Exercise the public access matrix across independent resources and owners."""

import pytest
from sqlalchemy import delete, select

from app.agent import Agent, AgentManagementScope, AgentTeamModel
from app.dataset.models import Dataset
from app.dataset import access as dataset_access
from app.process.models import ProcessDefinition
from app.process import native_access as process_access
from app.share import ShareConfig, ShareEffectiveAccess, ShareGrant
from app.services import ServiceModel
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel


@pytest.mark.asyncio
async def test_effective_rights_follow_physical_deletions_without_removing_other_beneficiaries(db, agents):
    agent, _ = agents
    human = UserModel(email="cascade@example.test", hashed_password="unused", is_active=True)
    first, second = (ShareConfig(resource_kind="document") for _ in range(2))
    db.add_all([human, first, second])
    await db.flush()
    for policy in (first, second):
        db.add_all([
            ShareEffectiveAccess(share_id=policy.id, agent_id=agent.id, can_write=True),
            ShareEffectiveAccess(share_id=policy.id, user_id=human.id, can_write=False),
        ])
    await db.flush()

    async def beneficiaries():
        return set((await db.execute(select(ShareEffectiveAccess.share_id,
            ShareEffectiveAccess.agent_id, ShareEffectiveAccess.user_id)
            .where(ShareEffectiveAccess.share_id.in_((first.id, second.id))))).tuples())

    await db.execute(delete(ShareConfig).where(ShareConfig.id == first.id))
    assert await beneficiaries() == {(second.id, agent.id, None), (second.id, None, human.id)}
    await db.execute(delete(UserModel).where(UserModel.id == human.id))
    assert await beneficiaries() == {(second.id, agent.id, None)}
    await db.execute(delete(Agent).where(Agent.id == agent.id))
    assert await beneficiaries() == set()
    assert await db.scalar(select(ShareConfig.id).where(ShareConfig.id == second.id)) == second.id


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["dataset", "process"])
async def test_common_sql_preserves_existing_access_matrix(db, agents, domain):
    owner, recipient = agents
    human = UserModel(email=f"synthetic-share-{domain}@example.test", hashed_password="unused", is_active=True)
    team = TeamModel(name="Synthetic shared group")
    outsider = Agent(title_id=owner.title_id, code=f"synthetic-outsider-{domain}", first_name="Synthetic", last_name="Outsider", agent_driver="internal")
    db.add_all([human, team, outsider])
    await db.flush()
    db.add_all([AgentTeamModel(agent_id=owner.id, team_id=team.id),
        AgentTeamModel(agent_id=recipient.id, team_id=team.id), TeamUserModel(user_id=human.id, team_id=team.id)])
    if domain == "dataset":
        model, rules = Dataset, dataset_access
        resource = Dataset(owner_agent_id=owner.id, title="Synthetic ACL matrix", content="{}")
        foreign = Dataset(owner_agent_id=outsider.id, title="Synthetic unrelated resource", content="{}", group_access=2)
    else:
        model, rules = ProcessDefinition, process_access
        tool = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "galaris"))
        resource = ProcessDefinition(agent_id=owner.id, service_id=tool, label="Synthetic ACL matrix",
            code="synthetic_matrix", engine_process_id="synthetic_matrix")
        foreign = ProcessDefinition(agent_id=outsider.id, service_id=tool, label="Synthetic unrelated resource",
            code="synthetic_other", engine_process_id="synthetic_other", group_access=2)
    db.add_all([resource, foreign])
    await db.flush()
    actors = [owner.id, recipient.id, outsider.id, AgentManagementScope(human.id, frozenset()),
        AgentManagementScope(human.id, frozenset({recipient.id})), AgentManagementScope(human.id, None)]
    if domain == "dataset":
        actors.append(HumanActor(human.id))
    for recipient_kind in (None, "agent", "user", "team"):
        grant = None
        if recipient_kind is not None:
            identity = {"agent": recipient.id, "user": human.id, "team": team.id}[recipient_kind]
            grant = ShareGrant(share_id=resource.share_id, can_write=True, **{recipient_kind + "_id": identity})
            db.add(grant)
        for public, groups in ((0, 0), (1, 0), (2, 0), (0, 1), (0, 2)):
            resource.global_access, resource.group_access = public, groups
            await db.flush()
            for actor in actors:
                for write in (False, True):
                    full_scope = isinstance(actor, AgentManagementScope) and actor.agent_ids is None
                    owner_access = actor == owner.id or full_scope
                    team_member = actor in (owner.id, recipient.id) if isinstance(actor, int) else True
                    agent_grant = recipient_kind == "agent" and (actor == recipient.id or
                        isinstance(actor, AgentManagementScope) and actor.allows(recipient.id))
                    user_grant = recipient_kind == "user" and not isinstance(actor, int)
                    team_grant = recipient_kind == "team" and team_member
                    threshold = 2 if write else 1
                    expected = owner_access or public >= threshold or groups >= threshold and team_member or agent_grant or user_grant or team_grant
                    actual = set(await db.scalars(select(model.id).where(rules.accessible_clause(actor, write=write))))
                    assert (resource.id in actual) == bool(expected), (domain, recipient_kind, public, groups, actor, write)
                    assert (foreign.id in actual) == (actor == outsider.id or full_scope), ("foreign", domain, actor, write)
        if grant is not None:
            await db.delete(grant)
            await db.flush()
