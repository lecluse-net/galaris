# Éditeur de code Git dans les discussions

- Statut : `design`
- Date : 2026-10-11.
- Demande : suivre les changements des agents développeurs avant commit et push, et
  afficher leur dépôt dans le panneau utilisé par les documents de la discussion.
  L'humain doit aussi pouvoir modifier le code, coéditer avec les agents et gérer
  lui-même Git : branches, commits, pull, push, rebase et autres commandes.
- Candidat retenu pour le prototype : code-server, service autonome fondé sur VS Code OSS.
- Ce plan décrit une cible ; aucun éditeur, droit ou outil supplémentaire n'est encore livré.

## Résultat recherché

Quand un agent travaille sur le code source d'un dépôt Git, il peut présenter son espace
de travail dans la discussion. Le panneau affiche code-server avec l'arborescence, les
fichiers et les diffs Git. La conversation reste utilisable pendant la consultation.
Un document demandé ensuite retrouve ce même emplacement avec son éditeur habituel.
Le dépôt demeure une ressource de code ; il n'est ni copié dans un Document ni converti
en HTML ou Dataset pour être affiché.

L'éditeur ouvre exactement le checkout ou worktree dans lequel l'agent écrit par SSH.
Un autre clone, un export et une synchronisation périodique par copie ne satisfont pas
la garantie : ils ne montrent pas nécessairement les changements non committés courants.

L'édition humaine et la gestion Git complète sont des exigences utilisateur. La sauvegarde
écrit dans le même dépôt et devient visible à l'agent. Un utilisateur autorisé dispose
des actions Git de l'IDE et d'un terminal pour les autres opérations. Le mode consultation
reste disponible pour les lecteurs ; un utilisateur ayant les droits d'édition ouvre
directement un éditeur modifiable, comme dans VS Code. Les documents conservent leurs règles actuelles
d'édition ; les capacités consultation/édition concernent ici les dépôts.

Le dépôt et son accès Git sont déjà configurés dans la console. Réutiliser en priorité
cette configuration, notamment les clés SSH de pull/push. Une identité Git humaine
distincte est facultative si elle se configure simplement ; l'utilisateur autorise
l'utilisation de l'identité et de l'accès Git de l'agent pour ses propres opérations.
Ne pas imposer de nouveau compte de forge ni de gestionnaire d'identités Git.

Le besoin de coédition est précisé : retrouver le fonctionnement standard de VS Code,
sans fonctionnalité collaborative supplémentaire. L'humain édite dans l'IDE et les agents
continuent à modifier les mêmes fichiers par SSH ; l'IDE détecte les changements sur disque
avec ses mécanismes natifs. Les buffers non sauvegardés restent propres à l'éditeur.
Le partage des frappes et des curseurs, un serveur de collaboration et un protocole
spécifique d'écriture agent sont hors périmètre.

Première cible : Console SSH embarquée, dépôt synthétique, un agent et un utilisateur.
La livraison complète inclut les consoles SSH externes préparées pour accueillir l'IDE ;
leur qualification constitue un lot distinct, sans présumer que toute cible SSH le permet.

## Socle vérifié et garanties à préserver

| Surface existante | Conséquence |
|---|---|
| `front/app/chat/pages/index.vue`, `ChatDocumentPane.vue`, `ConversationDocumentDialog.vue` | Réutiliser le panneau intégré desktop, ses dispositions et sa visionneuse mobile ; préserver les brouillons et la discussion. |
| `front/app/chat/documentFocus.ts` et contexte documentaire à l'envoi | Ne pas faire passer un dépôt pour `displayed_document_id`, ni perdre le contexte des documents existants. |
| `back/app/conversation/document_display.py`, `mcp.py` | `document_show` appartient à Conversation et vérifie room, accès et fraîcheur. Son exposition actuelle exclut les Tasks et la voix. |
| `back/app/memory/tests/test_document_show.py`, `front/browser-tests/chat-document-workspace.spec.mjs` | Couverture existante des droits, ouvertures répétées, sauvegardes et événements pour une autre room. Étendre les garanties communes. |
| `back/app/console/contracts.py`, `connection_service.py`, `ssh_client.py` | Résoudre la connexion et le home SSH via les contrats existants ; respecter la vérification de clé hôte et le confinement des chemins. |
| `ssh-executor/`, `compose.yaml` | Homes et dépôts persistants, comptes distincts, service privé ; ne pas publier un port IDE sur l'hôte par défaut. |
| `back/app/tools`, `app.connection`, `app.file_share` | Réutiliser droits d'outils, secrets chiffrés, provenance de connexion et URI de fichiers ; ne pas créer un second transport générique de fichiers. |
| `front/nginx.conf` | CSP et intégration des frames doivent être traitées explicitement ; une iframe ne suffit pas à intégrer l'IDE. |

