"""Bootstrap only the disposable db-team database; no production fixture route."""

import asyncio
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from .cases import CASES, mission
from .evidence import write_json

PILOT_EMAIL = "team-pilot@example.com"

def require_isolated_database(environment: str, host: str, database: str) -> None:
    if (environment, host, database) != ("qualification", "db-team", "agent_team_pilot"):
        raise RuntimeError("The team pilot requires its isolated qualification/db-team/agent_team_pilot stack")


def configuration(path: Path, *, execute: bool) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"base_url", "model", "context_length", "timeout_seconds", "max_tokens", "allow_no_api_key",
               "input_usd_per_million", "output_usd_per_million"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("Unknown configuration fields; credentials belong only in the key file")
    url = urlsplit(config["base_url"])
    if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("base_url must be an HTTP(S) endpoint without embedded credentials, query or fragment")
    if execute and (url.hostname.endswith((".invalid", ".test")) or config["model"] == "replace-with-your-model"):
        raise ValueError("Configure a real tool-capable model before execution")
    if not 60 <= config.get("timeout_seconds", 600) <= 3600:
        raise ValueError("timeout_seconds must be between 60 and 3600")
    if not 1 <= config.get("max_tokens", 150000) <= 1000000:
        raise ValueError("max_tokens must be between 1 and 1000000")
    return config


