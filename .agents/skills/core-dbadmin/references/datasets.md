# Concevoir les données permanentes

Lire cette référence pour choisir qui possède une ligne ou une colonne et pour constituer des jeux
de données statiques ou calculés.

## Déclarer la propriété avant le code

Un `DbAdminDataset` fait converger des lignes identifiées par `natural_key`. La politique de
colonnes détermine si Galaris impose une valeur ou laisse l'administrateur la modifier ensuite.

| Intention | Configuration |
|---|---|
| valeur imposée par le logiciel à chaque synchronisation | nommer explicitement la colonne dans `update_columns` |
| ligne créée avec des valeurs initiales, puis administrable | `update_columns=()` |
| valeur initialisée seulement tant qu'elle est `NULL` | `update_columns=(...)` avec `update_only_null=True` |
| ajouter de nouvelles clés par défaut sans écraser les clés existantes | `column_mergers` avec une fusion additive |
| toutes les colonnes fournies hors clé naturelle sont imposées | `update_columns=None`, valeur par défaut à réserver aux datasets réellement autoritatifs |

Préférer une liste `update_columns` explicite. L'absence de colonne dans une ligne signifie que le
dataset ne la possède pas, même si elle figure dans `update_columns`.

Une valeur « imposée » par dataset est reconvergée à chaque exécution de DbAdmin, mais DbAdmin
n'interdit pas sa modification entre deux synchronisations. Si une donnée doit être réellement
immuable au runtime, faire aussi respecter cette règle par le service, l'API/RBAC ou une contrainte
de base adaptée ; le dataset sert alors à créer la valeur et à réparer une éventuelle dérive.

Exemples vivants à inspecter :

- `back/core/params/dbadmin.py` : existence imposée, valeur administrateur préservée ;
- `back/app/tools/dbadmin.py` : colonnes logicielles imposées, activation administrable et fusion
  additive de paramètres globaux ;
- `back/app/chat/dbadmin.py` : affectation initiale seulement si la colonne est `NULL` ;
- `back/app/llm/dbadmin.py` : fournisseurs async évalués après leurs dépendances.

## Construire un dataset sûr

- Choisir une clé naturelle stable et unique dans le métier. Un identifiant technique n'est une
  bonne clé que pour une table d'association où il désigne réellement les lignes parentes.
- Fournir des lignes statiques pour un référentiel fixe, ou un provider async lorsque des FK ou
  des valeurs dépendent de datasets déjà convergés.
- Déclarer `depends_on` avec les clés exactes. Le registre refuse les dépendances absentes, cycles
  et collisions.
- Ne jamais fournir les colonnes d'audit `HistoryMixin`; le moteur les gère.
- Utiliser `after_merge` seulement pour un effet directement lié au merge, comme recharger un
  cache après convergence de l'état désiré. Garder le callback idempotent.
- Tester deux réconciliations consécutives : la seconde doit être un no-op observable.

## Suppression et restauration

`delete_missing=False` est le choix normal. Activer `delete_missing=True` uniquement si le dataset
décrit l'ensemble autoritatif de **toute la table** : le moteur n'applique pas de filtre de portée
et retirera chaque ligne absente. Avec `deleted_at`, le retrait est un soft-delete ; sinon il est
physique. Une ligne désirée déjà historisée est restaurée automatiquement.

Ne pas utiliser `delete_missing` sur une table partagée avec des lignes administrateur ou d'autres
producteurs. Séparer la propriété ou employer un mécanisme métier adapté.

## Dataset ou reconciler

Un dataset décrit des lignes désirées par clé naturelle. Une projection calculée, un index dérivé,
une réparation procédurale ou une synchronisation vers un stockage externe est un
`DbAdminReconciler`. Celui-ci s'exécute après tous les datasets, peut dépendre de datasets ou
d'autres reconcilers, et doit lui aussi converger sans dommage à chaque synchronisation.
