<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/messaging.md">English</a></p>

# Flux de messagerie

`app.messenger` est le langage commun de Galaris. Les bridges possèdent le protocole externe,
pas le workflow métier.

Galaris expose le provider natif dans `app.chat`, identifié par le Tool intégré `chat`. Il
réutilise le journal et les rooms canoniques, sans listener réseau ni secret. L’application
utilisateur `/chat` est aussi la vue unifiée en lecture seule des rooms issues des bridges
externes. L’ancien `EmployeeMessenger` en boucle
locale et son Tool `galaris_messenger` restent retirés.

Le chat peut intégrer le composant documentaire complet dans sa page, à côté de la
conversation ou au-dessous, avec les mêmes droits et sauvegardes que dans sa modale.
Lors de l'envoi, le client attend les sauvegardes puis transmet `displayed_document_id`
uniquement si le document a effectivement chargé et reste affiché. Messenger conserve sa
référence `document://<uuid>` dans les métadonnées de ce message, sans changer son texte.
La construction du tour ajoute cette indication au prompt à partir du seul message entrant
le plus récent ; elle ne reprend jamais l'affichage d'un message ancien comme état courant.
Fermer le document ou perdre son accès supprime cette indication des envois suivants.
L'outil `document_show(document=...)`, rattaché au Tool Conversation (`conversation`), demande l'ouverture dans ce même
panneau (ou la visionneuse mobile). Il accepte un UUID, une URI `document://` ou une URL
Galaris `/memory/documents?document_id=...`. Son exposition exige une connexion Conversation active,
Conversation autorisé en conversation et un round textuel dans une room interne appartenant à l'agent.
Le catalogue et le prompt partagent ce filtre ; l'appel revérifie les autorisations, l'accès au
document et la fraîcheur du round. L'événement `chat.document_show` ne contient que la room et
l'identifiant du document, ne modifie aucun partage et ne vaut pas accusé de lecture. Le client
ignore les autres rooms et préserve les sauvegardes avant ouverture ; les droits du lecteur
restent contrôlés par l'API documentaire. L'action est implémentée dans `app.conversation.mcp`
avec `task_enabled=False` : aucune Task, même issue du chat, ni la voix n'expose cet outil.
Memory fournit le contrôle d'accès au document via son adaptateur enregistré au démarrage ;
sa connexion n'est pas requise. Le Tool Conversation et ses connexions sont initialisés actifs
par les datasets intégrés, puis leur activation reste administrable.
Ce contexte descriptif ne doit pas déclencher le renvoi automatique d'une pièce jointe ;
une demande d'édition reste soumise au contrôleur conversationnel.

Chaque action « nouvelle conversation » crée une room interne distincte, y compris lorsque
l'utilisateur choisit un agent avec lequel il possède déjà un fil. Le libellé reprend le nom de
l'agent, puis ajoute `(2)`, `(3)`, etc. sous le verrou de sa connexion afin que deux créations
concurrentes ne reçoivent pas le même nom.

Pour une room interne autorisée, le scheduler publie en WebSocket un événement `started` avant
l'appel du contrôleur, puis une projection ordonnée des `AIMessage` et enfin `finished`. Le texte
visible est regroupé en petits lots afin d'alimenter une bulle temporaire sans créer un message
canonique par delta. Les types de trace et les appels d'outils sont affichés dans cette bulle. Les
événements WebSocket d'outil contiennent leur nom, contenu, succès, durée, coût et données
structurées bornées. Le bloc technique `thinking` transporte lui aussi le contenu de réflexion
fourni par le runtime. Cette projection est limitée à la room autorisée et retire les clés
sensibles ainsi que les formes usuelles de credentials avant émission ; prompts système et secrets
ne la franchissent jamais. La réponse confirmée reste le seul message Messenger durable. Une
projection HTTP rattachée au message de sortie permet ensuite de déplier dans sa bulle le même
AIResult nettoyé (réflexions, outils, paramètres et résultats bornés, réponse finale, durée, coût
et erreur). Le prompt système reste absent. Le signal `chat.message` de cette réponse n'est publié
qu'après le commit du lien entre le round et le message. Jusqu'à ce commit, un marqueur de journal
empêche aussi les lectures HTTP concurrentes d'exposer ce message. Le frontend conserve
l'`AIResult` live jusqu'à ce que cette projection durable complète soit rendue, puis effectue un
remplacement atomique : les deux représentations ne sont jamais affichées ensemble et aucune trame
vide ne les sépare.

À l’ingestion d’un message humain, Messenger fige aussi le `requester_user_id` issu de
`MessengerUser.galaris_user_id`. Les rounds et Tasks admis propagent cet instantané. Un abonnement
ChatGPT personnel n’est utilisable que lorsque cet identifiant correspond à son titulaire ; une
identité non associée dans « Mon profil » reste refusée, y compris en mode mono-utilisateur. Une
modification ultérieure de l’annuaire ne change pas l’autorité des messages historiques.
L’événement `chat.message` porte `is_new=true` pour une nouvelle entrée durable et `is_new=false`
pour une simple mise à jour, telle qu’une correction de Topic. L’interface ne joue son carillon
que pour un nouveau message qui n’est ni personnel, ni rattaché à une room muette, ni observé en
mode impersonation.

Le non-lu est un état Messenger durable et ordonné. Chaque entrée du journal porte une position
monotone, son auteur canonique et un indicateur distinguant les événements live des imports
passifs d'historique. Le membership de l'utilisateur conserve la plus haute position réellement
vue. L'interface ne fait avancer ce curseur que pour une bulle intersectant suffisamment la zone
de conversation lorsque la page, la fenêtre et le panneau mobile sont visibles. Le total global
est réconcilié par HTTP et projeté dans la navigation ainsi que dans le badge de l'application.

L'écoute des nouveaux messages appartient au shell authentifié et reste donc active hors de la
page Chat. Sans abonnement Push actif, elle produit une notification Quasar de repli après avoir
revérifié que le message est toujours non lu, non personnel et non muet. Avec Web Push, le backend
crée une livraison durable par abonnement et par message. Après un court délai de grâce, il
revérifie ces mêmes conditions : une bulle affichée entre-temps ou un onglet connecté qui rend
encore cette room annule la livraison. La page publie cette présence visible séparément de son
simple abonnement aux événements et la retire lorsqu'elle est masquée, lorsque le panneau mobile
des détails remplace la conversation ou lorsqu'elle est démontée. Les endpoints et clés des
abonnements sont chiffrés au repos ; les réponses 404/410 désactivent l'appareil et les erreurs
transitoires sont reprises avec backoff. Le service worker PWA reçoit ensuite le push même
application arrêtée, affiche une notification système respectant la préférence d'aperçu et ouvre
`/chat?room=<uuid>` au clic. Ce chemin exige HTTPS, une autorisation explicite du navigateur et des
clés VAPID configurées sur l'instance.
Lorsqu’un auteur agent possède une voix TTS active, chacune de ses bulles textuelles expose aussi
une action de lecture à côté de « Répondre ». Une bulle humaine n’expose jamais cette action.
Les capacités sont résolues depuis les `agent_id` des auteurs effectivement référencés par les
messages canoniques, jamais depuis la projection courante des membres de la room. L’API vérifie
l’accès exact à la room et au message, refuse également tout auteur qui n’est pas un agent Galaris
lié, prépare le texte avec le même nettoyage que le pipeline Voice, puis diffuse le MP3 synthétisé
avec la voix de l’auteur sans le persister dans le journal Messenger.
L'HTTP fournit aussi le rattrapage des états de round après une reconnexion.
Le volet droit du Messenger projette uniquement les Tasks directement liées aux rounds de la
room, puis tous leurs descendants transitifs. La projection récursive suit la hiérarchie
`parent_id` et la causalité `source_task_id` : une délégation à un autre agent reste donc visible,
ainsi que toute sa descendance, sans limite de profondeur et sans filtre d'agent. L'endpoint
`/chat/rooms/{room_id}/tasks` exige à la fois l'accès exact à la room et un privilège
Task ordinaire. Le volet consomme les événements WebSocket canoniques
`task.create/update/delete/restore/cleanup`, puis réconcilie l'arbre par HTTP après chaque lot
d'événements et chaque reconnexion. La fiche `TaskDetail` s'ouvre dans une modale locale au
Messenger afin de ne pas quitter la conversation. Aucun état de suivi propre au Messenger n'est
persisté. L'API renvoie les Tasks des plus récentes aux plus anciennes par pages de dix ; le volet
charge la première tranche, puis ajoute dix Tasks antérieures lorsque le scroll atteint le haut.

