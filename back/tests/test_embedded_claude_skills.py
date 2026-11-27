"""Qualify progressive skill loading through Deep and the bundled Claude SDK."""

import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.chat.tests.test_deep import room_info, send
from app.conversation import DeepSession, deep
from app.harness import claude_driver
from app.harness.claude_session import ClaudeSession
from app.llm.models import LLMCall
from app.llm.profile_models import LlmProfile
from app.skill import skill_service, storage
from app.skill.models import AgentSkill, Skill
from app.skill.schemas import SkillCreate
from core.util import get_encryption_service
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


@pytest.mark.asyncio
async def test_claude_skills_load_progressively_and_cannot_be_replayed_after_revocation(
    attachment_context, runtime, monkeypatch, tmp_path,
):
    db, model, requests, mode = runtime
    room_id = attachment_context["room_id"]
    agent = await db.get(Agent, attachment_context["agent_id"])
    assert agent is not None
    workspace = tmp_path / "claude"
    workspace.mkdir()
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    mode["concurrent"] = True
    profile = LlmProfile(label="Synthetic skill profile", text_standard_llm_id=model.id)
    db.add(profile)
    await db.flush()
    agent.agent_driver = "claude_embedded"
    agent.profile_id = profile.id
    await db.commit()

    async def add_generic(code, description, instructions, *, assigned):
        data = SkillCreate(code=code, label=description, markdown=(
            f"---\nname: {code}\ndescription: {description}\n---\n\n{instructions}\n"
        ))
        item = await skill_service.create(data)
        await skill_service.set_agent_authorization(item.id, agent.id, "enabled" if assigned else "disabled")
        return item.id

    eager, deferred = "eager-synthetic-guide", "deferred-synthetic-guide"
    eager_marker, refreshed_marker, deferred_marker = "SYNTHETIC_EAGER_BODY", "SYNTHETIC_REFRESHED_EAGER", "SYNTHETIC_DEFERRED_BODY"
    section_marker, other_marker = "SYNTHETIC_EXACT_SECTION", "SYNTHETIC_UNREQUESTED_SECTION"
    await add_generic(eager, "Synthetic eager description", eager_marker, assigned=True)
    (storage.skill_dir(eager) / "runtime.yaml").write_text("loading: eager\n", encoding="utf-8")
    deferred_id = await add_generic(deferred, "Synthetic deferred description", deferred_marker, assigned=True)
    (storage.skill_dir(deferred) / "reference.md").write_text(
        f"# Target section\n{section_marker}\n\n# Adjacent section\n{other_marker}\n", encoding="utf-8",
    )
    await add_generic("hidden-synthetic-guide", "SYNTHETIC_HIDDEN_DESCRIPTION", "SYNTHETIC_HIDDEN_BODY", assigned=False)
    other_owner = attachment_context["other_agent_id"]
    private = Skill(code="private-synthetic-guide", label="Synthetic private skill", owner_agent_id=other_owner)
    db.add(private)
    await db.flush()
    db.add(AgentSkill(agent_id=other_owner, skill_id=private.id, active=True))
    await storage.install_markdown(private.code, private.label, (
        "---\nname: private-synthetic-guide\ndescription: SYNTHETIC_PRIVATE_DESCRIPTION\n---\n\nSYNTHETIC_PRIVATE_BODY\n"
    ), owner_agent_id=other_owner)
    await db.commit()

    gate = asyncio.Event()
    first_text, second_text = "Use the synthetic guide for this Deep turn.", "Continue in the same Deep session."
    read = "mcp__galaris__read_skill_file"
    load = "mcp__galaris__load_capability"

    def choose_tools(body):
        messages = body["messages"]
        if any(message["role"] == "user" and second_text in json.dumps(message) for message in messages):
            return []
        last_user = max(index for index, message in enumerate(messages) if message["role"] == "user")
        count = sum(message["role"] == "tool" for message in messages[last_user + 1:])
        if count == 0:
            return [("skill-unloaded-read", read, {"id": deferred, "path": "reference.md"})]
        if count == 1:
            return [("skill-loaded", load, {"id": deferred})]
        if count == 2:
            return [("skill-section", read, {"id": deferred, "path": "reference.md", "section": "Target section"})]
        if count == 3:
            mode["tool_gate"] = gate
            return [("skill-revoked", read, {"id": deferred, "path": "reference.md", "section": "Adjacent section"})]
        return []

    mode["tool_calls_for"] = choose_tools

    async with _gateway(monkeypatch), asyncio.timeout(65):
        try:
            await send(attachment_context, room_id, f"@deep {first_text}")
            await deep.start_deep()
            while "tool_gate" not in mode:
                await asyncio.sleep(0.025)
            await skill_service.set_agent_authorization(deferred_id, agent.id, "disabled")
            gate.set()

            async def completed(count):
                while True:
                    submissions = (await room_info(attachment_context, room_id))["submissions"]
                    assert not any(item["state"] == "failed" for item in submissions), submissions
                    if len(submissions) == count and all(item["state"] == "completed" for item in submissions):
                        return submissions
                    await asyncio.sleep(0.025)

            [first] = await completed(1)
            session = await db.get(DeepSession, UUID(first["session_id"]))
            assert session is not None and session.native_history is not None
            saved = ClaudeSession.from_deep_history(get_encryption_service().decrypt(session.native_history), session.id)
            assert deferred_marker in saved.transcript and section_marker in saved.transcript

            eager_guide = storage.skill_dir(eager) / "SKILL.md"
            eager_guide.write_text(eager_guide.read_text(encoding="utf-8").replace(eager_marker, refreshed_marker), encoding="utf-8")
            await send(attachment_context, room_id, f"@deep {second_text}")
            first, second = await completed(2)
            assert first["session_id"] == second["session_id"]
        finally:
            gate.set()
            await deep.stop_deep()

    assert len(requests) == 6, [
        (first_text in json.dumps(body), second_text in json.dumps(body),
         sum(message["role"] == "tool" for message in body["messages"])) for body in requests
    ]
    initial, unloaded, loaded, read_section, revoked, continued = map(json.dumps, requests)
    assert eager_marker in initial and "Synthetic deferred description" in initial
    assert deferred_marker not in initial and section_marker not in initial
    assert "Load skill" in unloaded and deferred_marker not in unloaded
    assert deferred_marker in loaded and section_marker not in loaded
    assert section_marker in read_section and other_marker not in read_section
    assert "This Galaris skill is unavailable." in revoked and other_marker not in revoked
    assert first_text in continued and second_text in continued
    assert refreshed_marker in continued and eager_marker not in continued
    assert "Synthetic deferred description" not in continued
    assert deferred_marker not in continued and section_marker not in continued
    assert not any("SYNTHETIC_HIDDEN" in json.dumps(body) or "SYNTHETIC_PRIVATE" in json.dumps(body) for body in requests)
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id)))
    assert len(calls) == len(requests)
    assert {str(call.deep_submission_id) for call in calls} == {first["id"], second["id"]}
    assert all(str(call.deep_session_id) == first["session_id"] for call in calls)
    assert list(workspace.iterdir()) == []
