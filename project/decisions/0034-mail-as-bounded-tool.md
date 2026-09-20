# ADR 0034 — Le courriel comme Tool borné, distinct de Messenger

- Statut : Accepted
- Date : 2026-08-14

## Contexte

Les agents doivent administrer une boîte IMAP, envoyer par SMTP et traiter automatiquement les
nouveaux courriels. La réception requiert un polling paramétrable, un curseur durable et une
déduplication résistante aux redémarrages. Créer un scheduler propre au bridge ou contourner
`app.messenger` dupliquerait ces garanties.

## Décision

Le code stable `mail` désigne un Tool intégré non auto-connecté, implémenté par `bridge.mail`.
Une connexion active associe un agent à une boîte. Elle porte son adresse et son mot de passe,
tandis que les paramètres IMAP/SMTP héritent du Tool selon l'ADR 0035.
Les opérations sont des fonctions MCP natives bornées et interdites au chemin conversationnel
court. Une identité de message repose sur `mailbox + UIDVALIDITY + UID`.

La connexion Mail expose aussi une capacité Messenger entrante gérée par le Tool, sans interrupteur
global de canal supplémentaire. Le superviseur canonique lance un polling IMAP toutes les
`poll_interval_s` secondes, 60 par défaut et de 5 à 86 400 secondes. Sa première lecture établit
une baseline sans rejouer les anciens messages. Chaque UID ultérieur traverse le journal entrant
canonique puis est admis directement comme Task, sans round conversationnel. Cette Task reçoit une
référence opaque et doit appeler `mail_get`; le corps externe n’est pas injecté par le listener.

Le résultat libre de la Task n’est jamais envoyé automatiquement à l’expéditeur. Une réponse exige
un appel explicite à un outil `mail_*`, qui conserve les garanties d’idempotence et la mention IA.

Les pièces jointes traversent la façade de l’ADR 0033 avec un schéma `mail://` en lecture seule.
Les envois possèdent une clé d’idempotence durable et une issue explicite ; une issue SMTP ambiguë
n’est jamais rejouée automatiquement. Le MIME sortant reçoit côté serveur une mention bilingue
obligatoire indiquant qu’un agent IA a envoyé le message. Aucun paramètre ni argument MCP ne peut
supprimer cette mention.

Tout expéditeur entrant et tout destinataire d’une soumission confirmée sont observés via la
projection de contact privée de `app.messenger`. Pour Mail, l’adresse validée et normalisée est
l’identité du compte ; la contrainte de source gérée interdit les doublons. Des adresses distinctes
restent des items distincts. Un futur traitement Dream pourra établir des liens entre comptes sans
fusionner les items ni altérer leur provenance. Lorsque la surface d’exécution possède aussi les
fonctions de fichiers nécessaires, l’inventaire MCP ordonne de rechercher ces contacts dans
`memory://` avant un envoi adressé seulement à un nom et interdit de deviner l’adresse.

## Conséquences

- L’activation de la connexion gouverne à la fois les fonctions Mail et son listener de polling.
- `app.messenger` reste l’unique journal et superviseur des entrées, même lorsque la politique Mail
  choisit l’admission directe en Task plutôt qu’une conversation.
- `UIDVALIDITY + UID` constitue le curseur distant ; la contrainte canonique du journal empêche
  qu’un même message redéclenche plusieurs Tasks lors d’un rejeu normal.
- La projection contact est fail-open vis-à-vis du transport : son échec ne transforme jamais un
  envoi SMTP confirmé en échec et un rejeu idempotent peut la réparer.
- Les mots de passe d'application sont couverts en V1 ; OAuth2 et plusieurs comptes par agent
  restent des évolutions séparées.

## Preuves dans le code

`back/bridge/mail/`, `back/app/tools/mandatory_tools.py`,
`back/app/file_share/resource_service.py`, `front/app/connection/` et les tests associés.
