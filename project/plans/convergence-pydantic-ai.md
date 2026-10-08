# SDK et fournisseurs — extensions restantes

- Statut : `partial`
- Revue des sources : 2026-10-08.
- Contrats réalisés : [0095](../decisions/0095-pydantic-ai-request-ownership.md) et
  [0097](../decisions/0097-durable-inference-lifecycle.md).

Construction SDK, profil Codex/OAuth, historique Responses et cycle durable sont acquis.
Les [preuves historiques](../audits/2026-09-13-pydantic-ai-request-ownership.md)
ne qualifient pas automatiquement une future version.

## Travaux ouverts

| Périmètre | Travail et réception |
|---|---|
| Métadonnées OpenRouter | Conservation/fraîcheur de canonical_slug, supported_parameters et variantes d'endpoint ; ne pas déduire valeurs/contraintes croisées ni imposer require_parameters partout. |
| Transport Codex alternatif | Évaluer le bénéfice d'un SDK natif avec credentials Galaris ; si retenu, préserver renouvellement, identité, checkpoints, compaction et éléments opaques de Responses. |
| Réglages/comptabilité | Projection bornée demandé/résolu/envoyé avec reasoning_effort canonique, sans contenu sensible ; publication UI distincte de comptabilité qualifiée. |
| Autres entrées | Extensions embeddings, realtime et média par manque d'un consommateur, coordonnées avec les inférences durables ; adaptateurs natifs déjà réalisés dans l'ADR 0126 préservés. |
| Décisions spécialisées différées | API TypeSafe directe, adaptateurs locaux dont Laya, services conteneurisés CPU/GPU, démarrage à froid et contention ; besoin et contrat provider à vérifier avant réalisation. |

La qualification spécialisé/texte et les nouveaux usages expérimentaux appartiennent au
[Lab](lab-evaluation-mecanismes-ia.md), après retrait du plan de modèles de décision.
Un provider de décision supplémentaire implémente le port public ; aucune dépendance
du workflow métier à son client ni provider cloud implicite.

## Réception et clôture

Provider explicite, identifiant de modèle opaque, restrictions déclaratives ;
pas d'heuristique de famille/version. Préserver sorties structurées/validateurs,
tools/URI/droits, budgets/coûts/corrélation, annulation et absence de rejeu ambigu.

Vérifier chaque capacité sur version verrouillée au moment de son extension.
Réutiliser make tests-providers et suites LLM/harnais/agent/Goal ; comptes réels qualifiés
séparément. Retirer les extensions réalisées/transférées ; les
[inférences durables](llm-calls-durables.md) gardent leur cycle et leurs propres évolutions.
