<p align="right"><strong>Français</strong> · <a href="../../en/user/README.md">English</a></p>

# Guide utilisateur et découverte

Pour trouver un écran, consultez le [guide des menus et parcours](navigation.md) et la
[carte de navigation générée](../architecture/generated/navigation.md).

Ce guide s’adresse à une personne qui veut utiliser Galaris sans connaître les modèles de
langage, les API ou Docker. Les écrans accessibles dépendent des droits attribués à votre
compte.

Dans les fenêtres de détail, de formulaire ou de benchmark du Lab, seul le contenu défile :
le titre et sa croix de fermeture restent visibles, même lorsque le contenu est long.

Pour commencer par une vue d’ensemble, consultez le
[tour complet des fonctionnalités](../features.md).

Pour organiser les accès aux agents, consultez [Équipes et autorisations de dialogue](teams.md).

## Galaris, simplement

Un agent Galaris est un collaborateur logiciel avec :

- un prénom obligatoire, un nom de famille facultatif, un rôle et des consignes de comportement ;
- un modèle de langage pour comprendre et rédiger ;
- des outils autorisés pour chercher, lire, créer, envoyer ou lancer un processus ;
- une mémoire gouvernée, des documents de travail et un historique d’activité ;
- un driver d’exécution, c’est-à-dire la manière concrète dont son travail est exécuté.

Galaris est l’orchestrateur autour de ces agents. Il reçoit une demande, choisit un agent,
conserve la tâche, supervise son exécution et restitue le résultat. Un modèle peut se
tromper : l’interface montre donc les étapes, les outils utilisés et les échecs au lieu de
faire croire que toute réponse est forcément une action réussie.

## Première connexion et repères

Ouvrez l’adresse communiquée par votre administrateur, puis connectez-vous avec votre adresse
électronique et votre mot de passe. Si l’inscription libre est affichée, vous pouvez créer un
compte ; cela ne vous accorde pas automatiquement l’accès aux agents ou aux outils.

Sur une instance sans compte, la première inscription crée l’administrateur. Ensuite,
les inscriptions sont fermées par défaut. Le réglage **Préférences → Système → Permettre
aux utilisateurs de créer leur compte** les ouvre immédiatement ; les nouveaux comptes
restent sans droits jusqu’à l’attribution d’un rôle. Sa désactivation ferme le formulaire
et l’API d’inscription, sans empêcher les comptes existants de se connecter.

À la connexion, l’accueil affiche Welcome si la langue par défaut de l’instance, un LLM utilisable
ou un agent manque, même si la langue de votre profil est déjà renseignée. Sans droits de
configuration, le parcours indique les permissions nécessaires. Une fois la langue enregistrée,
l’accueil normal revient si les autres éléments requis sont configurés ; `/welcome` reste accessible.

Le parcours de bienvenue présente sept étapes dans une timeline qui revient à la ligne selon
la largeur disponible, sans défilement horizontal. Sélectionnez une étape pour
afficher son contenu en dessous, ou utilisez **Étape précédente** et **Étape suivante**.
La première étape, **Langue par défaut**, suit la même présentation : si la langue n’est pas
renseignée, un sélecteur permet de la choisir avec les droits de gestion des paramètres ; sinon,
la langue enregistrée est affichée. Le choix est enregistré automatiquement ; la langue du profil
reste prioritaire. Dans les autres étapes, le bouton de configuration ouvre l’écran correspondant
selon vos droits.

La barre latérale ne montre que les écrans autorisés par votre rôle :

| Écran | À quoi il sert |
|---|---|
| Accueil | voir les agents disponibles, les tâches récentes et les étapes de configuration manquantes |
| Agents | connaître le rôle, la personnalité et les capacités de chaque agent |
| Suivi d’exécution | suivre séparément conversations texte, appels, Tasks, processus et appels LLM en temps réel |
| Objectifs | suivre les missions de fond, leurs cycles, preuves et résultats |
| Dossiers thématiques | retrouver les sujets globaux et les connaissances liées entre plusieurs canaux |
| Mémoire | rechercher, lire et corriger les souvenirs privés d’un agent et les synthèses des documents autorisés ; oublier uniquement les souvenirs autonomes |
| Dream | suivre le travail de fond, consulter son historique et gérer l’indexation des fichiers par agent |
| Lab IA | analyser une tâche et mesurer les mécanismes IA sur des jeux de cas reproductibles |
| Processus | lancer et suivre un workflow externe, par exemple n8n |
| Outils | voir les capacités et connexions autorisées ; principalement destiné aux responsables |

Les rubriques LLM, paramètres, utilisateurs et autorisations sont administratives. Leur
absence dans votre menu est normale. Dans **Profil**, choisissez Français ou English ; ce
choix traduit l’interface et devient aussi la langue de référence de vos nouvelles tâches.
Le menu de votre compte permet de changer d’affectation si plusieurs rôles vous ont été
attribués. Les droits visibles changent immédiatement avec le rôle actif.

Le profil permet également d’activer l’authentification à deux facteurs avec une application TOTP.
Conservez les codes de secours affichés lors de l’activation dans un emplacement distinct et sûr :
ils ne seront pas réaffichés et chacun ne fonctionne qu’une fois. Après plusieurs mots de passe ou
codes erronés, Galaris ralentit temporairement les nouvelles tentatives de connexion.

## Installer Galaris sur Android ou iPhone

