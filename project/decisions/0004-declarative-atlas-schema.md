# ADR 0004 — Schéma déclaratif avec Atlas

- Statut : Accepted
- Date : 2026-07-18
- Orchestration remplacée par : ADR 0044

## Contexte

Maintenir à la fois des modèles SQLAlchemy et une suite de migrations impératives crée deux
représentations du schéma. Galaris charge déjà ses modèles depuis les modules activés et doit
supporter PostgreSQL et pgvector de manière identique en test et en production.

## Décision

Le schéma cible est généré depuis les modèles SQLAlchemy des modules déclarés. Depuis l’ADR 0044,
`core.dbadmin` orchestre la comparaison et encapsule Atlas. En production,
`make update` reconstruit et redémarre la stack puis attend cette synchronisation. En
développement, `make sync-db` rejoue le même flux sans redémarrage afin de préserver le hot reload.

Le projet n’utilise pas Alembic et ne conserve pas de scripts de migration manuels.

## Conséquences

- Un modèle doit être importable depuis un module backend activé pour appartenir au schéma.
- Les changements destructifs exigent une stratégie de compatibilité/backfill avant réduction.
- Les fichiers de privilèges générés ne sont pas édités à la main.
- Les tests appliquent le même flux Atlas sur une base PostgreSQL éphémère.

## Preuves dans le code

`core/dbadmin/`, `back/entrypoint.sh`, `back/modules.py` et les cibles `make update` /
`make sync-db`.
