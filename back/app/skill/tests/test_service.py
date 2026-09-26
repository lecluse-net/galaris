from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.harnesses.models import AgentHarness
from app.skill import skill_service, storage
from app.skill.models import AgentSkill, AgentSkillCategory, Skill, SkillCategory
from app.skill.schemas import (
    SkillCategoryCreate,
    SkillCategoryUpdate,
    SkillCreate,
    SkillUpdate,
)


def write_skill(root: Path, code: str) -> None:
    directory = root / code
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {code}\ndescription: Procedures for {code}.\n---\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_disk_reconciliation_creates_and_restores_database_index(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    monkeypatch.setattr(storage, "SYSTEM_SKILLS", ())
    write_skill(root, "manual-skill")

    first = await skill_service.sync_from_disk()
    record = await skill_service.get_by_code("manual-skill")

    assert first == {"created": 1, "restored": 0, "invalid_directories": []}
    assert record is not None
    record.soft_delete()
    await db.commit()

    second = await skill_service.sync_from_disk()

    assert second == {"created": 0, "restored": 1, "invalid_directories": []}
    assert await skill_service.get_by_code("manual-skill") is not None


@pytest.mark.asyncio
async def test_bundled_galaris_skills_receive_default_category_without_reclassifying_custom_skills(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    write_skill(root, "galaris-custom")
    await skill_service.sync_from_disk()
    codes = ("galaris", "galaris-lab", "galaris-knowledge")
    skills = list((await db.scalars(select(Skill).where(Skill.code.in_(codes)))).all())
    category = await db.scalar(select(SkillCategory).where(SkillCategory.label == "Galaris"))
    assert category is not None
    assert len(skills) == 3
    assert {skill.category_id for skill in skills} == {category.id}
    imported = await skill_service.get_by_code("galaris-custom")
    assert imported is not None and imported.category_id is None

    custom_category = await skill_service.create_category(SkillCategoryCreate(label="Internal guides"))
    for skill in skills:
        skill.category_id = custom_category.id if skill.code == "galaris-knowledge" else None
    enabled_before = {skill.code: skill.global_enabled for skill in skills}
    await db.commit()

    # Existing uncategorized skills are filled in; an administrator's choice survives rescans.
    for _ in range(2):
        result = await skill_service.sync_from_disk()
        assert result == {"created": 0, "restored": 0, "invalid_directories": []}
        for skill in skills:
            await db.refresh(skill)
            expected_category = custom_category.id if skill.code == "galaris-knowledge" else category.id
            assert skill.category_id == expected_category
            assert skill.global_enabled is enabled_before[skill.code]
        categories = await db.scalars(select(SkillCategory).where(SkillCategory.label == "Galaris"))
        assert len(categories.all()) == 1


@pytest.mark.asyncio
async def test_authorization_cascade_resolves_global_and_agent_overrides(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    monkeypatch.setattr(storage, "SYSTEM_SKILLS", ())
    write_skill(root, "cascade-skill")
    await skill_service.sync_from_disk()
    skill = await skill_service.get_by_code("cascade-skill")
    assert skill is not None

    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    first = Agent(
        title_id=title.id,
        code="cascade-one",
        first_name="Cascade",
        last_name="One",
        agent_driver="hermes",
    )
    second = Agent(
        title_id=title.id,
        code="cascade-two",
        first_name="Cascade",
        last_name="Two",
        agent_driver="hermes",
    )
    internal = Agent(
        title_id=title.id,
        code="cascade-internal",
        first_name="Cascade",
        last_name="Internal",
        agent_driver="internal",
    )
    db.add_all([first, second, internal])
    await db.flush()
    db.add_all([AgentHarness(agent_id=agent.id, provider_code="hermes") for agent in (first, second)])
    await db.commit()

    initial = (await skill_service.list_authorizations(first.id))[0]
    matrix = await skill_service.list_authorizations()
    filtered = await skill_service.list_authorizations(skill_id=skill.id)
    combined = await skill_service.list_authorizations(first.id, skill.id)
    assert {
        (row.skill_id, row.agent_id)
        for row in matrix
        if row.skill_id == skill.id
    } == {
        (skill.id, first.id),
        (skill.id, second.id),
        (skill.id, internal.id),
    }
    assert {(row.skill_id, row.agent_id) for row in filtered} == {
        (skill.id, first.id),
        (skill.id, second.id),
        (skill.id, internal.id),
    }
    assert [(row.skill_id, row.agent_id) for row in combined] == [
        (skill.id, first.id),
    ]
    assert initial.agent_label == "Cascade One"
    assert initial.agent_driver == "hermes"
    assert initial.global_state == "disabled"
    assert initial.agent_state == "default"
    assert initial.effective is False

    global_enabled, affected = await skill_service.set_global_authorization(
        skill.id, first.id, "enabled"
    )
    assert global_enabled.effective is True
    assert affected == sorted([first.id, second.id])
    assert "cascade-skill" in await skill_service.get_assigned_codes(first.id)
    assert "cascade-skill" in await skill_service.get_assigned_codes(second.id)
    assert "cascade-skill" in await skill_service.get_assigned_codes(internal.id)

    internal_disabled = await skill_service.set_agent_authorization(
        skill.id, internal.id, "disabled"
    )
    assert internal_disabled.agent_driver == "internal"
    assert internal_disabled.effective is False
    assert "cascade-skill" not in await skill_service.get_assigned_codes(internal.id)

    first_disabled = await skill_service.set_agent_authorization(
        skill.id, first.id, "disabled"
    )
    assert first_disabled.agent_state == "disabled"
    assert first_disabled.effective is False
    assert "cascade-skill" not in await skill_service.get_assigned_codes(first.id)

    global_disabled, affected = await skill_service.set_global_authorization(
        skill.id, first.id, "disabled"
    )
    assert global_disabled.effective is False
    assert affected == [second.id]

    first_enabled = await skill_service.set_agent_authorization(
        skill.id, first.id, "enabled"
    )
    assert first_enabled.effective is True
    assert "cascade-skill" in await skill_service.get_assigned_codes(first.id)

    inherited = await skill_service.set_agent_authorization(
        skill.id, first.id, "default"
    )
    assert inherited.agent_state == "default"
    assert inherited.effective is False
    assert "cascade-skill" not in await skill_service.get_assigned_codes(first.id)

    persisted_default = await db.scalar(
        select(AgentSkill).where(
            AgentSkill.agent_id == first.id,
            AgentSkill.skill_id == skill.id,
        )
    )
    assert persisted_default is not None
    assert persisted_default.active is None

    deleted, _ = await skill_service.delete_skill(skill.id)
    assert deleted is True
    remaining_after_soft_delete = await db.scalar(
        select(AgentSkill).where(AgentSkill.skill_id == skill.id).limit(1)
    )
    assert remaining_after_soft_delete is None


@pytest.mark.asyncio
async def test_category_authorization_is_scoped_by_agent(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    monkeypatch.setattr(storage, "SYSTEM_SKILLS", ())
    write_skill(root, "category-skill")
    await skill_service.sync_from_disk()
    skill = await skill_service.get_by_code("category-skill")
    assert skill is not None

    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code="category-agent",
        first_name="Category",
        last_name="Agent",
        agent_driver="hermes",
    )
    other_agent = Agent(
        title_id=title.id,
        code="category-other-agent",
        first_name="Category",
        last_name="Other",
        agent_driver="hermes",
    )
    db.add_all([agent, other_agent])
    await db.flush()
    db.add_all([AgentHarness(agent_id=item.id, provider_code="hermes") for item in (agent, other_agent)])
    await db.commit()

    category = await skill_service.create_category(
        SkillCategoryCreate(label="Research")
    )
    assigned, affected = await skill_service.set_skill_category(skill.id, category.id)
    assert assigned.category_id == category.id
    assert affected == []
    public = skill_service.to_public(assigned)
    assert public.category_id == category.id
    assert public.category_label == "Research"

    inherited = (await skill_service.list_authorizations(agent.id, skill.id))[0]
    assert inherited.category_id == category.id
    assert inherited.category_label == "Research"
    assert inherited.global_state == "disabled"
    assert inherited.category_state == "default"
    assert inherited.agent_state == "default"
    assert inherited.effective is False

    enabled_category, affected = await skill_service.set_category_authorization(
        category.id,
        agent.id,
        "enabled",
    )
    assert enabled_category == "enabled"
    assert affected == [agent.id]
    enabled = (await skill_service.list_authorizations(agent.id, skill.id))[0]
    other = (await skill_service.list_authorizations(other_agent.id, skill.id))[0]
    assert enabled.category_state == "enabled"
    assert enabled.effective is True
    assert other.category_state == "default"
    assert other.effective is False
    assert "category-skill" in await skill_service.get_assigned_codes(agent.id)
    assert "category-skill" not in await skill_service.get_assigned_codes(other_agent.id)

    persisted_category = await db.scalar(
        select(AgentSkillCategory).where(
            AgentSkillCategory.agent_id == agent.id,
            AgentSkillCategory.category_id == category.id,
        )
    )
    assert persisted_category is not None
    assert persisted_category.active is True

    global_disabled, affected = await skill_service.set_global_authorization(
        skill.id,
        agent.id,
        "disabled",
    )
    assert global_disabled.effective is True
    assert affected == []

    agent_disabled = await skill_service.set_agent_authorization(
        skill.id,
        agent.id,
        "disabled",
    )
    assert agent_disabled.effective is False
    assert "category-skill" not in await skill_service.get_assigned_codes(agent.id)

    await skill_service.set_global_authorization(skill.id, agent.id, "enabled")
    default_category, affected = await skill_service.set_category_authorization(
        category.id,
        agent.id,
        "default",
    )
    assert default_category == "default"
    assert affected == []
    still_overridden = (await skill_service.list_authorizations(agent.id, skill.id))[0]
    assert still_overridden.global_state == "enabled"
    assert still_overridden.category_state == "default"
    assert still_overridden.agent_state == "disabled"
    assert still_overridden.effective is False

    agent_default = await skill_service.set_agent_authorization(
        skill.id,
        agent.id,
        "default",
    )
    assert agent_default.effective is True
    assert "category-skill" in await skill_service.get_assigned_codes(agent.id)

    filtered = await skill_service.list_authorizations(category_id=category.id)
    assert {(item.skill_id, item.agent_id) for item in filtered} == {
        (skill.id, agent.id),
        (skill.id, other_agent.id),
    }

    updated = await skill_service.update_category(
        category.id,
        SkillCategoryUpdate(label="Web research"),
    )
    assert updated.label == "Web research"
    with pytest.raises(FileExistsError):
        await skill_service.create_category(SkillCategoryCreate(label="web RESEARCH"))

    skill_ids, affected = await skill_service.delete_category(category.id)
    assert skill_ids == [skill.id]
    assert affected == []
    uncategorized = await skill_service.get(skill.id)
    assert uncategorized is not None
    assert uncategorized.category_id is None
    assert await skill_service.get_category(category.id) is None
    assert "category-skill" in await skill_service.get_assigned_codes(agent.id)
    removed_category_setting = await db.scalar(
        select(AgentSkillCategory).where(
            AgentSkillCategory.category_id == category.id,
        )
    )
    assert removed_category_setting is None


@pytest.mark.asyncio
async def test_new_skill_materializes_agent_settings_and_hard_delete_cascades(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    monkeypatch.setattr(storage, "SYSTEM_SKILLS", ())

    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    agents = [
        Agent(
            title_id=title.id,
            code=f"matrix-{index}",
            first_name="Matrix",
            last_name=str(index),
            agent_driver="internal" if index == 0 else "hermes",
        )
        for index in range(2)
    ]
    db.add_all(agents)
    await db.commit()

    skill = await skill_service.create(
        SkillCreate(code="matrix-skill", label="Matrix skill")
    )
    second_skill = await skill_service.create(
        SkillCreate(code="matrix-skill-two", label="Matrix skill two")
    )

    assignments = list(
        (
            await db.execute(
                select(AgentSkill)
                .where(AgentSkill.skill_id.in_([skill.id, second_skill.id]))
                .order_by(AgentSkill.skill_id, AgentSkill.agent_id)
            )
        )
        .scalars()
        .all()
    )
    assert {
        (assignment.agent_id, assignment.skill_id) for assignment in assignments
    } == {
        (agent.id, current_skill.id)
        for agent in agents
        for current_skill in (skill, second_skill)
    }
    assert len(assignments) == len(agents) * 2
    assert all(assignment.active is None for assignment in assignments)

    await db.delete(skill)
    await db.commit()

    remaining = await db.scalar(
        select(AgentSkill).where(AgentSkill.skill_id == skill.id).limit(1)
    )
    assert remaining is None


@pytest.mark.asyncio
async def test_galaris_system_skill_is_referenced_enabled_and_protected(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))

    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code="system-skill-agent",
        first_name="System",
        last_name="Agent",
        agent_driver="hermes",
    )
    db.add(agent)
    await db.commit()

    existing_before = await skill_service.get_by_code("galaris")
    result = await skill_service.sync_from_disk()
    skill = await skill_service.get_by_code("galaris")

    assert result["created"] == int(existing_before is None)
    assert result["invalid_directories"] == []
    assert skill is not None
    assert skill.system is True
    assert skill.global_enabled is True
    assert not (root / "galaris").exists()
    public = skill_service.to_public(skill)
    assert public.available is True
    assert public.valid is True
    assert public.system is True
    assert await skill_service.get_assigned_codes(agent.id) == ["galaris"]

    assignment = await db.scalar(
        select(AgentSkill).where(
            AgentSkill.agent_id == agent.id,
            AgentSkill.skill_id == skill.id,
        )
    )
    assert assignment is not None
    assert assignment.active is None

    await skill_service.set_global_authorization(skill.id, agent.id, "disabled")
    assert await skill_service.get_assigned_codes(agent.id) == []

    with pytest.raises(ValueError, match="système"):
        await skill_service.update(skill.id, SkillUpdate(label="Override"))
    with pytest.raises(ValueError, match="système"):
        await skill_service.delete_skill(skill.id)
