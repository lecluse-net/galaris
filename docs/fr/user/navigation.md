<p align="right"><strong>Français</strong> · <a href="../../en/user/navigation.md">English</a></p>

# Se repérer dans Galaris : menus, écrans et parcours

**Connaissances → Jeux de données** ouvre la bibliothèque JSON. Voir le [parcours des jeux de données](datasets.md).

Ce guide aide à trouver une fonction dans l’application. La
[carte des menus générée depuis le frontend](../architecture/generated/navigation.md)
donne les libellés exacts, routes, descriptions et conditions d’accès de la version livrée.
Les chemins ci-dessous sont relatifs à votre instance Galaris.

Pour comprendre les jalons, les plans, les questions et les reprises, consulter le
[guide des Tasks](tasks.md).

Lors de la première ouverture d'un onglet ou d'un éditeur, un indicateur de chargement
peut apparaître brièvement. Le reste de la page reste utilisable. Si le chargement échoue,
**Réessayer** relance l'ouverture sans recharger la page ni effacer les saisies en cours.
Une erreur persistante laisse la vue en échec ; les autres actions restent accessibles.

## Ouvrir les menus

Une fois connecté, utilisez la barre latérale à gauche. Si elle ne montre que des icônes,
dépliez-la avec le bouton menu. Sur un écran de moins de 1024 pixels CSS de large,
le bouton menu de la barre supérieure ouvre le tiroir de navigation. Les sections restent
les mêmes ; leur visibilité dépend du rôle actif et des fonctions disponibles.
Le logo de la barre latérale mène à l’accueil `/`.

Le menu du compte s’ouvre en cliquant sur votre nom ou avatar, en haut à droite.
Il regroupe le profil, les tokens API personnels, la langue, le thème, les affectations
permettant de changer de rôle et la déconnexion. Le rôle affiché sous le nom permet de
vérifier le contexte courant. Les préférences personnelles de langue et de thème sont
distinctes des **Préférences** d’administration de l’instance.

## Les sections principales

Les documents, fichiers, pièces jointes, objectifs, tâches et sujets proposent aussi leurs
actions au clic droit. Au clavier, placez le focus sur l’élément ou l’un de ses contrôles,
puis utilisez **Maj+F10**. Les commandes disponibles
dépendent de vos droits et de l’état de la ressource ; les confirmations restent applicables.
Les messages et les éléments de la liste des conversations du Chat conservent le menu du navigateur.
Le menu des tâches du Chat permet aussi de déplier ou replier la tâche sans ouvrir sa fiche.
Dans les menus contextuels, les sous-menus s’ouvrent au survol et restent ouverts pendant le passage du pointeur vers
leurs commandes. Le clic, le toucher et le clavier restent disponibles ; un sous-menu voisin
remplace le précédent.
Un clic ou un toucher hors du menu ferme immédiatement toute sa chaîne de sous-menus,
y compris dans sa zone d’origine ou dans un contenu embarqué. L’élément cliqué reste utilisable.

En mode développement uniquement (`APP_ENV=dev`), la rubrique **Développeurs** apparaît juste
après **Administrer**, au même niveau. **Développeurs → Référence graphique**
ouvre `/graphic-reference`. Cette page réunit la palette Solaire, les contrôles de
formulaire, les boutons, une mini-modale intégrée et sa version ouvrable, les dossiers
ouverts/fermés avec leurs tailles, la navigation, les séparateurs redimensionnables,
les états, les contenus et les éditeurs. Les interactions utilisent des données fictives
et ne sauvegardent rien. Le changement de thème est temporaire et le bouton Réinitialiser
rétablit les exemples. Le tableau des glyphes propose une recherche, les illustrations
embarquées et les catalogues d’icônes de documents ; l’inventaire des composants indique
leurs fichiers consommateurs. Les icônes personnelles des utilisateurs ne sont pas chargées.
La route est exclue des constructions des autres environnements.

| Section | Ce qu’on y trouve |
|---|---|
| **Configurer** | Fournisseurs & modèles, Agents, Outils & connexions, Compétences |
| **Agir** | Discussion, Objectifs, Processus |
| **Connaissances** | Documents, Jeux de données, Fichiers, Mémoire, Contacts, Sujets |
| **Superviser** | Tableau de bord, Activité, Dream, Journal des mails, Journal des échecs |
| **Administrer** | Préférences, Laboratoire, Console, Utilisateurs, Équipes, Rôles & autorisations |
| **Développeurs** (mode dev uniquement) | Référence graphique |

Dans la documentation technique, « Chat » correspond au menu **Discussion**,
« Tasks » à l’onglet **Tâches** d’**Activité**, « Topics » à **Sujets**
et « Lab IA » au **Laboratoire**. Ces termes désignent les mêmes domaines ; ils ne sont
pas autant de menus supplémentaires.

## Fournisseurs, modèles et agents

**Configurer → Fournisseurs & modèles** (`/llm`) propose :

| Onglet | Usage | Lien direct |
|---|---|---|
| Fournisseurs | Configurer les services de modèles et consulter leur catalogue | `/llm?tab=providers` |
| Modèles disponibles | Gérer les modèles exposés à Galaris | `/llm?tab=models` |
| Modèles utilisés | Choisir les modèles employés par les usages et profils | `/llm?tab=usage` |

La configuration d’un fournisseur s’enregistre automatiquement après un test de connexion
réussi, à chaque modification lorsqu’il est actif et que les champs requis sont remplis,
ainsi que lors de sa désactivation, même si des champs sont incomplets. Les modifications
d’un fournisseur déjà inactif restent en brouillon jusqu’à un test réussi ou un enregistrement
manuel. En cas d’erreur d’enregistrement, la saisie est conservée ; utilisez **Enregistrer**
pour réessayer.

Les champs de clés API restent masqués pendant la saisie et ne proposent pas d’icône œil.
Les clés enregistrées sont chiffrées et ne sont jamais réaffichées : le champ vide porte
l’indicateur fixe `**********`. Le libellé reste visible en petit à l’intérieur du champ.
Laissez-le vide pour conserver la clé, ou saisissez une
nouvelle clé pour la remplacer. Le petit bouton de suppression dans le champ demande une
confirmation puis supprime la clé enregistrée. Supprimer une clé obligatoire désactive le
fournisseur ; supprimer une clé facultative conserve son état. Ce fonctionnement est commun
à la clé des modèles et à la clé de gestion facultative d’OpenRouter.

