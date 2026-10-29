"""Opt-in paired qualification with real configured providers, never live memory."""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import event

from app.agent import context as agent_context
from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.llm import llm_service, model_usages
from app.memory import bootstrap, context, retrieval, semantic_index, service
from app.memory.embedding import resolve_embedding_model
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemoryRecallRequest
from app.memory.temporal import MemoryTemporalAnchor
from core.database import engine
from tests.memory_benchmark_adapter import assert_isolated
from tests.memory_benchmark_reference import load_reference, reference_fingerprints


class FactAnswer(BaseModel):
    answer: str | None = None
    conflict: bool = False
    sources: list[str] = Field(default_factory=list)


def fingerprint():
    root = Path(__file__).resolve().parents[3]
    paths = [root / "app/memory" / name for name in (
        "retrieval.py", "context.py", "admission.py", "provenance.py", "bootstrap.py")]
    paths.append(Path(__file__).resolve())
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


@pytest.mark.asyncio
async def test_configured_provider_relevance_campaign(request, db, agents, memory_storage, monkeypatch):
    if not request.config.getoption("--memory-benchmark-live", default=False):
        pytest.skip("Explicit live-provider opt-in required")
    assert_isolated()
    output = Path(request.config.getoption("--memory-benchmark-output"))
    output.resolve().relative_to(Path("/repo/artifacts").resolve())
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"synthetic": True, "complete": False, "source_fingerprints": fingerprint(),
                "scope": "paired hybrid retrieval, common driver context, configured-model answer; saturated calendar"}
    reference_path = Path(request.config.getoption('--memory-benchmark-reference'))
    manifest['reference_fingerprints'] = reference_fingerprints(reference_path)
    results = []
    try:
        owner, _ = agents
        model = await resolve_embedding_model()
        llm = await llm_service.get_profile_llm_for_agent_id(model_usages.CONVERSATION, owner.id)
        if llm is None:
            raise RuntimeError("Configured conversation model unavailable")
        from app.memory import embedding
        from app.memory.embedding import EmbeddingModel
        recording_path = request.config.getoption("--memory-benchmark-embedding-recording")
        lexical = request.config.getoption("--memory-benchmark-lexical")
        recording = json.loads(Path(recording_path).read_text()) if recording_path else None
        recorded_inputs = set()
        if recording is not None:
            # Cache identity is public; provider URLs and credentials never enter
            # the isolated DB. Every vector is an actual, frozen provider result.
            model = EmbeddingModel(key=recording["model_key"], code=recording["model_code"],
                model_name=recording["model_code"], base_url="")
        async def vectors(texts, **_kwargs):
            recorded_inputs.update(texts)
            return [recording["vectors"][value] for value in texts] if recording else [[1.0, 0.0] for _ in texts]
        async def configured_embedding():
            if lexical:
                from app.memory.embedding import MemoryEmbeddingNotConfiguredError
                raise MemoryEmbeddingNotConfiguredError("Controlled lexical qualification")
            return model
        monkeypatch.setattr(embedding, "embed_many", vectors)
        monkeypatch.setattr(semantic_index, "embed_many", vectors)
        monkeypatch.setattr(semantic_index, "resolve_embedding_model", configured_embedding)
        monkeypatch.setattr(retrieval, "resolve_embedding_model", configured_embedding)
        manifest.update(embedding_model=model.code, answer_model=llm.code)
        manifest["provider_phase"] = "lexical" if lexical else "frozen_real_embeddings" if recording else "collect_inputs_only"
        facts = [
            ("Aster reporting format", "Aster requires reporting files in CSV format.", "CSV", "What exact file format does Aster require for reporting?", "Quel format exact Aster impose-t-il pour ses fichiers de reporting ?"),
            ("Boreal annual limit", "Boreal has an annual spending limit of 730 euros.", "730", "What exact annual spending limit applies to Boreal?", "Quel plafond annuel exact de dépenses s'applique à Boreal ?"),
            ("Cobalt delivery day", "Cobalt accepts deliveries on Tuesday.", "Tuesday", "On which exact day does Cobalt accept deliveries?", "Quel jour exact Cobalt accepte-t-il les livraisons ?"),
            ("Dahlia reporting currency", "Dahlia requires reporting amounts in EUR.", "EUR", "What exact currency must Dahlia use for reporting?", "Quelle devise exacte Dahlia utilise-t-il pour le reporting ?"),
        ]
        identities = []
        for title, text, *_ in facts:
            item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title=title,
                payload=MemoryPayload(text=f"<p>{text}</p>"), media_type="text/html"))
            identities.append(item.id)
        now = datetime.now(timezone.utc)
        for index in range(10):
            item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
                title=f"Synthetic appointment {index}", payload=MemoryPayload(text=f"Separate scheduled appointment number {index}."),
                temporal=MemoryTemporalAnchor(year=now.year, month=now.month, day=now.day)))
            identities.append(item.id)
        assert len(set(identities)) == 14, "Saturation requires ten distinct calendar facts, not duplicate fixtures"
        # Invoke the real indexer and configured embedding protocol, not prescribed vectors.
        if not lexical:
            for identity in identities:
                await semantic_index.process_embedding_job({"item_id": str(identity)})
        reference = load_reference(reference_path, datetime)
        reference["retrieval"].resolve_embedding_model = configured_embedding
        reference["context"].search_memory_detailed = reference["facade"].search_memory_detailed
        reference["context"].temporal_hits = reference["retrieval"].temporal_hits
        reference["context"].admit_recall_hits = reference["retrieval"].admit_recall_hits
        monkeypatch.setattr(agent_context, "_providers", {})
        agent_context.register_context_provider("long_term_memory", bootstrap.memory_context_provider, priority=20)
        monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
        monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 8)
        monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_CHARS", 6_000)
        snapshot = AgentSnapshot(owner.id, owner.code, "Synthetic", "Agent", "internal")
        queries = [(f"fact-{index}-{language}", question, (identities[index],), expected)
                   for index, (_title, _text, expected, en, fr) in enumerate(facts)
                   for language, question in (("en", en), ("fr", fr))]
        queries += [
            ("two-facts-en", "What are Aster's reporting format and Dahlia's reporting currency? Return format;currency, or null if either is missing.", (identities[0], identities[3]), "CSV;EUR"),
            ("two-facts-fr", "Quels sont le format de reporting d'Aster et la devise de reporting de Dahlia ? Retourne format;devise, ou null si une preuve manque.", (identities[0], identities[3]), "CSV;EUR"),
            ("other-pair-en", "Give Boreal's annual limit and Cobalt's delivery day as amount;weekday, or null if either is missing.", (identities[1], identities[2]), "730;Tuesday"),
            ("other-pair-fr", "Donne le plafond annuel de Boreal et le jour de livraison de Cobalt sous la forme montant;jour (jour en anglais), ou null si une preuve manque.", (identities[1], identities[2]), "730;Tuesday"),
            ("unknown-en", "What is the exact password for the unknown Epsilon project?", (), None),
            ("unknown-fr", "Quel est le mot de passe exact du projet inconnu Epsilon ?", (), None),
        ]
        histories = {
            'follow-up-limit-en': 'We were discussing the annual limit for Boreal.',
            'follow-up-limit-fr': 'Nous parlions du plafond annuel de Boreal.',
            'follow-up-format-en': 'We were discussing the reporting file format for Aster.',
            'follow-up-format-fr': "Nous parlions du format des fichiers de reporting d'Aster.",
            'follow-up-unknown-en': 'We were discussing the exact access code for Epsilon.',
            'follow-up-unknown-fr': "Nous parlions du code d'accès exact pour Epsilon.",
        }
        queries += [
            ('follow-up-limit-en', 'And its value?', (identities[1],), '730'),
            ('follow-up-limit-fr', 'Et sa valeur ?', (identities[1],), '730'),
            ('follow-up-format-en', 'And its value?', (identities[0],), 'CSV'),
            ('follow-up-format-fr', 'Et sa valeur ?', (identities[0],), 'CSV'),
            ('follow-up-unknown-en', 'And its value?', (), None),
            ('follow-up-unknown-fr', 'Et sa valeur ?', (), None),
        ]
        for index, (key, question, expected_ids, expected) in enumerate(queries):
            history = ({'role': 'user', 'text': histories[key]},) if key in histories else ()
            # Alternate order; freeze facts, query, model and budgets between arms.
            for variant in (("previous", "current") if index % 2 == 0 else ("current", "previous")):
                sql = 0

                def count(*_args):
                    nonlocal sql
                    sql += 1

                event.listen(engine.sync_engine, "before_cursor_execute", count)
                started = time.perf_counter()
                try:
                    search = reference["retrieval"].recall_items if variant == "previous" else retrieval.recall_items
                    query_module = reference['context'] if variant == 'previous' else context
                    import inspect
                    query_args = dict(label='Conversation', objective=question)
                    if 'conversation_history' in inspect.signature(query_module.memory_context_query).parameters:
                        query_args['conversation_history'] = history
                    lexical_query = query_module.memory_context_query(**query_args)
                    semantic_query = query_module.memory_context_semantic_query(label='Conversation',
                        objective=question, conversation_history=history)
                    page = await search(MemoryRecallRequest(agent_id=owner.id, query=lexical_query,
                        semantic_query=semantic_query, exclude_temporal=True))
                    builder = reference["context"].build_memory_brief if variant == "previous" else context.build_memory_brief
                    monkeypatch.setattr(bootstrap, "build_memory_brief", builder)
                    # Freeze the query constructor too, adapting legacy signatures.
                    def build_query(**kwargs):
                        if 'conversation_history' not in inspect.signature(query_module.memory_context_query).parameters:
                            kwargs.pop('conversation_history', None)
                        return query_module.memory_context_query(**kwargs)
                    monkeypatch.setattr(bootstrap, 'memory_context_query', build_query)
                    monkeypatch.setattr(bootstrap, 'memory_context_semantic_query', query_module.memory_context_semantic_query)
                    prepared = await agent_context.build_agent_run_context(AgentContextRequest(
                        task_id=None, agent=snapshot, label="Conversation", objective=question, fallback_history=history))
                    latency_ms = (time.perf_counter() - started) * 1000
                finally:
                    event.remove(engine.sync_engine, "before_cursor_execute", count)
                injected = [str(value) for value in prepared.metadata.get("memory_context_ids", [])]
                results.append(dict(case=key, variant=variant,
                    retrieved=bool(expected_ids) and all(any(hit.item.id == identity for hit in page.hits) for identity in expected_ids),
                    injected=bool(expected_ids) and all(str(identity) in injected for identity in expected_ids),
                    retrieval_mode=page.mode, degraded=page.degraded,
                    expected=expected, expected_uris=[f"memory://{identity}" for identity in expected_ids],
                    sql_statements=sql, latency_ms=latency_ms,
                    context_chars=len(prepared.shared_context),
                    prompt=f"Prior subject (for resolving references only): {histories.get(key, '')}\n"
                           f"Question: {question}\n\nAvailable evidence:\n{prepared.shared_context}"))
                (output / "observations.json").write_text(json.dumps(results, indent=2) + "\n")
        if manifest["source_fingerprints"] != fingerprint():
            raise RuntimeError("Sources changed during the campaign")
        if manifest['reference_fingerprints'] != reference_fingerprints(reference_path):
            raise RuntimeError('Reference sources changed during the campaign')
        manifest["hybrid_complete"] = recording is not None
        manifest["lexical_complete"] = lexical
        manifest['complete'] = lexical or recording is not None
        (output / "embedding-inputs.json").write_text(json.dumps({"texts": sorted(recorded_inputs)}, indent=2) + "\n")
    except Exception as error:
        manifest["failure_class"] = type(error).__name__
        raise
    finally:
        manifest["observations"] = len(results)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
