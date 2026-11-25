<p align="right"><strong>Français</strong> · <a href="../../en/admin/service-administration.md">English</a></p>

# Déléguer l’administration des Services

Le code `galaris` et le libellé **Galaris** sont réservés au seul Service système Galaris.
Aucun autre code ou libellé de Service ne peut contenir ce nom, quelle que soit sa casse.
**Galaris** fournit la documentation et les diagnostics d’exécution soumis à une portée.
**Chat** fournit le canal interne, les choix en attente, la présentation de dépôts, les appels
vocaux et l’inspection des tours. Dans **Connexions**, ouvrez les réglages Chat de l’agent pour
modifier **Canal interne**. **Préférences → Messagerie** règle sa disponibilité pour l’instance.
Le tableau des permissions de Chat permet de régler la réponse automatique sur les ponts compatibles.

Un **Service** représente un service, par exemple **Ionos**. Ses **protocoles** sont regroupés
par usage : MCP, API, partage, messagerie, Listener, Mail et Calendrier.
Chaque groupe utilise un seul protocole sur ce service : HTTP ou SSE pour MCP,
REST pour API, AFFiNE/Nextcloud/Samba pour le partage, IMAP & SMTP pour Mail, CalDAV pour
Calendrier. Le catalogue présente chaque groupe comme un en-tête, suivi de ses protocoles.
Mail et CalDAV sont des protocoles de fournisseurs optionnels. Le service système **Agenda**
est disponible par défaut pour chaque agent, sans compte externe ; ses fonctions suivent les
permissions ordinaires. L’agenda porte les rendez-vous et rappels, les Goals conservent leurs cycles.
Dans **Permissions → Agenda**, `services.management_scope` délègue la gestion des événements
et rappels de l’agent, de ses équipes ou de tous les agents. La portée par défaut est personnelle.

Dans **Permissions → Contact**, un gestionnaire global disposant du droit de modifier les
connexions peut définir `services.management_scope` pour un agent. `personal` donne accès
à son carnet, `team` ajoute les carnets des agents partageant une équipe active, et
`all` couvre tous les carnets. La réinitialisation remet la portée personnelle. Les permissions
de `contact_list`, `contact_get`, `contact_create` et `contact_update` s’appliquent sur la
connexion Contact de l’appelant. Une adresse créée pour un autre agent entre dans le carnet
utilisé par la politique Mail entrante de cet agent.

Dans **Permissions → Documents** et **Permissions → Tâches**, le même réglage est
indépendant pour chaque connexion. La portée personnelle est la valeur par défaut.
Les outils Documents vérifient le propriétaire d'un document natif et ses droits de lecture
ou d'écriture. Un agent délégué peut administrer le partage d'un document d'agent dans
son périmètre s'il détient un droit d'écriture sur ce document.
Les outils Tâches et les vues agentiques `galaris://task/` utilisent la portée Tâches.
L'agent peut lire les tâches qu'il a demandées. Une cible distincte pour `task_run` exige la
portée équipe ou globale.

Dans **Services → Connexions**, le bouton **Tester** vérifie les paramètres enregistrés de la
connexion sans modifier son activation ni ses autorisations. Enregistrer les modifications
avant de les tester. Le résultat distingue réussite, échec et vérification incomplète par
protocole : MCP découvre les fonctions, Mail vérifie IMAP et SMTP, la console vérifie SSH,
les messageries interrogent leur fournisseur et les agendas découvrent leur source distante.
Le test d’un protocole de messagerie exige une connexion active.
Les partages compatibles vérifient une liste de métadonnées bornée. REST, les listeners et
les transports sans sonde indiquent explicitement que leur disponibilité n’est pas vérifiée.
Pour un service interne, le test vérifie uniquement la disponibilité de ses fonctions.
Dans la fiche d’une connexion exposant des fonctions, l’onglet **Permissions** reprend le
tableau de la page Permissions pour cette seule connexion, y compris inactive. Les décisions
sont enregistrées immédiatement, sous les mêmes droits et avec le même héritage global.
Les colonnes **Global (tous)** et **Local (cette connexion)** permettent de définir la règle
globale du Service ou une exception locale. Modifier le global exige la gestion de tous les agents ;
ce choix remet la connexion courante en héritage sans supprimer les exceptions des autres connexions.
Le catalogue est chargé à l’ouverture de l’onglet ; le bouton de rafraîchissement le recharge.

Dans **Services & connexions → Services**, ouvrez **Outils en conversation** sur la carte
du service. Le réglage est global à tous les agents et requiert le droit d’édition des
Services. Chaque agent voit uniquement les outils admis que sa connexion active expose
et que ses permissions autorisent. Les nouveaux outils partent désactivés. La fiche
regroupe par nom les outils MCP distants annoncés avec les paramètres partagés du
service et par les connexions actives que vous pouvez consulter. **Actualiser** relance
la découverte. Si la liste est incomplète, explorez les connexions suivantes quand le
bouton est proposé ou saisissez le nom exact d’un outil manquant. Un serveur qui exige
des identifiants propres à un compte nécessite au moins une connexion accessible et
autorisée à lister ses outils. Pour un serveur `stdio`, utilisez la saisie du nom exact.
La fiche enregistre les autorisations du Service en base et interroge les catalogues MCP
distants à la demande.
Pour les services intégrés, la fiche affiche tous les outils déclarés par le service,
même sans connexion. La colonne **Autorisé** indique en lecture seule lesquels sont
[admis par Galaris en conversation](../../../project/decisions/0308-conversation-tool-allowlists.md).

