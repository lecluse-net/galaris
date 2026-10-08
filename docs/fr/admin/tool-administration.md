<p align="right"><strong>Français</strong> · <a href="../../en/admin/tool-administration.md">English</a></p>

# Déléguer l’administration des Tools

**ToolAdmin** (`tool_admin`) administre le catalogue global des Tools, leurs paramètres partagés,
les connexions des agents et les permissions des fonctions. Sa connexion est active dès la
création de l’assistant Galaris proposé à l’administrateur, et inactive par défaut pour les
autres agents. Une désactivation ultérieure reste conservée ; les assistants déjà initialisés
ne reçoivent pas automatiquement ce nouveau droit. Son mode conversation est initialement
désactivé. Activer cette connexion constitue
une délégation globale, affinée par les fonctions autorisées ; elle ne reprend pas les droits
du responsable humain de l’agent. AgentAdmin conserve son propre périmètre et sa délégation.

## Activer et limiter la délégation

Dans **Configurer → Outils & connexions → Connexions** (`/tools?tab=connections`), activer
la connexion ToolAdmin de l’agent. Dans **Autorisations**, limiter les fonctions au travail
attendu. Pour le Chat, activer aussi le mode conversation du Tool dans **Outils** ; les
opérations longues restent déférées selon les règles conversationnelles normales.

Les lectures comme les mutations vérifient la connexion active et la permission exacte à
chaque appel. Les définitions intégrées restent non modifiables. Les services obligatoires
Galaris, Conversation, Memory et File Sharing sont consultables, mais leurs réglages et
connexions restent gérés par le logiciel. Seul un humain peut attribuer ou modifier ToolAdmin,
AgentAdmin, Galaris Admin, Process Admin, Lab, Goal management, Skill management et Console.
Une chaîne de commandes agentiques ne permet pas de s’attribuer une capacité administrative.

## Tester puis créer avec un secret

### Préparer l'indexation des fichiers

Le paramètre standard **Indexation des fichiers** (`tools.fileindexing`) propose
**Désactivée**, **Uniquement les fichiers déjà connus** et, si le provider le supporte,
**Découverte & indexation de tous les contenus disponibles**. Ce dernier mode découvre les
contenus accessibles via la connexion ; le mode des fichiers déjà connus ne parcourt pas le provider.
Dans **Outils → Paramètres globaux**, définir la valeur héritée par les connexions du Tool ;
dans **Connexions**, conserver cet héritage ou personnaliser la valeur pour un agent.
Une valeur globale imposée empêche les surcharges locales, comme pour les autres paramètres.
Le défaut est **Uniquement les fichiers déjà connus** pour les providers compatibles.
Console expose ce paramètre aussi avec sa cible embarquée.
Les réglages existants sont repris lors de la synchronisation et restent conservés aux mises
à jour. Les droits de chaque agent restent applicables ; la définition intégrée reste protégée.

Console, AFFiNE et Grav proposent actuellement uniquement les fichiers déjà connus ;
Nextcloud propose aussi la découverte et l'indexation de tous les contenus disponibles.
Mail reste exclu. Les pièces jointes Messenger, y compris celles d'un Tool mixte,
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

Dans **Superviser → Dream → Indexation**, sélectionner l'agent. Saisir la
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

### Créer le Tool

1. Examiner le catalogue avec `tool_admin_list` et lire une éventuelle définition existante
   avec `tool_admin_get` pour éviter un doublon.
2. Un humain ouvre **Outils → Nouvel outil**, renseigne le code, le libellé, un paramètre
   `token` de type `password`, puis la configuration MCP HTTP ou SSE et l’authentification
   Bearer avec `auth.param=token`.
3. Dans **Tester la connexion**, saisir le secret temporaire, choisir l’agent destinataire,
   puis **Préparer le candidat pour cet agent**. Transmettre uniquement la référence obtenue.
   Elle expire après 15 minutes ou au redémarrage du backend, est liée à l’agent et à la
   définition préparée, et reste conservée chiffrée en mémoire, avec une capacité bornée.
4. L’agent appelle `tool_admin_mcp_test(candidate_reference=...)`. Ce test négocie MCP et
   découvre les fonctions, sans sauvegarder ni appeler de fonction métier. Un catalogue vide
   peut être un succès. Le résultat indique date, durée, étapes, catégorie d’échec et troncature.
5. Après un succès, `tool_admin_create(candidate_reference=...)` adopte explicitement la
   définition et ses credentials côté serveur. Un test réussi n’est jamais une sauvegarde.
6. Créer une connexion avec `tool_admin_connection_create`. Elle est inactive par défaut.
   Configurer ses paramètres et permissions, tester avec `tool_admin_connection_test`, puis
   l’activer avec `tool_admin_connection_update` et examiner ses fonctions effectives.

