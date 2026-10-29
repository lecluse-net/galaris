"""Own sharing intent and rebuildable, additive ACLs over personal trees.

The caller owns the transaction. A single transaction lock serializes placement
and ACL mutations so a late projection can never revive a revoked permission.
"""

from collections import deque
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select, literal, union_all

from app.agent import Agent, AgentTeamModel
from app.share import GrantUpdate, ShareConfig, ShareGrant, SharingState, SharingUpdate
from core.database import get_db
from core.team import TeamModel, TeamUserModel
from core.user import UserModel

from .models import DocumentNesting, DocumentSharingIntent, DocumentTag, DocumentTagAssignment, Document

Principal = tuple[str, int]


async def lock_sharing() -> None:
    await get_db().execute(select(func.pg_advisory_xact_lock(1195656264, 0)))


async def _grants(share_id: UUID) -> dict[Principal, bool]:
    result: dict[Principal, bool] = {}
    for row in await get_db().scalars(select(ShareGrant).where(ShareGrant.share_id == share_id)):
        kind = "agent" if row.agent_id is not None else "user" if row.user_id is not None else "team"
        identity = row.agent_id if row.agent_id is not None else row.user_id if row.user_id is not None else row.team_id
        assert identity is not None
        result[kind, identity] = row.can_write
    return result


def _serialized(grants: dict[Principal, bool]) -> list[dict[str, int | bool | str]]:
    return [{"kind": kind, "id": identity, "can_write": write}
        for (kind, identity), write in sorted(grants.items())]


def own_grants(intent: DocumentSharingIntent) -> dict[Principal, bool]:
    return {(grant.kind, grant.id): grant.can_write for grant in map(GrantUpdate.model_validate, intent.grants)}


async def ensure_intent(share_id: UUID) -> DocumentSharingIntent:
    db = get_db()
    intent = await db.get(DocumentSharingIntent, share_id)
    if intent is None:
        config = await db.get(ShareConfig, share_id)
        if config is None:
            raise LookupError("Sharing configuration not found")
        intent = DocumentSharingIntent(share_id=share_id, global_access=config.global_access,
            group_access=config.group_access, grants=[])
        db.add(intent)
        await capture_intent(share_id, intent=intent)
    return intent


async def capture_intent(share_id: UUID, *, intent: DocumentSharingIntent | None = None) -> None:
    db = get_db()
    intent = intent if intent is not None else await db.get(DocumentSharingIntent, share_id)
    config = await db.get(ShareConfig, share_id)
    assert config is not None
    if intent is None:
        intent = DocumentSharingIntent(share_id=share_id)
        db.add(intent)
    intent.global_access = config.global_access
    intent.group_access = config.group_access
    intent.grants = _serialized(await _grants(share_id))
    await db.flush()


async def _project(share_id: UUID, global_access: int, group_access: int, grants: dict[Principal, bool]) -> bool:
    db = get_db()
    config = await db.get(ShareConfig, share_id)
    assert config is not None
    current = await _grants(share_id)
    if (config.global_access, config.group_access, current) == (global_access, group_access, grants):
        return False
    config.global_access = global_access
    config.group_access = group_access
    config.revision += 1
    # Update surviving rows rather than replacing every identity on each repair.
    for row in list(await db.scalars(select(ShareGrant).where(ShareGrant.share_id == share_id))):
        kind = "agent" if row.agent_id is not None else "user" if row.user_id is not None else "team"
        identity = row.agent_id if row.agent_id is not None else row.user_id if row.user_id is not None else row.team_id
        assert identity is not None
        if (kind, identity) not in grants:
            await db.delete(row)
        else:
            row.can_write = grants[kind, identity]
    for (kind, identity), write in grants.items():
        if (kind, identity) not in current:
            db.add(ShareGrant(share_id=share_id, can_write=write, **{kind + "_id": identity}))
    await db.flush()
    return True


async def prepare_own_sharing(item: Document | DocumentTag) -> None:
    """Restore the own ACL before an existing command mutates it."""
    await lock_sharing()
    intent = await ensure_intent(item.share_id)
    grants = own_grants(intent)
    live = await _principal_keys()
    grants = {key: write for key, write in grants.items() if key in live}
    intent.grants = _serialized(grants)
    await _project(item.share_id, intent.global_access, intent.group_access, grants)


