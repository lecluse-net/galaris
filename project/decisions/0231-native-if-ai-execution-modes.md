# 0231 — Native IF AI execution modes

Date: 2026-10-24
Status: accepted

## Context

Native IF AI processing currently creates an agent Task. Some conditions require tools
and agent work, while others need only a closed-choice LLM decision on existing run data.
Galaris already supports specialized decision models such as Jev and durable inference.

## Decision

Keep `config.mode` as `ai`, `code` or `human`. For typed AI IFs, add `config.ai_mode`:
`task` is the existing default; `llm` requires an explicit configured `llm_id`.
The editor exposes these as two AI submodes. This change is scoped to IFs.

Task execution retains its agent, tools and human-question workflow. Direct inference
receives only instructions and the frozen activity data. Decision models use the common
closed-choice contract with true/false criteria. Text models use a strict boolean output
contract. Neither path interprets arbitrary prose or a failed request as False.

Process stores the deterministic inference identity before admission, then prepares,
starts, observes and stops it through the public LLM facade. LLM owns provider execution,
requests, results and cancellation. Process owns the activity and chosen branch. An acquired
result is reused after scheduler recovery. Interrupted or failed inference fails the
activity explicitly; there is no automatic replay or model substitution. Process cancellation
waits for the inference to stop. Run pause retains the existing finish-admitted-work policy.

Calls carry the run identity and an attempt correlation reference so existing run metrics
include direct non-agentic calls at both node and occurrence level. No database schema,
Document, Dataset, auxiliary Task or new process definition is needed.

## Verification

Process integration tests exercise both branches for text and decision HTTP boundaries,
absence of Tasks, reuse of completed inference, cancellation and model/contract failures.
Browser coverage checks mode/model selection, persistence and reopening in the editor.
