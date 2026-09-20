# ADR 0003 — Messagerie canonique et bridges

- Statut : Accepted
- Date : 2026-07-18

## Contexte

OneBot, Matrix, Nextcloud Talk, Telegram et WhatsApp diffèrent sur les identités, rooms,
pièces jointes, accusés, polling, webhooks et websockets. Un workflow métier par protocole
rendrait la création de tâches, la déduplication et les réponses incohérentes.

## Décision

`app.messenger` définit les modèles persistés `Message`, `MessengerUser`, `Room`, `File`,
`Attachment`, les contrats de bridge et le dispatch entrant. Chaque `bridge.*` traduit son
protocole en observations privées et s’enregistre auprès de la façade. Tous les messages entrants
convergent vers `dispatch_incoming`, qui ne publie que le `Message` stocké localement.

Le journal durable identifie un message par connexion, identifiant distant et direction. Les
capacités optionnelles sont déclarées et vérifiées avant appel.

## Conséquences

- Un bridge ne crée ni tâche ni conversation selon une règle propre.
- Les redeliveries n’entraînent pas un second effet métier.
- Une fonctionnalité commune se développe dans `app.messenger`; le parsing reste dans le
  bridge.
- Les tests séparent fixtures du protocole et contrat canonique.

## Preuves dans le code

`app.messenger.interface`, `facade`, `inbound`, `journal`, `service` et les packages
`bridge.one_bot`, `bridge.matrix`, `bridge.nextcloud`, `bridge.telegram`,
`bridge.whatsapp`.

Messenger est une capacité déclarative de `app.tools`, indépendante du code du Tool. Un Tool peut
cumuler MCP, File Share et Messenger. Chaque capacité choisit son bridge et ses mappings sans
partager implicitement son URL ni ses identifiants avec les autres.

`bridge.nextcloud` expose Talk vers `app.messenger` et WebDAV/OCS vers `app.file_share`. Ces deux
adaptations peuvent être sélectionnées sur le même Tool tout en utilisant des configurations et
des mappings distincts.
