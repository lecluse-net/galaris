"""Compatibility import for the unified conversation-round memory mechanism."""

from .conversation_memory import (
    ConversationMemoryMechanism,
    build_conversation_extraction_input,
    conversation_memory_mechanism,
)

VoiceMemoryMechanism = ConversationMemoryMechanism
voice_memory_mechanism = conversation_memory_mechanism
build_voice_extraction_input = build_conversation_extraction_input

__all__ = [
    "VoiceMemoryMechanism",
    "build_voice_extraction_input",
    "voice_memory_mechanism",
]
