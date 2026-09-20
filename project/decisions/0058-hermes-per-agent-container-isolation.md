# ADR 0058 — Isolation d’Hermès dans un conteneur par agent

- Statut : Accepted
- Date : 2026-08-29

## Contexte

L’ADR 0009 avait ajouté un mode optionnel représentant plusieurs agents Galaris comme des profils
d’un même conteneur Hermès officiel. Cette topologie diffère de celle des autres harnais
conteneurisés, affaiblit l’isolation des données et des processus, et repose sur des profils dans
Docker alors qu’Hermès recommande d’y déployer des instances séparées.

Le `harness_manager` générique sait déjà gérer un répertoire Compose indépendant par instance.
Il peut être commun à plusieurs harnais sans que leurs runtimes, volumes ou conteneurs le soient.

## Décision

Chaque agent Galaris affecté au harnais Hermès possède exactement une instance managée nommée
`<agent.code>`, un Compose propre, un volume de données propre et un conteneur
`<agent.code>-agent`. Le bridge Hermès génère ses artefacts puis délègue exclusivement leur cycle
de vie et leur transport de fichiers à `bridge.harness`.

Cette règle est la même pour tous les harnais conteneurisés. Le harnais interne Pydantic AI reste
la seule implémentation locale qui n’a pas besoin d’un conteneur dédié ; un harnais distant sans
runtime local n’en crée pas non plus.

Le mode partagé est supprimé : il n’existe plus de `HERMES_NATIVE`, de Compose Hermès global,
d’adaptateur de profils ni de Params `BRIDGE_HERMES_*` pilotant ce déploiement. Le port API, le
dashboard éventuel, la configuration, les sessions, la mémoire, les skills, les secrets et le
répertoire de travail restent bornés à l’instance de l’agent.

Le dataset autoritatif de `core.params` supprime les anciennes lignes de Params lors de la
synchronisation DbAdmin. En revanche, Galaris ne supprime pas automatiquement un ancien
conteneur partagé `galaris-hermes` ni son volume : l’opérateur doit d’abord vérifier et sauvegarder
les données encore utiles avant de retirer ces restes de déploiement.

## Conséquences

- deux agents Hermès ne partagent ni conteneur, ni volume, ni profil runtime ;
- la compromission ou la panne d’une instance est mieux bornée ;
- chaque instance peut être démarrée, arrêtée, mise à jour ou supprimée indépendamment ;
- le coût Docker augmente linéairement avec le nombre d’agents Hermès actifs ;
- une réintroduction d’un runtime partagé exigerait une nouvelle décision d’architecture ;
- cette décision remplace le mode natif de l’ADR 0009 et les clauses correspondantes des ADR
  0038 et 0054.

## Preuves dans le code

`back/bridge/hermes/manager.py`, `back/bridge/hermes/harness_provider.py`,
`back/bridge/hermes/harness_supervisor.py`, `back/bridge/harness/manager.py`,
`harness_manager/main.py` et `back/bridge/hermes/tests/test_manager_config.py`.
