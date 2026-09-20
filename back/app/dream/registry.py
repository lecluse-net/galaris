"""Ordered registry of Dream mechanisms."""

from __future__ import annotations

from collections import OrderedDict

from .contracts import DreamMechanism


_mechanisms: OrderedDict[str, DreamMechanism] = OrderedDict()


def register_mechanism(mechanism: DreamMechanism) -> None:
    key = mechanism.key.strip()
    if not key:
        raise ValueError("A Dream mechanism requires a non-empty key.")
    existing = _mechanisms.get(key)
    if existing is not None and existing is not mechanism:
        raise ValueError(f"Dream mechanism already registered: {key}")
    _mechanisms[key] = mechanism


def mechanisms() -> tuple[DreamMechanism, ...]:
    return tuple(_mechanisms.values())


def register_default_mechanisms() -> None:
    from .mechanisms.attachment_memory import attachment_memory_mechanisms
    from .mechanisms.document_structure import document_structure_mechanism
    from .mechanisms.sequential_topic_classification import (
        message_topic_classification_mechanism,
    )
    from .mechanisms.topic_classification import (
        task_topic_classification_mechanism,
    )
    from .mechanisms.task_memory import task_memory_mechanism
    from .mechanisms.conversation_memory import conversation_memory_mechanism
    from .mechanisms.skill_learning import skill_learning_mechanism
    from .mechanisms.process_memory import process_memory_mechanism
    from .mechanisms.memory_maintenance import memory_maintenance_mechanism

    register_mechanism(message_topic_classification_mechanism)
    register_mechanism(task_topic_classification_mechanism)
    register_mechanism(task_memory_mechanism)
    register_mechanism(conversation_memory_mechanism)
    register_mechanism(skill_learning_mechanism)
    register_mechanism(process_memory_mechanism)
    register_mechanism(memory_maintenance_mechanism)
    register_mechanism(document_structure_mechanism)
    for mechanism in attachment_memory_mechanisms:
        register_mechanism(mechanism)


def reset_registry() -> None:
    """Clear process-local registrations, primarily for isolated tests."""

    _mechanisms.clear()


__all__ = [
    "mechanisms",
    "register_default_mechanisms",
    "register_mechanism",
    "reset_registry",
]
