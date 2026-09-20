# ADR 0030 — La room Messenger est l'unique portée conversationnelle

- Statut : Accepted
- Date : 2026-08-09
- Remplace partiellement : ADR 0022 pour la persistance des mailboxes et entrées

## Contexte

Le control plane conversationnel a introduit `conversation_mailboxes` pour identifier une portée
agent, connexion, room et participant, puis `conversation_inputs` pour recopier la séquence,
l'identifiant distant et un payload de chaque message. Depuis la normalisation de Messenger,
`messenger_rooms` porte déjà la connexion et l'identifiant distant, tandis que
`messenger_messages` porte l'auteur, le contenu, la date et la room interne.

Ces tables Conversation dupliquent donc l'identité et le contenu possédés par Messenger.

## Décision

`messenger_rooms` est l'unique identité durable d'une room textuelle ou audio. Chaque
`ConversationRound` la référence directement. `conversation_round_messages` ordonne les messages
d'entrée et de sortie et porte, pour une entrée, la date à laquelle le round l'a définitivement
consommée.

Le scheduler déduit les rooms prêtes depuis les messages entrants sans lien consommé. Les états,
leases, tentatives et effets restent propres au round. Agent, connexion, plateforme, participant,
texte, auteur et date sont joints depuis Messenger et ne sont pas recopiés dans Conversation.

La migration a été additive avant d'être destructive : les FK canoniques et la consommation ont
d'abord été écrites et backfillées, puis observées en production. Après bascule du scheduler, des
lectures et des notifications, Atlas a supprimé `conversation_mailboxes`, `conversation_inputs`,
`conversation_events` et les colonnes de snapshots devenues redondantes.

## Conséquences

- Conversation ne possède plus une seconde représentation d'une room ou d'un message.
- Un round supersédé peut référencer une entrée sans la consommer ; un successeur peut donc la
  reprendre sans copier son payload.
- Les notifications sortantes deviennent des messages Messenger ordinaires et suivent leur
  mécanisme de livraison canonique.
- La contraction est interdite tant que le backfill de production ne prouve pas que toutes les
  relations canoniques sont résolues.
- Deux index partiels garantissent au plus un round `FROZEN` et au plus un round en traitement
  (`CLAIMED` ou `RUNNING`) par room, ce qui préserve la supersession sans autoriser deux exécutions.

## Preuves dans le code

`back/app/conversation/models.py`, `back/app/conversation/service.py`,
`back/app/conversation/upgrade.py`, `back/app/voice/conversation_service.py` et les contributions
désormais enregistrées dans `core.dbadmin`.
