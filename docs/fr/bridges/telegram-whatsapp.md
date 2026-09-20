<p align="right"><strong>Français</strong> · <a href="../../en/bridges/telegram-whatsapp.md">English</a></p>

# Telegram, WhatsApp Cloud et Matrix

Galaris peut faire fonctionner simultanément tous les bridges configurés d'un agent. Les valeurs
techniques restent `nextcloud_talk`, `matrix`, `one_bot`, `telegram` et `whatsapp`; l'ordre affiché
dans **Préférences → Messagerie** sert seulement à départager des endpoints sans échange antérieur.

La messagerie est activée sur un Tool choisi par l’administrateur. Les secrets propres à un agent
sont enregistrés dans sa connexion à ce Tool et chiffrés comme paramètres `password`. Les valeurs
serveur invariantes sont enregistrées dans l’onglet Messenger du Tool. Le code du Tool est libre et
ne détermine pas le bridge.

## Telegram Bot API

### 1. Créer et configurer le bot

1. Créer le bot auprès de [BotFather](https://t.me/BotFather) et conserver son token.
2. Activer Messenger sur un Tool et sélectionner le bridge `telegram`.
3. Ajouter un paramètre de connexion chiffré au Tool, puis le faire correspondre à `token`.
4. Dans la connexion de chaque agent, renseigner son token BotFather.

Les anciens champs de politique d’accès (`allowed_user_ids`, `allowed_chat_ids`,
`require_group_mention`) restent lus sur les connexions migrées, mais ne font pas partie du
nouveau contrat de correspondance du bridge.

### 2. Exploitation

Le bridge appelle `getMe` lors de la validation de connexion, supprime un éventuel webhook sans
purger les messages, puis utilise `getUpdates` en long polling. L’offset est conservé en base par
connexion et avancé seulement après traitement déterministe de l’update. Les updates trop anciens
sont ignorés selon `MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS`.

Telegram ne donne pas aux bots un historique arbitraire. `messenger_room_history` lit donc le
journal Galaris par lots paginés ; le curseur retourné permet de continuer vers les messages plus
anciens. Les photos, documents, fichiers audio et notes vocales restent référencés à distance et
ne sont téléchargés que par le pipeline de pièces jointes. Les albums sont regroupés sur plusieurs
réponses de polling adjacentes avec une courte fenêtre bornée.

Les réponses texte dépassant 4 096 caractères sont envoyées dans l’ordre en plusieurs messages.
Les erreurs réseau et `retry_after` sont réessayés au maximum trois fois. Une réponse TTS est
convertie en OGG/Opus puis envoyée avec `sendVoice`.

Référence : [Telegram Bot API officielle](https://core.telegram.org/bots/api).

## WhatsApp Business Cloud

Ce bridge cible exclusivement l’API officielle Meta. Il ne connecte pas un compte WhatsApp
personnel et n’utilise ni WhatsApp Web ni Baileys.

### 1. Préparer Meta

1. Créer une application Meta avec le produit WhatsApp et rattacher un WhatsApp Business Account.
2. Créer un utilisateur système et un token permanent disposant des permissions WhatsApp requises.
3. Relever le `phone_number_id`.
4. Choisir un verify token aléatoire et relever le secret exact de l’application Meta.
5. Exposer en HTTPS l’URL publique suivante :

   ```text
   https://galaris.example/api/whatsapp/webhook/<tool_id>
   ```

6. Configurer cette URL et le verify token dans Meta, puis abonner le WABA au champ `messages`.

Dans l’onglet Messenger du Tool, sélectionner `whatsapp`, puis renseigner `app_secret` et
`verify_token`. Dans le schéma de connexion, faire correspondre `access_token` et
`phone_number_id`; chaque connexion d’agent fournit ses propres valeurs.

Les paramètres techniques globaux restent :

```text
MESSENGER_WHATSAPP_GRAPH_URL=https://graph.facebook.com
MESSENGER_WHATSAPP_GRAPH_VERSION=v23.0
MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES=1048576
MESSENGER_WHATSAPP_HTTP_TIMEOUT_S=30
```

La version Graph est volontairement épinglée et doit être montée explicitement après lecture des
notes de migration Meta.

### 2. Connexion d’un agent

Renseigner sur sa connexion WhatsApp :

- `access_token` : token Meta permanent ;
- `phone_number_id` : identifiant du numéro, unique parmi les connexions actives.

Les anciens champs de politique et de template restent lus sur les connexions migrées, sans faire
partie du nouveau mapping d’identité. Les numéros sont normalisés en chiffres. Les logs n’affichent
qu’une empreinte HMAC de l’expéditeur, calculée avec le secret applicatif.

### 3. Sécurité et cycle du webhook

Le `GET` de souscription compare le verify token en temps constant. Chaque `POST` :

1. applique la limite de taille avant et après lecture ;
2. calcule le HMAC SHA-256 sur les octets bruts ;
3. compare `X-Hub-Signature-256` en temps constant ;
4. valide le schéma et route avec `metadata.phone_number_id` ;
5. persiste le `wamid` avant l’acquittement ;
6. ignore sans erreur les doublons déjà journalisés ;
7. met à jour les statuts `sent`, `delivered`, `read` et `failed`.

Le secret, la signature, le token, le contenu audio et les numéros complets ne sont jamais écrits
dans les logs normaux.

### 4. Fenêtre de 24 heures et médias

Une réponse libre ou un média ne peut partir que dans les 24 heures suivant le dernier message de
l’utilisateur. Hors fenêtre :

- le texte utilise `template_name` si celui-ci est configuré ; ce template doit être approuvé et
  accepter un paramètre texte dans son corps ;
- sans template, le bridge retourne une erreur explicite ;
- les médias proactifs nécessitent un template média approuvé, non automatisé par ce bridge.

Images, documents, vidéos et audio locaux sont téléversés sur `/{phone_number_id}/media`, puis
référencés par leur ID dans `/{phone_number_id}/messages`. Les URLs entrantes temporaires sont
résolues et téléchargées avec le token dans un flux borné avant mise en cache. Les notes vocales
TTS sont converties en OGG/Opus et envoyées avec `audio.voice=true`.

Référence : [collection officielle WhatsApp Business Platform de Meta](https://www.postman.com/meta/whatsapp-business-platform/overview).

## Matrix

### 1. Configurer le homeserver et le compte de l’agent

Le Tool sélectionne `matrix` et porte le réglage `homeserver`. Le timeout de sync demeure un
paramètre technique global. Chaque agent utilise sa propre connexion au Tool :

- `user_id` : identifiant complet du bot, par exemple `@agent:example.org` ;
- `token` : token longue durée facultatif ;
- `password` : repli facultatif lorsque le token n’est pas fourni.

Les anciens champs de politique Matrix restent lus sur les connexions migrées, mais ne font pas
partie du nouveau contrat de correspondance.

Les allowlists vides ne retirent pas l’accès aux rooms dont le bot est déjà membre. En revanche,
`auto_join_invites` reste inopérant tant qu’au moins une allowlist explicite n’est pas renseignée.
Lorsque les deux listes existent, la room et l’expéditeur doivent être autorisés. Une invitation
annonçant le chiffrement de la room est toujours refusée.

### 2. Messages, réponses et reprise

La validation de connexion utilise `whoami`. La réception repose sur un unique `/sync` par
connexion, partagé avec les événements d’appel. Son `next_batch` est conservé dans le journal
Galaris et n’avance qu’après admission complète du lot. Une connexion créée avant cette garantie
établit une seule baseline lors de l’upgrade ; une nouvelle connexion traite immédiatement son
premier lot. Un lot rejoué est dédupliqué par l’identifiant d’événement.

Le bridge prend en charge :

- texte, emotes, réponses `m.in_reply_to`, historique et annuaire utilisateurs ;
- images, documents, audio et vidéo référencés par URI `mxc://` ;
- upload streaming borné et download authentifié, avec repli pour les anciens homeservers ;
- notes vocales OGG/Opus envoyées comme `m.audio`, avec le marqueur vocal compris par les clients
  Element.

Les pièces jointes conservent l’URI du Tool Matrix et ne sont téléchargées qu’à la demande dans un
temporaire serveur nettoyé après l’appel. Les noms, tailles annoncées et octets réellement
transférés sont bornés. Les `m.notice` ne créent
jamais de Task afin d’éviter les boucles entre bots. Une édition `m.replace` n’est pas interprétée
comme un nouveau message.

Le bridge ne possède pas les clés Megolm et ne revendique donc pas l’E2EE. Les événements et
fichiers chiffrés sont ignorés à l’entrée ; tout envoi vers une room chiffrée est refusé avant
l’upload ou l’émission pour éviter une fuite en clair. Les DM créés par Galaris utilisent une room
privée non chiffrée et sont enregistrés dans `m.direct`.

Référence : [spécification Matrix Client-Server](https://spec.matrix.org/latest/client-server-api/).

## Notes vocales communes

PyAV est une dépendance directe. La conversion n’appelle aucun binaire `ffmpeg` de l’hôte. Les
limites partagées se trouvent dans la zone avancée de **Préférences → Messagerie** :

```text
MESSENGER_CONTENT_MAX_MB=1000
MESSENGER_VOICE_MAX_DURATION_MINUTES=15
```

Le pipeline entrant existant télécharge la pièce jointe audio puis utilise le modèle de
transcription configuré. L’outil `messenger_send_audio_message` produit le TTS de l’agent et appelle
la capacité native `VOICE_NOTES` de Telegram, WhatsApp ou Matrix ; les autres bridges conservent le
fallback fichier.

## Appels vocaux Matrix

Avec une connexion Matrix active et `VOICE_ENABLED=true`, Matrix est aussi enregistré comme
`CallProvider`, en parallèle des autres fournisseurs vocaux configurés. Le bridge implémente les
événements VoIP v1 `m.call.invite`, `answer`,
`candidates`, `select_answer`, `negotiate`, `reject` et `hangup`, puis échange l’audio WebRTC en PCM
mono 48 kHz avec `app.voice`.

Prérequis :

- le compte bot est membre de la room ;
- la room contient exactement le bot et un interlocuteur ;
- les événements de signalisation ne sont pas chiffrés ;
- le homeserver expose idéalement `/_matrix/client/v3/voip/turnServer` avec des identifiants TURN ;
- l’agent possède une connexion active à l’outil `voice` et un driver compatible voix.

L’auto-réponse respecte `VOICE_AUTO_ANSWER_ENABLED` et la durée de l’invitation. Le flux `/sync`
reste unique : un bus interne diffuse les événements d’appel au transport afin d’éviter deux
consommateurs concurrents du même curseur.

Ce mode couvre les appels Matrix VoIP classiques 1:1. Les rooms chiffrées, Element Call/MatrixRTC
et les appels de groupe ne sont pas pris en charge.

Référence : [spécification Matrix Client-Server — Voice over IP](https://spec.matrix.org/latest/client-server-api/#voice-over-ip).

## Mise à niveau et validation

Après modification de la configuration ou installation initiale :

```text
make upgrade-deps-back
make sync-db
make typecheck
make tests
```

Scénario manuel minimal pour chaque bridge : texte aller-retour, image, document, note vocale
entrante avec transcription, réponse vocale native, redémarrage sans rejeu, expéditeur refusé et
erreur distante sans secret dans les logs. Pour Matrix, lancer ensuite un appel depuis un client
compatible VoIP v1 et vérifier l’auto-réponse, l’audio bidirectionnel, l’interruption et le raccrochage.