Les déclarations `back/modules.py` et `front/modules.ts` ne comportent pas de module
d'espace de code. Les Documents HTML et Dataset restent les ressources documentaires
actuelles. Le panneau générique ne change ni leurs types ni leurs ACL.

## Architecture et identité du dépôt

Proposer `app.code` pour posséder les espaces de code, leur autorisation, les références
conversationnelles et les sessions humaines ; `bridge.code_server` adapte le cycle de vie
et les capacités du service tiers. Le frontend métier correspondant est `front/app/code`.
Confirmer cette séparation après le prototype et enregistrer une décision avant réalisation.

```text
Agent / Task ── console SSH ─────────────── dépôt Git / worktree réel
     │                                          ▲
     └── déclaration d'espace ── app.code        │ mêmes fichiers
                                      │         │
Discussion ── panneau de travail ── passerelle ── code-server isolé
                 │                    │
                 └── Document         └── session humaine, ACL, mode, cible
                     ou dépôt Git
```

L'espace persistant comporte un UUID, un libellé, une référence à la connexion Console,
une racine canonique validée, son propriétaire et ses grants. Les liens conversationnels
et Task sont des relations séparées ; un même espace peut être rouvert depuis plusieurs
messages autorisés. Tout champ `_id` du modèle est une vraie FK. La branche et HEAD sont
des observations rafraîchies, pas l'identité durable du workspace.

Proposer `galaris://code/<uuid>` comme référence durable de l'espace, avec projection
de métadonnées autorisées dans le provider natif. Les fichiers conservent leurs URI
`console://` dans le contexte de leur connexion d'origine. Une URI relative au home
sans provenance de connexion ne suffit pas à identifier un dépôt partagé entre agents.
Les arguments publics ne contiennent ni chemin hôte Galaris, ni clé SSH, ni URL libre d'IDE.

À l'enregistrement, résoudre la racine avec Git et le transport Console public : checkout
normal, worktree lié et dépôt imbriqué doivent être distingués. Refuser les sorties du home,
traversées et liens symboliques hors périmètre. Ne pas modifier automatiquement `safe.directory`
globalement ; faire correspondre les identités Unix ou borner une éventuelle configuration.
Préserver l'accès aux métadonnées communes d'un worktree et leurs chemins dans les montages.

Les nouvelles tables suivront SQLAlchemy et `core.dbadmin`, puis `make sync-db` en
développement. Aucun schéma n'est ajouté par ce plan. Les sessions techniques ne deviennent
pas des Process métier ; Tasks et Console gardent leurs responsabilités actuelles.

### Liaison concrète Console et IDE

La liaison porte sur une cible Console effective et les mêmes fichiers, pas sur une
copie du code ni sur le partage de la session shell. Le service résout la connexion du
run appelant, découvre le home, valide le répertoire, puis interroge Git pour identifier
la racine du worktree et ses métadonnées communes. Il retourne un descripteur typé à
l'adaptateur IDE. Étendre si nécessaire la façade publique de Console pour ces opérations
bornées et le transport IDE ; ne pas importer `ssh_client.py` depuis le nouveau domaine.

| Cible | Accès aux fichiers | Accès navigateur à l'IDE |
|---|---|---|
| Console embarquée | Monter dans le runtime IDE isolé le dépôt déjà présent dans le volume de l'exécuteur, avec UID/GID et métadonnées Git compatibles. Qualifier un lanceur administré qui ne donne pas à l'IDE accès au volume applicatif complet. | Passerelle authentifiée vers le service IDE sur un réseau interne ; aucun tunnel SSH TCP n'est requis. |
| Console externe préparée | Exécuter code-server sur la machine du dépôt, ou dans un runtime isolé qui monte ce même dépôt. | Passerelle vers le port loopback IDE à travers une connexion SSH dédiée, sous réserve de la configuration du serveur distant. |

