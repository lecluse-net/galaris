# ADR 0002 — Frontière des drivers agentiques

- Statut : Accepted
- Date : 2026-07-18

## Contexte

Le harnais interne Pydantic AI et Hermès ont des cycles de vie et capacités différents. Les
faire appeler directement par les domaines métier dupliquerait la sélection du modèle, le
planner, le briefing, le streaming et la reprise.

## Décision

`app.agent` possède les contrats et la façade uniques. Les runtimes implémentent
`AgentDriver`. `app.harness` contient Pydantic AI et `bridge.hermes` adapte Hermès.
`app.task` expose sa persistance à travers `AgentTaskPort`; `app.agent` ne dépend pas du modèle
ORM `Task`.

La politique du pipeline et le modèle sont résolus avant le driver. Le stream commun impose
un résultat terminal unique.

## Conséquences

- Un futur driver s’ajoute par contrat, registre, configuration et tests de conformité.
- Une capacité absente est explicite ; aucun fallback silencieux ne masque un driver inconnu.
- Les tests AST empêchent le retour d’imports `app.task` ou `pydantic_ai` dans `app.agent`.
- Le scheduler reste responsable de la durabilité, pas du choix du runtime.

## Preuves dans le code

`app.agent.contracts`, `registry`, `facade`, `task_port`, `app.task.agent_adapter`,
`app.harness.driver` et `bridge.hermes.driver`.
