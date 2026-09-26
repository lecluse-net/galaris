"""Product knowledge remains readable, attributable and scoped to the shipped version."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app.documentation import corpus, facade
from app.documentation.models import DocumentationPassage


@pytest.fixture
def release_sources(tmp_path):
    for language in ("fr", "en"):
        for relative in ("README.md", "features.md", "user/navigation.md",
                         "architecture/generated/navigation.md", "architecture/generated/navigation.json"):
            target = tmp_path / "docs" / language / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"entries": []}' if relative.endswith(".json") else
                              "# Observatory guide\n\n## Stations\nVoyage → Observatory → Stations at /sample/stations.\n")
    return tmp_path


def test_release_gate_rejects_missing_sources_translations_and_stale_container(release_sources):
    from app.documentation.readiness import check_corpus

    snapshot = facade.load_corpus(root=release_sources)
    revision = check_corpus(snapshot)
    target = release_sources / "docs/en/user/navigation.md"
    target.write_text(target.read_text() + "\nA new route.\n")
    current = facade.load_corpus(root=release_sources)
    with pytest.raises(ValueError, match="differs from the prepared"):
        check_corpus(current, expected_revision=revision)
    target.unlink()
    with pytest.raises(FileNotFoundError):
        check_corpus(facade.load_corpus(root=release_sources))
    target.write_text("# Observatory guide\n\nRestored guide.\n")
    (target.parent / "new-feature.md").write_text("# New feature\n")
    with pytest.raises(ValueError, match="counterparts"):
        check_corpus(facade.load_corpus(root=release_sources))


def test_offline_release_check_needs_no_database_or_provider(release_sources):
    import os
    import subprocess
    import sys

    # Same isolated configuration as image qualification: a synthetic encryption key,
    # no production credentials, no reachable database and no development-mode bypass.
    result = subprocess.run(
        [sys.executable, "-m", "app.documentation", "check", "--root", str(release_sources)],
        env={"PATH": os.environ["PATH"], "APP_ENV": "prod",
             "ENCRYPTION_MASTER_KEY": "documentation-offline-check-key-0001"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"content_revision"' in result.stdout


@pytest.mark.parametrize("command", ["check", "revision"])
def test_offline_commands_never_import_the_orm_or_settings(release_sources, command):
    import os
    import subprocess
    import sys

    # The minimal documentation image ships neither SQLAlchemy nor application settings.
    # Blocking those imports proves the offline commands stay usable there, while the
    # ORM export below still works for every runtime caller.
    blocker = (
        "import sys\n"
        "class Absent:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in {'sqlalchemy', 'core'}:\n"
        "            raise ModuleNotFoundError(f'absent in the documentation image: {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Absent())\n"
        "import runpy\n"
        "sys.argv = ['app.documentation', %r, '--root', %r]\n"
        "runpy.run_module('app.documentation', run_name='__main__')\n"
    ) % (command, str(release_sources))
    result = subprocess.run(
        [sys.executable, "-c", blocker], cwd=os.getcwd(),
        env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "sqlalchemy" not in result.stderr.lower()


def test_orm_export_stays_available_to_runtime_callers():
    # The package keeps its public model export: a lazy module __getattr__ must not
    # break model registration or the documented import path.
    from app import documentation

    assert documentation.DocumentationPassage is DocumentationPassage
    with pytest.raises(AttributeError):
        getattr(documentation, "Missing")


@pytest.mark.asyncio
async def test_refresh_makes_new_sources_searchable_without_model_or_agent_grants(db, release_sources):
    from app.documentation.readiness import check_corpus, refresh_and_check

    initial = facade.load_corpus(root=release_sources)
    with pytest.raises(ValueError, match="differs"):
        await refresh_and_check(initial, expected_revision="0" * 64)
    assert await db.scalar(select(func.count()).select_from(DocumentationPassage)) == 0
    first = await refresh_and_check(initial, expected_revision=check_corpus(initial))
    assert first.indexed_passages == len(initial.passages)
    count = await db.scalar(select(func.count()).select_from(DocumentationPassage))
    assert await refresh_and_check(initial) == first
    assert await db.scalar(select(func.count()).select_from(DocumentationPassage)) == count
    target = release_sources / "docs/fr/user/navigation.md"
    target.write_text("# Observatory guide\n\nStations moved to /new/stations.\n")
    current = facade.load_corpus(root=release_sources)
    refreshed = await refresh_and_check(current)
    assert refreshed.content_revision != first.content_revision
    result = await facade.search(current, "Stations", language="fr", path_prefix="docs/fr/user/navigation.md")
    assert "/new/stations" in result.hits[0].excerpt
    assert all(hit.checksum != facade.page_at(initial, "docs/fr/user/navigation.md").checksum for hit in result.hits)


@pytest.fixture
def sources(tmp_path, monkeypatch):
    pages = {
        "docs/fr/user/documents.md": "# Documents\n\n## Partage\nPour partager un document, choisir les destinataires. Un lien ne donne pas accès.\n",
        "docs/en/user/goals.md": "# Goals\n\n## Recurring work\nA Goal coordinates repeated work through successive cycles.\n",
        "docs/fr/user/navigation.md": "# Navigation synthétique\n\n## Observatoire\nMenu Voyage → Observatoire → Stations, route `/sample/stations`.\n",
        "docs/fr/dev/database.md": "# Schéma\n\nUtiliser `make sync-db` avec `APP_ENV=dev`.\n\n```sh\n# This is a code comment\nmake sync-db\n```\n",
        "project/plans/future.md": "# Partage futur\n\nPartage automatique prospectif des documents.\n",
        "project/plans/README.md": "| Plan | Statut |\n| [Future](future.md) | `approved` |\n",
    }
    for relative, text in pages.items():
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    (tmp_path / ".env").write_text("SECRET=synthetic-only")
    (tmp_path / "docs/fr/user/escape.md").symlink_to(tmp_path / ".env")
    monkeypatch.setattr(corpus, "source_root", lambda: tmp_path)
    return tmp_path


def test_shipped_sources_are_bounded_and_keep_provenance(sources):
    snapshot = facade.load_corpus()
    assert len(snapshot.pages) == 6
    assert all("synthetic-only" not in p.content for p in snapshot.pages)
    plan = facade.page_at(snapshot, "project/plans/future.md")
    assert (plan.kind, plan.status) == ("plan", "approved")
    assert not any(p.heading == "This is a code comment" for p in snapshot.passages)
    assert all(p.text == p.page.content[p.start:p.end] for p in snapshot.passages)
    with pytest.raises(FileNotFoundError):
        facade.page_at(snapshot, "../../.env")


@pytest.mark.asyncio
async def test_search_handles_questions_symbols_and_removed_sources(db, sources):
    snapshot = facade.load_corpus()
    response = await facade.search(snapshot, "Comment partager un document ?", language="fr")
    assert response.hits[0].uri.endswith("docs/fr/user/documents.md")
    assert response.mode == "lexical"
    assert response.degradation_reason == "no_vector_model"
    exact = await facade.search(snapshot, "APP_ENV", language="fr")
    assert exact.hits[0].uri.endswith("database.md")
    navigation = await facade.search(snapshot, "Où trouver les stations de l’observatoire ?", language="fr", domain="user")
    assert navigation.hits[0].uri.endswith("docs/fr/user/navigation.md")
    assert "/sample/stations" in navigation.hits[0].excerpt
    old = response.hits[0]
    path = sources / "docs/fr/user/documents.md"
    path.unlink()
    current = facade.load_corpus()
    response = await facade.search(current, "partager", language="fr", kind="documentation")
    assert old.uri not in [hit.uri for hit in response.hits]
    assert current.revision != snapshot.revision
    assert await db.scalar(select(func.count()).select_from(DocumentationPassage)) > 0


@pytest.mark.asyncio
async def test_semantic_index_is_incremental_and_does_not_reuse_other_models(db, sources):
    snapshot = facade.load_corpus()

    async def embed(texts):
        return [[1.0, 0.0] if "successive cycles" in text else [0.0, 1.0] for text in texts]

    embedding = AsyncMock(side_effect=embed)
    count = await facade.index_embeddings(snapshot, model_key="a" * 64, embed=embedding, batch_size=100)
    assert count == len(snapshot.passages)
    assert await facade.index_embeddings(snapshot, model_key="a" * 64, embed=embedding) == 0
    assert embedding.await_count == 1
    result = await facade.search(snapshot, "orchestration périodique", model_key="a" * 64, query_vector=[1.0, 0.0])
    assert result.mode == "hybrid"
    assert result.hits[0].uri.endswith("goals.md")
    assert result.indexed_passages == result.total_passages
    changed_model = await facade.search(snapshot, "orchestration périodique", model_key="b" * 64, query_vector=[1.0, 0.0])
    assert changed_model.mode == "lexical"
    assert changed_model.degradation_reason == "semantic_index_incomplete"


@pytest.mark.asyncio
async def test_documentation_access_can_exclude_audits_and_is_revoked_live(db, sources):
    from app.agent.models import Agent, Title
    from app.connection.models import Connection, ConnectionFunctionState
    from app.tools.models import Tool
    from app.tools import mandatory_tools
    from app.tools import documentation_service
    from app.file_share import resource_service
    from app.file_share.resource_contracts import ResourceContext
    from app.skill import skill_service

    title = Title(label="Knowledge test", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, code="knowledge-test", first_name="Product", last_name="Guide", agent_driver="internal")
    db.add(agent)
    await db.flush()
    await mandatory_tools.sync_integrated_tool_connections(agent.id)
    connection = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == agent.id, Tool.code == "galaris_admin"))
    ctx = ResourceContext(agent_id=agent.id, runtime="internal")
    uri = "galaris://documentation/docs/fr/user/documents.md"
    with pytest.raises(PermissionError):
        await resource_service.resource_read(ctx, uri)

    connection.active = True
    for name in ("conversation_round_get", "voice_turn_get", "llm_call", "llm_calls"):
        db.add(ConnectionFunctionState(connection_id=connection.id, function_name=name, enabled=False))
    await db.flush()
    catalog = await documentation_service.documentation_catalog(agent.id)
    assert catalog["pages"] == 6
    navigation_uri = "galaris://documentation/docs/fr/user/navigation.md"
    assert navigation_uri in catalog["entrypoints"]
    assert "/sample/stations" in (await resource_service.resource_read(ctx, navigation_uri)).content
    assert "galaris-knowledge" in await skill_service.get_assigned_codes(agent.id)
    root = await resource_service.resource_list(ctx, "galaris://")
    assert "galaris://documentation/" in {entry.uri for entry in root.entries}
    with pytest.raises(PermissionError, match="read-only"):
        await resource_service.resource_write(ctx, uri, b"Unrequested replacement")
    listing = await resource_service.resource_list(ctx, "galaris://documentation/", max_entries=2)
    assert listing.next_cursor
    first = await resource_service.resource_read(ctx, uri, max_chars=20)
    second = await resource_service.resource_read(ctx, uri, offset=first.next_offset)
    assert first.content + second.content == facade.page_at(facade.load_corpus(), "docs/fr/user/documents.md").content
    source = sources / "docs/fr/user/documents.md"
    source.write_text(source.read_text() + "\nUne précision ajoutée.\n")
    with pytest.raises(ValueError, match="changed"):
        await resource_service.resource_list(ctx, "galaris://documentation/", cursor=listing.next_cursor)
    knowledge = await skill_service.get_by_code("galaris-knowledge")
    await skill_service.set_agent_authorization(knowledge.id, agent.id, "disabled")
    assert "galaris-knowledge" not in await skill_service.get_assigned_codes(agent.id)
    await skill_service.set_agent_authorization(knowledge.id, agent.id, "default")
    assert "galaris-knowledge" in await skill_service.get_assigned_codes(agent.id)
    disabled = ConnectionFunctionState(connection_id=connection.id, function_name="documentation_catalog", enabled=False)
    db.add(disabled)
    await db.flush()
    assert "galaris-knowledge" not in await skill_service.get_assigned_codes(agent.id)
    for operation in (resource_service.resource_read(ctx, uri), resource_service.resource_info(ctx, uri),
                      documentation_service.documentation_catalog(agent.id)):
        with pytest.raises(PermissionError):
            await operation
    await db.delete(disabled)
    await db.flush()
    assert (await resource_service.resource_read(ctx, uri)).content
    connection.active = False
    await db.flush()
    with pytest.raises(PermissionError):
        await resource_service.resource_read(ctx, uri)


@pytest.mark.asyncio
async def test_mcp_documentation_only_search_read_and_live_revocation(committed_database, sources, monkeypatch):
    import json
    from uuid import uuid4
    from fastmcp import Client
    from app.agent.models import Agent, Title
    from app.connection.models import Connection, ConnectionFunctionState
    from app.tools.models import Tool
    from app.tools import mandatory_tools, mcp_loader, documentation_service
    from core.database import get_db_session
    from core.user.models import User

    # A provider failure must not prevent the user from finding and reading a guide.
    monkeypatch.setattr(documentation_service, "configured_embedding_model", AsyncMock(side_effect=RuntimeError("synthetic outage")))
    async with get_db_session() as db:
        title = Title(label="Product knowledge", gender="X")
        user = User(email=f"knowledge-{uuid4().hex}@example.test", hashed_password="unused")
        db.add_all([title, user])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"knowledge-{uuid4().hex}",
                      first_name="Synthetic", last_name="Guide", agent_driver="internal")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        await mandatory_tools.sync_integrated_tool_connections(agent_id)
        connection = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == agent_id, Tool.code == "galaris_admin"))
        connection.active = True
        connection_id = connection.id
        tool = await db.get(Tool, connection.tool_id)
        tool.conversation_enabled = True
        for name in ("conversation_round_get", "voice_turn_get", "llm_call", "llm_calls"):
            db.add(ConnectionFunctionState(connection_id=connection_id, function_name=name, enabled=False))
    async with get_db_session():
        server = await mcp_loader.build_agent_galaris_fastmcp(agent_id, conversation_only=True)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {"documentation_search", "documentation_catalog", "file_read"} <= names
        assert not {"llm_call", "llm_calls", "voice_turn_get", "conversation_round_get"} & names
        result = await client.call_tool("documentation_search", {"query": "Comment partager un document ?", "language": "fr"})
        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["mode"] == "lexical"
        assert payload["degradation_reason"] == "semantic_provider_unavailable"
        hit = payload["hits"][0]
        read = await client.call_tool("file_read", {"uri": hit["uri"], "offset": hit["offset"], "max_chars": hit["max_chars"]})
        assert not read.is_error
        source = json.loads(read.content[0].text)
        assert "destinataires" in source["content"]
        assert source["corpus_revision"] == payload["corpus_revision"]
        assert source["checksum"] == hit["checksum"]
        async with get_db_session() as db:
            db.add(ConnectionFunctionState(connection_id=connection_id, function_name="documentation_catalog", enabled=False))
        denied = await client.call_tool("file_read", {"uri": hit["uri"]}, raise_on_error=False)
        assert denied.is_error
        denied_search = await client.call_tool("documentation_search", {"query": "document"}, raise_on_error=False)
        assert denied_search.is_error