Galaris est une Progressive Web App (PWA) : il peut être ajouté à l’écran d’accueil et lancé
depuis sa propre icône, comme une application installée depuis un store. Après une première
connexion depuis cette icône, la session est restaurée automatiquement pendant 30 jours
d’inactivité par défaut.

- sur Android, l’installation se fait depuis le menu de Chrome ;
- sur iPhone, elle se fait dans Safari avec **Partager**, puis **Sur l’écran d’accueil**.

L’adresse doit être fournie en HTTPS par l’administrateur. La PWA met en cache son interface,
mais les conversations, tâches et autres données restent en ligne : Galaris n’est pas une
application métier hors connexion.

Le [guide PWA détaillé](pwa.md) décrit l’installation pas à pas, les mises à jour, la sécurité
de la session et les solutions aux problèmes courants.

## Créer sa première tâche dans l’interface

1. Ouvrez **Suivi d’exécution → Tâches**, puis **Nouvelle tâche**.
2. Donnez un libellé court, par exemple « Synthèse des factures de juin ».
3. Choisissez l’agent dont le métier correspond au besoin.
4. Placez la consigne complète dans **Objectif** : résultat attendu, entrées, contraintes et
   vérification souhaitée.
5. Laissez **Mode** et **Effort** sur **Auto** lors d’un premier essai.
6. Cliquez sur **Créer & exécuter**. **Créer** seul enregistre une tâche en pause, utile pour
   préparer ou faire relire la demande avant son lancement.

L’option d’auto-approbation autorise à l’avance certaines actions demandant normalement une
validation. Ne l’activez que si vous comprenez les effets possibles sur les fichiers, messages
ou services externes. Une approbation donnée à un agent n’autorise pas automatiquement les
agents auxquels il délègue.

Depuis la liste, cliquez sur une tâche pour ouvrir son détail. Vous y retrouvez la phase
courante, les sous-tâches, les appels d’outils, les processus liés, les coûts LLM connus et le
retour final. Les boutons de pause et de reprise agissent sur l’arbre de travail. **Forcer la fin**
est une récupération administrative pour une exécution réellement bloquée : elle marque la Task
en erreur et libère sa lease, elle ne constitue pas une annulation ordinaire du travail externe.

Les nouvelles exécutions et les messages des modèles réveillent leur suivi dès leur
enregistrement. Pour une inférence interne, pause et arrêt restent réactifs même si le
fournisseur ne produit plus de texte. Rouvrir le suivi relit les événements enregistrés
sans relancer la génération ; fermer une vue de suivi seule ne l'arrête pas.

Les exécutions sans budget de réponse explicite demandent automatiquement la capacité de
sortie publiée du modèle lorsqu'elle est connue. Aucun réglage n'est nécessaire pour les
modèles déjà configurés. Cela évite les petits plafonds par défaut de certains fournisseurs ;
leur limite physique reste applicable et une réponse coupée ne valide pas la tâche.

Si vous demandez de remplacer une tâche Hermès en cours, le nouveau travail attend la
confirmation de l'arrêt du précédent. Une coupure réseau ou un redémarrage de Galaris ne
déclenche pas automatiquement le remplaçant : la vérification reprend depuis les informations
enregistrées. Une pause que vous avez posée reste active après confirmation. Si l'attente
persiste avec une ancienne instance Hermès, demandez à l'administrateur de vérifier sa mise à jour.

Avec le harnais interne, trois erreurs identiques ou trois appels répétés sans progrès
déclenchent une consigne à l’agent : changer de méthode, relire les skills pertinents ou
vérifier les arguments. L’agent garde ses outils pour poursuivre ; s’il ne peut pas avancer,
il explique les erreurs répétées et ce qui reste bloqué. Les limites globales d’exécution
restent applicables.

Pour un agent Hermès configuré avec son propre fournisseur LLM, la tâche et son résultat
restent visibles, mais Galaris ne peut pas afficher les appels LLM intermédiaires ni leur coût
détaillé. Ce n’est pas une perte de tâche : ces appels ont lieu directement dans Hermès.

## Les trois formes de demande

### Discuter

Posez une question comme à un collègue. Une demande courte et sans action extérieure est
normalement traitée immédiatement en mode `standard`.

Exemple : « Explique-moi la différence entre un devis et une facture. »

### Faire une action

Indiquez le résultat attendu, la cible et les contraintes utiles. Si un outil est requis,
l’agent doit réellement l’appeler ; une simple phrase comme « c’est fait » sans trace
d’outil ne valide pas l’action.

Exemple : « Envoie le compte rendu `reunion.md` dans le salon Projet Alpha. »

### Confier un objectif de fond

Décrivez le livrable final plutôt qu’une conversation étape par étape. Lorsque le driver le
permet et que le travail contient plusieurs unités distinctes, le dispatcher peut demander
au planner de créer un plan durable.

Exemple : « Compare ces trois offres, produis un tableau argumenté, vérifie les totaux et
partage le fichier dans le salon Achats. »

Une tâche planifiée reste un travail fini : elle se termine après la livraison demandée. Un
**objectif durable** est différent : Galaris lance des cycles successifs, évalue les progrès après
chaque cycle et continue jusqu’à réussite ou arrêt explicite.

Lorsqu’une DRH agentique dispose des capacités de gestion correspondantes, vous pouvez lui
demander par exemple :

> Donne à l’agent Commercial l’objectif durable « Structurer le suivi des prospects », avec
> l’agent Direction comme référent, puis indique-moi où il en est.