Pour une boîte Ionos, créer un service personnalisé nommé **Ionos**, cliquer sur **+**,
puis choisir **IMAP & SMTP** sous **Mail** dans le menu. Renseigner les hôtes IMAP/SMTP,
ports et sécurité dans la section IMAP puis SMTP. Associer les champs d'identification aux
paramètres standards de connexion, créés uniquement via **Nouveau paramètre…** ou l'éditeur
habituel. Un même `login` contenant une adresse mail et un même `password` peuvent servir
à plusieurs champs et protocoles ; SMTP peut aussi utiliser d'autres références.
Enregistrer le Service, puis créer une connexion **Ionos** pour chaque agent avec ces valeurs.
Le paramètre des dossiers autorisés affiche une arborescence à choix multiples après
enregistrement et authentification de la connexion. Les valeurs imposées et surcharges suivent les
règles ordinaires des connexions. Ajouter aussi **CalDAV** sous **Calendrier** si nécessaire :
son onglet propose le type de source, le fuseau, les horaires et le pas des créneaux.
Associer l’URL CalDAV à un paramètre standard de type mot de passe (l’URL peut contenir
un jeton privé), et les identifiants HTTP éventuels à `login` et `password`, réutilisables avec Mail.
Renseigner ensuite les valeurs dans les paramètres ordinaires de la connexion de l’agent :
aucun formulaire de source supplémentaire n’est nécessaire. CalDAV fournit la découverte et la
synchronisation bidirectionnelle des événements iCalendar. Le type `ical` permet un abonnement
en lecture seule. Consultations et modifications sont locales ; une écriture `pending` attend
sa confirmation distante. Les conflits et échecs restent consultables sans écrasement automatique.
La navigation dans les fichiers d'un Service Mail personnalisé conserve les droits Fichiers
génériques, auxquels s'ajoutent les droits Mail. Les anciennes URI `mail://` conservent
leurs contrôles Mail.

Lors d'une mise à jour, DbAdmin convertit les anciens Services intégrés `mail` et `calendar`
en Services personnalisés portant le protocole correspondant. Leurs codes et identifiants,
connexions, activations, paramètres chiffrés, autorisations et historiques restent conservés.
Le libellé peut ensuite être renommé pour désigner le fournisseur. Une installation neuve
ne crée aucun de ces deux anciens Services ; les synchronisations suivantes ne les recréent pas
et ne rétablissent pas un protocole désactivé après migration.
L'ancien code `mail` conserve les URI `mail://` et ne peut pas héberger un partage de
fichiers ou une autre messagerie : créer un Service fournisseur nommé pour ces combinaisons.

Le service **Services** (`service`) démarre actif en mode `usage` pour chaque agent et expose
`services_list` dans les tâches. L’administration du catalogue, des paramètres et des connexions
exige une délégation explicite. Elle suit la portée locale `services.management_scope` et les
autorisations de chaque fonction. L’assistant Galaris proposé par l’installation reçoit la portée
globale sur Services à sa création. Le service **Agent** applique sa propre délégation.

<a id="built-in-service-scopes"></a>
## Services intégrés et portées

Les connexions système sont créées ou réactivées pour chaque agent. Les fonctions gardent
leurs propres modes **Actif**, **Bloqué** et **Sur demande**. La portée ci-dessous concerne
l'accès délégué des agents. Les privilèges de l'interface humaine et les ACL des ressources
s'appliquent séparément.

| Service (code) | Connexion initiale | Portée locale par défaut | Fonctions ou rôle |
| --- | --- | --- | --- |
| Galaris (`galaris`) | Système | Voir Services pour les inspections | Documentation, appels LLM, incidents |
| Chat (`chat`) | Système | `team` pour la communication inter-agents ; voir Services pour les inspections | Canal interne, choix, présentation de dépôts, appels vocaux et inspection des tours |
| Documents (`document`) | Système | `personal` | Partage, révisions, affichage, analyse et cartes mentales |
| Memory (`memory`) | Système | Mémoire privée de l'agent | Mémorisation, rappel des éléments à venir, synthèse et oubli |
| Partage de fichiers (`file_sharing`) | Système | Droits de la ressource source | Fonctions `file_*` et URI canoniques |
| Agenda (`calendar`) | Système | `personal` | Agendas, événements, disponibilité et actions |
| Contact (`contact`) | Système | `personal` | Recherche et gestion des carnets |
| Tâches (`task`) | Système | `personal` | Délégation, suivi et commandes `task_*` et `conversation_task_*` |
| Agent (`agent`) | Active | `usage` | Annuaire, équipes et administration d'agents |
| Services (`service`) | Active | `usage` | Inventaire, administration des services et portée des inspections d'exécution |
| Objectifs (`goal`), Processus (`process`), Compétences (`skills`) | Active | `personal` | Commandes propres à chaque domaine |
| Navigateur (`browser`), Multimédia (`multimedia`) | Active | Permissions de fonction | Recherche Web et navigation, outils image/audio/vidéo |
| Lab (`lab`) | Inactive | Les sources réelles exigent la portée `all` sur Services | Expériences, diagnostics et campagnes Processus |
| Sujets (`topic`) | Sur configuration | Permissions de fonction | Classement thématique |
| Console SSH (`console`) | Provisionnée pour le harnais interne | Compte SSH de la connexion | Exécution et stockage `console://` |

Mail, CalDAV et les messageries externes utilisent des connexions fournisseur. Leurs protocoles
et leurs fonctions restent indépendants du service système Agenda et du canal interne Chat.
Les codes et noms exacts des fonctions sont inventoriés dans la [cartographie du code](../architecture/generated/project-map.md).

## Activer et limiter la délégation

