# 0311 — Services Agent, Services et Agenda

Statut : accepté — 22 novembre 2026.

**Agent** (`agent`) regroupe `agent_list`, `agent_get` et les fonctions du service
`agent_admin`. **Services** (`service`) regroupe `services_list` et les fonctions de
`service_admin`. **Agenda** conserve son code `agenda`. Les noms d’outils MCP restent stables.

La [décision 0314](0314-calendar-service-code.md) change ensuite le code d’Agenda en `calendar`.

Agent et Services démarrent actifs en mode `usage`, qui expose les outils de consultation
transférés depuis Galaris. L’administration exige une délégation et les autorisations de
fonction habituelles. La lecture de l’annuaire reste disponible en conversation.

DbAdmin applique les renommages de codes et libellés au démarrage ou lors de `make sync-db`
en développement. Pour Agent, Services, Objectifs et Processus, il conserve les identifiants
des services, les connexions, les paramètres, les portées déléguées et les politiques d’outils.
Un conflit entre deux politiques différentes annule leur transfert dans la transaction.
Agenda change de libellé sur la ligne existante.
