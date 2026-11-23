# 0309 — Service Processus avec une portée personnelle par défaut

Statut : accepté — 22 novembre 2026. Remplace la répartition des fonctions de la
[décision 0008](0008-personal-processes-and-administration.md).

Le service intégré **Processus** (`process`) regroupe les outils MCP de processus.
Les noms des outils, le routage de l’API Process et les codes des moteurs restent stables.
La projection conversationnelle garde les quatre lectures autorisées de processus.

Chaque agent reçoit une connexion active en portée `personal`. Un humain habilité peut
déléguer les portées `team` et `all`. En portée personnelle, les opérations de gestion
portent sur les définitions affectées à l’agent et les exécutions qu’il a lancées. Les ACL
des processus natifs continuent de s’appliquer aux exécutions. La découverte des moteurs,
leur synchronisation et l’association d’un workflow externe exigent `all`.

DbAdmin renomme `process_admin` sur place, active les anciennes connexions sans portée
locale et transfère les politiques globales et locales des outils déplacés depuis `galaris`.
Les délégations enregistrées et les réglages déjà présents sur la connexion de destination
sont conservés. Une connexion inactive qui porte une délégation explicite reste inactive.
