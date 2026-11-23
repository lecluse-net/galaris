# 0319 — Portées de gestion Documents et Tâches

Statut : accepté — 23 novembre 2026.

Chaque connexion `document` et `task` déclare une portée locale `personal`, `team` ou
`all`. Le défaut est personnel. Les droits de fonction et les contrôles du contexte
d'exécution s'appliquent à chaque appel. La délégation suit les équipes actives.

Les outils Documents vérifient la portée sur le propriétaire agent de la ressource native
en plus de son ACL. Les documents détenus par un humain et les fichiers externes suivent
les droits de leur source. Un agent avec droit d'écriture peut gérer le partage d'un document
appartenant à un agent couvert par sa délégation. La création d'une carte mentale utilise
le compte de l'appelant. La lecture ou l'annulation déléguée d'une analyse exige une source
native lisible par l'appelant et un lanceur dans sa portée. Le lanceur peut annuler sa propre
analyse après la révocation de l'accès à sa source. Les analyses en cours revérifient
la portée et l'ACL du lanceur avant chaque étape.

Les outils et projections agentiques des Tâches utilisent la connexion `task`. Le
demandeur agent peut consulter la tâche qu'il a déléguée. Commander une tâche requiert
la portée sur l'agent affecté. Les opérations d'arbre contrôlent la racine ciblée.
`task_run` requiert une cible dans la portée et applique l'isolation inter-agents.
Le suivi d'avancement utilise la tâche en cours de l'appelant. L'admission, les
amendements et la liste conversationnelle suivent aussi le contexte du canal.
Les API humaines et les accès ordinaires à Documents par Partage de fichiers suivent
leurs droits propres.

Cette décision remplace le rattachement des accès Tasks à la portée Services de la
[décision 0315](0315-service-management-scope.md). Chaque délégation Task se configure
sur sa propre connexion.
