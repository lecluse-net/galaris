# Convergence SDK — métadonnées, protocoles et surfaces restantes

- Statut : `partial`
- Revue documentaire : 2026-10-01
- Contrats réalisés : [0095](../decisions/0095-pydantic-ai-request-ownership.md) et
  [0097](../decisions/0097-durable-inference-lifecycle.md).

Les [preuves historiques](../audits/2026-09-13-pydantic-ai-request-ownership.md) restent dans
l'audit ; le cycle de vie durable et ses extensions ont leur [plan propre](llm-calls-durables.md).

## Travaux restants

1. **OpenRouter et métadonnées.** Définir conservation et fraîcheur de `canonical_slug`,
   `supported_parameters` et des variantes d'endpoint avant leur usage. Ces champs ne
   prouvent pas toutes les valeurs permises ni les contraintes croisées. Conserver le profil
   officiel du provider ; ne pas imposer `require_parameters` à toutes les routes.
2. **Intégration Codex native alternative.** Évaluer l'intérêt d'un transport SDK natif
   avec les credentials Galaris avant de remplacer l'adaptation actuelle. Le profil Codex,
   OAuth et la reprise Responses appartiennent déjà à 0095 ; ils ne sont plus à réaliser.
   Toute alternative retenue conserve renouvellement, identité, checkpoints, compaction
   et éléments opaques, sans faire perdre un historique Responses.
3. **Réglages et comptabilité.** Définir une projection bornée des réglages demandés,
   résolus et envoyés ; garder `reasoning_effort` canonique et les contenus sensibles
   hors de cette projection. Qualifier le découplage entre publication UI et comptabilité.
4. **Autres surfaces.** Compléter les intégrations embeddings, realtime et génération/analyse
   média selon les manques de chaque consommateur, dans des lots distincts coordonnés avec
   le plan d'inférences durables. Les entrées natives Chat/Task sont portées par
   l'[ADR 0126](../decisions/0126-native-multimodal-inputs.md) ; restent notamment les formats
   et fournisseurs non pris en charge par ses adaptateurs.

## Garanties de réception

Provider sélectionné explicitement et identifiant de modèle opaque ; aucune nouvelle
heuristique de famille ou de version. Les restrictions propres à l'endpoint restent
déclaratives. Préserver sorties structurées, validateurs, outils, URI, limites, budgets,
autorisations, coûts, corrélation, annulation et absence de rejeu d'effets ambigus.

Vérifier les capacités sur la version verrouillée au moment de chaque extension. Un échec
du SDK ne justifie pas de retirer un scénario de compatibilité utile ; les éléments inconnus
ne sont pas remplacés par des garanties inventées.
La qualification des protocoles et du raisonnement accompagne chaque changement retenu ;
elle ne constitue pas un lot d'implémentation permanent des intégrations déjà réalisées.

## Qualification et clôture

Réutiliser `make tests-providers`, les suites LLM/harnais/agent/Goals, les types et
l'architecture. Les comptes externes sont qualifiés séparément ; une publication demandée
requiert `make validate` sur l'instantané final.

Supprimer ce plan une fois les extensions retenues réalisées ou transférées. Les contrats
du SDK et du runtime ne doivent pas être dupliqués dans un historique d'implémentation.
