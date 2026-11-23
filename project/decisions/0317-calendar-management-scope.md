# 0317 — Portée de gestion des agendas

Statut : accepté — 23 novembre 2026.

La connexion système `calendar` déclare `services.management_scope`. Le mode `personal`
est le défaut pour tous les agents. Le mode `team` étend la gestion aux agents partageant
une équipe avec l’appelant. Le mode `all` couvre l’ensemble des agents.

Un appel MCP sur l’agenda d’un autre agent est autorisé sur la connexion Agenda de
l’appelant. Il relit la délégation locale et les appartenances aux équipes. Un appel sur
son propre agenda utilise la connexion de la source. La persistance, la synchronisation
et les rappels continuent de s’exécuter pour le propriétaire de l’agenda ciblé.

La délégation couvre aussi les métadonnées des références `galaris://calendar/`. Le
contexte temporel automatique conserve les sources personnelles de l’appelant. L’API
humaine conserve son périmètre RBAC.
