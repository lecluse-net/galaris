<p align="right"><a href="../../fr/bridges/telegram-whatsapp.md">Français</a> · <strong>English</strong></p>

# Telegram, WhatsApp Cloud, and Matrix

Galaris can run all configured bridges of an agent simultaneously. The technical values remain
`nextcloud_talk`, `matrix`, `one_bot`, `telegram`, and `whatsapp`; the order displayed in
**Preferences → Messaging** is used only to break ties between endpoints with no prior exchange.

Messaging is enabled on a Tool chosen by the administrator. Agent-specific secrets are stored in
the agent’s connection to that Tool and encrypted as `password` parameters. Invariant server
values are stored in the Tool’s Messenger tab. The Tool code is unrestricted and does not determine
the bridge.

## Telegram Bot API

### 1. Create and configure the bot

1. Create the bot with [BotFather](https://t.me/BotFather) and retain its token.
2. Enable Messenger on a Tool and select the `telegram` bridge.
3. Add an encrypted connection parameter to the Tool, then map it to `token`.
4. In each agent’s connection, enter its BotFather token.

The old access policy fields (`allowed_user_ids`, `allowed_chat_ids`,
`require_group_mention`) are still read on migrated connections, but are not part of the bridge’s
new matching contract.

### 2. Operation

The bridge calls `getMe` when validating the connection, removes any existing webhook without
purging messages, then uses `getUpdates` with long polling. The offset is stored in the database
per connection and advanced only after deterministic processing of the update. Updates that are too
old are ignored according to `MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS`.

Telegram does not provide bots with arbitrary history. `messenger_room_history` therefore reads the
Galaris log in paginated batches; the returned cursor allows continuing toward older messages.
Photos, documents, audio files, and voice notes remain remotely referenced and are downloaded only
by the attachment pipeline. Albums are grouped across multiple adjacent polling responses within a
short bounded window.

Text responses exceeding 4,096 characters are sent in order as multiple messages. Network errors
and `retry_after` are retried at most three times. A TTS response is converted to OGG/Opus and then
sent with `sendVoice`.

Reference: [Official Telegram Bot API](https://core.telegram.org/bots/api).

## WhatsApp Business Cloud

This bridge targets the official Meta API exclusively. It does not connect a personal WhatsApp
account and uses neither WhatsApp Web nor Baileys.

### 1. Prepare Meta

1. Create a Meta application with the WhatsApp product and associate a WhatsApp Business Account.
2. Create a system user and a permanent token with the required WhatsApp permissions.
3. Record the `phone_number_id`.
4. Choose a random verify token and record the exact Meta application secret.
5. Expose the following public URL over HTTPS:

   ```text
   https://galaris.example/api/whatsapp/webhook/<tool_id>
   ```

6. Configure this URL and the verify token in Meta, then subscribe the WABA to the `messages` field.

In the Tool’s Messenger tab, select `whatsapp`, then enter `app_secret` and
`verify_token`. In the connection schema, map `access_token` and
`phone_number_id`; each agent connection provides its own values.

The global technical parameters remain:

```text
MESSENGER_WHATSAPP_GRAPH_URL=https://graph.facebook.com
MESSENGER_WHATSAPP_GRAPH_VERSION=v23.0
MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES=1048576
MESSENGER_WHATSAPP_HTTP_TIMEOUT_S=30
```

The Graph version is intentionally pinned and must be explicitly upgraded after reviewing Meta’s
migration notes.

### 2. Connect an agent

Enter the following on its WhatsApp connection:

- `access_token`: permanent Meta token;
- `phone_number_id`: number identifier, unique among active connections.

The old policy and template fields are still read on migrated connections, without being part of
the new identity mapping. Numbers are normalized to digits. Logs display only an HMAC fingerprint
of the sender, calculated using the application secret.

### 3. Webhook security and lifecycle

The subscription `GET` compares the verify token in constant time. Each `POST`:

1. applies the size limit before and after reading;
2. calculates the HMAC SHA-256 over the raw bytes;
3. compares `X-Hub-Signature-256` in constant time;
4. validates the schema and routes using `metadata.phone_number_id`;
5. persists the `wamid` before acknowledgment;
6. ignores already logged duplicates without error;
7. updates the `sent`, `delivered`, `read`, and `failed` statuses.

The secret, signature, token, audio content, and complete phone numbers are never written to normal
logs.

### 4. 24-hour window and media

A free-form response or media can be sent only within 24 hours of the user’s last message. Outside
the window:

- text uses `template_name` if configured; this template must be approved and accept a text
  parameter in its body;
- without a template, the bridge returns an explicit error;
- proactive media requires an approved media template, which is not automated by this bridge.

Local images, documents, videos, and audio are uploaded to `/{phone_number_id}/media`, then
referenced by their ID in `/{phone_number_id}/messages`. Temporary incoming URLs are resolved and
downloaded with the token in a bounded stream before being cached. TTS voice notes are converted to
OGG/Opus and sent with `audio.voice=true`.

Reference: [Official Meta WhatsApp Business Platform collection](https://www.postman.com/meta/whatsapp-business-platform/overview).

## Matrix

### 1. Configure the homeserver and the agent account

The Tool selects `matrix` and carries the `homeserver` setting. The sync timeout remains a global
technical parameter. Each agent uses its own connection to the Tool:

- `user_id`: full bot identifier, for example `@agent:example.org`;
- `token`: optional long-lived token;
- `password`: optional fallback when the token is not provided.

The old Matrix policy fields are still read on migrated connections, but are not part of the new
matching contract.

Empty allowlists do not remove access to rooms in which the bot is already a member. However,
`auto_join_invites` remains inoperative until at least one explicit allowlist is populated. When
both lists exist, the room and the sender must be authorized. An invitation announcing room
encryption is always refused.

### 2. Messages, responses, and resumption

Connection validation uses `whoami`. Reception relies on a single `/sync` per connection, shared
with call events. Its `next_batch` is stored in the Galaris log and advances only after the batch
has been fully admitted. A connection created before this guarantee establishes a single baseline
during the upgrade; a new connection processes its first batch immediately. A replayed batch is
deduplicated by event ID.

The bridge supports:

- text, emotes, `m.in_reply_to` responses, history, and user directory;
- images, documents, audio, and video referenced by `mxc://` URIs;
- bounded streaming upload and authenticated download, with fallback for older homeservers;
- OGG/Opus voice notes sent as `m.audio`, with the voice marker understood by Element clients.

Attachments retain the Matrix Tool URI and are downloaded only on demand into a server temporary
file that is cleaned up after the call. Names, advertised sizes, and actually transferred bytes are
bounded. `m.notice` messages never create a Task, to prevent loops between bots. An `m.replace`
edit is not interpreted as a new message.

The bridge does not possess Megolm keys and therefore does not claim E2EE support. Encrypted events
and files are ignored on input; any sending to an encrypted room is refused before upload or
emission to prevent a plaintext leak. DMs created by Galaris use a private, unencrypted room and
are recorded in `m.direct`.

Reference: [Matrix Client-Server specification](https://spec.matrix.org/latest/client-server-api/).

## Common voice notes

PyAV is a direct dependency. Conversion does not call any host `ffmpeg` binary. Shared limits are
located in the advanced area of **Preferences → Messaging**:

```text
MESSENGER_CONTENT_MAX_MB=1000
MESSENGER_VOICE_MAX_DURATION_MINUTES=15
```

The existing incoming pipeline downloads the audio attachment and then uses the configured
transcription model. The `messenger_send_audio_message` tool generates the agent’s TTS and calls
the native `VOICE_NOTES` capability of Telegram, WhatsApp, or Matrix; the other bridges retain the
file fallback.

## Matrix voice calls

With an active Matrix connection and `VOICE_ENABLED=true`, Matrix is also registered as a
`CallProvider`, alongside the other configured voice providers. The bridge implements the v1 VoIP
events `m.call.invite`, `answer`,
`candidates`, `select_answer`, `negotiate`, `reject`, and `hangup`, then exchanges WebRTC audio in
mono 48 kHz PCM with `app.voice`.

Prerequisites:

- the bot account is a member of the room;
- the room contains exactly the bot and one interlocutor;
- signaling events are not encrypted;
- the homeserver ideally exposes `/_matrix/client/v3/voip/turnServer` with TURN credentials;
- the agent has an active connection to the `voice` Tool and a voice-compatible driver.

Auto-answering respects `VOICE_AUTO_ANSWER_ENABLED` and the invitation duration. The `/sync` flow
remains unique: an internal bus broadcasts call events to the transport to avoid two concurrent
consumers of the same cursor.

This mode covers classic 1:1 Matrix VoIP calls. Encrypted rooms, Element Call/MatrixRTC, and group
calls are not supported.

Reference: [Matrix Client-Server specification — Voice over IP](https://spec.matrix.org/latest/client-server-api/#voice-over-ip).

## Upgrade and validation

After changing the configuration or performing the initial installation:

```text
make upgrade-deps-back
make sync-db
make typecheck
make tests
```

Minimal manual scenario for each bridge: round-trip text, image, document, incoming voice note with
transcription, native voice response, restart without replay, rejected sender, and remote error
without a secret in the logs. For Matrix, then place a call from a v1 VoIP-compatible client and
verify auto-answering, bidirectional audio, interruption, and hang-up.
