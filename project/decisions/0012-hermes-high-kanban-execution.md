# ADR 0012 — Exécution Hermès `high` par Kanban

- Statut : Superseded par [ADR 0013](0013-disable-hermes-high-kanban.md)
- Date : 2026-07-22

## Contexte

Les niveaux `standard` et `high` ne sélectionnaient jusqu’ici qu’un modèle d’exécution. Pour le
harnais interne, `high` active aussi un briefing Galaris avant l’exécuteur Pydantic AI. Appliquer ce
même briefing à Hermès dupliquerait son propre raisonnement et ne profiterait pas de son runtime de
travail durable.

Hermès Agent `v2026.7.20` fournit un Kanban persistant, un dispatcher, des workers par profil, des
tentatives et des résumés de passation. Le mode natif Galaris peut joindre les routes du plugin sur
le dashboard partagé. Le mode historique ne doit pas exposer ces routes directement : il possède
déjà un bridge hôte authentifié capable d’exécuter une liste bornée de commandes dans le conteneur
de l’agent.

Galaris possède toutefois déjà son autorité métier : la Task PostgreSQL, son lease, ses tentatives,
son annulation et son résultat. Faire de la carte Hermès une deuxième Task autoritative créerait
deux schedulers concurrents et des transitions impossibles à réconcilier.

## Décision

Le descripteur de chaque driver déclare une stratégie pour chaque effort. Cette stratégie est
résolue avec le modèle, puis figée dans l’`AgentRunRequest` :

| Driver | `standard` | `high` | Briefing Galaris |
|---|---|---|---|
| `internal` | exécution directe | exécution directe | `high` uniquement |
| `hermes` | `/v1/runs` direct | Kanban Hermès | jamais |

La façade ne transmet à Hermès ni `BriefingResult` ni texte de briefing, même si une ancienne Task
en contient encore un. Le scheduler `app.task`, ses phases et sa règle de sérialisation par agent
restent inchangés.

Pour un run Hermès `high`, le driver :

1. construit une carte autonome contenant l’objectif, le contexte et les identifiants Galaris
   `task_id`, `run_id` et `llm_id` ;
2. persiste un checkpoint de création avant l’appel distant et emploie une clé d’idempotence ;
3. crée puis distribue la carte, observe ses états et persiste son identifiant ;
4. transforme `done` en succès et `blocked`, `review` ou `archived` en échec explicite ;
5. produit le même contrat `AgentEvent* + ExecutionResult` que les autres exécuteurs ;
6. reclaim puis archive la carte en cas d’annulation.

La carte est un handle de runtime subordonné. La Task PostgreSQL reste seule propriétaire de
l’état métier final. Les tentatives Hermès ont lieu à l’intérieur de la carte ; les tentatives
Galaris ne commencent qu’après son état terminal.

Le checkpoint conserve aussi le transport (`native` ou `legacy`), le board, le profil, le répertoire de travail
et la clé d’idempotence. Un checkpoint Kanban reprend la même carte. Pour préserver les exécutions
déjà en vol lors du déploiement, un checkpoint Hermès historique sans stratégie reste interprété
comme un run direct.

En mode natif, le manager utilise les routes officielles `/api/plugins/kanban/*` sur le board
`default`. En mode historique, les nouvelles routes authentifiées du bridge traduisent vers les
commandes CLI `create`, `show`, `dispatch`, `reclaim` et `archive` dans l’instance concernée. Les
Compose générés et le conteneur natif épinglent `nousresearch/hermes-agent:v2026.7.20` ; une
surcharge doit fournir un contrat compatible.

Lorsque le proxy LLM Galaris est activé, les identifiants inclus dans la carte permettent de
rattacher les appels du worker et de respecter le modèle figé sans dépendre d’une Task courante
globale. Lorsque Hermès utilise son fournisseur natif, Galaris conserve le résultat et l’état de la
carte mais n’invente pas de `LLMCall` ni de coût détaillé.

L’observabilité suit une règle distincte de l’autorité d’exécution. Tant que la carte travaille,
les `LLMCall` éventuellement présents sont projetés dans un `ExecutionResult` provisoire ; en leur
absence, une étape Kanban minimale expose seulement l’état du worker. À l’état terminal, le
`worker_session_id` inscrit par Hermès dans les métadonnées du run permet de relire sa session
persistante et de remplacer entièrement la projection provisoire par les étapes Hermès. Si cette
session n’est pas disponible, la meilleure projection existante est conservée. Aucune de ces
sources de trace ne décide du succès, de l’échec ou d’une transition de Task.

## Conséquences

- `high` signifie désormais un runtime de fond durable pour Hermès, pas seulement un modèle plus
  puissant.
- `standard` préserve le comportement conversationnel et les sessions Hermès existants.
- Aucun modèle, table, scheduler ou phase Galaris supplémentaire n’est créé.
- Le résultat Kanban est observé par polling. La trace détaillée est provisoirement alimentée par
  les appels LLM vus par le proxy, puis réconciliée avec la session worker Hermès au terminal.
- Une installation historique doit mettre à jour le bridge et disposer d’une image Hermès
  compatible avant d’utiliser `high`.
- Cette décision ne met pas en œuvre le futur control plane conversationnel ni sa priorité LLM.

## Références et preuves

- Documentation Hermès : [Kanban](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban)
  et [worker lanes](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban-worker-lanes).
- Contrat Galaris : `back/app/agent/contracts.py`, `registry.py` et `facade.py`.
- Adaptation : `back/bridge/hermes/driver.py`, `kanban.py`, `native.py`, `manager.py` et
  `bridge/hermes/main.py`.
- Tests : `back/app/agent/tests/test_registry.py`, `test_facade.py` et
  `back/bridge/hermes/tests/test_kanban_executor.py`, `test_native.py`.
