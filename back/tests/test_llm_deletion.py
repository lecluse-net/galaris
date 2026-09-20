import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.llm import llm_provider_service, llm_service
from app.llm.profile_models import LlmProfile
from app.llm.provider_models import LLM, LLMProvider


pytestmark = pytest.mark.asyncio


def _provider(name: str = "Deletion test") -> LLMProvider:
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
        code=f"deletion-{suffix}",
        llm_name=f"test/{suffix}",
        label=f"Deletion {suffix}",
        resource_type="model",
        primary_capability="chat",
        service_capabilities=["chat"],
        pricing={},
    )


async def test_delete_llm_historizes_and_clears_live_references(
    db: AsyncSession,
) -> None:
    provider = _provider()
    db.add(provider)
    await db.flush()
    llm = _llm(provider.id)
    db.add(llm)
    await db.flush()
    survivor = _llm(provider.id, "survivor")
    db.add(survivor)
    await db.flush()

    profile = LlmProfile(
        label="Deletion profile",
        text_standard_llm_id=llm.id,
        text_low_llm_id=llm.id,
        text_high_llm_id=survivor.id,
    )
    db.add(profile)

    title = Title(label="Test", gender="N")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Deletion",
        last_name="Agent",
        code="deletion-agent",
        profile_id=profile.id,
        voice=f"tts:{llm.id}",
    )
    db.add(agent)
    await db.commit()
    assert await llm_service.delete_llm(llm.id) is True
    assert await llm_service.get_llm(llm.id) is None

    archived = await db.scalar(
        select(LLM)
        .execution_options(include_historized=True)
        .where(LLM.id == llm.id)
    )
    assert archived is not None
    assert archived.deleted_at is not None

    await db.refresh(agent)
    assert agent.profile_id == profile.id
    assert agent.voice is None

    # Profile columns pointing at the deleted LLM are cleared; the columns
    # pointing elsewhere survive untouched.
    await db.refresh(profile)
    assert profile.text_standard_llm_id is None
    assert profile.text_low_llm_id is None
    assert profile.text_high_llm_id == survivor.id


async def test_soft_deleted_llm_identifiers_can_be_reused(db: AsyncSession) -> None:
    provider = _provider("Reuse test")
    db.add(provider)
    await db.flush()
    first = _llm(provider.id, "reusable")
    db.add(first)
    await db.commit()

    assert await llm_service.delete_llm(first.id) is True

    replacement = _llm(provider.id, "reusable")
    db.add(replacement)
    await db.commit()

    assert replacement.id != first.id
    assert await llm_service.get_llm(replacement.id) is not None


async def test_delete_provider_historizes_its_llms_and_clears_profiles(
    db: AsyncSession,
) -> None:
    provider = _provider("Provider deletion test")
    db.add(provider)
    await db.flush()
    first = _llm(provider.id, "provider-first")
    second = _llm(provider.id, "provider-second")
    db.add_all([first, second])
    profile = LlmProfile(
        label="Provider deletion profile",
        text_low_llm_id=first.id,
        text_standard_llm_id=second.id,
    )
    db.add(profile)
    await db.commit()

    assert await llm_provider_service.delete_provider(provider.id) is True
    assert await llm_provider_service.get_provider(provider.id) is None
    assert await llm_service.get_llm(first.id) is None
    assert await llm_service.get_llm(second.id) is None
    await db.refresh(profile)
    assert profile.text_low_llm_id is None
    assert profile.text_standard_llm_id is None

    archived_provider = await db.scalar(
        select(LLMProvider)
        .execution_options(include_historized=True)
        .where(LLMProvider.id == provider.id)
    )
    archived_llms = list(
        (
            await db.execute(
                select(LLM)
                .execution_options(include_historized=True)
                .where(LLM.llm_provider_id == provider.id)
            )
        ).scalars().all()
    )
    assert archived_provider is not None
    assert archived_provider.deleted_at is not None
    assert len(archived_llms) == 2
    assert all(llm.deleted_at is not None for llm in archived_llms)