Dans la configuration d’un fournisseur compatible, **Consommation et crédits** affiche les
limites remontées par le service : fenêtres et crédits supplémentaires ChatGPT, crédits ElevenLabs, consommation de clé
Mammouth AI et OpenRouter, soldes DeepSeek et crédits SunoAPI.org. Ces données s’actualisent
automatiquement toutes les cinq minutes tant que le panneau est ouvert. **Actualiser les limites**
relit le service sans génération. Le panneau précise si les chiffres concernent le compte
entier ou la clé API ; ils incluent ses usages hors de Galaris. Une jauge apparaît seulement
lorsqu’un plafond permet de calculer un pourcentage. Les montants conservent leur unité,
les zéros et les dépassements ; une erreur peut être retentée. Les quotas de l’application
Mammouth sont distincts de ses crédits API. OpenRouter affiche uniquement le montant restant,
sans jauge ni pourcentage calculé sur les achats cumulés. Sans clé de gestion, ce montant
concerne le budget disponible pour la clé API ; le solde global nécessite une clé de gestion.
Le champ **Clé de gestion (facultative)** permet
d’enregistrer cette seconde clé, chiffrée en base, sans remplacer la clé API des modèles.
Le lien **Créer une clé de gestion OpenRouter** ouvre la page dédiée du fournisseur.
Cette clé dispose de droits administratifs et Galaris l’utilise uniquement pour lire les
crédits et la consommation du compte. Une clé déjà enregistrée reste masquée ; une nouvelle
saisie la remplace, et **Supprimer la clé de gestion** rétablit le montant restant pour la clé API.
La clé ElevenLabs doit autoriser
**User → Read** pour consulter l’abonnement. Une donnée absente reste inconnue.
Pour ChatGPT, le solde des crédits supplémentaires apparaît en crédits, sans jauge, à côté
des fenêtres de l’abonnement. Un solde nul reste affiché ; un montant absent ou un accès
illimité n’est pas présenté comme zéro. Ces crédits sont distincts des crédits de l’API OpenAI.

La configuration Fireworks AI n’affiche aucun panneau de solde ou de consommation,
car le solde prépayé ne peut pas être lu avec la clé API.
La [disponibilité par fournisseur](../dev/provider-quotas.md) distingue les lecteurs intégrés
des API nécessitant une intégration ou des droits supplémentaires.

Dans **Fournisseurs → Ressources disponibles**, la liste **Type de ressources** conserve
les icônes et filtre le catalogue du fournisseur. **Documents / PDF** présente les modèles
de chat déclarant les fichiers en entrée et le texte en sortie. Ajoutez un modèle, puis
affectez-le à **Modèle d’analyse de document** dans **Modèles utilisés**. Si les métadonnées
du fournisseur sont incomplètes, un modèle compatible peut manquer à cette liste.

L’onglet **Modèles utilisés** demande `PARAMS_ACCESS` ou `PARAMS_EDIT`, en plus des
droits nécessaires pour atteindre l’écran. Il est sélectionné par défaut pour les comptes
autorisés ; sinon l’écran ouvre **Fournisseurs**.

### Créer un agent

L'assistant **Galaris** proposé à l'installation porte un avatar dédié : un G bleu et vert
sur un fond de réseau étoilé.
Son [guide de connaissance produit](../admin/product-knowledge.md) est chargé automatiquement
dans ses réponses texte et voix par tours, et ses Tasks internes, sous ses droits existants.
Vous pouvez personnaliser ou supprimer son avatar ; les mises à jour conservent votre choix.

**Configurer → Agents** (`/agent`) contient les onglets **Agents**, **Équipes** et
**Civilités**, selon les droits. Pour créer un agent, ouvrez l’onglet **Agents**, puis
**Nouvel Agent**. Pour modifier un agent existant, ouvrez sa fiche depuis la liste.
Les onglets de cette fiche ne sont pas les onglets de la page : ils regroupent notamment
le général, les modèles et le MCP selon les droits. Le choix du moteur des Tasks appartient
à la fiche de l’agent. Elle s’affiche dès l’ouverture ; les sélecteurs se chargent ensuite.
Dans **Général**, le choix du harnais suit les champs d’identité.
Les profils et les voix sont actualisés à l’ouverture de **Modèles**. L’administration des harnais se trouve dans
**Administrer → Préférences → Harnais** (`/params/harnesses`). Les entrées de harnais
dépendent du catalogue serveur : utilisez le lien affiché, sans inventer leur identifiant.

Si un harnais géré refuse son identité technique (`Invalid runtime principal`), utiliser
**Redémarrer** dans sa supervision pour recréer le runtime avec ses credentials, attendre
sa disponibilité, puis réessayer la Task. **Actualiser** ne demande que la projection des
compétences. La recréation du runtime ne relance aucune action métier.

Dans **Modèles**, choisissez le **Profil principal** et, si nécessaire, un
**Profil secondaire (secours)**, puis enregistrez la fiche. Un principal vide suit le
profil courant ; **Aucun profil de secours** désactive la bascule. Configurez les mêmes
usages dans les deux profils : un usage absent du secondaire n'offre pas de secours.
Le harnais interne utilise le secondaire en cas de surcharge, d'indisponibilité ou
d'erreur d'accès du fournisseur, en conservant les résultats des outils déjà exécutés.
La fiche de l'appel dans **Superviser → Activité → Activité LLM** indique le motif de la bascule.
Un harnais externe passant par la gateway Galaris bénéficie du secours avant la publication
de sa réponse ; un flux déjà transmis conserve son fournisseur. Les modèles choisis
explicitement par l'API de profils et la voix native suivent leurs contrats propres.

