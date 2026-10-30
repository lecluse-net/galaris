"""Contact-owned candidate retrieval and stale-safe canonical merging for Dream."""

from collections import defaultdict
from collections.abc import AsyncIterator
from difflib import SequenceMatcher
import hashlib
from itertools import combinations

from sqlalchemy import func, select

from app.memory import contact_owner_agent_ids, lock_messenger_contact
from core.database import get_db
from core.params import runtime_settings

from .directory import coordinate_keys, directory, fingerprint, name_key, snapshot, lock_contact_directory
from .discovery_contracts import ContactMergeCandidate
from .models import ContactDiscoveryJob


async def _evidence_counts(agent_id: int) -> dict[str, int]:
    rows = (await get_db().execute(select(ContactDiscoveryJob.contact_item_id, func.count(ContactDiscoveryJob.id)).where(
        ContactDiscoveryJob.agent_id == agent_id, ContactDiscoveryJob.status == "success",
        ContactDiscoveryJob.contact_item_id.is_not(None),
    ).group_by(ContactDiscoveryJob.contact_item_id))).all()
    return {str(identity): int(count) for identity, count in rows}


def _pair_fingerprint(first: str, second: str, first_id: str, second_id: str,
                      threshold: float, evidence: dict[str, int]) -> str:
    sources = sorted((first, second))
    revisions = sorted(((first_id, evidence.get(first_id, 0)), (second_id, evidence.get(second_id, 0))))
    return hashlib.sha256(f"contact-reconcile-v2:{sources}:{revisions}:{threshold}".encode()).hexdigest()


async def _candidate_stream(excluded: frozenset[str]) -> AsyncIterator[ContactMergeCandidate]:
    threshold = runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD
    for agent_id in await contact_owner_agent_ids():
        contacts = await directory(agent_id)
        evidence = await _evidence_counts(agent_id)
        buckets: dict[str, list[int]] = defaultdict(list)
        keys = [set(coordinate_keys(contact)) for contact in contacts]
        names = [" ".join(sorted(name_key(contact.display_name).split())) for contact in contacts]
        fingerprints = [fingerprint(contact) for contact in contacts]
        blocks: list[set[str]] = []
        for index, contact in enumerate(contacts):
            block = {f"name:{word}" for word in set(name_key(contact.display_name).split()) if len(word) >= 2}
            block.update(f"coordinate:{key}" for key in keys[index])
            blocks.append(block)
            for key in block:
                buckets[key].append(index)
        # Stream pairs instead of materializing a quadratic set of homonyms.
        for bucket_key, bucket in sorted(buckets.items()):
            for first, second in combinations(bucket, 2):
                if bucket_key != min(blocks[first] & blocks[second]):
                    continue
                left, right = contacts[first], contacts[second]
                similarity = 1.0 if keys[first] & keys[second] else SequenceMatcher(None, names[first], names[second]).ratio()
                if similarity < threshold:
                    continue
                target, source = sorted((left, right), key=lambda item: (item.created_at, item.memory_item_id))
                key = _pair_fingerprint(fingerprints[first], fingerprints[second], str(left.memory_item_id),
                    str(right.memory_item_id), threshold, evidence)
                if key not in excluded:
                    yield ContactMergeCandidate(agent_id=agent_id,
                        source_contact_item_id=source.memory_item_id, target_contact_item_id=target.memory_item_id,
                        fingerprint=key, similarity=similarity, source=snapshot(source), target=snapshot(target))


async def contact_merge_candidates(excluded: frozenset[str] = frozenset(), *, limit: int = 100) -> list[ContactMergeCandidate]:
    candidates: list[ContactMergeCandidate] = []
    async for candidate in _candidate_stream(excluded):
        candidates.append(candidate)
        if len(candidates) >= max(1, limit):
            break
    return candidates


async def count_contact_merge_candidates(excluded: frozenset[str]) -> int:
    count = 0
    async for _candidate in _candidate_stream(excluded):
        count += 1
    return count


async def contact_merge_evidence(candidate: ContactMergeCandidate) -> list[dict[str, object]]:
    rows = (await get_db().scalars(select(ContactDiscoveryJob).where(
        ContactDiscoveryJob.agent_id == candidate.agent_id,
        ContactDiscoveryJob.contact_item_id.in_((candidate.source_contact_item_id, candidate.target_contact_item_id)),
        ContactDiscoveryJob.status == "success",
    ).order_by(ContactDiscoveryJob.created_at.desc()).limit(10))).all()
    return [{"contact": str(row.contact_item_id), "coordinate": row.coordinate,
             "context": row.context, "source_kind": row.source_kind, "source_ref": row.source_ref} for row in rows]


async def apply_contact_merge(candidate: ContactMergeCandidate) -> bool:
    from .service import merge_contacts

    await lock_contact_directory(candidate.agent_id)
    locked = {identity: await lock_messenger_contact(identity) for identity in sorted(
        (candidate.source_contact_item_id, candidate.target_contact_item_id))}
    source, target = locked[candidate.source_contact_item_id], locked[candidate.target_contact_item_id]
    if source is None or target is None:
        return False
    if (source.owner_agent_id != candidate.agent_id or target.owner_agent_id != candidate.agent_id
            or snapshot(source) != candidate.source or snapshot(target) != candidate.target
            or candidate.similarity < runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD):
        return False
    current_key = _pair_fingerprint(fingerprint(source), fingerprint(target), str(source.memory_item_id),
        str(target.memory_item_id), runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
        await _evidence_counts(candidate.agent_id))
    if current_key != candidate.fingerprint:
        return False
    await merge_contacts(source_contact_item_id=source.memory_item_id, target_contact_item_id=target.memory_item_id)
    return True