L'agent écrit par SSH ; les watchers de l'IDE observent ces mêmes fichiers. Une sauvegarde
humaine autorisée est donc visible lors de la lecture SSH suivante, sans transfert SFTP
de synchronisation. Un buffer IDE non sauvegardé reste local à cette session et n'est
pas encore visible à l'agent. L'actualisation des fichiers et de la vue Git est à mesurer.

Le terminal intégré à code-server est une autre session shell dans son environnement
autorisé. Il ne reprend pas automatiquement stdin, stdout, cwd, historique ou processus
de la console de l'agent. Les commandes et résultats de l'agent restent suivis dans les
traces Console/Task de Galaris. Le terminal minimal doit permettre les commandes Git
non couvertes par l'interface native.

Retrouver également l'environnement complet de la console est un complément souhaité,
facultatif s'il complexifie l'intégration : mêmes outils et dépendances, tests et possibilité
de relancer un service avec les permissions déjà disponibles. Sur une cible externe où
code-server s'exécute directement sous le même compte, qualifier l'environnement effectivement
hérité. Pour un IDE isolé, partager le dépôt ne garantit pas les mêmes exécutables, services
ou privilèges ; qualifier une session SSH humaine distincte vers la console seulement si
l'intégration reste simple. Sans ce complément, conserver édition et Git, et documenter
les limites du terminal sans demander de réinstaller tout l'environnement dans l'IDE.

Le transport Console courant ferme sa connexion après un délai d'inactivité de 60 secondes.
Une session IDE longue ne doit donc pas réutiliser aveuglément cette connexion de run :
sa connexion de transport et ses keepalives ont leur propre cycle de vie, rattaché aux
droits de la cible et au TTL de la session, sans empêcher le nettoyage des commandes agent.

La référence d'espace conserve une génération de cible. Modifier hôte, compte, clé hôte,
credentials ou racine invalide les sessions concernées et exige une nouvelle validation ;
la même ligne Connection ne suffit pas à identifier indéfiniment le même dépôt. Ne pas
rediriger silencieusement un lien de conversation vers un autre serveur. Une suppression,
un déplacement ou un remplacement du répertoire produit un état explicite à revalider,
sans recréer ni recloner automatiquement le dépôt.

## Consultation, édition et concurrence

| Mode | Garantie recherchée |
|---|---|
| Consultation | Lire le dépôt courant et les diffs ; aucune écriture du code, de l'index ou des refs Git depuis la session humaine. |
| Édition et Git | Sauvegarder dans le dépôt courant, gérer branches, index, commits et remotes avec les droits accordés ; détecter les modifications externes et préserver les buffers. |

La consultation doit être imposée par l'environnement serveur. Sur l'exécuteur embarqué,
qualifier une instance isolée avec montages du dépôt et de ses métadonnées Git en lecture
seule, profil IDE séparé et inscriptible, sans clés, socket Docker, accès au management
ou home complet de l'agent. Tester aussi terminal, tâches et extensions : un réglage
`readOnly` dans l'éditeur ou des boutons cachés ne constituent pas une protection.
Git doit pouvoir lire sans mise à jour facultative de l'index ; qualifier son comportement
sur montage en lecture seule. Le réseau de cette instance ne doit pas offrir une autre
voie d'écriture vers la console ou les services privés.

Une session éditable isolée ne monte que le périmètre autorisé. Un IDE complet possède
néanmoins terminal, tâches et extensions : son accès correspond à une capacité d'exécution
dans cet environnement, plus large que la seule saisie de texte. Ne pas prétendre appliquer
un droit fin « éditer mais ne jamais commiter » par une barre d'outils. Toute extension
livrée est qualifiée séparément.

Le parcours humain inclut création/changement de branche, préparation par fichier ou
fragment, commit, fetch, pull, push, rebase et résolution de conflits. Utiliser les actions
Git natives disponibles dans la version retenue ; le terminal assure la couverture des
commandes restantes. Installer Git dans le runtime et rendre accessibles en écriture
les métadonnées nécessaires, y compris celles communes aux worktrees autorisés. Préparer
l'accès réseau aux remotes ; les privilèges Galaris ne créent pas les droits sur la forge.