Pour déléguer cette administration à un agent, activez sa connexion optionnelle **AgentAdmin**
dans **Outils & connexions**. Elle est active par défaut à la création de l’assistant **Galaris** ;
une désactivation ultérieure est conservée. Ses 34 fonctions restent limitées aux droits et au périmètre de
son responsable humain. Le portrait généré utilise le modèle image de l’appelant ; attendez
la confirmation d’enregistrement, puis rouvrez la fiche de la cible.
Voir le [contrat AgentAdmin](../dev/agent-admin.md) pour les connexions, équipes et harnais.
À l’enregistrement d’un avatar d’agent, l’image est convertie en JPEG et réduite à
500 × 500 pixels au maximum, en conservant ses proportions, sans agrandir les petites images.

Dans la fiche d’un agent enregistré, **Général → Générer un avatar** crée un avatar à partir
de ses noms, du sexe renseigné dans sa civilité, de sa personnalité et de sa fiche de poste.
La forme et le style sont libres, avec une nature d’agent IA visuellement identifiable.
Le canevas reste carré, sans masque ni recadrage circulaire.
Le bouton apparaît uniquement si le **profil LLM par défaut** dispose d’un modèle image
actif et configuré. Enregistrez les modifications de la fiche avant la génération.
L’avatar est demandé en 1024 × 1024, avec les dimensions adaptées au modèle par le service
image existant, puis enregistré comme les autres avatars. Une erreur conserve l’avatar
précédent ; une fiche ou un avatar modifiés pendant la génération empêchent son remplacement.

## Outils, connexions et compétences

**Configurer → Outils & connexions** (`/tools`) sépare trois besoins :

| Onglet | Usage | Lien direct |
|---|---|---|
| Outils | Consulter les Tools et leurs fonctions | `/tools?tab=tools` |
| Connexions | Configurer les connexions associées aux agents | `/tools?tab=connections` |
| Autorisations | Administrer les règles d’accès aux outils et fonctions | `/tools?tab=authorizations` |

Dans **Connexions**, les connexions des agents historisés sont masquées. Les paramètres
s’actualisent après l’enregistrement et à chaque retour dans l’onglet. Les filtres
s’appliquent à la liste chargée ; si son chargement échoue, utilisez **Réessayer**.

Dans **Outils**, **Outils internes à Galaris** regroupe les définitions intégrées protégées par le
logiciel. Les Tools créés ou importés restent dans **Outils personnalisés**, y compris
lorsqu’ils utilisent un bridge dédié comme Nextcloud ou AFFiNE. Le nom du bridge ne
détermine pas l’origine du Tool. n8n n’est pas créé comme Tool standard ; une ancienne
entrée n8n est conservée comme Tool personnalisé avec ses références de processus.

Dans **Autorisations**, chaque fonction dispose des colonnes **Global (tous)** et **Cette connexion**,
avec les choix Activé, Désactivé et Sur demande. La colonne sélectionnée indique la règle applicable.
Choisir un mode global remet la connexion de cet agent en héritage, sans retirer les exceptions
des autres agents. La sauvegarde suit vos choix successifs et signale les erreurs.

Le bridge Grav a été retiré. Il n'est plus proposé dans la configuration du partage de
fichiers ; les anciennes configurations Grav sont refusées comme service inconnu.

Pour les providers de fichiers compatibles et la Console SSH, **Indexation des fichiers**
utilise par défaut **Uniquement les fichiers déjà connus**. Les fichiers et répertoires
retournés par les listes et recherches `file_share` deviennent des fiches privées dans
Memory ; Dream peut ensuite enrichir les fichiers pris en charge. Le mode
**Découverte et indexation** confie aussi le parcours à Dream : un répertoire
par travail, sans LLM, quand Galaris est disponible. **Préférences > Dream > Reparcours des
fichiers** règle l'actualisation périodique, chaque lundi à minuit par défaut.
Les réglages existants, y compris une désactivation explicite, restent conservés. Voir le
[parcours d’indexation](../admin/tool-administration.md).

Dream regroupe les copies identiques d'un fichier **par agent**, grâce au SHA-256 de ses
octets complets. La fiche commune conserve les différents emplacements et un résumé partagé.
Elle conserve aussi une URL principale de visualisation, stable lors de la découverte
d'une copie et actualisée si la source est déplacée ou supprimée.
Dans une fiche ou le détail d'un fichier du graphe, **Emplacements du fichier** donne accès
aux miniatures et au téléchargement de l'original, ainsi qu'à l'aperçu plein écran pour
les formats disposant d'un lecteur. Les droits de
chaque source restent applicables ; une copie modifiée ne remplace pas les autres.

Dans la définition d’un Tool personnalisé, chaque paramètre de connexion peut recevoir un
libellé, une description et une valeur par défaut. Pour un texte ou un entier, **Ajouter un
choix fixe** permet de définir les valeurs proposées et leurs libellés : le formulaire affiche
alors une liste déroulante. Le code technique reste visible sous le libellé. Ces contrôles sont
communs aux connexions des agents, aux paramètres globaux et au test MCP. Sans choix définis,
la saisie reste libre ; les mots de passe restent masqués. Les choix et libellés sont conservés
lors de l’export et de l’import YAML.

Pour déléguer la gestion du catalogue et des connexions, activer explicitement **ToolAdmin**
et suivre le [parcours d’administration déléguée](../admin/tool-administration.md).
L’assistant Galaris reçoit cette connexion active lors de sa création initiale ; une
désactivation ultérieure est conservée.
Le candidat MCP se prépare depuis **Outils → Nouvel outil → Tester la connexion** ; seul
sa référence temporaire est transmise à l’agent, les secrets restent côté serveur.

Les nouvelles demandes d’autorisation présentent l’action et ses paramètres par champs lisibles.
Pour un e-mail, vérifiez les destinataires, les copies et copies cachées, l’objet, le message
et les pièces jointes du mail préparé. Dans **Permissions**, **Détails techniques** permet
de consulter les paramètres JSON. Les contenus HTML restent du texte source inerte.
Une notification abrégée le signale : ouvrez la demande pour lire le contenu complet.

