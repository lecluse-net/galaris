<p align="right"><strong>Français</strong> · <a href="../../en/dev/dbadmin.md">English</a></p>

# `core.dbadmin` — évolutions de la base de données

Ce document décrit le contrat développeur de `core.dbadmin`, l’unique chemin Galaris pour faire
évoluer le schéma PostgreSQL `public` et les données permanentes. Les
[contrats et tests](../../../back/core/dbadmin/) restent l’autorité si ce document diverge du code.

## Principes

- Les modèles SQLAlchemy actifs décrivent entièrement la cible du schéma `public`.
- DbAdmin utilise Atlas comme détail privé pour faire converger la base vers cette cible.
- Galaris n’utilise ni Alembic, ni migrations numérotées, ni historique linéaire de versions.
- Chaque synchronisation compare la base présente à la cible de la branche courante.
- Les transformations particulières sont des actions idempotentes déclenchées par le delta
  courant, pas par un numéro de révision déjà appliqué.
- Les datasets et reconcilers font converger les données après le schéma ; ils ne doivent pas être
  dupliqués dans le lifespan FastAPI.

Cette architecture est volontairement **a-versionnée**. Passer d’une branche à une autre produit
un nouveau delta entre la base locale et les modèles de cette branche, sans imposer une chaîne
globale `v1 → v2 → v3`.

## Commandes et environnements

Après une modification de modèle ou de données permanentes en développement :

```bash
make sync-db
```

Cette cible est réservée à `APP_ENV=dev` et appelle `python -m core.dbadmin synchronize` dans le
conteneur backend. En production, ne pas l’appeler séparément : `make update` redémarre le backend,
dont l’entrypoint exécute DbAdmin avant Uvicorn.

Les commandes internes utiles sont :

```bash
python -m core.dbadmin synchronize --dry-run
python -m core.dbadmin status --latest
```

Elles doivent également être exécutées dans le conteneur. Le dry-run affiche le plan Atlas, mais
n’exécute ni actions, ni datasets, ni reconcilers et ne persiste pas de run.

## Ce que DbAdmin compare

DbAdmin inspecte les tables, colonnes, nullabilités et ENUM du schéma PostgreSQL `public`, puis les
compare aux métadonnées SQLAlchemy. Le `SchemaTransitionSet` résultant expose :

| Signal | Contenu |
|---|---|
| `added_tables` | tables présentes dans la cible mais absentes de la base |
| `removed_tables` | tables présentes dans la base mais absentes de la cible |
| `added_columns` | clés `table.colonne` ajoutées à une table existante |
| `removed_columns` | clés `table.colonne` retirées d’une table existante |
| `required_columns` | colonnes nouvelles ou existantes qui doivent devenir `NOT NULL` |
| `enums` | ENUM dont les valeurs ou leur ordre diffèrent |
| `definitions` | définitions avant/après des types, défauts, index et clés étrangères |

Les helpers `table_added()` et `column_added()` couvrent les deux cas les plus fréquents. Les
autres ensembles sont directement consultables par un prédicat d’action.

Les définitions d'index comprennent aussi méthode d'accès, expressions, tri observé,
colonnes incluses, classes d'opérateurs, options de stockage et `NULLS NOT DISTINCT`.
Ces différences sont des observations, pas une preuve de conversion sans perte.
Les contraintes CHECK, exclusions et autres constructions non représentées dans ce contrat
restent dans le plan Atlas ; aucune nouvelle transformation automatique ne repose sur elles.

## Cycle d’une synchronisation

Une synchronisation non sèche suit cet ordre :

1. charger les contributions `<module>.dbadmin` des modules actifs ;
2. attendre PostgreSQL et acquérir un verrou consultatif global ;
3. inspecter `public` et calculer une fois le delta vers la cible canonique ;
4. créer si nécessaire les tables de journal DbAdmin ;
5. vérifier les actions inachevées et les successions explicitement compatibles ;
6. exécuter les actions `BEFORE_EXPAND` ;
7. préparer les changements d’ENUM ;
8. appliquer avec Atlas une cible où les nouvelles colonnes obligatoires sont temporairement
   nullables ;
9. exécuter les actions `AFTER_EXPAND` ;
10. faire converger les datasets, puis les reconcilers ;
11. exécuter les actions `AFTER_DATASET` ;
12. rendre `NOT NULL` les colonnes dont le backfill est complet et réappliquer la cible Atlas ;
13. exécuter les actions `AFTER_CONTRACT` ;
14. libérer le verrou, calculer le verdict et persister un résumé borné.

Toutes les phases reçoivent le même `SchemaTransitionSet`, calculé avant la première application
Atlas. Une action `AFTER_EXPAND` peut se déclencher sur la suppression prévue d’une ancienne
colonne : celle-ci est conservée pendant l’expansion pour permettre le transfert des données.

