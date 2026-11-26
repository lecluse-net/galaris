"""Bounded encrypted checkpoint chains for text rounds. A single ciphertext is a legacy snapshot."""

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import func, update

from app.agent.contracts import AgentRunCheckpoint, CheckpointIndex
from app.services.facade import canonical_authorization_snapshot
from core.database import get_db_session
from core.util import get_encryption_service
from .models import ConversationRound


_MAX_DELTAS = 31


def read_checkpoint_payload(stored: str) -> dict[str, Any]:
    cipher = get_encryption_service()
    records = stored.split("\n")
    if len(records) > _MAX_DELTAS + 1:
        raise ValueError("Invalid conversation checkpoint chain length.")
    previous = records[0]
    payload = json.loads(cipher.decrypt(previous))
    for record in records[1:]:
        delta = json.loads(cipher.decrypt(record))
        if delta["parent"] != hashlib.sha256(previous.encode()).hexdigest():
            raise ValueError("Conversation checkpoint chain mismatch.")
        next_payload = delta["checkpoint"]
        for name, count in delta["prefixes"].items():
            prior = payload["data"][name]
            if name not in {"message_history", "effects"} or not 0 < count <= len(prior):
                raise ValueError("Invalid conversation checkpoint prefix.")
            next_payload["data"][name] = prior[:count] + next_payload["data"][name]
        payload, previous = next_payload, record
    return payload


def _encode(checkpoint: AgentRunCheckpoint, previous: CheckpointIndex | None, parent: str) -> tuple[str, bool, CheckpointIndex]:
    index = checkpoint.checkpoint_index()
    prefixes = index.unchanged_prefixes(previous)
    if prefixes:
        data = dict(checkpoint.data)
        for name, count in prefixes.items():
            data[name] = data[name][count:]
        value = {"checkpoint": replace(checkpoint, data=data), "prefixes": prefixes,
                 "parent": hashlib.sha256(parent.encode()).hexdigest()}
        plain = canonical_authorization_snapshot(value)
    else:
        plain = canonical_authorization_snapshot(checkpoint)
    return get_encryption_service().encrypt(plain), bool(prefixes), index


class RoundCheckpointWriter:
    def __init__(self, round_id: UUID, lease_token: UUID) -> None:
        self.round_id = round_id
        self.lease_token = lease_token
        self.previous: CheckpointIndex | None = None
        self.last_record = ""
        self.deltas = 0
        self.lock = asyncio.Lock()

    async def save(self, checkpoint: AgentRunCheckpoint) -> None:
        from .service import ConversationLeaseLostError, PROCESSING_ROUND_STATUSES

        if checkpoint.driver_code != "internal" or checkpoint.runtime_run_id != str(self.round_id):
            raise ValueError("The checkpoint belongs to another conversation round.")
        async with self.lock:
            previous = self.previous if self.deltas < _MAX_DELTAS else None
            record, append, index = await asyncio.to_thread(_encode, checkpoint, previous, self.last_record)
            async with get_db_session() as db:
                owned = update(ConversationRound).where(
                    ConversationRound.id == self.round_id, ConversationRound.lease_token == self.lease_token,
                    ConversationRound.status.in_(PROCESSING_ROUND_STATUSES),
                    ConversationRound.lease_expires_at > func.clock_timestamp(),
                ).returning(ConversationRound.id).execution_options(synchronize_session=False)
                if append:
                    # Also fence an independent checkpoint writer on this lease.
                    # Fernet's trailing signature identifies the previously committed record.
                    saved = await db.scalar(owned.where(func.right(ConversationRound.encrypted_checkpoint, 32) ==
                        self.last_record[-32:]).values(encrypted_checkpoint=ConversationRound.encrypted_checkpoint + "\n" + record))
                    if saved is None:
                        record, append, index = await asyncio.to_thread(_encode, checkpoint, None, "")
                if not append and await db.scalar(owned.values(encrypted_checkpoint=record)) is None:
                    raise ConversationLeaseLostError(f"Conversation round lease lost for {self.round_id}")
            self.previous, self.last_record = index, record
            self.deltas = self.deltas + 1 if append else 0