Cette projection suit la fenêtre de messages effectivement chargée par l'interface : le client
transmet l'identifiant du plus ancien message affiché et les endpoints Tasks, documents de travail
et Process ne retiennent que les rounds qui touchent la tranche chronologique correspondante. Le
chargement progressif d'un morceau d'historique recule cette borne et étend les trois listes ; une
room ancienne n'expose donc pas d'emblée tout son historique de travail. Les documents regroupent
les références `document://` des messages, des traces d'outils réussies et des Working Sets actifs
des Tasks projetées. Leur contenu et leur modification repassent par les ACL et les révisions
optimistes d'`app.memory`. Les Process regroupent les runs liés directement aux rounds visibles et
ceux rattachés à l'arbre de Tasks correspondant.
Les listes de documents et de Process suivent elles aussi un ordre récent d'abord et chargent leurs
éléments plus anciens au scroll, par tranches de dix, sans commande de pagination visible.

Pour les bridges externes, un utilisateur ne voit une room que si l’identité distante associée à
son compte dans « Mon profil » en est membre. Cette correspondance enrichit également la projection
du contact en mémoire. Avec `CHAT_IMPERSONATE`, le même écran peut prendre la perspective d’un agent
IA et filtre alors les rooms par son membership canonique exact ; l’écriture reste désactivée.
Le nom affiché et la visibilité de l’aperçu du dernier message sont des préférences locales au
membre canonique : ils s’appliquent donc aussi aux rooms externes sans modifier ni perdre le nom
fourni par le bridge. Masquer l’aperçu n’empêche pas l’ouverture de l’historique autorisé. L’avatar
de la room reste celui de l’agent propriétaire de sa connexion, indépendamment du nom personnalisé,
et les notifications de nouveaux messages conservent leur comportement normal.
La liste Chat masque les rooms issues des messageries externes et les rooms archivées par défaut.
Un menu propose deux bascules indépendantes pour les inclure dans la recherche. L’archivage est
une préférence locale au membre canonique et reste réversible depuis la modale de conversation ;
il ne modifie ni la room ni sa visibilité pour les autres membres. Les rooms restent paginées côté
serveur, mais l'interface charge la page suivante au bas du scroll et n'affiche aucun contrôle de
pagination.

L’historique Nextcloud Talk est synchronisé à la demande par tranches. L’ouverture d’une room
et le retour en bas du fil importent la tranche distante la plus récente. La réponse fournit un
curseur opaque ; lorsque l’utilisateur atteint le haut, le frontend le renvoie pour importer une
seule tranche plus ancienne, puis conserve le curseur suivant. La journalisation canonique rend
ces recouvrements idempotents et le scroll ne dépend donc pas d’un import global préalable.
Lorsque le bridge déclare la capacité `UNREAD`, la liste Chat demande en plus les compteurs au
provider, une seule fois par connexion et par chargement de page. Le résultat complète le compteur
canonique sans jamais le réduire : le provider observe le compte du bridge, dont la perspective
peut différer de celle de l’utilisateur Galaris. Une room n’est marquée comme lue qu’après le rendu
du dernier message durable dans une conversation réellement visible ; le marqueur transmet
l’identifiant provider exact de ce message. Un onglet masqué, le volet mobile des détails ou le
mode impersonation ne modifient jamais la lecture. Si le provider est indisponible, le curseur
canonique local reste le repli et son échec n’empêche pas l’affichage.

Chaque room Messenger peut porter un Topic facultatif persistant. Le Topic effectif d'un message
est résolu dans l'ordre suivant : surcharge explicite du message, Topic par défaut de la room,
puis classement propre historique ou Dream du message. La colonne canonique distinguant une
surcharge explicite empêche une modification ultérieure de la room d'écraser les choix réalisés
avec `@topic`. À l'inverse, les messages sans surcharge reflètent immédiatement le nouveau Topic
de la room, sans réécriture de leur journal durable. En l'absence de Topic de room, la
classification historique conserve son comportement.

La création d'une conversation interne persiste atomiquement l'agent destinataire, son libellé,
son Topic facultatif et la préférence du propriétaire indiquant si le dernier message peut être
affiché dans la liste. Les anciens clients qui ne fournissent que l'agent conservent le libellé
numéroté dérivé de celui-ci et l'aperçu activé. Choisir un Topic dès la création requiert le même
privilège `TOPIC_EDIT` qu'une modification ultérieure.

Le Messenger interne ouvre le sélecteur de surcharge pour le prochain message avec `@topic`. Le
sélecteur redevient vide après chaque envoi réussi. Une surcharge explicite dispense ce message de
la classification Dream. Le round et toute Task qu'il lance reçoivent le Topic effectif du dernier
message humain déclencheur. La réponse agent copie la provenance de Topic de ce message : elle
reste donc alignée pendant le streaming, après persistance et après une modification du Topic de
room, tout en conservant une éventuelle surcharge explicite.

Depuis l'audit d'une bulle, un utilisateur disposant de `TOPIC_EDIT` peut corriger manuellement
le Topic du seul message ou celui de ce message et de tous les messages chronologiquement
suivants de la même room qui portent encore son Topic d'origine. Les messages antérieurs et les
messages affectés à un autre Topic ne sont pas modifiés. Cette correction agit sur les messages
canoniques et reste distincte du Topic historique du round. En l'absence d'une décision Dream
correspondante, elle apparaît comme une affectation manuelle dans l'audit.

## Bridges actifs

| Bridge | Réception principale | Adaptation |
|---|---|---|
| OneBot | WebSocket inverse push | Payload OneBot v11 vers observation privée puis `Message` persisté |
| Matrix | Boucle sync ; événements voix sur le même flux | Client Matrix vers message, média ou call canonique |
| Nextcloud Talk | Polling ou signaling | Conversation Talk vers message/call canonique |
| Telegram | Long polling | Update Bot API vers message canonique |
| WhatsApp | Webhook push | Graph API vers message canonique et statuts de livraison |
| Mail | Polling IMAP | UID entrant vers journal canonique puis Task directe de lecture |
| Internal | API Galaris + WebSocket par room | Message humain natif vers round foreground ; travail long vers Task liée |

Le provider natif conserve le kind technique `internal`, tandis que son Tool public est `chat`.
Les URI de ses pièces jointes utilisent donc le schéma `chat://`.

La liste exacte des paramètres, capacités et modes entrants vient de chaque `BridgeSpec`
enregistré dans le package du bridge.
Le même contrat déclare aussi `identity_param`, la clé de compte distant qui relie une identité
observée à la `Connection` de son agent. Messenger applique ensuite le `param_map` du Tool avant
la recherche : Nextcloud utilise ainsi son `login`, tandis que Matrix et OneBot utilisent
`user_id`. Cette résolution intervient à l’ingestion et lors de l’hydratation d’anciennes lignes,
afin que Chat, les avatars et le TTS consomment tous le même `agent_id` canonique.