### Les phases d’action

| Phase | Moment | Usage typique |
|---|---|---|
| `BEFORE_EXPAND` | avant toute intervention Atlas | sauvegarder une donnée menacée ou préparer une transformation |
| `AFTER_EXPAND` | après création de la nouvelle structure | backfiller ou réinjecter dans le nouveau modèle |
| `AFTER_DATASET` | après les datasets et reconcilers | utiliser des références permanentes fraîchement convergées |
| `AFTER_CONTRACT` | après le dernier passage Atlas | vérifier ou nettoyer un état transitoire |

Le premier passage Atlas interdit les suppressions de tables et de colonnes et garde les
colonnes obligatoires concernées temporairement nullables. Ce garde ne transforme pas un
changement de type en conversion sans perte : ces transformations exigent toujours une action
adaptée. Une action indispensable en échec avant l’expansion arrête le DDL. Une contribution
différée conserve les sources et permet les ajouts. La contraction destructive et les actions
`AFTER_CONTRACT` attendent la fin des préparations et du remplissage des colonnes obligatoires.

## Modifier le schéma

Pour une évolution ordinaire :

1. modifier le modèle SQLAlchemy sous `back/core`, `back/app` ou `back/bridge` ;
2. vérifier que le module est actif dans `back/modules.py` et que son modèle est importé ;
3. ajouter une action seulement si les données existantes exigent une transformation particulière ;
4. lancer `make sync-db` ;
5. inspecter le résultat et tester le contrat modifié.

Ne jamais :

- lancer Atlas directement ;
- créer une migration Alembic ;
- exécuter du DDL `public` dans le démarrage FastAPI ;
- définir une table applicative hors `public` dans les métadonnées `Base` ;
- conserver dans `public` une table technique absente de la cible SQLAlchemy.

### Nouvelle colonne obligatoire

Une nouvelle colonne `NOT NULL` sans défaut serveur est d’abord créée nullable. Une action
`AFTER_EXPAND` remplit les lignes existantes. DbAdmin ne resserre la colonne que lorsqu’aucune
valeur `NULL` ne subsiste.

L’absence de backfill n’est pas une panne bloquante : la colonne est disponible en nullable,
un message d’erreur explicite signale l’écart et le processus sort avec le code zéro (`STAGED`).
L’application peut remplir les valeurs ; une prochaine synchronisation impose `NOT NULL`.
Une contraction en échec après une expansion utilisable produit `DEGRADED`, également non
bloquant. L’impossibilité de créer les objets indispensables reste fatale.

```python
from typing import cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminAction,
    DbAdminPhase,
    DbAdminRegistry,
    SchemaTransitionSet,
)


def _needs_backfill(transitions: SchemaTransitionSet) -> bool:
    return any(item.key == "widgets.owner_id" for item in transitions.required_columns)


async def _backfill(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    widgets = cast(Table, Widget.__table__)
    await session.execute(
        update(widgets)
        .where(widgets.c.owner_id.is_(None))
        .values(owner_id=widgets.c.created_by)
    )


async def _is_complete(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    widgets = cast(Table, Widget.__table__)
    missing = await session.scalar(
        select(func.count()).select_from(widgets).where(widgets.c.owner_id.is_(None))
    )
    return int(missing or 0) == 0


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.widget.backfill_owners",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1-created-by",
            predicate=_needs_backfill,
            handler=_backfill,
            postcondition=_is_complete,
        )
    )
```

Le checksum est une empreinte développeur stable du comportement attendu. Ce n’est ni un numéro
de migration, ni un ordre global.

### ENUM

Ajouter une valeur d’ENUM est automatique. Retirer, renommer ou réordonner des valeurs exige un
`DbAdminEnumMapping` total pour chaque ancienne valeur qui ne reste pas valide. DbAdmin prépare la
conversion avant Atlas et refuse une transformation destructive incomplète.

## Actions conditionnelles

Une `DbAdminAction` déclare :

| Champ | Contrat |
|---|---|
| `key` | identité globale stable, généralement préfixée par le module |
| `phase` | unique phase d’exécution |
| `checksum` | identité du comportement tant que l’action reste inachevée |
| `predicate` | décision pure basée sur le delta courant |
| `handler` | transformation async recevant une `AsyncSession` |
| `postcondition` | preuve async que l’état désiré est atteint |
| `required` | une exception rend-elle le verdict fatal ; vrai par défaut |
| `compatible_checksums` | anciens comportements que le handler et la postcondition courants peuvent reprendre sans perte ; vide par défaut |

Avant le handler, DbAdmin évalue la postcondition. Si elle est déjà vraie, l’action devient
`already_satisfied`. Sinon, le handler et la seconde vérification de postcondition s’exécutent dans
la même transaction : succès validé par commit, exception annulée par rollback. Un crash après le
commit mais avant l’écriture du statut est récupérable grâce à la postcondition au prochain run.

