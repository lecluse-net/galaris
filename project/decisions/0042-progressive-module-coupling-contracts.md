# 0042 — Contrats progressifs de couplage des modules

Statut : Accepted

## Contexte

Les couches `core`, `app` et `bridge`, les surfaces publiques et quelques frontières critiques
étaient déjà contrôlées par AST. La majorité du graphe restait néanmoins gouvernée par la revue :
une nouvelle dépendance entre domaines, un import direct de service ou l'élargissement d'un cycle
pouvaient être ajoutés sans faire échouer la CI. Refuser immédiatement toute dette existante aurait
imposé un refactoring transversal risqué et aurait empêché les changements fonctionnels ordinaires.

La cartographie statique ne résolvait par ailleurs pas les listes injectées dans `MODULES` par une
expression étoilée. Les bridges de fournisseurs LLM actifs étaient donc absents de l'inventaire des
modules, même si leurs imports apparaissaient dans le graphe.

## Décision

Galaris maintient deux contrats complémentaires :

- `back/architecture.toml` déclare, pour chaque module backend actif, les dépendances de domaine
  autorisées et un fan-out maximal ; ce fichier est un plafond à réduire, pas une liste de cible ;
- `back/architecture-baseline.json` est un instantané déterministe des imports privés historiques
  et des composantes fortement connexes existantes.

Le frontend applique le même principe progressif dans `front/architecture-baseline.json`. Son
graphe dérive statiquement les imports aliasés `@/` et relatifs des fichiers TypeScript/Vue. La
baseline fige les dépendances, imports privés et composantes cycliques existants : toute croissance
est refusée et toute réduction doit être enregistrée. Les imports vers la racine d'un module ou
vers `index`, `contracts`, `facade`, `interface` et `types` sont ses surfaces publiques reconnues.

Un import inter-module est public lorsqu'il cible le package racine, `contracts`, `facade` ou
`interface`. Les autres imports sont de la dette tant qu'ils figurent dans la baseline. Le contrôle
d'architecture refuse :

1. un module actif sans contrat ;
2. une dépendance de domaine non autorisée ou un fan-out supérieur au plafond ;
3. un import privé absent de la baseline ;
4. une composante cyclique qui n'est pas contenue dans une composante historique.

Une scission de cycle est donc immédiatement admise, tandis qu'un agrandissement est refusé. La
baseline est régénérée explicitement avec `make architecture-baseline` après une amélioration, puis
son diff est relu. La cartographie expose les métriques du graphe et résout statiquement les listes
de modules référencées par étoile sans importer l'application.

## Conséquences

- La dette existante ne bloque pas le dépôt, mais elle ne peut plus croître silencieusement.
- Ajouter une dépendance requiert une modification visible du manifeste et une revue consciente.
- Retirer une dépendance doit conduire à diminuer son budget et la baseline correspondante.
- Les baselines peuvent être volumineuses ; elles sont mécaniques et séparées du manifeste humain afin de
  garder la politique lisible.
- Les surfaces publiques restent des contrats de code : le manifeste ne rend pas stable un module
  interne et ne remplace ni les tests de comportement ni les décisions métier.

## Contrôles

- `make project-context-check`
- `make architecture-check`
- `make architecture-baseline` uniquement pour accepter un état relu
