---
name: back-conventions
description: Conventions du backend Python Galaris — Pyright strict, SQLAlchemy async, services, surfaces publiques, FastAPI, RBAC, journalisation et tests. À utiliser pour toute lecture ou modification de code sous back/core, back/app ou back/bridge.
---

# Écrire le backend Galaris

## Partir du contrat

Lire le test, le modèle et la surface publique du domaine avant son implémentation. Préserver
les frontières décrites dans `AGENTS.md` et `docs/fr/architecture/invariants.md`. Pour une
modification agentique, de messagerie ou de processus, charger aussi le skill métier dédié.

## Respecter Pyright strict

- Annoter paramètres, attributs et retours du code de production.
- Utiliser `T | None`, des protocoles et des types structurés plutôt qu’un `Any` propagé.
- Isoler les conversions dynamiques à la frontière d’une bibliothèque ou d’un payload.
- Utiliser `TYPE_CHECKING` et des références différées seulement pour résoudre un vrai cycle.
- Lancer `make typecheck`; Pylance n’est pas le contrat de CI.

## Utiliser SQLAlchemy 2 async

- Déclarer les colonnes avec `Mapped[T]` et `mapped_column`.
- Utiliser la session contextuelle fournie par `core.database`; ne pas la transmettre dans
  toute la chaîne de services si le domaine suit ce modèle contextuel.
- Dans tout service, façade, router ou fonction MCP exécuté sous un contexte géré, récupérer
  exclusivement la session courante avec `get_db()`. Ne jamais y ouvrir une session imbriquée.
- Réserver `get_db_session()` aux véritables racines autonomes qui ne possèdent aucun contexte :
  script/CLI, scheduler ou worker, listener, callback détaché, thread ou orchestration
  d'infrastructure. Chaque branche asynchrone concurrente possède alors sa propre session courte.
- Exécuter les requêtes avec l’API async et charger explicitement les relations nécessaires,
  souvent avec `selectinload`.
- Employer `HistoryMixin` pour les entités historisées et sa suppression logique.
- Charger le skill `database` pour toute table, colonne, contrainte, index ou relation modifiée.

## Séparer HTTP et métier

Un router FastAPI :

1. décrit le contrat HTTP et les schémas ;
2. applique l’authentification et le RBAC existants ;
3. délègue au service ou à la façade du domaine ;
4. traduit les erreurs de domaine prévues en réponses HTTP.

Ne pas placer un workflow ou une requête complexe directement dans le handler. Déclarer les
routes statiques avant une route dynamique susceptible de les capturer.

## Protéger les frontières

- Exporter les contrats inter-domaines par le package racine ou un module `contracts`,
  `facade` ou `interface` explicite.
- Ne pas importer un modèle ORM externe pour piloter son domaine ; appeler sa façade ou son
  port. Une relation SQLAlchemy nécessaire doit rester ciblée et testée.
- `core` n’importe jamais `app` ni `bridge`.
- Un bridge traduit le monde externe vers un contrat Galaris et ne duplique pas le métier.

## RBAC et i18n

- Déclarer les privilèges dans le `privileges.py` du module ; les définitions Python et
  TypeScript générées ne sont pas éditées manuellement.
- Tester le refus d’accès et le cas autorisé pour un nouvel endpoint sensible.
- Utiliser `core.i18n` pour un message backend localisé et conserver la parité `en`/`fr`.

## Journaliser et tester

Utiliser Loguru avec des arguments structurés, sans secret et sans `print` en production.
Écrire des tests unitaires pour les règles pures, des tests DB pour la persistance et des
tests AST pour les frontières. Exécuter les tests via `make tests ARGS='…'`, jamais avec
pytest dans la base de développement.