Tous ces bridges peuvent être actifs pour un même agent. Messenger est une capacité optionnelle
d’un `Tool`, au même niveau que MCP et File Share. Le `messenger_config.service` choisit le bridge,
`settings` porte les valeurs serveur communes à toutes les connexions de ce Tool, et `param_map`
relie le contrat du bridge aux paramètres de connexion propres à l’agent. Le code du Tool ne
sélectionne jamais implicitement un bridge.

Les paramètres par connexion sont `login`/`password` pour Nextcloud Talk,
`user_id`/`token`/`password` pour Matrix (token et password facultatifs individuellement),
`token` pour Telegram, `access_token`/`phone_number_id` pour WhatsApp et `user_id`/`token` pour
OneBot. Les réglages Tool indispensables sont respectivement `base_url`, `homeserver`, aucun,
`app_secret`/`verify_token` et `platform`.

Chaque Tool de messagerie déclare directement ce contrat. `MESSENGER_DRIVER` configure le service
du Tool générique `messenger` lorsqu’il est activé ; les Tools propres aux bridges déclarent leur
service explicitement.

`MESSENGER_ENABLED_CHANNELS` est le témoin global de disponibilité. Il contient un sous-ensemble
sans doublon des kinds pris en charge et vaut la liste complète sur une installation neuve.
Un bridge retiré de cette liste conserve ses paramètres et ses connexions, mais disparaît des
recherches, outils et connexions de messagerie. Ses aliases MCP, webhooks, WebSockets,
listeners texte/voix et appels actifs sont arrêtés ou refusés. Il reste visible uniquement dans
les préférences, où son onglet permet de le réactiver. Une fonction non-messagerie portée par le
même outil, telle que WebDAV pour Nextcloud, reste disponible indépendamment.

## Réception canonique

```text
transport externe
  → authentification et validation dans bridge.*
  → conversion en app.messenger.models.Message
  → app.messenger.inbound.dispatch_incoming
  → journal durable + déduplication récente
  → signal message_received
  → app.messenger.service
  → projection privée du contact humain dans Memory
  → humain avec connexion + room exactes : app.conversation
  → identité IA ou entrée legacy incomplète : collaboration/Task existante
```

La clé durable d’un message est `(connection_id, remote_message_id, direction)`. La connexion
fait partie de l’identité parce qu’un même outil peut représenter plusieurs comptes. Un
webhook dupliqué déjà `admitted` est accusé selon le protocole mais ne redéclenche pas le métier.
Avant toute interaction, tout round ou toute Task, l'admission canonique applique une règle
permanente aux bridges de messagerie instantanée : un message âgé de plus d'une heure est marqué
`admitted` avec la disposition auditée `dream_only`, reste visible dans le journal et éligible aux
mécanismes Dream, mais ne déclenche aucun run Conversation ou Task. Cette règle s'applique aussi
aux récupérations après crash et aux imports d'historique complet. Mail est explicitement exempté
car son contrat asynchrone est `inbound_admission="task"`.
Une Task issue directement d'une admission conserve en plus l'UUID canonique du message dans une
colonne unique. Le statut du journal n'est donc jamais l'unique barrière : une redelivery après un
crash survenu entre la création de la Task et l'accusé `admitted` retrouve la même Task et ne peut
pas dupliquer l'effet métier. L'admission conversationnelle possède la même garantie par le lien
durable unique du message à son round.
Lors du cutover depuis l'ancien journal, DbAdmin ferme les entrées historiques restées à
`received` avant le démarrage des listeners. Il met aussi en quarantaine les Tasks et rounds
encore actifs dont la création est postérieure de plus d'une heure à l'horodatage canonique de
l'entrée : l'admission étant synchrone, cet écart prouve une réadmission d'historique. Les
résultats déjà terminaux restent intacts pour audit.
L’admission humaine fait partie du reçu durable : une exception après journalisation marque le
message `failed`, et une redelivery reprend l’admission jusqu’à la création effective du round.
Le listener Nextcloud n’avance son curseur de room qu’après cette admission ; au redémarrage, il
rejoue son historique récent borné, dédupliqué par le journal canonique.

### Admission des conversations humaines

Une entrée humaine possédant une connexion et une room exactes est admise directement depuis le
`Message` Messenger canonique. Le verrou porte sur sa `Room` interne et le message est relié à un
`ConversationRound` figé de cette room. En groupe, tous les auteurs partagent la même room mais
restent identifiés sur leur propre message. Le scheduler `app.conversation` est indépendant de
celui des Task : une room n’exécute qu’un round à la fois, tandis que des rooms différentes peuvent
avancer en parallèle.

Le dernier message non traité est l’ancre LIFO du round. Tous les messages entrants non consommés
sont liés au round, puis rendus chronologiquement. Un nouveau message arrivé avant le premier effet
supersède le round sans consommer ses entrées ; elles sont réagrégées dans son successeur. Après un
effet durable, l’ancienne réponse libre est supprimée et le nouveau message forme le round suivant.
Chaque lien d'entrée porte `consumed_at` lorsqu'il est définitivement consommé. Les anciennes
mailboxes, entrées et outbox ne sont plus écrites ; elles restent temporairement présentes afin de
drainer et contrôler les données antérieures à la bascule avant leur suppression Atlas.

Le contrôleur court est toujours interne et utilise le niveau texte `low` dans l’unique profil
effectif de l’agent. Il n’existe aucun repli vers l’exécuteur ni vers un autre profil. Il ne dépend pas du driver executor et ne
prend aucun slot Task. Un travail long crée une Task liée qui
reprend le scheduler et le driver ordinaires ; un Process est lancé sans attente. Le lien
conversationnel projette le résultat réussi de la Task après sa terminaison. Son échec définitif
revient par un message localisé qui expose la cause persistée après masquage des secrets usuels.
Cet envoi et les résultats terminaux de Process utilisent un état de notification porté directement
par le lien Task ou Process ; aucun driver agentique ne publie implicitement son texte terminal.
En cas d’erreur de transport après dispatch potentiel, la livraison devient `UNKNOWN` et n’est pas
rejouée aveuglément.

Son prompt dédié conserve le personnage de l’agent — identité, personnalité, poste et fiche de
poste — mais remplace les règles d’exécution longue par une politique de réponse rapide. Il reçoit
la projection exacte des fonctions natives conversationnelles ainsi que les identifiants,
libellés et descriptions des Process affectés. Il répond directement après quelques appels courts,
lance le Process correspondant si le besoin est déjà modélisé, ou crée sinon une Task autonome ;
il ne bloque jamais la conversation en attendant leur résultat.

Pour un auteur humain, le dispatcher court retourne directement `EXEC standard`, sans modèle,
sur tous les canaux textuels. L'exécuteur conserve le choix d'admettre un Process ou une Task.
Le contrôleur restitue le résultat réussi sans contrôle d'admission a posteriori ni jugement de
formulation. Il transmet les erreurs d'exécution au scheduler, qui conserve sa reprise bornée et
ses protections contre la répétition d'effets. Une erreur finale produit la réponse de secours,
avec sa catégorie et son détail après masquage des formes usuelles de secrets. La Task admise
conserve l'agent, la room et le driver ordinaires ; Hermès peut donc l'exécuter sans intervenir
dans le contrôleur conversationnel interne.

