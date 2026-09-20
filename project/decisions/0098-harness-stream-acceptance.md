# ADR 0098 — Acceptation terminale des flux de harnais

- Statut : Accepted
- Date : 2026-09-14

## Contexte

La façade rejetait les événements après un résultat mais avait déjà publié ce résultat
comme terminal. Une erreur de protocole pouvait ainsi contredire un succès visible.
Les capacités d’annulation pouvaient aussi annoncer une méthode sans effet.

## Décision

Une validation commune possède le flux concret. Elle transmet immédiatement les
messages valides et retient le résultat jusqu’à une fin de flux normale et au nettoyage.
Une fin sans résultat, un payload ambigu, un événement tardif, une exception ou un
blocage après résultat provoquent un échec avant publication du résultat candidat.
Le délai de fermeture est commun à tous les drivers et déclaré dans `AgentDriverSpec`.
Il suppose une annulation asyncio coopérative.

Une capacité `cancellation` signifie que `cancel(run_id)` est implémenté par le driver.
Une interruption locale asyncio n’est pas un acquittement d’arrêt distant. Le driver
Chat Completions ne déclare pas d’annulation distante en l’absence d’un tel protocole.

Le kit de conformité réutilise cette validation. Un harnais scriptable dédié aux tests
injecte fautes, événements et barrières sans être enregistré au démarrage applicatif.

## Conséquences

Le résultat final peut être retardé du temps de fermeture, tandis que le streaming des
messages conserve sa latence. Une fermeture invalide peut faire échouer un run dont un
effet a déjà eu lieu : les garanties de réconciliation et de non-rejeu restent nécessaires.
Les checkpoints opaques et la négociation unifiée des capacités font l’objet des
recommandations de l’[audit](../audits/2026-09-14-harness-api.md).
