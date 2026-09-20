---
name: galaris-messaging-bridges
description: Architecture de messagerie Galaris — modèle canonique app.messenger, conversations, journal entrant, capacités, médias et bridges Matrix, Nextcloud Talk, OneBot, Telegram, WhatsApp et voix. À utiliser pour implémenter ou diagnostiquer un message entrant/sortant, une connexion, un bridge ou un média conversationnel.
---

# Maîtriser la messagerie Galaris

## Lire les contrats avant le protocole

Commencer par `docs/fr/architecture/flows/messaging.md`,
`docs/fr/architecture/flows/media-resources.md`, puis `app.messenger.interface` et les tests du
bridge concerné. Charger aussi `onebot-11` pour OneBot.

## Respecter la frontière canonique

- `app.messenger` possède les contrats `Messenger`, `BridgeSpec`, capacités, conversations,
  journal, déduplication, dispatch entrant et déclenchement du workflow Galaris.
- Chaque `bridge.*` possède l’authentification, le transport, le parsing et la traduction de
  son protocole externe.
- Un bridge s’enregistre auprès de la façade canonique et ne crée pas sa propre variante du
  modèle de conversation ou du workflow de tâches.

Le sens entrant doit converger vers la même façade, qu’il parte d’un websocket inverse, d’un
webhook push, d’un polling ou d’une boucle de synchronisation.

## Traiter un message entrant

1. Authentifier et identifier la connexion avant de faire confiance au payload.
2. Normaliser plateforme, compte, conversation, auteur, identifiant externe, texte et médias.
3. Dédupliquer dans la portée correcte, au minimum connexion + identifiant externe.
4. Journaliser la réception et ses transitions pour permettre reprise et diagnostic.
5. Résoudre ou créer la conversation canonique.
6. Normaliser les métadonnées et construire l'URI avec le code exact du Tool d'origine ; ne pas
   remplacer cette identité par une copie locale.
7. Appeler le dispatch `app.messenger`, qui décide de créer ou reprendre une tâche.
8. Accuser réception au protocole seulement selon sa sémantique réelle de livraison.

Tester redelivery, événement dupliqué entre connexions, payload incomplet, secret invalide,
média trop grand et reprise après une erreur transitoire.

## Envoyer un message

Lorsque le résultat demande un contenu rédigé durable à conserver, réviser ou partager,
privilégier un document `document://` pertinent existant lorsque Memory
et les fonctions nécessaires sont disponibles (Memory et File Sharing sont des services système obligatoires).
La conversation porte la discussion et le lien vers ce document, sans entretenir une autre
version dans un fichier `.md` ou `.html`. `memory_sharing` puis `document_share` donnent accès
au destinataire Galaris ; ni le lien ni `document_show` ne changent les droits. Une livraison
externe de fichier conserve son propre contrat et son reçu. Respecter les ACL des ressources
et toute désactivation d'une connexion de messagerie optionnelle.

1. Résoudre la connexion et le bridge enregistrés.
2. Vérifier la capacité demandée (`text`, fichier, voix, réaction, etc.).
3. Convertir le message canonique vers le format externe dans le bridge.
4. Enregistrer identifiant externe, résultat ou erreur sans exposer de secret.

Ne pas simuler une capacité absente. Retourner une erreur de domaine explicite ou choisir un
fallback déclaré par le contrat.

Pour envoyer un fichier, le contrat public reçoit l'URI canonique exacte de la source. La façade
`app.file_share` la matérialise dans un temporaire borné, puis le transport Messenger l'envoie sous
le nom exposé par les métadonnées source. L'appelant passe directement `console://`,
`nextcloud://`, HTTPS, Mail ou l'URI d'une pièce jointe, sans copie locale préalable. Après succès,
le résultat rend l'URI du fichier chez le provider de destination afin que le Working Set conserve
source, destination et reçu de livraison sans ambiguïté.

## Médias et voix

- Ne pas injecter directement une URL ou un chemin externe dans un runtime agentique.
- Télécharger ou décoder avec timeout, limites, validation du type et nom de fichier sûr.
- Matérialiser seulement dans un temporaire serveur borné lorsqu'une bibliothèque exige des
  octets ; ce temporaire n'est jamais exposé comme ressource.
- Exposer une pièce jointe persistée comme
  `<tool.code>://<room-locator-provider>/<attachment-uuid-local>` ; Messenger est une capability,
  jamais un schéma. Le nom visible reste une métadonnée non fiable.
- Le schéma vient exactement du Tool connecté, le locator de room du provider et l'identité du
  fichier de `messenger_files.id`. Ne jamais substituer le kind du bridge ou un code générique.
- Conserver les fichiers dans l'entrée chronologique du message qui les porte. Un message sans
  texte mais avec une pièce jointe reste un message d'historique ; chaque entrée de fichier expose
  au minimum `id`, `uri`, `name`, `mime`, `size` et `kind` aux façades qui sérialisent l'historique.
- Séparer transport audio, transcription et boucle temps réel voix.
- Nettoyer les ressources temporaires et préserver une trace corrélable sans contenu secret.

## Modifier un bridge

Conserver les fixtures de protocole au niveau du bridge et les règles métier au niveau
`app.messenger`. Ajouter un test de contrat canonique commun et un test d’adaptation propre au
transport. Régénérer la cartographie puis lancer `make architecture-check`.
