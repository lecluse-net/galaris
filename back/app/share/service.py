"""Common sharing commands. Callers authorize their resource and own the commit."""

from uuid import UUID

from sqlalchemy import delete, select

from core.database import get_db

from .contracts import Collaborator, PrincipalKind, SharingState, SharingUpdate
from .directory import directory
from .models import ShareConfig, ShareGrant


async def grants(share_id: UUID) -> list[ShareGrant]:
    return list(await get_db().scalars(select(ShareGrant).where(ShareGrant.share_id == share_id)))


async def state(
    share_id: UUID,
    *,
    owner_agent_id: int | None,
    owner_user_id: int | None,
    can_manage: bool,
    lock_version: int,
) -> SharingState:
    config = await get_db().get(ShareConfig, share_id)
    if config is None:
        raise LookupError("Sharing configuration not found")
    result = await directory(owner_agent_id=owner_agent_id, owner_user_id=owner_user_id)
    catalog = {(p.kind, p.id): p for p in [*result.options, *result.owner_groups]}
    recipients: dict[tuple[PrincipalKind, int], Collaborator] = {}
    for grant in await grants(share_id):
        # Older ownership transfers can leave a redundant owner grant behind.
        # Ownership already grants access and is never a sharing recipient.
        if (
            owner_agent_id is not None and grant.agent_id == owner_agent_id
        ) or (
            owner_user_id is not None and grant.user_id == owner_user_id
        ):
            continue
        kind: PrincipalKind = (
            "agent"
            if grant.agent_id is not None
            else "user"
            if grant.user_id is not None
            else "team"
        )
        identity = (
            grant.agent_id
            if grant.agent_id is not None
            else grant.user_id
            if grant.user_id is not None
            else grant.team_id
        )
        assert identity is not None
        recipient = catalog.get(
            (kind, identity), Collaborator(kind=kind, id=identity, label=f"#{identity}")
        )
        recipients[(kind, identity)] = recipient.model_copy(update={"can_write": grant.can_write})
    if config.group_access:
        for team in result.owner_groups:
            previous = recipients.get((team.kind, team.id))
            recipients[(team.kind, team.id)] = team.model_copy(
                update={
                    "can_write": config.group_access == 2 or bool(previous and previous.can_write)
                }
            )
    return result.model_copy(
        update={
            "lock_version": lock_version,
            "can_manage": can_manage,
            "options": result.options if can_manage else [],
            "grants": list(recipients.values()),
            "level": "public"
            if config.global_access
            else "groups"
            if any(k == "team" for k, _ in recipients)
            else "private",
            "can_write": config.global_access == 2,
        }
    )


async def set_grant(
    share_id: UUID, kind: PrincipalKind, principal: int, can_write: bool | None
) -> None:
    config = await get_db().scalar(
        select(ShareConfig).where(ShareConfig.id == share_id).with_for_update()
    )
    if config is None:
        raise LookupError("Sharing configuration not found")
    column = {"agent": ShareGrant.agent_id, "user": ShareGrant.user_id, "team": ShareGrant.team_id}[
        kind
    ]
    grant = await get_db().scalar(
        select(ShareGrant).where(ShareGrant.share_id == share_id, column == principal)
    )
    if can_write is None:
        if grant is not None:
            await get_db().delete(grant)
    elif grant is not None:
        grant.can_write = can_write
    else:
        get_db().add(
            ShareGrant(share_id=share_id, can_write=can_write, **{kind + "_id": principal})
        )
    config.revision += 1
    await get_db().flush()


async def replace(share_id: UUID, data: SharingUpdate, current: SharingState) -> None:
    if not current.can_manage:
        raise PermissionError("Sharing management is not allowed")
    if current.lock_version != data.expected_lock_version:
        from .contracts import SharingConflictError

        raise SharingConflictError("Sharing changed; reload before updating")
    recipients = {(g.kind, g.id): g for g in data.grants}
    if len(recipients) != len(data.grants):
        raise ValueError("Duplicate collaborators")
    has_groups = any(kind == "team" for kind, _ in recipients)
    if data.level == "groups" and not has_groups:
        raise ValueError("Select at least one group")
    if data.level == "private" and has_groups:
        raise ValueError("Group sharing requires the groups level")
    available = {(p.kind, p.id) for p in [*current.options, *current.grants]}
    if set(recipients) - available:
        raise LookupError("Collaborator not found")
    config = await get_db().scalar(
        select(ShareConfig).where(ShareConfig.id == share_id).with_for_update()
    )
    if config is None:
        raise LookupError("Sharing configuration not found")
    await get_db().execute(delete(ShareGrant).where(ShareGrant.share_id == share_id))
    for grant in recipients.values():
        get_db().add(
            ShareGrant(
                share_id=share_id, can_write=grant.can_write, **{grant.kind + "_id": grant.id}
            )
        )
    config.global_access = (2 if data.can_write else 1) if data.level == "public" else 0
    config.group_access = 0
    config.revision += 1
    await get_db().flush()
