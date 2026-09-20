# Delta de fin d'audit

Une deuxième copie du répertoire de travail a été prise pendant l'audit pour examiner les changements concurrents. **Le Lab est exclu sur demande de l'utilisateur.** Le périmètre restant contient **503 fichiers candidats et 3 293 définitions**, soit neuf définitions supplémentaires par rapport à la référence initiale. Deux corps de tests existants ont changé. Les déplacements de lignes seuls ne sont pas comptés comme de nouveaux tests.

L'[inventaire du delta](delta-tests.csv) complète l'inventaire initial. Les [résultats détaillés](delta-resultats.json) restent séparés : la suite complète initiale n'a pas été rejouée sur cette deuxième copie.

## Résultats ciblés

| Sélection | Résultat |
|---|---|
| `core/dbadmin/tests/test_volume_transitions.py`, activé explicitement | 1 réussi, 100 000 lignes |
| `core/preview/tests/test_conversion.py` | 8 cas réussis, issus de 4 définitions |
| `front/app/process/runActions.test.mjs` et `runDetailDialog.test.mjs` | 8 réussis |
| `make tests-restore` | Réussi ; 28 écritures validées restaurées, aucune perdue |
| `make tests-load` | 1 réussi, charge mixte pendant 60 secondes |

## Nouveaux tests de conversion : à conserver

Les quatre définitions de `core/preview/tests/test_conversion.py` exercent le registre réel et `prepare_preview` : retour de la source inchangée sans convertisseur compatible, rejet d'un nom déjà enregistré, sélection unique par priorité puis nom, préservation du fichier original et nettoyage du dérivé en succès, erreur et annulation.

Les huit cas réussissent. Ils protègent le contrat local de sélection et de durée de vie des fichiers ; ils ne qualifient pas le fonctionnement d'un futur convertisseur externe.

## Nouveaux tests Process : un modèle pertinent à reproduire

Les cinq tests de `runActions.test.mjs` exécutent le composable et le store réels avec Vue et Pinia. Ils vérifient fermeture pendant une requête, rejet tardif d'une ancienne sélection, notification d'une erreur courante, unicité du rafraîchissement avec arrêt au démontage, et nouvelle vérification des droits après confirmation.

Ils réussissent et sont **à conserver**. Les dépendances réseau, minuterie et dialogue sont substituées, ce qui convient à cette couche. Les trois tests voisins de `runDetailDialog.test.mjs` restent des inspections de sources : leur réussite ne démontre pas le rendu responsive ni les événements du dialogue.

## Qualification DbAdmin exécutée

Le test modifié mesure maintenant les phases et observe explicitement une attente de verrou PostgreSQL. Il a réussi sur 100 000 lignes, avec 409 écritures concurrentes validées, interruption d'une application DDL puis reprise, remplissage de la colonne, contrainte `NOT NULL`, création d'index et rejeu idempotent.

Le [rapport de volume](dbadmin-volume-benchmark.json) conserve les mesures de cette exécution. Les durées reflètent la machine de l'audit et cette taille de données ; elles ne sont pas un engagement de performance en production.

## Restauration et charge : preuves opérationnelles à conserver

`make tests-restore` a réussi en 49 secondes. Il exerce sauvegarde et restauration PostgreSQL, fichiers persistants et clés, puis contrôle les accès autorisés et refusés. Les deux écrivains ont validé 28 opérations avant la frontière de quiescence ; les 28 ont été retrouvées après restauration. Il s'agit d'une preuve sur ce jeu de données et cette procédure, pas d'une garantie pour toutes les formes de sauvegarde possibles.

`make tests-load` a réussi en 60,46 secondes. Le scénario conserve une lease renouvelée pendant les opérations réseau et fichiers ; il a reçu 2 728 trames WebRTC. Les mesures observées comprennent un p95 de requête d'identité d'environ 22 ms, un retard maximal de boucle d'environ 109 ms et une hausse maximale de RSS d'environ 61 Mio. Ce sont les observations d'une exécution locale, pas des seuils de capacité de production.

La revue complémentaire des assertions placées dans des boucles ou conditions n'a pas démontré de nouveau test vide hors Lab. Les cas repérés utilisent principalement des listes fixes non vides, des paramètres contrôlés ou des inventaires dont d'autres tests vérifient aussi le contenu. Une boucle n'est donc pas, à elle seule, un motif de suppression.

Les captures de référence et du delta sont identifiées par [leurs empreintes initiales](sources-initial.sha256) et [leurs empreintes du delta](sources-delta.sha256). Le fichier `.env` synthétique est exclu de ces manifestes. Les modifications postérieures à cette seconde capture ne sont pas attribuées à ces résultats.
