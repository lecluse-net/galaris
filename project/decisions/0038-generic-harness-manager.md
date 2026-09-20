# ADR 0038 — Gestionnaire hôte générique des harnais conteneurisés

- Statut : Accepted
- Date : 2026-08-20

## Contexte

Le déploiement historique d'Hermès utilisait deux composants confondus sous le même nom :

- `back/bridge/hermes`, qui adapte les API, la configuration et l'exécution Hermès ;
- `bridge/hermes`, serveur hôte pilotant les répertoires, Docker Compose et le transport de
  fichiers.

Le second composant contenait presque uniquement des primitives réutilisables. Son vocabulaire
`agent` et quatre endpoints Kanban appelant directement la CLI Hermès empêchaient néanmoins son
emploi futur pour Claude Code, Codex, DSH ou tout autre harnais conteneurisé.

## Décision

Le serveur hôte devient `harness_manager` et annonce le service `bridge.harness`. Son
contrat manipule des `instances`, sans connaître le runtime contenu :

- inventaire, création depuis un template et suppression ;
- état, logs et actions bornées `start`, `stop`, `restart`, `update` ;
- lecture/écriture/suppression de fichiers et streaming binaire ;
- information UID/GID nécessaire à la génération des Compose.

Chaque bridge runtime reste propriétaire de son image, de son Compose, de ses fichiers, de ses
ports, de sa configuration et de ses appels API. Pour Hermès, ces responsabilités restent dans
`back/bridge/hermes`.

Le client Galaris du contrat générique vit dans `back/bridge/harness`. Comme il s'agit d'une
infrastructure de déploiement, son URL et son secret partagé sont chargés exclusivement depuis le
`.env` par `core.settings`; ils ne sont ni persistés dans Params, ni exposés dans les préférences
d'un runtime.

Le manager n'exécute aucune CLI de runtime. Les anciennes routes Kanban sont supprimées et le
bridge Hermès utilise uniquement les API d’exécution de son conteneur dédié. Le contrat est
volontairement incompatible : `/agents` devient
`/instances`, `X-Hermes-Token` devient `X-Harness-Token` et le secret du service devient
`HARNESS_MANAGER_SECRET`. Aucun shim n'est conservé.

Cette décision livre uniquement l'extraction du serveur générique. Elle ne crée pas encore le
domaine persistant `app.harnesses`, les instances multiples par agent ou la sélection de nouveaux
runtimes décrits dans le plan des harnais modulaires.

## Conséquences

- un même manager peut héberger des répertoires Compose produits par plusieurs bridges ;
- aucune mise à jour du manager n'est nécessaire pour ajouter une configuration propre à un
  nouveau runtime ;
- les installations de l'ancien serveur doivent réinstaller le service et reconfigurer leur
  secret ;
- Hermès consomme le contrat générique comme les autres harnais conteneurisés, avec une instance
  et un conteneur par agent conformément à l’ADR 0058 ;
- l'ancien transport Kanban `legacy` est refusé explicitement.

## Preuves dans le code

`harness_manager/main.py`, ses tests, `back/bridge/harness/manager.py`,
`back/bridge/hermes/manager.py`,
`back/bridge/hermes/README.md` et `harness_manager/README.md`.