Le handler doit donc :

- être idempotent ;
- traiter un volume borné ou employer une stratégie de reprise explicite ;
- ne jamais dépendre du statut journalisé comme source métier ;
- ne pas écrire de secret dans les logs ou erreurs ;
- laisser la postcondition vérifier l’état réel, pas seulement le passage du code ;
- utiliser uniquement la surface publique `core.dbadmin`, jamais `core.dbadmin._internal`.

Une action appartient à une seule phase. Pour encadrer Atlas, enregistrer deux actions distinctes
avec des clés et postconditions propres.

## Sauvegarde provisoire et réinjection

Une transformation complexe peut nécessiter de préserver l’ancienne représentation avant de
construire la nouvelle :

```text
BEFORE_EXPAND
  ancienne structure
        ↓ copie idempotente
  galaris_migration.widget_backup

première application Atlas
        ↓
AFTER_EXPAND
  lecture du backup
        ↓ transformation
  écriture dans le nouveau modèle public

dernier passage Atlas
        ↓
AFTER_CONTRACT
  validation finale ou nettoyage explicite
```

Deux sessions différentes exécutent les actions avant et après Atlas. Une table PostgreSQL `TEMP`
ne peut donc pas transporter les données entre phases. Une table provisoire non déclarée dans
`public` serait par ailleurs supprimée par Atlas.

Pour une sauvegarde durable entre phases :

- utiliser un schéma hors cible comme `galaris_migration` ;
- créer la table et copier les données de manière idempotente ;
- ne pas l’ajouter aux métadonnées SQLAlchemy `Base`, qui n’acceptent que `public` ;
- définir une clé permettant de reprendre sans doublons ;
- vérifier la complétude et l’intégrité dans la postcondition ;
- décider explicitement si la sauvegarde est conservée pour audit ou supprimée après validation.

Les deux actions peuvent partager un prédicat fondé sur le delta initial :

```python
def _moves_legacy_payload(transitions: SchemaTransitionSet) -> bool:
    return (
        "records.payload" in transitions.removed_columns
        and "records.document_id" in transitions.added_columns
    )
```

### Barrières effectives et limites

Une exception d’action `required=True` en `BEFORE_EXPAND` arrête le pipeline avant Atlas.
Une postcondition encore fausse produit un état différé non bloquant : l’expansion peut créer
les nouveaux objets, mais les tables et colonnes sources restent présentes. Après expansion
ou datasets, une erreur indispensable interdit la contraction ; un écart non fatal conserve
les sources et laisse fonctionner le schéma utilisable. `AFTER_CONTRACT` attend la convergence.

Ces protections et la reprise sont testées sur PostgreSQL. Elles ne constituent pas une
transaction globale : une expansion déjà réussie reste appliquée si une phase ultérieure échoue.
Un changement de type peut lui aussi perdre des données ; la protection des suppressions de
tables/colonnes ne suffit pas à le rendre sûr. Pour ces transformations, conserver l’ancienne
représentation, sauvegarder et backfiller avant son retrait lors d’une livraison ultérieure.

## Datasets, reconcilers ou actions ?

| Besoin | Contrat |
|---|---|
| jeu de lignes permanent décrit par clé naturelle | `DbAdminDataset` |
| projection dérivée entièrement reconstruisible | `DbAdminReconciler` |
| transformation conditionnée par un changement de schéma | `DbAdminAction` |
| changement de table, colonne, index ou contrainte | modèle SQLAlchemy, appliqué par Atlas |

Les datasets sont ordonnés par `depends_on`. Les reconcilers s’exécutent ensuite et peuvent aussi
dépendre de datasets ou d’autres reconcilers. Les actions n’ont pas de graphe de dépendance : leur
ordre principal est leur phase, puis leur clé triée dans le registre. Si deux transformations
doivent être atomiquement ordonnées dans une même phase, les réunir dans un handler cohérent au
lieu de dépendre artificiellement du tri lexical.

### Données initiales laissées à l’administrateur

Les civilités des agents (`titles`) sont initialisées avec les clés i18n
`agent_titles.mr` (`M`) et `agent_titles.ms` (`F`) dans le champ `label` existant,
par l’action `app.agent.initial_titles`, en phase `AFTER_EXPAND`, uniquement lorsque la table
vient d’être créée. Ce n’est pas un dataset permanent : `update_columns=()` préserverait les
valeurs, mais recréerait des lignes supprimées ou renommées lors d’une synchronisation suivante.
Les démarrages et mises à jour ultérieurs ne modifient donc plus ce référentiel, même s’il est
entièrement vidé. Une base possédant déjà la table n’est pas peuplée rétroactivement.
Les identifiants sont attribués par PostgreSQL ; aucun identifiant de civilité n’est imposé.
L’interface affiche **Mr/Ms**, **Monsieur/Madame** ou **先生/女士** selon la langue.
Enregistrer sans modifier le libellé préserve la clé ; le renommer la remplace par le texte
personnalisé, affiché tel quel dans toutes les langues. La traduction appartient exclusivement
au frontend ; le backend conserve et expose les valeurs brutes.

