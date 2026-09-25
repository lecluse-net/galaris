<p align="right"><a href="../../fr/user/profile-api.md">Français</a> · <strong>English</strong></p>

# Calling models by profile

Each LLM usage profile displays its **API code**, generated from its label as a
unique lowercase ASCII name. For example, “Profile1” becomes `profile1`.
Renaming a profile preserves its code. Existing profiles receive codes during
the normal database synchronization.

All profiles share one base URL per protocol:

| Protocol | Base URL | Catalog |
|---|---|---|
| OpenAI | `https://galaris.example/api/profile/openai` | `GET /models` |
| Anthropic | `https://galaris.example/api/profile/anthropic` | `GET /v1/models` |

Use a user API token with **LLM API access**, passed as `Authorization: Bearer …`
for either protocol. Configure an Anthropic client's Bearer authentication token
(`auth_token`). `GET /api/profile/models` lists every available
usage, including decisions. Catalogs include every profile, not only the current one.

The LLM call log displays the API token's name as it was at the time of the call,
even if the token is later renamed or deleted. Tokens without a label appear as
“Unnamed API token”. Older calls without this information keep their previous display.

Select a model as `<profile-code>/<usage>/<level>`:

| Example | Profile assignment |
|---|---|
| `economique/text/ultra-low` | Ultra-low text tier |
| `economique/text/low` | Low text tier |
| `profile1/text/standard` | Standard text tier |
| `profile1/text/high` | High text tier |
| `local/embedding/default` | Vector model |
| `profile1/decision/default` | Decision model |

`text/default` aliases `text/standard`. Text tiers and reasoning effort are
separate profile settings. Assignment changes affect subsequent calls; an admitted
inference retains its selection. Empty or unavailable usages fail explicitly and
never borrow models from another profile.

## External coding clients

The [Codex CLI](codex.md) and [Claude Code](claude-code.md) guides provide
configuration files, user token placement, and verification commands. They use
the same shared URLs and models such as `profile1/text/high`. Codex uses Responses;
Claude Code uses Messages.

With a user token, task or model references in messages and tool results remain
content: they do not change the selected model or automatically associate the
call with a Galaris task.

## Text

```http
POST /api/profile/openai/chat/completions
Authorization: Bearer <token>
Content-Type: application/json

{
  "model": "profile1/text/high",
  "messages": [{"role": "user", "content": "Summarize this proposal."}],
  "stream": true
}
```

The `/responses` and `/responses/compact` routes are also available, subject to
provider support. Anthropic clients use `/v1/messages` and `/v1/messages/count_tokens`
with the same model selector.

## Embeddings

```http
POST /api/profile/openai/embeddings
Authorization: Bearer <token>
Content-Type: application/json

{
  "model": "local/embedding/default",
  "input": ["First text", "Second text"],
  "encoding_format": "float"
}
```

Input accepts one nonempty text or a list of 1–2,048 nonempty texts. Pretokenized
input is unsupported. `encoding_format` accepts `float` or `base64`; optional
`dimensions` depends on provider support. Vectors retain input order and usage
is returned when provided upstream. `X-Galaris-LLM-Call-Id` identifies the trace.

## Decisions

```http
POST /api/profile/decisions
Authorization: Bearer <token>
Content-Type: application/json

{
  "model": "profile1/decision/default",
  "prompt": "This request concerns a supplier invoice.",
  "questions": {
    "category": {
      "instructions": "Choose the relevant category.",
      "criteria": {"billing": "Billing", "other": "Other requests"}
    }
  }
}
```

The response contains `answers` and reports `source: specialized` or `source: text`.
A recoverable specialized-model failure can use the same profile's `text/standard`
when its fallback policy allows it and that model is available. `fallback_reason`
explains the fallback; probabilities are never fabricated. Embeddings and decisions
are standalone user calls.

The existing `/api/llm/openai` and `/api/llm/anthropic` routes continue to accept
concrete model codes.
