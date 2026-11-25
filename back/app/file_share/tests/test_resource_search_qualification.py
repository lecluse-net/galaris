"""Synthetic relevance judgments against the actual PostgreSQL search entry point."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from math import ceil, log2
from random import Random
from statistics import mean, median
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update

from app.agent import AgentContextCandidate, AgentContextContribution, AgentContextRequest, AgentSnapshot, build_agent_run_context
from app.agent import context as agent_context
from app.document import document_service, resource_service as documents
from app.document.schemas import DocumentGrantUpdate
from app.file_share import ResourceContext, resource_create, resource_index, resource_index_query, resource_search
from app.file_share.resource_index import IndexSubject, index_subject, pending_subjects, refresh_vectors
from app.file_share.models import ResourceIndexContent, ResourceIndexSource
from app.file_share.resource_index_content import document_kind, order_evidence, passages
from app.file_share.resource_index_query import index_details, related_index_sources
from app.memory import service as memory
from app.memory import MemoryTemporalAnchor, MessengerContactObservation, create_mail_contact, observe_messenger_contact, search_memory_detailed
from app.memory import indexed_resources
from app.memory.context import build_memory_brief
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.memory.tests.conftest import agents, memory_storage  # noqa: F401
from core.user import UserModel
from core.util import local_timezone_name


def ndcg(ranking: Sequence[str], expected: dict[str, int], k: int) -> float:
    def discounted_gain(grades: Sequence[int]) -> float:
        return sum((2**grade - 1) / log2(rank + 2) for rank, grade in enumerate(grades[:k]))

    return discounted_gain([expected.get(key, 0) for key in ranking]) / discounted_gain(sorted(expected.values(), reverse=True))


@pytest.mark.parametrize("kind,subject,property_", [
    ("facture", "linogravure", "acompte"), ("invoice", "shipyard", "deposit"),
    ("devis", "jardinières", "arrosage"), ("quote", "greenhouse", "ventilation"),
])
def test_federated_ranking_requires_the_requested_subject_across_title_and_passage(kind, subject, property_):
    from app.memory import FederatedEvidence, rank_federated

    relevant = FederatedEvidence("source", subject, f"{kind} — {property_}", source_document=True)
    partial = FederatedEvidence("note", "Suivi", f"{subject} {property_}")
    distractors = [FederatedEvidence(f"other-{index}", f"{kind} {index}", property_,
        source_document=True, contact_match=True) for index in range(8)]
    ranked = rank_federated(f"{kind} {subject} {property_}", [partial], [*distractors, relevant],
        lambda item: item)
    assert ranked[0].identity == relevant.identity


@pytest.mark.parametrize("document_answers", [True, False])
def test_federated_detail_needs_the_subject_and_answer_in_one_passage(document_answers):
    from app.memory import FederatedEvidence, rank_federated

    question = "Quel est le code d’entrée de Maison Aurore ?"
    answer = FederatedEvidence("answer", "Accueil", "Maison Aurore: use the keypad at reception.",
                               source_document=document_answers)
    subject_only = FederatedEvidence("mention", "Maison Aurore", "La cantine est fermée.")
    split = FederatedEvidence("directory", "Annuaire", "Maison Aurore organise un déjeuner.",
                              passages=("Maison Érable: son code d’entrée est disponible sur place.",),
                              contact_match=True)
    documents, memories = ([answer], [subject_only, split]) if document_answers else ([subject_only, split], [answer])
    ranked = rank_federated(question, memories, documents, lambda item: item)
    assert ranked[0] == answer
    assert len(ranked) == 3


@pytest.mark.asyncio
async def test_federated_ranking_promotes_all_exact_sources_over_mentions(db, agents, memory_storage):
    owner, reader = agents
    expected_by_query: dict[str, dict[str, int]] = {}
    for reference in ("CMB-192", "PLV-623", "DRK-867"):
        relevant: dict[str, int] = {}
        for kind in ("Facture", "Devis", "Bon de livraison", "Commande"):
            item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
                title=f"{kind} {reference}", content=f"<p>{kind} {reference}</p><p>Pièce de référence du dossier.</p>")
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
            assert await index_subject(IndexSubject("document", item.id, item.content_hash))
            relevant[f"document://{item.id}"] = 3
        for ordinal in range(5):
            await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id,
                title=f"Note de suivi {ordinal}", payload=MemoryPayload(text=(
                    f"<p>Nous avons évoqué le numéro {reference} pendant le suivi {ordinal}. "
                    "La pièce elle-même est dans le dossier.</p>"))))
        expected_by_query[reference] = relevant

    actor = ResourceContext(reader.id, "internal")
    async def search(query):
        return await resource_search(actor, "memory://", query, mode="text", max_results=4)

    for query in expected_by_query:
        await search(query)
    durations: list[float] = []
    rankings: dict[str, list[str]] = {}
    for _ in range(12):
        for query in expected_by_query:
            start = perf_counter()
            result = await search(query)
            durations.append((perf_counter() - start) * 1000)
            rankings[query] = [hit.resource.uri for hit in result.hits]
    relevance = mean(ndcg(rankings[query], expected, 4) for query, expected in expected_by_query.items())
    print(f"FEDERATED_SEARCH_QUALIFICATION queries={len(durations)} ndcg_at_4={relevance:.4f} "
          f"p50_ms={median(durations):.2f} p95_ms={sorted(durations)[ceil(len(durations) * .95) - 1]:.2f}")
    for query, expected in expected_by_query.items():
        assert set(rankings[query]) == set(expected), (query, rankings[query], expected)
        assert len(rankings[query]) == len(expected)
    query = next(iter(expected_by_query))
    first = await search(query)
    assert first.next_cursor is not None
    second = await resource_search(actor, "memory://", query, mode="text", max_results=4, cursor=first.next_cursor)
    full = await resource_search(actor, "memory://", query, mode="text", max_results=8)
    assert [hit.resource.uri for hit in (*first.hits, *second.hits)] == [hit.resource.uri for hit in full.hits]


@pytest.mark.asyncio
async def test_sales_corpus_relevance_and_complete_accessible_recall(db, agents, memory_storage):
    owner, reader = agents
    definitions = {
        "invoice": ("Facture FCT-714", "Facture FCT-714", "CMD-381", "82736481927364", "Échéance contractuelle : 14 février."),
        "delivery": ("Bon de livraison BL-990", "Bon de livraison BL-990", "CMD-381", "82736481927364", "Expédition des sondes Nébulor."),
        "quote": ("Devis DV-123", "Devis DV-123", "CMD-381", "82736481927364", "Installation des sondes Nébulor."),
        "other_issuer": ("Facture FCT-713", "Facture FCT-713", "CMD-381", "93847591027364", "Sondes Nébulor pour un autre partenaire."),
        "adjacent": ("Facture FCT-715", "Facture FCT-715", "CMD-387", "82736481927364", "Échéance contractuelle : 28 avril."),
        "private": ("Facture FCT-714", "Facture FCT-714", "CMD-381", "82736481927364", "IndigoPrive."),
        "mention": ("Notes de suivi", "Compte rendu", "CMD-999", "82736481927364", "Discussion de la facture FCT-714." * 12),
    }
    refs = {}
    for key, (title, heading, order, issuer, body) in definitions.items():
        item = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title=title,
            content=f"<p>{heading}</p><p>Référence commande : {order}</p><p>SIRET émetteur : {issuer}</p><p>{body}</p>")
        refs[key] = f"document://{item.id}"
        if key != "private":
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))
    await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id, title="Note de préparation",
        payload=MemoryPayload(text="<p>Retrouver la facture FCT-714 lorsqu’elle sera déposée.</p>")))
    actor = ResourceContext(reader.id, "internal")
    judgments = (
        ("facture FCT-714", {"invoice": 3, "mention": 1}, "invoice"),
        ("echeance contractuelle", {"invoice": 3, "adjacent": 3}, None),
        ("sondes nebulor", {"delivery": 3, "quote": 3, "other_issuer": 3}, None),
        ("installation sondes nebulor", {"quote": 3}, "quote"),
        ("CMD-381", {"invoice": 3, "delivery": 3, "quote": 3, "other_issuer": 3}, None),
    )
    for query, expected, first in judgments:
        golden = {refs[key]: grade for key, grade in expected.items()}
        found = await resource_search(actor, "memory://", query, mode="text", max_results=10)
        ranking = [hit.resource.uri for hit in found.hits]
        assert golden.keys() <= set(ranking), (query, ranking, golden)
        assert refs["private"] not in ranking
        assert "IndigoPrive" not in found.model_dump_json()
        assert ndcg(ranking, golden, k=5) >= 0.85, (query, ranking, golden)
        if first:
            assert ranking[0] == refs[first]
    related = await related_index_sources(actor, refs["invoice"])
    assert {link["uri"] for link in related} == {refs["quote"], refs["delivery"]}
    assert (await index_details(actor, refs["invoice"]))["document_kind"] == "invoice"


@pytest.mark.asyncio
@pytest.mark.parametrize("padding", [470, 594])
async def test_file_search_recovers_phrase_across_chunk_boundary(db, agents, isolated_managed_files, padding):
    owner, _reader = agents
    actor = ResourceContext(owner.id, "internal")
    content = ("x " * padding) + "héliotrope déporté à la fin de la page."
    item = await resource_create(actor, "file://", content.encode(), name="Boundary.txt")
    handled = select(ResourceIndexSource.uri).where(ResourceIndexSource.id.is_(None))
    stored = next(subject for subject in await pending_subjects(handled) if subject.kind == "stored")
    assert await index_subject(stored)
    for query in ('"héliotrope déporté"', '"heliotrope deporte"'):
        result = await resource_search(actor, item.uri, query, mode="text")
        assert result.hits and result.hits[0].passages
        assert "héliotrope déporté" in result.hits[0].excerpt
        assert any("héliotrope déporté" in part["text"] for part in result.hits[0].passages)


@pytest.mark.asyncio
async def test_context_recovers_a_supported_passage_from_a_verbose_request(agents, memory_storage):
    reader, other = agents
    uris = []
    for agent, body in ((reader, "Analyse spectrale du basalte poreux."),
                        (reader, "Analyse annuelle du mobilier du laboratoire."),
                        (other, "Analyse spectrale du basalte poreux.")):
        item = await document_service.create_document(owner_agent_id=agent.id, task_id=None,
            title="Bulletin expérimental", content=f"<p>{body}</p>")
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))
        uris.append(f"document://{item.id}")
    question = "Retrouve notre discussion sur l'analyse spectrale du basalte poreux"
    result = await resource_index_query.search_resource_index(ResourceContext(reader.id, "internal"),
        question, mode="text", contextual_resources=True)
    assert result is not None
    assert [hit.resource.uri for hit in result.hits] == uris[:1]
    assert "basalte poreux" in result.hits[0].excerpt


@pytest.mark.asyncio
async def test_distributed_terms_return_both_evidence_fragments_without_weakening_quotes(db, agents, isolated_managed_files):
    owner, _reader = agents
    actor = ResourceContext(owner.id, "internal")
    first = "La clé tourmalinemobile désigne le matériel."
    last = "L'atelier zéphyrrotatif stocke le matériel."
    irrelevant = " ligne intermédiaire " * 160
    full = await resource_create(actor, "file://", f"{first}\n{irrelevant}\n{last}".encode(), name="Complete.txt")
    partial = await resource_create(actor, "file://", first.encode(), name="Partial.txt")
    handled = select(ResourceIndexSource.uri).where(ResourceIndexSource.id.is_(None))
    for _ in (full, partial):
        stored = next(subject for subject in await pending_subjects(handled) if subject.kind == "stored")
        assert await index_subject(stored)
    result = await resource_search(actor, "memory://", "tourmalinemobile zephyrrotatif", mode="text")
    assert [hit.resource.uri for hit in result.hits] == [full.uri]
    assert all(any(value in passage["text"] for passage in result.hits[0].passages)
               for value in ("tourmalinemobile", "zéphyrrotatif"))
    quoted = await resource_search(actor, full.uri, '"tourmalinemobile zephyrrotatif"', mode="text")
    assert quoted.hits == []


@pytest.mark.asyncio
async def test_dense_result_pages_return_every_authorized_source_once(db, agents, memory_storage):
    owner, reader = agents
    visible = set()
    for ordinal in range(36):
        item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title=f"Qualification Andésite {ordinal:03d}", content=f"<p>Marqueur andésitebellule dans la pièce {ordinal}.</p>")
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))
        if ordinal % 4:
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
            visible.add(f"document://{item.id}")
    actor = ResourceContext(reader.id, "internal")
    cursor = None
    returned: list[str] = []
    for _ in range(15):
        page = await resource_search(actor, "memory://", "andesitebellule", mode="text", max_results=3, cursor=cursor)
        returned.extend(hit.resource.uri for hit in page.hits)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert cursor is None and len(returned) == len(visible)
    assert set(returned) == visible
    unpaged = await resource_search(actor, "memory://", "andesitebellule", mode="text", max_results=40)
    assert returned == [hit.resource.uri for hit in unpaged.hits]


@pytest.mark.asyncio
async def test_hybrid_finds_paraphrases_but_preserves_exact_reference_priority(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    sources = [("Official NFV-960", "NFV-960. Adverse weather cancels transport."),
               ("Dispatch guidance", "Do not load the vehicle in icy conditions."),
               ("Private NFV-960", "Private NFV-960 hiddenverdict for icy roads.")]
    identities = []
    for ordinal, (title, body) in enumerate(sources):
        item = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title=title, content=f"<p>{body}</p>")
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))
        identities.append(f"document://{item.id}")
        if ordinal < 2:
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)

    async def embed(texts):
        return [[0.0, 1.0] if "Adverse" in text else [1.0, 0.0] for text in texts]

    model = SimpleNamespace(key="synthetic-qualification-vector", embed=AsyncMock(side_effect=embed))
    monkeypatch.setattr(resource_index, "_embedding_model", AsyncMock(return_value=model))
    for content_id in await db.scalars(select(ResourceIndexContent.id)):
        assert await refresh_vectors(content_id, model.key)
    actor = ResourceContext(reader.id, "internal")
    semantic = await resource_search(actor, "memory://", "frost precautions", mode="semantic")
    assert semantic.retrieval_mode == "hybrid"
    assert semantic.hits[0].resource.uri == identities[1]
    exact = await resource_search(actor, "memory://", "NFV-960", mode="semantic")
    assert exact.hits[0].resource.uri == identities[0]
    assert all(hit.resource.uri != identities[2] for hit in (*semantic.hits, *exact.hits))
    assert "hiddenverdict" not in semantic.model_dump_json()


@pytest.mark.asyncio
async def test_round_spends_one_eight_item_budget_across_memory_and_shared_documents(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    contact = await create_mail_contact(owner_agent_id=reader.id, display_name="Synthetic contact", email="capsule@example.org")
    monkeypatch.setattr(indexed_resources, "resource_search", resource_index_query.memory_index_search)
    expected = {}
    for topic, document_count, memory_count in (("thermolunaire", 10, 0), ("nebulotide", 6, 2)):
        uris = set()
        for ordinal in range(document_count):
            item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
                title=f"Rapport {topic} {ordinal}", content=f"<p>Rapport {topic} {ordinal}.</p><p>{'Mesures et observations. ' * 28}</p>")
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
            assert await index_subject(IndexSubject("document", item.id, item.content_hash))
            uris.add(f"document://{item.id}")
        for ordinal in range(memory_count):
            item, _ = await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id, title="Observation",
                payload=MemoryPayload(text=f"Observation {topic} {ordinal}.")))
            uris.add(f"memory://{item.id}")
        expected[topic] = uris

    for topic, documents_expected in (("thermolunaire", 8), ("nebulotide", 6)):
        brief = await build_memory_brief(agent_id=reader.id, contact_item_id=contact.memory_item_id, query=topic)
        selected = {item.resource_uri or f"memory://{item.memory_id}" for item in brief.items}
        assert len(selected) == 8 and selected <= expected[topic]
        assert sum(uri.startswith("document://") for uri in selected) == documents_expected
        prompt = await build_agent_run_context(AgentContextRequest(task_id=None,
            agent=AgentSnapshot(id=reader.id, code="synthetic", first_name="Agent", last_name="Test", driver_code="internal"),
            objective=topic, label="Conversation — synthetic", contact_memory_item_id=contact.memory_item_id))
        assert prompt.metadata["memory_context_count"] == 8
        assert sum(uri in prompt.memory_context for uri in expected[topic] if uri.startswith("document://")) == documents_expected


@pytest.mark.asyncio
async def test_conversation_prefers_relevant_shared_sources_and_checks_the_subject_of_personal_records(
    db, agents, memory_storage, monkeypatch,
):
    owner, reader = agents
    alice = await create_mail_contact(owner_agent_id=reader.id, display_name="Camille Rivage", email="camille.a@example.org")
    bob_account = UserModel(email="camille.b@example.org", display_name="Camille Rivage", hashed_password="synthetic")
    db.add(bob_account)
    await db.flush()
    bob_contact_id = await observe_messenger_contact(MessengerContactObservation(
        owner_agent_id=reader.id, messaging_id="internal", user_id=f"user:{bob_account.id}",
        display_name="Camille Rivage", galaris_user_id=bob_account.id))
    context = ResourceContext(reader.id, "internal", conversation_turn=SimpleNamespace(
        agent_id=reader.id, contact_memory_item_id=alice.memory_item_id, topic_id=None, objective="ma dernière prise de sang"))
    monkeypatch.setattr(indexed_resources, "resource_search", resource_index_query.memory_index_search)

    definitions = {
        "guide": ("Guide étalonnage", "<p>Guide étalonnage des capteurs.</p>", True),
        "own": ("2021-05-15 — Prise de sang", "<p>Prise de sang.</p><p>Patient : camille.a@example.org</p><p>Valeur synthétique ambre.</p>", True),
        "old": ("2020-04-03 — Prise de sang", "<p>Prise de sang.</p><p>Patient : camille.a@example.org</p>", True),
        "other": ("2024-06-05 — Prise de sang", "<p>Prise de sang.</p><p>Patient : camille.b@example.org</p><p>Destinataire : camille.a@example.org</p>", True),
        "unverified": ("2024-06-07 — Prise de sang", "<p>Prise de sang.</p><p>Patient : Camille Rivage</p><p>Destinataire : camille.a@example.org</p>", True),
        "mixed": ("2024-08-07 — Prise de sang", "<p>Prise de sang.</p><p>Patient : camille.a@example.org</p><p>Patient : camille.b@example.org</p>", True),
        "private": ("2024-10-04 — Prise de sang", "<p>Prise de sang.</p><p>Patient : camille.a@example.org</p>", False),
    }
    uris = {}
    for key, (title, html, shared) in definitions.items():
        item = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title=title, content=html)
        if shared:
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))
        uris[key] = f"document://{item.id}"
    await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id, title="Échantillon sans identité",
        payload=MemoryPayload(text="2024-06-12 — Prise de sang, valeur synthétique rubis.")))

    general_query = "Peux-tu me retrouver le guide d’étalonnage des capteurs ?"
    brief = await build_memory_brief(agent_id=reader.id, contact_item_id=alice.memory_item_id, query=general_query)
    assert uris["guide"] in brief.rendered
    unknown = await build_memory_brief(agent_id=reader.id, include_relevant=False, query=general_query)
    assert uris["guide"] in unknown.rendered

    query = "ma dernière prise de sang"
    brief = await build_memory_brief(agent_id=reader.id, contact_item_id=alice.memory_item_id, query=query)
    assert [item.resource_uri for item in brief.items] == [uris["own"], uris["old"]]
    assert "rubis" not in brief.rendered
    monkeypatch.setattr(agent_context, "_providers", dict(agent_context._providers))
    agent_context.register_context_provider("synthetic_prior_reference", lambda _: AgentContextContribution(candidates=(
        AgentContextCandidate(key="synthetic-previous-document", kind="resource", title="Prise de sang",
            reference=uris["other"], excerpt="Recently consulted in the same room.", base_score=1.0),
    )))
    prompt = await build_agent_run_context(AgentContextRequest(task_id=None,
        agent=AgentSnapshot(id=reader.id, code="synthetic", first_name="Agent", last_name="Test", driver_code="internal"),
        objective=query, label="Conversation — synthetic", contact_memory_item_id=alice.memory_item_id))
    assert uris["own"] in prompt.memory_context and "source_date=2021-05-15" in prompt.memory_context
    assert all(uris[key] not in prompt.shared_context for key in ("other", "unverified", "private", "mixed"))
    found = await resource_search(context, "memory://", query, mode="semantic", max_results=1)
    assert [hit.resource.uri for hit in found.hits] == [uris["own"]]
    assert found.next_cursor is not None
    page = await resource_search(context, "memory://", query, mode="semantic", max_results=1, cursor=found.next_cursor)
    assert [hit.resource.uri for hit in page.hits] == [uris["old"]]
    wrong_document = await resource_search(context, uris["other"], query, mode="text")
    assert not wrong_document.hits and wrong_document.relevance_status == "no_sufficient_evidence"
    reformulated = await resource_search(context, "memory://", "prise sang", mode="text")
    assert {hit.resource.uri for hit in reformulated.hits} == {uris["own"], uris["old"]}

    brief = await build_memory_brief(agent_id=reader.id, contact_item_id=bob_contact_id, query=query)
    assert [item.resource_uri for item in brief.items] == [uris["other"]]
    bob_account.is_active = False
    await db.flush()
    revoked_identity = await build_memory_brief(agent_id=reader.id, contact_item_id=bob_contact_id, query=query)
    assert revoked_identity.items == ()
    unknown = await build_memory_brief(agent_id=reader.id, query=query)
    assert unknown.items == ()


@pytest.mark.asyncio
async def test_subject_evidence_upgrade_reuses_analyzed_content(db, agents, memory_storage, monkeypatch):
    owner, _reader = agents
    item = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title="Synthetic report",
        content="<p>Patient : profile@example.org</p><p>Synthetic value.</p>")
    subject = IndexSubject("document", item.id, item.content_hash)
    assert await index_subject(subject)
    source = await resource_index._source(subject)
    content_id = await db.scalar(select(ResourceIndexSource.content_id).where(ResourceIndexSource.source_key == item.id))
    assert source is not None and content_id is not None
    await db.execute(update(ResourceIndexContent).where(ResourceIndexContent.id == content_id)
        .values(analysis_key=source.analysis_key_for(2), analysis_version=2, contact_evidence=[]))
    extract = AsyncMock(side_effect=AssertionError("Existing passages should be reused"))
    monkeypatch.setattr(resource_index, "_extract", extract)
    assert await index_subject(subject)
    upgraded = await db.get(ResourceIndexContent, content_id)
    assert upgraded is not None and upgraded.contact_evidence[0]["role"] == "subject"
    assert await db.scalar(select(ResourceIndexSource.content_id).where(ResourceIndexSource.source_key == item.id)) == content_id
    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_last_week_uses_source_dates_and_keeps_historical_writings_searchable(db, agents, memory_storage):
    owner, reader = agents
    today = datetime.now(ZoneInfo(local_timezone_name())).date()
    monday = today - timedelta(days=today.weekday())
    last_monday = monday - timedelta(days=7)
    last_sunday = monday - timedelta(days=1)
    definitions = {
        "archive": ("Rapport capteurs — rédigé le 15 mai 2021", True),
        "period": ("Bilan capteurs 2021", True),
        "undated": ("Rapport capteurs — prototype", True),
        "start": (f"{last_monday} — Rapport capteurs", True),
        "end": (f"{last_sunday} — Rapport capteurs", True),
        "boundary": (f"{monday} — Rapport capteurs", True),
        "private": (f"{last_sunday} — Rapport capteurs privé", False),
    }
    uris = {}
    for key, (title, shared) in definitions.items():
        item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title=title, content=f"<p>Rapport capteurs. Observations de contrôle {key}.</p>")
        uris[key] = f"document://{item.id}"
        if shared:
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))
    memo_date = last_monday + timedelta(days=2)
    memo, _ = await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id,
        title="Vérification", payload=MemoryPayload(text="Rapport capteurs, vérification."),
        temporal=MemoryTemporalAnchor(year=memo_date.year, month=memo_date.month, day=memo_date.day)))
    await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id,
        title="Rapport capteurs", payload=MemoryPayload(text="Rapport capteurs — rédigé le 3 avril 2021, données anciennes.")))

    actor = ResourceContext(reader.id, "internal")
    for query in ("le truc de la semaine dernière", "rapport capteurs de la semaine dernière"):
        personal = await search_memory_detailed(query, agent_id=reader.id)
        assert [hit.item.id for hit in personal.hits] == [memo.id], (query, personal)
        result = await resource_search(actor, "memory://", query, mode="text")
        assert [hit.resource.uri for hit in result.hits] == [uris["end"], f"memory://{memo.id}", uris["start"]], (
            query, [(hit.resource.name, hit.chronology) for hit in result.hits])
        assert result.hits[0].resource.metadata["chronology"]["source_date"] == last_sunday.isoformat()
        assert result.hits[1].resource.metadata["chronology"]["event_date"] == memo_date.isoformat()
        assert result.date_filter is not None and result.date_filter["end_exclusive"] == monday.isoformat()
    archived = await resource_search(actor, "memory://", "écrits rédigés en 2021 sur les capteurs", mode="text")
    assert [hit.resource.uri for hit in archived.hits if hit.resource.uri.startswith("document://")] == [uris["archive"]]
    period = await resource_search(actor, "memory://", "capteurs sur 2021", mode="text")
    assert [hit.resource.uri for hit in period.hits] == [uris["period"]]
    assert period.hits[0].resource.metadata["chronology"]["covered_year"] == 2021
    recent = await resource_search(actor, "memory://", "rapport capteurs récent", mode="text")
    assert [hit.resource.uri for hit in recent.hits] == [uris["boundary"], uris["end"], uris["start"]]
    paged = await resource_search(actor, "memory://", "le truc de la semaine dernière", mode="text", max_results=1)
    assert paged.next_cursor is not None
    next_page = await resource_search(actor, "memory://", "le truc de la semaine dernière", mode="text",
                                      max_results=2, cursor=paged.next_cursor)
    assert [hit.resource.uri for hit in next_page.hits] == [f"memory://{memo.id}", uris["start"]]
    default = await resource_search(actor, "memory://", "le truc de la semaine dernière")
    assert [hit.resource.uri for hit in default.hits] == [uris["end"], f"memory://{memo.id}", uris["start"]]
    brief = await build_memory_brief(agent_id=reader.id, query="le truc de la semaine dernière")
    assert str(memo.id) in brief.rendered
    assert f"event_date={memo_date.isoformat()}" in brief.rendered


@pytest.mark.asyncio
async def test_business_questions_find_the_field_in_the_exact_authorized_source(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    filler = "Consignes de conditionnement du matériel. " * 100
    definitions = {
        "invoice": ("Facture FCT-714", f"Facture FCT-714. {filler} À régler avant le 14 février. Total TTC : 186,50 €."),
        "body_only": ("Bordereau fournisseur", f"Facture FCT-717. {filler} Échéance contractuelle : 19 mars."),
        "title_only": ("Facture FCT-718", f"{filler[:970]} Total TTC : 75,60 €."),
        "neighbor": ("Facture FCT-7149", "Facture FCT-7149. Échéance contractuelle : 28 avril. Total TTC : 800 €."),
        "suffix": ("Facture FCT-714-2", "Facture FCT-714-2. Échéance : 25 août. Total TTC : 45 €."),
        "subcode": ("Facture FCT-714.2", "Facture FCT-714.2. Échéance : 10 juin. Total TTC : 60 €."),
        "private": ("Facture FCT-714", "Échéance acceptée : IndigoPrive. Total TTC : 4 €."),
        "mention": ("Notes de suivi", "La facture FCT-714 sera envoyée par le fournisseur."),
        "other": ("Facture FCT-715", "Facture FCT-715. Échéance : 22 mai. Total TTC : 19 €."),
    }
    uris = {}
    for key, (title, body) in definitions.items():
        item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title=title, content=f"<p>{body}</p>")
        uris[key] = f"document://{item.id}"
        if key != "private":
            await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        assert await index_subject(IndexSubject("document", item.id, item.content_hash))

    # Deliberately give unrelated passages the same vector as the question.
    model = SimpleNamespace(key="synthetic-business-question-vector",
        embed=AsyncMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts]))
    monkeypatch.setattr(resource_index, "_embedding_model", AsyncMock(return_value=model))
    for content_id in await db.scalars(select(ResourceIndexContent.id)):
        assert await refresh_vectors(content_id, model.key)
    model.embed.reset_mock()

    actor = ResourceContext(reader.id, "internal")
    cases = (
        ("Quelle est l’échéance de la facture FCT-714 ?", "invoice", "14 février"),
        ("When is invoice FCT-714 due?", "invoice", "14 février"),
        ("What is the amount on invoice FCT-714?", "invoice", "186,50 €"),
        ("Quelle est la date limite de paiement pour FCT-717 ?", "body_only", "19 mars"),
        ("Quel est le montant de la facture FCT-718 ?", "title_only", "75,60 €"),
    )
    for query, key, answer in cases:
        for mode in ("text", "semantic"):
            result = await resource_search(actor, "memory://", query, mode=mode)
            assert [hit.resource.uri for hit in result.hits] == [uris[key]]
            assert result.retrieval_mode == "lexical" and not result.degraded
            assert answer in result.hits[0].excerpt
            assert any(answer in part["text"] for part in result.hits[0].passages)
            if key == "body_only":
                assert any("FCT-717" in part["text"] for part in result.hits[0].passages)
            assert "IndigoPrive" not in result.model_dump_json()
        exact = await resource_search(actor, uris[key], query, mode="text")
        assert exact.hits and answer in exact.hits[0].excerpt

    missing = await resource_search(actor, "memory://", "Quel est le montant de la facture FCT-719 ?", mode="semantic")
    assert missing.hits == []
    assert missing.relevance_status == "no_sufficient_evidence"
    wrong_field = await resource_search(actor, "memory://", "What amount is due on invoice FCT-717?", mode="text")
    assert wrong_field.hits == []
    compare = await resource_search(actor, "memory://", "Compare les échéances de FCT-714 et FCT-715", mode="text")
    assert {hit.resource.uri for hit in compare.hits} == {uris["invoice"], uris["other"]}
    model.embed.assert_not_awaited()
    phrase = await resource_search(actor, "memory://", '"échéance FCT-714"', mode="text")
    assert phrase.hits == []


@pytest.mark.asyncio
async def test_business_question_accepts_reference_in_file_name(db, agents, isolated_managed_files):
    owner, reader = agents
    ctx = ResourceContext(owner.id, "internal")
    item = await resource_create(ctx, "file://", b"Total TTC : 142,20 EUR.", name="Facture FCT-140.txt")
    handled = select(ResourceIndexSource.uri).where(ResourceIndexSource.id.is_(None))
    stored = next(subject for subject in await pending_subjects(handled) if subject.kind == "stored")
    assert await index_subject(stored)

    query = "What is the amount on invoice FCT-140?"
    result = await resource_search(ctx, "memory://", query, mode="text")
    assert [hit.resource.uri for hit in result.hits] == [item.uri]
    assert "142,20 EUR" in result.hits[0].excerpt
    assert not (await resource_search(ResourceContext(reader.id, "internal"), "memory://", query, mode="text")).hits


@pytest.mark.asyncio
async def test_revocation_during_hit_hydration_disallows_earlier_evidence(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
        title="Qualification Péridot", content="<p>Le dossier contient peridotsourcier.</p>")
    await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    assert await index_subject(IndexSubject("document", item.id, item.content_hash))
    resolve = resource_index_query._current_document_descriptors

    async def revoke_after_resolving(ctx, sources):
        descriptors = await resolve(ctx, sources)
        await documents.remove_item_grant(item.id, reader.id, actor_agent_id=owner.id)
        return descriptors

    monkeypatch.setattr(resource_index_query, "_current_document_descriptors", revoke_after_resolving)
    result = await resource_index_query.search_resource_index(ResourceContext(reader.id, "internal"), "peridotsourcier", mode="text")
    assert result is None


@pytest.mark.asyncio
async def test_outdated_analysis_returns_to_dream_without_duplicate_source(db, agents, memory_storage):
    owner, _reader = agents
    item = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
        title="Synthetic upgrade", content="<p>Rebuild the reusable analysis for this source.</p>")
    subject = IndexSubject("document", item.id, item.content_hash)
    assert await index_subject(subject)
    await db.execute(update(ResourceIndexContent).values(analysis_version=1, analysis_key="synthetic-initial-analysis"))
    handled = select(ResourceIndexSource.uri).where(ResourceIndexSource.id.is_(None))
    assert next(job for job in await pending_subjects(handled) if job.kind == "document") == subject
    assert await index_subject(subject)
    assert await db.scalar(select(func.count()).select_from(ResourceIndexSource)) == 1
    assert await db.scalar(select(func.count()).select_from(ResourceIndexContent)) == 1
    assert subject not in await pending_subjects(handled)


@pytest.mark.parametrize("seed", [219, 783, 9_219])
def test_order_evidence_is_invariant_under_line_order_and_rejects_conflicts(seed):
    generator = Random(seed)
    for _ in range(80):
        reference = f"QUAL-{generator.randint(1_000, 90_000)}"
        issuer = f"{generator.randint(10**13, 10**14 - 1)}"
        lines = [f"Commande : {reference}", f"SIRET fournisseur : {issuer}", "Pièce préparée."]
        generator.shuffle(lines)
        baseline = "\n".join(["Facture QUAL-F01", *lines])
        parts = list(passages(baseline, page=1))
        evidence = order_evidence(parts, document_kind(parts))
        assert evidence is not None and (evidence.order, evidence.issuer, evidence.role) == (reference, issuer, "invoice")
        for conflicting_field in (f"Commande : {reference}-A", f"SIRET émetteur : {issuer[::-1]}7", "Devis QUAL-D01"):
            parts = list(passages(f"{baseline}\n{conflicting_field}", page=1))
            assert order_evidence(parts, document_kind(parts)) is None


@pytest.mark.parametrize("seed", [37, 1_781])
def test_passage_locators_reconstruct_source_without_a_gap(seed):
    generator = Random(seed)
    alphabet = ("azur", "Élévation", "boussole", "\n", "雪", "É", " ")
    for _ in range(60):
        raw = "début " + " ".join(generator.choices(alphabet, k=generator.randrange(0, 1_700))) + " fin"
        reconstructed = ""
        for part in passages(raw):
            start, end = part.locator["start"], part.locator["end"]
            assert start <= len(reconstructed) < end and end - start <= 1_200
            assert part.text == raw[start:end]
            reconstructed += part.text[len(reconstructed) - start:]
        assert reconstructed == raw


@pytest.mark.asyncio
async def test_conversational_quantity_finds_shared_document_without_the_question_word(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    monkeypatch.setattr(indexed_resources, "resource_search", resource_index_query.memory_index_search)
    ids = []
    for title, body in (
        ("Préparation", "Pour le glacis opalin, prévoir 14 fioles."),
        ("Quantité de glacis opalin", "La quantité de glacis opalin reste à préciser."),
        ("Confidentiel", "Pour le glacis opalin, prévoir 97 fioles."),
        ("Pointage", "Pour le glacis opalin, la visite aura lieu le 2031-05-18."),
    ):
        doc = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title=title, content=f"<p>{body}</p>")
        assert await index_subject(IndexSubject("document", doc.id, doc.content_hash))
        if title != "Confidentiel":
            await documents.set_item_grant(doc.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        ids.append(doc.id)
    await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id, media_type="text/html",
        payload=MemoryPayload(text="<p>La quantité de glacis opalin sera annoncée après la visite.</p>")))
    scope, _ = await memory.create_item(MemoryItemCreate(owner_agent_id=reader.id, media_type="text/html",
        payload=MemoryPayload(text="<p>Pour le glacis opalin, le cuivre est admis, le zinc est exclu.</p>")))
    query = "Quelle quantité pour le glacis opalin ?"
    brief = await build_memory_brief(agent_id=reader.id, query=query, conversational=True)
    assert [item.resource_uri for item in brief.items] == [f"document://{ids[0]}"]
    assert "14 fioles" in brief.rendered
    for scope_query in ("Quel est le périmètre pour le glacis opalin ?",
                        "What did we include or rule out for glacis opalin?"):
        scope_brief = await build_memory_brief(agent_id=reader.id, query=scope_query, conversational=True)
        assert [item.memory_id for item in scope_brief.items] == [str(scope.id)]

    await documents.remove_item_grant(ids[0], reader.id, actor_agent_id=owner.id)
    reopened = await build_memory_brief(agent_id=reader.id, query=query, conversational=True)
    assert "14 fioles" not in reopened.rendered and "97 fioles" not in reopened.rendered
    assert str(ids[3]) not in reopened.rendered


@pytest.mark.asyncio
async def test_contact_question_uses_the_shared_index_and_stops_at_revocation(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    monkeypatch.setattr(indexed_resources, "resource_search", resource_index_query.memory_index_search)
    ids = []
    for body in (
        "Mira Selin est la référente du projet Verrière.",
        "Le chantier Verrière commence lundi. Mira Selin est la référente du projet Quartz.",
        "Lise Doran is the contact for project Verrière.",
    ):
        doc = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title="Compte rendu de l'atelier", content=f"<p>{body}</p>")
        assert await index_subject(IndexSubject("document", doc.id, doc.content_hash))
        ids.append(doc.id)
    for identity in ids[:2]:
        await documents.set_item_grant(identity, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)

    async def selection(query):
        brief = await build_memory_brief(agent_id=reader.id, query=query, conversational=True)
        return {entry.resource_uri for entry in brief.items}

    correct = {f"document://{ids[0]}"}
    assert await selection("Who should I speak to about Verrière?") == correct
    assert not await selection("Give me the other agent's private note about Verrière.")
    assert correct <= await selection("Verrière")
    await documents.remove_item_grant(ids[0], reader.id, actor_agent_id=owner.id)
    assert not await selection("Who should I speak to about Verrière?")


@pytest.mark.asyncio
async def test_language_qualified_index_search_cites_only_the_requested_passage(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    monkeypatch.setattr(indexed_resources, "resource_search", resource_index_query.memory_index_search)
    ids = []
    for body in (
        "The nacre specimens are in the blue vault. Les spécimens de nacre sont dans la salle ocre.",
        "The nacre specimens are in the green cabinet.",
        "Les spécimens de nacre sont dans un tiroir confidentiel.",
    ):
        doc = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title="Inventaire de l'atelier", content=f"<p>{body}</p>")
        assert await index_subject(IndexSubject("document", doc.id, doc.content_hash))
        ids.append(doc.id)
    for identity in ids[:2]:
        await documents.set_item_grant(identity, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)

    async def lookup():
        return await build_memory_brief(agent_id=reader.id, query="Find the French report on nacre.", conversational=True)

    brief = await lookup()
    assert [entry.resource_uri for entry in brief.items] == [f"document://{ids[0]}"]
    assert "salle ocre" in brief.rendered and "blue vault" not in brief.rendered
    await documents.remove_item_grant(ids[0], reader.id, actor_agent_id=owner.id)
    assert not (await lookup()).items

    # Identical indexed bytes under different titles must keep their own scope.
    documents_by_title = {}
    for title in ("Nacre", "Nacre de synthèse"):
        doc = await document_service.create_document(owner_agent_id=owner.id, task_id=None, title=title,
            content="<p>Les échantillons se trouvent dans la vitrine ronde.</p>")
        assert await index_subject(IndexSubject("document", doc.id, doc.content_hash))
        await documents.set_item_grant(doc.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        documents_by_title[title] = doc.id
    brief = await lookup()
    assert [entry.resource_uri for entry in brief.items] == [f"document://{documents_by_title['Nacre']}"]
    assert "vitrine ronde" in brief.rendered


@pytest.mark.asyncio
async def test_indexed_storage_answer_keeps_only_the_requested_objects_location(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    monkeypatch.setattr(indexed_resources, "resource_search", resource_index_query.memory_index_search)
    statement = "Les cristaux sont rangés dans le coffret ambre."
    documents_created = []
    for body in (statement + " Les pigments sont dans le tiroir bleu.",
                 "Les cristaux demandent un contrôle. Les pigments sont dans le casier vert."):
        doc = await document_service.create_document(owner_agent_id=owner.id, task_id=None,
            title="Registre d'atelier", content=f"<p>{body}</p>")
        assert await index_subject(IndexSubject("document", doc.id, doc.content_hash))
        await documents.set_item_grant(doc.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        documents_created.append(doc.id)

    for query in ("Où sont rangés les cristaux ?", "Où sont rangés les cristaux selon la note française ?"):
        brief = await build_memory_brief(agent_id=reader.id, query=query, conversational=True)
        assert [entry.resource_uri for entry in brief.items] == [f"document://{documents_created[0]}"]
        assert statement in brief.rendered and "tiroir bleu" not in brief.rendered
