# 0306 — Profile-based inference and human choices in Process

Date: 2026-11-21
Status: Accepted

Process authors select a primary profile and a fallback profile for direct LLM activities.
A text task selects one common text tier. An LLM IF uses the Decision column of both
profiles. Missing selections inherit the current profile and the default fallback profile.
Process keeps the graph and activity-attempt ownership. Durable LLM inference freezes the
selected models and runs the provider fallback within the same inference. Direct model IDs
remain valid for historical BPMN. This updates the activity configuration in [0272](0272-explicit-process-activity-types.md).

Python, Decision LLM and Human IF are directly insertable. A Human IF may take its question
from a selected string input, allowing an earlier code, LLM or Service activity to prepare
the text. Process freezes the question before the existing durable Messenger wait. The
localized Yes/No labels use the existing `true` and `false` choice identities.