async def seed(directory: Path, case_code: str, mode: str, config: dict, *, execute: bool) -> None:
    from core.settings import settings
    require_isolated_database(settings.APP_ENV, settings.POSTGRES_HOST, settings.POSTGRES_DB)
    # This is the real composition root, never tests.e2e_app or a patched driver.
    import main  # noqa: F401
    from sqlalchemy import select
    from app.agent.models import Agent, Title
    from app.agent import agent_service
    from app.agent.schemas import AgentUpdate
    from app.connection import Connection, facade as connections
    from app.document import resource_service, DocumentItemCreate, DocumentPayload, DocumentSourceCreate
    from app.document.schemas import DocumentGrantUpdate
    from app.llm import LLM, LLMProvider, model_usages, profile_service
    from app.messenger import create_internal_room
    from app.tools.mandatory_tools import INTEGRATED_TOOL_SPECS, SYSTEM_TOOL_CODES, sync_integrated_tool_connections
    from app.tools import mcp_tools_by_tool_code
    from core.authorize.models import Assignment, Role
    from core.database import get_db_session
    from core.params import params_service
    from core.params.consts import Params
    from core.user import UserModel, user_service
    from core.team import TeamModel
    from core.util.encryption import encrypt_value

    case = CASES[case_code]
    password = secrets.token_urlsafe(32)
    api_key = Path("/run/pilot/api-key").read_text().strip() if execute else ""
    if execute and not api_key and not config.get("allow_no_api_key", False):
        raise ValueError("A provider key file is required (or explicit allow_no_api_key for a local endpoint)")
    async with get_db_session() as db:
        # Reusing a prior project could contaminate the qualification.
        if await db.scalar(select(Agent.id).where(Agent.code == "pilot-leader")):
            raise RuntimeError("Pilot already seeded; use a fresh Compose project")
        await params_service.load_params()
        owner = UserModel(email=PILOT_EMAIL, display_name="Pilot synthetic operator", language="fr",
                          hashed_password=user_service.encrypt_password(password), is_active=True)
        title = Title(label="Pilot", gender="M")
        provider = LLMProvider(name="Pilot endpoint", provider_type="openai_compatible",
                              base_url=config["base_url"], api_key=encrypt_value(api_key) if api_key else None,
                              is_active=execute, max_concurrent_calls=4)
        db.add_all([owner, title, provider])
        await db.flush()
        role = await db.scalar(select(Role).where(Role.code == "admin"))
        if role is None:
            raise RuntimeError("DbAdmin did not initialize roles")
        db.add(Assignment(user_id=owner.id, role_id=role.id, is_default=True))
        model = LLM(llm_provider_id=provider.id, code="pilot-model", llm_name=config["model"], label="Pilot model",
                    context_length=config.get("context_length", 128000),
                    cost_per_input_token=config.get("input_usd_per_million"),
                    cost_per_output_token=config.get("output_usd_per_million"))
        db.add(model)
        await db.flush()
        profile = await profile_service.create_profile("Pilot profile")
        profile = await profile_service.update_profile(profile.id, values={
            tier: str(model.id) for tier in model_usages.TEXT_TIERS
        })
        assert profile is not None
        finance_profile = profile
        if case_code == "peer_failure":
            # Fail the external inference boundary, never a fabricated Task result.
            offline = LLMProvider(name="Synthetic unavailable Finance endpoint", provider_type="openai_compatible",
                                  base_url="http://127.0.0.1:9/v1", api_key=encrypt_value("synthetic-offline"),
                                  is_active=execute, max_concurrent_calls=1)
            db.add(offline)
            await db.flush()
            offline_model = LLM(llm_provider_id=offline.id, code="pilot-offline", llm_name=config["model"],
                                label="Synthetic unavailable Finance model", context_length=config.get("context_length", 128000))
            db.add(offline_model)
            await db.flush()
            finance_profile = await profile_service.create_profile("Pilot Finance unavailable")
            finance_profile = await profile_service.update_profile(finance_profile.id, values={
                tier: str(offline_model.id) for tier in model_usages.TEXT_TIERS})
            assert finance_profile is not None
        await params_service.set(Params.LLM_PROFILE_ID, str(profile.id))
        await params_service.set_runtime_values({
            Params.TASK_ROOT_MAX_TOKENS: str(config.get("max_tokens", 150000)),
            Params.TASK_ROOT_MAX_SECONDS: str(config.get("timeout_seconds", 600)),
            Params.TASK_ASK_AGENT_MAX_ROUNDS: "3",
            Params.TASK_PLAN_MAX_LEAVES: "12",
            Params.TASK_SCHEDULER_MAX_CONCURRENCY: "4",
            Params.DREAM_ENABLED: "false",
        })
        await db.commit()
        user_service.set_current_user(owner)
        agents = []
        try:
            team = TeamModel(name="Quartz pilot team")
            db.add(team)
            await db.flush()
            for code, name, job in (
                ("leader", "Pilote", "Coordonne les contributions utiles, vérifie les sources et conserve les incertitudes. Tu assumes le résultat final et la transmission des nouvelles consignes."),
                ("logistics", "Logistique", "Analyse la logistique, les capacités et les dates. Rapporte les sources exactes, les lacunes et les contradictions. Ne prends aucun engagement."),
                ("finance", "Finances", "Analyse les budgets et vérifie les calculs. Distingue montants confirmés et coûts inconnus. Rapporte les sources exactes et ne décide pas à la place de l'humain."),
            ):
                # Fixture bootstrap is not an agent-creation qualification. Avoid
                # provisioning optional SSH consoles; use the ordinary connections.
                agent = Agent(user_id=owner.id, title_id=title.id,
                    profile_id=finance_profile.id if code == "finance" else profile.id,
                    code=f"pilot-{code}", first_name=name, last_name="", job_title=job,
                    job_description=f"<p>{job}</p>", agent_driver="internal")
                db.add(agent)
                await db.flush()
                await sync_integrated_tool_connections(agent.id)
                agents.append(agent)
            for agent in agents:
                updated = await agent_service.update(agent.id, AgentUpdate(team_ids=[team.id]), actor_user_id=owner.id)
                assert updated is not None
            allowed = {"agent_list", "agent_get", "task_get", "task_work_update", "tools_list", "document_show",
                       "file_list", "file_search", "file_read", "file_write", "file_edit", "file_append",
                       "document_share", "document_sharing", "conversation_task_submit",
                       "conversation_task_list", "conversation_task_status"}
            if mode != "solo":
                allowed.update({"task_run", "messenger_send_message_to_user"})
            specs = {spec.code: spec for spec in INTEGRATED_TOOL_SPECS}
            definitions = mcp_tools_by_tool_code()
            from app.tools.models import Tool
            for agent in agents:
                rows = (await db.execute(select(Connection, Tool.code).join(Tool).where(Connection.agent_id == agent.id))).all()
                for connection, tool_code in rows:
                    connection.active = tool_code in SYSTEM_TOOL_CODES or tool_code == "chat"
                    if tool_code in specs:
                        names = set(specs[tool_code].mcp_tools) | {definition.name for definition in definitions.get(tool_code, [])}
                        # Internal Chat also exposes the generic Messenger family.
                        # Its functions must obey solo/colleague policy as well.
                        if tool_code == "chat":
                            names.update(definition.name for definition in definitions.get("messenger", []))
                        for function in sorted(names):
                            await connections.set_connection_function_state(connection.id, function,
                                "enabled" if function in allowed else "disabled", commit=False)
            await db.commit()
            sources = []
            for index, content in enumerate(case.source_html):
                document, _ = await resource_service.create_item(DocumentItemCreate(owner_agent_id=agents[0].id,
                    title=f"Quartz source {index + 1}", payload=DocumentPayload(text=content), media_type="text/html",
                    source=DocumentSourceCreate(source_kind="qualification", source_ref=f"pilot:{case_code}:{index}")),
                    deduplicate=False)
                sources.append(document)
            target, _ = await resource_service.create_item(DocumentItemCreate(owner_agent_id=agents[0].id,
                title="Quartz — synthèse de travail", payload=DocumentPayload(text="<h1>Quartz</h1><p>Les inscriptions restent ouvertes.</p>"),
                media_type="text/html"), deduplicate=False)
            for document in [*sources, target]:
                for peer in agents[1:]:
                    await resource_service.set_item_grant(document.id, peer.id, DocumentGrantUpdate(can_write=False),
                        actor_agent_id=agents[0].id)
            room = await create_internal_room(actor_user_id=owner.id, agent_id=agents[0].id, label=f"Pilot Quartz — {case_code}")
            if room is None:
                raise RuntimeError("Could not create pilot Chat room")
            await db.commit()
            peers = [{"id": agent.id, "name": agent.first_name, "role": agent.job_title} for agent in agents[1:]]
            source_uris = [f"document://{document.id}" for document in sources]
            manifest = {
                "run_id": os.environ.get("TEAM_PILOT_RUN_ID", ""),
                "restart_after_amendment": os.environ.get("TEAM_PILOT_RESTART") == "1",
                "restart_phase": os.environ.get("TEAM_PILOT_RESTART_PHASE", "pending_amendment"),
                "schema_version": "galaris.agent-team-pilot/v1", "case": case_code, "mode": mode,
                "executable": execute, "leader_id": agents[0].id, "peer_ids": [agent.id for agent in agents[1:]],
                "profile_id": profile.id, "model_id": model.id, "team_id": team.id,
                "room_id": str(room.id), "source_uris": source_uris, "target_uri": f"document://{target.id}",
                "document_ids": [str(document.id) for document in [*sources, target]],
                "initial_sources": [{"uri": source_uris[index], "html": content} for index, content in enumerate(case.source_html)],
                "initial_target_html": "<h1>Quartz</h1><p>Les inscriptions restent ouvertes.</p>",
                "mission": mission(source_uris, f"document://{target.id}", peers, mode),
                "criteria": list(case.criteria), "amendment": case.amendment, "followup_amendment": case.followup_amendment,
                "fault": {"kind": "unavailable_provider", "agent_id": agents[2].id,
                          "profile_id": finance_profile.id} if case_code == "peer_failure" else None,
                "configuration": {key: value for key, value in config.items() if key != "base_url"},
                "limits": {"timeout_seconds": config.get("timeout_seconds", 600), "max_tokens": config.get("max_tokens", 150000)},
            }
            if manifest["restart_after_amendment"]:
                manifest["criteria"].extend([
                    ("L'écriture cible enregistrée avant le SIGKILL est conservée et la livraison finale intervient après redémarrage."
                     if manifest["restart_phase"] == "committed_write" else
                     "La consigne enregistrée avant le SIGKILL est retrouvée après redémarrage et appliquée une seule fois."),
                    "Les contributions terminées avant l'interruption sont conservées sans nouvelle inférence sur ces tâches.",
                    "Les révisions documentaires ne montrent aucun effet durable répété ; la réponse finale n'est livrée qu'une fois.",
                ])
            write_json(directory / "manifest.json", manifest)
            write_json(directory / "_session.json", {"email": owner.email, "password": password})
            from .evidence import readable_html
            overview = ["# Mission fictive à qualifier", "", "Ce fichier décrit les entrées ; il ne rapporte aucune réussite.",
                        "", f"Scénario : {case_code}. Organisation : {mode}.", "", "## Demande au responsable", "", manifest["mission"],
                        "", "## Sources fictives", ""]
            for index, content in enumerate(case.source_html):
                overview.extend([f"### Source {index + 1} — {source_uris[index]}", "", readable_html(content), ""])
            overview.extend(["## Critères réservés à la relecture", ""])
            overview.extend(f"- {criterion}" for criterion in case.criteria)
            if case.amendment:
                overview.extend(["", "## Nouvelle consigne après observation de deux collègues actifs", "", case.amendment])
            (directory / "scenario.md").write_text("\n".join(overview) + "\n", encoding="utf-8")
        finally:
            user_service.set_current_user(None)


def main() -> None:
    config = configuration(Path("/run/pilot/config.json"), execute=os.environ.get("TEAM_PILOT_EXECUTE") == "1")
    asyncio.run(seed(Path("/artifacts"), os.environ.get("TEAM_PILOT_CASE", "baseline"),
                     os.environ.get("TEAM_PILOT_MODE", "spontaneous"), config,
                     execute=os.environ.get("TEAM_PILOT_EXECUTE") == "1"))


if __name__ == "__main__":
    main()
