---
name: onebot-11
description: Spécification du protocole OneBot v11 — format des événements, des API, des segments de message et des modes de connexion WebSocket. À utiliser pour tout développement impliquant les adapters de messagerie (Napcat, Lagrange, etc.).
---

# OneBot v11 — Référence protocole

OneBot est une spécification d'interface unifiée pour les bots de messagerie. Dans Galaris,
elle connecte des **adapters** comme Napcat ou Lagrange au bridge `bridge.one_bot` par
WebSocket inverse. Le bridge convertit ensuite les événements vers le modèle canonique
`app.messenger`.

## Modes de connexion WebSocket

### WebSocket direct (serveur OneBot)

OneBot expose un serveur WebSocket avec trois chemins :
- `/api` — appels API uniquement
- `/event` — réception d'événements uniquement
- `/` — combiné (API + événements)

### WebSocket inverse (utilisé dans Galaris)

OneBot se connecte **en tant que client** vers le serveur Galaris. C'est le mode utilisé ici.

L'adapter se connecte à : `ws://<host>/ws/onebot/{platform}/{user_id}`

**En-têtes envoyés par l'adapter à la connexion :**
```
X-Self-ID: <bot_user_id>
X-Client-Role: Universal
Authorization: Bearer <ONEBOT_SECRET_KEY>
```

L'adapter tente de se reconnecter automatiquement en cas de déconnexion (intervalle configurable, défaut 3000 ms).

---

## Format des appels API

Pour invoquer une action, envoyer un JSON sur le WebSocket :

```json
{
    "action": "send_private_msg",
    "params": {
        "user_id": "10001000",
        "message": "Bonjour"
    },
    "echo": "mon-id-unique"
}
```

- `action` — nom de l'API à appeler
- `params` — paramètres (peut être omis si aucun)
- `echo` — identifiant optionnel, retourné dans la réponse pour corréler requête/réponse

**Format de réponse :**
```json
{
    "status": "ok",
    "retcode": 0,
    "data": { ... },
    "echo": "mon-id-unique"
}
```

Codes d'erreur : `retcode` 1400 (requête invalide), 1401 (non autorisé), 1403 (interdit), 1404 (non trouvé).

---

## Événements entrants

Tout événement contient ces champs universels :

| Champ | Type | Description |
|-------|------|-------------|
| `time` | int | Timestamp Unix |
| `self_id` | str/int | ID du bot |
| `post_type` | str | `message`, `notice`, `request`, `meta_event` |

### Événement message privé (`post_type: message`, `message_type: private`)

```json
{
    "time": 1700000000,
    "self_id": "12345",
    "post_type": "message",
    "message_type": "private",
    "sub_type": "friend",
    "message_id": "abc123",
    "user_id": "67890",
    "message": "Bonjour",
    "raw_message": "Bonjour",
    "font": 0,
    "sender": {
        "user_id": "67890",
        "nickname": "Alice",
        "sex": "unknown",
        "age": 0
    }
}
```

`sub_type` : `friend`, `group` (message temporaire depuis groupe), `other`

### Événement message de groupe (`post_type: message`, `message_type: group`)

Mêmes champs que le message privé, plus :

| Champ | Type | Description |
|-------|------|-------------|
| `group_id` | str | ID du groupe |
| `anonymous` | object\|null | Infos anonymat si applicable |
| `sender.card` | str | Pseudo dans le groupe |
| `sender.area` | str | Région |
| `sender.level` | str | Niveau membre |
| `sender.role` | str | `owner`, `admin`, `member` |
| `sender.title` | str | Titre spécial |

**Modèles Pydantic du wire format :** `OneBotMessage` et `MessageSender` dans
`back/bridge/one_bot/client.py`. Leur conversion canonique vit dans
`back/bridge/one_bot/messenger.py`.

---

## Segments de message (format array)

`message` peut être une chaîne ou un tableau de segments :

```json
[
    {"type": "text", "data": {"text": "Bonjour "}},
    {"type": "at", "data": {"qq": "67890"}},
    {"type": "image", "data": {"file": "https://example.com/img.jpg"}}
]
```

### Types de segments principaux

| Type | Paramètres clés | Notes |
|------|-----------------|-------|
| `text` | `text` | Texte brut |
| `face` | `id` | Émoticône QQ (ID numérique) |
| `image` | `file`, `type`, `url`, `cache`, `proxy` | Local, URL ou base64 |
| `record` | `file`, `magic`, `url`, `cache`, `proxy` | Message vocal |
| `video` | `file`, `url`, `cache`, `proxy` | Vidéo courte |
| `at` | `qq` | Mention — `"all"` pour @tous |
| `rps` | — | Pierre-feuille-ciseau aléatoire |
| `dice` | — | Dé aléatoire |
| `shake` | — | Secouer |
| `poke` | `type`, `id` | Interaction poke |
| `anonymous` | `ignore` | Message anonyme |
| `share` | `url`, `title`, `content`, `image` | Partage de lien |
| `contact` | `type` (`qq`/`group`), `id` | Recommandation contact/groupe |
| `location` | `lat`, `lon`, `title`, `content` | Localisation |
| `music` | `type` (`qq`/`163`/`xm`/`custom`), `id` | Partage musical |
| `reply` | `id` | Réponse à un message (par ID) |
| `forward` | `id` | Transfert fusionné (reçu) |
| `node` | `id` ou `uin`+`name`+`content` | Nœud de transfert (envoi) |
| `xml` | `data` | Message XML brut |
| `json` | `data` | Message JSON brut |