Réutiliser les remotes, l'identité d'auteur configurée et l'authentification Git fonctionnelle
dans la console. L'utilisateur autorise les opérations humaines avec l'identité de l'agent ;
les commits pourront donc porter son nom/email et les accès forge utiliser ses clés SSH.
Une configuration humaine propre peut être proposée si elle reste simple, sans devenir
un préalable à l'édition ou au push. Ne pas remplacer silencieusement la configuration
existante du dépôt pour attribuer un commit à un autre auteur.

La clé qui ouvre la console SSH et celle utilisée par Git pour accéder à la forge peuvent
être différentes. Qualifier l'accès Git effectif dans l'IDE : configuration SSH, clé ou
agent SSH requis, known_hosts et chemins résolus dans son environnement. Dans un runtime
isolé, donner accès côté serveur aux seuls éléments nécessaires à ce Git, sans exposer
le volume applicatif complet ni des secrets sans rapport. Le navigateur ne reçoit pas
les clés privées. La session humaine reste identifiée et autorisée par Galaris, même si
Git utilise une identité technique partagée. L'historique Git seul ne distingue alors
les contributions humaines et celles de l'agent.

Ne jamais changer les permissions du dépôt partagé pour faire passer la session humaine
en lecture seule : l'agent doit conserver ses propres droits de travail. Une transition
de mode termine/remplace la session concernée après protection des brouillons et nouveau
contrôle d'autorisation. Elle ne transforme pas la session d'un autre lecteur.

### Coédition et opérations concurrentes

L'humain et les agents travaillent sur le même worktree avec le comportement natif de
VS Code OSS : actualisation des fichiers sauvegardés, détection des changements externes
et traitement des conflits de sauvegarde. Qualifier ce comportement dans la version
code-server retenue, notamment quand un fichier ouvert contient des modifications non
sauvegardées. Préserver les buffers lors des changements de panneau propres à Galaris.

Les agents conservent leurs commandes SSH habituelles. Ne pas ajouter de serveur de
collaboration, de verrou applicatif, de sauvegarde intermédiaire automatique ou d'outil
de modification obligatoire pour cette intégration. Les limites sont celles d'un éditeur
ouvert sur des fichiers aussi modifiés par un autre processus : une commande SSH peut
remplacer un fichier déjà sauvegardé. Ne pas promettre une fusion automatique ni une
protection universelle contre ces écritures.

Git partage l'index et les refs dans ce worktree : un commit peut inclure des fragments
préparés par un autre participant. Conserver les vues natives du contenu préparé et les
commandes Git habituelles. Un changement de branche, un pull ou un rebase affecte aussi
les fichiers vus par l'agent ; leur coordination relève du travail partagé et de la
discussion, sans workflow supplémentaire d'approbation ou de pause imposée par Galaris.

Des worktrees distincts restent utiles pour des travaux indépendants de plusieurs agents ;
ils ne remplacent pas la coédition demandée sur un espace commun. Leur création demeure
une action du workflow, jamais un effet de l'ouverture de l'éditeur.

## Présentation par les agents

Le nom public retenu pour la présentation est `repository_show`, distinct de
`document_show` : les deux fonctions ouvrent leur ressource dans le même panneau de
discussion, avec respectivement code-server et l'éditeur documentaire. Les paramètres
et capacités restent à qualifier avec le prototype.

Contrats proposés :

| Surface | Responsabilité |
|---|---|
| Résolution/enregistrement interne de l'espace | Valider une URI de répertoire Console dans la connexion effective, retrouver/enregistrer l'espace autorisé et dédupliquer les demandes concurrentes. Aucun second appel MCP obligatoire, clone ou commande libre. |
| `repository_show(repository, file?, view?)` sur Conversation | Accepter une URI durable d'espace ou une URI de répertoire `console://` dans la connexion effective, résoudre l'espace, puis demander son ouverture dans le même panneau que `document_show`, avec code-server ; disponible au contrôleur et aux Tasks explicitement liées à un Chat interne autorisé. |
| Liaison d'espace à une Task | Conserver la provenance, publier sa disponibilité dans la discussion d'origine et rendre la référence réouvrable pendant le travail. |

Exemple proposé : `repository_show(repository="console://projects/demo/", view="changes")`.
Les appels suivants peuvent utiliser la référence `galaris://code/<uuid>` retournée.
Le backend extrait la connexion effective du contexte, jamais d'un hôte arbitraire fourni
par le modèle. L'ouverture dans la vue des changements constitue le parcours initial de
revue ; le panneau rend clairement le dépôt, le worktree, la branche et le mode courant.