## Journal, reprise et changement de branche

DbAdmin conserve :

- un résumé de chaque run dans `dbadmin_runs` ;
- jusqu’à cent problèmes bornés dans `dbadmin_issues` ;
- le dernier état de chaque action dans `dbadmin_actions`.

Les statuts d’action sont `running`, `deferred`, `failed`, `applied` et `already_satisfied`.
Lorsqu’une action est `running`, `deferred` ou `failed` :

- son code doit rester enregistré ;
- un changement de checksum exige de déclarer l’ancien dans `compatible_checksums` ;
- sa postcondition doit permettre une reprise idempotente.
- elle reste applicable aux synchronisations suivantes même lorsque le delta de schéma initial a
  disparu ; le journal durable porte alors l’obligation jusqu’à validation de la postcondition.

La disparition ou la modification incompatible d’une action indispensable arrête la synchronisation.
Pour une action facultative, DbAdmin signale un écart non bloquant, conserve le journal ancien et
les sources, et permet l’expansion sans exécuter le handler incompatible. Une succession déclarée
compatible réévalue la postcondition ; si elle est déjà vraie, aucun handler n’est exécuté.
`dbadmin_action_revisions` conserve la criticité des comportements admis. Pour un ancien journal
sans cette information, la déclaration présente fait foi ; une action disparue de criticité
inconnue reste bloquante. La compatibilité est une garantie développeur sur les données partielles,
pas une manière de sauter une transformation destructive. Une action
terminée n’est pas une révision globale interdisant toute réexécution future : le delta courant et
la postcondition restent les autorités. C’est ce qui permet le travail sur plusieurs branches.

Le verrou consultatif PostgreSQL empêche deux synchronisations DbAdmin concurrentes. Chaque action,
dataset et reconciler utilise sa propre transaction ; ils ne forment pas une transaction globale
avec Atlas.

## Verdicts

| Verdict | Signification |
|---|---|
| `converged` | aucune anomalie et aucune colonne obligatoire en attente |
| `staged` | aucune anomalie, mais une colonne reste nullable faute de backfill complet |
| `degraded` | au moins une anomalie non fatale |
| `fatal` | au moins une anomalie fatale ; la commande retourne un code non nul |

Le verdict décrit le résultat final du run. Un verdict fatal après expansion n’annule pas les
modifications intermédiaires déjà réussies ; voir les barrières et limites ci-dessus.

## Tests et validation

Une évolution doit au minimum tester :

- le prédicat sur un `SchemaTransitionSet` applicable et non applicable ;
- l’idempotence du handler ;
- la postcondition avant et après transformation ;
- le rollback en cas d’exception ;
- le scénario PostgreSQL réel pour toute expansion/contraction sensible ;
- la conservation des données lors d’un aller-retour pertinent entre états de schéma.

Exécuter ensuite :

```bash
make tests ARGS='core/dbadmin/tests app/<module>/tests/test_dbadmin.py'
make typecheck
make architecture-check
git diff --check
```

Les tests backend passent toujours par `make tests` et sa base PostgreSQL éphémère. Ne jamais
lancer `pytest` dans le conteneur de développement.

## Références dans le code

- [contrats publics](../../../back/core/dbadmin/contracts.py) ;
- [registre des actions et reconcilers](../../../back/core/dbadmin/registry.py) ;
- [calcul du delta](../../../back/core/dbadmin/snapshot.py) ;
- [orchestrateur](../../../back/core/dbadmin/orchestrator.py) ;
- [exécution et suivi des actions](../../../back/core/dbadmin/actions.py) ;
- [datasets](../../../back/core/dbadmin/dataset.py) ;
- [cible SQLAlchemy adaptée](../../../back/core/dbadmin/_internal/target.py) ;
- [tests PostgreSQL](../../../back/core/dbadmin/tests/test_postgresql_transitions.py).

## Définitions observées

`SchemaTransitionSet.definitions` décrit les différences observées de types de colonnes,
défauts serveur, index et clés étrangères, avec définition avant/après. Ces preuves sont
informatives : la comparaison textuelle peut signaler une différence de représentation SQL,
et ne garantit pas l'équivalence sémantique de deux expressions SQL. Elle ne donne aucune autorisation
supplémentaire de conversion ou de suppression ; Atlas et les barrières de préservation restent
responsables de l'application. Les checkpoints JSON multimédia utilisent séparément un schéma
versionné ; une version future non comprise échoue sur le run concerné, pas au démarrage global.