Une demande d’autorisation pour une fonction MCP configurable, par exemple `topic_create`,
propose **Autoriser cette action**, **Refuser cette action** et **Toujours autoriser cette
fonction**. Ce dernier choix mémorise l’accord pour cette fonction sur la connexion de cet
agent, quels que soient les paramètres des futurs appels. Les autres fonctions conservent
leurs règles. Pour redemander une confirmation, remettez la fonction sur **Sur demande** dans
les autorisations de la connexion. Les demandes suivent la langue du responsable (français,
anglais ou chinois), puis la langue par défaut de l’installation si son profil n’en définit pas.
Dans le Chat interne, la phrase « Réponse à… » des réponses par bouton suit la langue de
l’interface, y compris après réouverture ou changement de langue. Le titre de la demande
et le libellé du choix restent ceux de la demande d’origine.

Pour une action locale de tout harnais externe géré (Hermès, DeepSeek Harness, Codex,
Claude Agent ou un harnais OpenAI Messages configuré), choisissez
**Toujours autoriser ce type d’action**. L’accord concerne cet agent, ce harnais et le nom exact
de l’action, quels que soient ses paramètres, y compris dans les tâches suivantes. Par exemple,
autoriser `write_file` n’autorise pas l’exécution de commandes. Les autres demandes déjà en
attente restent à traiter. Dans **Permissions**, la liste **Types d’action autorisés pour les
harnais** permet de révoquer l’accord. Un changement de harnais, de configuration ou de
responsable exige un nouvel accord. Une révocation empêche les prochains départs ; une action
déjà commencée peut se terminer.
Le harnais interne est exclu de ce mécanisme d’accord par type d’action du harnais.

Pour les accès du navigateur, ouvrez la connexion **Navigateur** de l’agent. **Sites publics
autorisés** est le choix initial des nouvelles installations : les méthodes HTTP et WebSocket
publics passent sans accord par site, sous réserve des filtres et refus explicites. Les instances
existantes gardent leur politique ; un paramètre auparavant absent devient **Autorisation par site**.
Le réseau local est bloqué par défaut ; activez `allow_local_network` pour permettre une demande
de permission distincte. Le mode public ne donne aucun accès local.
Le filtre de destinations reste prioritaire. Répondez à la question dans la messagerie ou avec
les boutons du chat interne : accord et refus sont mémorisés par agent, type d’accès et origine
(domaine, protocole, port). Les GET publics ne posent pas de question avec les réglages par défaut.
Le troisième choix **Toujours autoriser tous les sites** mémorise un accord pour tous les
domaines, protocoles, ports et chemins, avec les méthodes HTTP configurées et WebSocket,
pour cet agent. Les nouvelles destinations web ne demandent plus d’autorisation de site.
Les filtres, les refus explicites et les permissions distinctes du réseau local restent prioritaires.
Les boutons **Autoriser et mémoriser** et **Refuser et mémoriser** restent limités au type
d’accès demandé. En mode **Autorisation par site**, supprimez l’accord « tous les sites » pour que
ces accès nécessitent à nouveau un choix. Revenir à ce mode ne crée aucun accord implicite. Les anciens accords limités à un seul site conservent cette portée.
**Superviser → Permissions** (`/connection/permissions`) ouvre **Approbations en attente** :
examinez les demandes sans réponse, puis autorisez l’action, refusez-la ou choisissez un accord
permanent lorsque cette option est disponible. Les demandes d’accès réseau se traitent aussi ici.
Le filtre Agent s’applique à toute la page. Les demandes traitées quittent cette liste ; les demandes
d’action expirées n’y figurent plus. Une réponse ponctuelle ne crée aucune autorisation permanente.

L’onglet **Autorisations permanentes** rassemble les fonctions explicitement autorisées sur une
connexion, les types d’action des harnais et les accès réseau mémorisés autorisés. Vous pouvez y
révoquer un accord ; une fonction MCP revient alors sur **Sur demande**, même si son réglage global
est actif. Les refus réseau restent appliqués mais ne figurent pas parmi les autorisations accordées.
Les traces techniques d’exécution restent conservées pour empêcher les doubles exécutions et permettre
la reprise des tâches ; cette page ne les présente pas comme des permissions.
Pour le navigateur, une action bloquée attend une nouvelle tentative après votre réponse ; les
formulaires ne sont pas resoumis automatiquement.

Pour donner la connaissance du produit à un agent, partez de **Connexions**, trouvez sa
connexion **Galaris Admin**, puis suivez le [guide de connaissance produit](../admin/product-knowledge.md).
Une compétence fournit des instructions ; l’accès effectif aux fonctions dépend aussi
des Tools et connexions autorisés.

**Configurer → Compétences** (`/skill`) contient **Compétences** (`?tab=skills`),
**Auto-apprentissage** (`?tab=learned`) si l’apprentissage est activé, et
**Autorisations** (`?tab=authorizations`) avec le privilège `SKILL_ASSIGN`.
Cette dernière page gère l’affectation des compétences ; elle ne remplace pas les autorisations
des Tools ni les rôles du compte humain.

Ses colonnes **Global (tous)**, **Catégorie** et **Cet agent** proposent Actif/Bloqué et mettent
en évidence la règle applicable. La règle de catégorie concerne l’agent sélectionné.
Une exception de compétence pour cet agent prévaut sur sa règle de catégorie, puis sur le global.
Modifier une règle globale ou de catégorie conserve les exceptions plus spécifiques.

Les compétences fournies **Galaris**, **Galaris Lab** et **Connaissance de Galaris** sont
regroupées par défaut dans la catégorie **Galaris**. La synchronisation classe aussi les
compétences existantes sans catégorie, en conservant vos classements personnalisés.

## Discuter, suivre une tâche et retrouver son résultat

Pour échanger avec un agent, ouvrez **Agir → Discussion** (`/chat`). Pour un objectif
durable, ouvrez **Agir → Objectifs** (`/goal`). Pour lancer un workflow prédéfini,
ouvrez **Agir → Processus** (`/process`). Les analyses de pièces jointes et de gros rapports
restent accessibles depuis la demande faite à l'agent et ne créent aucune entrée dans
ce catalogue de workflows. Le [guide utilisateur](README.md) explique
quand choisir une conversation, une Task ou un Goal.