L'agent développeur présente le dépôt avant ses premières modifications, puis continue à
utiliser ses outils SSH habituels. Pour une Task longue, la même résolution interne doit
permettre de présenter l'IDE pendant l'exécution, sans attendre sa réponse terminale.
Cette capacité ne peut pas se limiter à un clone de `document_show`, actuellement absent
des Tasks. Utiliser les liens publics Task/Conversation et un port de publication vers
Chat ; ne pas introduire de dépendance `app.agent → app.task`.

Le contrôleur conversationnel et une Task développeur liée peuvent appeler le même
`repository_show`. Pour cette nouvelle fonction, qualifier une exposition Task avec un
filtre dédié (`task_enabled=True` et disponibilité conditionnelle), sans changer les
restrictions de `document_show`. Résoudre la room via les liens publics existants, jamais
par un argument libre du modèle. L'appel publie une référence et, lorsque son rattachement
et sa fraîcheur sont encore valides, une demande d'affichage via le même service de
présentation. Une Task autonome sans discussion n'invente pas une room. Un round remplacé,
une Task détachée ou une autre room ne prend pas le focus.
L'absence de droit du lecteur n'élargit jamais les grants et ne bloque pas les opérations
SSH déjà autorisées de l'agent ; l'affichage retourne son propre état.

Prévoir un événement `chat.repository_show` typé avec room, espace, séquence de demande et
navigation relative validée. Le backend vérifie l'accès agent ; le client recharge via
l'API sous les droits humains courants. La publication signifie « ouverture demandée »,
pas « humain ayant lu », « validation » ou « autorisation de commit/push ».

Conserver dans l'historique une référence d'espace réouvrable, indépendante du WebSocket.
Elle ouvre l'état courant du dépôt ; elle n'est pas une preuve de son état historique.
Une référence à un commit ou un snapshot explicitement conservé est nécessaire pour une
revue historique. Le rendu d'une référence ne doit jamais provoquer un clonage ni une écriture.

Actualiser le skill runtime Galaris et les descriptions d'outils : annoncer le dépôt,
présenter les diffs, ne pas remplacer le code versionné par un Document. Les commandes
SSH libres ne sont pas parsées pour deviner un dépôt ou attribuer sûrement une modification.
Une comparaison Git révèle aussi les changements d'autres acteurs du même worktree.

## Un panneau de travail commun

Remplacer la sélection uniquement documentaire par une cible typée
`document | code_workspace`, sans second panneau concurrent. Un seul contenu est actif.
Le Document utilise l'éditeur documentaire actuel ; le dépôt utilise code-server.
Les commandes communes restent dans la barre du panneau : titre, disposition, ouverture,
fermeture et retour à la discussion. Les commandes spécifiques sont fournies par le contenu.

Conserver les dispositions desktop à partir de 1024 CSS px, leur redimensionnement au
clavier et la discussion utilisable. Sur mobile, réutiliser la visionneuse avec fermeture
par backdrop et bouton accessible. Adapter l'IDE à l'espace disponible, qualifier clavier
logiciel, focus et raccourcis ; une ouverture plein écran peut compléter le panneau.

Les demandes concurrentes suivent une séquence et une génération de room. Une réponse
ancienne ne remplace pas un contenu ouvert plus récemment. Réouvrir le même espace
réutilise la session autorisée et conserve les onglets et la position lorsque possible.
Un changement de Document/dépôt n'écrase pas les brouillons de message.

Avant Document → code, appeler la sauvegarde existante et rester sur le Document si elle
échoue. Avant code → Document, fermeture ou changement de contexte, protéger les buffers
non sauvegardés. code-server ne fournit pas une API hôte équivalente au `flush()` de notre
éditeur : le prototype doit qualifier un pont minimal pour disponibilité, état dirty,
sauvegarde et navigation, avec réponses corrélées, origine/source vérifiées et timeouts.
Ne pas supposer qu'un `postMessage` arbitraire ou une extension seule suffit.

En attendant un pont fiable, conserver l'iframe éditable montée lors d'une simple bascule
et traiter son état comme potentiellement dirty. Interdire sa destruction automatique ;
une fermeture manuelle exige un choix explicite et ne promet pas une sauvegarde invisible.
Borner les instances conservées ; ne jamais évincer une session potentiellement dirty
pour satisfaire un quota. L'échec du pont doit conserver l'ancien contenu et offrir une
action de récupération. Ne pas lancer une sauvegarde forcée en réponse à une révocation.

