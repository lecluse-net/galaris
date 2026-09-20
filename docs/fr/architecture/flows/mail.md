<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/mail.md">English</a></p>

# Flux du Tool Mail IMAP/SMTP

Le bridge `bridge.mail` adapte une boîte externe aux contrats Tool et Messenger de Galaris.
L’agent invoque des fonctions MCP bornées sur son unique connexion `mail` active ; le listener
canonique interroge aussi l’INBOX et admet chaque nouveau courriel comme une Task dédiée.

```text
Agent / Task
   → fonctions MCP mail_*
   → paramètres effectifs : surcharge de connexion, sinon valeur globale du Tool
   → connexion Mail active de l'agent
   ├── IMAP TLS/STARTTLS : dossiers, recherche, lecture, flags, move, trash
   ├── SMTP TLS/STARTTLS : send, reply, forward
   ├── mail_outbound_deliveries : contenu MIME + enveloppe + validation + issue durable
   ├── app.messenger → Memory : un contact privé par compte observé
   └── app.file_share : pièces jointes mail:// en lecture seule

Connexion Mail active
   → polling IMAP toutes les poll_interval_s
   → curseur durable UIDVALIDITY + UID dans app.messenger
   → journal entrant et déduplication canoniques
   → Task immédiate demandant mail_get sur la référence opaque
```

## Réception et polling

`poll_interval_s` est un paramètre du Tool Mail, configurable globalement et surchargeable par
connexion sauf lorsqu’une valeur globale est imposée. Il vaut 60 secondes par défaut et est borné
entre 5 secondes et 24 heures. La première activation établit une baseline sur `UIDNEXT` sans
transformer l’historique déjà présent en Tasks. Les UID ultérieurs sont traités dans l’ordre
croissant, par lots bornés à 50.

Le curseur persiste `UIDVALIDITY + UID` dans `messenger_listener_state`. Un changement de
`UIDVALIDITY` établit une nouvelle baseline au lieu de rejouer une boîte reconstruite. Chaque
courriel est d’abord journalisé par `app.messenger`, puis admis directement comme Task ; il ne
passe pas par le contrôleur conversationnel court. La Task ne livre pas automatiquement son texte
terminal à l’expéditeur : toute réponse ou mutation exige un appel explicite à `mail_reply`,
`mail_send`, `mail_move`, `mail_set_flags` ou `mail_trash`.

## Identité et contenu entrant

Une référence de message encode de façon opaque le triplet `mailbox + UIDVALIDITY + UID`. Le
bridge refuse la référence lorsque `UIDVALIDITY` a changé, afin de ne jamais agir sur un autre
message après une reconstruction de boîte. Les corps sont paginés dans la réponse MCP, la taille
RFC822 est vérifiée avant le téléchargement complet et le nombre de parties MIME est plafonné.
Le contenu d’un courriel demeure marqué comme externe et non fiable ; il ne constitue jamais une
instruction système pour l’agent.

Après journalisation, l’expéditeur humain est projeté dans Memory avec l’identité canonique
`(mail, adresse normalisée)`. Le nom d’affichage MIME est conservé lorsqu’il existe. La contrainte
unique de la projection rend l’observation idempotente, y compris lorsque deux messages du même
compte arrivent en concurrence.

Une pièce jointe reçoit une URI
`mail://attachment/<message-ref>/<part-id>/<filename>`. Les deux identifiants opaques font foi ; le
nom est seulement descriptif. La façade `file_*` autorise `info`, `list`, `read` et `copy`, mais
refuse create, write, move et delete.

## Envoi et transparence IA

`mail_send`, `mail_reply` et `mail_forward` exigent une clé d’idempotence. La ligne correspondante
est créée avant toute soumission avec l’agent, l’expéditeur, les destinataires, le sujet, les corps,
les métadonnées de pièces jointes et le message MIME final. Elle reste donc consultable après la
suppression d’une connexion ; le MIME brut nécessaire à une validation différée n’est jamais exposé
par l’API d’administration. La ligne est verrouillée avant soumission : un appel concurrent voit
l’état `submitting` au lieu de lancer un deuxième SMTP. Une coupure dont l’issue est inconnue produit
`uncertain` et n’est pas rejouée aveuglément ; le bridge tente seulement une réconciliation par
`Message-ID` dans Envoyés.