Dans le formulaire d'une connexion administrative, `services.management_scope` propose
`usage` (aucune administration), `personal` (ressources de l'agent), `team` (union de ses
équipes actives) et `all` (global). Cette portée est locale, sans valeur globale ni héritage.
Agent propose seulement `usage`, `team`, `all` et intersecte la délégation avec les
droits et le périmètre du responsable humain ; il interdit les modifications de l'appelant.
Services exige `all` pour les définitions, paramètres et permissions partagés ; `personal`
et `team` délèguent les connexions et les inspections des agents couverts. Objectifs suit
l'agent responsable et Processus les règles de son domaine. Tâches applique sa propre portée.
Les [compétences](../user/skills.md) conservent leur propre distinction entre usage et gestion.

Le registre MCP rattache chaque outil natif à son Service. Une permission enregistrée
sur une autre connexion ne modifie pas la disponibilité de cet outil. Lorsqu’un outil
administre une ressource, la portée se lit normalement sur son propre Service.
Les inspections de Chat et Galaris utilisent la portée commune de Services et gardent
leur permission de fonction d’origine. Le Lab exige la portée globale pour ses sources
réelles. Les outils de protocole utilisent la connexion de la source, avec la délégation
Agenda sur sa connexion système pour les agendas d’autres agents. La communication
entre pairs utilise la politique de la connexion de messagerie.

Seul un humain en session web avec `CONNECTION_EDIT` et gestion globale des agents peut
enregistrer cette délégation. Connexion, portée et équipes sont relues à chaque appel.
Sans réglage local, la connexion utilise la valeur par défaut de son Service.
La sauvegarde de la connexion et de sa portée est atomique.
Les [privilèges humains](privileges.md), les fonctions accordées et les ACL restent distincts.

Dans **Services**, le sous-onglet **Services personnalisés** s'ouvre par défaut, avant
**Services internes à Galaris**. Ils séparent les services que vous ajoutez de ceux fournis par la plateforme. Une création ou un
import affiche automatiquement le sous-onglet du service enregistré. Dans **Connexions** et
**Autorisations**, le filtre **Filtrer par service** affiche **Personnalisé** puis **Galaris**.
Le champ **Service** du formulaire de connexion et le choix de la connexion dans
**Autorisations** reprennent cet ordre. Les badges des listes rappellent cette origine. Les Services intégrés
optionnels restent dans le groupe Galaris lorsqu’ils sont désactivables, mais leur définition
reste protégée. Un bridge dédié ne crée pas de Service standard : les Services utilisant Nextcloud,
AFFiNE ou un bridge de messagerie restent personnalisés. n8n n’est plus créé automatiquement ;
une entrée existante reste personnalisée, avec ses références de processus et son historique.

La liste des services affiche uniquement les capacités en badges à texte et bordure colorés,
sur fond transparent, sans leurs protocoles. Les onglets distinguent les services personnalisés
des services Galaris, sans badge d'origine supplémentaire.
Dans le formulaire **Nouveau service**, le bouton **Ajouter un protocole** apparaît lorsqu'aucun
onglet n'existe. Après un premier choix, il devient un bouton **+** à côté des onglets.
Cliquer sur ce bouton ouvre un menu déroulant avec les protocoles rangés sous leurs groupes.
Choisir un protocole ajoute et active son onglet. Les autres protocoles du même groupe deviennent
indisponibles. Retirer son onglet permet de choisir un autre protocole de ce groupe.
Sans protocole, le bouton **Créer** reste désactivé.
Les libellés standards sont traduits ; les extensions personnalisées conservent leur chaîne.
Il n'y a pas de saisie libre de protocole : les futurs plugins alimenteront le même catalogue.
La migration déduit les sélections des configurations existantes sans modifier les accès.
Les champs des protocoles sont décrits par le catalogue et utilisent les contrôles communs.
Le formulaire conserve les saisies après une erreur ; un mot de passe laissé vide préserve
le secret existant, et l'action d'effacement permet de le supprimer explicitement.

### Supprimer un service personnalisé

Dans **Services → Services personnalisés**, cliquer sur **Supprimer** sur le service concerné.
La confirmation calcule et affiche les données supprimées avec lui : connexions des agents,
paramètres partagés et locaux, permissions, demandes d’accord, comptes OAuth et autres données
dépendantes éventuelles, notamment messagerie et processus. **Annuler**, le bouton de fermeture
et le clic sur l’arrière-plan ferment le bilan sans rien supprimer. Un bilan indisponible
doit être rechargé avant de pouvoir confirmer.

La suppression confirmée est définitive et transactionnelle. Si son périmètre a changé depuis
l’ouverture du bilan, le serveur refuse cette confirmation ; l’interface actualise le bilan
et demande de confirmer à nouveau. Les tâches, objectifs et autres ressources indépendantes
liés par une référence facultative sont conservés sans cette référence. Les données d’autres
services sont conservées. Les données du service externe et les actions déjà lancées chez lui
ne sont pas supprimées ou annulées par cette opération.

Les définitions intégrées protégées restent non supprimables. Le Services MCP conserve sa
règle de suppression sans dépendances ; la cascade décrite ici est une confirmation humaine
de l’interface, sous le privilège d’édition des Services.

Dans **Configurer → Services & connexions → Connexions** (`/services?tab=connections`), activer
la connexion Services de l’agent. Dans **Autorisations**, limiter les fonctions au travail
attendu.

Les lectures comme les mutations vérifient la connexion active et la permission exacte à
chaque appel. Le logiciel protège les définitions intégrées et l'activation des connexions
système. Un humain habilité peut régler les fonctions, les portées prévues et le canal interne
Chat. Seul un humain peut déléguer les capacités de Services, Agent, Processus, Lab, Objectifs,
Compétences et Console.
Une chaîne de commandes agentiques ne permet pas de s’attribuer une capacité administrative.

<a id="mcp-oauth"></a>
## Connecter un serveur MCP avec OAuth

