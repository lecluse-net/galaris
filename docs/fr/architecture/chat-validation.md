<p align="right"><strong>Français</strong> · <a href="../../en/architecture/chat-validation.md">English</a></p>

# Validation de Chat

Statut : `accepted-and-implemented`

Date : 21 août 2026

Cette validation décrit le contrat livré ; elle remplace le plan d’implémentation désormais retiré.

Ce dossier constitue les validations A et B exigées par le plan. Les contrats, modèles et tests
liés restent la source de vérité lorsque ce document devient ancien.

## Validation A — modules, façades et sécurité

`app.chat` possède l’API utilisateur, le stockage privé, le provider natif, les
assertions, les événements autorisés par room et l’adaptation WebRTC. Il dépend uniquement des
surfaces publiques de `app.messenger`, `app.conversation` et `app.voice`. Le domaine canonique
`app.messenger` possède les lectures et mutations ORM et retourne les DTO `NativeMessenger*` ;
aucun autre domaine n’importe le nouveau module.

```text
front/app/chat
  -> API /chat + room WebSocket autorisée
  -> app.chat
       -> app.messenger (journal, rooms directes, identités, fichiers)
       -> app.conversation (activité expurgée et arbre transitif des Tasks liées)
       -> app.voice (CallTransport navigateur)
```

Le bootstrap déclare les modules dans `back/modules.py` et `front/modules.ts`, importe le provider
avant la résolution Messenger, enregistre la politique WebSocket et planifie la réconciliation du
stockage. Le Tool intégré `chat` n’expose aucun outil MCP, auto-connecte chaque agent actif et
ne réactive jamais une connexion désactivée lors d’une synchronisation ultérieure.

Chaque route est protégée par un privilège global. Les routes portant un UUID de room ajoutent
`ChatRoomAccessAssertion`; les mutations internes gardent `InternalRoomAccessAssertion`. L’identité
humaine vient de la session et de la correspondance exacte `messenger_users.galaris_user_id` pour
chaque Tool externe. La fusion des
paramètres d’autorisation applique les paramètres de path en dernier, de sorte qu’un body ou une
query ne peut masquer `room_id` ou `file_id`. Les services revérifient le membership sous verrou
avant les mutations.

| Surface | Privilège | Politique de ressource |
|---|---|---|
| statut, identités, rooms et historique | `CHAT_ACCESS` | collection filtrée SQL par identité liée ou membership exact |
| publication et upload | `CHAT_SEND` | membership exact, agent encore actif |
| ouverture d'une conversation 1-to-1 | `CHAT_MANAGE` | agent actif, utilisateur issu de la session |
| appel et raccrochage | `CHAT_CALL` | membership, connexion et appel corrélés |
| téléchargement | `CHAT_ACCESS` | room + message porteur + fichier |
| arbre des tâches liées | `TASK_ACCESS` ou `TASK_EDIT` | membership exact de la room |
| perspective d’un agent IA | `CHAT_IMPERSONATE` | l’agent sélectionné est membre exact de chaque room |

Les refus absent/inaccessible retournent le même `404`. Les émissions WebSocket ne ciblent pas un
nom de room partagé aveuglément : avant chaque émission, `core.websocket` revérifie privilège et
membership pour chaque socket. L’événement n’est qu’un signal ; le store rattrape l’état durable
par HTTP et purge son contenu sur déconnexion ou refus d’accès.

Le flux texte est idempotent par `(connection_id, client_message_id, direction)`. Il persiste
d’abord le message canonique puis admet un `ConversationRound`. Pour `platform=internal`, le contrat
de conversation conserve le round foreground sans Task propre, mais expose la même admission de
Task durable que Nextcloud Talk. Une directive Task ou une demande classée comme travail long crée
une Task liée avant confirmation ; le contrôleur garde aussi les outils Process disponibles. La
projection d’activité expose une trace bornée et nettoyée, et l’arbre des Tasks liées est chargé
séparément sous privilège Task ; aucun prompt système ni secret ne franchit ces surfaces.

Le flux fichier écrit par morceaux dans `.staging`, vérifie limite, capacité, MIME déclaré,
extension et signatures actives, fait un déplacement atomique, puis journalise le fichier avec le
même UUID que le blob. Le réconciliateur supprime les staging anciens et les blobs orphelins après
une période de grâce. L’URI canonique est `chat://<room-locator>/<file-uuid>` et ne contient
jamais un chemin hôte.

