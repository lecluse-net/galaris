"""Operational context needed for plausible synthetic situations in each Lab."""

from .schemas import EvaluationMechanism


USAGE_CONTEXT: dict[EvaluationMechanism, str] = {
    "dispatcher": (
        "The caller is an active Task awaiting a route, not a chatbot choosing whether to answer. "
        "Ground requests in the shared agent mission, channel and harness policy. Include concrete "
        "deliverables and constraints, short follow-ups whose meaning comes from item messages, "
        "and multi-stage work only when the policy permits planning. Forced route/effort are "
        "authoritative even if a different choice might otherwise be natural."
    ),
    "briefing": (
        "The caller prepares a Task for an executor. Build objectives that actually use the supplied "
        "resource catalog, agent role and channel. Vary item history, prior attachments and missing "
        "information. Include relevant resources and plausible distractors. When creating a fresh "
        "environment, supply a small coherent tool/process catalog with identifiers and descriptions. "
        "References must select existing resources or explicit checks, never invent a tool."
    ),
    "planner": (
        "The caller decomposes a Task before execution. Use the shared tool catalog, result contract, "
        "delivery owner, context and limits. Vary objectives with real dependencies (collect, verify, "
        "produce, deliver), missing requirements and previous clarifications. When creating a fresh "
        "environment, define a plausible catalog and deliverable contract. Do not turn every task "
        "into the same three-step plan. Clarification depends on can_clarify; unavailable capabilities "
        "must stay unavailable."
    ),
    "topic_classification": (
        "The caller processes consecutive conversation messages. Generate natural multi-message "
        "exchanges with short acknowledgments, pronouns, digressions, topic returns and mixed speakers. "
        "Use coherent timestamps and roles when supplied. Respect configured continuity windows and "
        "the initial topic. A topic return need not create a new title. Keep expected topics aligned "
        "with every message; do not leak the expected classification into message text."
    ),
    "memory_extraction": (
        "The caller processes a completed round or Task, not an isolated fact list. Match source_kind: "
        "natural speaker turns for conversation_round, a coherent trace and its messages for task. "
        "Include the topic, speaker context, earlier statements and evidence supporting durable facts. "
        "Use the existing corpus for duplicates, corrections and relevant-memory decisions. For fresh "
        "environments, create a small fictional corpus using the native input schema. Transient "
        "requests, assistant guesses and unverified claims must not become established memories."
    ),
    "outcome_reflection": (
        "The caller learns after a Task terminates. Ground each outcome in the same shared objective, "
        "driver, effort and route. Fresh environments need a concrete objective. Include bounded "
        "observations of actions, retries, errors and verified deliverables; let terminal status and "
        "claimed final result disagree in robustness cases. Lessons need evidence, and no reusable "
        "lesson can be the correct output. Do not infer delivery from a success claim alone."
    ),
    "goal_tracking": (
        "The caller judges a cycle against a durable goal. Use the shared title, description, latest "
        "Task objective and reminder policy. Fresh environments need a concrete goal and measurable "
        "completion conditions. Each item provides earlier HTML tracking and the latest cycle result. "
        "Cover evidence of progress, apparent success missing a criterion, repeated stalls and actual "
        "completion when allowed by the requested categories. These are alternative cycles in one "
        "goal context, not unrelated missions with identical tracking."
    ),
    "task_executor": (
        "The caller executes an assigned Task. Use the shared agent role, tool catalog, briefing, "
        "plan, resources, working set and simulated tool responses. Fresh environments need a concrete "
        "role, relevant tool names and coherent response fixtures. Cases must be executable with "
        "those tools and fixtures; inability or clarification is valid when a capability is absent. "
        "Keep simulated call arguments, ordered results and final claims consistent. A fixture error "
        "must not become successful delivery in the reference."
    ),
    "conversation_executor": (
        "The caller handles the current turn in a text conversation. Use the agent role, channel, "
        "memories, available processes and linked work. Item history should make follow-ups, pronouns, "
        "status questions and repeated requests understandable. Include direct answers, clarification "
        "and background handoff where context permits. Previously started work must not be started "
        "again. Reference actions must agree with the simulated tool results and foreground policy."
    ),
    "voice_executor": (
        "The caller receives a voice transcript in an ongoing spoken exchange. Use the agent role, "
        "channel, linked work and interrupted objective. Write natural short transcripts with "
        "self-corrections, ambiguous names, interruptions and context-dependent follow-ups, not "
        "formatted written task briefs. Include preceding turns when needed to resolve pronouns. "
        "References should sound speakable and concise, clarify uncertain intent and avoid repeating "
        "a pending action. Do not claim to test speech recognition or synthesize audio."
    ),
    "task_analysis": (
        "The caller diagnoses a bounded execution dossier. Create mutually consistent fictional Task "
        "objectives, statuses, attempts, model/tool calls, process results and delivery evidence under "
        "the supplied agent configuration, active skills and runtime settings. Evidence can be missing "
        "deliberately, but never silently invent it in the diagnosis. A failed attempt followed by "
        "verified recovery differs from final failure. Distinguish a provider error, bad tool arguments, "
        "an unavailable capability and a false success claim with their own evidence."
    ),
}
