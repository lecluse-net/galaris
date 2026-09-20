"""Contract tests for personal ChatGPT subscription attribution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_managed_runtime_credential, llm_provider_service, proxy_service
from app.llm.provider_models import LLM, LLMProvider
from app.llm.provider_schemas import LLMProviderUpdate, ProviderCatalogConfigure
from app.llm.subscription_policy import (
    SubscriptionAccessError,
    enforce_subscription_access,
    ensure_subscription_confirmation,
    llm_execution_scope,
)
from bridge.openai import codex_oauth
from app.task import Task, TaskCreate, task_service
from core.user import user_service
from core.user.models import User


def _provider(owner_id: int | None, *, catalog_code: str = "openai-codex") -> LLMProvider:
    return LLMProvider(
        name="ChatGPT test",
        catalog_code=catalog_code,
        provider_type="openai_codex",
        base_url="https://chatgpt.com/backend-api/codex",
        user_id=owner_id,
        is_active=True,
        subscription_acknowledged=True,
    )


async def _user(db: AsyncSession, suffix: str) -> User:
    user = User(
        email=f"subscription-{suffix}@example.test",
        hashed_password="not-used",
        display_name=f"Subscription {suffix}",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_non_subscription_provider_is_not_restricted(db: AsyncSession) -> None:
    del db
    assert (
        await enforce_subscription_access(
            _provider(None, catalog_code="openai-api"),
            task_id=None,
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [False, None])
async def test_unacknowledged_subscription_is_denied_even_to_its_owner(
    db: AsyncSession, acknowledged: bool | None,
) -> None:
    owner = await _user(db, "owner")
    provider = _provider(owner.id)
    # None also covers a transient/legacy object without explicit confirmation.
    setattr(provider, "subscription_acknowledged", acknowledged)
    user_service.set_current_user(None)

    with llm_execution_scope(requester_user_id=owner.id):
        with pytest.raises(SubscriptionAccessError, match="confirmation"):
            await enforce_subscription_access(provider, task_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entrypoint",
    ["chat", "chat_stream", "responses", "responses_stream", "compact",
     "runtime", "models", "catalog", "oauth"],
)
async def test_connected_subscription_cannot_be_used_after_confirmation_is_revoked(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, entrypoint: str,
) -> None:
    owner = await _user(db, "owner")
    provider = await llm_provider_service.configure_catalog_provider(
        "openai-codex",
        ProviderCatalogConfigure(user_id=owner.id, subscription_acknowledged=True),
    )
    provider.oauth_credentials = "existing-encrypted-credentials"
    model = LLM(
        llm_provider_id=provider.id, code="confirmation-test", llm_name="gpt-test",
        label="Confirmation test",
    )
    db.add(model)
    await db.commit()
    await ensure_subscription_confirmation(provider)
    await llm_provider_service.update_provider(
        provider.id, LLMProviderUpdate(subscription_acknowledged=False),
    )
    assert provider.is_active and provider.oauth_connected
    token = AsyncMock(side_effect=AssertionError("Upstream credentials must not be used"))
    monkeypatch.setattr(codex_oauth, "get_access_token", token)
    user_service.set_current_user(None)

    with llm_execution_scope(requester_user_id=owner.id):
        with pytest.raises(SubscriptionAccessError, match="confirmation"):
            if entrypoint == "runtime":
                await get_managed_runtime_credential("openai-codex")
            elif entrypoint == "models":
                await llm_provider_service.list_models(provider.id)
            elif entrypoint == "catalog":
                await llm_provider_service.list_catalog_resources("openai-codex", "chat")
            elif entrypoint == "oauth":
                await llm_provider_service.ensure_subscription_owner(provider)
            elif entrypoint.startswith("chat"):
                await proxy_service.proxy_chat_completion(
                    {"model": model.code, "messages": [], "stream": entrypoint.endswith("stream")},
                    task_id=None, llm_override=model, route_executor_model=False,
                )
            else:
                await proxy_service.proxy_responses(
                    {"model": model.code, "input": [], "stream": entrypoint.endswith("stream")},
                    task_id=None, llm_override=model, route_executor_model=False,
                    operation="compact" if entrypoint == "compact" else "create",
                )
    token.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_is_global_without_sql_and_tracks_configuration_changes(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import subscription_policy

    owner = await _user(db, "owner")
    provider = await llm_provider_service.configure_catalog_provider(
        "openai-codex",
        ProviderCatalogConfigure(user_id=owner.id, subscription_acknowledged=True),
    )
    # Simulate the first check after restart, using the already-loaded provider.
    monkeypatch.setattr(subscription_policy, "_chatgpt_acknowledged", None)
    statements: list[str] = []
    connection = await db.connection()

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", record_sql)
    try:
        for _ in range(3):
            await ensure_subscription_confirmation(provider)
        assert statements == []

        # A partial save keeps confirmation; changing the owner revokes it globally.
        await llm_provider_service.configure_catalog_provider(
            "openai-codex", ProviderCatalogConfigure(),
        )
        await ensure_subscription_confirmation(provider)
        other = await _user(db, "other")
        await llm_provider_service.configure_catalog_provider(
            "openai-codex", ProviderCatalogConfigure(user_id=other.id),
        )
        stale_provider = _provider(owner.id)
        statements.clear()
        with pytest.raises(SubscriptionAccessError, match="confirmation"):
            await ensure_subscription_confirmation(stale_provider)
        assert statements == []

        await llm_provider_service.update_provider(
            provider.id, LLMProviderUpdate(subscription_acknowledged=True),
        )
        await ensure_subscription_confirmation(provider)
        await llm_provider_service.delete_provider(provider.id)
        with pytest.raises(SubscriptionAccessError, match="confirmation"):
            await ensure_subscription_confirmation(stale_provider)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", record_sql)


@pytest.mark.asyncio
async def test_single_user_fallback_never_applies_to_unlinked_messenger(
    db: AsyncSession,
) -> None:
    owner = await _user(db, "owner")
    user_service.set_current_user(None)

    assert await enforce_subscription_access(_provider(owner.id), task_id=None) == owner.id
    with llm_execution_scope(messenger_origin=True):
        with pytest.raises(SubscriptionAccessError, match="Messenger"):
            await enforce_subscription_access(_provider(owner.id), task_id=None)


@pytest.mark.asyncio
async def test_explicit_owner_is_allowed_and_other_user_is_denied(
    db: AsyncSession,
) -> None:
    owner = await _user(db, "owner")
    other = await _user(db, "other")
    user_service.set_current_user(None)

    with llm_execution_scope(requester_user_id=owner.id, messenger_origin=True):
        assert await enforce_subscription_access(_provider(owner.id), task_id=None) == owner.id
    with llm_execution_scope(requester_user_id=other.id, messenger_origin=True):
        with pytest.raises(SubscriptionAccessError, match="owner"):
            await enforce_subscription_access(_provider(owner.id), task_id=None)


@pytest.mark.asyncio
async def test_inactive_subscription_owner_is_denied(db: AsyncSession) -> None:
    owner = await _user(db, "inactive")
    owner.is_active = False
    await db.commit()
    user_service.set_current_user(None)

    with llm_execution_scope(requester_user_id=owner.id):
        with pytest.raises(SubscriptionAccessError, match="active"):
            await enforce_subscription_access(_provider(owner.id), task_id=None)


@pytest.mark.asyncio
async def test_task_children_inherit_the_durable_requester(db: AsyncSession) -> None:
    owner = await _user(db, "owner")
    parent = Task(label="Parent", requester_user_id=owner.id)
    db.add(parent)
    await db.commit()
    await db.refresh(parent)

    child = await task_service.create(TaskCreate(label="Child", parent_id=parent.id))

    assert child.requester_user_id == owner.id
    assert await enforce_subscription_access(_provider(owner.id), task_id=child.id) == owner.id


@pytest.mark.asyncio
async def test_chatgpt_configuration_requires_and_projects_an_active_owner(
    db: AsyncSession,
) -> None:
    owner = await _user(db, "owner")

    with pytest.raises(ValueError, match="owns"):
        await llm_provider_service.configure_catalog_provider(
            "openai-codex",
            ProviderCatalogConfigure(is_active=True),
        )

    provider = await llm_provider_service.configure_catalog_provider(
        "openai-codex",
        ProviderCatalogConfigure(is_active=True, user_id=owner.id, subscription_acknowledged=True),
    )
    catalog = await llm_provider_service.get_provider_catalog()

    assert provider.user_id == owner.id
    assert provider.subscription_acknowledged is True
    connection = next(item.connection for item in catalog.items if item.code == "openai-codex")
    assert connection is not None
    assert connection.subscription_acknowledged is True
    assert catalog.active_user_count == 1
    assert [(item.id, item.label) for item in catalog.users] == [
        (owner.id, owner.display_name)
    ]

    other = await _user(db, "other")
    provider = await llm_provider_service.configure_catalog_provider(
        "openai-codex", ProviderCatalogConfigure(user_id=other.id),
    )
    assert provider.subscription_acknowledged is False
    provider = await llm_provider_service.update_provider(
        provider.id, LLMProviderUpdate(subscription_acknowledged=True),
    )
    assert provider is not None and provider.subscription_acknowledged is True
    provider = await llm_provider_service.update_provider(
        provider.id, LLMProviderUpdate(user_id=owner.id),
    )
    assert provider is not None and provider.subscription_acknowledged is False
