<p align="right"><a href="../../fr/user/codex.md">Français</a> · <strong>English</strong></p>

# Connect Codex to Galaris

A Codex CLI installed on your machine can use Galaris as its model provider through
`https://galaris.example/api/profile/openai`. All profiles share this URL:
`profile1/text/high` selects the `high` tier of the profile whose **API code** is
`profile1`. The internal profile identifier is not involved.

## Prepare the connection

Create a **user API token** under **API tokens**, using an account with the
**LLM API access** privilege (`LLM_API_ACCESS`). Galaris runtime system tokens
are not intended for this external connection.

The selected tier must point to an active model whose provider supports
**Responses**, streaming, and the tool calls Codex expects. A model’s presence
in the catalog does not guarantee compatibility: Chat Completions support alone
is insufficient. Remote compaction also requires the provider to support
`/responses/compact`.

Replace `https://galaris.example` and `profile1` with your server and the **API code**
shown in LLM usages. See the [profile model contract](profile-api.md).

## Configure `~/.codex/config.toml`

Under **API tokens** (`/user/tokens`), click **Configure Codex / Claude Code**,
choose a profile, then the **Codex** tab. Copy the configuration using your server
address and fill in the token separately.

Merge these keys into your existing user configuration. Put the first two keys
at the file’s root, before any TOML tables:

```toml
model = "profile1/text/high"
model_provider = "galaris"

[model_providers.galaris]
name = "Galaris"
base_url = "https://galaris.example/api/profile/openai"
env_key = "GALARIS_API_TOKEN"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

Do not append `/v1` or `/responses` to the base. Codex adds the Responses route;
Galaris uses HTTP and SSE for streaming here. `env_key` names the variable holding
the token sent as Bearer authentication. This uses the official
[Codex custom provider mechanism](https://developers.openai.com/codex/config-advanced/)
and keys from the [configuration reference](https://developers.openai.com/codex/config-reference/).
Declare the provider in the user configuration file.

In the terminal that will launch Codex:

```bash
export GALARIS_API_TOKEN='<galaris-user-api-token>'
```

Keep the token outside the TOML file and repository. For regular use, supply this
variable through your local environment or secret manager. A client launched by
another application must also receive the variable.

## Verify and launch Codex

First check that the catalog contains the required selector:

```bash
curl --fail-with-body 'https://galaris.example/api/profile/openai/models' \
  -H "Authorization: Bearer $GALARIS_API_TOKEN"
```

Then start a session from your working directory:

```bash
codex --model profile1/text/high
```

Request a short answer to verify inference and its trace under
**Execution tracking → LLM calls**. To change profiles or tiers, change only
`model` or the `--model` argument, for example to `profile1/text/standard`.
The profile code remains stable when its label is renamed.

To keep your usual provider as the default, retain only the
`[model_providers.galaris]` table in your configuration and select Galaris at startup:

```bash
codex -c 'model_provider="galaris"' --model profile1/text/high
```

Galaris tiers are distinct from Codex reasoning levels: this example does not
force `model_reasoning_effort`. `embedding/default` and `decision/default` are
not conversation models for Codex; their routes are documented in the
[API guide](profile-api.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Missing token, `401` or `403` | `GALARIS_API_TOKEN` available to the process, valid token, and `LLM_API_ACCESS` privilege |
| Unknown or unavailable model | Exact catalog selector and tier assigned to an active model |
| Calls sent to your usual provider | `model_provider = "galaris"` and any configuration overrides |
| Responses, tools, or compaction failure | Assigned provider compatibility; keep `wire_api = "responses"` and choose a compatible assignment |

This connection supplies models to your local Codex. It does not create a
Galaris Task or Agent, or configure an MCP server. The `/api/llm/openai` base
remains available for calling a concrete model by its LLM code. For Claude Code,
see the [Claude Code guide](claude-code.md).
