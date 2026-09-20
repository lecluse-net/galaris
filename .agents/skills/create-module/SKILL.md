---
name: create-module
description: Créer un module métier Galaris backend et/ou frontend — activation, contrat public, CRUD, RBAC, SQLAlchemy, tests, navigation et i18n. À utiliser lors de l’ajout d’un package core/app/bridge ou d’un CRUD de bout en bout.
---

# Créer un module Galaris

Utiliser d’abord le skill `modules` pour choisir la couche et les dépendances. Ajouter
`back-conventions`, `database` et les skills frontend selon la portée réelle.

## Choisir la référence

1. Ouvrir `docs/fr/architecture/generated/project-map.md`.
2. Choisir un module actif proche par capacités : modèle, router, MCP, pages, store, bridge.
3. Lire sa surface publique et ses tests, pas seulement son arborescence.
4. Utiliser `exemple-album/` comme squelette pédagogique de CRUD, puis l’aligner sur les
   conventions du module actuel choisi. Ne pas le recopier mécaniquement.

## Définir avant de générer

Préciser :

- la couche (`core`, `app` ou `bridge`) et le propriétaire métier ;
- le contrat public et les dépendances autorisées ;
- les entités persistées, règles de suppression et invariants ;
- les endpoints, privilèges et outils MCP éventuels ;
- les pages, navigation et traductions ;
- les événements temps réel réellement nécessaires.

## Construire le backend

1. Créer un package léger avec `__init__.py`.
2. Ajouter seulement les capacités nécessaires : `contracts.py`, `models.py`, `schemas.py`,
   `service.py`, `router.py`, `privileges.py`, `mcp.py`, `i18n.py` et `tests/`.
3. Exposer une façade stable plutôt que les détails du service ou les modèles ORM.
4. Déclarer le module dans `back/modules.py`.
5. Tester règle métier, autorisation et persistance.
6. Si le schéma change, exécuter `make sync-db` avec le skill `database`.

## Construire le frontend

1. Créer `front/app/<module>/` ou la couche choisie.
2. Ajouter les pages, composants, services et éventuellement un store.
3. Ajouter `navigation.ts`, `presentation.ts` ou `i18n.ts` seulement si le module les utilise.
4. Déclarer le module dans `front/modules.ts`.
5. Garantir la parité anglaise/française et les privilèges de navigation.

## Temps réel

Ne pas ajouter un websocket par réflexe. Réutiliser l’infrastructure et les sujets existants
si une modification externe doit être reflétée sans rechargement. Définir le payload, la
portée de la room, l’autorisation et le nettoyage de l’abonnement dans les tests.

## Terminer

Régénérer la cartographie, lancer les tests ciblés, `make typecheck`,
`make architecture-check` et `git diff --check`. Mettre à jour un flux ou une décision si le
module introduit une nouvelle frontière architecturale.
