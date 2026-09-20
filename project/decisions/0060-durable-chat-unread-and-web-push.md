# 0060 — Lecture durable et Web Push pour Chat

- Statut : Accepted
- Date : 2026-08-30

## Contexte

Le compteur historique de Chat comparait un dernier message à un marqueur ambigu et pouvait
assimiler un simple chargement d'historique à un nouveau message. Le frontend marquait en outre
le dernier élément chargé comme lu sans prouver qu'il avait réellement été affiché. Enfin, le
WebSocket ne peut prévenir l'utilisateur que tant que l'application reste ouverte.

## Décision

Messenger attribue à chaque message une position monotone de journal, persiste son auteur
canonique et indique explicitement si l'entrée peut créer du non-lu. Chaque membership conserve
la plus haute position effectivement lue. Le compteur est la différence entre ces deux états,
en excluant les messages de l'identité qui consulte la room.

Le frontend ne fait avancer ce curseur que lorsqu'une bulle est suffisamment visible dans la
conversation au premier plan. L'écoute WebSocket et le badge total appartiennent au shell
authentifié et restent actifs quelle que soit la page affichée.

Les notifications hors application utilisent Web Push. Chaque abonnement de navigateur est
chiffré au repos et lié à l'utilisateur courant. Un signal Messenger crée des livraisons
durables et idempotentes, avec un court délai de grâce. Au moment d'envoyer, le worker backend
revérifie le curseur, l'auteur, le mute et la préférence d'aperçu ; si le message a entre-temps
été affiché, la livraison est annulée. Le service worker PWA affiche le message même lorsque
l'application est arrêtée et ouvre directement la room concernée.

## Conséquences

- Un import passif d'historique ne fabrique plus de nouveaux non-lus.
- Une room ouverte dans un onglet masqué ou dans un panneau non visible ne devient pas lue.
- Les appareils reçoivent les notifications après autorisation explicite, sous réserve que
  l'instance dispose de clés VAPID et soit servie dans un contexte sécurisé.
- Le cutover DbAdmin considère l'historique antérieur comme déjà lu afin d'éviter une tempête de
  compteurs et de notifications au déploiement.
- Les abonnements invalides sont désactivés et les erreurs transitoires sont reprises avec
  backoff par une file durable.
