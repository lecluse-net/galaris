# 0315 — Portée commune sur la connexion Services

Statut : accepté — 22 novembre 2026.

La [décision 0319](0319-document-task-management-scopes.md) rattache ensuite les accès aux
tâches à leur propre connexion.

La portée locale `services.management_scope` de la connexion **Services** (`service`)
couvre l’administration des services et les accès délégués aux tâches, conversations,
appels LLM et incidents. Chaque outil garde sa permission sur sa connexion d’origine.
La connexion Galaris conserve les outils de documentation et d’inspection qu’elle héberge.

DbAdmin transfère les anciennes valeurs de Galaris vers Services et retire les doublons
identiques. Des réglages ou activations incompatibles interrompent le transfert. L’autorité
reste une délégation locale accordée par un humain habilité.
