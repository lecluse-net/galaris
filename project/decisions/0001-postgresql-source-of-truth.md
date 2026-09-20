# ADR 0001 — PostgreSQL comme source durable

- Statut : Accepted
- Date : 2026-07-18

## Contexte

Les tâches, objectifs, processus et listeners continuent au-delà d’une requête ou d’un
processus Python. Une coordination uniquement en mémoire perdrait leases, tentatives,
callbacks et décisions lors d’un redémarrage.

## Décision

PostgreSQL est la source de vérité durable. Les registres et caches en mémoire sont des vues
reconstructibles. Les opérations rejouables utilisent transactions, verrous, révisions,
contraintes d’unicité, curseurs ou clés d’idempotence selon le domaine.

## Conséquences

- Une reprise après crash se décide depuis les lignes persistées.
- Les tests de persistance utilisent PostgreSQL/pgvector, pas une imitation SQLite.
- Une nouvelle boucle durable doit expliciter son lease, son curseur ou son identité de
  redelivery.
- Les émissions websocket et appels externes suivent une écriture durable ou disposent d’une
  stratégie de répétition sûre.

## Preuves dans le code

`app.task.models`, `app.goal.models`, `app.process.models`, `app.messenger.models` et les
services correspondants.
