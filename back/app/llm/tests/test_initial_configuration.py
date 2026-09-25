"""Installation proposals belong to administrators after their first creation."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import initial_configuration, llm_provider_service, llm_service, profile_service
from app.llm.dbadmin import register_dbadmin
from app.llm.profile_models import LlmProfile, PROFILE_MODEL_FIELDS
from app.llm.provider_models import LLM, LLMProvider
from core.dbadmin import DbAdminActionStatus, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.dbadmin.actions import run_actions, run_datasets


FRESH = SchemaTransitionSet(added_tables=frozenset({"llm_providers", "llms", "llm_profiles"}))


def _registry() -> DbAdminRegistry:
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    from core.params.dbadmin import register_dbadmin as register_params
    from core.authorize.dbadmin import register_dbadmin as register_authorize
    register_authorize(registry)
    register_params(registry)
    return registry


@pytest.mark.parametrize("tables", [(), ("llm_profiles",), ("llms",), ("llm_providers", "llms")])
def test_existing_installations_are_not_eligible(tables):
    assert not initial_configuration.needs_initial_configuration(
        SchemaTransitionSet(added_tables=frozenset(tables)),
    )
    assert initial_configuration.needs_initial_configuration(FRESH)


@pytest.mark.asyncio
async def test_installation_selects_models_without_credentials_and_preserves_edits(db: AsyncSession):
    # The real test database bootstrap has already run DbAdmin on a fresh schema.
    provider = (await db.scalars(select(LLMProvider))).one()
    profile = (await db.scalars(select(LlmProfile))).one()
    models = {model.code: model for model in await db.scalars(select(LLM))}
    assert provider.catalog_code == "openrouter"
    assert provider.api_key is None and provider.oauth_credentials is None
    assert provider.api_key_configured is False
    assert len(models) == 9
    assert {model.llm_provider_id for model in models.values()} == {provider.id}
    assert await profile_service.get_current_profile_id() == profile.id
    for field, code in initial_configuration.INITIAL_SELECTIONS.items():
        selected = await llm_service.get_profile_llm(field)
        assert selected is not None and selected.id == models[code].id
    assert profile.sound_generation_llm_id is None
    assert [getattr(profile, f"text_{tier}_reasoning_effort")
            for tier in ("ultra_low", "low", "standard", "high")] == ["none", "low", "medium", "high"]

    await profile_service.update_profile(profile.id, label="Custom setup", values={"text_high_reasoning_effort": "low"})
    provider.name = "Custom connection"
    provider.is_active = False
    await db.commit()
    await initial_configuration.initialize_configuration(db, FRESH)
    registry = _registry()
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not results and not issues
    assert not await run_datasets(registry)
    await db.refresh(profile)
    await db.refresh(provider)
    assert profile.label == "Custom setup" and profile.text_high_reasoning_effort == "low"
    assert provider.name == "Custom connection" and provider.is_active is False
    assert len((await db.scalars(select(LLM))).all()) == 9


@pytest.mark.asyncio
async def test_deleted_defaults_stay_deleted_after_synchronization(db: AsyncSession):
    provider = (await db.scalars(select(LLMProvider))).one()
    profile = (await db.scalars(select(LlmProfile))).one()
    replacement = await profile_service.create_profile("My empty profile")
    assert await llm_service.delete_llm(profile.text_high_llm_id)
    registry = _registry()
    await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not await run_datasets(registry)
    await db.refresh(profile)
    assert profile.text_high_llm_id is None
    assert len((await db.scalars(select(LLM))).all()) == 8
    assert await llm_provider_service.delete_provider(provider.id)
    assert await profile_service.delete_profile(profile.id)
    await db.commit()
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not results and not issues
    assert not await run_datasets(registry)
    assert not (await db.scalars(select(LLMProvider))).all()
    assert not (await db.scalars(select(LLM))).all()
    assert [row.id for row in await db.scalars(select(LlmProfile))] == [replacement.id]
    await db.refresh(replacement)
    assert all(getattr(replacement, field) is None for field in PROFILE_MODEL_FIELDS)


@pytest.mark.asyncio
async def test_initialization_rolls_back_and_can_be_retried(db: AsyncSession, monkeypatch):
    await db.execute(delete(LlmProfile))
    await db.execute(delete(LLM))
    await db.execute(delete(LLMProvider))
    await db.commit()
    original = initial_configuration.INITIAL_SELECTIONS
    monkeypatch.setattr(initial_configuration, "INITIAL_SELECTIONS", {"text_high_llm_id": "missing-synthetic-model"})
    registry = _registry()
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, FRESH)
    assert results[0].status is DbAdminActionStatus.FAILED
    assert issues and issues[0].fatal
    assert not (await db.scalars(select(LLMProvider))).all()
    assert not (await db.scalars(select(LLM))).all()
    assert not await initial_configuration.initial_configuration_complete(db, FRESH)
    # The remaining DbAdmin datasets still run after a failed AFTER_EXPAND action.
    assert not await run_datasets(registry)
    empty_profile = (await db.scalars(select(LlmProfile))).one()
    assert empty_profile.text_high_llm_id is None
    monkeypatch.setattr(initial_configuration, "INITIAL_SELECTIONS", original)
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not issues and results[0].status is DbAdminActionStatus.APPLIED
    assert await initial_configuration.initial_configuration_complete(db, FRESH)
    await initial_configuration.initialize_configuration(db, FRESH)
    assert len((await db.scalars(select(LLMProvider))).all()) == 1
    assert len((await db.scalars(select(LLM))).all()) == 9
    await db.refresh(empty_profile)
    assert empty_profile.text_high_llm_id is not None
    assert len((await db.scalars(select(LlmProfile))).all()) == 1
