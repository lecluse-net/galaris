# ADR 0008 — Processus personnels et administration séparée

- Statut : Accepted
- Date : 2026-07-20

## Contexte

Les fonctions d’exécution des processus appartenaient à un package MCP `process` configurable
par connexion. Un agent pouvait donc ne pas découvrir les workflows qui lui étaient pourtant
affectés. À l’inverse, réutiliser ce package pour administrer les définitions aurait transformé
une capacité personnelle souvent active en accès global aux processus de tous les agents.

La publicité du prompt doit rester utile sans devenir une fuite d’autorisations : un agent voit
ses propres processus, tandis qu’une capacité d’administration explicitement déléguée peut agir
sur les affectations et les runs globaux.

## Décision

Les six fonctions personnelles `process_list`, `process_get`, `process_start`,
`process_list_runs`, `process_get_run` et `process_analyze_run` appartiennent au package socle
`galaris`. Leurs services filtrent ou revalident toujours l’identité `agent_id` portée par le
contexte d’appel. Le catalogue injecté dans le prompt est construit uniquement avec
`list_for_agent` et ne s’élargit jamais du fait d’un droit administratif.

Un package distinct `process_admin` est auto-connecté inactif. Ses fonctions préfixées
`process_admin_*` permettent à un agent explicitement autorisé de découvrir les moteurs, créer,
réaffecter, modifier et supprimer les définitions, puis démarrer, inspecter, rafraîchir, annuler,
relancer, analyser ou supprimer les runs de tous les agents.

La synchronisation remplace les anciennes lignes `processus` / `process` par `process_admin`.
Lorsqu’une ligne historique est promue, toutes ses connexions sont désactivées avant que les
fonctions administratives y soient rattachées. Une activation personnelle historique ne peut
donc pas produire une élévation de privilèges lors de la mise à niveau.

## Conséquences

- Chaque agent découvre ses affectations sans connexion processus supplémentaire.
- Aucun outil personnel n’accepte un `agent_id` cible et aucun prompt ne publie les affectations
  d’un autre agent.
- L’administration globale demande une activation explicite et peut encore être réduite fonction
  par fonction au niveau de la connexion.
- Les démarrages administratifs inter-agents ne peuvent pas référencer le système de fichiers privé de la
  cible ; la préparation de fichiers doit être déléguée à cet agent.
- Le code d’outil `process` disparaît du catalogue intégré ; `app.process` reste le domaine métier
  canonique et les outils moteurs tels que `n8n` restent inchangés.

## Preuves dans le code

`back/app/process/mcp.py`, `back/app/process/process_service.py`,
`back/app/tools/mandatory_tools.py`, les prompts des drivers, le skill système `galaris` et les
tests `back/app/process/tests/test_mcp.py` et `back/app/tools/tests/test_mandatory_tools.py`.