Avant l'admission, le contrôleur distingue strictement amendement et nouveau travail. Un amendement
conserve le même artefact ou la même cible principale ainsi que des critères de réussite
substantiellement identiques. Une autre cible, un autre dépôt, une autre ressource, un autre
livrable ou un résultat vérifiable indépendamment reçoit une nouvelle Task, même si la demande
découle du même incident. L'URI d'une Task amendée reste unique, mais le round expose son
`TaskAmendment` comme lignée d'audit. Lorsqu'un amendement interrompt une exécution, le nouveau
dispatcher et le nouveau briefing voient l'objectif fusionné ; le checkpoint conserve uniquement
son journal d'effets anti-rejeu et abandonne l'ancien historique fournisseur. Un résultat ou un
checkpoint portant l'empreinte d'un objectif antérieur est refusé avant persistance terminale.
Le scheduler clôt alors l'ancien attempt comme annulé, sans consommer de retry ni inscrire une
erreur sur la Task révisée.

Le contexte récent expose un nombre borné de Tasks et de ressources actives. Les libellés de run
génériques ne servent pas de sujet au rappel mémoire : la requête est construite depuis le message
humain courant et son identité structurée.

La session récente est reconstruite depuis le journal canonique Messenger et conserve, pour
chaque entrée, les UUID internes du message, de la room et des fichiers, les identifiants externes,
l'expéditeur et les pièces jointes. Chaque fichier reste imbriqué dans son message et porte la
référence `<tool.code>://<room-locator-provider>/<file-uuid-local>` ; un message sans texte qui contient uniquement un
fichier reste une entrée chronologique complète. Cette même projection est figée dans toute Task admise depuis
le round : un planner ou un driver reçoit donc l'historique Messenger complet autorisé, pas
seulement le dernier texte. Une demande explicite de joindre une version déjà présente est résolue
par UUID de pièce jointe avant le dispatcher, puis les octets existants sont copiés vers la room.
Elle ne crée aucune Task et le service d'admission refuse toute tentative de la transformer en
nouvelle génération.

Lorsqu'un message humain admis en conversation porte un ou plusieurs fichiers audio, Messenger
résout le niveau texte `low` du profil effectif avant de créer le round. Si ce modèle ne déclare
pas `input_audio` et qu'un `transcription_llm_id` utilisable est configuré, chaque fichier est
transcrit immédiatement. Les transcriptions sont conservées dans les métadonnées du message et
ajoutées à son texte uniquement dans les projections destinées aux modèles, y compris l'historique
des tours suivants. Le texte visible et l'URI canonique de l'audio restent inchangés. Un modèle
conversationnel audio-capable ne déclenche pas ce STT automatique ; l'absence ou l'échec du STT
reste fail-open et n'empêche jamais l'admission du message.

Le registre fait partie du contexte d’exécution. Un round textuel est présenté comme la suite d’un
clavardage, jamais comme un courrier : il ne répète ni salutation, ni reformulation de convenance,
ni signature à chaque message. Un tour vocal est présenté comme la suite d'un appel dont la
salutation initiale est gérée séparément : il adapte la longueur à la demande et au moment tout en
gardant une formulation naturelle à l’oral, ne relit pas la transcription et ne conclut par une
formule d’au revoir que lorsque l’appelant termine réellement la conversation.

Les expéditeurs reconnus comme agents IA conservent le workflow de collaboration Task. Une entrée
humaine sans adresse de réponse exacte reste temporairement sur le chemin legacy afin d’éviter
une perte silencieuse.

Mail déclare une politique d’admission `task` propre au transport : chaque nouveau courriel
journalisé crée immédiatement une Task qui reçoit sa référence `mail_get`, sans passer par le
contrôleur conversationnel court. Cette exception reste possédée par `app.messenger`; le bridge
IMAP ne crée jamais lui-même une Task. Le résultat terminal n’est pas renvoyé implicitement par
SMTP, car toute réponse doit rester un effet explicite et idempotent d’un outil `mail_*`.
Les rooms techniques créées pour ces courriels restent dans le journal canonique mais sont exclues
de la projection Chat, y compris dans la vue d’un agent, afin qu’un flux IMAP ne crée pas une
discussion visible par message.
L’expéditeur est observé comme contact Memory avec son adresse normalisée et son éventuel nom MIME.
Après un envoi SMTP confirmé, les destinataires sont observés par la même surface publique. Chaque
compte conserve son propre item source ; un futur rapprochement Dream ne pourra ajouter que des
liens et ne fusionnera pas ces identités.

La supervision de **Suivi d’exécution → Conversations textuelles** lit ces projections durables
via `/conversations/messages`. Chaque message humain reçu produit une ligne paginée, avec la
réponse du round correspondant dans la même cellule, sur une seconde ligne tronquée.
Les compteurs suivent dans cet ordre les conversations à jour, en attente et en cours, puis les
conversations ayant rencontré une erreur. Ce dernier compteur filtre les messages couverts par un
round `ERROR_RESOLVED`, indépendamment de l’état des autres rounds de leur room.
Quand un round agrège plusieurs messages, chacun conserve sa propre ligne et référence la réponse
commune. Un clic charge directement ce seul round via `/conversations/rounds/{id}` et ouvre une
modale avec le bloc agrégé complet, la réponse et les appels `/llm-calls` associés. Un round en
échec affiche la réponse de secours envoyée, son statut et son erreur, ainsi que la trace partielle
du driver pour chaque tentative.

Les deux modales possèdent une barre d’actions commune. Les routes
`/conversations/rounds/{id}/dataset` et `/voice/conversations/turns/{id}/dataset` exposent le même
jeu de données complet que l’inspection administrative afin de le copier en JSON. La suppression
est réservée à `TASK_EDIT` et accepte le round quel que soit son état. Elle verrouille le round,
annule immédiatement son worker local s’il existe, puis supprime la ligne durable : un worker d’une
autre instance perd alors sa lease et interrompt son action au heartbeat suivant. Elle retire le run
de l’historique sans supprimer les messages canoniques Messenger. Les Tasks et ProcessRuns déjà
créés ne sont pas supprimés. Les `LLMCall` restent dans le journal global après détachement de leur
clé conversationnelle ; ceux encore `running` sont fermés comme `cancelled` avec leurs compteurs,
coûts et sorties partielles intacts.

L’identifiant unique d’un traitement textuel ou vocal est `ConversationRound.id`. Les modales
affichent cet UUID primaire et le copient dans le presse-papiers au clic.
Le package MCP optionnel `galaris_admin`, inactif par défaut, expose `conversation_round_get`.
Chaque fonction exige encore une connexion active au moment de l’appel et retourne toutes les données
persistées directement pour ce tour ainsi que tous ses appels LLM corrélés. Le tour vocal ne
contient pas les octets audio, qui ne sont pas persistés dans ce jeu de données conversationnel.

La même barre permet d’envoyer un tour dans un benchmark du Lab IA si l’utilisateur possède
`EVALUATION_EDIT`. L’action demande toujours le jeu de données cible, même lorsqu’un seul jeu
existe ; si aucun jeu n’existe, l’utilisateur peut le créer avant la copie. Un round textuel ne
peut alimenter que l’**Exécuteur conversationnel**, et un tour vocal que l’**Exécuteur vocal**.
Le cas reçoit une copie de travail de l’entrée et de la sortie ainsi qu’un snapshot source autonome
contenant toutes les preuves persistées au moment du transfert. Le benchmark ne rejoue jamais le
tour et ses outils factices ne produisent aucune Task ni aucun Process réel.

Les appels téléphoniques sont les lignes parentes de leurs tours, affichés en permanence comme des
sous-tâches et sans accordéon. Seule une ligne de tour est cliquable ; sa modale contient ce tour
uniquement, sa transcription, sa réponse et ses appels LLM. La page vocale charge les tours des
appels de la page courante en une requête backend groupée. Toutes les traces restent reliées par
`conversation_round_id`.

