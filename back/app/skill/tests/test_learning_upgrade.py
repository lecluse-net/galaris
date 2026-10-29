"""Synthetic legacy sources survive upgrade failures and become personal packages."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from core.dbadmin import DbAdminRegistry, SchemaTransitionSet
from app.skill import dbadmin, interface, storage, learning_service
from app.skill.learning_contracts import LearnedSkillDecision, LearnedSkillOperation
from app.skill.models import AgentSkill, Skill, SkillLearningEvidence
from .test_personal_packages import agents, personal


async def legacy_tables(db):
    await db.execute(text('''CREATE TABLE learned_skills (
        id uuid PRIMARY KEY, agent_id integer NOT NULL REFERENCES agents(id),
        code varchar(100) NOT NULL, label varchar(255) NOT NULL, markdown text NOT NULL,
        revision integer NOT NULL DEFAULT 2, positive_weight double precision NOT NULL DEFAULT 3,
        negative_weight double precision NOT NULL DEFAULT 0, evidence_count integer NOT NULL DEFAULT 3,
        score double precision NOT NULL DEFAULT 0.8, suspended boolean NOT NULL DEFAULT false,
        last_evidence_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
        created_by integer, updated_at timestamptz, updated_by integer, deleted_at timestamptz, deleted_by integer
    )'''))
    await db.execute(text('''CREATE TABLE learned_skill_evidences (
        id uuid PRIMARY KEY, learned_skill_id uuid NOT NULL REFERENCES learned_skills(id),
        source_ref varchar(300) NOT NULL, source_fingerprint varchar(64) NOT NULL,
        operation varchar(20) NOT NULL, polarity varchar(10) NOT NULL,
        weight double precision NOT NULL, confidence double precision NOT NULL,
        evidence_refs jsonb NOT NULL, rationale text NOT NULL, instruction_digest varchar(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_learned_skill_evidence_source UNIQUE (learned_skill_id, source_fingerprint),
        CONSTRAINT ck_learned_skill_evidence_operation CHECK (operation IN ('CREATE', 'REINFORCE', 'REVISE', 'WEAKEN')),
        CONSTRAINT ck_learned_skill_evidence_polarity CHECK (polarity IN ('positive', 'negative')),
        CONSTRAINT ck_learned_skill_evidence_weight CHECK (weight > 0 AND confidence BETWEEN 0 AND 1)
    )'''))


def action():
    registry = DbAdminRegistry()
    dbadmin.register_dbadmin(registry)
    return next(item for item in registry.actions if item.key == 'app.skill.personal_learning')


@pytest.mark.asyncio
@pytest.mark.parametrize('collision,suspended', [(False, False), (True, True)])
async def test_transfer_preserves_files_provenance_scores_and_disabled_state(db, agents, collision, suspended):
    owner, _, _ = agents
    code = f"learned-{owner.code}-legacy"
    if collision:
        existing = await interface.create_package(personal(code), actor_agent_id=owner.id)
    await legacy_tables(db)
    identity, proof = uuid4(), uuid4()
    markdown = personal(code, body='Legacy verified procedure.').markdown
    await db.execute(text('''INSERT INTO learned_skills(id,agent_id,code,label,markdown,suspended)
        VALUES (:key,:owner,:code,'Legacy procedure',:markdown,:suspended)'''),
        dict(key=identity, owner=owner.id, code=code, markdown=markdown, suspended=suspended))
    await db.execute(text('''INSERT INTO learned_skill_evidences
        (id,learned_skill_id,source_ref,source_fingerprint,operation,polarity,weight,confidence,evidence_refs,rationale,instruction_digest)
        VALUES (:key,:target,:source,:fingerprint,'CREATE','positive',1,0.9,'["tool:0:check"]','Synthetic proof',:digest)'''),
        dict(key=proof, target=identity, source=f'galaris://task/{uuid4()}', fingerprint='a'*64,
             digest=hashlib.sha256(markdown.encode()).hexdigest()))
    migration = action()
    delta = SchemaTransitionSet(removed_tables=frozenset({'learned_skills', 'learned_skill_evidences'}))
    assert migration.predicate(delta) and not migration.predicate(SchemaTransitionSet())
    assert not await migration.postcondition(db, delta)
    await migration.handler(db, delta)
    assert await migration.postcondition(db, delta)
    await migration.handler(db, delta)
    target = await db.scalar(select(Skill).where(Skill.learning_key == identity))
    assert target.owner_agent_id == owner.id and target.learning_score == 0.8
    assert target.learning_evidence_count == 3 and target.revision == 2
    assert (await db.get(SkillLearningEvidence, proof)).skill_id == target.id
    assert 'Legacy verified procedure.' in storage.read_text(target.code, 'SKILL.md', owner_agent_id=owner.id)
    assert await db.scalar(select(AgentSkill.active).where(AgentSkill.skill_id == target.id)) == (not suspended)
    if collision:
        assert target.id != existing.id and target.code != existing.code
        assert storage.read_text(existing.code, 'SKILL.md', owner_agent_id=owner.id) == personal(code).markdown
    # Postcondition checks the actual evidence and bytes, not just a migration marker.
    (storage.skill_dir(target.code, owner_agent_id=owner.id) / 'SKILL.md').write_text(personal(target.code, 'Unexpected edit.').markdown)
    assert not await migration.postcondition(db, delta)
    assert await db.scalar(text('SELECT count(*) FROM learned_skills')) == 1
    # Old checkpointed UUID targets and CREATE codes still address the transferred package,
    # even when its original name belongs to a different personal package.
    for op in (
        LearnedSkillOperation(action='REINFORCE', target_skill_id=identity,
            evidence_refs=['tool:0:check'], rationale='Synthetic late confirmation', confidence=.9),
        LearnedSkillOperation(action='CREATE', code=code, label='Legacy procedure', markdown=markdown,
            evidence_refs=['tool:0:check'], rationale='Synthetic replayed proposal', confidence=.9),
    ):
        await learning_service.apply_learning_decision(agent_id=owner.id,
            source_ref=f'galaris://task/{uuid4()}', source_fingerprint=uuid4().hex * 2,
            allowed_evidence_refs={'tool:0:check'}, evidence_weight=1,
            decision=LearnedSkillDecision(operations=[op]))
    assert target.learning_evidence_count == 5
    if collision:
        assert (await db.get(Skill, existing.id)).learning_last_evidence_at is None


@pytest.mark.asyncio
async def test_failed_file_transfer_keeps_legacy_sources_for_retry(db, agents, monkeypatch):
    owner, _, _ = agents
    await legacy_tables(db)
    await db.execute(text('''INSERT INTO learned_skills(id,agent_id,code,label,markdown)
        VALUES (:key,:owner,'shared-name','Legacy procedure',:markdown)'''),
        dict(key=uuid4(), owner=owner.id, markdown=personal().markdown))
    await db.commit()
    original = storage.install_markdown
    async def fail(*args, **kwargs):
        raise OSError('Synthetic file storage failure')
    delta = SchemaTransitionSet(removed_tables=frozenset({'learned_skills'}))
    monkeypatch.setattr(storage, 'install_markdown', fail)
    with pytest.raises(OSError, match='Synthetic file'):
        async with db.begin_nested():
            await action().handler(db, delta)
    assert await db.scalar(text('SELECT count(*) FROM learned_skills')) == 1
    assert not await action().postcondition(db, delta)
    monkeypatch.setattr(storage, 'install_markdown', original)
    await action().handler(db, delta)
    assert await action().postcondition(db, delta)


@pytest.mark.asyncio
async def test_real_dbadmin_contracts_only_after_personal_files_and_evidence_are_verified(
    committed_database, tmp_path, monkeypatch,
):
    """Exercise the real Atlas executable on a disposable clone, including a failed transfer."""
    from core import settings
    from core.dbadmin import orchestrator, DbAdminVerdict, DbAdminMode
    from core.dbadmin._internal import atlas
    from core.user import UserModel
    from app.agent.models import Agent, Title
    factory = committed_database
    isolated_engine = factory.kw['bind']
    monkeypatch.setattr(orchestrator, 'engine', isolated_engine)
    monkeypatch.setattr(atlas, 'engine', isolated_engine)
    monkeypatch.setattr(settings, 'POSTGRES_DB', isolated_engine.url.database)
    monkeypatch.setattr(orchestrator, '_load_contributions', lambda _registry: None)
    monkeypatch.setattr(type(storage.settings), 'GALARIS_SKILLS_ROOT', str(tmp_path / 'skills'))
    async with factory() as session:
        # Start with the actual historical shape, not a target schema that already
        # contains the destination table. Old and new indexes must coexist during expansion.
        await session.execute(text('DROP TABLE skill_learning_evidences'))
        await session.execute(text('''ALTER TABLE skills
            DROP COLUMN learning_key, DROP COLUMN learning_origin_code,
            DROP COLUMN learning_positive_weight, DROP COLUMN learning_negative_weight,
            DROP COLUMN learning_evidence_count, DROP COLUMN learning_score,
            DROP COLUMN learning_last_evidence_at'''))
        user = UserModel(email='learning-upgrade@example.test', hashed_password='synthetic')
        title = Title(label='Synthetic upgrade', gender='N')
        session.add_all([user, title])
        await session.flush()
        owner = Agent(user_id=user.id, title_id=title.id, code='synthetic-upgrade', first_name='Synthetic', last_name='Upgrade')
        session.add(owner)
        await session.flush()
        await legacy_tables(session)
        identity = uuid4()
        await session.execute(text('''INSERT INTO learned_skills(id,agent_id,code,label,markdown)
            VALUES (:key,:owner,'shared-name','Legacy procedure',:markdown)'''),
            dict(key=identity, owner=owner.id, markdown=personal().markdown))
        await session.commit()
    registry = DbAdminRegistry()
    registry.register_action(action())
    original = storage.install_markdown
    async def fail(*args, **kwargs):
        raise OSError('Synthetic upgrade storage failure')
    monkeypatch.setattr(storage, 'install_markdown', fail)
    failed = await orchestrator.synchronize_database(mode=DbAdminMode.TEST, target_registry=registry)
    assert failed.verdict != DbAdminVerdict.CONVERGED
    async with factory() as session:
        assert await session.scalar(text('SELECT count(*) FROM learned_skills')) == 1
    monkeypatch.setattr(storage, 'install_markdown', original)
    result = await orchestrator.synchronize_database(mode=DbAdminMode.TEST, target_registry=registry)
    assert result.verdict == DbAdminVerdict.CONVERGED
    async with factory() as session:
        assert await session.scalar(text("SELECT to_regclass('public.learned_skills')")) is None
        assert await session.scalar(text("SELECT to_regclass('public.learned_skill_evidences')")) is None
        package = await session.scalar(select(Skill).where(Skill.learning_key == identity))
        assert storage.read_text(package.code, 'SKILL.md', owner_agent_id=package.owner_agent_id) == personal().markdown
