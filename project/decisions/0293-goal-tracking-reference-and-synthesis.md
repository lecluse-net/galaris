# 0293 — Suivi Goal par référence et synthèse de continuité

Statut : accepté, implémenté.

## Problème et garantie

Recopier le document de suivi dans l'objectif de chaque cycle fait croître les entrées
du dispatcher, du planner et de l'exécuteur avec l'historique du Goal. Une erreur de
génération sans sortie exploitable ne démontre toutefois pas un dépassement du contexte :
le budget de sortie peut être épuisé pendant le raisonnement.

## Décision

Les nouvelles Tasks de cycle conservent la description originale et les consignes métier,
mais référencent le suivi existant par `document://<uuid>`. L'agent lit ce document avec
`file_read` avant de choisir son travail ; il suit les pages nécessaires et respecte les
refus d'accès. La référence n'accorde aucun droit supplémentaire. Aucun document parallèle
n'est créé, aucune donnée existante ni Task déjà matérialisée n'est réécrite.

Le jugement de fin de cycle reste une inférence structurée avec le suivi complet en entrée.
Il remplace le document par une synthèse complète plutôt qu'un journal cumulatif. La consigne
de consolidation fait désormais partie du contrat runtime, y compris lorsque le prompt
système est personnalisé. Elle conserve les chantiers distincts, engagements, décisions,
contraintes, incertitudes, blocages, raisons utiles et références exactes aux preuves.
Il n'y a ni plafond arbitraire, ni troncature, ni garantie déterministe de compression par
le modèle. L'historique des cycles et les révisions documentaires restent disponibles.

La capacité de sortie continue d'être résolue au proxy selon la décision 0139. Ce changement
n'ajoute pas de réglage modèle et ne prétend pas supprimer les limites physiques du fournisseur.

## Vérification et limites

Le parcours DB existant de matérialisation couvre les suivis vide, court et volumineux,
l'absence de leur contenu dans l'objectif, la lecture paginée complète du document canonique
et le refus pour un autre agent. Il conserve les garanties de routage, scope et unicité du cycle.
Les tests de jugement et du parcours de réponse du référent restent applicables. Ils ne
mesurent pas la fidélité d'une synthèse produite par un modèle réel.

Le prompt par défaut demandait déjà une synthèse ; le contrat runtime explicite cette règle
pour les prompts personnalisés aussi. La couverture antérieure attendait au contraire la
présence du contenu dans l'objectif : cette attente est remplacée par la continuité via le
document. Un suivi trop volumineux pour le jugement reste une limite à diagnostiquer ; cette
décision n'introduit pas de moteur séparé de compression par morceaux.