La projection de supervision est paginée depuis les messages entrants canoniques. L’API borne les
pages demandées afin qu’une room contenant des milliers de messages ne puisse pas produire une
lecture non maîtrisée. Les actions d’export, de transfert Lab et de suppression restent des
opérations administratives explicites ; elles n’interviennent ni dans l’admission, ni dans les
leases du scheduler.

Nextcloud constitue un bridge unifié : `bridge.nextcloud` enregistre à la fois l’adaptateur Talk
auprès de `app.messenger` et le transport WebDAV auprès de `app.file_share`. Un même Tool peut
activer MCP, File Share et Messenger. Les deux capacités de bridge restent néanmoins indépendantes :
elles ont chacune leur sélecteur de service, leur URL et leur `param_map`. Une connexion peut donc
utiliser deux serveurs Nextcloud ou deux couples de paramètres différents pour les fichiers et
la messagerie.

Le journal conserve texte, identités, conversation, métadonnées bornées des pièces jointes, date
canonique et statut. `messenger_files` normalise ces métadonnées avec un UUID interne, sans jamais
stocker les octets ni le contenu extrait : ceux-ci restent dans la messagerie d'origine et sont
téléchargés à la demande. Les curseurs et la santé des listeners sont également persistés par connexion.
`messenger_room_history` parcourt l'historique par pages, de la plus récente vers les plus
anciennes. Chaque page reste chronologique et fournit un curseur opaque à repasser à l'appel
suivant. Matrix et Nextcloud utilisent le curseur historique natif afin d'atteindre aussi les
messages antérieurs au journal Galaris ; Telegram, WhatsApp et OneBot paginent le journal durable,
leurs protocoles ne fournissant pas tous un historique distant arbitraire et portable.

Après résolution serveur de la connexion et du kind réel, Messenger enrichit l'expéditeur courant
avec l'annuaire des identités IA. Un expéditeur humain non vide est projeté par la façade publique
de Memory avant la résolution d'une interaction ou la création d'une Task. Une réponse humaine
consommée par un choix produit donc elle aussi une fiche. L'écriture est fail-open : son échec est
journalisé sans identifiant natif ni contenu et ne change jamais le traitement conversationnel.

Une réponse qui désigne sans ambiguïté un numéro, un identifiant, un libellé ou un alias d'une
interaction en attente reste résolue déterministiquement avant le contrôleur conversationnel. Si
le texte ne correspond à aucune option, il n'est pas perdu ni forcé dans un choix : il devient un
round normal. Le round reçoit alors la projection bornée des interactions encore actives pour la
connexion, le Tool, la room, l'agent et l'expéditeur exacts. Le LLM conversationnel peut appeler
`conversation_choice_resolve` avec la référence et l'identifiant d'une option persistée, ou poser
une question si l'intention reste ambiguë. La commande reverrouille la même portée, refuse toute
option inventée et remet la résolution au handler idempotent d'origine. Une réorientation peut
ainsi refuser une approbation devenue obsolète puis amender la Task concernée dans le même round.

La portée des choix associe l'UUID canonique du salon à l'identifiant externe du participant,
avec la connexion, le Tool et l'agent. Les approbations Dream suivent ce même contrat : une réponse
numérique non ambiguë applique le choix sans round conversationnel ni appel LLM. DbAdmin répare
les anciennes demandes de classement encore en attente dont le destinataire était un UUID interne,
uniquement si le message source prouve la même identité et la même portée, sans capturer de décision.
Le chat transmet sa langue d'interface pour les messages texte et les pièces jointes ; le journal
la conserve pour l'admission et les reprises. La proposition Dream reprend la langue du round
source, puis celle du message, avec la langue d'instance comme dernier repli.

Dans le chat interne, les messages de choix exposent aussi une projection structurée : titre,
corps, options et état durable, sans les métadonnées métier ni les jetons de traitement. Le chat
affiche des boutons, réserve la réponse au destinataire humain et conserve le choix sélectionné
après rechargement. La commande de réponse vérifie le salon, la connexion, le Tool, l'agent et le
destinataire, puis appelle directement le résolveur déterministe, sans round ni LLM. Un double
envoi du même choix est idempotent ; un choix différent ou expiré est refusé. Les transitions
de capture enregistrent aussi la réponse par bouton comme message humain dans le journal,
avec le libellé choisi, la question et sa référence. Cette réponse appartient à l'historique
transmis aux agents et au contact canonique, sans créer de round ni de Task. Le message et
la décision sont committés ensemble avant le handler ; une reprise de celui-ci ne duplique
pas la réponse, même après une erreur de traitement. Les transitions
diffusent une invalidation du message pour synchroniser les autres vues, y compris après une
réponse textuelle. Le texte numéroté canonique reste inchangé pour les messageries externes ;
les interactions ne proposant que du texte libre restent dans le compositeur habituel.

L'adresse sociale est `(messaging_id, user_id)`, où `messaging_id` est ici le code canonique du
bridge et `user_id` l'identifiant natif exact, sensible à la casse. La connexion, la room et le
message sont des données de transport et n'entrent pas dans cette identité. Memory ajoute seulement
`owner_agent_id` à sa clé technique pour isoler les mémoires privées de deux agents. Deux
connexions du même agent et du même bridge convergent donc vers une fiche, tandis que deux agents
restent distincts. Deux canaux convergent automatiquement seulement lorsqu'ils portent le même
`galaris_user_id` prouvé. L'administration peut aussi fusionner explicitement deux contacts du même
agent : les adresses deviennent alors des alias durables du contact conservé et les futures
observations ne recréent pas le doublon. Cette fusion repointe dans une transaction les souvenirs
scellés, scopes Topic/contact, arêtes mémoire, messages, rounds et Tasks avant d'oublier l'ancienne
projection.

L'administration peut également oublier explicitement un contact. Les souvenirs scellés à ce
contact sont oubliés avec leurs révisions et ressources, les références des messages, rounds et
Tasks sont vidées, puis la projection et ses identités sont purgées. Une nouvelle interaction avec
la même adresse recrée un contact neuf et ne réactive aucune donnée oubliée.

`messenger_users` constitue le référentiel canonique des identités distantes observables. Une ligne
est identifiée en interne par UUID et reste unique par `(tool_id, external_id)` ; elle conserve le
nom affiché fourni par le système distant et son historique. Son `agent_id` nullable peut la relier
explicitement à un agent Galaris ; plusieurs identités distantes peuvent désigner le même agent.
Le booléen `is_ai`, faux par défaut, qualifie explicitement une identité automatisée sans imposer
qu'elle soit déjà liée à un agent. Une contrainte garantit qu'un `agent_id` non nul implique
toujours `is_ai = true`, sans imposer la réciproque pour les agents IA externes.
Deux identités appartenant à des Tools différents restent deux lignes Messenger, même lorsqu'elles
désignent la même personne. Leur rattachement à un contact Memory commun est une identité Galaris
prouvée ou une décision administrative explicite ; une similarité de nom ne suffit jamais.

`messenger_rooms` constitue de la même manière le référentiel des rooms par
`(connection_id, external_id)`. La table courante `messenger_room_users` relie les UUID locaux des
rooms et utilisateurs ; elle n'est pas historisée elle-même. La disparition d'une association
n'est appliquée que lorsqu'un bridge a fourni la liste complète des participants de cette room.

La façade Messenger synchronise toute donnée distante avant de la rendre au reste de Galaris. Les
listes de rooms, annuaires, historiques entrants et réponses d'envoi sont insérés ou rafraîchis de
façon idempotente, puis reconstruits depuis les lignes locales. Les UUID locaux sont portés par
`local_id`; les identifiants distants restent nécessaires aux bridges mais ne servent pas de clé
primaire Galaris.