La page **Processus** affiche ses listes sans attendre le contrôle du moteur externe ni
le catalogue des agents. Les détails d'une exécution et son diagramme se chargent seulement
à l'ouverture de sa fiche ; vous pouvez fermer celle-ci pendant le chargement et la rouvrir.

Les traitements de **Processus** utilisent le moteur de leur définition affectée.
**Préférences → Processus** configure actuellement n8n ; les autres logiciels nécessitent
un bridge installé. Le [guide des moteurs externes](../dev/process-engines.md)
explique cette préparation à l'administrateur et au développeur.

L’accueil de **Discussion** présente toutes les conversations, comme la rubrique
**Conversations** de la fenêtre de chat, puis les agents. Les conversations anciennes et
sans message sont incluses, avec les mêmes filtres et la pagination habituelle.

Pendant une réponse, **Mettre en pause** vous laisse le temps de rédiger un complément.
L’envoi du message reprend automatiquement avec la demande initiale et votre complément.
**Reprendre la réponse** permet de continuer sans nouveau message ; **Arrêter la réponse**
abandonne la réponse en cours. L’outil déjà engagé termine avant la pause ou l’arrêt.

À l’ouverture d’une discussion, les messages s’affichent sans attendre le catalogue des
commandes ni l’état des appels. Les aperçus de liens et les miniatures de documents se
chargent progressivement à proximité de la zone visible ; vous pouvez lire et rédiger
pendant leur chargement, et ouvrir un document avant que sa miniature soit prête.
Les aperçus des pièces jointes, y compris Markdown, se chargent aussi à l’approche de
l’écran. Les aperçus récents sont réutilisés pendant la consultation de l’historique,
avec une mémoire limitée : un ancien aperçu peut se recharger lorsque vous y revenez.
Les médias visibles, ouverts ou en lecture restent disponibles. Changer de discussion
annule les transferts en attente. En cas d’échec, utilisez l’action
de rechargement de l’aperçu ; le téléchargement du fichier original reste disponible.
Dans les longues discussions, la position de lecture est conservée lors du chargement
des messages précédents et du redimensionnement. Après avoir placé le focus dans
l’historique, utilisez **Début**, **Fin** et **Page précédente/suivante** pour parcourir
les messages chargés. **Ctrl+F** (ou **Cmd+F**) rend ceux-ci accessibles à la recherche
du navigateur. Un média en lecture reste actif pendant le défilement.
Les cartes de liens et leurs miniatures sont brièvement réutilisées lors d’un retour
sur un message. Les mises à jour et suppressions documentaires reçues les actualisent,
y compris lorsque le message est hors écran.
Les bulles d’un même agent partagent le chargement de son avatar ; ses initiales restent
visibles tant que l’image n’est pas disponible.
Les avatars sont aussi réutilisés brièvement entre les autres écrans. Un remplacement ou
une suppression effectués dans l’application invalident leur cache ; la déconnexion le vide.

Dans la discussion, supprimer un document le retire immédiatement de la rubrique **Documents**
et ferme son panneau ou sa modale, sans effacer le message en cours de rédaction.
La rubrique **Code source** regroupe les dépôts associés à la discussion et recherche à
l’ouverture ceux du home SSH de l’agent si vous possédez sa Console active. Les chemins
complets depuis le home, tels que `work/galaris`, permettent de distinguer les dépôts de même
nom. Un clic ouvre le VS Code interne ; **Actualiser les dépôts** relance la recherche.
La rubrique se replie comme les autres rubriques de la colonne latérale.

Les listes d’agents sont réutilisées pendant une minute ; les titres, groupes et paramètres
pendant cinq minutes. Les sauvegardes correspondantes invalident le cache concerné.
Pour voir immédiatement un changement effectué depuis une autre session, rechargez la page
avec **F5** : tous ces caches mémoire repartent à vide.

Le suivi se fait dans **Superviser → Activité** (`/task`) :

| Onglet | Contenu | Lien direct |
|---|---|---|
| Conversations textuelles | Historique des échanges courts et des rounds | `/task?tab=conversations` |
| Appels téléphoniques | Historique vocal | `/task?tab=voice` |
| Tâches | Travaux durables, état et détails d’exécution | `/task?tab=tasks` |
| Activité LLM | Appels aux modèles | `/task?tab=llm` |
| Processus | Suivi des exécutions de workflows, avec `PROCESS_READ` | `/task?tab=processes` |

Ne cherchez pas un menu latéral « Conversations » ou « Tâches » séparé : ce sont des onglets
d’**Activité**. **Discussion** sert à échanger ; **Activité** sert à suivre les exécutions.
L’accès à cet écran ne donne pas accès à toutes les conversations ni à tous les agents.

Pour un plan qui doit produire et livrer un fichier, le résultat annoncé par l'agent est
rapproché de la production et de l'envoi enregistrés. Un autre fichier déjà livré ne suffit
pas à valider le plan ; un fichier périmé ou un envoi non confirmé peut laisser le travail
en erreur. Consultez la cause dans le détail de la tâche. Si le fichier final est conservé
et qu'aucun envoi vers la destination demandée n'a été tenté, la reprise peut se limiter à
sa livraison. Un envoi dont l'issue est incertaine doit être vérifié avant toute répétition.

Si vous demandez un bilan enregistré même lorsque le travail échoue, le plan peut conserver
cette action de clôture. La tâche reste en erreur avec sa cause et son bilan ; les travaux
échoués attendent votre décision de reprise. Une reprise manuelle actualise aussi le bilan.

Dans **Activité LLM** et le détail d’une tâche, **Arrêter cet appel LLM** interrompt une
inférence en cours avec le droit `TASK_EDIT`, dans le périmètre des agents gérés.
Confirmez la demande puis attendez son état terminal : l’accusé de réception ne signifie
pas encore que le fournisseur est arrêté. La trace et les coûts sont conservés ; ces
inférences ne proposent pas de corbeille. La tâche ou conversation en attente peut signaler
une interruption. Pour suspendre un travail en conservant sa reprise, utilisez plutôt la
pause de la tâche.

