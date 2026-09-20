---
name: core-dbadmin
description: Concevoir et implémenter les opérations avancées de core.dbadmin — migrations de données volumineuses, datasets permanents ou initialisables, reconcilers et actions idempotentes déclenchées par un delta de modèle. À utiliser quand un changement dépasse la simple convergence déclarative du schéma SQLAlchemy.
---

# Opérations avancées avec `core.dbadmin`

Utiliser ce skill avec `general` et `database`. Ajouter `back-conventions` dès que du code Python,
SQLAlchemy ou un modèle backend est lu ou modifié.

`core.dbadmin` est l'unique chemin de convergence du schéma PostgreSQL `public` et des données
permanentes de Galaris. Atlas reste privé sous `core.dbadmin._internal`; il n'existe ni migration
Alembic, ni suite de révisions numérotées, ni script global d'upgrade.

## Commencer par le contrat réel

Avant de concevoir une contribution :

1. lire entièrement `docs/fr/dev/dbadmin.md` ;
2. inspecter la surface publique `back/core/dbadmin/__init__.py`, les contrats concernés et leurs
   tests ;
3. localiser les contributions comparables avec `rg --files back | rg '/dbadmin.py$'` ;
4. vérifier l'activation du module dans `back/modules.py` et sa découverte par
   `load_dbadmin_contributions()`.

Les contrats, l'implémentation et les tests priment sur ce skill et sur la documentation.

## Choisir le bon mécanisme

| Besoin | Mécanisme |
|---|---|
| table, colonne, contrainte ou index cible | modèle SQLAlchemy, puis Atlas via DbAdmin |
| ensemble de lignes décrit par clé naturelle | `DbAdminDataSource` + `DbAdminDataset` |
| projection dérivée entièrement reconstruisible | `DbAdminReconciler` |
| traitement applicable seulement à un delta de schéma | `DbAdminAction` |
| opération métier à la demande | service du domaine, pas DbAdmin |

- Pour créer des lignes imposées, des valeurs initiales modifiables ou une fusion de nouveaux
  défauts, lire [references/datasets.md](references/datasets.md).
- Pour un backfill, une transformation volumineuse ou un traitement déclenché par changement de
  modèle, lire [references/schema-actions.md](references/schema-actions.md).

Un traitement appelé parfois « script manuel de migration » devient ici un handler enregistré
comme `DbAdminAction` dans `<module>.dbadmin`. Son déclencheur est un prédicat sur le delta courant
et sa réussite est prouvée par une postcondition sur les données, jamais par un numéro de version
ou par le simple fait que le code s'est exécuté.

## Contribuer depuis le bon endroit

- Placer la contribution dans `back/<couche>/<module>/dbadmin.py` et exposer
  `register_dbadmin(registry: DbAdminRegistry) -> None`.
- Importer uniquement la surface publique `core.dbadmin`; ne jamais importer `_internal`.
- Garder les modèles et services dans leur domaine propriétaire. Utiliser
  `back/dbadmin_composition.py` seulement pour une composition réellement transverse qui ne peut
  appartenir à un module unique.
- Donner aux sources, datasets, reconcilers et actions des clés globales stables préfixées par le
  module.
- Déclarer les dépendances réelles des datasets et reconcilers. Les actions n'ont pas de graphe de
  dépendance : choisir leur phase et réunir dans un même handler ce qui doit être atomiquement
  ordonné.

## Préserver les invariants opérationnels

- Une synchronisation doit être idempotente et sans interaction opérateur.
- Chaque action, dataset et reconciler possède sa transaction ; il n'existe pas de transaction
  globale englobant Atlas.
- Le verrou consultatif DbAdmin reste tenu pendant toute la synchronisation. Borner le travail et
  les verrous SQL, surtout au démarrage de production.
- Le dry-run montre le plan DDL, mais n'exécute ni actions, ni datasets, ni reconcilers.
- Une action indispensable en échec `BEFORE_EXPAND` arrête Atlas. Une préparation différée
  permet les ajouts mais conserve les sources ; une contraction attend les préparations.
  Les changements de type destructifs restent soumis au patron multi-livraisons de la référence.
- Ne jamais déplacer cette logique dans le lifespan FastAPI, `back/scripts/`, un appel Atlas
  direct ou du DDL applicatif au démarrage.

## Tester et livrer

Tester au niveau du contrat modifié : prédicat applicable et non applicable, idempotence,
postcondition, rollback, dépendances et politiques de propriété des colonnes. Toute
expansion/contraction sensible ou transformation PostgreSQL doit avoir un test d'intégration réel.

Exécuter d'abord les tests ciblés, puis les contrôles proportionnés :

```bash
make tests ARGS='core/dbadmin/tests app/<module>/tests/test_dbadmin.py'
make typecheck
make architecture-check
git diff --check
```

En développement, appliquer avec `make sync-db`. En production, ne pas lancer cette cible :
`make update` laisse l'entrypoint synchroniser avant Uvicorn. Pour une opération destructive ou
volumineuse, inspecter d'abord le dry-run dans le conteneur et documenter la stratégie de reprise.