Le flux voix crée un `BrowserCallTransport` WebRTC puis appelle la façade publique `app.voice`.
Cette façade crée une session d'appel dans la room Chat courante et des rounds vocaux indépendants
des Task. Les appels successifs partagent donc la chronologie sans partager leur cycle de vie. La
conférence et le SFU restent hors périmètre, conformément au plan.

Réserves acceptées : le registre des appels actifs est local au processus backend ; un déploiement
multi-réplicas doit employer de l’affinité de session ou faire évoluer ce registre avant mise à
l’échelle horizontale. Aucune réserve ne bloque la livraison mono-backend de référence.

## Validation B — mapping des données existantes

Aucune table n’est ajoutée et aucun contenu visible n’est dupliqué. La colonne nullable
`messenger_users.galaris_user_id` relie une identité distante à un compte Galaris ; l’unicité
`(tool_id, galaris_user_id)` garantit une seule identité courante par Tool et par compte.

| Table | Colonnes et invariants utilisés | Accès critique |
|---|---|---|
| `tools` | `code='chat'`, `messenger_config.service='internal'` | unicité de `code` |
| `connections` | `tool_id`, `agent_id`, `active` | unicité `(tool_id, agent_id)`, connexion revérifiée avant admission/appel |
| `messenger_rooms` | UUID, connexion, external ID, label, kind direct, type, timestamps | unicité `(connection_id, external_id)`, un couple utilisateur-agent |
| `messenger_users` | Tool, external ID, `agent_id`, `galaris_user_id`, `is_ai` | unicités `(tool_id, external_id)` et `(tool_id, galaris_user_id)` |
| `messenger_room_users` | room/user, `role`, `joined_at`, `muted`, `last_read_message_id` | exactement le propriétaire humain et l'agent pour l'IHM interne |
| `messenger_messages` | room, expéditeur, direction, external ID, réponse, statut, dates | idempotence canonique et pagination `(created_at,id)` |
| `messenger_files` / `messenger_attachments` | UUID, connexion, nom non fiable, MIME, taille, ordre | fichier accessible seulement via un message de la room |
| `conversation_rounds` et liens | room, messages, statut, trace expurgée | activité filtrée après membership HTTP |
| `voice_sessions` | room conversationnelle et cycle de vie propre à chaque appel | accès par la room et l’appel corrélé |
| `chat_emoji_usages` | utilisateur, émoji, compteur et dernière utilisation | unicité `(user_id, emoji)`, suppression en cascade avec le compte |

Les extensions de schéma historiques sur `messenger_room_users` restent inchangées : `role` identifie le propriétaire
humain de la room directe, `joined_at` conserve l'audit, `muted` porte la préférence personnelle et
`last_read_message_id` fournit un curseur non-lu stable. Chaque suffixe `_id` est une vraie FK et la
suppression du message lu remet le curseur à `NULL`.

L’écran « Mon profil » permet de définir ou retirer la correspondance pour chaque Tool externe.
Chat n’affiche ensuite que les rooms dont cette identité est membre. Les rooms externes sont
consultables, paginées par lots de 100 messages au scroll et strictement en lecture seule. Le badge
de source distingue notamment Nextcloud Talk et Telegram. Les rooms techniques Mail sont exclues
de cette projection : les courriels entrants restent journalisés et admis comme Tasks sans créer
une discussion visible par message. Le privilège `CHAT_IMPERSONATE` expose un sélecteur séparé
pour consulter la même projection depuis l’identité canonique d’un agent IA.

Le sélecteur d’émojis maintient pour chaque compte un classement privé et atomique par fréquence,
puis récence. Ses 25 premières valeurs forment la catégorie mise en avant « Fréquemment utilisés » ;
ce classement ne dépend ni de la room courante ni du navigateur employé.

L'API n'expose ni ajout, ni retrait, ni départ de participant. Les éventuelles rooms de groupe
historiques restent en base mais sont exclues des collections et assertions de l'IHM interne. Les
messages ne sont ni éditables ni supprimables dans cette version. Les blobs vivent sous
`/data/chat/attachments/<préfixe>/<uuid-hex>` et leur durée de vie suit leur ligne
canonique.

PostgreSQL et `/data/chat` forment un seul jeu de sauvegarde cohérent. La procédure
opérateur impose une fenêtre sans écriture, le dump de la base et la copie du volume dans le même
point de restauration. Après restauration, le réconciliateur peut enlever un blob sans ligne mais
ne peut reconstituer des octets absents : une sauvegarde de la base seule est invalide.