La DRH peut alors créer l’objectif avec un propriétaire et un référent distincts, lister ou
rechercher les objectifs d’un agent, consulter leur suivi et leurs cycles, les modifier, les
mettre en pause, les reprendre, déclencher un cycle immédiatement, les clôturer ou les supprimer
lorsqu’aucun cycle n’est en cours. Les modifications sensibles utilisent la révision courante de
l’objectif afin de ne pas écraser une évolution concurrente.

La même DRH peut auditer les skills disponibles pour un agent et lire le `SKILL.md` central d’un
skill. Elle ne reçoit ni les scripts, ni les références, ni les autres fichiers du package par ce
tool. Ces capacités spécialisées ne sont accordées à aucun agent par défaut.

### Passer par une messagerie

Dans l’installation par défaut, les skills `galaris-lab` et `galaris-knowledge` sont
bloqués globalement et autorisés individuellement pour le seul agent **Galaris** créé
à l’installation. Les autorisations restent modifiables et les mises à jour conservent
les choix déjà enregistrés.

L'entrée **Messenger** ouvre la messagerie native de Galaris lorsqu'elle est activée et que votre
rôle possède les droits nécessaires. Vous pouvez créer une conversation directe avec un agent, ou
un groupe contenant cet agent et des collègues, rechercher les rooms, suivre les non-lus, répondre,
joindre un fichier, enregistrer une note vocale et démarrer un appel navigateur. Le panneau
**Activité** montre les étapes publiables et les outils du round, jamais le raisonnement privé de
l'agent. Quitter une conversation retire votre accès sans effacer son historique pour les autres
membres.

Avant de sélectionner une conversation, l’accueil de **Discussion** affiche d’abord les
**Conversations récentes** ayant reçu un nouveau message durant les **7 derniers jours**,
de la plus récente à la plus ancienne. Le bouton **+** affiche toutes les conversations,
y compris les anciennes et celles sans message, avec la pagination habituelle. Le bouton
**−** permet de revenir aux conversations récentes. Les agents apparaissent en dessous,
sous **Avec qui souhaitez-vous échanger ?**. Cliquez sur un agent pour ouvrir une nouvelle conversation avec cet agent
présélectionné, puis confirmez son nom et ses préférences. Le nom proposé tient compte de vos
conversations existantes avec cet agent, y compris les archives : si le nom est déjà pris,
Galaris ajoute **(2)**, **(3)**, etc. Vous pouvez modifier ce nom ; sa disponibilité est
revérifiée lors de la création, et un suffixe est ajouté si nécessaire. Les **Conversations récentes**
apparaissent en cartes avec l’agent, les non-lus et la date du dernier message. L’aperçu respecte
votre préférence de confidentialité. Sur cet accueil, la recherche et les filtres restent
visibles : conversations externes, archives et, selon vos droits, vue d’un agent.
Les cartes s’adaptent à la largeur de l’écran et s’affichent sur une colonne sur téléphone.
Les agents et les conversations récentes se chargent par pages de 50. Chaque liste affiche
sa pagination uniquement au-delà de 50 résultats, avec un choix de 10, 20, 50, 100 ou 500
éléments par page. Modifier un filtre ramène les conversations à la première page.

Les rubriques du panneau sont présentées dans l’ordre **Conversations, Documents, Tâches, Processus**.
Elles s’ouvrent automatiquement lorsqu’elles contiennent des éléments et se replient lorsqu’elles
deviennent vides. Vous pouvez les replier manuellement ; une simple actualisation ne les rouvre pas.
Le bouton **+** de l’en-tête **Documents de travail** permet de créer un document, même lorsque
la rubrique est repliée, si vous disposez du droit de modification.

Sur ordinateur, lorsqu’un document est ouvert à côté de la conversation, chaque message
transmet aussi à l’agent la dernière sélection de texte dans ce document, la dernière position
du curseur et un extrait de la zone visible au moment de l’envoi. Vous pouvez sélectionner
un passage, puis écrire « reformule ce passage » sans perdre ce repère en passant au champ
de message. Cela fonctionne en lecture seule, dans le contenu HTML, dans Source et dans les
Datasets JSON. Les extraits longs sont tronqués et accompagnés de la révision du document.
Un changement de document ou de contenu invalide les anciens repères ; fermer le panneau
cesse de transmettre ce contexte. Les zones internes des applications intégrées ne sont pas
inspectées. Les droits de l’agent sur le document restent inchangés.

Dans l’en-tête **Conversations**, le bouton de filtres à gauche du **+** affiche ou masque
le sélecteur **Moi / agents**, la recherche et les cases **conversations externes** et
**conversations archivées**. Cette zone est masquée par défaut ; la masquer conserve les filtres.
Le **+** permet de créer une conversation selon vos droits.
La rubrique **Tâches** conserve les tâches liées aux messages affichés et leurs sous-tâches.
Elle affiche aussi les tâches en cours ou en attente de réponse de l’agent, même créées
ailleurs ou avant les messages visibles, y compris dans une conversation encore vide.
Les tâches en file et les attentes automatiques restent visibles ; les tâches extérieures
terminées ou mises en pause manuellement ne sont pas ajoutées. La liste se met à jour en direct
et un clic ouvre le détail de la tâche, selon vos droits de consultation.