Dans le Service MCP **HTTP** ou **SSE**, choisir **OAuth 2.0** comme type d’authentification.
Dans **Connexions**, ouvrir la connexion active de l’agent, puis cliquer sur **Connecter le compte**.
Se connecter chez le fournisseur et accepter les droits. Galaris conserve le jeton sur cette
connexion. Le parcours habituel ne demande aucun Client ID, scope ou secret.
Si une connexion existe déjà pour cet agent et ce service, le bouton la réutilise avec ses
paramètres enregistrés et la réactive si nécessaire, même si elle n’est pas dans la liste affichée.

À la mise à jour, un Service dont une connexion possède déjà une autorisation MCP passe
à **OAuth 2.0** et conserve les autorisations existantes. Les autres connexions de ce Service
doivent alors autoriser leur propre compte. La méthode peut ensuite être modifiée dans le Service.

Un changement manuel de méthode demande confirmation. Il retire les autorisations MCP OAuth
des connexions du Service et efface les anciens identifiants devenus inutilisés. Les paramètres
encore référencés et les autorisations Agenda sont conservés.

Galaris découvre les possibilités du fournisseur et s’arrête dès qu’une préparation réussit :

1. Il utilise le retour direct vers Galaris et un client déjà connu, les métadonnées publiques
   du client (CIMD) ou l’enregistrement dynamique (DCR), selon les mécanismes disponibles.
   Un accès par `http://localhost:<port>` ou `http://127.0.0.1:<port>` utilise directement
   cette adresse et ne nécessite aucun script, même si `APP_HOST` contient un nom de domaine.
   Le navigateur doit alors tourner sur la machine qui rend Galaris accessible sur ce port.
2. Si ce parcours est refusé pendant sa préparation, il essaie le code d’appareil lorsque
   le fournisseur l’annonce. Ouvrir la page proposée et confirmer le code affiché suffit,
   sans installation. Galaris respecte la fréquence d’interrogation et les ralentissements
   demandés par le fournisseur, puis affiche le compte connecté.
3. Le relais local ci-dessous est proposé seulement en dernier recours, si le retour direct
   est refusé et qu’aucun parcours sans relais ne peut être préparé.

L’enregistrement dynamique commence par un client public, puis essaie les méthodes Basic ou
POST annoncées par le fournisseur si celui-ci exige un secret généré. Les grants et scopes
demandés suivent ses métadonnées. Un fournisseur qui ne publie pas ses méthodes PKCE est
essayé avec S256 ; Galaris ne retire jamais PKCE pour obtenir un accord.

Si aucun enregistrement automatique n’est disponible, la connexion demande les identifiants
d’une application OAuth pré-enregistrée chez ce fournisseur, avec l’URL de retour affichée.
Le secret éventuel est chiffré avec l’accord et n’est pas renvoyé au navigateur.
Les erreurs réseau, les réponses indisponibles, le refus du consentement ou un code expiré
n’entraînent pas de changement automatique de méthode. Les autres connexions restent inchangées.

En cas d’échec, le message reste visible dans la connexion et précise le statut HTTP et
le code OAuth renvoyés par le service lorsqu’ils sont disponibles. **Réessayer** relance
l’action qui a échoué. Les réponses brutes du fournisseur et les jetons ne sont pas affichés.

Si les parcours sans relais sont indisponibles, Galaris essaie un retour local enregistré
à son propre nom. S’il l’accepte, la connexion propose de télécharger
**le relais de connexion**. Sur l’ordinateur du navigateur, lancer `python3 galaris-connect.py`
depuis le dossier de téléchargement (Python 3 requis, aucune dépendance à installer).
Le relais écoute uniquement sur `127.0.0.1:3334`, ouvre le fournisseur puis renvoie le navigateur
vers Galaris. Il se ferme après le retour ou après dix minutes ; si le port est occupé, fermer
l’autre relais et recommencer. Si le navigateur ne s’ouvre pas, utiliser le lien d’autorisation
affiché dans Galaris après avoir lancé le relais.

Le relais reçoit uniquement le code temporaire protégé par PKCE : aucun jeton ni session Galaris
ne lui est transmis. Le nouvel onglet retrouve la demande grâce à une association locale
state/connexion expirant après dix minutes. Les permissions et l’identité de l’initiateur
restent vérifiées par l’API. Galaris peut rester privé : le navigateur doit pouvoir atteindre
son adresse `APP_HOST`, éventuellement via le VPN, et le serveur doit pouvoir joindre le fournisseur.

Si le service refuse aussi le retour local, il renvoie `invalid_redirect_uri`.
Le message indique l’URL exacte, construite depuis `APP_HOST`, suivie de
`/connection/oauth-callback` pour le parcours web, ou l’adresse locale essayée en repli.
Vérifier HTTPS, le nom de domaine et les règles de retour
du fournisseur. Une adresse déclarée uniquement dans un fichier hosts ou un DNS interne
peut fonctionner dans le navigateur tout en étant refusée par le service distant.
Ce code n’identifie pas à lui seul une liste d’autorisation : confirmer le motif auprès
du fournisseur avant de demander un ajout d’URL. Réessayer sans modifier l’adresse ou
les règles du service ne résout pas ce refus.

L'autorisation appartient à cette connexion d'agent. Les jetons et le secret du client
enregistré sont chiffrés et ne figurent ni dans les paramètres renvoyés par l'API, ni dans
les exports YAML. Le renouvellement est automatique si le fournisseur délivre un refresh
token. Une expiration sans renouvellement ou une révocation exige une nouvelle autorisation.
**Déconnecter le compte** supprime les jetons locaux et les demandes en attente ; pour révoquer
aussi l'accord chez le fournisseur, utiliser son propre écran d'applications autorisées.

