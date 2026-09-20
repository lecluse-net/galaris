# 0068 — Coûts historiques stables du dashboard

Statut : Accepted

Date : 2026-09-05

## Décision

Le coût facturé affiché par le dashboard est la somme des `LLMCall.cost` enregistrés
lors des appels. Le coût API comparable reste la somme des `LLMCall.inference_cost`.
Changer aujourd'hui le statut d'abonnement d'un modèle ne recalcule pas les mois passés.

Cette décision remplace l'ancienne règle de présentation qui appliquait l'abonnement
courant à l'ensemble de l'historique. Les traces ne sont pas modifiées. Les totaux,
comparaisons mensuelles, ventilations par agent et séries journalières suivent tous
la même règle. Les anciens chiffres du dashboard peuvent donc changer une fois lors
de l'adoption de ce contrat, pour refléter les montants déjà conservés dans les traces.
