# ADR 0045 — Runs agentiques portables et reprise sûre vis-à-vis des effets

- Statut : Accepted
- Date : 2026-08-21

## Contexte

Le contrat historique `AgentRunRequest` mélangeait les données d'exécution avec des callbacks
Python de progression et de checkpoint. Il convenait aux drivers chargés dans le processus
Galaris, mais ne constituait pas une frontière transportable pour un futur harnais externe.
L'identité d'un même travail pouvait en outre changer lors d'une reprise, les traces des drivers
n'avaient pas de sémantique commune et le checkpoint interne ne distinguait pas assez précisément
un appel de lecture interrompu d'un effet non idempotent dont l'issue était inconnue.

## Décision

`app.agent` possède désormais deux représentations complémentaires :

- `AgentRunRequest` reste le contrat local remis aux drivers chargés dans le processus ; son
  `AgentRunControl` contient les callbacks locaux et n'est jamais sérialisé ;
- `AgentRunEnvelopeV1` est la projection bornée, sérialisable et sans secret destinée aux futures
  frontières réseau ou processus. Elle fige l'objectif, le modèle, la cible résolue, les capacités,
  les limites, les URI canoniques et les empreintes utiles, sans modèle ORM, chemin hôte, credential
  ni fonction Python.

L'identité canonique corrèle `task_id`, `attempt_id`, `run_id` logique et `runtime_run_id`. Le
`run_id` est conservé à travers les reprises compatibles ; chaque lease du scheduler reste lié à
son propre `TaskAttempt`. La cible sépare les capacités d'exécution des capacités de gestion du
cycle de vie afin qu'un runtime puisse être exécutable sans être administrable par Galaris, ou
l'inverse.

La façade valide l'enveloppe avant tout appel de driver et publie des `AgentRunEventV1` ordonnés.
Seuls les événements sémantiques sont persistés dans la tentative : démarrage, fin, outil terminé
ou échoué, erreur et annulation. Les deltas de tokens restent éphémères et la projection durable
borne le texte, les outils et les champs libres. Le résultat de Task reste la source autoritative.

Le checkpoint du harnais interne passe en version 2 et journalise pour chaque appel : signature,
arguments, identifiant d'appel, politique d'effet et politique de concurrence. À la reprise :

- un appel de lecture ou idempotent interrompu est refermé dans l'historique comme résultat
  interrompu et peut être redemandé explicitement ;
- un effet non idempotent démarré sans résultat durable devient `outcome_unknown` et bloque le
  rejeu automatique ;
- un résultat terminé est rejoué depuis le journal lorsque la même signature réapparaît.

Précision du 2026-09-12, renforcée par l’[ADR 0093](0093-tool-outcome-evidence-and-console-recovery.md) :
`ModelRetry` ne prouve pas l’absence d’effet. Seul un rejet prouvé avant dispatch peut être
acquitté avec le statut `failed`. Une erreur textuelle historique ne suffit pas à réparer le
journal ; une erreur de validation structurée doit correspondre au nom et à l’identifiant
d’appel. La console v2 peut réconcilier un résultat distant grâce à un UUID persisté avant
lancement. Une issue encore inconnue reste bloquée, y compris lors d’un retry manuel.

La concurrence est désactivée par défaut. Une fonction doit déclarer explicitement une politique
`safe` pour s'exécuter en parallèle ; toute fonction inconnue ou mutante reste `exclusive`. Un
writer attend les lecteurs actifs, empêche de nouveaux lecteurs de le dépasser et les résultats
sont rendus au modèle dans l'ordre d'invocation. L'historique est compacté selon la fenêtre du
modèle, tout en conservant atomiques les appels d'outils et leurs retours.

Enfin, `AgentUsage` normalise tokens, requêtes, appels d'outils et coût. La qualité de chaque mesure
est explicite (`exact`, `estimated`, `partial` ou `unknown`) ; l'absence de télémétrie native n'est
jamais présentée comme une mesure exacte.

## Conséquences

- un nouveau driver peut être vérifié par le testkit de conformité sans dépendre de son transport ;
- l'intégration ultérieure d'un harnais tel que DeepSeek Harness pourra adapter une enveloppe stable
  au lieu de contourner la façade agentique ;
- les reprises préfèrent un arrêt visible à la répétition silencieuse d'un effet externe ambigu ;
- seule une petite première liste d'outils de lecture est parallélisée ; l'élargissement exige une
  revue explicite de leur idempotence et de leurs dépendances transactionnelles ;
- aucun nouveau moteur, token de capacité ou transport distant n'est introduit par cette décision ;
- aucune migration de schéma n'est requise : identité et timeline utilisent les JSONB existants des
  Tasks et `TaskAttempt`.

## Preuves dans le code

`back/app/agent/contracts.py`, `back/app/agent/facade.py`,
`back/app/agent/driver_testkit.py`, `back/app/task/agent_adapter.py`,
`back/app/harness/checkpoint.py`, `back/app/harness/runtime.py`,
`back/app/tools/mcp_loader.py`, `back/bridge/hermes/executor.py` et leurs tests de contrat.