Un retour expire après dix minutes et ne s'utilise qu'une fois. En cas de refus ou d'erreur,
recommencer depuis la connexion. Une modification de l’agent ou de l’URL MCP invalide
l’ancien accord. Les permissions des fonctions Galaris restent applicables.
Ces méthodes exigent les métadonnées OAuth MCP ; le parcours par code d’autorisation utilise
PKCE S256. Elles ne concernent pas stdio ni les API REST. HTTPS est requis, sauf sur localhost. Un serveur privé peut
utiliser des endpoints OAuth sur son origine ; les autres origines découvertes doivent être publiques.

<a id="rest-api"></a>

## Activer une API REST

Dans **Services → Nouveau service** ou l'édition d'un service configurable, choisir
**Ajouter un protocole → REST**. Un même service peut proposer MCP et REST. L'onglet **REST**
configure l'adresse de base, l'authentification (aucune, Bearer, en-tête, Basic ou paramètre de requête), le délai maximum
et la taille maximale des réponses. Aucun catalogue d'opérations ou document OpenAPI n'est requis.

Saisir directement l'adresse HTTP(S) dans l'onglet **REST**. Elle est commune à toutes les
connexions du service. Le protocole REST démarre avec **Aucune authentification**. Si l’API exige
des identifiants ou des en-têtes supplémentaires, sélectionner les paramètres de connexion
existants ou choisir **Nouveau paramètre…**. Pour Basic, sélectionner un paramètre pour
l’identifiant et un paramètre secret pour le mot de passe.

Renseigner ensuite les valeurs des identifiants et des en-têtes dans **Paramètres** ou **Connexions → Modifier**.
L'héritage, les surcharges, les valeurs imposées, le chiffrement et le masquage existants
s'appliquent. Pour ces valeurs, la définition et l'export YAML conservent uniquement les noms des paramètres.
Une connexion désactivée ou appartenant à un autre agent ne peut pas être utilisée.

Les droits sur les endpoints REST sont exclusivement ceux du token dans le service tiers.
Les permissions MCP **Actif / Bloqué / Sur demande** ne filtrent pas les appels REST.
La façade applicative est disponible pour les futurs consommateurs Code et Process ;
elle n'ajoute ni outil MCP générique ni proxy HTTP public. Les redirections ne sont pas
suivies, les erreurs HTTP sont retournées avec leur statut et aucun appel n'est réessayé
automatiquement. Le suivi de jobs distants et les callbacks feront l'objet d'une évolution.

## Tester puis créer avec un secret

### Préparer l'indexation des fichiers

Le paramètre standard **Indexation des fichiers** (`services.fileindexing`) propose
**Désactivée**, **Uniquement les fichiers déjà connus** et, si le provider le supporte,
**Découverte & indexation de tous les contenus disponibles**. Ce dernier mode découvre les
contenus accessibles via la connexion ; le mode des fichiers déjà connus ne parcourt pas le provider.
Dans **Services → Paramètres globaux**, définir la valeur héritée par les connexions du Service ;
dans **Connexions**, conserver cet héritage ou personnaliser la valeur pour un agent.
Une valeur globale imposée empêche les surcharges locales, comme pour les autres paramètres.
Le défaut est **Uniquement les fichiers déjà connus** pour les providers compatibles.
Console expose ce paramètre aussi avec sa cible embarquée.
Les réglages existants sont repris lors de la synchronisation et restent conservés aux mises
à jour. Les droits de chaque agent restent applicables ; la définition intégrée reste protégée.

Console et AFFiNE proposent actuellement uniquement les fichiers déjà connus ;
Nextcloud propose aussi la découverte et l'indexation de tous les contenus disponibles.
Mail indexe les messages `INBOX` dont le traitement est autorisé et les pièces jointes annoncées,
en mode **Uniquement les fichiers déjà connus**. L'historique de la boîte n'est pas parcouru.
Les pièces jointes Messenger, y compris celles d'un Service mixte,
rejoignent le catalogue lors de leur réception ou de l'import d'historique. Les listes créent une fiche pour le répertoire consulté et chaque fichier ou
répertoire retourné ; les recherches créent des fiches pour leurs résultats. Ces observations
sont journalisées avec les URI canoniques, puis projetées immédiatement en fiches
privées `file`/`directory` dans Memory, recherchables par nom, URI et métadonnées sans
attendre Dream. Une désactivation ou un changement de configuration de connexion retire
les anciennes fiches des recherches ; l'accès au fichier source est également vérifié.
Dream traite le parcours automatique pendant l'inactivité : un travail liste une page directe
d'un répertoire (500 entrées au maximum), puis les sous-répertoires attendent leurs tours.
Le mécanisme **Indexation et enrichissement des fichiers** affiche les travaux en attente,
les répertoires traités et les nouvelles tentatives, sans appel LLM pour la découverte.
Dans **Préférences > Dream**, **Reparcours des fichiers** renouvelle chaque schéma admissible
par défaut chaque lundi à minuit, dans le fuseau horaire de l'application. Les autres choix
sont chaque jour à minuit et désactivé. Un passage manqué est rattrapé au prochain tour
disponible ; un parcours actif ou déjà lancé pour cette échéance n'est pas dupliqué.
Les URI connues sont vérifiées périodiquement
sans parcourir le provider. Seules les listes complètes et les suppressions prouvées retirent
des fichiers du catalogue ; une source inaccessible reste distincte d'une source supprimée.

Ouvrir une fiche dans **Memory**, modifier son titre ou son contenu, puis enregistrer.
Les champs modifiés manuellement sont conservés lors des observations suivantes du fichier.
L'édition porte sur la fiche Memory ; les références source continuent à être actualisées
par le catalogue et les octets du fichier restent chez leur provider.

