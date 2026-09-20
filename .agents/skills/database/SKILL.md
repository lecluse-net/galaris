---
name: database
description: Système de base de données et synchronisation — schéma PostgreSQL public géré par core.dbadmin avec Atlas encapsulé (PAS Alembic), dérivé des modèles SQLAlchemy. À utiliser dès qu'on ajoute/modifie/supprime un modèle ou une colonne, qu'on cherche comment appliquer un changement de schéma, ou qu'on parle de `make sync-db`, `make update`, d'Atlas, de pgvector ou de génération des privilèges.
---

# Synchronisation du schéma : core.dbadmin, Atlas encapsulé, PAS Alembic

⚠️ **Ce projet n'utilise PAS Alembic.** Il n'y a aucun fichier de migration, aucun dossier `versions/`, aucune commande `make migration`. Toute mention d'Alembic est obsolète.

Pour une migration de données volumineuse, un dataset avec politique de propriété, un reconciler
ou une action déclenchée par un delta de modèle, charger aussi le skill `core-dbadmin`.

Le schéma `public` est **dérivé automatiquement des modèles SQLAlchemy**. `core.dbadmin` est
l’unique orchestrateur et utilise Atlas comme détail privé pour calculer et appliquer le diff.
Tout objet de `public` appartient à cette cible ; les autres schémas sont hors périmètre.

## Workflow pour changer le schéma

1. Éditer le modèle dans `back/app/<module>/models.py` (style SQLAlchemy 2.0, `Mapped[T]`).
2. Lancer **`make sync-db`** dans l’environnement de développement déjà démarré.

C'est tout. `make sync-db` appelle `python -m core.dbadmin`, qui :
- charge une copie isolée des métadonnées SQLAlchemy ;
- prépare automatiquement les nouvelles colonnes `NOT NULL` et les changements d’ENUM ;
- utilise Atlas en interne, sans confirmation ;
- synchronise ensuite les actions conditionnelles et données permanentes.

```bash
make sync-db   # dev uniquement : schéma + datasets DbAdmin, sans restart
```

En développement, `make update` reconstruit aussi les images avec cache et redémarre la stack ;
la commande de démarrage dev synchronise la base avant Uvicorn, puis la mise à jour attend les
services. `make sync-db` reste adapté à une synchronisation seule sans redémarrage.

En production, ne lancez pas cette commande séparément : `make update` reconstruit puis redémarre
la stack. L’entrypoint du nouveau backend appelle le même DbAdmin avant Uvicorn, et `make update`
attend ensuite que les services soient sains. Ces deux chemins sont idempotents.

> Ne pas écrire de script de migration ni lancer `atlas ...` à la main. Toute invocation Atlas
> runtime reste sous `core.dbadmin._internal`.

## Datasets permanents

Toute donnée imposée par Galaris se déclare dans `<module>.dbadmin`. Le module enregistre une
`DbAdminDataSource`, dont la factory produit un ou plusieurs `DbAdminDataset` : tools intégrés,
connexions par défaut, paramètres, privilèges, profils et autres tables de référence. Le registre
compile toutes les sources des modules actifs, puis ordonne les datasets avec `depends_on`; une clé
absente, un cycle ou une collision entre deux sources est une erreur de développement.

- Un dataset nomme sa table, sa clé naturelle et ses lignes, statiques ou produites à la demande
  par un fournisseur async. Les FK peuvent donc être résolues après le merge d’un dataset parent.
- Déclarer précisément `update_columns`; utiliser un `column_mergers` seulement pour une politique
  comme l’ajout de valeurs par défaut sans écraser les valeurs administrateur.
- Les suppressions sont désactivées par défaut et deviennent des soft-deletes lorsque
  `deleted_at` existe.
- Une reconstruction de projection qui ne décrit pas un jeu de lignes autoritatif est un
  `DbAdminReconciler`, pas un dataset. Une transformation conditionnée par un delta de schéma est
  une `DbAdminAction` avec postcondition.
- Ne jamais dupliquer cette synchronisation dans le lifespan FastAPI ou un script global.

## Conditions pour qu'un modèle soit pris en compte

- Le module doit être déclaré dans `back/modules.py` (`"app.<module>"`).
- Le modèle doit être importable (atteignable depuis le package du module). Un modèle jamais importé n'apparaît pas dans le schéma généré → pas de table créée.

## Règles de modélisation propres au projet

- Hériter de `Base` ; ajouter `HistoryMixin` pour le **soft-delete** + colonnes d'audit (`created_at/by`, `updated_at/by`, `deleted_at/by`).
- Les lignes soft-deleted sont **filtrées automatiquement** sur tous les SELECT ORM. Pour les inclure : `.execution_options(include_historized=True)`. Pour filtrer manuellement une query : `Model.histo_filter(query)`.
- Supprimer = `entity.soft_delete()` puis `db.commit()` (jamais de `DELETE` SQL pour les entités métier).
- Clés étrangères : `mapped_column(ForeignKey("table.colonne"), index=True)`. Les FK optionnelles sont `Mapped[Optional[int]]`, `nullable=True`.
- Avant de supprimer une ligne référencée ailleurs (ex: suppression d'un groupe), détacher les références (`UPDATE ... SET fk = NULL`) dans le service avant le `soft_delete()`.

Détails ORM/typage : voir la skill `back-conventions`.

# Privilèges RBAC — génération automatique

Les privilèges ne sont **pas écrits à la main** dans `definitions.py`.

- On déclare des constantes dans `back/app/<module>/privileges.py` (ex: `EMPLOYEE_ACCESS = "..."`).
- `make sync-db` en développement — ou `make update` en production — passe par la DataSource
  `core.authorize`, dont le dataset `core.authorize.privileges` **régénère** :
  - `back/core/authorize/definitions.py` (classe `Privileges`, Python),
  - `front/core/authorize/definitions.ts` (TypeScript),
  - et synchronise la table `privileges` + le rôle admin en base.
- Ces deux fichiers `definitions.*` sont **auto-générés — ne pas les éditer**.
- Pour une entité « secondaire » d'un module (ex: groupes d'employés), **réutiliser** les privilèges existants du module plutôt que d'en créer, sauf besoin réel de granularité.

# pgvector

Les embeddings utilisent l'extension `pgvector`. Les tables applicatives restent dans `public` ;
le schéma `vectors`, lorsqu’il est requis par les services, reste hors de la cible DDL Atlas.

# Environnement

Toutes ces commandes tournent dans Docker (l'hôte n'a ni `python`, ni `atlas`, ni `psql`). Voir la skill `general` pour l'environnement dockerisé et les commandes `make`.