Redemander un travail ne relance pas systématiquement une ancienne tâche échouée. L’agent doit
examiner l’erreur et les résultats partiels : il peut relancer la même tâche si vous le demandez
explicitement ou si la cause de l’échec a été corrigée. Si l’approche ou les instructions doivent
changer, il privilégie une nouvelle tâche tenant compte de l’échec et de vos corrections, sur un
canal autorisant les Tasks. La relance manuelle reste aussi disponible depuis la fiche tâche.

Une conversation native n'ouvre jamais de Task, même si le message le demande explicitement. Elle
peut toutefois lancer un Processus configuré. Pour confier un travail durable à une Task, utilisez
la page Tasks ou un autre canal dont la politique d'admission l'autorise.

Si votre organisation relie Nextcloud Talk, Matrix, OneBot, Telegram ou WhatsApp Business,
adressez votre demande au compte de l’agent dans le salon prévu. Les plateformes configurées
peuvent fonctionner simultanément et la réponse revient par la connexion et la conversation
d’origine. Évitez de relancer plusieurs fois une demande lente : ouvrez plutôt la Task ou le
Processus créé, ou demandez son état.

Les pièces jointes restent des fichiers. Précisez leur nom et l’action attendue : « lis »,
« modifie », « compare », « renvoie » ou « partage ». Pour un fichier volumineux, l’agent peut
le transférer sans charger tout son contenu dans le modèle.

Pour échanger des fichiers avec les agents depuis votre PC, utilisez un dossier Nextcloud
accessible au compte connecté de l’agent, synchronisé ou monté sur votre ordinateur.
Indiquez le dossier et le fichier concernés. Les noms avec accents, espaces, `#`, `?` et `%`
sont conservés. Si vous modifiez le fichier pendant le travail de l’agent, une édition
concurrente est refusée : l’agent doit relire votre version avant de poursuivre.
La recherche peut continuer sur plusieurs pages ; une recherche de contenu signale les fichiers
qu’elle n’a pas pu examiner. La suppression générique porte uniquement sur des fichiers,
jamais sur un dossier entier. Une connexion active mais incomplètement configurée reste inutilisable.

L’agent interprète la demande de renvoi et choisit le fichier et sa destination avant l’envoi.
Le contenu d’un document ouvert à côté du chat sert de contexte ; ses mots ne déclenchent
aucun renvoi automatique. Joindre une image à un document et la renvoyer dans le chat sont
deux demandes distinctes.

### Comprendre les conversations courtes et le travail de fond

Un agent peut consulter l’annuaire des agents pendant une conversation pour identifier un
collègue et son rôle, sans créer de Task. Demander la contribution d’un collègue suit la
politique d’action habituelle et les droits de contact ; lire sa fiche ne le contacte pas.

À l’initialisation, **Console SSH**, **Image**, **Mail** et **Multimédia** ne sont pas
accessibles en mode conversation par défaut. Un administrateur peut autoriser chaque outil
pour les conversations depuis le catalogue des outils. Ce réglage ne change pas leur accès
dans les Tasks ; les mises à jour conservent les choix déjà enregistrés.

Un message reçu n’est plus systématiquement transformé en Task. Le contrôleur conversationnel
agrège les messages arrivés en rafale, reconstruit l’historique utile et prépare une réponse courte.
Lorsqu’un outil doit produire un effet durable ou qu’un travail va prendre du temps, il crée une
Task ou un Processus de fond et vous en donne la référence.

Dans **Suivi d’exécution → Conversations textuelles**, vous pouvez voir les messages traités ou en
attente, les rounds, leurs tentatives, les appels LLM, la livraison et les éventuelles erreurs. Une
réponse entre deux agents est admise seulement lorsqu’une requête fraîche l’attend ; cette garde
évite les boucles automatiques de politesse.

Les détails d'exécution montrent le délai jusqu'au premier texte ou appel d'outil observé,
avec le temps dans les appels LLM et entre ces appels. Pour une Task, la préparation,
l'admission et l'attente avant sa prise en charge restent séparées. « Non mesuré » signifie
que les traces nécessaires manquent ; ces délais serveur ne prouvent pas la livraison.

### Parler à un agent en temps réel

Lorsque Matrix ou Nextcloud Talk et une capacité vocale sont configurés, un agent peut participer
à un appel. Selon la voix choisie sur sa fiche, Galaris utilise soit le pipeline transcription →
agent → synthèse, soit une session audio native à faible latence. Le second mode peut ne conserver
aucune transcription intermédiaire : l’absence de texte dans un tour natif n’indique donc pas une
perte de l’appel.

L’onglet **Appels téléphoniques** montre les appels actifs ou terminés, leurs tours, interruptions,
réponses, appels LLM et erreurs. Un tour vocal peut aussi créer une Task de fond ; celle-ci apparaît
alors dans l’onglet **Tasks** et continue après la fin de l’appel.

### Résumer un audio, une vidéo ou une vidéo YouTube

Si l’agent dispose de l’outil Audio, joignez l’enregistrement puis demandez directement le
livrable attendu, par exemple :

> Transcris `reunion-projet.mp4`, puis résume les sujets discutés, les décisions, les responsables
> et les actions avec leurs échéances. Conserve aussi la transcription complète.

Le même outil accepte directement une URL publique YouTube. Il suffit donc de demander, par
exemple :

> Résume en français cette vidéo, relève ses idées principales et conserve les timestamps utiles :
> `https://www.youtube.com/watch?v=…`

