# 0290 — Native provider embeddings through the shared LLM boundary

Status: accepted. Date: 2026-11-14.

Embedding consumers keep the canonical `app.llm` client and its batch ordering,
vector count, dimension and finite-value checks. Providers with a native vector
protocol register an `EmbeddingProvider` through `provider_facade`; the default
remains the OpenAI-compatible `/embeddings` protocol. Bridges return an indexed
payload, including provider usage when supplied, before common validation.

Configured vector handles carry a detached provider connection with credentials
excluded from representations. Existing cache identities remain unchanged.
Memory, Tools, document search and profile API calls use the same dispatch.
No application domain imports provider-specific code.

Hugging Face keeps its OpenAI router for chat and vision. Specialist catalogs
use the Hub task API and live provider mappings, including pagination. The bridge
currently implements HF Inference and DeepInfra embeddings/transcription,
DeepInfra MP3 speech synthesis and HF Inference text-to-image. It does not advertise
other native provider protocols, realtime voice, music, video or image editing.
Native routes are resolved before each embedding, transcription or speech request;
a failed submission is never automatically repeated through another provider.
