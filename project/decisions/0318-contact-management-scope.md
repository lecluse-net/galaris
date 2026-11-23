# 0318 — Portée de gestion du service Contact

Statut : accepté — 23 novembre 2026.

La connexion système `contact` déclare `services.management_scope`. La portée `personal`
est celle de chaque agent par défaut. `team` ajoute les agents d'une équipe active
partagée avec l'appelant et `all` permet de gérer tous les carnets. La délégation est
locale à la connexion et modifiable par un gestionnaire global habilité.

Les quatre outils Contact vérifient la permission et la portée sur la connexion de
l'appelant. Les listes paginent après filtrage des propriétaires. Une création déléguée
appartient au propriétaire ciblé, y compris pour la reconnaissance des expéditeurs Mail.

Les projections File Sharing et Memory conservent leur contrôle par propriétaire.
Les appels de l'API Contacts humaine suivent les privilèges Contacts et les agents
gérés par l'utilisateur. La délégation MCP s'applique aux quatre outils Contact.