Galaris traite le média comme une ressource volumineuse : il conserve l’URI du Tool d’origine sans
copier ses octets dans la conversation, le matérialise temporairement, extrait sa première piste
audio, ignore la vidéo et normalise le son en MP3 mono 32 kHz à 96 kbit/s. Le modèle de transcription reçoit ce fichier
audio normalisé et Galaris écrit son résultat dans un fichier `.txt`.

Au-delà d’environ 10 minutes, Galaris vous prévient que le traitement sera plus long, découpe le
son en segments, transcrit et résume chaque segment, puis fusionne ces résumés en une synthèse
globale `.summary.md`. L’agent lit cette synthèse courte pour vous répondre ; le verbatim complet
reste disponible sans être chargé intégralement dans son contexte. Si la réunion est extrêmement
longue, plusieurs niveaux de réduction sont appliqués automatiquement.

Pour une URL YouTube, Galaris ne télécharge pas la vidéo et n’utilise pas le modèle de
transcription. Il récupère une piste de sous-titres déjà disponible, en préférant les sous-titres
manuels dans la langue demandée puis en acceptant les sous-titres automatiques ou une autre langue.
Le fichier `youtube-<identifiant>.txt` indique la langue, le caractère manuel ou automatique de la
piste, la source et les timestamps. Une vidéo longue produit aussi
`youtube-<identifiant>.summary.md`, que l’agent utilise pour répondre sans charger tout le texte.

Les URL `youtube.com/watch`, `youtu.be`, `shorts`, `live` et `embed` en HTTPS sont reconnues. La
vidéo doit être publique et proposer des sous-titres accessibles. Une vidéo privée, restreinte ou
sans sous-titres produit une erreur explicite ; Galaris ne télécharge pas automatiquement sa piste
audio comme solution de repli.

Les principaux formats audio et vidéo reconnus par PyAV sont acceptés ; un fichier corrompu,
illisible ou sans piste audio produit une erreur explicite. Vous pouvez préciser la langue de
l’enregistrement, mais la détection automatique reste disponible.

La normalisation réduit fortement la taille d’une vidéo, d’un WAV ou d’un média à haut débit.
Elle ne réduit pas nécessairement la facture du fournisseur de transcription lorsque celui-ci
facture à la durée de l’enregistrement plutôt qu’au volume transmis.

### Analyser une grande source documentaire

Joignez le fichier ou indiquez son URI accessible, puis demandez une analyse avec une question
précise et les références attendues, par exemple :

> Analyse ce rapport par lots, relève les décisions et les chiffres de ses dernières pages,
> indique les pages sources et les parties qui n’ont pas pu être lues.

L’agent peut lancer une analyse documentaire durable, consulter sa progression et sa couverture,
puis demander son arrêt. Les lots terminés sont conservés ; une inférence facturable interrompue
n’est pas relancée automatiquement. Cette analyse appartient au service de modèles, sans apparaître
comme processus métier. L’accès au fichier et sa version restent vérifiés ; déplacer ou modifier
la source pendant le traitement peut invalider les résultats. La couverture indique les unités
fournies au modèle, sans certifier la justesse des réponses. Voir les
[formats et limites de lecture](../dev/document-qualification.md).

### Lancer un processus métier

L’écran **Processus** expose les workflows que l’administrateur a associés à un agent. Ouvrez
une définition, renseignez son entrée JSON puis lancez une exécution. Son statut, sa sortie, ses
événements et les tâches liées restent consultables dans le même écran.

Le rafraîchissement technique des outils ne figure pas dans cet écran. Si l’agent signale
un catalogue partiellement actualisé, demandez-lui de relancer le rafraîchissement pour les
agents indiqués, sans répéter la modification déjà enregistrée.

Une annulation locale ne garantit pas toujours l’arrêt immédiat du moteur externe. Lorsque
l’interface indique que l’exécution distante peut continuer, vérifiez le service cible avant de
relancer le processus.

## Mémoire, documents et dossiers thématiques

La mémoire récente d’une conversation est reconstruite automatiquement. Pour le contexte durable,
Galaris peut injecter avant l’exécution un rappel borné des souvenirs pertinents. Si la recherche
sémantique est indisponible, l’interface indique le repli vers la recherche lexicale.

La fiche d'un souvenir propose une **Temporalité (facultative)**. Renseignez uniquement les
composantes utiles : jour, mois, année, jour de semaine, heure et minute. Les champs vides
restent libres : jour 27 et mois 9 signifient chaque 27 septembre ; ajouter une année limite
la correspondance à cette année. Une date sans heure correspond toute la journée. L'heure 9
sans minute correspond de 9 h à 9 h 59. Le fuseau proposé est celui de l'application et peut
être changé. L'interprétation s'affiche sous les champs ; **Retirer la temporalité** conserve
le souvenir et son contenu.

Les correspondances actuelles ou prochaines enrichissent le contexte des agents, avec les
mêmes droits d'accès. L'anticipation se règle dans **Préférences → Mémoire** (24 heures par
défaut). Le contexte reste borné ; l'agent peut consulter les correspondances supplémentaires
avec `memory_upcoming`. Aucune notification ni expiration du souvenir n'est déclenchée.
Les agents et Dream réservent ces valeurs aux rappels voulus à une date donnée (rendez-vous,
anniversaire, habitude). Une date historique reste dans le texte : elle ne justifie pas à elle
seule une temporalité. Ajouter un ancrage exclut le souvenir du rappel automatique hors période
et lui donne priorité lorsqu'il correspond. Les souvenirs sans date suivent la recherche habituelle.

