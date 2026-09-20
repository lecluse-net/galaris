# ADR 0052 — Effort de raisonnement indépendant du palier de modèle

- Statut : Accepted
- Date : 2026-08-25
- Mise à jour : 2026-09-05

## Contexte

Les quatre paliers texte définis par l’ADR 0050 sélectionnent une capacité et un coût de modèle.
Ils ne décrivent pas l’effort de raisonnement demandé à ce modèle. Confondre les deux empêcherait
notamment un déploiement local d’affecter le même LLM aux quatre paliers tout en variant uniquement
son effort, ou un déploiement cloud de combiner librement modèles et efforts.

L’effort d’exécution `standard` ou `high` d’une Task reste une troisième notion : il pilote la
stratégie agentique et le choix éventuel du palier texte `high`, pas directement le paramètre de
raisonnement d’un fournisseur.

## Décision

Chaque profil LLM porte un effort nullable pour chacun de ses quatre paliers texte :
`text_ultra_low_reasoning_effort`, `text_low_reasoning_effort`,
`text_standard_reasoning_effort` et `text_high_reasoning_effort`. Les valeurs canoniques sont
`none`, `low`, `medium`, `high`, `xhigh` et `max`. L’ancienne valeur `minimal` est lue comme
un alias de compatibilité de `low`, puis n’est plus réémise. `NULL` signifie « automatique » :
Galaris n’impose alors aucune valeur et conserve le choix du harness ou du fournisseur.

Les capacités spécialisées (vision, document, audio, vidéo, image, transcription et embeddings)
n’ont pas de colonne d’effort. Lorsqu’un usage métier sélectionne un palier texte, il reçoit
toujours l’effort associé à ce même palier. Le repli de l’exécuteur `high` vers `standard` emporte
donc également l’effort `standard`.

Pour une exécution agentique, le modèle et son effort sont résolus ensemble puis figés dans
l’identité du run. Les appels passant par le gateway LLM appliquent cette valeur par défaut et la
tracent dans `llm_calls.reasoning_effort`. Un harness peut la remplacer uniquement avec le marqueur
explicite `X-Galaris-Force-Reasoning-Effort` ou son équivalent dans le corps Galaris. Un harness
externe qui réalise lui-même l’inférence sans passer par le gateway reste hors du contrôle de
Galaris.

Les protocoles fournisseurs reçoivent leur forme native (`reasoning_effort` pour Chat Completions,
`reasoning.effort` pour Responses). Les harnesses gérés traduisent les valeurs canoniques vers les
niveaux qu’ils supportent ; ils n’injectent rien en mode automatique.

## Conséquences

- Un même LLM peut occuper les quatre paliers avec quatre efforts différents.
- Le palier de modèle, l’effort de raisonnement et l’effort d’exécution d’une Task restent
  observables et modifiables indépendamment.
- Une modification de profil ne change pas l’effort d’un run déjà démarré.
- Les valeurs effectivement appliquées sont auditables dans les appels LLM.
- Les fournisseurs qui ne supportent pas toute l’échelle utilisent la traduction documentée par
  leur bridge ; aucune traduction ne modifie le palier du modèle.

## Preuves dans le code

`back/app/llm/profile_models.py`, `back/app/llm/reasoning.py`,
`back/app/agent/model_resolver.py`, `back/app/llm/proxy_service.py`,
`back/app/harnesses/openai_client.py` et `front/app/llm/components/LlmUsageManager.vue`.
