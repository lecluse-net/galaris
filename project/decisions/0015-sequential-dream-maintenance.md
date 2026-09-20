# ADR 0015 — Entretien opportuniste séquentiel par `app.dream`

- Statut : Accepted
- Date : 2026-07-26

## Contexte

Plusieurs enrichissements utiles ne doivent pas ralentir une conversation, une Task agentique ou
le mode Voice : extraction de souvenirs depuis l'historique, rapprochement ultérieur de souvenirs,
détection de doublons et autres travaux de consolidation. Les exécuter dans un observer terminal
limite le nombre de souvenirs, ajoute du travail à chaque terminaison et ne garantit pas le
rattrapage de l'historique existant.

Ces traitements n'ont pas besoin des outils, du planner, du dispatcher ni d'un `AgentDriver`. Leur
faire créer des Tasks ordinaires imposerait toute l'artillerie agentique à de petites inférences
locales structurées. À l'inverse, une collection de workers indépendants rendrait la priorité
interactive, la concurrence et la reprise difficiles à raisonner.

## Décision

`app.dream` possède l'unique boucle d'entretien opportuniste. Cette boucle est un composant runtime
racine non critique supervisé par `core.runtime`. Elle appelle les `DreamMechanism` enregistrés
dans un ordre déterministe et strictement séquentiel. Chaque mécanisme traite au plus un sujet par
cycle et retourne immédiatement lorsqu'il n'a aucun travail.

Avant un cycle et avant chaque mécanisme, Dream vérifie qu'aucune conversation Voice et aucun
travail agentique actif ne sont présents. `app.voice` expose son état réel et publie une transition
en mémoire lors du début d'un appel. Dream annule alors immédiatement sa sous-tâche courante sans
arrêter sa boucle racine. L'appel Voice ne dépend pas de Dream et n'attend aucun de ses traitements.

PostgreSQL conserve un `DreamReceipt` par
`(mechanism_key, subject_kind, subject_id)`. L'absence de ligne signifie que le
sujet n'a jamais été examiné. Un succès avec `result_count=0` signifie qu'il a été examiné sans
produire de donnée. Les statuts, tentatives, disponibilités et leases permettent les reprises après
erreur ou arrêt. L'identifiant stable d'un mécanisme ne change pas et un sujet déjà examiné n'est
pas rescanné implicitement lors d'une évolution du code.

La préparation et l'application sont séparées. La sortie structurée d'un modèle est persistée dans
le reçu avant les effets métier. Une reprise applique donc le même résultat avec des clés
d'idempotence stables au lieu de relancer silencieusement le modèle après un effet partiel.

Les mécanismes de classement affectent messages, rounds conversationnels, Tasks et sessions Voice
à des Topics globaux. Les extracteurs `memory.extract_task` et
`memory.extract_conversation_round` attendent ce classement, puis utilisent une sortie structurée unique
`CREATE`, `LINK` ou `IGNORE`. Aucun outil, toolset, capability ou serveur MCP n'est enregistré.
Les souvenirs retenus sont écrits par la façade gouvernée d'`app.memory`, avec provenance,
filtrage des secrets et idempotence.

`skill.learn_task_outcome` apprend uniquement depuis des preuves observables et bornées ; depuis
l'ADR 0047, ses effets appartiennent aux skills dédiées et non à Memory.
`memory.project_process` et `memory.forget_stale` appliquent encore leurs règles déterministes dans
la boucle. La maintenance des `MemoryLink`, y compris les suggestions thématiques, appartient en
revanche à `app.memory.automation` : chaque succès Dream déclenche un job ciblé et un sweep global
est admis une fois par jour à charge nulle. Ces jobs n'ont ni `DreamReceipt`, ni jauge Dream, ni
configuration LLM.

`app.task` reste propriétaire des Tasks et de leur scheduler. `app.agent` et les drivers ne
participent jamais à un cycle Dream. Les futurs mécanismes restent dans `app.dream/mechanisms` et
appellent les surfaces publiques des domaines dont ils lisent ou modifient les données.

Une surface de suivi en lecture seule expose l'état instantané et les reçus persistés aux
utilisateurs disposant de `TASK_ACCESS`. La page frontend ne consulte cette surface que lorsqu'elle
est ouverte. Elle n'ajoute ni worker, ni événement durable pour les cycles vides, ni dépendance
dans le chemin Voice.

## Conséquences

- Voice et les Tasks actives sont toujours prioritaires sur l'entretien.
- Une seule inférence Dream peut être active dans un processus.
- Toutes les Tasks terminales, y compris historiques, obtiennent progressivement un témoin.
- Un petit modèle local sans tool calling ni JSON natif peut être utilisé.
- Le modèle Dream doit être configuré explicitement ; sans lui, les mécanismes d'extraction ne
  réclament aucun sujet, tandis que la réconciliation des liens continue dans `app.memory`.
- Les liens déduits ne consomment aucun token Dream ; seuls le classement, l'extraction sémantique
  et l'apprentissage utilisent le petit modèle configuré.
- L'annulation libère immédiatement la coroutine et la requête HTTP associée. Une isolation
  matérielle supplémentaire reste nécessaire si un serveur local ne libère pas effectivement ses
  ressources lors de la fermeture de la requête.
- Les traitements nécessitant une inférence enrichissent le registre séquentiel ; les projections
  massives déterministes réutilisent le worker durable Memory.

## Preuves dans le code

`back/app/dream/`,
`back/app/llm/structured_service.py`, `back/app/voice/call_manager.py`,
`back/app/task/activity.py`, `back/main.py`, `front/core/params/`,
`front/app/dream/`, `front/app/llm/components/LlmUsageManager.vue` et leurs tests.