Dans **Mémoire → Liste**, le filtre temporel est toujours appliqué, dès la première recherche.
Un seul champ date et heure est prérempli avec l'heure actuelle du navigateur. Modifiez-le puis
cliquez sur **Appliquer** pour tester précisément cet instant, sans anticipation ni fuseau à saisir.
La liste réunit deux sélections indépendantes : les souvenirs **sans date** répondant aux filtres
texte, sujet et interlocuteur ; les souvenirs **datés** correspondant à la date cible,
même s'ils ne répondent pas aux autres filtres. Un souvenir daté hors période est exclu.
La date cible figure dans le filtre ; la correspondance figure sur les souvenirs datés.
Le champ est obligatoire et le filtre ne peut pas être désactivé. Cette simulation
utilise les souvenirs, leur validité et les droits actuels ; elle ne reconstitue pas un historique.

La recherche est regroupée dans **Liste** ; les deux onglets sont **Liste** et **Graphe**.
Une requête textuelle utilise le rappel lexical et sémantique, sous les filtres sélectionnés.
La sélection textuelle est bornée à 500 souvenirs sans date. Les correspondances temporelles
s'y ajoutent sans dépendre de cette limite. L'ensemble est paginé et triable sans doublons ;
par défaut, les correspondances temporelles apparaissent en premier.
Un message invite à affiner la recherche si cette sélection est tronquée et signale le repli
sur les mots recherchés si la recherche sémantique est indisponible. Sans texte, la liste
parcourt tous les souvenirs sans date correspondant aux filtres, plus les correspondances temporelles.

En zoomant suffisamment, les fichiers, pièces jointes et documents HTML visibles affichent leur miniature,
plus grande, à la place du carré turquoise. Les aperçus déjà prêts s'affichent en priorité ;
les aperçus manquants sont calculés progressivement. Le nombre d'images s'adapte
aux capacités du client ; les images éloignées sont masquées et conservées en cache pour
le retour à proximité. Une miniature indisponible conserve le carré. Un aperçu obtenu dans
le détail apparaît aussi dans le graphe. Les miniatures gardent leurs proportions dans une
limite de 320 × 320 pixels ; le graphe affiche directement ces images sans les recompresser.
Leur chargement ne déplace pas les nœuds.
Les fichiers audio portent une note de musique dans leur carré turquoise. Les Datasets
conservent leur symbole documentaire.

Un clic sur un nœud ouvre directement sa modale, avec sa nature, sa visibilité, son nombre
d'accès et la date de dernière activité. Les liens du graphe permettent d'ouvrir un voisin ;
les dossiers et conversations ont une modale dédiée à leurs métadonnées et relations.
La fermeture par le bouton ou l'arrière-plan rend le graphe avec son cadrage conservé.

Dans **Graphe**, les branches d'au moins huit éléments reliés exclusivement à la même ancre
sont représentées par cette ancre agrandie et un compteur. Zoomez ou cliquez sur le groupe
pour voir ses éléments. Les boutons **Zoomer** et **Dézoomer** sont utilisables au clavier.
Le dézoom et **Ajuster le graphe à la fenêtre** replient les branches. Jusqu'à 600 items chargés,
le placement initial se stabilise naturellement et se rééquilibre doucement après modification du graphe
pendant au plus 0,7 seconde. Le zoom, le dépliage et la fermeture du détail conservent les positions ; au-delà, les positions
restent fixes pour limiter le calcul. Un clic sur le groupe cadre son ancre.
Les nouveaux nœuds apparaissent progressivement sur place ; cet effet est désactivé
sur les vues denses et lorsque la réduction des animations est demandée.
En vue éloignée, les liens de détail et certains titres s'effacent ; zoomez pour les retrouver. Les nœuds partagés restent
visibles. Les titres sont limités pour éviter les superpositions et se retrouvent au survol
ou à la sélection. La fenêtre reste limitée à 3 000 nœuds ; affinez les filtres pour explorer
d'autres éléments. Le chargement par zone reste prévu.

Un document manipulé avec le même agent reste candidat au rappel même après de nombreux
échanges ordinaires. L'agent retrouve sa référence, son titre et sa révision actuels, sous
réserve des droits courants. Les documents supprimés ou devenus privés sont exclus. Ce
rappel reste borné : fournissez son URI exacte si un ancien document n'est pas retrouvé.

Chaque souvenir autonome reste privé à son agent et affiche ses mots-clés, ses sources et
un libellé dérivé de son contenu. Le document conserve son titre, son contenu complet et ses droits ;
sa fiche mémoire porte une synthèse facultative avec son propre historique. **Ouvrir le document**
permet d’éditer le contenu complet et le partage. La synthèse hérite des droits actuels du document.
La liste se filtre par texte, sujet, interlocuteur et date ; le graphe présente les
souvenirs avec les documents, fichiers, dossiers, contacts et sujets.

Dans **Mémoire**, les comptes autorisés peuvent :

- rechercher les souvenirs d’un agent directement dans Liste ;
- consulter contenu, révisions, provenance, relations et usages ;
- corriger ou archiver un souvenir ordinaire ;
- partager un document en lecture ou édition depuis son éditeur ;
- créer des documents HTML de travail ou des Datasets JSON qui évoluent sur plusieurs Tasks ;
- explorer le graphe sur une période donnée ;
- oublier définitivement un élément, action irréversible réservée aux droits adéquats.

