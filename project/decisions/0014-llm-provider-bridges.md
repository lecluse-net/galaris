# ADR 0014 — Fournisseurs IA comme bridges

- Statut : Accepted
- Date : 2026-07-26

## Contexte

`app.llm` portait historiquement à la fois les contrats canoniques de Galaris et des détails
propres à des produits externes : catalogue de fournisseurs, découverte de ressources, OAuth,
formats audio, transport Responses/SSE et métadonnées publiques. Ajouter un fournisseur imposait
donc de modifier le domaine central et plusieurs branches conditionnelles.

Le protocole OpenAI-compatible reste un contrat d’appel générique utilisé par Galaris. Il ne
constitue pas, à lui seul, un bridge de fournisseur.

## Décision

`app.llm` possède les façades et registres stables :

- profils et configuration de connexion ;
- découverte de ressources et gestion de modèles ;
- métadonnées, transcription, synthèse vocale et streaming ;
- authentification externe, adaptation du transport de chat et politiques de runtime ;
- protocole OpenAI-compatible générique pour chat, embeddings, STT et TTS.

Chaque produit ou outil tiers possède un package `back/bridge/<fournisseur>`. Le package racine
enregistre son `ProviderProfile` et uniquement les façades qu’il implémente. Les imports vont du
bridge vers les contrats publics de `app.llm`; `app.llm` n’importe jamais un bridge.

La racine de composition charge les bridges déclarés dans `back/modules.py` avant de construire
l’API. L’ajout d’un fournisseur consiste donc à créer son bridge, déclarer son profil, enregistrer
ses services et ajouter le module à la composition. Aucun nouveau type fermé ni branche de produit
ne doit être ajouté à `app.llm`.

Le frontend suit la même frontière pour les types de connexion personnalisés : `front/app/llm`
expose le contrat de contribution et découvre les fichiers `front/bridge/*/llmProvider.ts`.

Les adaptations OpenRouter, ElevenLabs, Google, Azure, Ollama et OpenAI/ChatGPT sont ainsi
propriétaires de leurs endpoints, en-têtes, payloads, OAuth et variantes de streaming.
`bridge.models_dev` possède séparément l’accès au catalogue public models.dev.

## Conséquences

- Le domaine LLM reste stable lors de l’ajout d’un fournisseur.
- Les protocoles communs sont testables indépendamment des produits.
- Les migrations de compatibilité propres à un fournisseur sont elles-mêmes des hooks de bridge.
- Une intégration peut exposer plusieurs services avec un seul profil.
- Une nouvelle nature de service nécessite une nouvelle façade générique dans `app.llm`; un
  nouveau fournisseur d’un service existant n’en nécessite pas.
- Le bootstrap doit charger explicitement les bridges avant toute lecture du catalogue.

## Références et preuves

- Contrats : `back/app/llm/provider_facade.py`.
- Composition : `back/modules.py`, `back/main.py`, `back/app/llm/dbadmin.py`.
- Contribution frontend : `front/app/llm/customProviderTypes.ts`.
- Bridges fournisseurs : `back/bridge/openrouter`, `openai`, `elevenlabs`, `google`,
  `azure_speech`, `ollama` et les profils voisins.
- Flux : `docs/fr/architecture/flows/llm-provider-bridges.md`.
- Contrôle : `back/scripts/architecture_check.py`.
