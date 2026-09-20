# ADR 0037 — L'effort mesure la complexité cognitive

- Statut : Accepted
- Date : 2026-08-15

## Contexte

L'ADR 0036 réserve le planner aux travaux réellement décomposables et privilégie `EXEC high` pour
un livrable cohérent complexe. Le seuil entre `standard` et `high` restait toutefois trop large :
les prompts et le schéma structuré citaient correction, artefact existant, destinataire nommé,
effet externe, nombre d'outils ou risque comme raisons suffisantes de sélectionner `high`.

Cette politique a classé en `high` une remise à zéro Git pourtant explicite, bornée et mécanique.
Le briefing a alors ajouté un coût de préparation sans résoudre de difficulté cognitive réelle.
Confondre danger et difficulté fait également du modèle plus puissant un substitut implicite aux
contrôles de sécurité, alors que ces responsabilités doivent rester indépendantes.

## Décision

L'effort mesure uniquement la complexité cognitive utile à l'exécution :

- `standard` couvre une opération explicite, bornée et déterministe, dont la méthode et les
  contrôles de fin sont simples ; elle peut employer plusieurs outils, agir sur un artefact
  existant, contacter un destinataire ou appliquer un effet destructif explicitement autorisé ;
- `high` exige une complexité matérielle : ambiguïté, contexte substantiel à reconstruire,
  hypothèses concurrentes, diagnostic ou récupération complexe, nombreuses décisions couplées,
  ou création technique ou créative exigeante.

Le risque opérationnel sélectionne les contrôles de portée, confirmations, autorisations,
checkpoints et règles de reprise. Il ne sélectionne jamais à lui seul le niveau d'effort. Une
correction, une vérification explicite, plusieurs appels d'outils ou un effet externe ne justifient
donc pas automatiquement `high`.

Cette règle s'applique au dispatcher de Task et aux efforts attribués aux feuilles du planner. Les
directives explicites `@standard`, `@high` et les choix forcés conservent leur autorité actuelle.

## Conséquences

- Les opérations mécaniques évitent le coût d'un modèle `high` et d'un briefing sans valeur ajoutée.
- Les actions destructives ne perdent aucune protection : leur sûreté reste portée par les contrôles
  dédiés et l'autorisation humaine, indépendamment du modèle.
- Les benchmarks Dispatcher doivent contenir des opérations destructives bornées attendues en
  `EXEC standard`, ainsi que des diagnostics réellement ambigus attendus en `EXEC high`.

## Preuves dans le code

`back/app/agent/dispatcher.py`, `contracts.py`, `planner_service.py`, leurs tests, les prompts
Planner par défaut et la documentation du flux agentique.