Les fiches Agent, Goals et cycles sont des projections en lecture seule : modifiez leur source
plutôt que leur copie mémoire. Les contacts issus des messageries ne contiennent que l’identité
minimale nécessaire et restent privés à l’agent propriétaire.

Les fiches de fichiers restent vides tant qu'elles n'ont ni notes ni description utile.
Leurs métadonnées techniques (URI, taille, type, date, empreinte) ne remplissent pas la description.

Les **Dossiers thématiques** regroupent les connaissances autour d’un sujet global, même si elles
proviennent de salons, Tasks ou appels différents. Dream effectue ce classement en arrière-plan ;
les comptes autorisés peuvent aussi corriger l’affectation d’un élément. Dream peut consolider des
souvenirs et analyser séparément les résultats de Tasks afin de renforcer des skills propres à
l'agent. Une skill auto-apprise n'est ajoutée aux futures exécutions qu'après avoir atteint les
seuils de preuves et de score configurés ; la page **Skills → Auto-apprises** permet d'en consulter
les preuves et de la suspendre.

## Standard et high

Le niveau d’effort ne désigne pas deux architectures différentes. Le même driver exécute la
tâche, mais Galaris peut sélectionner un modèle plus puissant et appliquer une préparation
supplémentaire.

| Niveau | À privilégier pour | Effet attendu |
|---|---|---|
| `standard` | conversation, recherche simple, opération bornée et déterministe, y compris une action destructive explicitement autorisée | réponse rapide et économique ; garde-fous ordinaires inchangés |
| `high` | ambiguïté réelle, contexte substantiel à reconstruire, diagnostic ou récupération complexe, décisions fortement couplées, création technique ou créative exigeante | modèle d’exécution plus robuste |

Le risque opérationnel ne détermine pas à lui seul l'effort : supprimer un fichier précisément
identifié ou réinitialiser un dépôt exact après autorisation explicite peut rester `standard`. Les
contrôles de portée, confirmations et protections contre les effets destructifs restent applicables
quel que soit le niveau.

Vous pouvez laisser Galaris choisir. Les directives `@standard` et `@high` forcent le niveau
lorsqu’elles sont disponibles dans votre canal. `@exec` et `@plan` forcent la route, mais un
driver qui interdit le planner ne peut pas être contraint à l’utiliser.

Pour un document unique, ses recherches, chapitres et relectures restent dans une même exécution
afin de conserver leur cohérence. Un ensemble de livrables pouvant être validés et repris
séparément peut passer par `PLAN`, même s'ils doivent être traités dans l'ordre et partagent un
suivi commun. Un petit lot mécanique ne nécessite pas à lui seul un plan.

Dans le Chat natif, `@task` placé n’importe où dans le message crée immédiatement une Task durable
avec le texte restant comme objectif, sans appel au LLM de conversation. Pour le harnais interne
Galaris, `@plan` suffit lui aussi à créer la Task et à forcer sa planification, sans ajouter `@task`.
Ces directives se combinent, sans ordre imposé, avec `@standard` et `@high`. `@approve` ne donne
aucun accord. Les actions sensibles utilisent [les autorisations et le mode YOLO](../admin/tool-administration.md). Le Chat
conserve le round et publie aussitôt une confirmation déterministe
dans la room ; le résultat de la Task y sera publié à sa terminaison. Le bouton `@` du composeur
affiche uniquement les directives compatibles avec le driver de l’agent sélectionné.

## Ce qui se passe après l’envoi

1. La demande créée dans cet écran devient une Task durable.
2. Le Dispatcher choisit une exécution directe ou un plan, puis fixe l’effort.
3. Le planner prépare les travaux décomposables.
4. Le driver exécute l’agent avec ses outils autorisés.
5. Galaris enregistre la trace et le résultat, puis reprend les parents éventuels.

Les conversations texte et voix suivent leur propre contrôleur et leur exécuteur configuré. Elles
ne passent pas par le Dispatcher de Tasks ; lorsqu’elles ont besoin d’un travail durable, elles
créent une Task explicitement liée.

## Planner : décomposer un travail coordonné

Le planner découpe uniquement un objectif qui exige plusieurs blocs de travail coordonnés.
Chaque feuille du plan est une vraie tâche. Une étape n’est pas censée « réfléchir » ou
« rédiger la réponse finale » : elle doit produire une partie vérifiable du résultat.

Le découpage privilégié répète le même traitement complet sur des éléments indépendants :
un fichier à traiter donne une tâche qui le lit, le transforme, le vérifie et enregistre son
résultat. Une tâche unique, même complexe, reste entière : ses phases de recherche,
construction et validation ne deviennent pas des sous-tâches. Cela vaut aussi avec `@plan`,
qui choisit l'orchestration sans remplacer le travail demandé par la rédaction d'un plan.

Pour un traitement répété sur de nombreux documents ou enregistrements, le planner peut créer
une collection : Galaris identifie les éléments depuis l'inventaire, puis crée une tâche par
élément, par vagues. « Un workspace après l'autre » conserve cet ordre tout en séparant les
documents. Le total de progression se précise à la découverte de chaque collection. En cas
d'erreur, **Réessayer** sur le plan reprend le travail en échec et conserve les éléments réussis.
Les plans déjà enregistrés ne sont pas redécoupés automatiquement.

Un petit lot mécanique d'au plus cinq éléments connus peut rester une seule tâche, par
exemple renommer trois documents avec les noms fournis. Lire, transformer et vérifier chaque
document reste un traitement par document, même pour un petit lot. Plusieurs cibles ne
suffisent pas, à elles seules, à déclencher le planner.