---

## API publiques de référence

### Messages

| Action | Paramètres principaux | Retour |
|--------|-----------------------|--------|
| `send_private_msg` | `user_id`, `message`, `auto_escape?` | `message_id` |
| `send_group_msg` | `group_id`, `message`, `auto_escape?` | `message_id` |
| `send_msg` | `message_type`, `user_id`/`group_id`, `message` | `message_id` |
| `delete_msg` | `message_id` | — |
| `get_msg` | `message_id` | message complet |
| `get_forward_msg` | `id` | messages fusionnés |

### Groupe

| Action | Paramètres principaux |
|--------|-----------------------|
| `set_group_kick` | `group_id`, `user_id`, `reject_add_request?` |
| `set_group_ban` | `group_id`, `user_id`, `duration?` (0=lever) |
| `set_group_whole_ban` | `group_id`, `enable` |
| `set_group_admin` | `group_id`, `user_id`, `enable` |
| `set_group_card` | `group_id`, `user_id`, `card` |
| `set_group_name` | `group_id`, `group_name` |
| `set_group_leave` | `group_id`, `is_dismiss?` |
| `set_group_special_title` | `group_id`, `user_id`, `special_title`, `duration?` |

### Informations

| Action | Paramètres principaux | Retour |
|--------|-----------------------|--------|
| `get_login_info` | — | `user_id`, `nickname` |
| `get_stranger_info` | `user_id`, `no_cache?` | infos utilisateur |
| `get_friend_list` | — | liste d'amis |
| `get_group_info` | `group_id`, `no_cache?` | infos groupe |
| `get_group_list` | — | liste des groupes |
| `get_group_member_info` | `group_id`, `user_id`, `no_cache?` | infos membre |
| `get_group_member_list` | `group_id` | liste membres |
| `get_group_honor_info` | `group_id`, `type` | honneurs du groupe |

### Système

| Action | Description |
|--------|-------------|
| `get_status` | État du bot (en ligne, stats) |
| `get_version_info` | Version de l'implémentation |
| `set_restart` | Redémarrage asynchrone |
| `clean_cache` | Nettoyage du cache |

---

## Implémentation dans Galaris

- `back/bridge/one_bot/client.py` contient le client bas niveau, `MessengerHub`, le singleton
  `hub` et les modèles du protocole.
- `back/bridge/one_bot/messenger.py` implémente l’interface `app.messenger.Messenger` et les
  conversions entre OneBot et les objets canoniques `Message`, `User` et `Room`.
- `back/bridge/one_bot/router.py` expose le WebSocket inverse, valide le payload et appelle
  `app.messenger.inbound.dispatch_incoming`.
- `back/bridge/one_bot/__init__.py` déclare le `BridgeSpec`, les capacités et l’enregistrement
  auprès de la façade de messagerie.

Le code métier appelle `OneBotMessenger` via le registre canonique. Le client `OneBot` reste
le wrapper protocolaire des actions telles que `send_group_msg`, `get_group_msg_history` ou
`delete_msg`.

### Endpoint WebSocket

```
ws://<host>/ws/onebot/{platform}/{user_id}
Authorization: Bearer <ONEBOT_SECRET_KEY>
```

L'adapter doit s'authentifier avec `MESSENGER_ONE_BOT_SECRET_KEY` ou
`AUTH_WEBHOOK_TOKEN` dans l’en-tête `Authorization: Bearer`. Si
`MESSENGER_ONE_BOT_PLATFORM` est défini, le segment `platform` doit lui correspondre.

---

## Notes d'implémentation spécifiques

- Les `user_id` et `group_id` sont des **strings** dans Galaris (pas des entiers), car certains adapters non-QQ utilisent des IDs alphanumériques.
- `OneBotMessage` utilise `extra = "ignore"` : les champs inconnus des adapters sont silencieusement ignorés.
- `hub.call()` attend la réponse jusqu'à **5 secondes** (timeout configurable). En cas de timeout, retourne `{"status": "failed", "msg": "timeout"}`.
- Si l'adapter n'est pas encore connecté au moment de l'appel, `hub.call()` attend jusqu'à **10 secondes** sa connexion.
