# 0183 — Révocation durable et nettoyage des flux audio

Statut : accepté. Date : 2026-10-14.

## Garantie

Raccrocher ou supprimer un tour audio doit révoquer son exécution même lorsque le
transport appartient à un autre worker. Une réponse tardive ne doit pas restaurer un
tour interrompu. La suppression attend la fin du nettoyage ; un acquittement local
ne suffit pas à prouver la fermeture de tous les propriétaires.

## Décision

`app.voice` possède la révocation durable des sessions et les demandes de suppression.
Les mutations prennent les verrous dans l'ordre session puis tours et commitent la
révocation avant d'annuler les propriétaires. Les moteurs classique et temps réel
surveillent l'état persistant et cessent leur activité lorsque la session est fermée
ou que la vérification de son autorité échoue.

Chaque propriétaire garde un verrou consultatif PostgreSQL partagé sur une connexion
distincte jusqu'au retour des finaliseurs moteur et transport. Une sonde exclusive
vérifie l'absence de propriétaires sur tous les workers. Une erreur de fermeture
persistée empêche l'acquittement, même lorsqu'elle arrive pendant l'annulation.

Le raccrochage forcé conserve l'historique et les travaux métier liés. Les tours actifs
deviennent `INTERRUPTED` ; les leases, checkpoints et autorisations sont révoqués.
Une session terminale garde son statut et ses dates. La suppression utilise une demande
idempotente dans `voice_turn_deletions` dont la clé `id` conserve l'identité du tour
après sa disparition. Le service périodique la reprend toutes les deux secondes.
La suppression effective passe par l'opération publique `app.conversation.delete_round`.

HTTP 202 signifie que le nettoyage reste en attente. Son état et sa dernière erreur
sont consultables ; le frontend conserve le contenu et suit la demande, y compris
après une panne temporaire ou une réouverture. Les réponses tardives sont ignorées
après un changement de tour. Les routes vérifient les privilèges Task et la portée de
gestion de l'agent ; aucun lien ni identifiant de tour ne donne accès à un autre agent.

## Vérification et limites

Les suites Voice couvrent propriétaires coopératifs et non coopératifs, verrou détenu
sur une connexion PostgreSQL distincte, concurrence de finalisation, reprise de
suppression sans registre local, erreurs de transport et refus des écritures tardives.
Les tests HTTP utilisent les véritables sessions, privilèges et scopes. Les parcours
de composants exercent confirmation, permissions, attente, réessai et navigation.

Le défaut de lecture d'une erreur tardive venait de l'objet session déjà chargé avant
l'annulation. Une relecture après fermeture et un scénario avec transaction indépendante
protègent cette garantie. Les contrôles antérieurs ne couvraient qu'une erreur déjà
présente avant l'action.

Ces tests ne remplacent pas un appel réel réparti entre deux processus avec redémarrage.
Les effets externes envoyés avant révocation ne sont pas annulés rétroactivement.
La table de demandes et `voice_sessions.teardown_error` sont convergés par DbAdmin,
avec `make sync-db` en développement et `make update` lors d'un déploiement autorisé.