Lorsque le paramètre effectif `approval_required` est actif, la première réclamation passe en
`pending_approval` et retourne immédiatement ce reçu à l’agent sans contacter SMTP. Le
`approver_user_id` effectif est figé sur la ligne : seul ce USER authentifié, disposant de l’accès
aux connexions, peut approuver ou rejeter le message. Une approbation verrouille la ligne puis envoie
exactement le MIME persisté ; un rejet est terminal et conserve le motif facultatif. Une modification
ultérieure de la politique de connexion ne réaffecte pas un mail déjà en attente.

Le serveur ajoute toujours, après le contenu fourni par le modèle, la signature suivante dans la
partie texte et son équivalent HTML :

```text
---
Ce message a été envoyé par un agent d'intelligence artificielle via Galaris.
This message was sent by an artificial intelligence agent via Galaris.
```

Cette signature n’est ni un paramètre de connexion ni un argument MCP : un agent ne peut donc pas
la désactiver. `Bcc` est transmis à l’enveloppe SMTP sans être écrit dans les en-têtes MIME.

Une soumission durablement `sent` projette aussi chaque destinataire distinct de `To`, `Cc` et
`Bcc` comme contact privé. Un rejeu idempotent rafraîchit cette projection sans créer de doublon ;
un envoi `error` ou `uncertain` ne crée aucun contact. Deux adresses différentes restent deux
items, même si leur nom d’affichage est identique. Dream pourra ultérieurement les relier à un
même individu par des liens non destructifs, sans fusionner ni réécrire les identités sources.

Quand `mail_send`, `file_search` et `file_read` sont tous autorisés, le registre des Tools demande
automatiquement à l’agent de chercher `memory://` si le destinataire est donné uniquement par son
nom. Une adresse explicitement fournie dans la demande est utilisée telle quelle après validation.
L’agent ne devine jamais une adresse : zéro ou plusieurs correspondances provoquent une demande
de précision. Les deux fonctions de lecture restent dans le scope d’une Task planifiée qui expose
`mail_send`.

## Configuration et sécurité

La connexion saisit uniquement l'adresse de la boîte et un mot de passe commun à IMAP et SMTP.
L'adresse sert aussi d'identifiant auprès des deux serveurs. Hôtes, ports, sécurité, timeouts et
l'intervalle de relève sont configurables globalement sur le Tool ; les limites de pièces jointes
y sont exprimées en Mo puis converties en octets à la frontière du bridge. Une connexion peut les
personnaliser sauf
lorsqu'une valeur est imposée. Tous les paramètres `password`, globaux ou locaux, restent chiffrés
au repos. Seuls TLS implicite et STARTTLS avec validation du certificat sont acceptés. Le formulaire
permet de tester IMAP et SMTP après enregistrement. `approval_required` et `approver_user_id`
suivent la même cascade globale/surcharge locale : la politique peut donc être commune au Tool ou
personnalisée pour la connexion Mail d’un agent. Une politique active sans USER actif est refusée
avant la création du mail. Le Tool n’est pas auto-connecté et reste absent du catalogue d’un agent
tant qu’un administrateur n’a pas créé et activé sa connexion.

La page `/connection/mail`, protégée par `CONNECTION_ACCESS`, affiche en premier les mails
`pending_approval`, puis tout l’historique. Les deux listes utilisent une pagination serveur bornée
à 500, un filtre agent et une recherche sur l’agent, l’expéditeur, les destinataires, le sujet et le
corps. Le détail expose le contenu utile, le reviewer et l’issue SMTP, mais jamais le payload MIME
brut. Son entrée de navigation n’est visible que si au moins une connexion Mail active existe ; le
privilège de page continue d’être vérifié indépendamment. Les routes d’approbation et de rejet
ajoutent une assertion contextuelle : le USER courant doit être le valideur officiel figé sur le
mail, en plus de posséder `CONNECTION_ACCESS`.