Une réponse sortante acceptée doit porter une référence distante non vide avant sa reconstruction
canonique. L'endpoint OCS de partage de fichier Nextcloud n'expose pas directement l'identifiant du
message Talk qu'il crée : le bridge relit donc l'historique récent avec le nom DAV aléatoire et
unique, puis retourne le message et ses pièces jointes réellement observés. Si leur propagation est
retardée, il journalise une référence de partage unique plutôt qu'un identifiant vide qui entrerait
en collision avec tous les uploads précédents. Une erreur après acceptation distante reste
`UNKNOWN` et n'autorise jamais une répétition aveugle ; l'historique fournisseur sert à confirmer
l'effet et à créer ensuite le reçu de livraison.

Une absence distante n'est une preuve de suppression que dans un instantané explicitement
exhaustif. Par défaut, les bridges déclarent leurs listes non autoritatives. Un filtre de recherche,
une pagination incomplète, une room chargée sans tous ses participants ou une fenêtre des N
derniers messages ne peut donc jamais historiser ce qui n'est pas remonté. Lorsqu'un bridge
certifie au contraire un instantané complet, les rooms ou utilisateurs absents reçoivent
`deleted_at` à la date de constatation et `deleted_by = NULL`; ils ne remontent plus dans les
lectures courantes. Une observation ultérieure de la même clé distante restaure la ligne existante
au lieu de créer un doublon.

Le journal permet de réparer les observations manquées. `make rebuild-messenger-contacts` relit
par lots les derniers expéditeurs entrants de chaque connexion, résout à nouveau le Tool, le kind
durable et l'identité IA, puis appelle le même projecteur que le runtime. Le champ `platform`
historique du journal n'est jamais autoritatif. La suppression d'une connexion ne supprime pas une
fiche déjà connue : la route technique n'est pas la source de l'identité humaine.

Matrix recharge son `next_batch` depuis cet état durable. Le premier `/sync` est traité comme les
suivants et son nouveau curseur n'est enregistré qu'après admission complète du lot dans le journal
canonique. Un arrêt avant l'enregistrement rejoue le lot depuis l'ancien curseur ; la
contrainte durable des messages et la déduplication des événements d'appel empêchent alors une
seconde émission. Cette frontière accuse l'admission au journal, pas encore la réussite métier de
tous ses consommateurs : la reprise générique journal → Task et sa file morte restent un chantier
distinct.

Le bridge Matrix filtre facultativement rooms, expéditeurs et mentions. L’auto-acceptation d’une
invitation est désactivée par défaut, exige une allowlist et refuse les rooms annoncées comme
chiffrées. Les notices automatisées, éditions et échos du compte bot n’entrent pas dans le workflow
de Task. Les réponses conservent `m.in_reply_to`; les images, documents, vidéos et audios restent
des `File` canoniques téléchargés à la demande. Le bridge ne gérant pas Megolm, tout envoi
dans une room chiffrée échoue avant transfert au lieu d’émettre du contenu en clair.

## Projection de session

Avant une exécution agentique, `app.messenger.session` reconstruit une vue bornée par
`(connection_id, room_id)`. Elle lit le journal durable dans l'ordre canonique, écarte le message
qui déclenche la Task et toute ligne plus récente, puis applique deux limites configurables :
nombre de messages et nombre de caractères. Avant cette lecture, la connexion est vérifiée comme
appartenant à l'agent ; une
référence étrangère ou invalide ne produit aucun historique. Le curseur, la portée et l'indicateur
de troncature accompagnent le snapshot.

À l'admission, `app.conversation` persiste dans `Task.messages` cette projection historique bornée,
puis le ou les messages déclencheurs. Les enfants d'un plan héritent du même instantané et de son
curseur. Lorsque le journal contient les lignes correspondantes, il reste la source autoritative
pour reconstruire la projection à la même position ; `Task.messages` sert de trace inspectable et
de repli si le journal est vide ou n'est plus disponible. Cette règle évite les doublons, interdit
l'injection de messages futurs et permet de changer de driver sans perdre la conversation. Le
provider de contexte commun remet ensuite les mêmes tours autorisés aux deux drivers. Pour une
Task humaine dont le contact est prouvé, cette projection suit le contact canonique à travers les
rooms et connexions et exclut tout autre participant. Elle alimente une capsule figée avec les
Tasks, ressources et mémoires du même contact ; le Topic tardif de Dream n'est pas consulté. Sans
contact prouvé, aucun historique de room collective n'est injecté.

Le scope complet et le curseur du journal restent dans les métadonnées serveur. Le contexte rendu
au modèle expose la plateforme et la room utiles aux tools, jamais l'identifiant de connexion ni le
scope interne. Pour Hermès, ce scope produit deux valeurs distinctes : une clé logique condensée et
stable pour `X-Hermes-Session-Key`, puis un ID de transcript opaque qui suit les rotations de
compaction. Un ID de room externe n'est jamais utilisé comme nouvel ID de transcript.

## Envoi canonique

1. La façade résout la connexion et construit le `Messenger` enregistré pour son `kind`.
2. Le domaine vérifie la `Capability` demandée.
3. La façade résout les modèles persistés `Message`, `Room`, `MessengerUser` et `File`, puis le
   bridge convertit leurs observations privées vers le protocole externe.
4. La réponse est journalisée avec son identifiant distant.
5. Les reçus de livraison ne peuvent qu’avancer `accepted → sent → delivered → read` ; une
   notification tardive ne régresse pas le statut.

Une opération optionnelle non déclarée lève `NotSupported`; elle n’est pas simulée par une
réponse de succès.

### Réponse depuis une Task legacy

Une Task Messenger persiste une adresse exacte :

```text
Task.messenger_connection_id + Task.message_platform + Task.message_group_id
```

La connexion est la source de vérité, la plateforme sert de contrôle de cohérence et la room reste
opaque. Les enfants de plan, attentes, interactions, Goals et drivers héritent de cette adresse.
Deux rooms nommées `42` sur deux connexions ne partagent donc ni session, ni await, ni garde de
réponse. La connexion reste une donnée serveur et n'est jamais ajoutée au bloc de contexte visible
par le modèle.

Cette adresse fournit au runtime le contexte des pièces jointes, interactions et outils Messenger,
mais ne déclenche aucun envoi terminal automatique. Une Task legacy directe, dépourvue de lien
`ConversationTaskLink`, ne peut répondre dans la room qu'en exécutant explicitement un outil
Messenger. Les drivers Internal, Hermès direct et Hermès Kanban retournent tous leur
`ExecutionResult` sans appeler eux-mêmes le transport.

Une Task créée par `app.conversation` conserve également cette adresse et son contrat Messenger
complet. Conversation et Task sont deux modes de la même identité agentique : son planner et ses
interactions publient directement la notice initiale de planification, les questions et les
autorisations. L'activation de chaque étape ne
publie pas de message `Étape x/y` : la progression durable reste consultable sur la Task sans
polluer la conversation. Le résultat terminal est garanti par le lien conversationnel, indépendamment
du Harness : après `SUCCESS`, il est envoyé si la trace ne prouve pas que ce même résultat a déjà été
livré par Messenger ; après `ERROR`, une alerte est envoyée. Une livraison explicite réussie du même
résultat classe la notification `SKIPPED`, tandis qu'un message de progression distinct ne la supprime pas.
Les Process lancés par un round utilisent le même principe de notification durable sans recopier leur
contenu dans une outbox. Pour une Task, la réclamation exige un lease libéré et une dernière tentative
terminale ; elle ignore donc les retries automatiques et les annulations. Une livraison ambiguë devient
`UNKNOWN` et n'est pas rejouée. Un retry humain porte un numéro de tentative supérieur et réarme la
projection terminale.

