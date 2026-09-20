# Transformations conditionnées par un delta de schéma

Lire cette référence pour les backfills, changements de représentation, opérations volumineuses
et anciens « scripts manuels » qui doivent se lancer lorsque les modèles changent.

## Détection disponible

Le prédicat d'une `DbAdminAction` reçoit le `SchemaTransitionSet` calculé une seule fois avant la
première application Atlas. Il peut actuellement détecter :

- tables ajoutées ou retirées ;
- colonnes ajoutées ou retirées ;
- colonnes qui doivent devenir `NOT NULL` ;
- différences d'ENUM.

Les changements de type, index, clé étrangère, contrainte et valeur par défaut ne sont pas encore
des signaux typés, même si Atlas sait les appliquer. Étendre d'abord le snapshot,
`SchemaTransitionSet` et les tests si une action doit dépendre d'un tel signal ; ne pas inférer ce
changement par une heuristique fragile.

## Contrat d'une action

Une action possède une clé stable, une phase, un checksum de comportement, un prédicat pur, un
handler async idempotent et une postcondition async qui prouve l'état métier final.

- Vérifier la postcondition avant d'écrire permet de récupérer un crash après commit.
- Garder le checksum inchangé tant qu'une action est `running`, `deferred` ou `failed`. DbAdmin
  refuse la disparition ou la modification d'une obligation inachevée.
- Ne pas prendre le journal DbAdmin comme vérité métier : seule la postcondition fait foi.
- `required=True` rend une exception fatale ; une postcondition encore fausse produit un état
  différé et devra converger lors d'une synchronisation ultérieure.
- Ne jamais inclure de secret ou de donnée sensible dans les exceptions et journaux.

Le checksum n'est pas un numéro de migration. Une action terminée peut redevenir applicable sur
une autre base ou après un changement de branche si le delta et la postcondition l'exigent.

## Choisir la phase

| Phase | Usage |
|---|---|
| `BEFORE_EXPAND` | lire ou sauvegarder une ancienne représentation avant Atlas |
| `AFTER_EXPAND` | backfiller une structure nouvellement créée ou temporairement nullable |
| `AFTER_DATASET` | transformer avec des références permanentes fraîchement convergées |
| `AFTER_CONTRACT` | vérifier ou nettoyer après la cible finale |

Toutes les phases voient le delta initial. Deux actions placées dans des phases différentes ont
des sessions différentes. Une table `TEMP` ne transporte donc pas les données entre phases.

Pour une sauvegarde intermédiaire, utiliser un schéma durable hors de la cible `public`, par
exemple `galaris_migration`, avec une clé de reprise et une postcondition d'intégrité. Ne pas ajouter
la table de sauvegarde aux métadonnées `Base`. Décider explicitement de sa conservation pour audit
ou de son nettoyage après validation.

## Nouvelle colonne obligatoire

DbAdmin ajoute d'abord une nouvelle colonne `NOT NULL` comme nullable. Une action
`AFTER_EXPAND` remplit les lignes existantes. La postcondition compte les valeurs manquantes ; le
dernier passage Atlas resserre la nullabilité seulement lorsque ce compte atteint zéro.

Le prédicat doit viser `required_columns` ou `column_added()` avec la clé exacte. Tester le cas
applicable, le cas sans delta et une seconde exécution déjà satisfaite.

## Opération volumineuse

Avant l'implémentation, estimer le nombre de lignes, le coût des index, les verrous et la durée
acceptable avant le démarrage d'Uvicorn. Le verrou consultatif DbAdmin couvre tout le pipeline.

- Préférer les opérations SQL ensemblistes lorsqu'elles sont bornées et sûres.
- Pour un volume important, rendre le travail reprenable à partir de l'état des données ou d'un
  checkpoint durable ; ne jamais dépendre d'une variable en mémoire.
- Limiter chaque transaction et éviter de charger la table entière dans l'ORM.
- Une action différée n'est pas une boucle automatique : planifier et vérifier les
  synchronisations suivantes jusqu'à satisfaction de la postcondition.
- Si la transformation ne peut raisonnablement finir avant le service, livrer d'abord une
  structure compatible, faire converger les données de façon reprenable, puis contracter lors
  d'une livraison ultérieure.

## Contraction destructive : règle impérative

Une action indispensable `BEFORE_EXPAND` en échec arrête maintenant le DDL. Le premier passage
Atlas préserve tables et colonnes sources ; une contribution différée empêche leur contraction.
Ce garde ne garantit pas qu'un changement de type est sans perte : les conversions sensibles
doivent toujours disposer d'une préparation adaptée.

Une colonne requise sans défaut sur une table remplie est créée nullable, avec erreur visible
non bloquante (`STAGED`, sortie zéro). L'application peut la remplir puis une synchronisation
ultérieure impose `NOT NULL`. Une contraction en échec après expansion utilisable reste non
bloquante. Réserver le caractère indispensable aux objets ou préparations sans lesquels
l'application ne peut pas fonctionner ou les données seraient menacées.

Procéder en plusieurs livraisons :

1. conserver l'ancien objet dans le modèle et ajouter la nouvelle structure ;
2. sauvegarder si nécessaire, backfiller et prouver la convergence ;
3. déployer et observer l'utilisation de la nouvelle représentation ;
4. retirer l'ancien objet du modèle dans une livraison ultérieure ;
5. nettoyer la sauvegarde seulement après validation explicite.

Ajouter un test PostgreSQL réel qui démontre la conservation des données et, lorsque pertinent,
un aller-retour entre les deux états de schéma.
