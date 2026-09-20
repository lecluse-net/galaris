<p align="right"><a href="../../fr/components/mammouth.md">Français</a> · <strong>English</strong></p>

# Mammouth AI

The `mammouth` provider connects Galaris to Mammouth AI's public API. The
`back/bridge/mammouth` bridge reuses the LLM, Image and Multimedia facades without
creating another agent system or file management workflow.

## Configuration

1. Add **Mammouth AI** in the LLM providers.
2. Enter a key from [Mammouth API settings](https://mammouth.ai/app/account/settings/api).
   The default URL is `https://api.mammouth.ai/v1`.
3. Test the connection and import models by capability. This test checks the key
   with an authenticated read, without generation; it does not guarantee sufficient credit.
4. Assign models to LLM profile usages. For `audio_read` and `video_read`, use the
   **Multimedia** section and enable the agent's Multimedia connection.

Multimedia connections are created automatically and disabled by default.
Functions are exposed only when the profile has a compatible resource and both
the provider and connection are active. See [Multimedia](multimedia.md).
API credits are separate from Mammouth application quotas; the provider does not
declare calls free or covered without limits by a subscription.

## API coverage

Reviewed on September 6, 2026 using the [API guide](https://info.mammouth.ai/docs/api-quick-start/),
the [published OpenAPI schema](https://api.mammouth.ai/openapi.json) and the unauthenticated
public catalog. The catalog contained 93 models during verification; Galaris does
not hardcode that list of 93 identifiers.

| Capability | Galaris facade | Mammouth contract |
|---|---|---|
| Text, code, streaming, tool calls, structured outputs | LLM / agents | Chat Completions and Responses; options depend on the model |
| Reasoning, context and prices | Catalog / LLM profiles | Model metadata; missing values do not imply capabilities |
| Vision | Existing image reading | Models declaring `supports_vision` |
| Image generation, with references when supported by the model | Image | Chat Completions; base64 `message.images[].image_url.url` output |
| Embeddings | Embeddings facade | `/v1/embeddings`; catalog filtered by capability |
| Sound and music analysis | Multimedia `audio_read` | WAV or MP3 `input_audio`; requires `supports_audio_input=true` |
| Video analysis | Multimedia `video_read` | `video_url` input; requires `supports_video_input=true` |
| Automatic model selection | `mammouth-recommended` preset | The alias is passed unchanged; Mammouth chooses the underlying model |

Image dimensions are a preference expressed in the prompt. The bridge does not
promise exact dimensions or send unpublished Images API parameters.
Responses uses explicit history with `store=false` and does not reuse reasoning
identifiers across models; compaction uses the existing Responses contract.
Remote response storage, retrieval and cancellation operations do not replace
Galaris's persisted tasks.

## Catalog and billing

`/public/models` supplies callable identifiers and public prices;
`/public/model/info` adds modalities and capabilities. The join uses `id` /
`model_name`, never deployment hashes or internal routes. Both responses are
bounded; errors are not replaced with an invented catalog. A protected read of
`/v1/models/{model_id}` validates the key separately.

Per-token prices are converted to per-million prices for Galaris; missing prices
remain unknown and explicit zeros are preserved. Public prices are ceilings,
not an exact measure of actual charges. LLM and Image calls use existing accounting;
multimedia analysis does not claim exact costs absent from its response contract.

## Mammouth application features

The [Mammouth application](https://info.mammouth.ai/docs/introduction-to-mammouth/) also
offers Lyria music, videos, dictation, voice conversations, text-to-speech, custom
assistants, response comparison and MCP connectors. The inspected public schema
does not provide the required contracts for dedicated music, sound or video
generation, transcription, speech synthesis or realtime voice services.
The Galaris provider therefore does not advertise them. A generic
`supports_audio_output` flag is insufficient to invent a voice or music service.

Web search advertised by individual models remains a model property; it does not
grant access to the application's Agentic Mode or connectors. Their MCPs are
incoming application connections, not a public server to add automatically to
Galaris. Mammouth Code is also a separate product. Credit tracking via `/key/info`
is not integrated: the guide's example targets a local address and this endpoint
does not appear in the inspected public schema.

## Validation

Tests cover dynamic import, aliases, price units, rejected keys, image/audio/video
formats, invalid outputs, response limits and exclusion of unavailable features.
The real catalog was queried without authentication. Paid inference requires a key
and credits; contract tests use a simulated HTTP transport and do not validate
every production model.
