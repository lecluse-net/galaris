"""Tests for LLM configuration profiles (column-based model)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.goal import goal_service
from app.llm import llm_service, model_usages, profile_service
from app.llm.profile_models import LlmProfile
from app.llm.provider_models import LLM, LLMProvider
from app.llm.provider_schemas import LLMCreate, LLMUpdate
from core.params import Param, Params, params_service


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_params_cache() -> None:
    """Reset the params cache around every test.

    The current-profile helpers read through this process-global cache; without
    a reset, values written by one test would leak into the next.
    """
    params_service._params_cache = {}
    params_service._cache_loaded = False
    yield
    params_service._params_cache = {}
    params_service._cache_loaded = False


def _provider(name: str = "Profile test") -> LLMProvider:
    return LLMProvider(
        name=name,
        catalog_code=None,
        provider_type="openai_compatible",
        base_url="https://example.test/v1",
        configuration={},
        is_active=True,
    )


def _llm(provider_id: int, suffix: str = "main") -> LLM:
    return LLM(
        llm_provider_id=provider_id,
        code=f"profile-{suffix}",
        llm_name=f"test/{suffix}",
        label=f"Profile {suffix}",
        resource_type="model",
        primary_capability="chat",
        service_capabilities=["chat"],
        pricing={},
    )


async def _seed_llms(db: AsyncSession) -> tuple[LLM, LLM]:
    provider = _provider()
    db.add(provider)
    await db.flush()
    first = _llm(provider.id, "first")
    second = _llm(provider.id, "second")
    db.add_all([first, second])
    await db.commit()
    return first, second


async def _clear_profiles(db: AsyncSession) -> None:
    await db.execute(delete(LlmProfile))
    await db.commit()


async def test_text_usages_share_the_expected_profile_tiers() -> None:
    assert model_usages.DREAM == model_usages.TEXT_ULTRA_LOW
    assert model_usages.DISPATCHER == model_usages.TEXT_LOW
    assert model_usages.CONVERSATION == model_usages.TEXT_LOW
    assert model_usages.BRIEFING == model_usages.TEXT_STANDARD
    assert model_usages.EXECUTOR == model_usages.TEXT_STANDARD
    assert model_usages.GOAL == model_usages.TEXT_STANDARD
    assert model_usages.EXECUTOR_HIGH == model_usages.TEXT_HIGH
    assert model_usages.PLANNER == model_usages.TEXT_HIGH
    assert model_usages.LAB == model_usages.TEXT_HIGH


async def test_llm_subscription_flag_is_persisted_and_editable(db: AsyncSession) -> None:
    provider = _provider("Subscription provider")
    db.add(provider)
    await db.commit()

    llm = await llm_service.create_llm(LLMCreate(
        llm_provider_id=provider.id,
        code="subscription-model",
        llm_name="provider/subscription-model",
        label="Subscription model",
        is_subscription=True,
    ))
    assert llm.is_subscription is True

    updated = await llm_service.update_llm(
        llm.id,
        LLMUpdate(is_subscription=False),
    )
    assert updated is not None
    assert updated.is_subscription is False


@pytest.mark.parametrize("primary_capability", ["chat", "vision"])
async def test_multimodal_llm_keeps_capabilities_and_supports_goal_tracking(
    db: AsyncSession, primary_capability: str,
) -> None:
    provider = _provider("Multimodal provider")
    db.add(provider)
    await db.commit()
    llm = await llm_service.create_llm(LLMCreate(
        llm_provider_id=provider.id,
        code="multimodal-model",
        llm_name="deepseek/deepseek-v4.1-flash",
        label="Multimodal model",
        primary_capability=primary_capability,
        service_capabilities=["vision", "chat"],
        input_text=True, input_image=True, output_text=True,
    ))
    llm_id = llm.id
    db.expunge(llm)
    reloaded = await llm_service.get_llm(llm_id)
    assert reloaded is not None
    assert set(reloaded.service_capabilities) == {"chat", "vision"}
    assert reloaded.input_text and reloaded.input_image and reloaded.output_text
    updated = await llm_service.update_llm(llm_id, LLMUpdate(label="Renamed model"))
    assert updated is not None
    assert set(updated.service_capabilities) == {"chat", "vision"}
    assert updated.input_text and updated.input_image and updated.output_text
    for capability in ("chat", "vision"):
        assert llm_id in [item.id for item in await llm_service.list_llms(capability=capability)]

    profile = await profile_service.create_profile("Multimodal tracking")
    await profile_service.update_profile(
        profile.id, values={model_usages.TEXT_STANDARD: str(llm_id)},
    )
    await profile_service.use_profile(profile.id)

    tracking_llm = await goal_service.get_tracking_llm()
    assert tracking_llm is not None
    assert tracking_llm.id == llm_id
    assert (await goal_service.list_page()).tracking_llm_configured is True


async def test_empty_table_seeds_a_default_profile(db: AsyncSession) -> None:
    await _clear_profiles(db)

    profile_id = await profile_service.ensure_default_profile_id()
    again = await profile_service.ensure_default_profile_id()

    assert profile_id == again
    profiles = await profile_service.list_profiles()
    assert [profile.label for profile in profiles] == ["Défaut"]


async def test_default_seed_reuses_the_existing_default_profile(
    db: AsyncSession,
) -> None:
    await _clear_profiles(db)

    seeded_id = await profile_service.ensure_default_profile_id()
    assert await profile_service.ensure_default_profile_id() == seeded_id

    created = await profile_service.create_profile("After seed")
    assert created.id != seeded_id


async def test_create_profile_starts_with_empty_columns(db: AsyncSession) -> None:
    """A fresh profile has no model selected on any usage column."""
    profile = await profile_service.create_profile("Serializable")

    assert profile.id > 0
    for model_field in model_usages.ALL:
        assert await profile_service.get_profile_value(profile.id, model_field) is None
    for reasoning_field in model_usages.TEXT_REASONING_FIELDS:
        assert await profile_service.get_profile_value(profile.id, reasoning_field) is None


async def test_text_tiers_store_independent_reasoning_efforts(db: AsyncSession) -> None:
    first, _ = await _seed_llms(db)
    profile = await profile_service.create_profile("Local reasoning")
    await profile_service.update_profile(
        profile.id,
        values={
            model_usages.TEXT_ULTRA_LOW: str(first.id),
            model_usages.TEXT_HIGH: str(first.id),
            model_usages.TEXT_ULTRA_LOW_REASONING: "max",
            model_usages.TEXT_HIGH_REASONING: "minimal",
        },
    )

    assert await profile_service.get_profile_reasoning_effort(
        profile.id, model_usages.TEXT_ULTRA_LOW
    ) == "max"
    assert await profile_service.get_profile_reasoning_effort(
        profile.id, model_usages.TEXT_HIGH
    ) == "low"
    assert await profile_service.get_profile_value(
        profile.id, model_usages.TEXT_HIGH_REASONING
    ) == "low"

    await profile_service.update_profile(
        profile.id,
        values={model_usages.TEXT_HIGH_REASONING: None},
    )
    assert await profile_service.get_profile_reasoning_effort(
        profile.id, model_usages.TEXT_HIGH
    ) is None


async def test_profile_rejects_unknown_reasoning_effort(db: AsyncSession) -> None:
    profile = await profile_service.create_profile("Strict reasoning")

    with pytest.raises(ValueError):
        await profile_service.update_profile(
            profile.id,
            values={model_usages.TEXT_STANDARD_REASONING: "maximum"},
        )


async def test_create_rename_and_column_write(db: AsyncSession) -> None:
    first, second = await _seed_llms(db)

    profile = await profile_service.create_profile("Dev")
    assert profile.id > 0

    renamed = await profile_service.update_profile(profile.id, label="Prod")
    assert renamed is not None
    assert renamed.label == "Prod"

    updated = await profile_service.update_profile(
        profile.id,
        values={model_usages.EXECUTOR: str(first.id)},
    )
    assert updated is not None
    assert (
        await profile_service.get_profile_value(profile.id, model_usages.EXECUTOR)
        == str(first.id)
    )
    stored = await profile_service.get_profile(profile.id)
    assert stored is not None
    assert stored.text_standard_llm_id == first.id

    # A second write replaces the column; None clears it in this profile.
    await profile_service.update_profile(
        profile.id,
        values={model_usages.EXECUTOR: str(second.id)},
    )
    assert (
        await profile_service.get_profile_value(profile.id, model_usages.EXECUTOR)
        == str(second.id)
    )

    await profile_service.update_profile(
        profile.id,
        values={model_usages.EXECUTOR: None},
    )
    assert (
        await profile_service.get_profile_value(profile.id, model_usages.EXECUTOR)
        is None
    )
    cleared = await profile_service.get_profile(profile.id)
    assert cleared is not None
    assert cleared.text_standard_llm_id is None

    assert await profile_service.update_profile(9999, label="Ghost") is None


async def test_update_validates_parameter_names_and_model_ids(
    db: AsyncSession,
) -> None:
    profile = await profile_service.create_profile("Strict")

    with pytest.raises(ValueError):
        await profile_service.update_profile(
            profile.id,
            values={"unknown_llm_id": "1"},
        )

    with pytest.raises(ValueError):
        await profile_service.update_profile(
            profile.id,
            values={model_usages.EXECUTOR: "99999"},
        )


async def test_duplicate_label_is_rejected(db: AsyncSession) -> None:
    await profile_service.create_profile("Dupe")

    with pytest.raises(ValueError):
        await profile_service.create_profile("Dupe")

    # Labels are normalized, so a whitespace variant is the same duplicate.
    with pytest.raises(ValueError):
        await profile_service.create_profile("  Dupe  ")


async def test_last_profile_cannot_be_deleted(db: AsyncSession) -> None:
    await _clear_profiles(db)
    profile_id = await profile_service.ensure_default_profile_id()

    with pytest.raises(profile_service.LastProfileDeletionError):
        await profile_service.delete_profile(profile_id)

    assert len(await profile_service.list_profiles()) == 1


async def test_deleting_a_profile_makes_its_agents_follow_current(db: AsyncSession) -> None:
    await profile_service.ensure_default_profile_id()
    doomed = await profile_service.create_profile("Doomed")

    title = Title(label="Test", gender="N")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Profile",
        last_name="Agent",
        code="profile-agent",
        profile_id=doomed.id,
    )
    db.add(agent)
    await db.commit()

    assert await profile_service.delete_profile(doomed.id) is True
    assert await profile_service.get_profile(doomed.id) is None

    await db.refresh(agent)
    assert agent.profile_id is None


async def test_current_profile_value_reads_the_active_profile(
    db: AsyncSession,
) -> None:
    first, second = await _seed_llms(db)
    profile = await profile_service.create_profile("Active")
    await profile_service.update_profile(
        profile.id,
        values={model_usages.EXECUTOR: str(first.id)},
    )
    await profile_service.set_current_profile_id(profile.id)

    assert (
        await profile_service.get_current_profile_value(model_usages.EXECUTOR)
        == str(first.id)
    )
    assert (
        await profile_service.has_current_profile_value(model_usages.EXECUTOR)
        is True
    )
    assert (
        await profile_service.get_current_profile_value(model_usages.DISPATCHER)
        is None
    )
    assert (
        await profile_service.has_current_profile_value(model_usages.DISPATCHER)
        is False
    )

    # Switching profiles switches the read-through.
    other = await profile_service.create_profile("Other")
    await profile_service.update_profile(
        other.id,
        values={model_usages.EXECUTOR: str(second.id)},
    )
    await profile_service.set_current_profile_id(other.id)
    assert (
        await profile_service.get_current_profile_value(model_usages.EXECUTOR)
        == str(second.id)
    )


async def test_profile_llm_resolution_uses_exactly_one_profile(
    db: AsyncSession,
) -> None:
    first, second = await _seed_llms(db)
    profiled = await profile_service.create_profile("Agent profile")
    await profile_service.update_profile(
        profiled.id,
        values={model_usages.EXECUTOR: str(first.id)},
    )
    agent = SimpleNamespace(profile_id=profiled.id)

    active = await profile_service.create_profile("Current")
    await profile_service.update_profile(
        active.id,
        values={
            model_usages.EXECUTOR: str(second.id),
            model_usages.DISPATCHER: str(second.id),
        },
    )
    await profile_service.set_current_profile_id(active.id)

    # The agent's own profile wins over the current profile.
    resolved = await llm_service.get_profile_llm(
        model_usages.EXECUTOR, agent=agent
    )
    assert resolved is not None
    assert resolved.id == first.id

    # A profile-less agent falls back on the current profile.
    fallback = await llm_service.get_profile_llm(
        model_usages.EXECUTOR, agent=SimpleNamespace()
    )
    assert fallback is not None
    assert fallback.id == second.id

    # An empty usage in a custom profile never borrows from the configured
    # current profile.
    assert (
        await llm_service.get_profile_llm(model_usages.DISPATCHER, agent=agent)
        is None
    )

    # No agent: the current profile answers alone.
    current_dispatcher = await llm_service.get_profile_llm(model_usages.DISPATCHER)
    assert current_dispatcher is not None
    assert current_dispatcher.id == second.id
    direct = await llm_service.get_profile_llm(model_usages.EXECUTOR)
    assert direct is not None
    assert direct.id == second.id


async def test_ensure_default_profile_seeds_the_current_profile_param(
    db: AsyncSession,
) -> None:
    await _clear_profiles(db)
    # The migrated baseline may point the parameter at a profile being
    # cleared; unset it so the seed below has room to act.
    await params_service.set(Params.LLM_PROFILE_ID, None)

    profile = await profile_service.ensure_default_profile()

    assert await profile_service.get_current_profile_id() == profile.id
    assert (
        await params_service.get(Params.LLM_PROFILE_ID)
        == str(profile.id)
    )

    # Idempotent: a second run keeps the seeded profile.
    await profile_service.ensure_default_profile()
    assert await profile_service.get_current_profile_id() == profile.id


async def test_ensure_default_profile_repairs_a_dangling_pointer(
    db: AsyncSession,
) -> None:
    await _clear_profiles(db)
    await params_service.set(Params.LLM_PROFILE_ID, "999999")

    profile = await profile_service.ensure_default_profile()

    assert await profile_service.get_current_profile_id() == profile.id


async def test_seed_tolerates_a_missing_param_row(db: AsyncSession) -> None:
    profile_id = await profile_service.ensure_default_profile_id()

    await db.execute(
        delete(Param).where(Param.name == Params.LLM_PROFILE_ID)
    )
    await db.commit()
    await params_service.refresh()

    # Defensive path (sync() not run yet): no exception, no silent success.
    assert await profile_service.seed_current_profile_id(profile_id) is False

    # Once sync() re-declares the row, the seed succeeds.
    await params_service.sync()
    await params_service.refresh()
    assert await profile_service.seed_current_profile_id(profile_id) is True
    assert await profile_service.get_current_profile_id() == profile_id


async def test_use_profile_only_moves_the_pointer(db: AsyncSession) -> None:
    first, _ = await _seed_llms(db)
    profile = await profile_service.create_profile("Use me")
    await profile_service.update_profile(
        profile.id,
        values={model_usages.EXECUTOR: str(first.id)},
    )

    assert await profile_service.use_profile(profile.id) == profile.id
    assert await profile_service.get_current_profile_id() == profile.id

    # Idempotent and side-effect free: the columns are the values, so using
    # the profile again rewrites nothing.
    assert await profile_service.use_profile(profile.id) == profile.id
    assert (
        await profile_service.get_profile_value(profile.id, model_usages.EXECUTOR)
        == str(first.id)
    )

    with pytest.raises(ValueError):
        await profile_service.use_profile(9999)


async def test_deleting_the_current_profile_resets_the_param(
    db: AsyncSession,
) -> None:
    default_id = await profile_service.ensure_default_profile_id()
    current = await profile_service.create_profile("Current")
    await profile_service.set_current_profile_id(current.id)

    assert await profile_service.delete_profile(current.id) is True
    assert await profile_service.get_current_profile_id() == default_id


async def test_deleting_another_profile_keeps_the_current_param(
    db: AsyncSession,
) -> None:
    await profile_service.ensure_default_profile_id()
    current = await profile_service.create_profile("Current")
    doomed = await profile_service.create_profile("Doomed")
    await profile_service.set_current_profile_id(current.id)

    assert await profile_service.delete_profile(doomed.id) is True
    assert await profile_service.get_current_profile_id() == current.id
