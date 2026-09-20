<p align="right"><a href="../../../fr/architecture/flows/llm-provider-bridges.md">Français</a> · <strong>English</strong></p>

# AI Provider Bridges

`app.llm` is the common language for AI resources. It exposes connections detached from the ORM
model and service-specific facades. External products live in `bridge.*`.

```text
API / agents / messaging / memory
                  │
                  ▼
             app.llm
  catalog + contracts + registries
  generic OpenAI-compatible protocols
                  │
        resolution by catalog_code
                  ▼
 bridge.<provider>          bridge.models_dev
 endpoints, auth, payloads  public metadata
```

## Available Facades

| `app.llm` contract | Bridge responsibility |
|---|---|
| `ResourceDiscovery` | List models, voices, or other resources |
| `ModelManagement` | Install or remove a managed model |
| `ModelMetadata` | Enrich provider-specific metadata |
| `TranscriptionProvider` | Adapt batch STT |
| `RealtimeTranscriptionProvider` | Open a PCM STT session |
| `SpeechProvider` | Produce an MP3 or a PCM stream |
| `ProviderAuthentication` | Perform external authentication |
| `ProviderChatTransport` | Adapt chat requests, responses, and SSE |
| `OpenAIProtocolAdapter` | Normalize the common protocol URL |
| `RequestParameterPolicy` | Declare accepted parameters and combinations per model and protocol |

Implementations receive an immutable `ProviderConnection`. They receive neither a SQLAlchemy
session nor an ORM model, except when an authentication integration explicitly owns the
persistence of its tokens.

The proxy applies the parameter policy after model and effort resolution, before sending
Chat or Responses requests. See the [audited matrix](../../dev/provider-parameters.md)
for compatibility rules and validation.

## Add a Provider

1. Create `back/bridge/<code>/__init__.py`.
2. Declare the immutable `ProviderProfile`: identity, key acquisition, capabilities, and
   non-secret configuration fields.
3. Implement one or more existing facades in the bridge.
4. Register the profile, services and text parameter policy when the package is loaded.
5. Add `bridge.<code>` to `back/modules.py`.
6. If the provider adds a custom connection type to the interface, contribute a
   `front/bridge/<code>/llmProvider.ts` file.
7. Test the bridge contract and run `make typecheck`, `make architecture-check`, and the
   relevant tests.

The generic OpenAI-compatible protocol must not be copied into each bridge. A bridge only replaces
the product differences: authentication, URL, headers, payloads, discovery, or streaming.
