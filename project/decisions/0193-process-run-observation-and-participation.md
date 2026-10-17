# 0193 — Observation des exécutions et participation figée

Statut : accepté — 2026-10-16.

La [décision 0198](0198-process-run-data-and-files.md) remplace la politique
d'accès indépendante des runs par les droits du processus parent et ajoute
les ressources de données et pièces jointes sous `galaris://processes/runs/`.

## Décision

Le détail d'une exécution et l'outil agentique `processus_get` partagent une projection
opérationnelle issue des occurrences, tentatives, Tasks et événements persistés. Elle
expose les attentes humaines, autorisations, sous-processus, travaux en file ou en cours,
erreurs et dernière activité. Un délai sans événement n'établit pas un blocage. Les
compteurs d'occurrences ne prétendent pas mesurer un pourcentage pour un graphe à boucles.
L'inspection ne fait pas avancer le moteur.

La référence copiable d'un run est `galaris://processes/runs/<uuid>`, indépendante de l'adresse
Web de l'installation. File Sharing expose cette projection native en lecture seule : info,
lecture JSON paginée et export par copie, sans liste ni recherche générique. Process
possède la projection et les autorisations ; le provider ne fait pas avancer le moteur.
Les commandes métier acceptent aussi cette référence à la place de l'UUID brut.

La portée agentique contient le lanceur et les agents affectés à des activités du graphe
figé, y compris les corps de boucle et leurs défauts hérités. Un rôle inutilisé n'accorde
aucun accès. Les droits de définition et de Dataset restent indépendants : une modification
ou un nouveau partage ne donne pas accès aux anciennes exécutions. Un reconciler DbAdmin
idempotent complète les snapshots historiques depuis leur propre graphe figé.

L'administration globale des exécutions exige une connexion dédiée `process_admin`
active, revérifiée à chaque requête. `galaris_admin` ne suffit pas. Les filtres s'appliquent
avant comptage et pagination, également aux enfants et métriques inclusives. Les agents
participants lisent ; le lanceur et les administrateurs Process contrôlent. Les accès
humains conservent leur portée de gestion et leurs ACL existantes.

La pause bloque les nouvelles admissions et laisse finir les effets admis. La reprise
continue le même run. L'arrêt ferme les demandes humaines et interrompt Tasks et enfants ;
`cancelling` persiste tant que les arrêts requis ne sont pas confirmés. Les états terminaux
restent immuables et un résultat d'effet incertain interdit la reprise sans réconciliation.

## Vérification

Les intégrations vérifient la participation figée, l'indépendance des grants Dataset,
la révocation du droit dédié, les refus de contrôle pour les participants et les lectures
indirectes. Le cycle attente/pause/reprise/arrêt préserve l'identité et les états terminaux.
Les parcours Vue/Quasar exercent la confirmation d'arrêt et le suivi en lecture seule.
