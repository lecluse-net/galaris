<p align="right"><a href="../../fr/user/claude-code.md">Français</a> · <strong>English</strong></p>

# Using Claude Code with Galaris

Claude Code, Anthropic’s command-line assistant, can use Galaris as a model provider through the Anthropic-compatible API exposed by Galaris at
`/api/llm/anthropic`. Calls are then routed through the LLMs configured in Galaris:
traces, costs, and errors remain visible under **Execution tracking → LLM calls**, as with
any other channel.

Two elements are sufficient:

- the Galaris server address, provided by your administrator;
- a **Hermes system token** created in the administration interface, or a **user account with
  permission to access the LLM API**.

Never copy a token into a conversation or shared channel. Configure it in
the environment intended for this purpose, like other secrets.

## First connection

In Claude Code’s settings file (`~/.claude/settings.json`), declare the address and
token in the `env` block:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://<your-server>/api/llm/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "<Hermes token or login identifier>"
  }
}
```

The `env` block in this file takes priority over shell variables: it is the reliable place to
configure the same machine persistently. The token is sent in an `Authorization: Bearer` header;
Anthropic clients that use `x-api-key` (SDKs, other tools) are accepted in the same
way.

## Choosing the model: the Opus, Sonnet, Fable… mapping

Each Galaris profile configures four text levels. The gateway accepts their canonical names and
the corresponding Claude families: Haiku → `ultra-low`, Sonnet → `low`, Opus → `standard`, and
Fable → `high`. A configured Galaris LLM code always takes priority over these aliases.

| Use | Setting |
|---|---|
| Try temporarily | `claude --model <Galaris code or level>` |
| Set for a repository | `.claude/settings.json` → `"model": "<Galaris code or level>"` |
| Set for the machine | `~/.claude/settings.json` → `"model": "<Galaris code or level>"` or `ANTHROPIC_MODEL` |
| Name four levels in the `/model` selector | variables `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL` (with `_NAME` and `_DESCRIPTION` for display) |

The four level variables are exactly the “Opus, Fable… equivalent”: Claude Code’s
`/model` menu displays these named entries, and choosing one sends the alias
that Galaris resolves in the effective profile. The `/model` choice remains limited to the session; “set as
default” saves it in the user settings.

### Two practical details

- Because a Galaris code is unknown to Claude Code, Claude Code assumes a context window of
  200,000 tokens. Specify the LLM’s actual value (the *context* field on its details page) with
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, or append `[1m]` to the name in `--model` for one million —
  this suffix is never sent to Galaris.
- The `/model` selector accepts only recognized names. For a Galaris code, use
  `--model`, environment variables, or settings, not the menu. With
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` (and nonessential traffic allowed),
  Claude Code can also retrieve the list of codes from `GET /v1/models` and offer them
  in the menu as additional options.

## What Galaris does for each call

Each call, whether streaming or not, is translated for the configured providers, traced, and
billed like an ordinary call. Errors are returned in the format expected by Claude
Code. If a correlation header is provided (for example, `X-Galaris-Task-Id`), the call is
attached to the indicated Task; otherwise Galaris correlates it as it does for its other surfaces.

An authentication refusal or missing privilege displays an explicit error in Claude
Code: check the token and the permission to access the LLM API.