À l'envoi d'un message, transmettre uniquement le workspace réellement affiché et chargé,
la branche/HEAD observés et, si le pont les confirme, le fichier et la sélection bornée.
Le serveur vérifie le contexte, les droits et la provenance ; ces métadonnées ne deviennent
pas des instructions et ne déclenchent aucune exécution. Réutiliser le principe du contexte
documentaire, sans surcharger ses champs ni injecter tout le dépôt dans le prompt.

## Déploiement, sessions et droits

Un utilisateur humain ouvre sa propre session Galaris autorisée. Cette session peut
utiliser côté serveur la configuration Git et les clés de forge de l'agent, conformément
au choix utilisateur ; elle ne reprend pas sa session MCP ni ses autres secrets.
Définir droits de consultation, d'édition complète et d'administration sur
des espaces précis ; ni l'accès à la room, ni un UUID, ni la gestion d'un agent ne suffisent.
Partager une référence n'accorde pas l'accès au dépôt. Le contenu des fichiers reste protégé
par le système de fichiers et l'isolation du runtime, même si l'IDE propose « Ouvrir dossier ».

code-server reste un service autonome à version et digest fixés, sans port public direct.
Proposer une origine IDE distincte, avec cookies propres et autorisation d'intégration limitée
à Galaris. Qualifier SSO par session courte côté passerelle, WebSockets, sous-chemins,
redirections, workers et webviews. La CSP du shell autorise seulement cette origine ; ne
pas exposer les cookies de l'application aux extensions ou previews exécutables de l'IDE.
Le prototype doit fonctionner avec les politiques de cookies des navigateurs ciblés.

La passerelle ne prend pas d'URL ou de port libre du navigateur. Elle résout une cible
enregistrée, revalide les droits, authentifie les transports internes et les connexions
WebSocket, puis expire/révoque les sessions et ferme les flux déjà ouverts. Une ancienne
URL ou une reconnexion ne restitue pas un droit retiré. Les clés restent côté serveur.

Session : `opening → ready → closing → closed`, avec `failed` depuis un état actif.
Idempotence d'ouverture, quotas par lecteur/espace, TTL, durée maximale et réconciliation
après panne ; pas de session ou verrou exclusivement en mémoire d'un worker HTTP.
Le nettoyage d'une session ne supprime aucun fichier du dépôt. Protéger les buffers lors
d'une fermeture normale ; une panne, expiration ou révocation peut interrompre leur
sauvegarde et nécessite une récupération distincte sans contourner les droits.

Pour une console externe, code-server s'exécute sur la cible ou dans un runtime local à
son système de fichiers. Un tunnel SSH backend transporte HTTP/WebSocket, avec clé hôte
épinglée et destination configurée. Remote-SSH de Microsoft n'est pas présumé disponible
dans code-server. Fournir une procédure d'installation versionnée et explicitement autorisée,
jamais une installation silencieuse à la première ouverture. La consultation protégée
nécessite aussi une identité/runtime isolé sur cette cible ; sinon annoncer la capacité
indisponible, sans la simuler avec un simple thème ou réglage de l'éditeur.

La configuration embarquée `ssh-executor/sshd_config` interdit aujourd'hui le forwarding
TCP et Unix. Préserver cette règle pour les consoles agent ; utiliser le réseau interne
pour l'IDE embarqué. Sur une cible externe, détecter cette capacité et documenter une
autorisation administrée limitée à la destination loopback IDE (`AllowTcpForwarding` et
`PermitOpen` selon le profil retenu), éventuellement sous une identité de transport
distincte. Ne pas ouvrir un forwarding général ni contourner un refus par une commande
shell de relais. Un serveur refusant ce transport annonce explicitement l'IDE indisponible.

## Licence et périmètre

Galaris reste CeCILL 2.1 ; code-server et VS Code OSS conservent leurs notices MIT.
La séparation en services correspond à l'intégration étudiée. Vérifier les licences de
la version, de l'image, des dépendances et des extensions réellement redistribuées, et
conserver leurs copyrights/notices. Open VSX est le catalogue candidat ; ne pas configurer
le Marketplace Microsoft en contournant ses conditions.