Ces aides sont activées par driver. Dans la configuration actuelle :

| Driver | Planner |
|---|---:|
| Interne (Pydantic AI) | oui |
| Hermès | non |

Hermès conserve ainsi ses capacités propres sans être enfermé dans un second harnais.

## Quand Galaris pose une question

Si une connexion Mail exige une validation humaine, son responsable désigné reçoit une demande
privée dans le Chat pour chaque mail préparé. Vérifiez les destinataires, l’objet, l’aperçu du
contenu et la liste des pièces jointes, puis choisissez **Autoriser l’envoi** ou **Refuser**.
Le **Journal des mails** présente le contenu complet et le résultat de l’envoi ; il permet aussi
de décider. L’accord concerne uniquement ce mail. Sans réponse, il reste non envoyé ; après
sept jours, utilisez le journal car la demande du Chat a expiré.

Une information essentielle peut manquer : destinataire, fichier, période, autorisation ou
choix irréversible. L’agent doit alors poser une question courte et attendre au lieu de
deviner. Une question est un résultat valide du tour en cours ; répondez dans la même
conversation pour continuer.

Un planner peut également demander une unique série de précisions avant de créer son plan.
Sans réponse avant l’expiration, il reprend avec des hypothèses explicites.

## Lire l’état d’une tâche

| État affiché | Signification pratique |
|---|---|
| Création / dispatch | la demande est en cours de routage |
| Exécution | l’agent travaille ou appelle des outils |
| Plan | Galaris crée ou avance dans les étapes |
| En pause | la tâche attend une réponse, une étape fille ou une reprise |
| Succès | le workflow s’est terminé sans erreur déclarée |
| Erreur | la tentative a échoué ou a été interrompue après les reprises autorisées |

Les onglets **Conversations textuelles** et **Appels téléphoniques** utilisent leurs propres états.
« À jour » signifie que tous les messages connus ont été traités ; « En attente » qu’un nouveau
round peut être réclamé ; « En cours » qu’un contrôleur répond actuellement.

Un succès technique ne garantit pas que le contenu est parfait. Pour une action importante,
vérifiez le livrable, la destination et les outils appelés.

## Écrire une demande fiable

Une bonne demande contient quatre éléments :

1. le résultat final : « produire un CSV », « répondre à Paul », « corriger le document » ;
2. les entrées exactes : période, fichiers, URL, identifiants et destinataires ;
3. les contraintes : langue, format, limites, éléments à ne pas modifier ;
4. le contrôle attendu : totaux vérifiés, fichier partagé, réponse confirmée.

Préférez :

> Analyse les factures de juin dans `/compta/2026-06`, crée `synthese.csv` avec les colonnes
> fournisseur, HT, TVA et TTC, vérifie que HT + TVA = TTC, puis partage le fichier dans le
> salon Comptabilité. Ne modifie pas les fichiers sources.

À :

> Occupe-toi des factures.

## En cas de résultat surprenant

- Vérifiez que le bon agent et le bon salon ont été utilisés.
- Ouvrez le détail de la tâche et regardez les outils réellement appelés.
- Reformulez la cible exacte plutôt que d’ajouter « fais attention ».
- Si l’action peut avoir un effet de bord, demandez une vérification avant répétition.
- Transmettez à l’administrateur l’identifiant de tâche visible dans l’interface ; il permet
  de retrouver les traces sans partager vos secrets.

Ne recopiez jamais une clé API ou un mot de passe dans une conversation. Les secrets se
configurent dans l’administration ou dans l’environnement prévu à cet effet.

## Mesurer la qualité avec le Lab IA

Les comptes autorisés disposent d’un **Lab IA** séparant deux usages : l’analyse complète d’une
Task réelle et les benchmarks reproductibles du Dispatcher, du Planner et des
exécuteurs Task/Conversation/Voice ainsi que des mécanismes Dream/Goal.

Le [guide complet du Lab IA](lab-ai.md) explique comment importer un cas réel, construire une
référence, lancer un modèle candidat, lire la pertinence et étalonner le juge automatique. Un
pourcentage du Lab n’est jamais une preuve suffisante à lui seul : il doit être interprété avec les
dimensions, la couverture, les erreurs et le dataset.

## Connecter un client Codex ou Claude Code externe

Pour sélectionner un usage tel que `profil1/text/high` dans un catalogue commun à
tous les profils, consultez le [guide de l’API par profil](profile-api.md).

Les guides suivants donnent les configurations, l’authentification par jeton API
utilisateur et les commandes de vérification :

- [Codex CLI](codex.md) : `~/.codex/config.toml`, fournisseur Responses sur `/api/profile/openai`.
- [Claude Code](claude-code.md) : `.claude/settings.json`, alias des quatre paliers et catalogue sur `/api/profile/anthropic`.

Les URL restent communes à tous les profils ; le champ `model` porte le sélecteur complet.

Claude Agent peut aussi être choisi directement comme **Moteur des Tasks** dans la fiche d'un
agent. Galaris provisionne alors un conteneur Claude Agent SDK isolé, lui fournit le modèle interne
résolu, les skills et le MCP de cet agent, puis affiche en direct le texte, les appels d'outils,
les appels LLM et le résultat terminal. Aucun compte ni token Anthropic direct n'est nécessaire.

- [Écrire et relier des contenus riches](rich-content.md) : éditeur, liens, images documentaires et historique.
