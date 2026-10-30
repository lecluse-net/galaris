<p align="right"><strong>Français</strong> · <a href="../../en/user/README.md">English</a></p>

# Guide utilisateur et découverte

Ce guide présente Galaris sans prérequis sur les modèles, les API ou Docker. Les écrans
accessibles dépendent des droits de votre compte. Pour une vue d'ensemble, commencez
par le [tour des fonctionnalités](../features.md).

| Votre besoin | Guide |
|---|---|
| Trouver un menu ou un écran | [Navigation et parcours](navigation.md), [carte générée](../architecture/generated/navigation.md) |
| Confier et suivre un travail | [tâches, jalons et reprise](tasks.md) |
| Organiser les contenus rédigés | [Bibliothèque documentaire](documents.md) |
| Écrire, relier, partager et exporter | [Contenus riches](rich-content.md) |
| Gérer des données JSON | [Documents Données](datasets.md) |
| Explorer les emplacements et contacts d'un agent | [Fichiers](files.md) |
| Modifier un dépôt avec un agent | [Éditeur Git conversationnel](code-editor.md) |
| Construire et observer un workflow | [Processus métier internes](internal-processes.md) |
| Organiser les accès aux agents | [Équipes et autorisations de dialogue](teams.md) |

Dans les fenêtres de détail, de formulaire ou de benchmark du Lab, le contenu défile
en conservant le titre et la fermeture accessibles.

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

L’étape LLM ouvre **Fournisseurs & modèles**. Elle n’est franchie que lorsqu’un modèle
conversationnel est associé à un fournisseur actif dont les identifiants requis sont renseignés.
OpenRouter est activé par défaut, mais sa clé API doit être renseignée. Un fournisseur local
qui n’exige pas de clé peut valider l’étape sans clé ; un fournisseur OAuth doit être connecté.
Cette vérification porte sur la configuration enregistrée ; testez la connexion pour vérifier
que les identifiants sont valides.

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
| Suivi d’exécution | suivre séparément conversations texte, appels, tâches, processus et appels LLM en temps réel |
| Objectifs | suivre les missions de fond, leurs cycles, preuves et résultats |
| Dossiers thématiques | retrouver les sujets globaux et les connaissances liées entre plusieurs canaux |
| Mémoire | rechercher, lire et corriger les souvenirs privés d’un agent et les synthèses des documents autorisés ; oublier uniquement les souvenirs autonomes |
| [Fichiers](files.md) | choisir un agent, explorer ses emplacements et répertoires et ouvrir les fichiers ou leurs vues métier ; chargement au défilement |
| Dream | suivre le travail de fond, consulter son historique et gérer l’indexation des fichiers par agent |
| Lab IA | analyser une tâche et mesurer les mécanismes IA sur des jeux de cas reproductibles |
| Processus | construire et suivre un workflow BPMN interne, ou lancer un workflow externe comme n8n |
| Outils | voir les capacités MCP et API REST et les connexions des agents ; principalement destiné aux responsables |

La liste **Outils** s'ouvre sur **Outils personnalisés** ; **Outils internes à Galaris** suit.
Le champ **Outil** d'une connexion regroupe aussi les choix sous **Galaris** et **Personnalisé**.
Dans **Nouvel outil**, activer au moins une capacité pour rendre le bouton **Créer** disponible.

