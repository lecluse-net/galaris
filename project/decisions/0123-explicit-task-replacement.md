# 0123 — Remplacement explicite après preuve d'arrêt

- Statut : Accepted
- Date : 2026-09-19

## Contexte

Un arrêt logique de Task ne prouve pas la fin de son worker ou de son exécution distante.
Une création indépendante doit rester possible pendant un autre travail, tandis qu'un
remplacement explicitement demandé doit attendre son prédécesseur. Un amendement refusé
ne constitue pas une demande de remplacement.

## Décision

Les soumissions conversationnelles texte et voix acceptent `REPLACE`, avec cible et révision.
`app.task` verrouille la racine, vérifie sa portée et enregistre atomiquement l'arrêt canonique
et le successeur suspendu. La relation utilise `source_task_id`, déjà présent ; les métadonnées
`_replacement` et `_replacement_successor` portent l'état et l'identité idempotente. Aucun
nouveau statut SQL, schéma ou moteur de tâches n'est introduit.

Le scheduler refuse toute prise de lease tant que le remplacement n'est pas confirmé,
même si une commande retire les pauses. Son job périodique réconcilie les demandes persistées,
sans maintenir de verrou pendant un appel au driver. Il exige la libération du lease et une
preuve correspondant à l'exécution capturée : tâche déjà réussie ou jamais démarrée,
nettoyage local achevé avec capacité `local_interrupt`, résultat terminal validé du driver,
ou reçu d'annulation confirmé. Un événement d'erreur synthétique, une expiration de lease
ou un reçu `requested`/`unknown` ne suffit pas. Les drivers à accusé typé peuvent faire
évoluer une demande d'annulation de `requested` vers `confirmed`.

Le nettoyage réel du worker persiste sa preuve dans `TaskAttempt`, après avoir attendu ses
opérations possédées. Une commande concurrente tenant le verrou ne doit pas faire perdre
cette preuve. Les résultats terminaux validés sont distingués des erreurs de transport
par une propriété persistée de l'événement agentique.

La confirmation retire seulement la pause `replacement`. Les pauses utilisateur et les
travaux indépendants sont préservés. Une relance, un changement de portée ou une nouvelle
identité d'exécution du prédécesseur met le remplacement en conflit sans arrêter ce nouveau
travail. L'état opérationnel expose le prédécesseur et l'état du remplacement.

## Limites assumées et qualification

Ce premier contrat concerne les racines sans enfant actif, Goal ni attente externe en cours.
La vérification traverse tous les descendants, y compris derrière un parent terminal, et
considère un lease résiduel comme du travail encore possédé. Les domaines externes fournissent
leurs identifiants de Tasks bloquées par un port de composition `register_replacement_blocker`.
`app.process` y inclut ses lanceurs et Tasks d'attente tant que le Process n'est pas terminal
ou que `remote_may_continue` est vrai, même après suppression logique. Le bootstrap enregistre
ce port avant les schedulers ; `app.task` ne dépend donc pas de `app.process`.
Cette barrière est relue à l'admission et avant libération du successeur. Les autres arbres et
les Processes terminés sans incertitude ne sont pas bloquants. Elle ne demande pas d'annulation
à leur place : l'orchestration d'un remplacement coordonné doit passer par leurs propriétaires.
Une coordination déjà présente entraîne un refus avant arrêt ; une coordination apparue
pendant l'arrêt empêche la libération du successeur. Le remplacement coordonné d'un arbre
ou d'un Process reste à concevoir. Les anciens runs dépourvus de preuve durable restent
en attente ; aucune déduction d'arrêt physique n'est faite à partir de leur seul état logique.

Les tests PostgreSQL couvrent admission texte/voix, rejeu, reprise entre sessions, nettoyage
retardé, reçus distants, pauses, changements de contexte et garde du scheduler. Ils ne
qualifient pas l'arrêt d'un véritable runtime externe. Les prompts d'exécution et de
préparation ne changent pas ; seules les descriptions des outils suivent le contrat général.

Voir `back/app/task/replacement.py`, `back/app/task/tests/test_replacement.py`,
`back/app/conversation/tests/test_service.py` et la décision 0100.
