# ADR 0061 — Responses natif pour le harnais interne

- Statut : Accepted
- Date : 2026-09-03

## Contexte

Le harnais interne Pydantic AI transformait tous ses échanges en Chat Completions, y compris pour
les modèles dont le fournisseur expose le protocole Responses. Cette conversion préservait le texte
et les appels d'outils, mais pouvait perdre les objets de raisonnement, leurs identifiants et la
continuité native entre les tours. Un même modèle et un même effort de raisonnement pouvaient donc
produire une exécution moins cohérente qu'un runtime utilisant Responses de bout en bout.

## Décision

Un `ProviderProfile` déclare explicitement sa capacité `supports_responses` et son bridge enregistre
une `ProviderResponsesPolicy`. Cette politique décide au niveau du modèle si Responses est
réellement disponible, fournit le profil Pydantic AI adapté au modèle routé et limite les extensions
de protocole envoyées (`store`, contexte/résumé de raisonnement, identifiants et compaction). Le
harnais sélectionne `OpenAIResponsesModel` uniquement lorsque les deux déclarations concordent et
conserve l'adaptateur Chat Completions comme repli.

Les réglages obligatoires de cette politique sont attachés au modèle Pydantic AI lui-même. Ils
s'appliquent ainsi à toutes les façades internes qui le consomment — exécuteur, appels structurés,
Dream, Lab et conversations — même lorsqu'un appel ne fournit que ses réglages locaux, par exemple
la température.

L'adaptateur Responses traverse le proxy en processus de `app.llm` : autorisation, corrélation,
traces, usage et coût restent donc identiques aux autres appels Galaris. Le proxy accepte les deux
opérations natives `create` et `compact`; les bridges choisissent leur endpoint sans que
`app.harness` connaisse un produit particulier.

OpenAI/Codex utilisent `store=false`, le contexte de raisonnement sur tous les tours, les résumés et
le replay des identifiants. xAI utilise `store=false`, demande et rejoue le raisonnement chiffré.
Les autres fournisseurs ne reçoivent que les extensions qu'ils documentent ; les éléments de
raisonnement textuels restent néanmoins rejoués dans l'historique Responses. Les checkpoints
Pydantic AI conservent ces données ainsi que les identifiants des appels et retours d'outils.

La capacité est activée pour OpenAI API, ChatGPT/Codex, OpenRouter, Fireworks, xAI, Groq, Hugging
Face Inference Providers, NVIDIA NIM et Perplexity Agent API. DeepSeek ne l'active que pour les
modèles `deepseek-v4-*`, conformément à son contrat. Perplexity ne l'active que pour les identifiants
Agent API qualifiés `provider/model`; les anciens modèles Sonar non qualifiés restent sur Chat
Completions. Together, Mistral, Cohere, Cerebras, Google et Anthropic gardent Chat Completions ou
leur protocole existant tant qu'aucune surface Responses compatible n'est déclarée.

Lorsque l'historique dépasse le seuil dérivé de la fenêtre du modèle, OpenAI/Codex et xAI compactent
le préfixe ancien via `/responses/compact`, gardent les deux blocs récents et atomiques, puis
poursuivent avec l'élément de compaction chiffré. Les fournisseurs sans endpoint de compaction
documenté utilisent le bornage local. Un échec de compaction native déclenche ce même repli sans
rendre le run irrécupérable.

## Conséquences

- Les modèles compatibles conservent leur continuité de raisonnement native entre outils et tours
  sans contourner la gouvernance LLM de Galaris.
- La sélection et les particularités de protocole sont déclarées par les bridges ;
  `app.harness` ne contient aucune branche sur un fournisseur.
- Une compaction est un appel LLM distinct, corrélé et comptabilisé, mais ne reçoit pas les champs
  de configuration propres à la création d'une réponse.
- Les fournisseurs OpenAI-compatibles qui ne déclarent pas Responses gardent le comportement Chat
  Completions existant.
- Aucun changement de schéma ni migration de données n'est requis.

## Preuves dans le code

`back/app/llm/provider_catalog.py`, `back/app/llm/pydantic_ai_utils.py`,
`back/app/llm/proxy_service.py`, `back/app/harness/runtime.py`,
`back/bridge/openai/codex.py` et leurs tests de contrat.

## Références fournisseurs

- OpenRouter : <https://openrouter.ai/docs/api/api-reference/responses/create-responses>
- Fireworks : <https://docs.fireworks.ai/api-reference/post-responses>
- DeepSeek : <https://api-docs.deepseek.com/api/create-response/>
- xAI : <https://docs.x.ai/developers/model-capabilities/text/comparison> et
  <https://docs.x.ai/developers/advanced-api-usage/context-compaction>
- Groq : <https://console.groq.com/docs/responses-api>
- Hugging Face : <https://huggingface.co/docs/inference-providers/en/guides/responses-api>
- NVIDIA NIM : <https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html>
- Perplexity : <https://docs.perplexity.ai/docs/agent-api/openai-compatibility>
- Together (absence explicite) :
  <https://docs.together.ai/docs/inference/openai-compatibility>
