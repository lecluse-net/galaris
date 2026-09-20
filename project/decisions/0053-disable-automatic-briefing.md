# ADR 0053 — Désactivation du Briefing automatique

- Statut : Accepted
- Date : 2026-08-26

## Contexte

L’ADR 0051 construit désormais, avant le dispatch, un objectif durable autonome qui conserve les
exigences, contraintes, livrables, destinataires et références de la conversation source. Le
Briefing du harnais interne reformule ensuite cet objectif pour une exécution `high`, recommande
une approche et présélectionne des outils ou Process.

Cette seconde interprétation ajoute un appel LLM et peut concurrencer l’objectif durable alors que
le harnais sait déjà découvrir les outils non présélectionnés par chargement différé. Le pipeline
tolère déjà l’absence ou l’échec du Briefing, et les drivers externes fonctionnent sans lui.

## Décision

La politique statique du driver `internal` conserve le Planner mais fixe `use_briefing=False` et
une liste `briefing_efforts` vide. Aucun driver actif ne route donc une nouvelle Task, y compris
une feuille planifiée en effort `high`, vers la phase `BRIEFING`.

Le mécanisme n’est pas supprimé. Ses contrats, son service, sa phase durable, ses résultats
historiques, leur affichage et les benchmarks isolés du Lab restent disponibles. Une Task
historique déjà en phase `BRIEFING` peut encore être reprise par le scheduler, mais aucun ancien
résultat n’est injecté dans un run dont la politique courante interdit le Briefing.

La directive `@briefing` n’est plus publiée dans le catalogue du Chat et toute admission explicite
qui la demande est refusée par la politique. Le parseur et le contrat d’admission restent présents
pour conserver une réactivation locale et une suppression ultérieure simples.

## Conséquences

- Les exécutions `high` du harnais interne partent directement de l’objectif autonome, du Working
  Set, du contexte gouverné et du catalogue d’outils différé.
- Une Task évite l’appel LLM, le coût et la latence du Briefing automatique.
- Les traces historiques et le Lab permettent encore de comparer les exécutions passées et de
  décider ultérieurement entre réactivation et suppression.
- L’ensemble d’états durable ne change pas pendant cette période d’observation.

## Preuves dans le code

`back/app/agent/registry.py`, `back/app/agent/workflow.py`,
`back/app/conversation/directives.py`, `back/app/conversation/mcp.py` et leurs tests.
