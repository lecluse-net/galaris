# ADR 0043 — Propriété du bridge Hermès et exécution exclusivement par Task

- Statut : Accepted
- Date : 2026-08-20

## Contexte

La première extraction d'Hermès avait créé `hermes_agent_configs`, mais l'API Agent générique
continuait d'exposer, chiffrer, hydrater et synchroniser les champs `hermes_*`. Le registre
`app.agent` déclarait aussi directement le driver concret. Enfin, le proxy LLM conservait une
sélection de modèle pour des appels Hermès autonomes sans Task, alors que le driver refusait déjà
les `AgentRunRequest` sans `task_id`.

## Décision

Hermès possède désormais ses surfaces spécialisées de bout en bout :

- `bridge.hermes.agent_driver` contribue le `AgentDriverSpec` depuis la liste de composition de
  `back/modules.py` ; le registre générique ne connaît aucun code concret externe ;
- la lecture et l'écriture de la configuration passent par `/api/hermes/configurations` et par
  `bridge.hermes.config_service` ; `/api/agents` ne contient plus de champ Hermès ;
- tous les composants, services, réglages et traductions propres à Hermès vivent sous
  `front/bridge/hermes` ; ils contribuent à l'onglet Hermès de la fiche Agent et à
  `Préférences > Harnais > Hermès`, sans créer d'entrée de navigation autonome ;
- la supervision opérationnelle d'un harnais reste générique : l'écran Agents appelle la façade
  HTTP de `app.harness`, qui résout une contribution selon le driver. Hermès fournit cette
  contribution et traduit `status`, `start`, `stop`, `restart`, `update`, `logs` et `refresh`
  vers `bridge.harness` ou vers son API native ;
- les appels LLM et les exécutions agentiques d'un runtime géré sont corrélés à une Task. Le
  handshake MCP reste autorisé avant le démarrage d'une Task, car Hermès initialise son client au
  démarrage du conteneur ; le contexte de la Task active est injecté aux outils lors des requêtes
  d'exécution. Il n'existe plus de routage autonome `standard`/`high` ;
- les changements de skills ciblent génériquement les drivers `manages_runtime`, sans branche
  Hermès dans `app.skill`.

Le code Kanban reste compilé et testé. Les nouveaux runs directs restent imposés par la constante
interne désactivée, tandis qu'un checkpoint Kanban historique peut toujours reprendre et être
annulé.

Les colonnes `agents.hermes_*` restent temporairement déclarées comme source de backfill. Atlas
applique le schéma avant les backfills applicatifs : les retirer dans la même version que
l'expansion pourrait donc supprimer des données sur une installation n'ayant jamais exécuté
cette expansion. Elles ne font plus partie des schémas, services ou routes Agent et pourront être
retirées dans une contraction séparée après validation opérationnelle de
`hermes_agent_configs`.

## Conséquences

- le CRUD Agent générique ne transporte plus de champs Hermès ; un composant fourni par le bridge
  présente la même configuration dans l'onglet Hermès de l'agent et dans le sous-menu Harnais des
  préférences ;
- l'écran Agents conserve les commandes de supervision communes sans dépendre d'Hermès ;
- ajouter un driver externe ne nécessite plus d'éditer `app.agent.registry` ;
- les sessions directes du dashboard Hermès ne peuvent pas consommer le proxy LLM Galaris avec
  un jeton système hors Task ;
- la dernière suppression de colonnes est explicitement une opération de schéma destructive,
  distincte de cette coupure applicative.

## Preuves dans le code

`back/app/harness/facade.py`, `back/app/harness/router.py`,
`back/bridge/hermes/harness_supervisor.py`, `back/bridge/hermes/agent_driver.py`,
`back/bridge/hermes/config_service.py`, `back/bridge/hermes/router.py`,
`back/app/agent/registry.py`, `back/app/llm/proxy_service.py`, `front/bridge/hermes/` et les tests
d'architecture d'`app.agent` et de façade d'`app.harness`.