Dans **Préférences → Tâches**, **Durée maximale d’un appel LLM (minutes)** vaut 30 par
défaut. Un appel sans résultat terminal est interrompu et mis en erreur à cette échéance,
même si le modèle continue à réfléchir ou à produire une réponse partielle. Chaque appel
est chronométré séparément : une tâche comprenant plusieurs appels peut durer des heures.
Les changements s’appliquent aux nouveaux appels.

## Documents et connaissances

La [bibliothèque documentaire](documents.md) explique création, dossiers, sous-documents,
listes, traitements groupés et raccourcis clavier.

**Connaissances → Documents** (`/documents`) sert à retrouver et créer les contenus rédigés HTML.
Les jeux de données JSON indépendants se créent et se gèrent séparément dans
**Connaissances → Jeux de données** (`/dataset`), y compris ceux issus d'anciens documents.
**Connaissances → Mémoire** (`/memory`) propose **Liste**
et **Graphe** : ouvrez la page puis choisissez l’onglet, sans supposer un paramètre d’URL.
Les contacts sont dans `/memory/contacts` ; les regroupements thématiques dans
**Connaissances → Sujets** (`/topic`). Le partage d’un lien ne donne pas accès au contenu.

Les anciens liens `/memory/documents` redirigent vers `/documents` en conservant le document
et la pièce jointe sélectionnés. Les anciens formulaires HTML restent accessibles dans la bibliothèque.

Cliquez sur une ligne de sujet, ou sur sa carte mobile, pour ouvrir son contenu.
Dans un sujet, les lignes des tâches, rounds texte, tours audio, espaces, documents et
mémoires ouvrent leur cible dans une modale sans quitter le sujet. Le clavier permet aussi
de les ouvrir. Fermez la modale avec son bouton de fermeture ou en cliquant à l’extérieur.
Le bouton **Retour**, sous le titre du sujet, ramène à la liste.

Une discussion ouverte en modale se cale sur les derniers messages. Remontez tout en haut
pour charger automatiquement les messages précédents, sans perdre votre position de lecture.
Revenez tout en bas pour actualiser les derniers messages, ou utilisez la flèche descendante.

Les documents supprimés disparaissent de la liste des documents du chat. Leurs anciennes
références dans les messages indiquent **Document supprimé**, sans permettre d’ouvrir leur contenu.

Les deux onglets placent l'agent et la recherche sur la première ligne, puis le sujet
et l'interlocuteur juste dessous. Dans **Liste**, la date cible et son bouton d'application
complètent ces filtres. Les champs se réorganisent sur les petits écrans.

Dans **Graphe**, les souvenirs se chargent sans filtre de période ni plafond global de nœuds.
Tous les répertoires connus sont chargés dès l'ouverture, par pages. Le zoom révèle les
fichiers de ces répertoires ; il n'est plus nécessaire de découvrir les sous-répertoires un à un.
En vue d'ensemble, les cartes denses regroupent spatialement les répertoires de chaque
partage. Approcher ou ouvrir un groupe révèle les répertoires déjà chargés.
Sous l'en-tête du graphe, la légende regroupe les types de nœuds, les relations,
puis les repères d'ancienneté et les commandes de zoom et de plein écran.
La taille et l'opacité des nœuds suivent une échelle relative linéaire de dernière activité,
du plus ancien au plus récent dans le graphe chargé. La légende affiche les deux dates
extrêmes ; masquer un type de nœud ne change pas cette échelle. Les nœuds anciens restent
visibles et leurs libellés conservent leur contraste.
Les éléments masqués par un filtre, un repli ou le cadrage contribuent à la taille de leurs
représentants visibles, jusqu'à quatre fois leur diamètre normal. Leur poids se partage entre
les représentants liés les plus proches et remonte les parents masqués ; les enfants connus
mais encore non chargés contribuent aussi. Le compteur d'éléments masqués reste visible même
si certains n'ont aucun représentant. Leur réapparition retire ce poids sans déplacer les nœuds.
Le graphe est uniquement en 3D. Le texte des représentants d'éléments masqués reste toujours
visible, même de loin et en cas de chevauchement. Si WebGL est indisponible, un message permet de réessayer.
L'actualisation automatique applique les ajouts, modifications et suppressions en arrière-plan,
toutes les cinq minutes quand l'onglet est visible. Elle conserve la caméra, les positions,
les filtres et les branches ouvertes, y compris après reconnexion. Les dossiers déjà chargés
sont aussi actualisés. Une erreur temporaire laisse le graphe utilisable ; les changements
de session ou de droits d'accès continuent à retirer les données protégées.
En vue éloignée, les titres privilégient les nœuds structurants et les plus connectés.
Les symboles ont deux tailles de base : éloignée et proche. À partir du zoom proche,
zoomer davantage écarte leurs positions sans les agrandir. Les autres titres restent filtrés pour
éviter les superpositions, y compris au zoom maximal ; le survol ou la sélection les révèle.
Les souvenirs ayant exactement les mêmes relations avec des sujets, contacts ou autres
ancres structurantes sont regroupés avec un compteur. Seuls les nœuds visibles sont dessinés.
Le dézoom minimal correspond au graphe entier ajusté à la fenêtre, toujours centré après
déplacement ; le zoom peut atteindre un million de fois ce cadrage. Les aperçus grandissent
plus tard, selon l'espace entre voisins, jusqu'à la taille réelle en pixels de la miniature.
Masquer une nature réorganise et recadre les éléments restants ; réafficher toutes les natures
restaure les positions enregistrées.
Les répertoires racines gardent leur titre visible même en vue éloignée. La mémoire enregistre
le libellé du Tool comme titre, ou son schéma sans libellé, par exemple `nextcloud://`.
Les anciens titres « . » et « / » sont corrigés lors de la synchronisation ; les titres
personnalisés valides sont conservés. Le graphe utilise ce titre enregistré.

Dans **Liste**, les documents, pièces jointes et fichiers indexés affichent leur miniature
lorsqu'elle est disponible. Un clic sur la ligne ou la carte ouvre la fiche ; les droits
d'écriture déterminent si son contenu peut être modifié.

