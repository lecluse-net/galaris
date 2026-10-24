"""Privatization revokes library access and preserves data through failures."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from core.user import UserModel
from app.skill import dbadmin, interface, skill_service, storage
from app.skill.contracts import SkillRevisionConflict
from app.skill.models import AgentSkill, Skill, SkillCategory, AgentSkillCategory
from .test_personal_packages import agents, personal


async def human(db):
    user = UserModel(email="synthetic-skill-owner@example.com", hashed_password="synthetic", is_active=True)
    db.add(user)
    await db.commit()
    return user.id


@pytest.mark.asyncio
async def test_private_transfer_crash_restores_the_source_owner_without_exposing_files(db, agents):
    a, b, _ = agents
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    storage.prepare_ownership_release(str(uuid4()), package.id, b.id, package.code, "moved-guide",
                                      direction="assign", source_owner=a.id)
    assert not storage.skill_dir(package.code, owner_agent_id=a.id).exists()
    await dbadmin._recover_releases(db)
    assert storage.read_file(package.code, "SKILL.md", owner_agent_id=a.id).content
    assert not storage.skill_dir("moved-guide", owner_agent_id=b.id).exists()
    assert not storage.skill_dir(package.code).exists()
    assert (await interface.personal_packages(a.id))[0].id == package.id
    assert not await interface.personal_packages(b.id)


@pytest.mark.asyncio
async def test_assignment_revokes_all_grants_preserves_content_and_replays_without_reactivation(db, agents):
    a, b, admin = agents
    actor = await human(db)
    package = await interface.create_package(personal(), actor_agent_id=admin.id, generic=True)
    await storage.write_file(package.code, "scripts/helper.py", b"print('synthetic')\n", overwrite=False)
    category = SkillCategory(label="Synthetic shared category")
    db.add(category)
    await db.flush()
    db.add(AgentSkillCategory(category_id=category.id, agent_id=b.id, active=True))
    await db.commit()
    await skill_service.set_skill_category(package.id, category.id)
    await skill_service.set_global_authorization(package.id, a.id, "enabled")
    await skill_service.set_agent_authorization(package.id, b.id, "enabled")
    assert package.code in await skill_service.get_assigned_codes(b.id)
    operation = uuid4()
    result = await interface.assign_ownership(package.id, owner_agent_id=a.id, actor_user_id=actor,
        expected_revision=1, operation_id=operation)
    assert result["uri"] == f"galaris://skill/personnal/{a.id}/{package.code}/"
    assert not result["cleanup_pending"]
    record = await db.get(Skill, package.id)
    assert record.owner_agent_id == a.id and record.creator_agent_id == admin.id and record.revision == 2
    assert not record.global_enabled and record.category_id is None
    assert [(row.agent_id, row.active) for row in (await db.scalars(select(AgentSkill).where(AgentSkill.skill_id == package.id))).all()] == [(a.id, True)]
    assert await db.scalar(select(AgentSkillCategory.id).where(AgentSkillCategory.category_id == category.id))
    assert await skill_service.get(package.id) is None
    assert package.code not in await skill_service.get_assigned_codes(b.id)
    assert (await interface.personal_packages(a.id))[0].id == package.id
    assert storage.read_file(package.code, "scripts/helper.py", owner_agent_id=a.id).content == b"print('synthetic')\n"
    with pytest.raises(FileNotFoundError):
        await interface.read_package_file(package.id, "SKILL.md", actor_agent_id=b.id)
    with pytest.raises(KeyError):
        await skill_service.set_agent_authorization(package.id, b.id, "enabled")
    await interface.set_package_enabled(package.id, False, actor_agent_id=a.id, expected_revision=2)
    replay = await interface.assign_ownership(package.id, owner_agent_id=a.id, actor_user_id=actor,
        expected_revision=1, operation_id=operation)
    assert replay == result
    assert not await interface.personal_packages(a.id)
    await interface.release_ownership(package.id, actor_agent_id=admin.id, expected_revision=3, operation_id=uuid4())
    await interface.assign_ownership(package.id, owner_agent_id=a.id, actor_user_id=actor,
        expected_revision=1, operation_id=operation)
    assert (await skill_service.get(package.id)).owner_agent_id is None
    assert all(row.active is None for row in (await db.scalars(select(AgentSkill).where(AgentSkill.skill_id == package.id))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["publish", "commit", "cleanup", "crash"])
async def test_assignment_failure_recovery_preserves_originals_and_authorizations(db, agents, monkeypatch, stage):
    a, b, admin = agents
    owner_id, other_id, admin_id = a.id, b.id, admin.id
    actor = await human(db)
    package = await interface.create_package(personal(), actor_agent_id=admin.id, generic=True)
    await skill_service.set_agent_authorization(package.id, b.id, "enabled")
    operation = uuid4()
    prepare, recover = storage.prepare_ownership_release, storage.recover_ownership_release

    def fail_publish(*args, **kwargs):
        prepare(*args, **kwargs)
        raise RuntimeError("Synthetic publish failure")

    async def fail_commit():
        raise RuntimeError("Synthetic commit failure")

    def fail_cleanup(operation_id, *, committed, deleted=False):
        if committed:
            raise OSError("Synthetic cleanup failure")
        recover(operation_id, committed=committed, deleted=deleted)

    if stage == "crash":
        prepare(str(operation), package.id, a.id, package.code, package.code, direction="assign")
        assert not dbadmin.compile_skill_rows()[1]
    else:
        with monkeypatch.context() as patch:
            if stage == "publish":
                patch.setattr(storage, "prepare_ownership_release", fail_publish)
            elif stage == "commit":
                patch.setattr(db, "commit", fail_commit)
            else:
                patch.setattr(storage, "recover_ownership_release", fail_cleanup)
            if stage == "cleanup":
                result = await interface.assign_ownership(package.id, owner_agent_id=a.id, actor_user_id=actor,
                    expected_revision=1, operation_id=operation)
                assert result["cleanup_pending"]
            else:
                with pytest.raises(RuntimeError, match="Synthetic"):
                    await interface.assign_ownership(package.id, owner_agent_id=a.id, actor_user_id=actor,
                        expected_revision=1, operation_id=operation)
    await dbadmin._recover_releases(db)
    record = await db.get(Skill, package.id)
    if stage == "cleanup":
        assert record.owner_agent_id == owner_id and record.revision == 2
        assert storage.read_file(package.code, "SKILL.md", owner_agent_id=owner_id).content
        # Reversing after pending cleanup cannot strand the old transition.
        await interface.release_ownership(package.id, actor_agent_id=admin_id, expected_revision=2, operation_id=uuid4())
    else:
        assert record.owner_agent_id is None and record.revision == 1
        assert storage.read_file(package.code, "SKILL.md").content
        assert package.code in await skill_service.get_assigned_codes(other_id)
        assert not storage.skill_dir(package.code, owner_agent_id=owner_id).exists()
    assert not storage.pending_ownership_releases()


@pytest.mark.asyncio
async def test_assignment_rejects_stale_revisions_homonyms_system_and_owner_quota(db, agents, monkeypatch):
    a, _, admin = agents
    actor = await human(db)
    package = await interface.create_package(personal(), actor_agent_id=admin.id, generic=True)
    await interface.create_package(personal(), actor_agent_id=a.id)
    async def assign(**kwargs):
        return await interface.assign_ownership(package.id, owner_agent_id=a.id, actor_user_id=actor,
            operation_id=uuid4(), **kwargs)
    with pytest.raises(SkillRevisionConflict):
        await assign(expected_revision=2)
    with pytest.raises(FileExistsError):
        await assign(expected_revision=1)
    monkeypatch.setattr(interface, "MAX_PERSONAL_PACKAGES", 1)
    with pytest.raises(ValueError, match="budget"):
        await assign(expected_revision=1, new_code="renamed-private")
    monkeypatch.setattr(interface, "MAX_PERSONAL_PACKAGES", 100)
    monkeypatch.setattr(interface, "MAX_PERSONAL_TOTAL_SIZE", 1)
    with pytest.raises(ValueError, match="budget"):
        await assign(expected_revision=1, new_code="renamed-private")
    monkeypatch.setattr(interface, "MAX_PERSONAL_TOTAL_SIZE", 200 * 1024 * 1024)
    exact_budget = storage.inspect(package.code).total_size + storage.inspect(package.code, owner_agent_id=a.id).total_size
    monkeypatch.setattr(interface, "MAX_PERSONAL_TOTAL_SIZE", exact_budget)
    owner_id = a.id
    with pytest.raises(ValueError, match="budget"):
        await assign(expected_revision=1, new_code="longer-renamed-private")
    await db.refresh(a)
    monkeypatch.setattr(interface, "MAX_PERSONAL_TOTAL_SIZE", 200 * 1024 * 1024)
    assert storage.read_file(package.code, "SKILL.md").content
    assert not storage.skill_dir("longer-renamed-private", owner_agent_id=owner_id).exists()
    record = await db.get(Skill, package.id)
    record.system = True
    await db.commit()
    with pytest.raises(ValueError):
        await assign(expected_revision=1, new_code="renamed-private")
    record.system = False
    await db.commit()
    await assign(expected_revision=1, new_code="renamed-private")
    assert storage.metadata_from_markdown(storage.read_file("renamed-private", "SKILL.md", owner_agent_id=a.id).content.decode(), expected_code="renamed-private")
