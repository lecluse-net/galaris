# ADR 0019 — Apprentissage Dream fondé sur des preuves

- Statut : Superseded by ADR 0047
- Date : 2026-07-31

## Contexte

L’extraction Dream des Tasks retient les faits et procédures explicitement formulés, mais un
statut terminal et une réponse finale ne suffisent pas à établir qu’une stratégie est bonne ou
mauvaise. Une expérience réutilisable doit rester vérifiable, privée au propriétaire, distincte
des souvenirs ordinaires et rappelée sans évincer tout le contexte courant.

## Décision

`memory.reflect_task_outcome` est un mécanisme Dream séparé, exécuté après
`memory.extract_task`. Il construit depuis les surfaces publiques de Task, Goal et Memory un
instantané déterministe, borné et expurgé : résultat terminal, erreurs normalisées, tentatives,
résultats d’outils observables, enfants terminaux, jugement de cycle, correction humaine tardive,
route de modèle et UUID des mémoires réellement injectées. Prompts système, arguments d’outils et
raisonnement privé en sont exclus.

Un filtre déterministe écarte avant tout appel LLM les succès non vérifiés, interruptions attendues
et incidents transitoires isolés. Le modèle Dream ne reçoit aucun outil et produit des leçons
structurées dont chaque affirmation référence une preuve fournie. Le serveur valide les références,
borne la confiance et choisit le type cognitif. La sortie et les preuves sont checkpointées avant
toute écriture.

L’identité durable d’un apprentissage est
`(memory.reflect_task_outcome, task_outcome, <task UUID>:<empreinte des preuves>)`. Une preuve
tardive matérielle crée une nouvelle empreinte ; un rescan identique ne produit rien. Un témoin
d’activation stable exclut les Tasks déjà terminales au premier passage : aucun backfill
historique n’est lancé implicitement.

Les leçons sont acquises par `app.memory` avec `memory_role=experience`, provenance et clé
d’idempotence. Leur consolidation ne cible que d’autres expériences. Une fusion accumule le nombre
de preuves et la confiance bornée ; plusieurs confirmations peuvent promouvoir une leçon épisodique
en procédure, sans modifier les ACL ni contourner les révisions.

Le réglage durable `DREAM_EXPERIENCE_MODE`, stocké dans `core.params`, possède quatre modes :

- `off` : aucun apprentissage ni injection ;
- `observe` : preuves et propositions visibles dans les reçus, sans écriture Memory ;
- `learn` : consolidation active, sans injection ;
- `active` : consolidation et rappel actifs.

Le passage d’`observe` à `learn` réutilise le checkpoint sans second appel LLM. Le rappel actif
réserve, dans les budgets globaux existants, jusqu’à `DREAM_EXPERIENCE_MAX_ITEMS` et
`DREAM_EXPERIENCE_MAX_CHARS`. Il est calculé une fois par décision de planning et une fois par
exécution, puis séparément pour chaque enfant. Les expériences sont présentées dans une section
distincte qui rappelle la priorité des instructions courantes et des sources autoritatives.
`MemoryUsage` distingue `experience_planning` et `experience_execution` uniquement pour les items
effectivement injectés.

## Conséquences

- L’expérience reste dans le stockage, les ACL, l’audit, l’oubli et la déduplication de Memory.
- Une correction tardive peut enrichir une Task sans boucle de retraitement.
- Le mode par défaut est `off`; l’activation progressive reste une décision d’exploitation.
- Aucune table statistique ni changement de schéma n’est nécessaire.
- L’attribution causale demeure hors contrat : les mesures rapprochent usage et résultat sans les
  confondre.

## Preuves dans le code

`back/app/dream/outcome_evidence.py`,
`back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/task/outcome.py`,
`back/app/memory/context.py`, `back/app/memory/acquisition_service.py`,
`back/app/agent/planner_service.py`, `front/core/params/` et leurs tests.
