# 0192 — Interactions humaines des processus par messagerie

Statut : accepté — 2026-10-16.

## Décision

La messagerie est l'unique interface d'interaction humaine des processus, y compris pour
fournir des fichiers. Process conserve l'affectation, l'attente et le contrat de données ;
Conversation interprète la contribution dans le contexte des demandes en cours. Messenger
possède le transport, les identités, le journal et le reçu de réponse.

Le lancement demandé par un humain passe également par l'agent depuis le Chat. L'agent
recueille les entrées et fichiers nécessaires puis utilise le contrat de lancement
conversationnel. Les pages Process restent des surfaces d'édition et de suivi ; elles
ne proposent plus de formulaire de lancement manuel. Les API métier restent disponibles
aux agents, aux sous-processus et aux évaluations du Lab.

La boîte et les routes `human-work` sont retirées. Un port injecté au bootstrap évite une
dépendance Process → Messenger qui créerait un cycle supplémentaire. Une outbox bornée
reprend les échecs de livraison. L'identité de tentative sert de clé d'idempotence.

Les demandes nécessitant une interprétation ne sont jamais résolues par la simple arrivée
d'un message. Le contrôleur reçoit les attentes de son participant et dispose d'une lecture
paginée du contrat complet. Il rapproche texte et pièces jointes des résultats attendus,
demande une précision en cas d'ambiguïté et laisse les échanges sans rapport indépendants.
La réponse validée et le reçu Messenger sont persistés dans une seule transaction.
Les doublons ne répètent pas l'achèvement et une réponse tardive ne réouvre pas un run annulé.

Une activité IA peut demander une information avec `process_activity_question`. La personne
est résolue depuis le lanceur humain authentifié ou la conversation ayant lancé le run,
jamais depuis un destinataire proposé par le modèle. L'activité porte l'attente, sans enfant
Task auxiliaire. La Task IA existante utilise la suspension interne `input` puis reprend
avec la réponse ; une pause humaine indépendante reste prioritaire. Les anciennes attentes
inertes sont retirées sans perdre la question ni rouvrir un état terminal.
Le contrat des variables demandées et l'identité de question sont figés avant livraison.
Conversation accepte les valeurs JSON ordinaires et les convertit au contrat typé avant
validation des accès aux fichiers. Le reçu conserve ces valeurs normalisées : un rejeu du
même résultat reste idempotent entre les représentations ordinaires et typées historiques.
Une valeur refusée fournit au modèle un diagnostic actionnable. La réponse et le reçu
Messenger sont atomiques, même si la réponse précède la fin du tour IA. `process_activity_complete` remet ensuite
des valeurs validées à Process ; le texte final du driver ne constitue pas le reçu de données.
Les activités sans données de sortie peuvent produire un message naturel pour la notification.

Les fichiers restent référencés par leur URI canonique de messagerie ; ils ne sont ni copiés
ni matérialisés pour enregistrer la réponse. Le profil d'acteur actuel garde un utilisateur
Galaris actif : les identités externes utilisées pour répondre doivent être reliées à ce compte.

## Vérification

Les intégrations couvrent le destinataire et la portée exacts, les données invalides,
les fichiers seuls, les refus d'accès, les doublons, l'annulation et la reprise de livraison.
Les parcours navigateur répondent depuis le Chat avec le contrôleur réel et un modèle
synthétique. Le test du formulaire retiré ne constitue plus un contrat ; les brouillons
relèvent du compositeur Chat, et la reprise d'enregistrement des tests d'intégration.
Le formulaire de lancement et son test de saisie typée sont retirés. Le codec typé reste
couvert par `test_typed_values.py` ; les parcours d'édition et d'exécution préparent leurs
runs par l'API et conservent la vérification des sauvegardes, résultats et réponses Chat.