async def _principal_keys() -> set[Principal]:
    """JSON intent must follow the grant table's physical FK cascades."""
    db = get_db()
    result: set[Principal] = set()
    for kind, query in (
        ("agent", select(Agent.id)), ("user", select(UserModel.id)), ("team", select(TeamModel.id)),
    ):
        result.update((kind, identity) for identity in await db.scalars(query.execution_options(include_historized=True)))
    return result


async def finish_own_sharing(item: Document | DocumentTag) -> None:
    await capture_intent(item.share_id)
    await reconcile_sharing()
    await get_db().refresh(item, attribute_names=["grants", "share"])


async def replacement_intent(item: Document | DocumentTag, data: SharingUpdate, current: SharingState) -> SharingUpdate:
    """An unchanged effective recipient must not silently become an own grant."""
    intent = await ensure_intent(item.share_id)
    own = own_grants(intent)
    effective = {(g.kind, g.id): g.can_write for g in current.grants}
    grants: list[GrantUpdate] = []
    for grant in data.grants:
        key = (grant.kind, grant.id)
        if effective.get(key) != grant.can_write:
            grants.append(grant)
        elif key in own:
            grants.append(grant.model_copy(update={"can_write": own[key]}))
        elif intent.group_access and grant.kind == "team" and any(group.id == grant.id for group in current.owner_groups):
            grants.append(grant)
    # The effective public level can come entirely from an ancestor as well.
    inherited_public_unchanged = data.level == current.level == "public" and data.can_write == current.can_write
    public = intent.global_access if inherited_public_unchanged else (2 if data.can_write else 1) if data.level == "public" else 0
    return data.model_copy(update={"grants": grants, "level": "public" if public else "groups" if any(g.kind == "team" for g in grants) else "private", "can_write": public == 2})


@dataclass
class Policy:
    share_id: UUID
    owner_user: int | None
    own_group: int
    public: int
    grants: dict[Principal, bool] = field(default_factory=dict[Principal, bool])
    inherited: dict[Principal, bool] = field(default_factory=dict[Principal, bool])

    def merge(self, source: "Policy") -> bool:
        changed = source.public > self.public
        self.public = max(self.public, source.public)
        for key, write in source.grants.items():
            self.inherited[key] = self.inherited.get(key, False) or write
            if key not in self.grants or (write and not self.grants[key]):
                self.grants[key] = write
                changed = True
        return changed