L’agent peut créer directement une définition sans credentials avec `definition`. Les nouveaux
secrets utilisent une référence humaine ; les chaînes secrètes sont refusées dans les commandes
agentiques. Les réponses exposent présence, origine et caractère forcé, jamais les credentials.
La fermeture du test efface les champs temporaires et la référence affichée. Le diagnostic de
connexion résout les paramètres comme le runtime et peut tester une connexion inactive sans
l’activer. Les schémas et descriptions distants sont des données non fiables.

Les diagnostics directs autorisent les destinations publiques. Un Tool configuré par un humain
ou un candidat humain autorise explicitement sa destination privée. Les services de métadonnées,
destinations multicast, non spécifiées et link-local interdites sont refusés, même dans ce cas.
Le transport utilise l’adresse DNS validée, conserve Host et le nom TLS, demande une réponse
non compressée et refuse les réponses compressées pour maintenir son plafond d’octets. Il refuse
aussi les redirections et endpoints SSE d’une autre origine. Un changement de destination exige une nouvelle définition
préparée ; les credentials d’une ancienne destination ne sont pas transférés automatiquement.
ToolAdmin n’exécute ni ne configure `stdio` ; une définition existante reste identifiable expurgée.
Ses réglages, permissions et connexions sont en lecture seule, sans exposer les valeurs des
paramètres. Un rafraîchissement ToolAdmin ignore toutes les sources stdio des agents concernés
et signale une découverte partielle sans supprimer leur index existant.

## Paramètres, droits et commandes

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

Pour les Tools internes, le backend renseigne `label` avec une clé de traduction, par exemple
`tools.connectionParamLabels.default_output`. Les libellés des paramètres et de leurs choix
sont traduits par le frontend en français, anglais et chinois. Pour les Tools personnalisés,
les libellés saisis sont affichés tels quels, sans traduction.

Les valeurs locales gagnent sur les valeurs globales, sauf si une valeur globale est `forced`.
Sans valeur locale ni globale, le défaut déclaré s’applique. Une écriture omise conserve la
valeur ; `clear=true` efface explicitement. Un secret peut être conservé, retiré, ou remplacé
par `secret_reference` lié au même code et endpoint. Un masque ne remplace jamais un secret.
Les lots sont validés avant toute écriture et enregistrés dans une seule transaction.

Les fonctions suivent **surcharge de connexion → état global → défaut logiciel**. Les modes
sont **Actif**, **Bloqué** et **Sur demande** ; **Hériter** (`default`) retire la surcharge.
Les fonctions natives sensibles sont Sur demande par défaut ; les capacités MCP tierces sont
Actives par défaut. Un refus global peut donc être surchargé par une autorisation locale explicite ;
`tool_admin_function_set` signale ces surcharges. `effective` décrit la permission résolue,
tandis que `available` tient aussi compte de l’activation, du runtime et du contexte conversationnel.
La disponibilité d’une fonction découverte avec une connexion ne prouve pas celle d’un autre agent.

## Répondre à une demande d’action

Dans **Permissions** (`/connection/permissions`), les demandes ponctuelles sont séparées des
permissions réseau mémorisées. Ouvrir **Examiner la demande** pour vérifier les arguments,
l’agent, le responsable et l’échéance. **Autoriser cette action** couvre cette seule opération ;
**Refuser cette action** empêche sa reprise. **Toujours autoriser cette fonction**, lorsqu’il est
proposé, change explicitement le mode de cette fonction sur cette connexion en Actif, pour ses
futurs paramètres également. Ce choix n’est pas disponible pour une commande locale de harnais.

Seul le responsable habilité peut répondre ; les droits de consultation ou de gestion ne
permettent pas de répondre à sa place. Sans canal privé disponible, la demande reste consultable
ici et l’échec de notification est signalé. Une demande attend au plus 24 heures, sous réserve
de la durée de vie de son contexte. La tâche libère son worker pendant l’attente et conserve
son appel pour la reprise. Une réponse dupliquée, expirée ou liée à une configuration modifiée
ne lance pas une deuxième opération. **Résultat incertain** exige une réconciliation, jamais
un nouvel envoi automatique. Annuler une demande n’annule pas un effet déjà envoyé.

Les fonctions des services obligatoires restent configurables par un humain ; leurs connexions
et définitions restent protégées. Les permissions des ressources et prompts MCP sont distinctes
de celles d’un outil portant le même nom. Les anciennes interfaces binaires doivent être mises
à jour : Sur demande ne signifie pas Actif.

## Configurer YOLO