Le périmètre comprend affichage, consultation, édition humaine, gestion Git complète,
travail sur les mêmes fichiers que les agents, provenance et consoles externes qualifiées.
Les modes Console interne et externe sont tous deux requis pour la livraison complète.
L'identité Git humaine séparée et l'équivalence complète du terminal sont facultatives ;
leur absence ne bloque pas l'intégration de l'éditeur, de Git et des deux types de console.
Le niveau fonctionnel demandé est celui de VS Code standard. Sont hors périmètre :
coédition des buffers en temps réel, serveur de collaboration, protocole d'écriture agent
spécifique, hébergement Git, création automatique des worktrees et politique d'approbation
avant commit/push.
Voir un diff ou enregistrer un fichier n'approuve pas une publication. Si une approbation
est ajoutée plus tard, elle devra porter sur une identité Git/contenu précis et être
invalidée après changement ; un simple bouton de l'IDE ne gouverne pas les commandes SSH.

## Lots de réalisation

| Lot | Travail | Condition de passage |
|---|---|---|
| 0 — Faisabilité | Prototype Docker synthétique : même worktree, changements SSH, Git avec la configuration et l'accès SSH déjà en place, lecture seule réelle, actualisation et conflits de sauvegarde natifs, pont dirty/sauvegarde, iframe isolée et authentification. Évaluer l'environnement de terminal complet comme complément facultatif. Mesurer délai d'actualisation, charge et nettoyage. | Vérifier le comportement standard de l'IDE sur le dépôt partagé, préciser les limitations et figer l'architecture dans une décision. Aucun mode « consultation » sans preuve de confinement. |
| 1 — Espaces et accès | Module, contrats publics, modèles/grants, provenance Console, racines Git/worktrees, projection canonique, sessions et passerelle. | Refus d'accès, révocation de flux, isolation et reprise vérifiés avec DB/services réels. |
| 2 — Panneau commun | Unifier sélection Document/code, événements et historique réouvrable ; conserver le comportement documentaire et protéger tous les brouillons. | Parcours document → dépôt → document, ouverture/réouverture, erreurs et événements tardifs vérifiés. |
| 3 — Agents développeurs | Enregistrement avant travail, `repository_show`, publication pendant une Task liée, contexte du message et skill runtime. | Agent exécutant une Task SSH visible dans la discussion avant sa fin, sans nouveaux droits implicites. |
| 4 — Édition humaine et Git | Sauvegarde réelle, réutilisation de l'identité/configuration Git de la console et des clés SSH de forge, branches/commit/pull/push/rebase et traitement natif des changements externes. Protection des buffers lors des transitions du panneau. Identité humaine distincte et terminal complet si simples à intégrer. | Parcours Git complet sur un remote synthétique avec l'identité partagée autorisée ; changements SSH visibles et conflit de sauvegarde traité comme dans l'IDE standard, sans mécanisme collaboratif ajouté. |
| 5 — Consoles externes et livraison | Préparation distante, tunnel, profils de consultation/édition, compatibilité Git/worktree, documentation FR/EN, licences et qualification élargie. | Même parcours sur une cible externe préparée, puis validation de l'ensemble avant publication. |

Le prototype est du code de développement, pas une intervention en production. Les lots
peuvent être livrés progressivement ; un état partiel doit préciser les capacités disponibles.
Pas de chiffrage calendaire fiable avant le lot 0, notamment pour le pont iframe et les
profils en lecture seule sur cibles externes.

## Critères de réception et vérification