Dream calcule une empreinte **SHA-256 des octets complets**, sans LLM et indépendamment
de la limite de 32 Mio de l'analyse. Deux fichiers identiques du même agent partagent alors
une seule fiche Memory, un résumé et plusieurs URI, même entre stockage et messagerie.
Les autres agents conservent leur propre fiche. Les notes, titres personnels, sources et
relations sont conservés lors du regroupement. Une copie modifiée rejoint une autre fiche ;
la disparition d'une copie retire seulement son emplacement.

Dans la fiche Memory ou le détail d'un nœud fichier du graphe, **Emplacements du fichier**
affiche les URI et miniatures disponibles. Cliquer sur une carte ouvre l'aperçu et permet
le plein écran ou le téléchargement original. Images, PDF, texte, HTML, audio, vidéo et
modèles 3D utilisent les lecteurs existants. Office et les tableurs peuvent afficher une miniature
de leur première page imprimée ; ils proposent le téléchargement original sans lecteur plein écran.
Les autres formats sans lecteur restent téléchargeables. Chaque accès revérifie la connexion et
la ressource source ; aucun octet n'est ajouté à la fiche Memory. Les aperçus sont bornés
à 512 Mio ; les limites propres aux convertisseurs continuent de s'appliquer.

Dans **Préférences → Fichiers** (`/params/files`), sélectionner l'agent. Saisir la
racine admissible, par exemple `nextcloud://`, et choisir **Indexer maintenant**. Le tableau
montre le nombre d'entrées rencontrées, les répertoires complets et les erreurs ; un run actif
peut être annulé. Une couverture partielle indique une limite de volume, profondeur ou
pagination. Les diagnostics terminaux sont conservés 30 jours. Les erreurs d'observation
sont réparées avec backoff sans rejouer l'opération externe ; **Relancer les réparations**
permet de relancer explicitement celles qui restent en échec. Les options de médias Dream
existantes activent les enrichissements versionnés, qui préservent les contenus personnels.
Dream analyse ensuite les fichiers pris en charge pour enrichir leur description ; les
répertoires restent des fiches de catalogue sans résumé automatique.

Dream prépare également les miniatures des fichiers identifiés et des pièces jointes
documentaires, sans appel IA et indépendamment des options d'analyse des médias.
Les images, vidéos, PDF, Office, HTML, textes et modèles 3D autonomes pris en charge
conservent leur WebP sans perte, au plus 320 × 320 pixels avec proportions et transparence préservées,
sur le stockage durable réparti en sous-répertoires. Rouvrir une ressource dans
le graphe relit ce WebP ; une version modifiée reçoit un nouveau dérivé. Le cache
ne contourne jamais les droits ni une connexion désactivée.

### Créer le Service

1. Examiner le catalogue avec `service_admin_list` et lire une éventuelle définition existante
   avec `service_admin_get` pour éviter un doublon.
2. Un humain ouvre **Services → Nouveau service**, renseigne le code, le libellé, un paramètre
   `token` de type `password`, puis la configuration MCP HTTP ou SSE et l’authentification
   Bearer avec `auth.param=token`.
3. Dans **Tester la connexion**, saisir le secret temporaire, choisir l’agent destinataire,
   puis **Préparer le candidat pour cet agent**. Transmettre uniquement la référence obtenue.
   Elle expire après 15 minutes ou au redémarrage du backend, est liée à l’agent et à la
   définition préparée, et reste conservée chiffrée en mémoire, avec une capacité bornée.
4. L’agent appelle `service_admin_mcp_test(candidate_reference=...)`. Ce test négocie MCP et
   découvre les fonctions, sans sauvegarder ni appeler de fonction métier. Un catalogue vide
   peut être un succès. Le résultat indique date, durée, étapes, catégorie d’échec et troncature.
5. Après un succès, `service_admin_create(candidate_reference=...)` adopte explicitement la
   définition et ses credentials côté serveur. Un test réussi n’est jamais une sauvegarde.
6. Créer une connexion avec `service_admin_connection_create`. Elle est inactive par défaut.
   Configurer ses paramètres et permissions, tester avec `service_admin_connection_test`, puis
   l’activer avec `service_admin_connection_update` et examiner ses fonctions effectives.

L’agent peut créer directement une définition sans credentials avec `definition`. Les nouveaux
secrets utilisent une référence humaine ; les chaînes secrètes sont refusées dans les commandes
agentiques. Les réponses exposent présence, origine et caractère forcé, jamais les credentials.
La fermeture du test efface les champs temporaires et la référence affichée. Le diagnostic de
connexion résout les paramètres comme le runtime et peut tester une connexion inactive sans
l’activer. Les schémas et descriptions distants sont des données non fiables.

Les diagnostics directs autorisent les destinations publiques. Un Service configuré par un humain
ou un candidat humain autorise explicitement sa destination privée. Les services de métadonnées,
destinations multicast, non spécifiées et link-local interdites sont refusés, même dans ce cas.
Le transport utilise l’adresse DNS validée, conserve Host et le nom TLS, demande une réponse
non compressée et refuse les réponses compressées pour maintenir son plafond d’octets. Il refuse
aussi les redirections et endpoints SSE d’une autre origine. Un changement de destination exige une nouvelle définition
préparée ; les credentials d’une ancienne destination ne sont pas transférés automatiquement.
Services n’exécute ni ne configure `stdio` ; une définition existante reste identifiable expurgée.
Ses réglages, permissions et connexions sont en lecture seule, sans exposer les valeurs des
paramètres. Un rafraîchissement Services ignore toutes les sources stdio des agents concernés
et signale une découverte partielle sans supprimer leur index existant.

## Paramètres, droits et commandes