Dans **Liste**, modifiez **Date et heure cibles** puis appliquez le filtre pour consulter
les souvenirs correspondant à cette date. La saisie et les correspondances utilisent le
fuseau global configuré dans Galaris (`TZ`), même si votre navigateur utilise un autre fuseau.
Les champs temporels d'un souvenir n'ont aucun sélecteur de fuseau.

La fiche d'un item sépare **Mémoire**, **Liens et relations** et **Historique**.
Dans **Mémoire**, les aperçus des contenus associés précèdent les mots-clés et le contenu ;
la temporalité utilise des champs compacts. Le titre affiche la nature du souvenir,
la dernière activité, le nombre d'accès et la révision. Une suppression protégée y apparaît
en badge d'avertissement avec son explication en infobulle.
Les souvenirs autonomes sont privés à leur agent, sans titre à saisir ni partage.
Dream fusionne automatiquement les doublons compatibles pendant l'inactivité lorsqu'ils
atteignent le seuil de similarité configuré, fixé initialement à **92 %**. Ce seuil se règle
dans **Préférences > Mémoire** ; la fusion n'a plus de choix de mode. Les anciens modes sont
retirés à la mise à jour, en conservant le seuil personnalisé. Désactiver Dream suspend ce
traitement avec les autres travaux d'entretien.
Dream peut aussi retenir un fait durable issu d'un message audio transcrit ou d'une pièce
jointe déjà analysée dans une Task liée à la conversation. Il conserve les preuves et leurs
limites de couverture ; une pièce jointe non analysée ne suffit pas à produire un fait.
Une preuve arrivée plus tard peut compléter les souvenirs. Pour les nouveaux souvenirs issus
de ce traitement, retrait de la source, correction de la transcription ou révocation de la
connexion retirent le fait du rappel s'il n'a aucune autre provenance indépendante valide.
Pour un document, ce contenu est une synthèse facultative : **Ouvrir le document**
ouvre une seconde modale pour modifier son titre, son contenu complet et son partage,
en conservant la fiche mémoire et son brouillon. Cette mémoire ne peut pas être oubliée
séparément : supprimer le document depuis son éditeur supprime aussi sa synthèse et son
historique. Retirer le partage la retire des mémoires de l'agent concerné, tout en la
conservant pour le propriétaire et les autres lecteurs autorisés. Les pièces jointes et fichiers indexés
s'ouvrent en plein écran lorsqu'un lecteur prend en charge leur format ; les fichiers audio
ont un lecteur directement dans leur aperçu. Les documents Office, tableurs et autres
formats sans lecteur conservent leur miniature lorsqu'elle est disponible et proposent
uniquement le téléchargement de l'original, sans plein écran. Une indication
signale si le document a changé depuis la synthèse. La recherche utilise toujours
le document complet et la synthèse et retourne un seul résultat.
Une ressource verrouillée affiche **Lecture seule** comme état, sans commande de verrouillage.
Le document et sa fiche mémoire partagent les mêmes mots-clés. Vous pouvez les modifier
depuis les deux fiches avec les droits du document. Une modification actualise l'autre
fiche ouverte sans perdre son brouillon de contenu et ne crée pas de version de synthèse.
Si les mêmes mots-clés ont changé ailleurs pendant votre saisie, l'enregistrement signale
un conflit et conserve votre brouillon. Les anciennes versions gardent leurs mots-clés historiques.
Les actions Dream et les autres boutons partagent une rangée alignée à droite dans le pied
de la fiche. Chaque bouton conserve son contenu sur une ligne ; la rangée peut se répartir
sur plusieurs lignes selon la largeur disponible.
Fermez la fiche avec la croix ou l'arrière-plan ; elle ne propose plus de bouton Annuler.
**Liens et relations** regroupe la provenance, les voisins du graphe
et les relations explicites. Vous pouvez y ajouter une relation selon vos droits.
Le passage d'un onglet à l'autre conserve le brouillon ; **Enregistrer** reste disponible
dans les deux premiers onglets.