OneBot namespace ses rooms en `group:<id>` et `direct:<id>` avant d'entrer dans ce contrat. Les
anciens IDs non préfixés restent interprétés comme des groupes pour permettre leur livraison, mais
tout nouvel événement ou envoi direct conserve explicitement son kind. L'upgrade préfixe les
anciens groupes persistés dans les Tasks, le journal, les interactions et les bindings
Hermès ; il ne tente pas d'inventer une room privée absente des anciens événements.

### Recherche et nouveau message vers un utilisateur

La recherche Messenger parcourt toutes les connexions actives des bridges disponibles qui exposent
la capacité `SEARCH_USERS`. Chaque annuaire distant est interrogé, les résultats sont synchronisés
dans `messenger_users`, puis la réponse est reconstruite depuis ce référentiel. Chaque résultat
conserve séparément `user_id`, `messaging_id` (la connexion exacte), `tool_id` et la plateforme.
Deux identifiants identiques sur deux connexions restent deux routes distinctes, même si leur ligne
locale est commune à l'échelle du Tool. Ce champ API historique `messaging_id: int` est un sélecteur
de route équivalent au `connection_id`; il ne doit pas être confondu avec le
`messaging_id: str` de l'adresse sociale projetée, qui est le code du bridge.

Une recherche filtrée enrichit le référentiel mais n'en retire jamais de ligne : ses absences sont
hors scope, pas des suppressions. Une recherche sans filtre ne devient autoritative que si le
bridge certifie que sa réponse couvre réellement tout son annuaire. La synchronisation ne crée
aucun rapprochement cross-canal ni canal préféré ; seule l'observation d'un message entrant humain
alimente la projection Memory. Les protocoles sans annuaire interrogeable, comme Telegram Bot ou
WhatsApp Cloud, ne produisent pas de résultat tant qu'un cache technique dédié n'est pas défini.

Pour un nouvel envoi, la connexion exacte de la Task est utilisée lorsqu'elle existe. Hors de ce
contexte, ou pour changer de plateforme, l'appelant fournit explicitement le canal obtenu par la
recherche. Une absence, une ambiguïté ou une incapacité du canal échoue sans repli cross-canal. Les
messages, fichiers et notes vocales appliquent la même règle ; aucun historique d'échange ne choisit
implicitement une plateforme.

## Médias et voix

Les métadonnées d’une pièce jointe restent canoniques, tandis que les octets sont récupérés à
la demande. Les bridges capables de streaming surchargent les méthodes de fichier pour éviter
un chargement complet en mémoire. Une note vocale native passe par la normalisation bornée
décrite dans [Médias et ressources](media-resources.md).

Matrix utilise l’upload média v3, le download authentifié du Client-Server API et un repli de
compatibilité pour les anciens homeservers. Les URI `mxc://`, tailles annoncées et octets
transférés sont validés ; les notes vocales sortent en OGG/Opus sous forme `m.audio`.

Un appel temps réel transporte `connection_id + kind + room_id` jusqu'à une
`VoiceConversationSession` durable. Lorsqu'il est lancé depuis une conversation canonique, la
session réutilise sa `messenger_room` : plusieurs appels successifs possèdent chacun leur cycle de
vie, mais poursuivent la même chronologie visible et le même contexte. Un transport sans room
canonique connue conserve une room audio dédiée. La salutation initiale, chaque prise de parole et chaque message agent sont
journalisés séparément dans `messenger_messages`. Un commit audio sans transcription conserve un
message entrant au texte vide plutôt que de faire disparaître l'intervention. Les fragments du
stream agentique continuent d'alimenter immédiatement la synthèse vocale, mais sont concaténés en
un seul `Message` de réponse : un delta de token ou de mot n'est jamais une frontière
conversationnelle. Plusieurs réponses explicitement distinctes conservent en revanche leur ordre
via `response_sequence` et `sequence`.

Pour le transport navigateur, l'API fournit au client et à `aiortc` le même relais ICE et les mêmes
identifiants temporaires. En mode intégré sans URL explicite, leurs locators diffèrent : le
navigateur reçoit le nom dérivé d'`APP_HOST` et l'IPv4 LAN détectée, tandis qu'`aiortc` rejoint le
même coturn sur `host.docker.internal`. Le navigateur peut ainsi contourner un DNS interne, un
proxy applicatif ou un hairpin NAT qui rendrait le locator nominal impropre à TURN. En
environnement assimilé à la production, cette liste contient obligatoirement un relais TURN
authentifié. Comme un client mobile natif, le navigateur envoie immédiatement son offre puis
transmet les candidats ICE au backend, jusqu'au marqueur de fin de collecte. Les candidats en
attente sont regroupés dans des lots ordonnés de 50 au maximum, y compris ceux reçus pendant
une requête en cours, pour éviter qu'une rafale de routes sature le quota HTTP. L'API accepte
aussi les anciens envois unitaires avec les mêmes contrôles de droits et de portée de l'appel.
Un rejet de signalisation est affiché sans raccrocher automatiquement : l'état WebRTC décide
de la fermeture effective, notamment quand une autre route fonctionne déjà. Les
candidats TURN tardifs ne sont donc plus perdus derrière le premier candidat local et la PWA ne
bloque pas la création de l'appel en attendant la collecte complète. Le
compose dédié
`compose.turn.yaml` fournit coturn par défaut en mode
`embedded`, mais sa présence n'appartient pas au contrat applicatif : le mode `external` l'exclut et
utilise les URLs et le secret REST d'un TURN existant. En mode intégré, les allocations sont liées
à l'unique IPv4 LAN publiée par le routeur et jamais à une interface de bridge Docker ; le candidat
relay public remplace cette IPv4 par l'adresse publique détectée. La réponse SDP conserve aussi un
alias relay vers l'IPv4 LAN résolue au démarrage : les clients locaux ne dépendent donc pas du
hairpin NAT UDP du routeur, tandis que les clients distants utilisent toujours le candidat public.
Le backend dérive dans les deux cas,
pour chaque utilisateur, un identifiant TURN REST à durée limitée. Avant d'enregistrer l'appel, il
vérifie que sa réponse SDP
contient réellement un candidat `relay`, et échoue explicitement sinon. Le raccrochage ferme d'abord
les pistes et le pair locaux, puis notifie le registre serveur par une opération idempotente : une
perte réseau mobile ne peut donc pas maintenir le microphone ouvert ni laisser l'interface bloquée.

Le transport navigateur vérifie les droits avant le démarrage, puis les surveille dans une
coroutine indépendante, une seconde après chaque contrôle. Les trames entrantes et sortantes
n'attendent pas ces requêtes en base. Chaque contrôle est borné à une seconde : un refus,
une erreur ou un dépassement ferme l'appel et vide l'audio en attente, même sans activité vocale.
Le raccrochage arrête aussi cette surveillance.

Après retrait d'un appel du registre actif, Voice publie sa terminaison vers la room Chat
canonique lorsqu'elle existe. Le client rafraîchit alors l'état autoritatif de l'appel afin que
l'action de l'en-tête redevienne immédiatement disponible, y compris quand l'agent raccroche.

La salutation courte (« allo? » en français) n'est émise qu'après réception effective de la
première trame PCM distante. Le transport ne doit jamais inviter l'appelant à parler alors que son
subscriber entrant est encore en négociation : dès que la salutation est audible, l'écoute est
donc déjà opérationnelle.

