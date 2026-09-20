# 0067 — Reprise durable des calendriers et des attentes de Process

Statut : Accepted

Date : 2026-09-05

## Décision

Les occurrences de calendrier et l'avancement du curseur sont enregistrés dans une
même transaction, sous verrou du calendrier. Chaque occurrence conserve un snapshot
chiffré de son contenu, de son agent et de son action. Un lease de cinq minutes protège
son dispatch ; une interruption laisse un reçu récupérable après expiration.
Les erreurs restent rejouables et ne bloquent pas les nouveaux reçus du batch suivant.

Le démarrage d'un Process utilise sa clé d'idempotence explicite. Une Task soumise
par la façade agentique peut également porter une `idempotency_key` : l'adaptateur Task
la transforme, dans la portée de l'agent, en UUID stable et sérialise sa création.
Un rejeu après commit rend la même Task, y compris si son reçu de création a été perdu.

Les terminaux Process conservent séparément `await_resolved_at`. La résolution inclut
la clôture de l'enfant et la reprise de son parent. Les callbacks dupliqués, le refresh
explicite et le passage périodique peuvent terminer une résolution interrompue.
Une demande d'annulation reste suivie par polling en état `cancelling`.

La disponibilité exige une lecture complète et actuelle de tous les calendriers
sélectionnés. Une source en erreur produit une erreur explicite « disponibilité
inconnue ». Le cache ne prouve pas une disponibilité. Le plafond d'affichage de 500
événements ne s'applique pas au calcul ; la limite du parseur produit une erreur
explicite au lieu d'une réponse tronquée.

## Limites

Ces garanties s'appliquent aux nouveaux reçus de calendrier contenant leur snapshot.
Les anciens reçus sans snapshot restent conservés mais ne permettent pas de reconstruire
automatiquement un contenu disparu ou de prouver qu'un ancien effet sans reçu n'a pas eu lieu.
Un événement déjà acquitté puis perdu par un transport externe n'est pas recréé.
La fenêtre de découverte après indisponibilité conserve sa borne existante de sept jours.

Le schéma converge par DbAdmin ; aucun worker externe ni broker supplémentaire n'est ajouté.
