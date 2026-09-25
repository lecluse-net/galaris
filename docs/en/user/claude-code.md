<p align="right"><a href="../../fr/user/claude-code.md">Français</a> · <strong>English</strong></p>

# Connect Claude Code to Galaris

A Claude Code client installed on your machine can use Galaris profile models
through `https://galaris.example/api/profile/anthropic`. All profiles share this
URL; the `model` field selects the profile and tier, such as `profile1/text/high`.
Calls remain visible under **Execution tracking → LLM calls**.

## Prepare the connection

In Galaris, create a **user API token** under **API tokens**. Your account needs
the **LLM API access** privilege (`LLM_API_ACCESS`). Use this token, rather than
your password or a system token reserved for runtimes managed by Galaris.

Find the profile’s **API code** in LLM usages. These examples assume a `profile1`
profile whose four text tiers are assigned to active models supporting tool calls.
Replace this code and `https://galaris.example` with your own values. The
[profile API guide](profile-api.md) describes the available selectors.

## Configure `.claude/settings.json`

Under **API tokens** (`/user/tokens`), **Configure Codex / Claude Code** lets you
choose a profile and copy this configuration with your server address. Fill in
the token separately. For a missing tier, its Claude Code alias uses the selected
startup model.

Merge this example into your existing project settings. It contains no secret:

```json
{
  "model": "profile1/text/high",
  "env": {
    "ANTHROPIC_BASE_URL": "https://galaris.example/api/profile/anthropic",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "profile1/text/ultra-low",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME": "Galaris · Ultra-low",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION": "profile1/text/ultra-low",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "profile1/text/low",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": "Galaris · Low",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION": "profile1/text/low",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "profile1/text/standard",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME": "Galaris · Standard",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION": "profile1/text/standard",
    "ANTHROPIC_DEFAULT_FABLE_MODEL": "profile1/text/high",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME": "Galaris · High capacity",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_DESCRIPTION": "profile1/text/high",
    "CLAUDE_CODE_SUBAGENT_MODEL": "profile1/text/low",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"
  }
}
```

This mapping is a client configuration choice: Claude Code sends the complete
selectors to Galaris. The underlying models may come from other providers. You
can also assign different profiles to different aliases. Discovery populates the
`/model` menu from `/api/profile/anthropic/v1/models`. Alias and display variables
are documented in the
[official Claude Code model configuration](https://code.claude.com/docs/en/model-config).

Keep the token in `~/.claude/settings.json` for your user, or
`.claude/settings.local.json` for this project. If creating the latter manually,
add it to `.gitignore` before storing the token. Merge this block into the chosen file:

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "<galaris-user-api-token>"
  }
}
```

`ANTHROPIC_AUTH_TOKEN` sends `Authorization: Bearer …`, as required for Galaris
user tokens; `ANTHROPIC_API_KEY` uses a different header. File scopes and
authentication are detailed in the
[official gateway connection guide](https://code.claude.com/docs/en/llm-gateway-connect).
For a fully personal setup, also put the first block in `~/.claude/settings.json`.
The base URL ends at `/anthropic`, without `/v1/messages`.

## Verify and switch models

To check the catalog from a terminal, export the token in that terminal
(`curl` does not read the JSON settings):

```bash
export ANTHROPIC_AUTH_TOKEN='<galaris-user-api-token>'
curl --fail-with-body 'https://galaris.example/api/profile/anthropic/v1/models' \
  -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
  -H 'anthropic-version: 2023-06-01'
claude --model profile1/text/high
```

In Claude Code, `/status` lets you check the connection. Then request a short
answer to verify inference and its trace in Galaris. For another session, use
`claude --model profile1/text/standard`, for example.

The `text/high` and `text/standard` tiers select profile assignments; they do not
designate reasoning effort. This example therefore does not force `effortLevel`
or reasoning capabilities. If needed, set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to a
window compatible with all models used by this configuration; see the
[official context window guidance](https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id).

## Troubleshooting

| Symptom | Check |
|---|---|
| `401` or `403` | Valid user token, `ANTHROPIC_AUTH_TOKEN` variable, `LLM_API_ACCESS` privilege |
| Unknown or unavailable model | Exact catalog selector, **API code**, and tier assigned to an active model |
| Wrong provider or model at startup | User/project/local settings and inherited variables; check `/status` |
| Catalog missing from the menu | Client version supporting discovery, enabled variable, and any `availableModels` restriction |
| Tool or reasoning failure | Assigned model capabilities and options requested by the client |

This connection supplies inference to your local client. It does not create a
Galaris Task or Agent, or configure an MCP server. To call a concrete model
directly, the existing `/api/llm/anthropic` base remains available with its LLM code.
For OpenAI Codex, see the [Codex guide](codex.md).