Pour configurer une intégration REST, un responsable active **API** sur le Tool, puis
saisit directement l'adresse dans l'onglet **API REST**. Cette adresse est commune à toutes
les connexions de l'outil. Les identifiants se renseignent dans ses paramètres globaux ou
dans la connexion de l'agent. Les droits de l'API sont ceux du token chez le service tiers. Voir
[l'administration des Tools](../admin/tool-administration.md).

Dans les listes de paramètres des drivers, **Nouveau paramètre…** crée un paramètre et
l'associe automatiquement au champ courant. Enregistrer l'outil pour conserver cet ajout.
La suppression d'un paramètre utilisé demande confirmation ; annuler conserve ses associations.

Pour connecter un compte à un serveur MCP, ouvrir la connexion de l’agent et cliquer sur
**Connecter le compte**. Le fournisseur demande l’accord directement ; Galaris récupère
le token sans saisie technique. OAuth se gère uniquement dans la connexion, jamais dans
le Tool. Chaque connexion possède son autorisation et son bouton de déconnexion.
Le renouvellement des jetons est automatique si le fournisseur le permet. Voir le
[guide des Tools](../admin/tool-administration.md).

Dans **Fournisseurs**, un administrateur peut régler le nombre d'appels LLM simultanés
par connexion. Les conversations vocales puis textuelles ont priorité sur le travail de
fond ; avec une seule place, un appel déjà engagé doit toutefois terminer avant le suivant.

Dans **Rôles & permissions**, les rubriques de privilèges fournies à l’installation sont
traduites dans la langue de l’interface. Les noms personnalisés restent tels que saisis ;
un administrateur peut renommer ou supprimer ces rubriques sans qu’une mise à jour les rétablisse.

Les rubriques LLM, paramètres, utilisateurs et autorisations sont administratives. Leur
absence dans votre menu est normale. Dans **Profil**, choisissez Français, English ou 简体中文 ; ce
choix traduit l’interface et devient aussi la langue de référence de vos nouvelles tâches.
Le menu de votre compte permet de changer d’affectation si plusieurs rôles vous ont été
attribués. Les droits visibles changent immédiatement avec le rôle actif.

Avant la connexion, l'interface suit la langue prise en charge du navigateur : français,
anglais ou chinois. L'anglais reste utilisable si cette langue ne peut pas être chargée.
Après connexion, la préférence de votre profil prend la priorité.

Le profil permet également d’activer l’authentification à deux facteurs avec une application TOTP.
Conservez les codes de secours affichés lors de l’activation dans un emplacement distinct et sûr :
ils ne seront pas réaffichés et chacun ne fonctionne qu’une fois. Après plusieurs mots de passe ou
codes erronés, Galaris ralentit temporairement les nouvelles tentatives de connexion.

## Choisir un profil de secours pour un agent

Les gestionnaires d'agents peuvent choisir un **Profil principal** et un **Profil secondaire
(secours)** dans **Agents → Modifier → Modèles**. Le secondaire est facultatif et sert lors
d'une surcharge ou d'une indisponibilité du fournisseur principal. La conversation ou la
Tâche conserve le travail déjà effectué ; les détails de la bascule apparaissent dans les
journaux d'appels LLM. Une sélection vide dans le secondaire ne remplace pas un usage absent.

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

## Obtenir un premier document accompagné

Sur la page Welcome (`/welcome`), **Réaliser votre première mission** est proposé après la configuration
indispensable, choisissez un agent actif auquel vous avez accès en Discussion, puis une synthèse
de notes, une présentation de projet ou un plan de travail. Les exemples sont fictifs et modifiables.
Le parcours vérifie les droits de création et d’envoi en Discussion, de suivi des tâches et de
lecture des Documents avant de proposer le lancement.
Vérifiez la demande puis cliquez sur **Lancer la mission** ; l’appel utilise vos modèles et leurs coûts.
Galaris prépare une conversation et envoie une demande de tâche durable avec une identité stable.
Un réessai d’envoi réutilise cette identité. Un échec de création de conversation peut nécessiter
de vérifier Discussion avant de recommencer.

Le suivi reste disponible après un retour sur cette page dans le même onglet navigateur. Les
questions, autorisations, pauses et erreurs se traitent dans la discussion ou le suivi habituel.
Le parcours distingue une exécution terminée d’un document associé disponible. Ouvrez le document
pour vérifier son contenu ; un succès technique ne vaut pas validation humaine. Si le document
manque, vérifiez les outils, les accès et le résultat dans la discussion, puis actualisez le suivi.
Ce parcours ne donne aucun droit supplémentaire et n’active aucun outil bloqué.

## Créer sa première tâche dans l’interface

1. Ouvrez **Superviser → Activité → Tâches**, puis **Nouvelle tâche**.
2. Donnez un libellé court, par exemple « Synthèse des factures de juin ».
3. Choisissez l’agent dont le métier correspond au besoin.
4. Placez la consigne complète dans **Objectif** : résultat attendu, entrées, contraintes et
   vérification souhaitée.
5. Laissez **Mode** et **Effort** sur **Auto** lors d’un premier essai.
6. Cliquez sur **Créer & exécuter**. **Créer** seul enregistre une tâche en pause, utile pour
   préparer ou faire relire la demande avant son lancement.

Les fonctions d'outils utilisent leurs règles Actif, Bloqué ou Sur demande. Les accords
ponctuels et permanents ainsi que **Toujours interdire** se traitent dans **Superviser → Permissions**.
Le tableau de bord par agent (`/permissions`) permet de modifier ou retirer les accords et refus ; il n'existe plus de
mode global d'auto-approbation. Un accord reste limité à sa connexion ou son type d'action
et ne donne pas automatiquement les mêmes droits aux agents délégataires.
Le suivi d’une conversation affiche **En attente d’autorisation** pendant la demande
d’accord, sans présenter cette suspension comme une erreur d’exécution.

Depuis la liste, cliquez sur une tâche pour ouvrir son détail. Vous y retrouvez la phase
courante, les sous-tâches, les appels d’outils, les processus liés, les coûts LLM connus et le
retour final. Les boutons de pause et de reprise agissent sur l’arbre de travail. **Forcer la fin**
est une récupération administrative pour une exécution réellement bloquée : elle marque la tâche
en erreur et libère sa lease, elle ne constitue pas une annulation ordinaire du travail externe.

Une erreur fournisseur temporaire dans DeepSeek déclenche une reprise automatique dans la
même session, en conservant le travail déjà enregistré. Les limites de reprise des tâches
s'appliquent ; une action dont le résultat reste incertain exige une réconciliation avant
de continuer. Un texte partiel après erreur ne valide pas la tâche.

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
déclenchent une consigne à l’agent : changer de méthode, relire les compétences pertinentes ou
vérifier les arguments. L’agent garde ses outils pour poursuivre ; s’il ne peut pas avancer,
il explique les erreurs répétées et ce qui reste bloqué. Les limites globales d’exécution
restent applicables.

Avec ce harnais, une erreur d’outil peut rester visible alors que l’agent poursuit le travail : il peut
vérifier l’état, corriger l’appel ou choisir une autre méthode. Une réponse externe en
erreur ne garantit pas qu’une écriture n’a eu aucun effet ; l’agent doit la vérifier avant
de la répéter. Les résultats très longs peuvent être présentés au modèle sous forme
d’aperçu explicitement partiel, avec les informations de pagination disponibles. Cet
aperçu ne signifie ni disparition des données sources, ni réussite de la tâche.

Si l’agent invente un paramètre de premier niveau dans un outil dont le schéma énumère
strictement les paramètres acceptés, Galaris l’ignore et indique à l’agent les paramètres
disponibles dans le résultat. Les objets imbriqués et les schémas composés gardent leur validation. Un paramètre obligatoire manquant ou une valeur
invalide provoque toujours un refus ; l'agent doit corriger son appel. Les outils qui acceptent
des paramètres libres conservent ces paramètres.

Pour un agent Hermès configuré avec son propre fournisseur LLM, la tâche et son résultat
restent visibles, mais Galaris ne peut pas afficher les appels LLM intermédiaires ni leur coût
détaillé. Ce n’est pas une perte de tâche : ces appels ont lieu directement dans Hermès.

Quand un agent délègue une tâche, il vérifie l’accès de son collègue aux documents cités.
Un partage manquant empêche le lancement et indique le destinataire et le droit requis.
Le parent attend les résultats enfants avant de reprendre la consolidation ; des tâches
de même nom restent distinguées par leurs références. Une autorisation traitée depuis
la page des permissions affiche aussi la décision dans Chat.

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

Si un cycle dépend d'un choix humain encore indécidé, l'agent peut poser la question au
référent puis attendre sa réponse. Une décision déjà enregistrée doit être lue dans sa
source ; un fait nécessaire au choix doit être vérifié avant de poser la question.
L'attente ne signifie pas que l'objectif est atteint.

Galaris actualise automatiquement le suivi de l'objectif à la fin du cycle, à partir des
preuves remontées par l'agent. Une livraison demandée reste une action à réaliser avec
les autorisations nécessaires ; le suivi automatique ne la remplace pas.

Dans **Préférences → Instructions**, les personnes autorisées peuvent personnaliser le prompt
de suivi : synthèse de l'état actuel, informations à conserver et décision de poursuite.
La modification s'applique aux prochains jugements. **Revenir au défaut** restaure les
consignes Galaris, qui fusionnent les répétitions sans imposer de cible de longueur.

Lorsqu’une DRH agentique dispose des capacités de gestion correspondantes, vous pouvez lui
demander par exemple :

> Donne à l’agent Commercial l’objectif durable « Structurer le suivi des prospects », avec
> l’agent Direction comme référent, puis indique-moi où il en est.

La DRH peut alors créer l’objectif avec un propriétaire et un référent distincts, lister ou
rechercher les objectifs d’un agent, consulter leur suivi et leurs cycles, les modifier, les
mettre en pause, les reprendre, déclencher un cycle immédiatement, les clôturer ou les supprimer
lorsqu’aucun cycle n’est en cours. Les modifications sensibles utilisent la révision courante de
l’objectif afin de ne pas écraser une évolution concurrente.

Le Tool unique **Compétences** distingue quatre portées serveur : `usage` pour utiliser les
génériques autorisés et ses personnels actifs ; `personal` pour gérer ses propres packages ;
`team` pour gérer aussi les packages des agents de l'une de ses équipes et leurs autorisations
génériques ; `all` pour administrer tout le catalogue et toutes les autorisations. Les écritures
exigent une connexion Compétences active. L'agent ne peut pas augmenter lui-même sa portée.
`skill_read` lit le `SKILL.md` central ; les références et fichiers passent par File Sharing.
Pour demander à un agent de créer sa propre compétence, décrivez la procédure souhaitée :
il crée un `SKILL.md` valide avec `file_create` dans son espace personnel, sans devoir
faire autoriser à l'avance l'URI d'un package qui n'existe pas encore. File Sharing délègue
à Skills, qui vérifie la portée de gestion et active le package pour son seul propriétaire.
Cette création privée n'autorise ni une publication générique ni l'accès aux services décrits
dans la procédure.
Un personnel utilise `galaris://skill/personnal/<agent_id>/<code>/` et reste privé : même un
administrateur ne peut pas l'affecter à un autre agent. Le retrait explicite de propriété
avec révision et identifiant d'opération le transforme en générique, sans activation automatique.
Un rejeu conserve les droits configurés depuis la conversion. Les changements de chargement
s'appliquent à la prochaine exécution ; les instructions déjà chargées restent dans le contexte courant.

Dans les listes **Compétences** et **Compétences personnelles**, le clic gauche sur une ligne ou une carte
ouvre le skill en lecture. Le clic droit ouvre son menu d'actions ; Maj+F10 depuis un bouton
de la ligne ouvre aussi ce menu. Choisissez **Visualiser** pour lire le skill, ses fichiers et références.
Les actions proposées respectent vos droits ; les boutons directs gardent leur action propre.
Avec l'édition des compétences et la gestion globale des agents, **Désactiver pour tous**
masque un générique, y compris système, dans les compétences utilisables de tous les agents,
quelles que soient leurs autorisations. Les fichiers et affectations sont conservés pour la
réactivation ; la gestion MCP reste accessible avec les droits et la vue d'administration.
Avec les droits d'édition des compétences et de gestion globale des agents, **Passer en personnel**
permet de choisir un propriétaire unique pour une compétence non système. La confirmation supprime
toutes ses autorisations individuelles, son activation globale et sa catégorie, puis l'active
uniquement pour ce propriétaire. Les fichiers et le libellé sont conservés. En cas de code déjà
utilisé chez le propriétaire, choisissez un autre code ; aucune compétence n'est écrasée.

Dans **Compétences → Compétences personnelles**, consultez les packages privés possédés par les agents
de votre périmètre de gestion, même lorsque Dream est désactivé. La liste indique le
propriétaire, l'activation, la validité, les fichiers et la dernière modification. Filtrez
par agent ou recherchez un nom/code, puis utilisez **Voir** pour lire le `SKILL.md` et ses
références. La portée se règle dans **Tools → Connexions → modifier la connexion Compétences →
Portée de gestion**, avec `usage`, `personal`, `team` ou `all`. Ce paramètre est propre à
la connexion, sans héritage global ; sa modification demande édition des connexions et
gestion globale des agents. Un agent dans trois équipes peut administrer les agents inclus
dans au moins l'une des trois. Avec le droit d'édition des compétences, la fiche permet
de modifier le libellé et les fichiers texte, d'activer/désactiver le package pour son
propriétaire et de le supprimer après confirmation. Dans le menu d'une ligne ou carte, **Modifier**
ouvre directement la fiche en édition ; **Visualiser** ouvre le contenu en lecture. Le libellé
reste éditable dès l'ouverture, avec le droit d'édition : **Enregistrer** peut le sauvegarder
seul sans modifier les fichiers. **Modifier** rend aussi le contenu éditable et conserve le
libellé déjà saisi. Les fichiers texte utilisent l'éditeur de code avec coloration adaptée
à leur extension. **Enregistrer** sauvegarde alors libellé et contenu ensemble ; **Annuler**
abandonne les modifications. Un conflit de révision
conserve le brouillon : copiez-le si nécessaire, puis fermez et rouvrez la fiche avant de reprendre.
Le champ **Agent propriétaire** utilise la sélection standard des agents de votre périmètre.
Choisissez un autre agent, enregistrez les éventuelles modifications du libellé/contenu, puis
confirmez **Changer de propriétaire**. Le transfert conserve le contenu et active le skill pour
le seul nouveau propriétaire ; l'ancien n'y a plus accès. Un code déjà utilisé chez le destinataire
est refusé sans écrasement : choisissez un autre code dans la confirmation.
Un administrateur global peut **Convertir en compétence générique**, choisir un code libre
et confirmer le retrait de propriété. La conversion n'active le package pour personne ;
sa diffusion se configure ensuite dans la bibliothèque générique. Un réessai de conversion
conserve le même reçu tant que la confirmation reste ouverte. La création personnelle
reste effectuée par l'agent. Les packages personnels ne sont pas partageables.

### Déléguer une administration à un agent

Dans **Tools → Connexions → modifier une connexion → Portée de gestion**,
`tools.management_scope` configure aussi Administration des processus, ToolAdmin,
Gestion des objectifs, Galaris Admin et AgentAdmin. Les niveaux sont `usage` (aucune
administration), `personal` (ses ressources), `team` (agents partageant une équipe
active) et `all` (global). Seul un humain avec édition des connexions et gestion globale
des agents peut changer cette valeur locale. Les autorisations des fonctions restent
nécessaires. Les retraits d'équipe prennent effet dès l'appel suivant.

À sa création, l'assistant **Galaris** reçoit le périmètre global (`all`) sur toutes
ses connexions intégrées proposant une portée : Galaris Admin, ToolAdmin, AgentAdmin,
Administration des processus, Gestion des objectifs, Compétences et Chat. Ces connexions
sont actives. Les synchronisations suivantes conservent vos restrictions et désactivations ;
un assistant déjà initialisé se configure dans le formulaire de chaque connexion.

ToolAdmin limite les niveaux personnel et équipe aux connexions ; les définitions et
réglages partagés exigent `all`. Les définitions de processus suivent l'agent affecté,
les exécutions leur lanceur et les objectifs leur responsable. Galaris Admin applique
la portée aux tâches, conversations et traces LLM sans élargir les droits des documents
ou souvenirs privés.

AgentAdmin propose seulement `usage`, `team`, `all`. Il permet la création dans une
équipe explicitement choisie de l'appelant, sous les droits du responsable humain.
Même au niveau global, un agent ne peut s'administrer lui-même ni modifier son propre
titre ou équipe par une mutation partagée. Les délégations restent humaines.

Une connexion inactive ou sans portée explicite n'accorde aucune administration.
Après mise à jour, configurez les anciennes connexions administratives dépourvues de
ce paramètre : leur activation seule ne donne plus accès à toutes les données.

### Passer par une messagerie

Les messages d'un cycle d'objectif utilisent la messagerie choisie pour son référent. Garder
Nextcloud Talk actif ne détourne donc pas les messages d'un objectif rattaché au chat interne.
Pour un envoi sans canal fixé, Galaris reprend le dernier échange entrant avec le destinataire,
puis choisit le chat interne par défaut. L'agent peut demander explicitement un autre canal.

Dans **Tools → Connexions → modifier la connexion de messagerie**, un gestionnaire global
peut régler **Communication inter-agents** (`tools.management_scope`) : **Aucune** (`none`),
**Agents de ses équipes** (`team`) ou **Tous les agents** (`all`). Le défaut `team` conserve
les échanges entre agents partageant au moins une équipe. Ce réglage s'applique aux envois et
aux réceptions de la connexion ; il ne change pas les droits de contact avec les humains.
Les demandes internes vérifient les connexions des deux agents avant de créer une tâche.

Lorsqu'une tâche doit solliciter un autre agent par le canal interne, elle lui crée une demande
suivie et attend son résultat, sans nécessiter de conversation avec un humain. Vous pouvez suivre
la demande par son lien tâche. Son acceptation ne confirme ni une réponse du collègue ni
l'accomplissement de l'action demandée ; les droits de contact et de partage restent nécessaires.

Dans l’installation par défaut, les compétences `galaris-lab` et `galaris-knowledge` sont
bloquées globalement et autorisées individuellement pour le seul agent **Galaris** créé
à l’installation. Les autorisations restent modifiables et les mises à jour conservent
les choix déjà enregistrés.

L'entrée **Messenger** ouvre la messagerie native de Galaris lorsqu'elle est activée et que votre
rôle possède les droits nécessaires. Vous pouvez créer des conversations directes distinctes avec
un agent, rechercher les rooms, suivre les non-lus, répondre, joindre un fichier, enregistrer une
note vocale et démarrer un appel navigateur. Le panneau **Activité** montre les étapes et outils
publiables du round. Archiver une conversation la retire de la liste courante sans effacer son
historique ; vous pouvez la retrouver dans les archives. La création de groupes et la gestion
des participants ne sont pas proposées dans la messagerie interne.

Sur Android, y compris dans la PWA installée, utilisez les boutons physiques du téléphone
pour régler le volume système pendant l’appel. Galaris conserve la lecture Web Audio et
la réduction d’écho ; la sortie est ouverte après l’activation du microphone pour suivre
le mode conversation d’Android. Il n’y a plus de réglage de volume dans Galaris et les anciens
réglages locaux ne sont plus appliqués. Si la lecture est bloquée, touchez **Activer le son**.
Le routage effectif du volume et le profil Bluetooth restent gérés par Android et le navigateur.

Changer de conversation met son adresse à jour dans le navigateur. Les boutons **Précédent**
et **Suivant** retrouvent les conversations visitées ; un retour avant la première ouverture
retrouve l’accueil du Chat. Sélectionner à nouveau la conversation courante n’ajoute pas de
visite. Le document ouvert est sauvegardé avant le changement ; si la sauvegarde échoue,
la conversation et le brouillon restent affichés.

Le texte et les pièces jointes sélectionnées restent dans la saisie tant que l’envoi n’est
pas confirmé. Après une erreur, vous pouvez réessayer sans les ressaisir ; un réessai
inchangé conserve l’identifiant du message pour éviter une seconde admission si le premier
envoi avait déjà été reçu. Après confirmation, un rafraîchissement lent ou indisponible du
fil ne bloque pas l’envoi suivant ni la sélection des pièces jointes. Ces brouillons restent
en mémoire dans la page : rechargez-la seulement après avoir conservé le contenu non envoyé.

Dans les messages, cliquer sur la carte d’une tâche, d’un contact, d’un objectif, d’un
thème ou d’une conversation ouvre sa modale habituelle. Cela fonctionne aussi pour les
ressources ajoutées comme PJ internes. Les droits de consultation et d’édition restent applicables.

Après l'admission de votre message, « Réflexion en cours » apparaît dès que le
round en attente est reçu par l'interface, avant ses premiers fragments. Une
réponse déjà en cours reste affichée si vous envoyez une nouvelle demande.

Dans une discussion native, les petits boutons à côté de « Réflexion en cours » donnent
la main sur cette réponse : **Pause** conserve l’avancement, **Reprendre** continue depuis
ce point et **Stop** retire la réponse de l’agent du round, y compris son texte provisoire.
Votre message reste visible. **Répondre maintenant** demande une réponse avec les éléments
disponibles, sans nouveaux outils. Un outil déjà engagé termine avant l’arrêt ; les actions
accomplies ne sont pas annulées. Une reprise dont les effets précédents sont incertains est
refusée. Une réponse en pause reste visible après réouverture ; une réponse arrêtée reste
absente, et vous pouvez envoyer une nouvelle demande. Ces commandes visent
la réponse conversationnelle ; les tâches et processus de fond ont leurs propres commandes.

Avant de sélectionner une conversation, l’accueil de **Discussion** affiche d’abord les
**Conversations**, avec la même liste que la rubrique **Conversations** de la fenêtre de chat,
y compris les anciennes et celles sans message, avec la pagination habituelle.
Les agents apparaissent en dessous,
sous **Avec qui souhaitez-vous échanger ?**. Cliquez sur un agent pour ouvrir une nouvelle conversation avec cet agent
présélectionné, puis confirmez son nom et ses préférences. Le nom proposé tient compte de vos
conversations existantes avec cet agent, y compris les archives : si le nom est déjà pris,
Galaris ajoute **(2)**, **(3)**, etc. Vous pouvez modifier ce nom ; sa disponibilité est
revérifiée lors de la création, et un suffixe est ajouté si nécessaire. Les **Conversations**
apparaissent en cartes avec l’agent, les non-lus et la date du dernier message. L’aperçu respecte
votre préférence de confidentialité. Sur cet accueil, la recherche et les filtres restent
visibles : conversations externes, archives et, selon vos droits, vue d’un agent.
Les cartes s’adaptent à la largeur de l’écran et s’affichent sur une colonne sur téléphone.
Les agents et les conversations se chargent par pages de 50. Chaque liste affiche
sa pagination uniquement au-delà de 50 résultats, avec un choix de 10, 20, 50, 100 ou 500
éléments par page. Modifier un filtre ramène les conversations à la première page.

Les rubriques du panneau sont présentées dans l’ordre **Conversations, Documents, Tâches, Processus**.
Elles s’ouvrent automatiquement lorsqu’elles contiennent des éléments et se replient lorsqu’elles
deviennent vides. Vous pouvez les replier manuellement ; une simple actualisation ne les rouvre pas.
La loupe de l’en-tête **Documents** permet de rechercher un document accessible.
La cloche de la conversation ouvre un menu pour activer ou désactiver les notifications
sur cet appareil et couper ou rétablir celles de la conversation.
La conversation effectivement affichée reste silencieuse, qu'elle soit ouverte dans
Discussion ou Documents : ni son, ni toast, ni push système. L'ouverture d'une conversation
ferme aussi ses notifications déjà présentes. Les messages visibles sont marqués lus ;
les messages des autres conversations continuent de notifier selon vos préférences.
Le bouton **+** du même en-tête permet de créer un document, même lorsque
la rubrique est repliée, si vous disposez du droit de modification.

Sur ordinateur, lorsqu’un document est ouvert à côté de la conversation, chaque message
transmet aussi à l’agent la dernière sélection de texte dans ce document, la dernière position
du curseur et un extrait de la zone visible au moment de l’envoi. Vous pouvez sélectionner
un passage à la souris ou au clavier, puis écrire « reformule ce passage » sans perdre ce
repère en passant au champ de message. Le même mécanisme s'applique depuis la page Documents,
sur ordinateur et mobile. Le contexte comprend l'UUID, la révision sauvegardée du document
et les positions de début et de fin dans le texte affiché. Cela fonctionne aussi en lecture
seule. Les jeux de données ont leur propre éditeur. Les extraits longs sont tronqués.
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
canal autorisant les tâches. La relance manuelle reste aussi disponible depuis la fiche tâche.

Une conversation native n'ouvre jamais de tâche, même si le message le demande explicitement. Elle
peut toutefois lancer un Processus configuré. Pour confier un travail durable à une tâche, utilisez
la page tâches ou un autre canal dont la politique d'admission l'autorise.

Si votre organisation relie Nextcloud Talk, Matrix, OneBot, Telegram ou WhatsApp Business,
adressez votre demande au compte de l’agent dans le salon prévu. Les plateformes configurées
peuvent fonctionner simultanément et la réponse revient par la connexion et la conversation
d’origine. Évitez de relancer plusieurs fois une demande lente : ouvrez plutôt la tâche ou le
Processus créé, ou demandez son état.

Les pièces jointes restent des fichiers. Précisez leur nom et l’action attendue : « lis »,
« modifie », « compare », « renvoie » ou « partage ». Pour un fichier volumineux, l’agent peut
le transférer sans charger tout son contenu dans le modèle.

Dans une discussion interne modifiable, **Renommer** change le nom d’une pièce jointe,
avant ou après son envoi. Dans un Document, la même action est disponible sur ses pièces
jointes si vous pouvez le modifier. Le nom complet inclut l’extension ; les liens et le
contenu du fichier sont conservés. Fermer le formulaire sans valider abandonne la saisie.

Pour échanger des fichiers avec les agents depuis votre PC, utilisez un dossier Nextcloud
accessible au compte connecté de l’agent, synchronisé ou monté sur votre ordinateur.
Indiquez le dossier et le fichier concernés. Les noms avec accents, espaces, `#`, `?` et `%`
sont conservés. Si vous modifiez le fichier pendant le travail de l’agent, une édition
concurrente est refusée : l’agent doit relire votre version avant de poursuivre.
La recherche peut continuer sur plusieurs pages ; une recherche de contenu signale les fichiers
qu’elle n’a pas pu examiner. La suppression générique porte uniquement sur des fichiers,
jamais sur un dossier entier. Une connexion active mais incomplètement configurée reste inutilisable.

Les partages Samba et Windows sont aussi accessibles avec le bridge **Samba / SMB 2–3**.
Consultez le [parcours de configuration et d'utilisation Samba](samba.md) pour connecter
un partage et manipuler ses fichiers avec les mêmes fonctions de Partage de fichiers.

L’agent interprète la demande de renvoi et choisit le fichier et sa destination avant l’envoi.
Le contenu d’un document ouvert à côté du chat sert de contexte ; ses mots ne déclenchent
aucun renvoi automatique. Joindre une image à un document et la renvoyer dans le chat sont
deux demandes distinctes.

### Comprendre les conversations courtes et le travail de fond

Pendant une mise à jour ou un redémarrage, une conversation en cours reprend automatiquement
à partir de ses informations enregistrées. Vous n'avez pas à renvoyer le message. Les actions
confirmées sont conservées et les interruptions ne consomment pas les essais réservés aux
erreurs. Si une action externe ou une livraison reste incertaine, le suivi le signale pour
vérification avant de la répéter.

Un agent peut consulter l’annuaire des agents pendant une conversation pour identifier un
collègue et son rôle, sans créer de tâche. Demander la contribution d’un collègue suit la
politique d’action habituelle et les droits de contact ; lire sa fiche ne le contacte pas.

À l’initialisation, **Console SSH**, **Image**, **Mail** et **Multimédia** ne sont pas
accessibles en mode conversation par défaut. Un administrateur peut autoriser chaque outil
pour les conversations depuis le catalogue des outils. Ce réglage ne change pas leur accès
dans les tâches ; les mises à jour conservent les choix déjà enregistrés.

Si une tâche attend votre accord pour lire un mail, répondez à la demande d’autorisation.
Le harnais reprend la lecture du même message après la reprise de la tâche ; un refus
laisse son contenu privé. Cet accord de lecture n’autorise pas l’envoi d’un mail.
Pour consulter vous-même la boîte d’un agent, ouvrez **Connaissances → Fichiers → Mail**,
puis un dossier IMAP et un message. Cette lecture ne donne aucun accord de traitement à l’agent.

La consultation d'une compétence déjà disponible dans le harnais DeepSeek ne demande pas
d'accord de modification. Les opérations qui modifient des fichiers conservent leur autorisation.

Un message reçu n’est plus systématiquement transformé en tâche. Le contrôleur conversationnel
agrège les messages arrivés en rafale, reconstruit l’historique utile et prépare une réponse courte.
Lorsqu’un outil doit produire un effet durable ou qu’un travail va prendre du temps, il crée une
Tâche ou un Processus de fond et vous en donne la référence.

Dans **Superviser → Activité → Conversations textuelles**, vous pouvez voir les messages traités ou en
attente, les rounds, leurs tentatives, les appels LLM, la livraison et les éventuelles erreurs. Une
réponse entre deux agents est admise seulement lorsqu’une requête fraîche l’attend ; cette garde
évite les boucles automatiques de politesse.

Les détails d'exécution montrent le délai jusqu'au premier texte ou appel d'outil observé,
avec le temps dans les appels LLM et entre ces appels. Pour une tâche, la préparation,
l'admission et l'attente avant sa prise en charge restent séparées. « Non mesuré » signifie
que les traces nécessaires manquent ; ces délais serveur ne prouvent pas la livraison.

### Parler à un agent en temps réel

Lorsque Matrix ou Nextcloud Talk et une capacité vocale sont configurés, un agent peut participer
à un appel. Selon la voix choisie sur sa fiche, Galaris utilise soit le pipeline transcription →
agent → synthèse, soit une session audio native à faible latence. Le second mode peut ne conserver
aucune transcription intermédiaire : l’absence de texte dans un tour natif n’indique donc pas une
perte de l’appel.

Le raccrochage par l’agent (`voice_call_stop`) est actif par défaut, sans demande
d’autorisation supplémentaire. Pour modifier une règle déjà enregistrée, ouvrez
**Outils → Autorisations**, sélectionnez la connexion **Voice**, recherchez
`voice_call_stop`, puis choisissez **Actif** pour cette connexion ou au niveau
**Global (tous)**. Les choix explicites **Sur demande** et **Bloqué** restent prioritaires
sur le défaut logiciel. Une demande d’accord propose aussi **Toujours autoriser cette
fonction**, limité à la connexion concernée.

Dans le mode transcription → agent → synthèse, l'écoute reste active pendant la
transcription : vous pouvez reprendre la parole sans attendre son résultat. La détection
locale de parole limite les déclenchements dus au bruit et conserve les pauses naturelles.
Une transcription vide ne crée pas de message ni de réponse de l'agent.
Si un bruit déclenche malgré tout une détection pendant la lecture, celle-ci se
met en pause. Sans texte transcrit, elle reprend à l'endroit interrompu. Une
transcription finale non vide arrête l'ancienne lecture et déclenche la réponse
au nouveau message.

Dans le chat, une bulle **Écoute en cours** apparaît dès la détection de parole.
Avec un modèle de transcription temps réel tel que Scribe v2 Realtime, son texte
se met à jour pendant que vous parlez. Sinon, le texte apparaît d'un bloc lorsque
la transcription est prête. La bulle est remplacée par le message définitif.

L’onglet **Appels téléphoniques** montre les appels actifs ou terminés, leurs tours, interruptions,
réponses, appels LLM et erreurs. Un tour vocal peut aussi créer une tâche de fond ; celle-ci apparaît
alors dans l’onglet **tâches** et continue après la fin de l’appel.

### Résumer un audio, une vidéo ou une vidéo YouTube

Dans le détail d'un tour de l'onglet **Appels téléphoniques**, les gestionnaires disposant
du droit de modification des tâches peuvent **Raccrocher de force** un traitement audio.
La confirmation conserve l'historique ; un arrêt encore en cours reste signalé.
Lors d'une suppression, le tour reste affiché tant que le nettoyage audio n'est pas
achevé. Le suivi reprend après réouverture et traverse les indisponibilités temporaires.

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

Pour un tableau, un montant ou une citation importante, demandez les pages et vérifiez-les
dans le fichier d'origine, même si toutes les pages sont couvertes. Les pièces contenues
dans un courriel EML ou une archive ne sont pas analysées récursivement : joignez séparément
les fichiers à examiner.

### Lancer un processus métier

La page **Processus** réunit workflows BPMN internes et workflows externes, dont n8n.
Demandez à l'agent de lancer le processus avec les informations et fichiers nécessaires.
Pour un processus interne, les pages servent à l'édition et au suivi ; le lancement passe
par le Chat, sans formulaire de lancement manuel. Les activités humaines vous sollicitent
dans la messagerie et leur réponse poursuit le run existant.

Pour demander l'ajout d'un fichier à une exécution compatible, indiquez l'URI du run
et le fichier souhaité. L'agent retrouve sa collection de pièces jointes à partir du run
autorisé ; les droits du processus et l'état de l'exécution restent applicables.

Le [guide des processus internes](internal-processes.md) détaille acteurs, variables,
branches, données du run et contrôles. Pour préparer un logiciel externe, l'administrateur
utilise le [guide des moteurs](../dev/process-engines.md).

Le rafraîchissement technique des outils ne figure pas dans cet écran. Si l’agent signale
un catalogue partiellement actualisé, demandez-lui de relancer le rafraîchissement pour les
agents indiqués, sans répéter la modification déjà enregistrée.

Une annulation locale ne garantit pas toujours l’arrêt immédiat du moteur externe. Lorsque
l’interface indique que l’exécution distante peut continuer, vérifiez le service cible avant de
relancer le processus.

## Mémoire, documents et dossiers thématiques

Les souvenirs produits par les agents contiennent chacun un fait structuré : par exemple,
un lien vers le contact, la propriété `langue_preferee` et la valeur `fr`. Les indications
sur l'auteur et l'origine restent séparées. Les emails, téléphones, adresses et identifiants
de messagerie vont dans **Contacts** ; les fiches restent recherchables par les agents.
Les fiches représentant directement une ressource se gèrent depuis cette ressource.
Un souvenir ordinaire lié à cette fiche reste supprimable dans Mémoire.

Dans une conversation, « mon email » désigne la fiche du correspondant identifié. Un simple
« oui » ou « merci » ne fait pas perdre la personne évoquée avant une relance. Vous pouvez
aussi citer directement un lien `document://` ou `memory://` dans une phrase ; il reste pris
en compte même après un long préambule, toujours avec les droits actuels de l'agent.

Les PJ déposées dans Documents et Chat utilisent le stockage interne partagé. Leurs liens
existants et leurs droits restent valables après migration. Un agent peut aussi créer un
fichier privé indépendant via `file_create` avec `path="file://"` et un nom intelligible.
Une référence externe, par exemple Nextcloud, conserve son fournisseur et n'est pas rapatriée
par la migration. Voir le [stockage et les sauvegardes](../dev/file-storage.md).

Pour personnaliser l’icône d’un document, cliquez sur celle de son en-tête dans l’éditeur.
Dans la liste et l’arbre, cliquer sur l’icône ouvre simplement le document.
Pour un dossier, ouvrez sa palette d’icônes. Utilisez le
bouton **+** pour téléverser une image, dans les documents Texte comme Données : SVG,
PNG, JPEG, GIF, WebP, AVIF, BMP ou ICO. Les autres formats reconnus, comme TIFF,
sont convertis en PNG. Les icônes n’ont pas de limite de taille de fichier propre.
Les SVG contenant des scripts, du contenu externe ou des feuilles de style restent refusés.
Un échec d’import ou d’enregistrement reste affiché dans la palette pour permettre de réessayer.

Les sélecteurs d’agents suivent l’ordre alphabétique du prénom puis du nom. Le dernier agent
sélectionné est conservé en mémoire frontend et proposé lors du passage à une autre page,
y compris entre **Mémoire** et **Contacts**, s’il reste disponible et autorisé. Un choix vide
ou **Tous les agents** ne remplace pas cet agent mémorisé. Une sélection explicite, notamment
dans un lien, reste prioritaire. Un rechargement complet ou une déconnexion efface ce choix.

La recherche de souvenirs conserve le contexte du contact courant, dans les échanges texte,
les appels vocaux et les tâches qui leur sont associées. Les commandes de mémorisation et les
recherches de l'agent utilisent ce même contexte.

La mémoire récente d’une conversation est reconstruite automatiquement. Pour le contexte durable,
Galaris peut injecter avant l’exécution un rappel borné des souvenirs pertinents. Si la recherche
sémantique est indisponible, l’interface indique le repli vers la recherche lexicale.

Pour une reprise de projet, une décision antérieure ou une préférence, l'agent est invité à
rechercher les preuves manquantes avant de répondre. Un calendrier chargé laisse jusqu'à la
moitié du rappel aux faits ordinaires ; les rendez-vous supplémentaires restent consultables.
Une correction conserve les anciennes preuves sauf demande explicite d'effacement.

La fiche d'un souvenir propose une **Temporalité (facultative)**. Renseignez uniquement les
composantes utiles : jour, mois, année, jour de semaine, heure et minute. Les champs vides
restent libres : jour 27 et mois 9 signifient chaque 27 septembre ; ajouter une année limite
la correspondance à cette année. Une date sans heure correspond toute la journée. L'heure 9
sans minute correspond de 9 h à 9 h 59. Le fuseau est celui configuré pour Galaris (`TZ`) ;
il ne se règle pas dans cette fiche. L'interprétation s'affiche sous les champs ; **Retirer la temporalité** conserve
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
Un seul champ date et heure est prérempli avec l'instant actuel dans le fuseau global de Galaris. Modifiez-le puis
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
Les fichiers audio portent une note de musique dans leur carré turquoise. Les jeux de données
conservent leur symbole documentaire.

Un clic sur un nœud ouvre directement sa modale, avec sa nature, sa visibilité, son nombre
d'accès et la date de dernière activité. Les liens du graphe permettent d'ouvrir un voisin ;
les dossiers et conversations ont une modale dédiée à leurs métadonnées et relations.
La fermeture par le bouton ou l'arrière-plan rend le graphe avec son cadrage conservé.

L'onglet **Graphe** affiche uniquement la carte 3D.
La 3D affiche les pages à mesure qu'elles arrivent, en commençant par les racines
File Share, sujets et contacts, puis dossiers/répertoires, documents et détails.
Tous les répertoires connus se chargent dès l'ouverture. Approchez un répertoire pour
charger ses fichiers connus, par pages de 500 au maximum ; les branches
visitées sont retrouvées à la réouverture. Leur profondeur suit les distances locales,
sans grands étages fixes. Un lien disparaît si l'un de ses nœuds passe derrière la caméra.
La carte utilise les SVG de dossiers, glyphes de fichiers et médias, bordures,
couleurs, courbures et différences d'épaisseur des relations. Les
liens sont épaissis pour mieux les voir et les longs liens utilisent davantage de segments
pour conserver leur courbe. Les libellés n'ont pas de fond.
Les nœuds éloignés sont environ deux fois plus petits que les nœuds proches.
En 3D, un clic gauche sans déplacement ouvre le nœud. Maintenez le bouton gauche et
glissez pour tourner autour du nœud visé, sans le recentrer à l'écran. Si le clic commence
sur le fond, le glissement déplace le graphe jusqu'au relâchement, sans rotation.
La translation suit le mouvement de la souris près des nœuds, même après zoom ; sa vitesse
reste stable pendant le glissement.
Relâcher après un déplacement n'ouvre aucune
modale, même si vous revenez au point de départ. Utilisez le clic droit pour déplacer la
carte. La molette déplace la caméra dans la direction du pointeur : le point visé reste
sous la souris pendant l'approche ou le recul, sans rotation. Le pincement et les boutons
de zoom déplacent la caméra dans l'axe central. Vous pouvez dépasser un nœud et continuer à traverser le graphe. Le recul
maximal retrouve le graphe entier centré. Le cadrage 3D remplit l'espace disponible selon
la largeur, la hauteur et la profondeur, avec une marge pour garder les symboles entiers.
Les flèches sélectionnent un nœud visible, **Entrée** ouvre
ses détails et **Début** recentre tout. La caméra est enregistrée à la réouverture.
Si le rendu 3D est indisponible, un message propose de vérifier WebGL et de réessayer.
Les zones denses peuvent aussi afficher un **Groupe de N éléments**, même sans sujet commun.
Cliquez sur son symbole pour approcher et voir ses membres ; reculer les regroupe à nouveau.
Ce regroupement d'affichage ne modifie pas les souvenirs ni leurs relations.

Les éléments masqués par un filtre, un repli ou le cadrage agrandissent leurs représentants
visibles, jusqu'à **quatre fois leur diamètre normal**, avec une croissance progressivement
atténuée. Leur poids suit les liens confirmés et remonte les parents masqués ; il se partage
entre les représentants les plus proches lorsqu'il y en a plusieurs. Les enfants connus d'un
répertoire encore non chargés contribuent également. Le texte des représentants ayant des
éléments masqués reste toujours affiché, même de loin et dans une zone dense.
Quand les éléments réapparaissent,
leur contribution disparaît, sans modifier leurs coordonnées. Le compteur **éléments masqués**
signale aussi ceux qui n'ont aucun représentant visible ; les libellés au survol indiquent les
éléments masqués liés au nœud. Les ressources inaccessibles ne contribuent pas au calcul.

Dans **Graphe**, les branches d'au moins huit éléments reliés exclusivement à la même ancre
sont représentées par cette ancre agrandie et un compteur. Zoomez ou cliquez sur le groupe
pour voir ses éléments. Les boutons **Zoomer** et **Dézoomer** sont utilisables au clavier.
**Réinitialiser le positionnement**, à gauche d’**Actualisation auto**, remplace les anciennes positions du
contexte courant par un placement automatique et recadre la vue. Les filtres de types
sont conservés ; les nouvelles positions sont enregistrées pour la réouverture.
Le dézoom et **Ajuster le graphe à la fenêtre** replient les branches. Le zoom, le dépliage
et la fermeture du détail conservent les positions. Le placement est préparé dans un worker ;
tourner ou zoomer ne relance aucune simulation. Un clic sur le groupe cadre son ancre.
En vue éloignée, les liens de détail et certains titres s'effacent ; zoomez pour les retrouver.
Les souvenirs partageant exactement les mêmes relations avec des ancres structurantes
sont également regroupés ; chaque groupe conserve ses connexions à toutes ses ancres.
Les symboles ont deux tailles de base, éloignée et proche : zoomer au-delà du seuil proche
écarte leurs positions sans les agrandir. Les aperçus grandissent plus tard, selon l'espace
disponible entre voisins, jusqu'à la taille réelle en pixels de la miniature, sans la dépasser.
Les titres ordinaires restent limités pour éviter les superpositions et se retrouvent au
survol ou à la sélection ; les représentants d'éléments masqués gardent toujours leur texte. Toutes les pages correspondant aux filtres sont chargées, sans plafond
global de nœuds ; les branches exclusives sont repliées dès l'ouverture. Les grandes cartes
placent les éléments près de leurs ancres avant stabilisation. Le dézoom minimal ajuste
toujours le graphe entier à la fenêtre et le recentre, même après déplacement. Le zoom
peut ensuite atteindre un million de fois ce cadrage. Seuls les nœuds dans la zone visible
sont dessinés. Masquer une nature réorganise et recadre les éléments restants ; réafficher
toutes les natures restaure les positions enregistrées. Toutes les pages restent chargées ;
le chargement réseau par zone reste prévu.

Un document manipulé avec le même agent reste candidat au rappel même après de nombreux
échanges ordinaires. L'agent retrouve sa référence, son titre et sa révision actuels, sous
réserve des droits courants. Les documents supprimés ou devenus privés sont exclus. Ce
rappel reste borné : fournissez son URI exacte si un ancien document n'est pas retrouvé.

Chaque souvenir autonome reste privé à son agent et affiche ses mots-clés, ses sources et
un libellé dérivé de son contenu. Le document conserve son titre, son contenu complet et ses droits ;
sa fiche mémoire affiche le résumé courant du document, sans historique propre. **Ouvrir le document**
permet d’éditer le contenu complet et le partage. La synthèse hérite des droits actuels du document.
La liste se filtre par texte, sujet, interlocuteur et date ; le graphe présente les
souvenirs avec les documents, fichiers, dossiers, contacts et sujets.

Dans **Mémoire**, les comptes autorisés peuvent :

- rechercher les souvenirs d’un agent directement dans Liste ;
- consulter contenu, révisions, provenance, relations et usages ;
- corriger ou archiver un souvenir ordinaire ;
- partager un document en lecture ou édition depuis son éditeur ;
- créer des documents HTML de travail qui évoluent sur plusieurs tâches ;
- explorer le graphe sur une période donnée ;
- oublier définitivement un élément, action irréversible réservée aux droits adéquats.

Les agents sont invités à envisager un jeu de données lorsque des données structurées peuvent
servir dans plusieurs documents, calculs ou tâches. Par exemple, une fiche d'entreprise peut
regrouper son capital et sa devise pour les réutiliser dans une présentation ou un budget.
Ils privilégient un jeu de données existant, conservent les sources et incertitudes et relisent
les données lors de la rédaction. Ce choix reste adapté au besoin : un fait isolé ou une
réponse courte ne nécessite pas systématiquement un jeu de données. Un document rédigé à partir
de ces données ne se met pas automatiquement à jour lorsque le jeu de données change.

Les fiches Agent, Goals et cycles sont des projections en lecture seule : modifiez leur source
plutôt que leur copie mémoire. Les contacts issus des messageries conservent l'identité nécessaire
et les coordonnées saisies ; ils restent privés à l’agent propriétaire.

Les agents disposent de `contact_list`, `contact_get`, `contact_create` et `contact_update`
dans le service MCP **Galaris**, en tâche comme en conversation, selon les permissions des fonctions.
Ils peuvent rechercher et lire leurs fiches, créer un contact avec un e-mail, un téléphone ou une
adresse postale, puis modifier son nom, ses téléphones et ses adresses postales. Une modification
conserve les coordonnées omises ; des listes vides les effacent. Les identités mail et messagerie
existantes sont préservées. La création et la modification sont sur demande par défaut.
Enregistrer un e-mail le rend connu de la politique Mail entrante par défaut.

Avec `messenger_search_users`, un agent peut aussi découvrir tous les autres agents et tous les
utilisateurs actifs de Galaris, même sans échange préalable. Il peut rechercher un nom, un e-mail,
un code ou un poste d'agent, ou une adresse `agent:<ID>` / `user:<ID>`. Plusieurs termes peuvent
être donnés dans n'importe quel ordre. Cette recherche ne crée pas de fiche dans le carnet privé
et n'accorde aucun droit d'envoi ; les règles de contact et d'accès aux conversations s'appliquent.

Dans **Connaissances → Contacts**, choisissez un agent puis cliquez sur le contact ou sur son
crayon pour modifier son nom affiché. Un seul nom d’affichage s’applique à tout le contact.
La modale ne propose ni rattachement direct ni suppression de compte : pour regrouper des comptes,
cochez deux contacts dans la liste puis utilisez **Fusionner deux contacts**.
Pour séparer un compte, utilisez **Scinder** dans la fiche, puis enregistrez. Chaque compte choisi
obtient une fiche distincte, avec le même nom initial, sans être supprimé. Il faut conserver au
moins un compte sur la fiche d’origine. Les souvenirs et l’historique restent sur cette fiche ;
les prochains échanges avec le compte séparé retrouveront sa nouvelle fiche. Annuler abandonne
la scission préparée. Une modification concurrente exige de rouvrir le contact avant de réessayer.

**Ajouter un contact** ouvre une fiche avec un nom et au moins un e-mail, un téléphone ou une
adresse postale. Plusieurs téléphones et adresses peuvent être enregistrés, chacun avec son
libellé et son pays ; une adresse contient rue et complément, code postal, ville et région.
Le pays est proposé d'après **Préférences → Localisation** : indiquez par exemple « Lyon, France ».
Il reste modifiable pour chaque coordonnée. Sans pays explicite reconnu, le champ reste vide ;
la langue et le fuseau horaire ne sont pas utilisés pour en inventer un. Un changement ultérieur
de localisation ne modifie pas les coordonnées déjà enregistrées.
Ce carnet d’adresses reste privé à l’agent sélectionné : il n’est pas nécessaire que le correspondant
possède un compte utilisateur ou soit un agent. La création n’envoie aucun mail, ne crée aucun
compte et ne lui accorde aucun accès. Un e-mail déjà présent dans le carnet de cet agent est
refusé, indépendamment des majuscules. Ces actions nécessitent `CONTACT_EDIT` et la gestion de cet agent.
L'oubli d'un contact avec ses souvenirs liés exige également `MEMORY_EDIT`.

Les téléphones et adresses se modifient aussi dans une fiche existante et participent à la recherche
de contacts. Une fusion conserve les coordonnées distinctes des deux fiches. Une scission les garde
sur la fiche d'origine, avec l'historique ; elle ne les attribue pas automatiquement à l'identité
séparée. Un nouveau message ne remplace pas les coordonnées saisies.

L'option **Enregistrer les coordonnées détectées**, dans les réglages Memory, enrichit le carnet
à partir des messages humains ou IA : mails, téléphones, adresses postales reconnues et identifiants
de messagerie explicites. Le pays téléphonique vient de la localisation de l'application.
Une coordonnée déjà connue ne déclenche aucun appel au modèle. Pour une nouvelle coordonnée,
le contexte de conversation sert à retrouver son propriétaire, puis une décision choisit une fiche
existante ou une nouvelle personne. Le traitement se déroule en arrière-plan, indépendamment de
la réponse de l'agent. Il nécessite les modèles décisionnel et texte ultra-léger du profil.
Les adresses sont conservées dans leur notation complète ; les motifs postaux couvrent les formes
françaises et anglaises courantes, sans garantir toute adresse. Une attribution incertaine ne crée
pas de fiche et n'est pas attribuée par défaut à l'expéditeur.

Au repos, Dream examine les doublons possibles au-dessus du **Seuil de similarité commun**,
réglé dans les paramètres Mémoire à 92 % par défaut. Cette même valeur s'applique à l'acquisition,
au rappel, aux doublons et aux contradictions mémoire. Le modèle doit confirmer qu'il s'agit de la même personne : un nom identique
ou une adresse familiale partagée ne suffit pas. Une fusion conserve les coordonnées, comptes et
liens de conversation. La supervision Dream expose **Rapprochement des contacts en doublon**.
Les coordonnées apprises restent privées à l'agent et n'accordent aucun droit d'accès supplémentaire.

Pour le Chat interne, l’identité **Utilisateur Galaris** suffit : aucune seconde identité de
messagerie interne n’est créée. Les anciens alias internes redondants sont retirés lors de
la synchronisation DbAdmin, sans supprimer le contact ni ses souvenirs.

Les fiches créées manuellement ou scindées conservent leur nom et leurs comptes lors des prochains
messages. Une scission peut être réunie par la fusion. En cas d’erreur, le brouillon reste
disponible pour réessayer. Annuler ferme la fenêtre sans enregistrer le brouillon.

Les fiches de fichiers restent vides tant qu'elles n'ont ni notes ni description utile.
Leurs métadonnées techniques (URI, taille, type, date, empreinte) ne remplissent pas la description.

Les **Dossiers thématiques** regroupent les connaissances autour d’un sujet global, même si elles
proviennent de salons, tâches ou appels différents. Dream effectue ce classement en arrière-plan ;
il peut aussi associer les documents et les datasets à ces sujets. Dans la fiche d'un sujet,
l'onglet **Contenus liés**, affiché en premier et ouvert par défaut, permet d'ouvrir les conversations,
documents et jeux de données associés auxquels vous avez accès. Les tâches disposent de leur onglet,
et l'onglet **Mémoires** rassemble les souvenirs liés avec leur aperçu et leur détail.
Les compteurs portent sur les conversations, tâches, mémoires, documents et jeux de données ;
les rounds texte et tours audio ne sont plus présentés séparément.
Une fusion conserve ces associations ; supprimer le sujet conserve les ressources.
Dans l'éditeur d'un document ou d'un dataset, l'en-tête affiche l'UUID puis le badge du sujet,
comme dans le Chat. Cliquez sur ce badge (ou **Sans sujet**) pour consulter l'affectation et
la changer si vous avez les droits de modification de la ressource et des sujets. Le brouillon
ouvert est conservé ; une affectation concurrente exige une actualisation avant de réessayer.
Le bouton de référence du document conserve la copie de son adresse complète.
La création automatique de sujets suit le réglage Dream existant ; en mode proposition,
ces ressources sont uniquement rattachées aux sujets existants.
Les comptes autorisés peuvent aussi corriger l’affectation d’un élément. Dream peut consolider des
souvenirs et analyser séparément les résultats de tâches afin de renforcer des compétences propres à
l'agent. Une compétence auto-apprise n'est ajoutée aux futures exécutions qu'après avoir atteint les
seuils de preuves et de score configurés ; la page **Compétences → Compétences personnelles** permet
d'en consulter les preuves, d'éditer son `SKILL.md` et de la désactiver.

## Organiser et suivre le travail

Galaris distingue le niveau d’effort, la méthode de travail et la coordination. Une action
simple peut être directe ; une mission longue conserve des jalons dans une seule tâche ;
plusieurs résultats indépendants peuvent former un plan. Une ambiguïté sur le périmètre
demande une précision avant l’exécution.

Le [guide des tâches](tasks.md) explique les directives du Chat, les jalons, la progression,
les questions, les autorisations et la reprise après erreur.

## Mesurer la qualité avec le Lab IA

Les comptes autorisés disposent d’un **Lab IA** séparant deux usages : l’analyse complète d’une
Tâche réelle et les benchmarks reproductibles du Dispatcher, du Planner et des
exécuteurs tâche/Conversation/Voice ainsi que des mécanismes Dream/Goal.

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

Claude Agent peut aussi être choisi directement comme **Moteur des tâches** dans la fiche d'un
agent. Galaris provisionne alors un conteneur Claude Agent SDK isolé, lui fournit le modèle interne
résolu, les compétences et le MCP de cet agent, puis affiche en direct le texte, les appels d'outils,
les appels LLM et le résultat terminal. Aucun compte ni token Anthropic direct n'est nécessaire.

- [Écrire et relier des contenus riches](rich-content.md) : éditeur, liens, images documentaires et historique.