Chaque transcript validé crée un `ConversationRound` et un `AgentRunRequest(task_id=None)` : une
intervention orale n'est donc pas une Task et n'apparaît pas en erreur quand l'utilisateur reprend
la parole. `conversation_round_messages` relie le round à ses messages d'entrée et de sortie ; ses
deux FK sont en cascade, sans placer de FK conversationnelle dans le modèle Messenger.
`conversation_round_id` corrèle le run agentique et ses appels LLM sans les rattacher à une tâche
concurrente de l'agent.

Une erreur technique qui termine l'appel est persistée sur la session, y compris lorsqu'elle
survient avant le premier tour de parole. La projection de supervision l'expose dans le détail de
la conversation afin que la modale affiche le message fournisseur utile sans dépendre des logs.

Un agent configuré en mode `realtime` remplace ce découpage par une session audio persistante.
Chaque commit VAD crée encore un `ConversationRound`, sans inventer de transcript ni d'objectif
textuel : l’audio est interprété directement par le modèle fournisseur. L'historique récent de la
room est projeté comme transcript conversationnel non fiable au démarrage de chaque nouvel appel.
La mémoire core est injectée au démarrage, `memory_search` complète le contexte à la demande et
`task_submit` crée une Task durable par le port agentique.

Après la conversation, Dream peut extraire progressivement les faits durables des tours terminés
qui possèdent un `effective_objective` textuel. Cette extraction n'est jamais sur le chemin Voice.
Elle associe chaque souvenir retenu au nœud structurel hashé de la conversation, sans stocker la
connexion ou la room dans Memory. Les tours realtime audio sans transcript ne sont pas devinés :
leur mémorisation passe par un appel explicite au tool Memory. La création de tous ces liens est
déterministe et sans inférence.

L'agent expose un seul choix vocal. Une ressource de synthèse, notamment ElevenLabs, active le
pipeline STT → agent → TTS. Une voix native découverte pour un modèle STS active directement la
session audio fournisseur associée ; elle n'est pas enregistrée comme un LLM supplémentaire. Le
bridge de messagerie ou d’appel ne connaît ni OpenAI ni ElevenLabs : il continue uniquement à
transporter le PCM canonique.

Le barge-in passe le tour en `INTERRUPTED` et conserve son `effective_objective` dans la session.
Le transcript suivant est concaténé à cet objectif en attente avant le nouveau run. Une réponse
complète consomme l'ensemble ; plusieurs interruptions successives l'accumulent sans dupliquer
les messages bruts dans l'historique fourni au modèle. `source_turn_id` et
`resolved_by_turn_id` rendent cette reprise causale inspectable.

Le moteur vocal direct conserve un pré-roll avant de confirmer le début de parole. Sa taille
est bornée en durée PCM, indépendamment du découpage des trames par le transport. Une prise de
parole continue peut être découpée en blocs audio bornés, mais ces blocs restent un seul tour :
seuls le silence, l'arrêt du flux ou sa fin valident le transcript puis déclenchent la réponse.
Une coupure technique ne doit donc ni relancer le barge-in, ni supprimer le début du message.

Lorsque la ressource sélectionnée expose le streaming natif, chaque trame entrante alimente le STT
exactement une fois, y compris avant la confirmation locale de parole et sous le seuil du détecteur.
Le VAD local décide uniquement du point de commit manuel ; il ne filtre jamais le flux envoyé au
transcripteur. Le tour PCM détecté reste disponible pour un repli batch si la session temps réel
échoue. L'agent ne démarre qu'après ce commit afin qu'une correction de transcript ne réexécute
jamais un outil à effet de bord.

La sortie de l'agent est déjà un flux de deltas. Pour une voix ElevenLabs, des segments parlables
sont transmis sur un WebSocket TTS unique utilisant le modèle faible latence et du PCM brut
24 kHz rééchantillonné au fil de l'eau vers le 48 kHz du transport ; les trames sont jouées sans
attendre la génération d'un fichier MP3 complet. Les autres providers, ou un échec avant la
première trame, conservent le chemin TTS encodé existant. Le barge-in annule dans les deux cas
l'inférence, la synthèse et les trames encore en attente grâce au même numéro de génération.
Une demande explicite de raccrocher arme une fin gracieuse côté domaine vocal, même si le modèle
n'appelle pas `voice_call_stop`. Le tour courant finit de produire sa réponse, puis le moteur attend
la vidange des files applicative et WebRTC avant de quitter le transport ; une fermeture de service
ou un arrêt administratif conserve en revanche l'annulation immédiate.
`voice_call_stop` reste en plus un contrôle obligatoire des deux runtimes vocaux : la projection
conversationnelle pipeline le cible avec le salon et la connexion issus du contexte serveur, et la
surface realtime l'arme sans argument fourni par le modèle. Après son succès, le realtime autorise
une dernière réponse brève, attend la vidange audio, puis quitte réellement le transport.
Un appel n'a pas de durée maximale applicative : il reste actif jusqu'au raccrochage d'un participant,
à une demande `voice_call_stop` ou à l'arrêt du service qui possède la session.

Chaque message textuel du journal et chaque tour Voice terminé reçoit séparément un `topic_id` par
le détecteur séquentiel. Le collecteur texte isole connexion+salon, conserve au plus dix messages
et n'invente pas d'heure distante lors d'un backfill. Le collecteur Voice isole la session et
projette au plus cinq tours Humain/IA dans la même limite. Une proposition de nouveau Topic bloque
la suite de ce flux jusqu'à sa résolution humaine, mais uniquement pendant la durée de validité de
l'approbation. Une interaction `PENDING` expirée reste dans l'audit et ne peut plus immobiliser le
salon ni son backlog de messages ; une interaction `PROCESSING` reste bloquante jusqu'à la reprise
de son handler idempotent.
Dans la rotation Dream, le classement d'un message réclamable précède toujours le classement d'une
Task. Cette précédence ne réordonne pas les autres mécanismes entre eux et cesse dès que le
collecteur de messages ne trouve plus de sujet réclamable.

Une Task lancée par un round reçoit immédiatement le Topic et le contact de ce round. L'outil de
création relit la portée persistée au moment de l'effet pour couvrir un classement concurrent. Si
le classement du message ou du tour Voice aboutit seulement après la création, son application met
à jour la Task dérivée dans le même passage ; aucun tour Dream supplémentaire n'est réservé à un
héritage de Task.

L'identité distante exacte observée à l'entrée est projetée en contact Memory puis copiée sur le
message, le round et les Tasks dérivées. Les transports vocaux ne renseignent cette identité que
lorsqu'ils prouvent un unique participant distant. Plusieurs participants ou une identité absente
laissent le contact nul et désactivent la capture de mémoire pour le tour, sans rapprochement
heuristique entre plateformes.

## Où intervenir

- Contrat commun : `back/app/messenger/interface.py`, `models.py`, `facade.py`.
- Réception : `inbound.py`, `journal.py`, `service.py`.
- Contacts observés et rejeu : `contact_memory.py`.
- Session commune : `session.py` et `tests/test_session.py`.
- Recherche d'utilisateurs et routage sortant : `service.py`, `mcp.py`, `router.py`.
- Adaptation : `back/bridge/<transport>/`.
- Transfert de pièces jointes : `back/app/file_share/messenger_transport.py`.
- Référence fichier canonique : `<tool.code>://<room-locator-provider>/<attachment-uuid-local>`,
  résolue par `app.file_share` avec contrôle de la connexion, de la room et de l'agent. Messenger
  reste une capability du Tool et ne possède aucun schéma propre.

Tester séparément le contrat canonique et les fixtures du protocole. Un nouveau transport
doit converger vers `dispatch_incoming` et s’enregistrer avec un `BridgeSpec`.
