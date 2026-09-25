<p align="right"><strong>Français</strong> · <a href="../../en/user/README.md">English</a></p>

# Guide utilisateur et découverte

Ce guide s’adresse à une personne qui veut utiliser Galaris sans connaître les modèles de
langage, les API ou Docker. Les écrans accessibles dépendent des droits attribués à votre
compte.

Pour commencer par une vue d’ensemble, consultez le
[tour complet des fonctionnalités](../features.md).

Pour organiser les accès aux agents, consultez [Équipes et autorisations de dialogue](teams.md).

## Galaris, simplement

Un agent Galaris est un collaborateur logiciel avec :

- un nom, un rôle et des consignes de comportement ;
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

La barre latérale ne montre que les écrans autorisés par votre rôle :

| Écran | À quoi il sert |
|---|---|
| Accueil | voir les agents disponibles, les tâches récentes et les étapes de configuration manquantes |
| Agents | connaître le rôle, la personnalité et les capacités de chaque agent |
| Suivi d’exécution | suivre séparément conversations texte, appels, Tasks, processus et appels LLM en temps réel |
| Objectifs | suivre les missions de fond, leurs cycles, preuves et résultats |
| Dossiers thématiques | retrouver les sujets globaux et les connaissances liées entre plusieurs canaux |
| Mémoire | rechercher, lire, corriger, partager ou oublier les souvenirs autorisés d’un agent |
| Dream | voir les opérations de classement, extraction et apprentissage exécutées en arrière-plan |
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

L'entrée **Messenger** ouvre la messagerie native de Galaris lorsqu'elle est activée et que votre
rôle possède les droits nécessaires. Vous pouvez créer une conversation directe avec un agent, ou
un groupe contenant cet agent et des collègues, rechercher les rooms, suivre les non-lus, répondre,
joindre un fichier, enregistrer une note vocale et démarrer un appel navigateur. Le panneau
**Activité** montre les étapes publiables et les outils du round, jamais le raisonnement privé de
l'agent. Quitter une conversation retire votre accès sans effacer son historique pour les autres
membres.

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

### Comprendre les conversations courtes et le travail de fond

Un message reçu n’est plus systématiquement transformé en Task. Le contrôleur conversationnel
agrège les messages arrivés en rafale, reconstruit l’historique utile et prépare une réponse courte.
Lorsqu’un outil doit produire un effet durable ou qu’un travail va prendre du temps, il crée une
Task ou un Processus de fond et vous en donne la référence.

Dans **Suivi d’exécution → Conversations textuelles**, vous pouvez voir les messages traités ou en
attente, les rounds, leurs tentatives, les appels LLM, la livraison et les éventuelles erreurs. Une
réponse entre deux agents est admise seulement lorsqu’une requête fraîche l’attend ; cette garde
évite les boucles automatiques de politesse.

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

### Lancer un processus métier

L’écran **Processus** expose les workflows que l’administrateur a associés à un agent. Ouvrez
une définition, renseignez son entrée JSON puis lancez une exécution. Son statut, sa sortie, ses
événements et les tâches liées restent consultables dans le même écran.

Une annulation locale ne garantit pas toujours l’arrêt immédiat du moteur externe. Lorsque
l’interface indique que l’exécution distante peut continuer, vérifiez le service cible avant de
relancer le processus.

## Mémoire, documents et dossiers thématiques

La mémoire récente d’une conversation est reconstruite automatiquement. Pour le contexte durable,
Galaris peut injecter avant l’exécution un rappel borné des souvenirs pertinents. Si la recherche
sémantique est indisponible, l’interface indique le repli vers la recherche lexicale.

Dans **Mémoire**, les comptes autorisés peuvent :

- tester le rappel d’un agent et voir le mode réellement utilisé ;
- consulter contenu, révisions, provenance, relations et usages ;
- corriger ou archiver un souvenir ordinaire ;
- partager directement un élément en lecture ou édition ;
- créer des documents Markdown de travail qui évoluent sur plusieurs Tasks ;
- explorer le graphe sur une période donnée ;
- oublier définitivement un élément, action irréversible réservée aux droits adéquats.

Les fiches Agent, Goals et cycles sont des projections en lecture seule : modifiez leur source
plutôt que leur copie mémoire. Les contacts issus des messageries ne contiennent que l’identité
minimale nécessaire et restent privés à l’agent propriétaire.

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

Dans le Chat natif, `@task` placé n’importe où dans le message crée immédiatement une Task durable
avec le texte restant comme objectif, sans appel au LLM de conversation. Pour le harnais interne
Galaris, `@plan` suffit lui aussi à créer la Task et à forcer sa planification, sans ajouter `@task`.
Ces directives se combinent, sans ordre imposé, avec `@standard`, `@high` et `@approve`. Le Chat
conserve le round et publie aussitôt une confirmation déterministe
dans la room ; le résultat de la Task y sera publié à sa terminaison. Le bouton `@` du composeur
affiche uniquement les directives compatibles avec le driver de l’agent sélectionné.

## Ce qui se passe après l’envoi

1. La demande créée dans cet écran devient une Task durable.
2. Le Dispatcher choisit une exécution directe ou un plan, puis fixe l’effort.
3. Le planner prépare les travaux décomposables ; le briefing automatique est actuellement désactivé.
4. Le driver exécute l’agent avec ses outils autorisés.
5. Galaris enregistre la trace et le résultat, puis reprend les parents éventuels.

Les conversations texte et voix suivent leur propre contrôleur et leur exécuteur configuré. Elles
ne passent pas par le Dispatcher de Tasks ; lorsqu’elles ont besoin d’un travail durable, elles
créent une Task explicitement liée.

## Planner et briefing : des aides optionnelles

Le planner découpe uniquement un objectif qui exige plusieurs blocs de travail coordonnés.
Chaque feuille du plan est une vraie tâche. Une étape n’est pas censée « réfléchir » ou
« rédiger la réponse finale » : elle doit produire une partie vérifiable du résultat.

Le briefing peut préparer une exécution `high` en rappelant l’objectif, les contraintes, les
ressources pertinentes et les contrôles de fin. Il est actuellement désactivé pour mesurer sa
valeur ajoutée face aux objectifs de Task autonomes. Ses anciennes traces restent consultables.

Ces aides sont activées par driver. Dans la configuration actuelle :

| Driver | Planner | Briefing |
|---|---:|---:|
| Interne (Pydantic AI) | oui | non, désactivé pour évaluation |
| Hermès | non | non |

Hermès conserve ainsi ses capacités propres sans être enfermé dans un second harnais.

## Quand Galaris pose une question

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
| Briefing | la préparation `high` est en cours |
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
Task réelle et les benchmarks reproductibles du Dispatcher, du Briefing, du Planner et des
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
