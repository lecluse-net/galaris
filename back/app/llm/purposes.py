"""Stable semantic purposes attached to persisted LLM call traces."""

from __future__ import annotations

from enum import StrEnum


class LLMCallPurpose(StrEnum):
    """Describe why Galaris started an inference, independently of its model."""

    AGENT_EXEC = "agent.exec"
    AGENT_DISPATCH = "agent.dispatch"
    AGENT_BRIEFING = "agent.briefing"
    AGENT_PLANNING = "agent.planning"
    AGENT_PLANNING_RECOVERY = "agent.planning_recovery"
    AGENT_SYNTHESIS = "agent.synthesis"

    CONVERSATION_TEXT = "conversation.text"
    CONVERSATION_AUDIO = "conversation.audio"
    CONVERSATION_TASK_OBJECTIVE = "conversation.task_objective"

    DREAM_TOPIC_CONTINUITY = "dream.topic_continuity"
    DREAM_TOPIC_REUSE = "dream.topic_reuse"
    DREAM_TOPIC_CREATION = "dream.topic_creation"
    DREAM_MEMORY_EXTRACTION = "dream.memory_extraction"
    MEMORY_DUPLICATE_DECISION = "memory.duplicate_decision"
    DREAM_TASK_OUTCOME_REFLECTION = "dream.task_outcome_reflection"
    DREAM_SKILL_LEARNING = "dream.skill_learning"

    GOAL_TRACKING = "goal.tracking"

    AUDIO_SEGMENT_SUMMARY = "audio.segment_summary"
    AUDIO_SUMMARY_REDUCTION = "audio.summary_reduction"
    AUDIO_FINAL_SYNTHESIS = "audio.final_synthesis"
    AUDIO_TRANSCRIPTION = "audio.transcription"

    IMAGE_ANALYSIS = "image.analysis"
    IMAGE_GENERATION = "image.generation"

    LAB_TASK_ANALYSIS = "lab.task_analysis"
    LAB_MECHANISM_RUN = "lab.mechanism_run"
    LAB_MECHANISM_JUDGE = "lab.mechanism_judge"
    LAB_BENCHMARK_ANALYSIS = "lab.benchmark_analysis"
    LAB_DISPATCHER_JUDGE = "lab.dispatcher_judge"

    PROCESS_EXEC = "process.exec"


__all__ = ["LLMCallPurpose"]
