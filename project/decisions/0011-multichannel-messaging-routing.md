# ADR 0011 — Routage et recherche multi-messageries

- Statut : Superseded partiellement par ADR 0028 pour la persistance des résultats d'annuaire
- Date : 2026-07-22
- Révisé : 2026-07-29

## Contexte

Un agent Galaris peut être joignable simultanément par Nextcloud Talk, Matrix, Telegram, WhatsApp
et OneBot. Une sélection globale de provider rendait ces bridges mutuellement exclusifs. Une room
ou un identifiant utilisateur seul ne suffit pas non plus à identifier une conversation : deux
connexions peuvent employer la même valeur distante.

La demande métier porte sur deux propriétés : conserver exactement l'origine d'une conversation et
rechercher un utilisateur dans tous les annuaires de messagerie disponibles. Elle ne porte pas sur
un carnet d'adresses, le rapprochement d'identités ou une préférence de canal. Depuis la révision
du 29 juillet, l'observation d'un expéditeur humain alimente néanmoins une projection sociale
minimale et privée dans Memory.

## Décision

Chaque Tool peut activer la capacité Messenger et sélectionner explicitement un bridge. Cette
capacité aliasse la famille de fonctions MCP canonique `messenger`; le code du Tool reste une
identité administrative libre. Toutes les connexions actives peuvent écouter simultanément.
`MESSENGER_DRIVER` ne sert plus qu’au backfill de l’ancien Tool générique.

Le Tool porte les paramètres serveur invariants et un mapping vers les paramètres propres à chaque
connexion d’agent. File Share et Messenger possèdent deux configurations indépendantes, même
lorsqu’ils choisissent tous deux `bridge.nextcloud`.

`MESSENGER_ENABLED_CHANNELS` contrôle la disponibilité administrative des kinds sans supprimer
leurs secrets, connexions ou historiques. Un kind désactivé disparaît de la résolution, de la
recherche, des aliases MCP et des listeners texte/voix, mais reste configurable dans les
préférences.

Une conversation est adressée par l'UUID de sa `Room`. Cette ligne persistée porte la
connexion exacte et l'identifiant distant opaque ; le kind concret se déduit du Tool de la
connexion. La Task conserve cette origine durable pour les enfants de plan, Goals, interactions,
attentes de collaboration, drivers, garde anti-double-réponse et sessions Hermès.

Hermès sépare la clé logique de conversation de l'identifiant opaque du transcript. La clé inclut
un condensat stable de l'agent et de la route Messenger persistée ; les rotations de transcript sont
persistées par compare-and-swap afin qu'une reprise ancienne n'écrase pas un pointeur plus récent.

Une room demeure opaque pour le cœur mais peut être namespacée par son bridge. OneBot emploie
`group:<id>` et `direct:<id>` afin qu'un groupe et un utilisateur portant la même valeur distante
ne partagent ni conversation ni session.

La recherche d'utilisateurs parcourt toutes les connexions actives et disponibles de l'agent dont
le `BridgeSpec` expose `SEARCH_USERS`. Elle interroge chaque annuaire natif, déduplique uniquement
une même paire `(connection_id, remote_user_id)` et conserve `user_id`, `messaging_id`, `tool_id` et
la plateforme dans chaque résultat. Dans cette API historique, `messaging_id` désigne la connexion
technique exacte. Les résultats sont éphémères : la recherche seule ne crée aucune fiche, aucun
rapprochement d'identités et aucune préférence de canal. Un protocole sans annuaire
interrogeable ne contribue pas de résultat ; un éventuel cache technique devra faire l'objet d'un
contrat séparé.

Indépendamment de ce sélecteur de route, l'adresse d'une fiche sociale Memory utilise
`messaging_id` pour le code canonique du bridge et `user_id` pour l'identifiant natif exact. Cette
projection est créée seulement après un message entrant humain. Elle exclut connexion, room et
contenu, reste privée à l'agent destinataire et ne permet aucun envoi sans résolution séparée d'une
route.

Pour un envoi sortant, la connexion exacte de la Task est prioritaire. Hors conversation ou lors
d'un changement volontaire de plateforme, l'appelant fournit explicitement le canal choisi. Une
connexion absente, ambiguë, inactive ou dépourvue de capacité échoue sans repli cross-canal. Il
n'existe ni ordre global de préférence, ni sélection depuis le dernier échange.

## Conséquences

- Les cinq bridges peuvent fonctionner en parallèle pour un même agent.
- Une panne d'un listener ne déplace pas une réponse et n'arrête pas les autres canaux.
- Deux résultats portant le même nom ou le même identifiant distant ne sont jamais fusionnés entre
  connexions.
- Galaris n'expose ni API CRUD, ni écran, ni table de contacts ; la fiche sociale est un
  `MemoryItem` source-managed.
- Les anciens Tools de bridge reçoivent une capacité explicite en place, sans renommage, fusion ni
  changement de leurs connexions.
- Une Task historique n'est backfillée que depuis une preuve de connexion non ambiguë ; sinon elle
  reste non routable.

## Preuves dans le code

`back/app/messenger/service.py`, `contact_memory.py`, `mcp.py`, `facade.py`, `session.py`,
`back/app/task/models.py`, `back/app/task/collab.py`, `back/app/agent/contracts.py`, les
providers/listeners Talk et Matrix, les déclarations `back/bridge/*/__init__.py` et les tests de
routage et de session sous `back/app/messenger/tests/`.
