"""Offline retrieval benchmark. Use pytest -s to report metrics for each channel."""

import math
from uuid import uuid4

import pytest

from app.agent import context as agent_context
from app.agent.contracts import AgentContextCandidate, AgentContextContribution, AgentContextRequest, AgentSnapshot
from app.memory import bootstrap, retrieval, semantic_index, service
from app.memory.embedding import EmbeddingModel
from app.memory.schemas import MemoryItemCreate, MemoryPayload


# Independent judgements on a mixed FR/EN collection. The common prefix and
# unrelated previous turn make both lexical and conversational drift observable.
TOPICS = (
    ("réglage du clavecin", "Le diapason de concert vaut 415 Hz.", "Comment régler le clavecin et son diapason ?"),
    ("irrigation du verger", "Le goutteur consomme deux litres par heure.", "irrigation : débit du goutteur au verger"),
    ("filtration des pigments", "Le tamis retient les grains épais.", "Quel tamis pour la filtration des pigments ?"),
    ("contrôle des émaux", "La cuisson du grès dure huit heures.", "Comment se déroule la cuisson des émaux ?"),
    ("lighthouse optics", "The Fresnel lens rotates twice per minute.", "What lens is used in the lighthouse optics?"),
    ("sailing ballast", "The keel contains iron bars.", "What ballast goes in the sailing keel?"),
    ("loom calibration", "The shuttle tension is six units.", "Which tension for loom calibration?"),
    ("orchid pollination", "A wax probe transfers pollen.", "What probe is used for orchid pollination?"),
)
ABSENT = ("Bonjour !", "Merci beaucoup.", "See you tomorrow.", "Underwater archaeology",
          "La cristallographie des minéraux", "Quasar pulsation period",
          "Atelier cristallographie", "Workshop quasar pulsations")
PARAPHRASE = "How quickly does the beacon revolve?"


@pytest.mark.asyncio
async def test_turn_relevance_benchmark(db, agents, memory_storage, monkeypatch):
    owner, peer = agents
    contact_id = uuid4()
    snapshot = AgentSnapshot(owner.id, owner.code, "Synthetic", "Benchmark", "internal")
    model = EmbeddingModel(key="benchmark", code="benchmark", model_name="benchmark", base_url="")
    async def configured():
        return model
    async def embed(texts, **kwargs):
        # This provider double models a shared embedding direction. Only the
        # lighthouse passage has the second component of the paraphrase vector.
        return [[0.82, math.sqrt(1 - 0.82**2), 0.] if "Fresnel" in text
                else [0.82, 0., math.sqrt(1 - 0.82**2)] for text in texts]
    async def query(*args, **kwargs):
        if PARAPHRASE in args[0]:
            return [0.82, math.sqrt(1 - 0.82**2), 0.]
        return [1., 0., 0.]
    monkeypatch.setattr(semantic_index, "resolve_embedding_model", configured)
    monkeypatch.setattr(semantic_index, "embed_many", embed)
    monkeypatch.setattr(retrieval, "resolve_embedding_model", configured)
    monkeypatch.setattr(retrieval, "embed_query", query)
    ids = []
    documents = []
    for topic, fact, _ in TOPICS:
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
            title=f"Atelier / Workshop — {topic}", payload=MemoryPayload(text=f"<p>{fact}</p>")))
        await semantic_index.process_embedding_job({"item_id": str(item.id)})
        ids.append(str(item.id))
        uri = f"document://{uuid4()}"
        documents.append(AgentContextCandidate(key=uri, reference=uri, kind="resource", title=item.title,
            excerpt=f"Role: primary_working_document; source Task: {topic}", base_score=0.9,
            metadata={"resource_type": "memory_document"}))
    private, _ = await service.create_item(MemoryItemCreate(owner_agent_id=peer.id,
        title=TOPICS[0][0], payload=MemoryPayload(text="<p>Confidential tuning chart.</p>")))
    await semantic_index.process_embedding_job({"item_id": str(private.id)})
    monkeypatch.setattr(agent_context, "_providers", {})
    agent_context.register_context_provider("memory", bootstrap.memory_context_provider)
    agent_context.register_context_provider("historical_documents", lambda _: AgentContextContribution(candidates=tuple(documents)))
    results = {"memory": [], "continuity": []}
    questions = [row[2] for row in TOPICS] + list(ABSENT) + [PARAPHRASE]
    for index, question in enumerate(questions):
        previous = TOPICS[(index + 3) % len(TOPICS)][0]
        prepared = await agent_context.build_agent_run_context(AgentContextRequest(
            task_id=None, agent=snapshot, label="Conversation", objective=question,
            contact_memory_item_id=contact_id,
            fallback_history=({"role": "assistant", "text": previous},)))
        assert not any(key.endswith("_error") for key in prepared.metadata), prepared.metadata
        entries = prepared.context_capsule.entries
        assert str(private.id) not in {entry.reference for entry in entries}
        for channel, kind, references in (("memory", "memory", ids),
                ("continuity", "resource", [doc.reference for doc in documents])):
            expected = references[index] if index < len(TOPICS) else None
            if channel == "memory" and question == PARAPHRASE:
                expected = ids[4]
            results[channel].append((expected, [entry.reference for entry in entries if entry.kind == kind]))
    for channel, rows in results.items():
        positives = [(expected, hits) for expected, hits in rows if expected]
        correct = sum(expected in hits for expected, hits in positives)
        emitted = sum(len(hits) for _, hits in rows)
        precision = correct / emitted if emitted else 0.
        recall = correct / len(positives)
        mrr = sum(1 / (hits.index(expected) + 1) for expected, hits in positives if expected in hits) / len(positives)
        negatives = [hits for expected, hits in rows if expected is None]
        abstention = sum(not hits for hits in negatives) / len(negatives)
        print(f"{channel}: precision={precision:.3f} recall={recall:.3f} MRR={mrr:.3f} abstention={abstention:.3f}")
    for rows in results.values():
        assert all(hits == ([expected] if expected else []) for expected, hits in rows), rows