Les formulaires de connexion affichent les paramètres globaux hérités et les valeurs imposées
si vous disposez aussi des droits de consultation ou d’édition des Services. Un droit limité aux
Connexions n’ouvre pas ces valeurs globales ; les secrets restent masqués et la configuration
de transport n’est pas exposée par ce catalogue. Après un échec de rafraîchissement, la liste
des connexions et le diagnostic restent consultables ; réessayez sans recréer la connexion.

Dans le formulaire d'un Service personnalisé, chaque liste de paramètres des drivers propose
**Nouveau paramètre…** en dernière position. Cette action ajoute un paramètre au bloc de droite,
avec un nom unique et le type adapté, puis l'associe au champ courant. Le paramètre et son
association sont enregistrés avec le service ; fermer sans enregistrer abandonne ces ajouts.

Supprimer un paramètre utilisé par une configuration active ou doté d'une valeur globale
demande confirmation et affiche les configurations concernées. **Annuler**, la fermeture
et le clic sur l'arrière-plan conservent le paramètre et ses associations. Après confirmation,
réaffecter les champs concernés avant d'enregistrer le service.

La définition `connection_schema.params` accepte un `label` facultatif par paramètre.
Le formulaire affiche ce libellé avec le code technique et la description. Pour les types
`string` et `integer`, `options` définit des choix fixes ; chaque entrée porte une `value`
(chaîne enregistrée) et un `label` (texte affiché, facultatif). Par exemple :

```yaml
connection_schema:
  params:
    region:
      type: string
      label: Région du service
      default: eu
      options:
        - value: eu
          label: Europe
        - value: us
          label: Amérique du Nord
```

Les valeurs des choix doivent être non vides, uniques et compatibles avec le type. Un défaut
non vide doit appartenir aux choix. Sans `options`, le contrôle habituel reste disponible.
Les connexions, paramètres globaux et tests MCP affichent ces choix ; les écritures locales
et globales refusent une valeur hors liste. L’import/export YAML conserve ces métadonnées.

Pour les Services internes, le backend renseigne `label` avec une clé de traduction, par exemple
`services.connectionParamLabels.default_output`. Les libellés des paramètres et de leurs choix
sont traduits par le frontend en français, anglais et chinois. Pour les Services personnalisés,
les libellés saisis sont affichés tels quels, sans traduction.

Les valeurs locales gagnent sur les valeurs globales, sauf si une valeur globale est `forced`.
Sans valeur locale ni globale, le défaut déclaré s’applique. Une écriture omise conserve la
valeur ; `clear=true` efface explicitement. Un secret peut être conservé, retiré, ou remplacé
par `secret_reference` lié au même code et endpoint. Un masque ne remplace jamais un secret.
Les lots sont validés avant toute écriture et enregistrés dans une seule transaction.

Les fonctions suivent **surcharge de connexion → état global → défaut logiciel**. Les modes
sont **Actif**, **Bloqué** et **Sur demande** ; **Hériter** (`default`) retire la surcharge.
Dans la matrice **Autorisations**, les colonnes **Global (tous)** et **Cette connexion** proposent Activé,
Désactivé et Sur demande. Seule la règle applicable est sélectionnée : une surcharge d’agent
laisse les boutons globaux non sélectionnés, mais cliquables. Choisir un mode global
enregistre cette règle et retire atomiquement la surcharge de la connexion sélectionnée ;
les autres connexions conservent leurs exceptions. Sans règle globale, le défaut logiciel
est affiché si la connexion en hérite. `default` reste la valeur d’héritage dans l’API ;
l’interface revient à cet héritage en sélectionnant une règle globale.
Les choix locaux successifs sont enregistrés dans l’ordre ; un échec est signalé et provoque
une relecture des règles. Leur sauvegarde n’attend pas une découverte MCP distante.
Les fonctions natives sensibles sont Sur demande par défaut ; les capacités MCP tierces sont
Actives par défaut. Un refus global peut donc être surchargé par une autorisation locale explicite ;
`service_admin_function_set` signale ces surcharges. `effective` décrit la permission résolue,
tandis que `available` tient aussi compte de l’activation, du runtime et du contexte conversationnel.
La disponibilité d’une fonction découverte avec une connexion ne prouve pas celle d’un autre agent.

## Choisir l’accès du Navigateur aux sites publics

Dans **Services & connexions → Services**, ouvrez les **Paramètres** du Navigateur.
**Accès aux sites publics** (`public_access_mode`) propose **Sites publics autorisés** (`allow`, choix initial des nouvelles installations)
pour éviter les demandes site par site, ou **Autorisation par site** (`ask`).
Une instance existante conserve ses choix ; si ce paramètre était absent, la mise à jour ajoute
`ask` pour préserver son comportement. Effacer la valeur globale rétablit aussi le repli `ask`.
Le choix peut être personnalisé dans la connexion d’un agent, ou imposé globalement.
Les filtres de destinations et les refus mémorisés par méthode restent prioritaires.
Localhost, loopback et les réseaux privés restent bloqués par défaut ; **Accès au réseau local**
permet seulement de demander leur autorisation séparée. Revenir au mode par site ne conserve
aucun accord implicite du mode public. Les politiques des fonctions du Navigateur restent
configurables séparément dans **Autorisations**.

## Répondre à une demande d’action

Dans **Permissions** (`/permissions`), choisissez l’agent pour afficher toutes les sections
du tableau de bord sans onglets. La recherche porte sur les demandes, les fonctions et prompts
des Services connectés, leurs périmètres, les types d’action connus des harnais et les décisions
de contact ou de réseau. Les skills et les droits des ressources restent sur leurs pages dédiées.
La liste des Services est à gauche ; les fonctions et leurs autorisations apparaissent à droite
pour le Service sélectionné, avec le périmètre et l’activation en tête.
Le sélecteur `services.management_scope` reprend les choix du Service et la valeur locale effective ;
sa modification exige une session humaine, la gestion globale et le droit de modifier les connexions.
Ouvrir **Examiner la demande** pour vérifier les arguments,
l’agent, le responsable et l’échéance. **Autoriser cette action** couvre cette seule opération ;
**Refuser cette action** empêche sa reprise. **Toujours autoriser cette fonction**, lorsqu’il est
proposé, change explicitement le mode de cette fonction sur cette connexion en Actif, pour ses
futurs paramètres également. **Toujours interdire** mémorise un refus sur la même portée.
Pour un harnais compatible, les choix permanents portent sur son type d’action pour cet agent
et restent liés au responsable et à la configuration courante.

