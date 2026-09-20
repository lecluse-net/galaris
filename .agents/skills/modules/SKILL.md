---
name: modules
description: Architecture modulaire back et front de Galaris — couches core/app/bridge, activation, surfaces publiques, bootstrap et contrôles de dépendances. À utiliser pour créer, déplacer, relier ou diagnostiquer un module.
---

# Naviguer dans les modules Galaris

## Identifier la couche

| Couche | Rôle | Dépendances autorisées |
|---|---|---|
| `back/core` | Infrastructure réutilisable | `core`, bibliothèques externes ; jamais `app` ou `bridge` |
| `back/app` | Domaine métier Galaris | `core` et surfaces publiques d’autres domaines `app` |
| `back/bridge` | Adaptateur d’un système externe | `core` et contrats/façades `app` nécessaires |
| `front/core` | Shell, API, auth, navigation, i18n | Infrastructure frontend |
| `front/app` | Pages et états métier | `front/core` et surfaces publiques frontend |

Choisir `app` par défaut pour un nouveau métier. Choisir `bridge` si le package traduit un
protocole ou gère le cycle de vie d’un système autonome externe.

## Vérifier l’activation

- Backend : `back/modules.py`, avec des noms Python comme `app.agent`.
- Frontend : `front/modules.ts`, avec des chemins comme `app/agent`.
- Cartographie : `docs/fr/architecture/generated/project-map.md`.

Un package sur disque n’est pas nécessairement actif. Inversement, toute entrée active doit
résoudre vers un package existant. Après une modification, exécuter `make project-context` et
`make architecture-check`.

## Utiliser des surfaces publiques

Préférer, dans cet ordre :

1. les exports intentionnels du package racine ;
2. un module public explicite tel que `contracts.py`, `facade.py` ou `interface.py` ;
3. un port enregistré au bootstrap lorsque la dépendance doit être inversée.

Ne pas importer arbitrairement le service interne ou les modèles ORM d’un autre domaine. Une
composition dans `back/modules.py` ou le bootstrap n’autorise pas le même couplage dans le
métier.

## Composer un module backend

Les fichiers sont ajoutés selon le besoin, et non comme une checklist obligatoire :

```text
app/<module>/
├── __init__.py       surface publique légère
├── contracts.py      protocoles et DTO inter-domaines éventuels
├── models.py         modèles SQLAlchemy
├── schemas.py        schémas d’API
├── service.py        logique métier
├── router.py         endpoints FastAPI
├── privileges.py     constantes RBAC
├── dbadmin.py         DataSource de datasets permanents éventuels
├── mcp.py            outils MCP éventuels
├── i18n.py           catalogues backend éventuels
└── tests/            contrats et régressions
```

Le chargeur découvre les capacités conventionnelles du module. Garder `__init__.py` léger
pour éviter les cycles et effets de bord d’import.

`core.dbadmin` compile conventionnellement les `DbAdminDataSource` exposées par les fichiers
`<module>.dbadmin`. Les lignes restent propriétaires de leur module ; ne constituez pas un fichier
central de seeds et n’enregistrez pas un pseudo-dataset sous forme de handler opaque.

## Composer un module frontend

```text
app/<module>/
├── pages/            routes basées sur les fichiers
├── components/       composants du domaine
├── services/         contrats TypeScript et appels API
├── stores/           état Pinia partagé si nécessaire
├── navigation.ts     contribution à la navigation
├── i18n.ts           catalogues anglais/français
└── presentation.ts   métadonnées de présentation éventuelles
```

Ne pas créer de store pour un état purement local et ne pas maintenir une table de routes
manuelle en parallèle du routage par fichiers.

## Modifier ou ajouter un module

1. Choisir un module voisin actuel comme référence, guidé par la cartographie générée.
2. Définir la surface publique et les dépendances avant l’implémentation.
3. Ajouter les fichiers strictement nécessaires et leurs tests.
4. Déclarer le module backend et/ou frontend.
5. Si un modèle change, utiliser le skill `database` puis `make sync-db`.
6. Régénérer la cartographie et lancer les contrôles d’architecture.

Pour générer un CRUD complet, utiliser aussi le skill `create-module`.
