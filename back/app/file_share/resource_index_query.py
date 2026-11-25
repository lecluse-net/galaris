"""Search current content and resolve links only through live source access."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Date, Float, String, and_, case, cast, column, exists, false, func, literal_column, or_, select, tuple_
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import aliased, load_only, raiseload
from sqlalchemy.sql import Select
from sqlalchemy.sql.selectable import CTE

from app.document import Document, DocumentAttachment, DocumentError, document_index_readable, get_item_metadata
from app.memory import (
    FederatedEvidence, MemoryGraphEdge, MemoryRecallRequest, MemorySearchItem, PersonalRecordKind, ReferenceQuestion,
    SourceChronology, SourceTimeQuery,
    chronology_from_title, federated_candidate_limit, fold_lexical, folded_lexical_sql, indexed_contact_addresses,
    indexed_contact_identities,
    lexical_excerpt, local_source_date, mail_source_date_sql, parse_question_evidence, parse_reference_question,
    parse_source_time_query, personal_record_kind, rank_federated, resource_query_terms, title_dates_sql,
)
from app.task import Task, task_index_readable
from core.database import Vector, get_db
from core.params import runtime_settings
from core.storage import FileAlias, StoredFile
from core.util import visible_text

from .catalogue import catalogue_binding_is_current, descriptor_version, indexed_mail_account
from .models import FileCatalogEntry, ManagedFileOwner, ResourceIndexContent, ResourceIndexLink, ResourceIndexPassage, ResourceIndexSource
from .resource_contracts import ResourceContext, ResourceDescriptor, ResourceSearchHit, ResourceSearchResult
from .resource_index import ANALYSIS_VERSION, embedding_model, indexable_task, task_fingerprint
from .resource_index_content import MAX_PASSAGES
from .resource_observation import suspend_observations
from .resource_uri import parse_resource_uri


def _index_date_candidates(filters: list[ColumnElement[bool]], chronology: SourceTimeQuery) -> CTE:
    document = select(Document.title).where(Document.id == ResourceIndexSource.source_key).correlate(ResourceIndexSource).scalar_subquery()
    stored = select(StoredFile.name).where(StoredFile.id == ResourceIndexSource.source_key).correlate(ResourceIndexSource).scalar_subquery()
    attachment = select(StoredFile.name).join(FileAlias, StoredFile.id == FileAlias.file_id).where(
        FileAlias.id == ResourceIndexSource.source_key).correlate(ResourceIndexSource).scalar_subquery()
    catalogue = select(FileCatalogEntry.descriptor["name"].as_string()).where(
        FileCatalogEntry.id == ResourceIndexSource.source_key).correlate(ResourceIndexSource).scalar_subquery()
    source_name = case({"document": document, "stored": stored, "attachment": attachment, "file": catalogue},
                       value=ResourceIndexSource.source_kind)
    mail_date = select(mail_source_date_sql(FileCatalogEntry.descriptor["modified_at"].as_string())).where(
        FileCatalogEntry.id == ResourceIndexSource.source_key,
        FileCatalogEntry.descriptor["media_type"].as_string() == "text/vnd.galaris.mail",
        FileCatalogEntry.uri.bool_op("~")(r"://(?:mail/)?account/[0-9]+/indexed/[^/]+/[0-9]+/body\.txt$"),
    ).correlate(ResourceIndexSource).scalar_subquery()
    named = (select(ResourceIndexSource.id, source_name.label("name"),
        case((ResourceIndexSource.source_kind == "file", mail_date)).label("mail_date"))
        .join(ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id)
        .where(*filters).cte("chronology_names").prefix_with("MATERIALIZED", dialect="postgresql"))
    written, coverage, mentioned = title_dates_sql(named.c.name)
    matching = chronology.sql_date(written=func.coalesce(named.c.mail_date, written, type_=Date()),
        coverage=coverage, mentioned=mentioned, event=cast(None, Date()))
    return select(named.c.id, matching.label("matched_on")).cte("chronology_dates").prefix_with("MATERIALIZED", dialect="postgresql")


def _indexed_chronology(info: ResourceDescriptor, source_kind: str) -> SourceChronology:
    if (source_kind == "file" and info.media_type == "text/vnd.galaris.mail"
            and indexed_mail_account(parse_resource_uri(info.uri)) is not None):
        try:
            sent = local_source_date(datetime.fromisoformat(info.modified_at)) if info.modified_at else None
        except ValueError:
            sent = None
        return chronology_from_title(info.name, source_date=sent, origin="mail_date")
    return chronology_from_title(info.name)


def _contact_proof(addresses: tuple[str, ...], *, health: bool) -> ColumnElement[bool]:
    evidence = func.jsonb_to_recordset(ResourceIndexContent.contact_evidence).table_valued(
        column("role", String()), column("address", String())).render_derived(name="indexed_subjects", with_types=True)
    subjects = ("subject",) if health else ("subject", "customer")
    matched = exists(select(evidence.c.address).where(evidence.c.role.in_(subjects), evidence.c.address.in_(addresses))
                     .correlate(ResourceIndexContent))
    conflicting = exists(select(evidence.c.address).where(or_(evidence.c.role == "ambiguous",
        and_(evidence.c.role.in_(subjects), or_(evidence.c.address.is_(None), evidence.c.address.not_in(addresses)))))
        .correlate(ResourceIndexContent))
    return and_(ResourceIndexContent.analysis_version >= ANALYSIS_VERSION, matched, ~conflicting)


def _neutral_source() -> ColumnElement[bool]:
    evidence = ResourceIndexContent.contact_evidence
    return and_(ResourceIndexContent.analysis_version >= ANALYSIS_VERSION, ~or_(
        evidence.contains([{"role": "subject"}]), evidence.contains([{"role": "customer"}]),
        evidence.contains([{"role": "ambiguous"}])))


def _distributed_lexical_match(query: str, config: ColumnElement[str]) -> ColumnElement[bool] | None:
    # Phrase, OR and exclusion queries keep their native PostgreSQL semantics.
    if re.search(r'"|\bOR\b|(?:^|\s)-', query, re.IGNORECASE):
        return None
    terms = tuple(dict.fromkeys(re.findall(r"[^\W_]+(?:[-./][^\W_]+)*", fold_lexical(query))))
    if not 2 <= len(terms) <= 6:
        return None
    term_queries = [func.plainto_tsquery(config, term) for term in terms]
    fragment = aliased(ResourceIndexPassage)
    all_terms = [exists(select(fragment.id).where(fragment.content_id == ResourceIndexSource.content_id,
        fragment.search_vector_folded.bool_op("@@")(term_query)).correlate(ResourceIndexSource)) for term_query in term_queries]
    return and_(or_(*(ResourceIndexPassage.search_vector_folded.bool_op("@@")(term_query) for term_query in term_queries)),
                *all_terms)


def _reference_evidence(question: ReferenceQuestion, config: ColumnElement[str]) -> tuple[ColumnElement[bool], Select[tuple[ResourceIndexPassage]]]:
    """Find literal references in source names or any indexed passage of the same content."""
    choices = "|".join(question.references)
    boundary = "[[:alnum:]_/-]"
    pattern = rf"(?<!{boundary})(?:{choices})(?!{boundary}|\.[0-9])"
    by_name = or_(
        and_(ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
            Document.id == ResourceIndexSource.source_key, Document.title.bool_op("~*")(pattern)))),
        and_(ResourceIndexSource.source_kind == "stored", exists(select(StoredFile.id).where(
            StoredFile.id == ResourceIndexSource.source_key, StoredFile.name.bool_op("~*")(pattern)))),
        and_(ResourceIndexSource.source_kind == "attachment", exists(select(FileAlias.id).join(
            StoredFile, StoredFile.id == FileAlias.file_id).where(
                FileAlias.id == ResourceIndexSource.source_key, StoredFile.name.bool_op("~*")(pattern)))),
        and_(ResourceIndexSource.source_kind == "file", exists(select(FileCatalogEntry.id).where(
            FileCatalogEntry.id == ResourceIndexSource.source_key,
            FileCatalogEntry.descriptor["name"].as_string().bool_op("~*")(pattern)))),
    )
    reference_query = func.to_tsquery(config, " | ".join(f"'{ref}'" for ref in question.references))
    anchors = select(ResourceIndexPassage).where(
        ResourceIndexPassage.search_vector_folded.bool_op("@@")(reference_query),
        ResourceIndexPassage.text.bool_op("~*")(pattern)).correlate(None)
    return by_name, anchors


async def readable_sources(ctx: ResourceContext) -> ColumnElement[bool]:
    """Use domain-owned ACL clauses before applying a search candidate limit."""
    readable_documents = exists(select(Document.id).where(Document.id == ResourceIndexSource.source_key,
        Document.deleted_at.is_(None), Document.content_hash == ResourceIndexSource.fingerprint,
        document_index_readable(ctx.agent_id)))
    task_access = await task_index_readable(ctx.agent_id, allow_delegation=not ctx.browser_navigation)
    readable_tasks = exists(select(Task.id).where(Task.id == ResourceIndexSource.source_key,
        indexable_task(),
        task_fingerprint() == ResourceIndexSource.fingerprint, task_access))
    readable_files = exists(select(FileCatalogEntry.id).where(FileCatalogEntry.id == ResourceIndexSource.source_key,
        FileCatalogEntry.agent_id == ctx.agent_id, FileCatalogEntry.present.is_(True),
        FileCatalogEntry.uri == ResourceIndexSource.uri,
        FileCatalogEntry.source_version == ResourceIndexSource.fingerprint, catalogue_binding_is_current()))
    readable_stored = exists(select(StoredFile.id).join(ManagedFileOwner, ManagedFileOwner.file_id == StoredFile.id)
        .where(StoredFile.id == ResourceIndexSource.source_key, StoredFile.deleted_at.is_(None),
               StoredFile.sha256 == ResourceIndexSource.fingerprint, ManagedFileOwner.agent_id == ctx.agent_id))
    readable_attachments = exists(select(FileAlias.id).join(StoredFile, FileAlias.file_id == StoredFile.id)
        .join(DocumentAttachment, FileAlias.uri == func.concat("document://", DocumentAttachment.document_id,
                                                          "/attachments/", DocumentAttachment.id))
        .join(Document, Document.id == DocumentAttachment.document_id).where(FileAlias.id == ResourceIndexSource.source_key,
            DocumentAttachment.active.is_(True), Document.deleted_at.is_(None), document_index_readable(ctx.agent_id),
            StoredFile.deleted_at.is_(None), StoredFile.sha256 == ResourceIndexSource.fingerprint))
    return or_(and_(ResourceIndexSource.source_kind == "document", readable_documents),
               and_(ResourceIndexSource.source_kind == "task", readable_tasks),
               and_(ResourceIndexSource.source_kind == "file", readable_files),
               and_(ResourceIndexSource.source_kind == "stored", readable_stored),
               and_(ResourceIndexSource.source_kind == "attachment", readable_attachments))


async def _current_descriptor(ctx: ResourceContext, source: ResourceIndexSource) -> ResourceDescriptor | None:
    from .resource_service import resource_info

    try:
        with suspend_observations():
            if source.source_kind == "document" and source.uri.startswith("document://"):
                item, _access = await get_item_metadata(source.source_key, agent_id=ctx.agent_id)
                return _document_descriptor(source, item)
            info = await resource_info(ctx, source.uri)
        if source.source_kind == "file":
            if descriptor_version(info.model_dump()) != source.fingerprint:
                return None
            summary = await get_db().scalar(select(FileCatalogEntry.enrichment_text).where(
                FileCatalogEntry.id == source.source_key, FileCatalogEntry.enrichment_version == source.fingerprint))
            if summary:
                info.metadata["summary"] = summary
            return info
        current = await get_db().scalar(select(ResourceIndexSource.id).where(ResourceIndexSource.id == source.id,
            await readable_sources(ctx)))
        return info if current is not None else None
    except (DocumentError, FileNotFoundError, PermissionError, ValueError, OSError):
        return None


def _document_descriptor(source: ResourceIndexSource, item: Document) -> ResourceDescriptor | None:
    if item.content_hash != source.fingerprint:
        return None
    summary = item.summary_content or ""
    return ResourceDescriptor(uri=source.uri, name=item.title, media_type=item.media_type,
        size=item.size_bytes, revision=item.revision, checksum=item.content_hash, capabilities=["info", "read"],
        metadata={"topic_id": str(item.topic_id) if item.topic_id else None, "keywords": item.keywords,
                  "summary": visible_text(summary) if item.summary_media_type == "text/html" else summary,
                  "summary_generated": item.summary_generated})


async def _current_document_descriptors(ctx: ResourceContext,
                                        sources: dict[UUID, ResourceIndexSource]) -> dict[UUID, ResourceDescriptor | None]:
    if not sources:
        return {}
    documents = await get_db().scalars(select(Document).where(Document.id.in_(sources), document_index_readable(ctx.agent_id))
        .options(load_only(Document.id, Document.content_hash, Document.title, Document.media_type, Document.size_bytes,
            Document.revision, Document.topic_id, Document.keywords, Document.summary_content, Document.summary_media_type,
            Document.summary_generated, raiseload=True), raiseload("*"))
        .execution_options(populate_existing=True))
    result: dict[UUID, ResourceDescriptor | None] = {source.id: None for source in sources.values()}
    for item in documents:
        source = sources[item.id]
        result[source.id] = _document_descriptor(source, item)
    return result


async def _admitted_snapshots(ctx: ResourceContext, sources: list[ResourceIndexSource]) -> set[UUID]:
    if not sources:
        return set()
    snapshots = [(source.id, source.fingerprint, source.content_id) for source in sources]
    current = await get_db().scalars(select(ResourceIndexSource.id).where(await readable_sources(ctx),
        tuple_(ResourceIndexSource.id, ResourceIndexSource.fingerprint, ResourceIndexSource.content_id).in_(snapshots)))
    return set(current)


async def related_index_sources(ctx: ResourceContext, uri: str, *, limit: int = 20) -> list[dict[str, object]]:
    db = get_db()
    allowed = await readable_sources(ctx)
    origins = list(await db.scalars(select(ResourceIndexSource).where(ResourceIndexSource.uri == uri, allowed)))
    live_origins = [source for source in origins if await _current_descriptor(ctx, source) is not None]
    if not live_origins:
        return []
    visible_origins = {source.id for source in live_origins}
    edges = await db.execute(select(ResourceIndexLink, ResourceIndexSource).join(ResourceIndexSource,
        or_(and_(ResourceIndexLink.source_id.in_(visible_origins), ResourceIndexLink.target_id == ResourceIndexSource.id),
            and_(ResourceIndexLink.target_id.in_(visible_origins), ResourceIndexLink.source_id == ResourceIndexSource.id)))
        .where(allowed).order_by(ResourceIndexLink.id).limit(limit * 3))
    result: dict[str, tuple[UUID, ResourceIndexSource, dict[str, object]]] = {}
    for edge, target in edges:
        if target.uri == uri or target.uri in result:
            continue
        info = await _current_descriptor(ctx, target)
        if info is not None:
            origin = edge.target_id if edge.source_id == target.id else edge.source_id
            result[target.uri] = (origin, target, {"uri": target.uri, "name": info.name, "relation": edge.relation,
                                                 "state": edge.state, "evidence": edge.evidence})
        if len(result) >= limit:
            break
    admitted = await _admitted_snapshots(ctx, [*live_origins, *(target for _origin, target, _detail in result.values())])
    return [detail for origin, target, detail in result.values() if origin in admitted and target.id in admitted]


async def index_details(ctx: ResourceContext, uri: str) -> dict[str, object]:
    if not await get_db().scalar(select(ResourceIndexSource.id).where(ResourceIndexSource.uri == uri).limit(1)):
        return {}
    row = (await get_db().execute(select(ResourceIndexSource, ResourceIndexContent)
        .join(ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id)
        .where(ResourceIndexSource.uri == uri, await readable_sources(ctx)).limit(1))).one_or_none()
    if row is None:
        return {}
    source, content = row
    info = await _current_descriptor(ctx, source)
    if info is None:
        return {}
    addresses = {address for item in content.contact_evidence if isinstance(address := item.get("address"), str)}
    identities = await indexed_contact_identities(ctx.agent_id, addresses) if addresses else {}
    contacts = [{"role": item["role"], "contact_id": str(identities[address]), "locator": item["locator"]}
        for item in content.contact_evidence if (address := str(item["address"])) in identities]
    related = await related_index_sources(ctx, uri)
    if source.id not in await _admitted_snapshots(ctx, [source]):
        return {}
    return {"keywords": info.metadata.get("keywords") or content.generated_keywords,
            "summary": info.metadata.get("summary") or content.generated_summary,
            "topic_id": info.metadata.get("topic_id") or (str(source.topic_id) if source.topic_id else None),
            "document_kind": content.document_kind, "contacts": contacts,
            "chronology": _indexed_chronology(info, source.source_kind).metadata(),
            "related_sources": related}


async def search_resource_index(
    ctx: ResourceContext, query: str, *, mode: Literal["text", "semantic"], uri: str | None = None,
    limit: int = 10, source_kinds: tuple[str, ...] = (), topic: UUID | None = None, keyword: str | None = None,
    contact_item_id: UUID | None = None, strict_contact_scope: bool = False,
    contextual_resources: bool = False,
    subject_kind: PersonalRecordKind | None = None,
) -> ResourceSearchResult | None:
    """Return a bounded set of current authorized passages, with lexical fallback."""
    query = query.strip()
    if not 1 <= len(query) <= 8_000:
        raise ValueError("Indexed resource search requires a query of 1 to 8000 characters")
    db = get_db()
    recent = select(ResourceIndexSource.id)
    exact: ResourceIndexSource | None = None
    if uri is not None:
        recent = recent.where(ResourceIndexSource.uri == uri)
    if not await db.scalar(recent.limit(1)):
        return None
    allowed = await readable_sources(ctx)
    filters = [allowed]
    addresses = await indexed_contact_addresses(ctx.agent_id, contact_item_id) if contact_item_id is not None else ()
    if strict_contact_scope and not addresses:
        return None
    personal = subject_kind or personal_record_kind(query)
    contact_match = _contact_proof(addresses, health=personal == "health") if addresses else false()
    if strict_contact_scope:
        filters.append(contact_match)
    elif contextual_resources:
        filters.append(or_(contact_match, _neutral_source()))
    if uri is not None:
        filters.append(ResourceIndexSource.uri == uri)
        sources = await db.scalars(select(ResourceIndexSource).join(
            ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id).where(*filters))
        for source in sources:
            if await _current_descriptor(ctx, source) is not None:
                exact = source
                break
        else:
            return None
    if source_kinds:
        filters.append(ResourceIndexSource.source_kind.in_(source_kinds))
    if topic is not None:
        filters.append(or_(and_(ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
            Document.id == ResourceIndexSource.source_key, Document.topic_id == topic))),
            and_(ResourceIndexSource.source_kind == "task", exists(select(Task.id).where(
                Task.id == ResourceIndexSource.source_key, Task.topic_id == topic))),
            and_(ResourceIndexSource.source_kind.not_in(("document", "task")), ResourceIndexSource.topic_id == topic)))
    if keyword:
        filters.append(or_(ResourceIndexContent.generated_keywords.contains([keyword]),
            and_(ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
                Document.id == ResourceIndexSource.source_key, Document.keywords.contains([keyword]))))))
    config = literal_column("'simple'::regconfig", type_=String())
    question = parse_reference_question(query)
    chronology = parse_source_time_query(query)
    lookup = chronology.query if chronology is not None else query
    if chronology is None and (contextual_resources or personal is not None):
        lookup = resource_query_terms(query)
        if not lookup and question is None:
            return None
    ts_query = func.websearch_to_tsquery(config, fold_lexical(lookup))
    lexical = ResourceIndexPassage.search_vector_folded.bool_op("@@")(ts_query)
    rank = func.ts_rank_cd(ResourceIndexPassage.search_vector_folded, ts_query, 32)
    phrase = func.phraseto_tsquery(config, fold_lexical(lookup))

    def folded_vector(trusted_expression: str) -> ColumnElement[str]:
        return func.to_tsvector(config, literal_column(folded_lexical_sql(trusted_expression), type_=String()))

    title = folded_vector("documents.title")
    title_match = and_(ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
        Document.id == ResourceIndexSource.source_key, title.bool_op("@@")(phrase))))
    summary_match = folded_vector("concat_ws(' ', resource_index_contents.generated_summary, "
                                  "resource_index_contents.generated_keywords::text)").bool_op("@@")(ts_query)
    document_match = and_(ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
        Document.id == ResourceIndexSource.source_key, or_(
            Document.search_vector.bool_op("@@")(func.websearch_to_tsquery(config, lookup)), title.bool_op("@@")(ts_query),
            folded_vector("coalesce(documents.summary_content, '')").bool_op("@@")(ts_query)))))
    metadata_match = and_(or_(ResourceIndexPassage.position == 0, ResourceIndexPassage.id.is_(None)),
                          or_(summary_match, document_match))
    passage_match = lexical
    anchors: Select[tuple[ResourceIndexPassage]] | None = None
    if question is not None:
        title_match, anchors = _reference_evidence(question, config)
        filters.append(or_(title_match, ResourceIndexSource.content_id.in_(anchors.with_only_columns(ResourceIndexPassage.content_id))))
        fields = func.to_tsquery(config, " | ".join(f"({' <-> '.join(field.split())})" for field in question.fields))
        passage_match = ResourceIndexPassage.search_vector_folded.bool_op("@@")(fields)
        rank = func.ts_rank_cd(ResourceIndexPassage.search_vector_folded, fields, 32)
        metadata_match = false()
    else:
        distributed = _distributed_lexical_match(lookup, config)
        if distributed is not None:
            passage_match = or_(lexical, distributed)
            rank = rank + case((distributed, 0.025), else_=0.0)
        # Conversational prose often adds an unmatched verb or noun to an
        # otherwise precise description. Require a majority in one passage.
        # Literal identifiers, quoted queries and personal records stay exact.
        words = lookup.split()
        if (contextual_resources and chronology is None and personal is None
                and 4 <= len(words) <= 18 and all(word.isalpha() for word in words)
                and not re.search(r'\bOR\b', lookup, re.I)):
            vector = ResourceIndexPassage.search_vector_folded
            matched = [case((vector.bool_op("@@")(func.plainto_tsquery(config, word)), 1), else_=0)
                       for word in words]
            count = sum(matched[1:], matched[0])
            any_term = func.to_tsquery(config, " | ".join(words))
            partial = and_(vector.bool_op("@@")(any_term), count >= max(3, len(words) // 2 + 1))
            passage_match = or_(passage_match, partial)
            rank = rank + case((partial, 0.04 * count / len(words)), else_=0.0)
    date_order: ColumnElement[date] = cast(None, Date())
    dated_candidates = None
    if chronology is not None:
        dated_candidates = _index_date_candidates(filters, chronology)
        date_order = cast(dated_candidates.c.matched_on, Date())
        filters = [date_order.is_not(None)]
        if not lookup:
            passage_match = ResourceIndexPassage.position == 0
            metadata_match = ResourceIndexPassage.id.is_(None)
            rank = case((passage_match, 1.0), else_=0.0)
            title_match = false()
    hybrid = False
    if mode == "semantic" and question is None and chronology is None:
        try:
            model = await embedding_model()
            has_embeddings = (model is not None and await db.scalar(select(ResourceIndexSource.id)
                .join(ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id).where(
                    *filters, ResourceIndexContent.embedding_model_key == model.key).limit(1)) is not None)
            if model is not None and has_embeddings:
                vector = (await model.embed([query]))[0]
                if not any(vector):
                    raise ValueError("Empty query embedding")
                compatible = and_(ResourceIndexContent.embedding_model_key == model.key,
                    ResourceIndexPassage.embedding.is_not(None), func.vector_dims(ResourceIndexPassage.embedding) == len(vector))
                distance = cast(ResourceIndexPassage.embedding.op("<=>")(cast(vector, Vector())), Float())
                cosine = case((compatible, 1.0 - distance), else_=0.0)
                passage_match = or_(passage_match, cosine >= 0.5)
                rank = rank + func.greatest(0.0, cosine) * 0.6
                hybrid = True
        except (ValueError, RuntimeError, OSError, IndexError):
            pass
    detail = (parse_question_evidence(query)
              if contextual_resources and uri is None and mode == "text" and question is None
              and chronology is None and personal is None else None)
    ordinary_match = or_(passage_match, metadata_match)
    candidate_match = ordinary_match
    topic_only = false()
    if detail is not None and (topic_words := detail.topic_prefix_query):
        # A passage can answer "how many" without containing those words.
        # Keep the ordinary matches and verify any added passage before emission.
        topic_tsquery = func.to_tsquery(config, topic_words)
        topic_match = ResourceIndexPassage.search_vector_folded.bool_op("@@")(topic_tsquery)
        if detail.source_language is not None:
            topic_match = or_(topic_match, and_(ResourceIndexPassage.position == 0,
                ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
                    Document.id == ResourceIndexSource.source_key, title.bool_op("@@")(topic_tsquery)))))
        candidate_match = or_(ordinary_match, topic_match)
        topic_only = ordinary_match.is_not(True)
    score_expr = (func.coalesce(rank, 0.0) + case((metadata_match, 0.05), else_=0.0)
                  + case((title_match, 2.0), else_=0.0))
    candidate_query = (select(ResourceIndexSource.id.label("source"), ResourceIndexPassage.id.label("passage"),
        score_expr.label("score"), date_order.label("evidence_date"), contact_match.label("contact_match"),
        passage_match.label("matched_passage"), topic_only.label("topic_only"), func.row_number().over(
            partition_by=ResourceIndexSource.uri, order_by=(score_expr.desc(), ResourceIndexSource.id,
            ResourceIndexPassage.position)).label("passage_rank"))
        .join(ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id)
        .outerjoin(ResourceIndexPassage, ResourceIndexPassage.content_id == ResourceIndexContent.id)
        .where(*filters, candidate_match))
    if dated_candidates is not None:
        candidate_query = candidate_query.join(dated_candidates, dated_candidates.c.id == ResourceIndexSource.id)
    candidates = candidate_query.subquery()
    priority = (candidates.c.contact_match.desc(), candidates.c.evidence_date.desc().nullslast(),
                candidates.c.score.desc()) if chronology is not None else (
                    candidates.c.score.desc(), candidates.c.contact_match.desc())
    rows = (await db.execute(select(ResourceIndexSource, ResourceIndexPassage, ResourceIndexContent,
        candidates.c.score, candidates.c.matched_passage, candidates.c.contact_match, candidates.c.topic_only).select_from(candidates)
        .join(ResourceIndexSource, ResourceIndexSource.id == candidates.c.source)
        .join(ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id)
        .outerjoin(ResourceIndexPassage, ResourceIndexPassage.id == candidates.c.passage)
        .where(candidates.c.passage_rank <= 3).order_by(*priority, candidates.c.source, candidates.c.passage_rank)
        .options(load_only(ResourceIndexPassage.id, ResourceIndexPassage.position, ResourceIndexPassage.locator,
            ResourceIndexPassage.text, raiseload=True), load_only(ResourceIndexContent.id, ResourceIndexContent.document_kind,
            ResourceIndexContent.generated_keywords, ResourceIndexContent.generated_summary, raiseload=True))
        .limit(min(1_500, max(24, limit * 9))))).all()
    hits: dict[str, ResourceSearchHit] = {}
    matched_sources: dict[str, ResourceIndexSource] = {}
    excerpt_query = " ".join(question.fields) if question is not None else lookup
    checked: dict[UUID, ResourceDescriptor | None] = await _current_document_descriptors(ctx, {source.source_key: source for source, *_ in rows
        if source.source_kind == "document" and source.uri.startswith("document://")}) if uri is None else {}
    # Two source documents may share indexed bytes and have different titles.
    proof_excerpts: dict[tuple[UUID, UUID], str] = {}
    storage_matches: set[tuple[UUID, UUID]] = set()
    if detail is not None and detail.topic_prefix_query:
        for source, passage, *_ in rows:
            if passage is None:
                continue
            excerpt = lexical_excerpt(passage.text, excerpt_query)
            if detail.source_language is not None or detail.storage is not None:
                descriptor = checked.get(source.id)
                proof = detail.answer_passage(descriptor.name if descriptor else "", excerpt)
                if proof and detail.storage is not None:
                    storage_matches.add((source.id, passage.id))
                if not proof and detail.source_language is not None:
                    proof = detail.source_language.passage(descriptor.name if descriptor else "", excerpt)
            else:
                proof = excerpt if detail.supports("", excerpt) else ""
            if proof:
                proof_excerpts[source.id, passage.id] = proof
        # Apply the response limit after promoting passages that supply the fact.
        rows = sorted(rows, key=lambda row: (
            row[1] is None or (row[0].id, row[1].id) not in storage_matches,
            row[1] is None or (row[0].id, row[1].id) not in proof_excerpts))
    for source, passage, content, score, matched_passage, matched_contact, only_topic in rows:
        proof = proof_excerpts.get((source.id, passage.id)) if passage is not None else None
        if only_topic and not proof:
            continue
        matched_passage = matched_passage or bool(proof)
        if source.uri not in hits:
            if len(hits) >= limit:
                continue
            if source.id not in checked:
                checked[source.id] = await _current_descriptor(ctx, source)
            if (info := checked[source.id]) is None:
                continue
            dated = _indexed_chronology(info, source.source_kind)
            if chronology is not None and chronology.rank_date(dated) is None:
                continue
            info.metadata = {**info.metadata, "index_source": str(source.id), "index_kind": source.source_kind,
                "document_kind": content.document_kind,
                "chronology": dated.metadata(),
                "keywords": info.metadata.get("keywords") or content.generated_keywords,
                "summary": info.metadata.get("summary") or content.generated_summary,
                "topic_id": info.metadata.get("topic_id") or (str(source.topic_id) if source.topic_id else None)}
            excerpt = passage.text if matched_passage and passage is not None else str(info.metadata.get("summary") or info.name)
            excerpt = proof or lexical_excerpt(excerpt, excerpt_query)
            hits[source.uri] = ResourceSearchHit(resource=info, score=float(score), excerpt=excerpt, chronology=dated,
                contact_match=bool(matched_contact),
                source_refs=[source.uri], retrieval_sources=["resource-index"])
            matched_sources[source.uri] = source
        hit = hits[source.uri]
        if (matched_sources[source.uri].id == source.id and matched_passage and passage is not None and len(hit.passages) < 3
                and not any(item["position"] == passage.position for item in hit.passages)):
            hit.passages.append({"position": passage.position, **passage.locator, "text": passage.text})
    if question is not None and anchors is not None:
        pending = {key: matched_sources[key].content_id for key, hit in hits.items()
            if not question.matches_reference(hit.resource.name)
            and not any(question.matches_reference(str(part["text"])) for part in hit.passages)}
        if pending:
            # Preserve both the answer and the citation tying it to the requested reference.
            anchor_rows = await db.scalars(anchors.where(ResourceIndexPassage.content_id.in_(set(pending.values())))
                .distinct(ResourceIndexPassage.content_id).order_by(ResourceIndexPassage.content_id, ResourceIndexPassage.position)
                .options(load_only(ResourceIndexPassage.id, ResourceIndexPassage.position, ResourceIndexPassage.content_id,
                    ResourceIndexPassage.locator, ResourceIndexPassage.text, raiseload=True)))
            by_content = {item.content_id: item for item in anchor_rows}
            for key, content_id in pending.items():
                if (anchor := by_content.get(content_id)) is None:
                    hits.pop(key)
                    matched_sources.pop(key)
                else:
                    hit = hits[key]
                    hit.passages = [*hit.passages[:2], {"position": anchor.position, **anchor.locator, "text": anchor.text}]
    admitted = await _admitted_snapshots(ctx, list(matched_sources.values()))
    if ((strict_contact_scope or contextual_resources) and contact_item_id is not None and addresses
            and addresses != await indexed_contact_addresses(ctx.agent_id, contact_item_id)):
        admitted.clear()
    hits = {key: hit for key, hit in hits.items() if matched_sources[key].id in admitted}
    if not hits and uri is None:
        return None
    coverage: dict[str, object] | None = None
    if exact is not None:
        if await _current_descriptor(ctx, exact) is None:
            return None
        count = int(await db.scalar(select(func.count()).select_from(ResourceIndexPassage)
            .where(ResourceIndexPassage.content_id == exact.content_id)) or 0)
        coverage = {"indexed_passages": count, "possible_extraction_truncation": count >= MAX_PASSAGES,
            "exhaustive": False, "offset_unit": "character",
            "selected_passages": sum(len(hit.passages) for hit in hits.values())}
    degraded = mode == "semantic" and not hybrid and question is None and chronology is None
    return ResourceSearchResult(uri=uri or "memory://", query=query, mode=mode, hits=list(hits.values()),
        retrieval_mode="hybrid" if hybrid else "lexical", degraded=degraded,
        degradation_reason="No compatible indexed vectors are available" if degraded else None, index_coverage=coverage,
        date_filter=chronology.metadata() if chronology is not None else None,
        candidate_window_exhausted=uri is None and limit >= 500 and len(hits) >= limit,
        relevance_status="matched" if hits else "no_sufficient_evidence")


async def merge_memory_resource_hits(ctx: ResourceContext, result: ResourceSearchResult, *, offset: int, limit: int,
                                     contact_item_id: UUID | None = None,
                                     subject_kind: PersonalRecordKind | None = None) -> ResourceSearchResult:
    bound = federated_candidate_limit(offset, limit)
    personal = subject_kind or personal_record_kind(result.query)
    indexed = await search_resource_index(ctx, result.query, mode="semantic" if result.mode == "semantic" else "text",
        limit=min(500, bound + 1), contact_item_id=contact_item_id, strict_contact_scope=personal is not None,
        subject_kind=personal)
    resources = indexed.hits[:bound] if indexed is not None else []
    memories = result.hits
    question = parse_reference_question(result.query)
    chronology = parse_source_time_query(result.query)
    ranked = (rank_federated(result.query, memories, resources, _federated_evidence, chronology=chronology)
              if resources or question or chronology else memories)
    hits = ranked[offset:offset + limit]
    next_offset = offset + len(hits)
    remaining_candidates = result.truncated or (indexed is not None and len(indexed.hits) > bound)
    more = next_offset < len(ranked) or (remaining_candidates and bool(hits) and next_offset < 500)
    updates: dict[str, object] = {"hits": hits, "truncated": more, "next_cursor": f"index:{next_offset}" if more else None}
    if resources:
        updates.update({"relevance_status": "matched" if hits else "no_sufficient_evidence", "evidence_status": "unassessed",
                        "ranking_version": "federated-evidence/v2"})
    if question is not None:
        updates.update({"relevance_status": "matched" if hits else "no_sufficient_evidence",
                        "evidence_status": "unassessed" if hits else "no_evidence"})
        if resources and all("resource-index" in hit.retrieval_sources for hit in hits):
            updates.update({"retrieval_mode": "lexical", "degraded": False, "degradation_reason": None})
    if chronology is not None:
        updates.update({"relevance_status": "matched" if hits else "no_sufficient_evidence",
                        "evidence_status": "unassessed" if hits else "no_evidence",
                        "date_filter": chronology.metadata(),
                        "retrieval_mode": "lexical", "ranking_version": "source-date/v1"})
    if personal and not hits:
        updates.update({"relevance_status": "no_sufficient_evidence", "evidence_status": "no_evidence"})
    if indexed is not None and indexed.candidate_window_exhausted:
        updates["candidate_window_exhausted"] = True
    if indexed is not None and indexed.retrieval_mode == "hybrid":
        updates["retrieval_mode"] = "hybrid"
        if not memories:
            updates.update({"degraded": indexed.degraded, "degradation_reason": indexed.degradation_reason})
    return result.model_copy(update=updates)


def _federated_evidence(hit: ResourceSearchHit) -> FederatedEvidence:
    info = hit.resource
    identity = info.uri
    if info.metadata.get("catalogue_ref") and not info.metadata.get("catalogue_manual_content"):
        refs = {ref for ref in hit.source_refs if "://" in ref and not ref.startswith("memory://")}
        if len(refs) == 1:
            identity = next(iter(refs))
    passages = tuple(text for part in hit.passages if isinstance(text := part.get("text", part.get("excerpt")), str))
    kind = info.metadata.get("document_kind")
    return FederatedEvidence(identity=identity, title=info.name, excerpt=hit.excerpt,
        passages=passages, document_kind=kind if isinstance(kind, str) else None,
        source_document=info.uri.startswith(("document://", "data://", "file://")) or isinstance(kind, str),
        chronology=hit.chronology, contact_match=hit.contact_match)


async def memory_index_search(request: MemoryRecallRequest, *, mode: Literal["text", "semantic"] = "semantic") -> list[MemorySearchItem]:
    if request.target_at is not None or request.memory_role:
        return []
    names = {"document": "document", "file": "file", "task": "task", "stored": "file", "attachment": "attachment"}
    kinds = tuple(kind for kind, name in names.items() if not request.node_kinds or name in request.node_kinds)
    if not kinds:
        return []
    from app.memory import MemoryItem
    topic_node = request.filter_topic_item_id or request.topic_item_id
    topic = await get_db().scalar(select(MemoryItem.topic_id).where(MemoryItem.id == topic_node)) if topic_node else None
    if topic_node is not None and topic is None:
        return []
    actor = ResourceContext(request.agent_id, "internal", task_id=request.task_id)
    query = request.query
    if (mode == "semantic" and personal_record_kind(query) is None
            and parse_reference_question(query) is None and parse_source_time_query(query) is None):
        query = request.semantic_query or query
    indexed = await search_resource_index(actor, query, mode=mode,
        source_kinds=kinds, limit=request.limit or runtime_settings.MEMORY_CONTEXT_MAX_ITEMS, topic=topic, keyword=request.keyword,
        contact_item_id=request.filter_contact_item_id or request.contact_item_id,
        strict_contact_scope=request.strict_contact_scope or request.require_personal_subject or request.filter_contact_item_id is not None
            or personal_record_kind(request.query) is not None,
        contextual_resources=request.contextual_resources)
    if indexed is None:
        return []
    return [MemorySearchItem(id=UUID(str(hit.resource.metadata["index_source"])), title=hit.resource.name,
        excerpt=hit.excerpt, uri=hit.resource.uri, source_refs=tuple(hit.source_refs),
        revision=hit.resource.revision, node_kind=names[str(hit.resource.metadata["index_kind"])],
        chronology=hit.chronology, contact_match=hit.contact_match) for hit in indexed.hits]


async def memory_index_graph(agent_id: int, seen: set[UUID], focus: UUID | None, limit: int) -> list[MemoryGraphEdge]:
    db = get_db()
    if await db.scalar(select(ResourceIndexLink.id).limit(1)) is None:
        return []
    actor = ResourceContext(agent_id, "internal", browser_navigation=True)
    file_node = select(FileCatalogEntry.memory_node_id).where(FileCatalogEntry.id == ResourceIndexSource.source_key
        ).correlate(ResourceIndexSource).scalar_subquery()
    attachment_node = select(DocumentAttachment.memory_item_id).join(FileAlias, FileAlias.uri == func.concat(
        "document://", DocumentAttachment.document_id, "/attachments/", DocumentAttachment.id)
    ).where(FileAlias.id == ResourceIndexSource.source_key).correlate(ResourceIndexSource).scalar_subquery()
    visible = select(ResourceIndexSource.id, case((ResourceIndexSource.source_kind == "document", ResourceIndexSource.source_key),
        (ResourceIndexSource.source_kind == "file", file_node), (ResourceIndexSource.source_kind == "attachment", attachment_node),
        else_=None).label("node")).where(
            await readable_sources(actor)).cte("graph_index_sources")
    left, right = visible.alias(), visible.alias()
    other_source = aliased(ResourceIndexSource)
    vertices = set(seen)
    if focus is not None:
        vertices.add(focus)
    neighbors = (or_(left.c.node == focus, right.c.node == focus) if focus is not None
                 else or_(left.c.node.in_(vertices), right.c.node.in_(vertices)))
    rows = await db.execute(select(ResourceIndexLink.id, left.c.node, right.c.node, ResourceIndexSource, other_source)
        .select_from(ResourceIndexLink).join(left, ResourceIndexLink.source_id == left.c.id)
        .join(right, ResourceIndexLink.target_id == right.c.id).join(ResourceIndexSource, ResourceIndexSource.id == left.c.id)
        .join(other_source, other_source.id == right.c.id).where(neighbors,
            left.c.node != right.c.node, ResourceIndexLink.state == "confirmed").order_by(ResourceIndexLink.id).limit(limit))
    checked: dict[UUID, bool] = {}
    result: list[MemoryGraphEdge] = []
    for link, left_node, right_node, source, target in rows:
        for endpoint in (source, target):
            if endpoint.id not in checked:
                checked[endpoint.id] = await _current_descriptor(actor, endpoint) is not None
        if checked[source.id] and checked[target.id]:
            result.append(MemoryGraphEdge(id=link, source_item_id=left_node, target_item_id=right_node,
                relation_type="same_order", confidence=1.0, suggested=False))
    return result