Seul le responsable habilité peut répondre ; les droits de consultation ou de gestion ne
permettent pas de répondre à sa place. Sans canal privé disponible, la demande reste consultable
ici et l’échec de notification est signalé. Une demande attend au plus 24 heures, sous réserve
de la durée de vie de son contexte. La tâche libère son worker pendant l’attente et conserve
son appel pour la reprise. Une réponse dupliquée, expirée ou liée à une configuration modifiée
ne lance pas une deuxième opération. **Résultat incertain** exige une réconciliation, jamais
un nouvel envoi automatique. Annuler une demande n’annule pas un effet déjà envoyé.

Une expiration libère l’attente de la tâche, même lorsqu’elle est constatée par une réponse
tardive. Une décision reçue avant la mise en attente d’un tour vocal reste à traiter jusqu’à
sa suspension. Une interruption après l’envoi d’une action place son résultat en état incertain ;
elle ne permet pas de renvoyer automatiquement cette action.
Si une exécution Hermes ayant pu produire des effets devient introuvable, elle se termine
en erreur avec son historique conservé, sans rester en attente ni recommencer automatiquement.

Les fonctions des services obligatoires restent configurables par un humain ; leurs connexions
et définitions restent protégées. Les permissions des ressources et prompts MCP sont distinctes
de celles d’un service portant le même nom. Les anciennes interfaces binaires doivent être mises
à jour : Sur demande ne signifie pas Actif.

## Autorisations explicites

Les actions Sur demande exigent un accord humain ou une autorisation permanente correspondante
par fonction ou type d’action de harnais. Il n’existe plus de mode global d’approbation automatique.
Le changement de responsable invalide les autorisations mémorisées de harnais. Les blocages,
droits métier et restrictions de contexte restent applicables après tout accord.

La synchronisation DbAdmin normale supprime la colonne `agents.yolo` et la table
`agent_authorization_changes`. Les anciens accords automatiques encore non consommés
sont invalidés avant exécution ; l’historique des actions terminées reste conservé.

| Besoin | Fonctions |
|---|---|
| Catalogue et définition | `service_admin_list`, `service_admin_get`, `service_admin_create`, `service_admin_update` |
| Dépendances et suppression | `service_admin_impact`, `service_admin_delete` |
| Réglages partagés | `service_admin_global_params_set` |
| Diagnostic et fonctions | `service_admin_mcp_test`, `service_admin_function_list`, `service_admin_function_get`, `service_admin_function_set` |
| Connexions | `service_admin_connection_list`, `service_admin_connection_get`, `service_admin_connection_create`, `service_admin_connection_update`, `service_admin_connection_delete` |
| Paramètres et test local | `service_admin_connection_params_set`, `service_admin_connection_param_delete`, `service_admin_connection_test` |
| Permissions et index | `service_admin_connection_function_list`, `service_admin_connection_function_set`, `service_admin_catalog_refresh` |

L’analyse d’impact inclut les connexions et les références directes du Service, notamment les
workflows et les identités de messagerie. Ces dépendances bloquent sa suppression et font
partie de sa version ; les retirer ne supprime jamais implicitement leurs données métier.

Les listes utilisent `offset` et `limit` : 50 par défaut, 500 au maximum. Les diagnostics
bornent également les pages distantes, la durée, la concurrence, les octets et les schémas.
Le détail d’une fonction est disponible avec `service_admin_function_get`.

## Conflits, propagation et reprise

Une mutation d’un objet existant fournit `expected_version` obtenu par sa dernière lecture.
Cette empreinte couvre définition, paramètres, permissions et dépendances. Sur `conflict`,
relire et réconcilier ; ne pas rejouer aveuglément. Une réponse perdue se réconcilie par code
du Service ou par couple agent/Service. L’identité d’une connexion est immuable dans cette commande.
La suppression par Services MCP d’un Service lié refuse toute cascade : retirer explicitement les connexions,
examiner les références techniques, puis refaire la lecture et supprimer avec l’empreinte courante.

Après une mutation, `persisted=true` confirme l’enregistrement, même si le rafraîchissement
est partiel. Les catalogues concernés sont réconciliés sans élagage sur découverte incomplète.
Le rafraîchissement appelle directement les fonctions Python de `app.services`, avec un budget
de 20 secondes et une validation des droits avant et après chaque agent. Les résultats de
chaque agent sont enregistrés séparément. Un résultat partiel précise `failed_agent_ids` et
`remaining_agent_ids` ; retrouver leurs connexions et relancer `service_admin_catalog_refresh`
avec ces `connection_ids`, pas la mutation déjà enregistrée. Aucun Process n’est créé.
La convergence DbAdmin supprime les anciennes définitions techniques `catalog_refresh`
et leurs runs, après résolution des éventuelles tâches en attente.

Les anciennes sessions natives et externes revalident les permissions. Les appels externes
suivants utilisent les nouveaux credentials. Un effet distant déjà envoyé n’est pas annulé
par une révocation ultérieure. L’index de recherche ne constitue jamais une autorité de permission.

Le contrat structurel figure dans la [décision 0150](../../../project/decisions/0150-tool-administration.md).
