# ADR 0050 — Quatre niveaux partagés pour les modèles texte

- Statut : Accepted
- Date : 2026-08-24

## Contexte

Un profil LLM sélectionnait séparément le modèle du dispatcher, du briefing, de l’exécuteur,
de la conversation rapide, de l’exécuteur high, du planner, du suivi des Goals, du Lab IA et de
Dream. Cette granularité rendait chaque profil coûteux à comprendre et à configurer alors que ces
usages expriment principalement quatre niveaux de coût, latence et capacité.

Les modèles spécialisés ne sont pas interchangeables de cette manière : vision, document, audio,
vidéo, génération d’image, transcription et embeddings exigent des capacités propres.

## Décision

Chaque profil LLM porte exactement quatre sélections de modèle texte : `text_ultra_low_llm_id`,
`text_low_llm_id`, `text_standard_llm_id` et `text_high_llm_id`. Les mécanismes utilisent la
correspondance statique suivante :

| Niveau | Usages Galaris | Familles reconnues |
|---|---|---|
| `ultra-low` | Dream | Claude Haiku |
| `low` | dispatcher, conversation rapide | Claude Sonnet, GPT Luna |
| `standard` | briefing, exécuteur, suivi des Goals | Claude Opus, GPT Terra |
| `high` | exécuteur high, planner, analyse et jugement du Lab IA | Claude Fable, GPT Sol |

Les gateways résolvent les noms canoniques de niveau et les familles Claude/Codex comme alias du
profil effectif. Un code LLM configuré explicitement possède toujours priorité sur un alias.
L’exécuteur high conserve son repli explicite vers le niveau `standard` lorsque `high` est vide ;
les autres mécanismes ne changent pas de niveau implicitement.

Les sept colonnes spécialisées restent inchangées. L’exclusivité du profil effectif décidée par
l’ADR 0039 reste également inchangée : un agent avec un profil personnel ne complète jamais une
valeur vide depuis le profil courant.

Les neuf anciennes colonnes texte sont supprimées directement. Aucun backfill ni choix automatique
n’est effectué : les quatre nouvelles valeurs sont volontairement vides et doivent être
reconfigurées par l’opérateur après synchronisation.

## Conséquences

- Un profil expose onze sélections au lieu de seize : quatre niveaux texte et sept capacités
  spécialisées.
- Plusieurs mécanismes deviennent volontairement solidaires d’une même sélection de modèle.
- Vider un niveau affecte tous ses usages ; l’absence d’un modèle continue d’être traitée selon le
  contrat de chaque mécanisme.
- Les traces conservent leur purpose métier (`dispatcher`, `planner`, `goal`, etc.) même lorsque le
  modèle provient d’un niveau partagé.
- Une mise à niveau depuis l’ancien schéma perd les neuf sélections texte, par décision explicite.

## Preuves dans le code

`back/app/llm/model_usages.py`, `back/app/llm/profile_models.py`,
`back/app/llm/proxy_service.py`, `back/bridge/claude_agent/default-agent/server.py.txt` et
`front/app/llm/components/LlmUsageManager.vue`.