| Garantie observable | Vérification attendue |
|---|---|
| Même code que l'agent | SSH crée/modifie/supprime des fichiers synthétiques ; l'IDE montre fichiers et diffs sans commit/push ni copie. |
| Git complet pour la revue | Fichiers nouveaux, changements préparés/non préparés, renommages, suppression, branche, HEAD et worktree lié. |
| Gestion Git humaine | Dépôt synthétique déjà configuré avec remote SSH : créer/changer une branche, sélectionner des fragments, commiter avec l'identité existante, fetch/pull/push, rebase et résoudre un conflit sans nouvelle configuration humaine obligatoire. Refus remote sans credentials/droits appropriés ; clés privées absentes des réponses navigateur. |
| Terminal complet si livré | Exécuter un test et relancer un service synthétique dans l'environnement Console attendu avec les permissions existantes. Sans ce complément, vérifier les commandes Git et décrire les capacités effectivement disponibles. |
| Panneau partagé | Document/code alternent dans le même espace, avec discussion et brouillons conservés, desktop et mobile. |
| Affichage pendant une Task | La Task liée présente le dépôt pendant son exécution ; une Task sans room ne publie rien dans une autre discussion. |
| Isolation des demandes | Autre room, round remplacé, réponse tardive, double ouverture et reconnexion n'appliquent pas une ancienne cible. |
| Consultation protégée | Tentatives d'écriture par sauvegarde, Git, terminal et extension échouent ; l'agent continue à écrire normalement. |
| Édition réelle et changements externes | Sauvegarde humaine visible depuis SSH ; changements SSH visibles dans l'IDE ; fichier propre actualisé et conflit de sauvegarde sur buffer modifié traité par les mécanismes natifs. Tester aussi suppression/renommage et documenter les limites. |
| Git pendant le travail partagé | Index partagé visible ; changement de branche/rebase humain répercuté dans le dépôt utilisé par l'agent, avec le comportement natif de l'IDE pour les buffers ouverts. |
| Accès et révocation | Refus croisés entre utilisateurs/agents, chemin/symlink interdit, session expirée, WebSocket déjà ouvert et ancien lien. |
| État non sauvegardé | Bascule, fermeture, timeout du pont, mode changé et perte réseau ne détruisent pas silencieusement le buffer. |
| Charge bornée | Plusieurs lecteurs/espaces, réouvertures et pannes : mesurer instances, mémoire, CPU, trafic et libération des sessions. |
| Console externe | Même contenu, tunnel coupé, clé hôte changée, IDE absent et mode protégé indisponible : erreur explicite et chat utilisable. |
| Liaison à la cible | Même Connection modifiée, répertoire remplacé/déplacé et serveur refusant le forwarding : session invalidée, aucune redirection implicite ni copie de secours. |
| Appel MCP simple | Un seul `repository_show` avec le répertoire autorisé ouvre le dépôt ; les doublons concurrents ne créent pas plusieurs espaces ou instances équivalents. |

Étendre d'abord les tests existants des garanties du panneau ; tester le composant réel
et conserver quelques E2E avec code-server réel. Les assertions portent sur fichiers,
actions et conservation, pas sur l'ordre des boutons ou des fragments Vue/CSS.
Fixtures intégralement synthétiques ; mesures et diagnostics dans `artifacts/`.
Chiffrer le délai d'actualisation et l'empreinte du runtime dans les mêmes conditions ;
ne pas annoncer un temps réel ou une optimisation sans mesure.

Lors de l'implémentation : tests ciblés via les cibles Make, puis `make typecheck`,
`make architecture-check`, suites proportionnées et revue des modes de panne.
Mettre à jour les parcours utilisateur FR/EN, les flux et le catalogue des tests avec
le comportement réellement livré. Régénérer les cartes par `make project-context`,
exécuter `make docs-prepare`, puis `make validate` avant publication sans CI.
Lire les résultats complets ; finir par `git diff --check`. Aucun commit ou déploiement
n'est autorisé par la seule création de ce plan.

## Références vérifiées

- [Flux de messagerie actuel](../../docs/fr/architecture/flows/messaging.md).
- [Catalogue de tests fonctionnels](../../docs/fr/dev/functional-tests.md).
- [Console SSH embarquée](../../docs/fr/components/ssh-executor.md).
- [Accès et reverse proxy code-server](https://coder.com/docs/code-server/guide).
- [FAQ code-server : extensions, différences et configuration](https://coder.com/docs/code-server/FAQ).
- [Git dans VS Code](https://code.visualstudio.com/docs/sourcecontrol/overview) : opérations natives, complétées par le terminal.
- [Discussion upstream sur la communication iframe/hôte](https://github.com/coder/code-server/discussions/6575) : pas de pont prêt à l'emploi annoncé ; qualifier la version retenue.
- [Git worktree et métadonnées communes](https://git-scm.com/docs/git-worktree).
- [Forwarding AsyncSSH](https://asyncssh.readthedocs.io/en/stable/#local-port-forwarding),
  [configuration OpenSSH](https://man.openbsd.org/sshd_config).
- [Licence code-server](https://github.com/coder/code-server/blob/main/LICENSE),
  [licence VS Code OSS](https://github.com/microsoft/vscode/blob/main/LICENSE.txt),
  [licence Galaris](../../LICENSE-FR.md).