Un clic sur un nœud ouvre sa modale directement. Elle conserve les métadonnées du graphe
(nature, dernière activité, nombre d'accès) et la navigation vers ses voisins,
y compris les dossiers et conversations. Le bouton de fermeture ou l'arrière-plan ramène au graphe.

La modale propose des boutons pour les traitements Dream compatibles avec le nœud :
générer sa description, **Régénérer la miniature** d'un fichier, d'une pièce jointe ou d'un
document HTML, analyser un PDF ou document Office avec le modèle
documentaire, vérifier les souvenirs ou **Synchroniser les liens du graphe**. Pour un
document, cette dernière action actualise ses pièces jointes, ses références et ses liens
vers les dossiers. Pour un dossier, elle actualise les dossiers et leurs liens parent-enfant
dans toute votre arborescence. Ces boutons
exigent un droit d'édition Mémoire et la propriété de la ressource. Ils déclenchent le
traitement immédiatement, même lorsque Dream automatique est désactivé ou en attente.
Une nouvelle analyse remplace la description générée ; les notes personnelles des fichiers
du catalogue et l'historique restent conservés. La régénération d'une miniature relance
le rendu même si une image existe déjà ; un échec conserve l'image précédente.
Enregistrez vos modifications avant de lancer
une action. Un échec peut être retenté et une modification concurrente prévaut sur l'analyse.

Le graphe replie les branches d'au moins huit feuilles exclusives avec un compteur. Zoomez,
cliquez sur le groupe pour voir les éléments, puis dézoomez
pour les replier. Les nœuds partagés restent visibles. Jusqu'à 600 items chargés, le premier
placement est animé. Les positions sont ensuite enregistrées en arrière-plan, y compris
celles des nœuds masqués ou repliés. À la réouverture, les nœuds connus retrouvent leur
place et les nouveaux se placent autour des ancres existantes. Chaque utilisateur conserve
ses propres positions, natures masquées, branches ouvertes et cadrage, pour chaque agent
et contexte de recherche/Topic/contact. Les nouveaux nœuds d'une nature masquée restent
masqués. Un état enregistré invalide ou incompatible est automatiquement abandonné : le
positionnement est reconstruit et enregistré, sans modifier les données Mémoire. Une erreur
réseau permet de réessayer sans fermer ni déplacer le graphe ; les sauvegardes reprennent
aussi lors des interactions suivantes.
Le bouton **Réinitialiser le positionnement**, à gauche d’**Actualisation auto**, abandonne les
positions enregistrées pour le contexte courant, recalcule le placement automatique et
recadre la vue. Les filtres de types restent actifs ; le nouveau placement est enregistré
pour les prochaines ouvertures.
Le zoom, le dépliage et la fermeture du détail conservent les positions. Le dézoom allège
aussi les liens et les titres. Les grandes cartes placent les éléments près de leurs ancres
avant stabilisation, en chargeant toutes les pages correspondant aux filtres. Le chargement spatial
et les sous-groupes sont les étapes restantes du
[plan de graphe mémoire à plusieurs niveaux de détail](../../../project/plans/graphe-memoire-multiechelle.md), au statut `partial`.

## Préférences, supervision et compte

**Administrer → Préférences** (`/params`) présente une grille de rubriques et des sous-menus :
Système, Langue, Messagerie, Mémoire, Dream, Voix, Audio, Processus, Tâches et exécution,
Harnais, Recherche, Navigateur, Janus, Instructions et Journaux. La
[carte générée](../architecture/generated/navigation.md) donne la route de chaque rubrique.

Dans **Préférences → Messagerie** et l’onglet **Messagerie** d’un Tool, les indications réseau
permettent de préparer les [tests des passerelles depuis une instance locale](../bridges/telegram-whatsapp.md).
Telegram, Matrix et Nextcloud Talk n’exigent pas d’URL publique Galaris pour les messages.
WhatsApp nécessite un webhook HTTPS public ; son avertissement apparaît avec une adresse locale,
privée ou sans HTTPS. OneBot demande une adresse joignable depuis l’adaptateur, y compris via
un réseau local ou un VPN. Ces avertissements se basent sur l’adresse du navigateur et ne bloquent
pas l’enregistrement.

Dans **Tâches et exécution → Planner**, la planification se règle avec la profondeur maximale et
le nombre maximal de feuilles. Il n’y a pas de plafond distinct sur le nombre total d’étapes.

Les agents exécutent directement les actions simples. Pour une mission longue ou complexe,
ils disposent d'un suivi durable avec jalons et prochaine action, sans fragmenter un livrable
unique. Si le périmètre ou la profondeur attendue reste ambigu, l'agent pose une question dans
la conversation et attend la réponse avant de commencer. Sans réponse à l'échéance, la tâche
signale une erreur ; le silence ne vaut pas choix. Le suivi est consultable avec `task_get`.

Quelques distinctions utiles :

- **Superviser → Dream** (`/dream`) montre l’activité ; **Préférences → Dream**
  (`/params/dream`) règle son fonctionnement.
  La page Dream ouvre **Suivi** par défaut, avec les indicateurs et la progression des actions.
  **Historique** regroupe les opérations et leurs filtres ; **Indexation** permet
  de choisir un agent, consulter ses parcours, lancer une indexation, l'annuler ou relancer les réparations.
- **Superviser → Journal des échecs** (`/incident`) sert au diagnostic ;
  **Préférences → Journaux** (`/params/logs`) configure la conservation et les purges.
- **Administrer → Laboratoire** (`/lab`) regroupe l’analyse de tâches et les évaluations
  par mécanisme, filtrées selon les droits. Voir le [guide du Lab](lab-ai.md).
- Le menu du compte ouvre le profil (`/authorize/profile`) et **Mes Tokens API**
  (`/user/tokens`). Il sert aussi à changer la langue, le thème et le rôle actif.
  La gestion des jetons personnels et des jetons MCP des agents exige une session
  web authentifiée. Un jeton API ne peut ni les lister, créer, modifier ou supprimer,
  ni obtenir un JWT web par renouvellement ou changement de rôle, même pour un administrateur.
  Le mot de passe, le profil, l’avatar, le MFA, les aides masquées, le rôle par défaut
  et les préférences personnelles LLM/voix se gèrent également en session web.
  Les jetons API ne peuvent pas créer, modifier ou supprimer un compte via les routes
  d’administration. Les privilèges habituels restent nécessaires dans l’interface web.
- **Administrer → Rôles & autorisations** (`/authorize`) gère les autorisations des
  utilisateurs ; les droits de dialogue avec les agents passent aussi par les
  [équipes](teams.md), accessibles dans `/team`.

## Un menu ou un bouton manque

Vérifiez d’abord le rôle actif dans le menu du compte. La carte générée indique les
privilèges de visibilité : dans une même liste, un seul suffit ; les contraintes du
parent s’appliquent aussi aux sous-menus. Les actions de création, modification, partage
et suppression peuvent demander des droits supplémentaires, contrôlés par l’API.

Certaines entrées ont aussi une condition de disponibilité : **Discussion** peut être
désactivée globalement ; le **Journal des mails** demande un service mail disponible ;
la **Console** dépend de l’exécuteur intégré ; **Préférences → Navigateur** dépend de la
disponibilité du navigateur. Les sous-menus de harnais proviennent du catalogue serveur.
Une section sans entrée visible disparaît. Un lien direct ne contourne aucun droit.

Un agent qui vous guide doit donner le chemin **section → écran → onglet → action**,
avec les libellés de votre langue, et signaler les prérequis utiles. S’il ne connaît pas
votre rôle ou votre configuration, il doit demander le libellé ou message affiché,
plutôt que conclure qu’une fonction n’existe pas. La carte documentaire décrit les
possibilités du logiciel ; elle ne constitue pas une observation de votre session.
Lorsqu'un travail durable est remplacé depuis la conversation, son successeur attend
l'arrêt confirmé des tâches et processus associés. Un arrêt distant incertain reste
en attente ; il ne provoque pas de second lancement. Une Goal active nécessite sa propre
coordination. Les travaux indépendants et vos pauses manuelles sont conservés.
Si une destination ne correspond pas à la demande, l'agent peut demander une précision
sur le même travail avant d'envoyer ou de modifier une ressource.
