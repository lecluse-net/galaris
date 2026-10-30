# 0259 — ChatGPT Fast model variants

Status: accepted. Date: 2026-10-30.

## Decision

The ChatGPT bridge exposes Fast as a separate catalog resource, named after the upstream
display name followed by `Fast`. Its bridge-local identifier is `<model>:fast`, persisted
through the existing configured LLM contract. No schema change or global speed switch is
needed. Existing standard LLMs keep their identity and behavior.

Discovery uses the connected account's `service_tiers`; the legacy
`additional_speed_tiers` is consulted only when the former is absent. Unknown support,
hidden models and Ultrafast alone do not create Fast variants. There is no hardcoded
model-family allowlist. Base-model metadata and SDK profiles also apply to the variant.

Only the ChatGPT bridge interprets the suffix. Chat and Responses requests send the real
model identifier and `service_tier=priority`. Authentication refresh preserves that mapping;
compaction resolves the base model without a generation tier. Reasoning remains independent.

An explicitly requested service tier is a functional requirement of inference and cannot
be removed by optional-parameter negotiation. OpenAI still controls eligibility, quota,
actual serving tier and latency; Galaris does not guarantee acceleration or infer a monetary
API price from subscription multipliers.

## Verification

Synthetic provider-boundary tests cover discovery, inherited metadata, both inference
protocols, authentication refresh and unchanged standard models. Persistence uses the normal
LLM creation and reload path. Existing protocol tests cover explicit service-tier rejection.

References: [OpenAI model catalogs](https://learn.chatgpt.com/docs/model-catalogs),
[Fast mode](https://learn.chatgpt.com/docs/agent-configuration/speed).
