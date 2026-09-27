"""Remembered permissions built on the canonical human-choice mechanism."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db
from core.i18n import t
from core.user import UserModel, user_service

from .interactions import ChoiceOption, ChoiceRequest, ChoiceResolution, PendingChoice, create_choice, register_choice_handler
from .models import Interaction, PermissionDecision, MessengerUser
from .permission_schemas import PermissionPage, PermissionRead
from .events import interaction_changed

KIND = "remembered_permission"


async def list_decisions(*, managed_agent_ids: frozenset[int] | None,
                         agent_id: int | None, allowed: bool | None,
                         offset: int, limit: int) -> PermissionPage:
    query = select(PermissionDecision)
    if managed_agent_ids is not None:
        query = query.where(PermissionDecision.agent_id.in_(managed_agent_ids))
    if agent_id is not None:
        query = query.where(PermissionDecision.agent_id == agent_id)
    if allowed is not None:
        query = query.where(PermissionDecision.allowed.is_(allowed))
    db = get_db()
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(query.add_columns(func.coalesce(UserModel.display_name, UserModel.email))
                            .outerjoin(UserModel, UserModel.id == PermissionDecision.approver_user_id)
                            .order_by(PermissionDecision.created_at.desc(), PermissionDecision.id)
                            .offset(offset).limit(limit))
    items: list[PermissionRead] = []
    for record, label in rows:
        item = PermissionRead.model_validate(record)
        item.approver_label = label or str(record.approver_user_id)
        items.append(item)
    return PermissionPage(items=items, total=total)


async def delete_decision(identifier: UUID, *, managed_agent_ids: frozenset[int] | None) -> bool:
    db = get_db()
    record = await db.scalar(select(PermissionDecision).where(
        PermissionDecision.id == identifier,
    ).with_for_update())
    if record is None or (managed_agent_ids is not None and record.agent_id not in managed_agent_ids):
        return False
    record.soft_delete()
    expired = await _expire_question(record)
    await db.commit()
    if expired is not None:
        await interaction_changed.send_async(expired)
    return True


async def _expire_question(record: PermissionDecision) -> Interaction | None:
    if record.interaction_id is None:
        return None
    interaction = await get_db().get(Interaction, record.interaction_id)
    if interaction is not None and interaction.status == "PENDING":
        interaction.expires_at = datetime.now(timezone.utc)
        await get_db().flush()
        return interaction
    return None


async def request_permission(agent_id: int, key: str, question: str) -> PermissionDecision:
    """Return a current decision, creating at most one active question per key."""
    from app.agent import get_agent_record
    if not key or len(key) > 512 or not question or len(question) > 4000:
        raise ValueError("Invalid permission request")
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise PermissionError("The agent has no permission approver")
    db = get_db()
    expired: Interaction | None = None
    record = await db.scalar(select(PermissionDecision).where(
        PermissionDecision.agent_id == agent_id, PermissionDecision.permission_key == key,
    ).execution_options(populate_existing=True))
    # An old manager's decision cannot silently become a new manager's decision.
    if record is not None and record.approver_user_id != agent.user_id:
        record.soft_delete()
        expired = await _expire_question(record)
        await db.flush()
        record = None
    if record is None:
        await db.execute(insert(PermissionDecision).values(
            id=uuid4(), agent_id=agent_id, permission_key=key, question=question,
            approver_user_id=agent.user_id,
        ).on_conflict_do_nothing(index_elements=["agent_id", "permission_key"],
                                index_where=PermissionDecision.deleted_at.is_(None)))
        await db.commit()
        if expired is not None:
            await interaction_changed.send_async(expired)
        record = await db.scalar(select(PermissionDecision).where(
            PermissionDecision.agent_id == agent_id, PermissionDecision.permission_key == key,
        ).execution_options(populate_existing=True))
    if record is None:
        raise RuntimeError("Permission request was concurrently removed; retry")
    if record.allowed is None:
        await _notify(record)
    return record


async def _notify(record: PermissionDecision) -> None:
    """A durable lease prevents concurrent sends; failed delivery can be retried."""
    from .service import messenger_for_agent, messenger_for_agent_kind

    now = datetime.now(timezone.utc)
    db = get_db()
    previous = await db.scalar(select(Interaction).where(
        Interaction.kind == KIND,
        Interaction.metadata_["permission_decision_id"].as_string() == str(record.id),
    ).order_by(Interaction.created_at.desc()).limit(1))
    if previous is not None and previous.expires_at > now:
        if record.interaction_id != previous.id:
            record.interaction_id = previous.id
            await db.commit()
        return
    if record.interaction_id is not None:
        # A timed-out question must not make an undecided permission unusable.
        record.interaction_id = None
        record.notification_after = None
        await db.flush()
    claimed = await db.scalar(update(PermissionDecision).where(
        PermissionDecision.id == record.id, PermissionDecision.allowed.is_(None),
        PermissionDecision.interaction_id.is_(None),
        or_(PermissionDecision.notification_after.is_(None), PermissionDecision.notification_after <= now),
    ).values(notification_after=now + timedelta(seconds=60)).returning(PermissionDecision.id))
    await db.commit()
    if claimed is None:
        return
    try:
        messenger = await messenger_for_agent(record.agent_id)
        if messenger is None:
            messenger = await messenger_for_agent_kind(record.agent_id, "internal")
        identity = await db.scalar(select(MessengerUser).where(
            MessengerUser.tool_id == messenger.tool_id,
            MessengerUser.galaris_user_id == record.approver_user_id,
            MessengerUser.is_ai.is_(False),
        ).limit(1))
        if identity is None and messenger.kind != "internal":
            messenger = await messenger_for_agent_kind(record.agent_id, "internal")
        external_user = identity.external_id if identity is not None else f"user:{record.approver_user_id}"
        try:
            room = await messenger.ensure_direct_room(external_user)
        except (LookupError, PermissionError) as exc:
            # A first internal conversation also creates the verified identity.
            # Existing contact-policy denials must still propagate unchanged.
            if messenger.kind != "internal" or (isinstance(exc, PermissionError) and identity is not None):
                raise
            from .native_facade import create_internal_room
            created = await create_internal_room(actor_user_id=record.approver_user_id, agent_id=record.agent_id)
            if created is None:
                raise LookupError("No internal channel for the permission approver") from None
            room = await messenger.ensure_direct_room(external_user)
        user = await user_service.get_user_by_id(record.approver_user_id)
        language = getattr(user, "language", None) or "en"
        interaction = await create_choice(
            messenger, agent_id=record.agent_id, room_id=str(room.id), user_id=external_user,
            request=ChoiceRequest(
                kind=KIND, title=t("permissions.title", language), body=record.question,
                options=[
                    ChoiceOption(id="allow", label=t("permissions.allow", language), aliases=["yes", "oui", "ok"]),
                    ChoiceOption(id="deny", label=t("permissions.deny", language), aliases=["no", "non"]),
                ],
                metadata={"permission_decision_id": str(record.id)},
                timeout_seconds=604800, language=language,
            ),
            idempotency_key=f"permission:{record.id}:{previous.id if previous is not None else 'initial'}",
        )
        record.interaction_id = interaction.id
        await db.commit()
    except Exception:
        logger.exception("Permission notification failed for {}", record.id)


async def _answer(interaction: PendingChoice, resolution: ChoiceResolution) -> None:
    from app.agent import get_agent_record
    if resolution.option_id not in {"allow", "deny"}:
        return
    identifier = UUID(str(interaction.metadata["permission_decision_id"]))
    db = get_db()
    record = await db.scalar(select(PermissionDecision).where(
        PermissionDecision.id == identifier,
    ).with_for_update().execution_options(populate_existing=True))
    if record is None or record.allowed is not None or record.agent_id != interaction.agent_id:
        return
    agent = await get_agent_record(record.agent_id)
    if agent is None or agent.user_id != record.approver_user_id:
        return
    record.allowed = resolution.option_id == "allow"
    record.answered_at = datetime.now(timezone.utc)
    record.interaction_id = interaction.id
    await db.commit()


register_choice_handler(KIND, _answer)
