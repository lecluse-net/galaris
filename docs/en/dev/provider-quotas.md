<p align="right"><a href="../../fr/dev/provider-quotas.md">Français</a> · <strong>English</strong></p>

# Provider usage, budgets and credits

Review of the 22 catalog profiles and custom Ollama connections on September 30, 2026.
“Integrated” describes readers registered by repository bridges. “Possible” describes a
consulted official API, without claiming it is integrated in Galaris. “Not found” means no
suitable public contract was identified in the consulted references, rather than proof that
the provider will never offer one. The review relies on public contracts; automated checks
use entirely synthetic responses. A development read verified authentication for the
Fireworks balance route; only its HTTP status and technical conclusion are retained,
without credentials or individual data.

A gauge requires usage and a ceiling for the same period, currency and scope. A balance alone
remains an amount. Rate-limit headers are not financial budgets. Galaris call costs cannot
reconstruct balances of accounts also used by other clients.

| Provider | Galaris availability | Readable information and requirements | Reference |
|---|---|---|---|
| Fireworks AI | Balance not integrated; no panel displayed | No public prepaid-balance route identified. `monthly-spend-usd` reports a spending ceiling and its usage, not available funds. The portal `/api/billing/balance` route rejects the tested API key (401). No spend gauge substitutes for a balance. | [Billing](https://app.fireworks.ai/account/billing), [account quotas](https://docs.fireworks.ai/guides/quotas_usage/account-quotas), [Get Quota](https://docs.fireworks.ai/api-reference/get-quota) |
| ChatGPT / Codex | Integrated | Connected OAuth account windows and `credits.balance` in credits, without invented ceilings or percentages; existing Galaris ownership and refresh rules. Missing amounts or unlimited credits are not shown as zero. ChatGPT-specific interface, separate from OpenAI API credits. | [Bridge contract tests](../../../back/bridge/openai/tests/test_quota.py), [ChatGPT credits](https://learn.chatgpt.com/docs/pricing#what-are-tokens-and-credits) |
| OpenAI API | Possible, not integrated | Organization usage and costs using a separate Admin key. These reports alone do not supply prepaid balance or a comparable ceiling. | [Usage and Cost APIs](https://developers.openai.com/cookbook/examples/completions_usage_api) |
| Anthropic API | Possible, not integrated | Admin API usage and costs; administrative credentials rather than workspace-scoped inference keys. Unavailable for individual accounts. Distinguish Claude Platform from Claude Enterprise. | [Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api) |
| OpenRouter | Integrated | Remaining key funds through `/key`; account balance through `/credits` using an optional management key. Amount only, without a gauge based on cumulative purchases. | [Credits](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits) |
| Mammouth AI | Integrated, live schema unconfirmed | `/key/info`: key spending and budget when supplied. Reader fields remain verified with synthetic responses; application quotas are separate. | [Decision and validation limit](../../../project/decisions/0146-provider-usage-snapshots.md), [service documentation](https://info.mammouth.ai/docs/api/) |
| DeepSeek | Integrated | `/user/balance`: USD/CNY balances; no original ceiling for a percentage. | [Balance](https://api-docs.deepseek.com/api/get-user-balance) |
| ElevenLabs | Integrated | `/v1/user/subscription`: credit usage, limit and next reset; `User → Read` permission. | [Subscription](https://elevenlabs.io/docs/api-reference/user/subscription/get) |
| SunoAPI.org | Integrated | `/api/v1/generate/credit`: third-party service credits remaining, without a ceiling. | [Remaining credits](https://docs.sunoapi.org/suno-api/get-remaining-credits) |
| Mistral | Possible, not integrated | Beta Admin API: `/v1/admin/usage` and `/v1/admin/spend-limit`, requiring an Admin key. Verify actual reported amounts before calculating a gauge; a limit-reached flag is insufficient. | [Admin Billing](https://docs.mistral.ai/api/endpoint/beta/admin/billing) |
| Together AI | Conditionally possible, not integrated | Beta `/v1/billing/usage`, enabled per organization on request; otherwise 404. Paginated USD spend, without balance/ceiling. Organization key, organization ID recommended; delayed data. | [Billing usage](https://docs.together.ai/reference/billing-usage) |
| xAI | Possible, not integrated | Management API: `/v1/billing/teams/{team}/prepaid/balance` and billing reports. Separate management key and team identifier; normalize cents. | [Billing Management](https://docs.x.ai/developers/rest-api-reference/management/billing), [authentication](https://docs.x.ai/developers/management-api-guide) |
| Gemini | Possible through Cloud infrastructure, not integrated | AI Studio / Cloud Billing usage. No balance route documented for the Gemini key alone; costs through Cloud Billing exports and additional Cloud permissions. | [Billing](https://ai.google.dev/gemini-api/docs/billing), [Cloud Billing exports](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) |
| Google Cloud TTS | Possible through Cloud infrastructure, not integrated | Project billing through Cloud Billing / BigQuery; IAM authentication and an enabled export. The TTS key alone does not provide an account balance. | [Cloud Billing exports](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) |
| Azure AI Speech | Possible through Azure infrastructure, not integrated | Cost Management Query API with subscription/billing scope, Entra token and appropriate permissions. Speech key and region alone are insufficient. | [Cost Management Query](https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage) |
| Groq | Public budget API not found | Console billing and spending limits. Enterprise Metrics API for throughput and tokens, without balance or financial ceiling documented by that contract. | [Billing](https://console.groq.com/docs/billing-faqs), [Enterprise metrics](https://console.groq.com/docs/prometheus-metrics) |
| Cerebras | Not found | Cloud Console balance and credits; no public balance/ceiling route found in the consulted API catalog. | [Account & Billing](https://inference-docs.cerebras.ai/console/account-billing) |
| Cohere | Not found | Per-call billed tokens and dashboard usage/limits; no public account-budget route identified. | [FAQ](https://docs.cohere.com/v2/docs/cohere-faqs) |
| Hugging Face | Not found | Billing-page credits and spend; no suitable public balance route identified. Custom provider keys are billed by that provider. | [Pricing and Billing](https://huggingface.co/docs/inference-providers/en/pricing) |
| Perplexity | Profile financial API not found | Project console for usage/billing. The documented Enterprise Analytics API covers Computer with a dedicated key, rather than the bridge's Sonar/Agent key balance. | [Projects & Billing](https://docs.perplexity.ai/docs/getting-started/projects), [Computer Analytics](https://docs.perplexity.ai/docs/admin/computer-analytics-api) |
| NVIDIA | Not found | No public balance route identified for the `integrate.api.nvidia.com` profile. Do not infer budgets from inference responses or Cloud Functions management. | [API reference](https://docs.api.nvidia.com/nim/reference) |
| BytePlus LAS | Unconfirmed | No budget route using the bridge's LAS key identified. Cloud/ModelArk billing does not establish that contract; a separate integration requires its own verification. | [LAS](https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced) |
| Custom Ollama | No external budget for local execution | A local server has no financial account to query. Any Cloud service needs its own contract. | [Local API](https://docs.ollama.com/api/introduction) |

`bridge.models_dev` enriches model metadata; it is not a billed provider account in this
catalog. Custom OpenAI-compatible connections cannot imply a billing API: they require an
explicitly registered reader.

The initial Fireworks spending-ceiling integration was removed: subtracting spend from
the ceiling incorrectly presented a spending allowance as available funds. A synthetic
million-dollar ceiling reproduced this defect before correction. The catalog no longer
declares a Fireworks reader; no balance panel or dedicated link is displayed in its
configuration. The interface also ignores the old support flag to avoid
redisplaying a gauge from an older backend. Former account-discovery and monthly-quota
tests are replaced by the guarantee that no spending ceiling substitutes for a balance.
There is no fallback to estimated spend or private web sessions.
See [decision 0146](../../../project/decisions/0146-provider-usage-snapshots.md)
and the [user journey](../user/navigation.md).

Readers are covered by `back/app/llm/tests/test_provider_quotas.py` and existing ChatGPT coverage
in `back/bridge/openai/tests/test_quota.py`. Credit field names and types were confirmed in
development without retaining balances, identifiers or personal account data. Component
scenarios cover additional balances alongside subscription windows, zero, errors, retry and
late responses. The assembled `e2e/specs/provider-usage.spec.mjs` journey covers
Fireworks on desktop and mobile: no balance panel or spending gauge, accessible
configuration and reopening. It also covers ChatGPT credits alongside subscription windows,
refresh, errors and recovery.