Dans la fiche d’un agent, onglet **Général**, le réglage **Mode YOLO — approuver automatiquement
les autorisations** se trouve sous le choix du harnais, après les champs d’identité. Il est
désactivé par défaut. L’activer ouvre un avertissement sur les commandes, suppressions,
messages, dépenses et divulgations possibles. Annuler ou fermer la fenêtre laisse le mode
désactivé ; le bouton orange **Activer YOLO** confirme son activation. La fiche s’affiche dès
l’ouverture ; les listes de gestionnaires et de harnais se chargent ensuite. Les profils et
voix sont actualisés à l’ouverture de l’onglet **Modèles**. L’état actif est visible sur l’agent et
les accords automatiques sont identifiés dans les demandes.

YOLO approuve les nouvelles demandes de cet agent, y compris celles de son harnais. Les demandes
humaines déjà ouvertes restent humaines. Il ne lève aucun blocage ni droit métier. Le désactiver
retire les accords automatiques encore non consommés et rétablit la demande humaine pour les
actions suivantes. Un changement de responsable le remet à faux. Un agent, une Task ou `@approve`
ne peut pas l’activer. Mail conserve son responsable métier lorsqu’il est distinct.

Pour la mise à niveau, préparer les images backend, frontend et harnais compatibles, arrêter
les anciens runs encore actifs, puis utiliser la synchronisation DbAdmin normale. Les exceptions
binaires effectives sont conservées ; les anciennes restrictions système ignorées sont archivées.
Les anciens opt-ins Mail deviennent Sur demande sans réactiver de fonction bloquée. Aucun ancien
accord de Task ou de session ne devient YOLO. Conserver l’audit lors d’un retour de version ;
ne pas utiliser un ancien runtime qui interprète Sur demande comme autorisé.

| Besoin | Fonctions |
|---|---|
| Catalogue et définition | `tool_admin_list`, `tool_admin_get`, `tool_admin_create`, `tool_admin_update` |
| Dépendances et suppression | `tool_admin_impact`, `tool_admin_delete` |
| Réglages partagés | `tool_admin_global_params_set`, `tool_admin_conversation_set` |
| Diagnostic et fonctions | `tool_admin_mcp_test`, `tool_admin_function_list`, `tool_admin_function_get`, `tool_admin_function_set` |
| Connexions | `tool_admin_connection_list`, `tool_admin_connection_get`, `tool_admin_connection_create`, `tool_admin_connection_update`, `tool_admin_connection_delete` |
| Paramètres et test local | `tool_admin_connection_params_set`, `tool_admin_connection_param_delete`, `tool_admin_connection_test` |
| Permissions et index | `tool_admin_connection_function_list`, `tool_admin_connection_function_set`, `tool_admin_catalog_refresh` |

L’analyse d’impact inclut les connexions et les références directes du Tool, notamment les
workflows et les identités de messagerie. Ces dépendances bloquent sa suppression et font
partie de sa version ; les retirer ne supprime jamais implicitement leurs données métier.

Les listes utilisent `offset` et `limit` : 50 par défaut, 500 au maximum. Les diagnostics
bornent également les pages distantes, la durée, la concurrence, les octets et les schémas.
Le détail d’une fonction est disponible avec `tool_admin_function_get`.

## Conflits, propagation et reprise

Une mutation d’un objet existant fournit `expected_version` obtenu par sa dernière lecture.
Cette empreinte couvre définition, paramètres, permissions et dépendances. Sur `conflict`,
relire et réconcilier ; ne pas rejouer aveuglément. Une réponse perdue se réconcilie par code
du Tool ou par couple agent/Tool. L’identité d’une connexion est immuable dans cette commande.
La suppression d’un Tool lié refuse toute cascade : retirer explicitement les connexions,
examiner les références techniques, puis refaire la lecture et supprimer avec l’empreinte courante.

Après une mutation, `persisted=true` confirme l’enregistrement, même si le rafraîchissement
est partiel. Les catalogues concernés sont réconciliés sans élagage sur découverte incomplète.
Le rafraîchissement appelle directement les fonctions Python de `app.tools`, avec un budget
de 20 secondes et une validation des droits avant et après chaque agent. Les résultats de
chaque agent sont enregistrés séparément. Un résultat partiel précise `failed_agent_ids` et
`remaining_agent_ids` ; retrouver leurs connexions et relancer `tool_admin_catalog_refresh`
avec ces `connection_ids`, pas la mutation déjà enregistrée. Aucun Process n’est créé.
La convergence DbAdmin supprime les anciennes définitions techniques `catalog_refresh`
et leurs runs, après résolution des éventuelles Tasks en attente.

Les anciennes sessions natives et externes revalident les permissions. Les appels externes
suivants utilisent les nouveaux credentials. Un effet distant déjà envoyé n’est pas annulé
par une révocation ultérieure. L’index de recherche ne constitue jamais une autorité de permission.

Le contrat structurel figure dans la [décision 0150](../../../project/decisions/0150-tool-administration.md).