async def reconcile_sharing() -> int:
    """Rebuild solely from own ACLs and current, owner-authorized placements."""
    await lock_sharing()
    db = get_db()
    await db.flush()
    agent_users = dict((await db.execute(select(Agent.id, Agent.user_id))).tuples().all())
    # Scalar projections deliberately avoid loading document payloads or histories.
    documents = select(Document.id, Document.share_id, Document.owner_user_id,
        Document.owner_agent_id, literal("document"), Document.read_only, literal(False),
        Document.document_type, Document.visibility)
    folders_query = select(DocumentTag.id, DocumentTag.share_id, DocumentTag.user_id,
        literal(None), literal("folder"), literal(False), literal(False), literal("html"), literal("private"))
    rows = (await db.execute(union_all(documents, folders_query))).all()
    shares = {row[1] for row in rows}
    sharing_ids = tuple(shares)
    configs = {config.id: config for config in await db.scalars(select(ShareConfig).where(ShareConfig.id.in_(sharing_ids)))}
    intents = {intent.share_id: intent for intent in await db.scalars(select(DocumentSharingIntent).where(DocumentSharingIntent.share_id.in_(sharing_ids)))}
    current_grants: dict[UUID, dict[Principal, bool]] = {share: {} for share in shares}
    for grant in await db.scalars(select(ShareGrant).where(ShareGrant.share_id.in_(sharing_ids))):
        kind = "agent" if grant.agent_id is not None else "user" if grant.user_id is not None else "team"
        principal = grant.agent_id if grant.agent_id is not None else grant.user_id if grant.user_id is not None else grant.team_id
        assert principal is not None
        current_grants[grant.share_id][kind, principal] = grant.can_write
    user_teams: dict[int, set[int]] = {}
    for user, team in (await db.execute(select(TeamUserModel.user_id, TeamUserModel.team_id))).tuples():
        user_teams.setdefault(user, set()).add(team)
    agent_teams: dict[int, set[int]] = {}
    for agent, team in (await db.execute(select(AgentTeamModel.agent_id, AgentTeamModel.team_id))).tuples():
        agent_teams.setdefault(agent, set()).add(team)
    policies: dict[UUID, Policy] = {}
    editable: set[UUID] = set()
    visibility: dict[UUID, str] = {}
    principals = await _principal_keys()
    for identity, share_id, user, agent, kind, read_only, managed, doc_type, current_visibility in rows:
        # Text and Data share documentary inheritance; Process keeps its ACLs.
        if kind == "document" and doc_type not in {"text", "html", "data"}:
            continue
        intent = intents.get(share_id)
        if intent is None:
            config = configs[share_id]
            intent = DocumentSharingIntent(share_id=share_id, global_access=config.global_access,
                group_access=config.group_access, grants=_serialized(current_grants[share_id]))
            db.add(intent)
            intents[share_id] = intent
        direct = own_grants(intent)
        pruned = {key: write for key, write in direct.items() if key in principals}
        if direct != pruned:
            intent.grants = _serialized(pruned)
        policies[identity] = Policy(share_id, user if user is not None else agent_users.get(agent),
            intent.group_access, intent.global_access, pruned)
        if kind == "document" and not read_only and not managed:
            editable.add(identity)
        if kind == "document" and not managed:
            visibility[identity] = current_visibility
        if intent.group_access:
            memberships = user_teams.get(user, set()) if user is not None else agent_teams.get(agent, set()) if agent is not None else set[int]()
            for team in memberships:
                policies[identity].grants["team", team] = policies[identity].grants.get(("team", team), False) or intent.group_access == 2
    tags = {tag.id: tag for tag in await db.scalars(select(DocumentTag))}
    edges: dict[UUID, set[UUID]] = {}
    placements: dict[tuple[int, UUID], set[UUID]] = {}
    folders = set(tags)

    def connect(parent: UUID | None, child: UUID | None, user: int) -> None:
        if parent is None or child is None:
            return
        placements.setdefault((user, parent), set()).add(child)

    for tag in tags.values():
        if tag.parent_id is not None and tag.parent_id in tags:
            connect(tag.parent_id, tag.id, tag.user_id)
    for tag_id, document_id in (await db.execute(select(DocumentTagAssignment.tag_id, DocumentTagAssignment.document_id))).tuples():
        if tag_id in tags:
            tag = tags[tag_id]
            connect(tag.id, document_id, tag.user_id)
    for user, parent, child in (await db.execute(select(DocumentNesting.user_id, DocumentNesting.parent_document_id, DocumentNesting.document_id))).tuples():
        connect(parent, child, user)
    shareable = editable | folders
    for (user, parent), children in placements.items():
        if parent not in policies or policies[parent].owner_user != user or parent not in shareable:
            continue
        # A received/read-only document is skipped, not reshared. Its position
        # must not prevent a folder rule reaching an owner's deeper descendants.
        pending_children: list[UUID] = list(children)
        seen: set[UUID] = {parent}
        while pending_children:
            child = pending_children.pop()
            if child in seen:
                continue
            seen.add(child)
            if child in policies and policies[child].owner_user == user and child in shareable:
                edges.setdefault(parent, set()).add(child)
            else:
                pending_children.extend(placements.get((user, child), ()))
    # A work queue computes the least fixed point, including cross-tree paths and
    # legacy cycles. Revocation starts from own intent, never yesterday's result.
    pending = deque(policies)
    queued = set(policies)
    while pending:
        parent = pending.popleft()
        queued.remove(parent)
        for child in edges.get(parent, ()):
            if policies[child].merge(policies[parent]) and child not in queued:
                pending.append(child)
                queued.add(child)
    changed = 0
    for identity, policy in policies.items():
        grants = own_grants(intents[policy.share_id])
        for key, write in policy.inherited.items():
            grants[key] = grants.get(key, False) or write
        config = configs[policy.share_id]
        expected_visibility = "shared" if policy.public or policy.own_group or grants else "private"
        visibility_drift = identity in visibility and visibility[identity] != expected_visibility
        if not visibility_drift and (config.global_access, config.group_access, current_grants[policy.share_id]) == (policy.public, policy.own_group, grants):
            continue
        if await _project(policy.share_id, policy.public, policy.own_group, grants) or visibility_drift:
            item = await db.get(DocumentTag if identity in folders else Document, identity)
            assert item is not None
            item.lock_version += 1
            if isinstance(item, Document) and identity in visibility:
                item.visibility = expected_visibility
            changed += 1
    await db.flush()
    if changed:
        db.info["document_sharing_changed"] = True
    return changed
