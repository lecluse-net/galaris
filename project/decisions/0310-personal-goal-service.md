# 0310 — Service Objectifs avec une portée personnelle par défaut

Statut : accepté — 22 novembre 2026.

Le service intégré **Objectifs** (`goal`) regroupe les fonctions MCP `goal_*` déjà exposées
par Galaris et par `goal_management`. Les noms d’outils, les URI `galaris://goal/` et leurs
lectures via Partage de fichiers restent stables.

Chaque agent reçoit une connexion active en portée `personal`. La gestion vise ses propres
objectifs et la délégation d’équipe ou globale relève d’un humain habilité. Les outils réservés
à l’objectif courant ou à la rétrospective vérifient également le contexte de la tâche.

DbAdmin renomme `goal_management` sur place et reprend ses connexions selon le mécanisme de la
[décision 0309](0309-personal-process-service.md). Il active les anciennes connexions sans portée
locale, conserve les délégations enregistrées et déplace les autorisations des outils transférés.
