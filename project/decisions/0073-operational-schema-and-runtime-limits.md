# 0073 — Disponibilité pendant les évolutions et limites opérationnelles

Statut : accepté — 2026-09-06.

## Décision

DbAdmin privilégie un schéma utilisable. Une colonne requise sur une table remplie est créée
nullable ; l’écart est une erreur visible non bloquante. Le remplissage puis la prochaine
synchronisation permettent de converger. L’expansion conserve les tables et colonnes sources ;
les contributions différées empêchent leur suppression. Les erreurs de contraction après
expansion utilisable sont non bloquantes. Les objets indispensables manquants et les
préparations indispensables en échec restent bloquants.

La topologie supportée est un backend Uvicorn à un seul worker par installation. Un deuxième
worker ne partage pas les caches, sockets, listeners et états locaux ; le démarrage standard
refuse donc `WEB_CONCURRENCY` ou `--workers` différents de 1. Plusieurs installations ne doivent
pas partager leur base comme moyen de distribuer cette application.
La [décision 0119](0119-file-input-preferences-and-fixed-server-topology.md) remplace ensuite
le refus de `WEB_CONCURRENCY` par un worker explicitement imposé au démarrage, indépendant
de cette ancienne variable ; les arguments CLI multiworkers restent refusés.

Les limites de budget racine et la rétention sont des paramètres administrables désactivés
par défaut. Le budget d’admission suit `parent_id`, puis `source_task_id`, et compte les appels
LLM une seule fois. Les baux actifs réservent une estimation par phase sous verrou transactionnel.
Une expiration libère cette réservation, jamais les coûts déjà constatés. Les limites portent
sur l’admission de nouvelles phases ; une phase active peut dépasser son estimation et le délai
ne l’interrompt pas. Elles ne constituent pas une garantie de facturation fournisseur.
`TASK_BUDGET_SHARE_GOAL`, désactivé par défaut, partage les plafonds entre les tâches de tous
les cycles du même Goal ; le temps est compté depuis la première tâche. L’archivage d’une tâche
ne réinitialise pas ses dépenses. Le quota de concurrence par propriétaire, également désactivé
par défaut, est partagé entre ses agents et réservé par les leases sous verrou transactionnel.

La résolution humaine d’une livraison `UNKNOWN` s’applique au tour et aux notifications de ses
liens Task/Process. Elle exige un périmètre autorisé, une preuve et la tentative courante, et
refuse un bail actif. Une décision répétée à l’identique est idempotente ; une décision
contradictoire est refusée. Elle ne renvoie rien et ne rejoue aucun travail.

La rétention ne supprime ni les incidents ni les appels LLM : elle réduit leurs détails par
lots de 100, avec `SKIP LOCKED`, et conserve les agrégats et références. Les incidents non résolus
sont conservés. Les appels conversation/process sont conservés ; les appels liés aux tâches le
sont tant qu’une tâche quelconque reste non terminale. Ce choix conservateur peut retarder la purge.

Les images destinées à une promotion sont construites une fois à partir d’un commit immuable,
exportées avec leurs identités et sommes SHA-256, puis chargées sans reconstruction.
Le retour arrière de code exige une compatibilité de schéma vérifiée ou une restauration
conjointe de la base, des fichiers et des clés. Un simple remplacement d’image n’annule pas le DDL.

## Vérification

Tests PostgreSQL de staging/reprise et contraction en échec ; budgets de descendants et baux
expirés ; rétention bornée et conservation des agrégats ; restauration par login/API et ACL ;
exercice de convergence depuis un schéma précédent rempli. Les artefacts utilisent les mêmes
images entre environnements ; les paquets système restent résolus à la construction.
