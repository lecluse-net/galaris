# ADR 0044 — DbAdmin idempotent comme autorité de synchronisation PostgreSQL

- Statut : Accepted
- Date : 2026-08-21
- Remplace partiellement : ADR 0004 pour l’orchestration opérateur

## Contexte

Atlas comparait déjà la cible SQLAlchemy à PostgreSQL, mais son shell et les réconciliations de
données étaient appelés séparément. Une nouvelle colonne `NOT NULL` sans défaut sur une table
peuplée et certaines évolutions d’ENUM pouvaient donc faire échouer une montée en version avant
qu’un traitement de données ait préparé la base. Atlas exposait aussi directement son cycle aux
commandes opérateur.

Une mise à jour de Galaris doit rester non interactive : l’administrateur qui déploie ne connaît
pas les décisions métier nécessaires pour approuver ou refuser une suppression. Les décisions
doivent être codées, testées et rejouables. En revanche, un échec total ne doit jamais être
masqué : il doit empêcher le backend de servir du trafic et fournir un diagnostic explicite.

## Décision

`core.dbadmin` devient l’unique autorité de synchronisation. Le reste du dépôt appelle seulement
`python -m core.dbadmin` : Atlas, ses fichiers cibles, son schéma de travail et ses options restent
des détails privés sous `core.dbadmin._internal`.

Le périmètre DDL est volontairement simple : Galaris possède entièrement le schéma PostgreSQL
`public`. Une table, colonne, contrainte, index ou type absent de la cible SQLAlchemy y est donc
retiré automatiquement, sans confirmation. Tous les autres schémas sont hors périmètre ; le
schéma `vectors`, les extensions et le schéma de travail Atlas ne sont pas une seconde cible
applicative.

DbAdmin :

- compare l’état réel à une copie isolée des métadonnées SQLAlchemy ;
- ajoute d’abord comme nullable une nouvelle colonne requise sans défaut, exécute les actions et
  datasets, puis pose `NOT NULL` dès que la colonne ne contient plus de `NULL` ;
- prépare les ajouts d’ENUM et remplace transactionnellement un ENUM destructif seulement lorsque
  le développeur a fourni un mapping total des anciennes valeurs ;
- permet aux modules de contribuer des actions conditionnées par le delta et dotées d’une
  postcondition, ainsi que des sources de données et des réconciliateurs d’état dérivé ;
- découvre les `DbAdminDataSource` dans `<module>.dbadmin`, compile les datasets qu’elles
  produisent, refuse collisions et cycles, puis isole leur transaction et leur diagnostic ;
- compose les traitements Hermès existants depuis `back/dbadmin_composition.py`, sans modifier le
  bridge en cours de développement ;
- sérialise les exécutions avec un verrou PostgreSQL et journalise un bilan borné ;
- ne pose aucune question. Un résultat `fatal` produit des logs `ERROR`, un code non nul, bloque
  Uvicorn et fait échouer `make update`. Un résultat `degraded` reste visible mais peut autoriser
  le démarrage ; une expansion inachevée connue produit `staged`.

Depuis le 12 septembre 2026, `make update` prend aussi en charge le développement : les images
dev sont reconstruites avec cache, puis la stack redémarre et attend un backend sain. La commande
de démarrage dev appelle DbAdmin avant Uvicorn, comme l’entrypoint de production.
Depuis le 16 septembre 2026, les mises à jour ordinaires de production réutilisent également
le cache Docker, tout en vérifiant les images de base avec `--pull`. L’invalidation du cache PWA
reste propre à chaque compilation frontend ; elle n’exige pas de reconstruire les dépendances
et les exécuteurs inchangés. Le chemin `RELEASE_DIR` conserve ses images qualifiées sans reconstruction.
`make sync-db` rejoue le même orchestrateur dans le conteneur de développement sans redémarrage.
Les tests utilisent également ce chemin sur leur PostgreSQL éphémère.

## Conséquences

- une suppression dans `public` est une décision déclarative du code et non une question posée au
  déploiement ;
- un modèle qui cible un autre schéma est refusé avant l’appel à Atlas ;
- l’idempotence est vérifiable par une seconde synchronisation sans DDL ;
- les transformations nécessitant une décision métier restent impossibles sans mapping ou
  postcondition explicite, et échouent alors avant la transformation destructive ;
- `HistoryMixin` ne change pas. Les tables techniques du journal DbAdmin ne l’utilisent pas ;
- le bridge Hermès et ses migrations en cours ne sont pas modifiés par cette décision ;
- le lifespan FastAPI ne synchronise plus de données persistantes : il charge seulement en
  mémoire les paramètres déjà réconciliés par DbAdmin.
- un dataset est toujours un merge tabulaire par clé naturelle. Une projection ou une réparation
  procédurale est explicitement un `DbAdminReconciler`, jamais un dataset à handler opaque.

## Preuves dans le code

`back/core/dbadmin/`, `back/modules.py`, `back/entrypoint.sh`, `bin/test-back.sh`, les cibles
`make update` / `make sync-db` et les tests de `core.dbadmin`.
