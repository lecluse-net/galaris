# ToolAdmin — administration déléguée des Tools

Statut : `design` — proposition du 29 septembre 2026, fondée sur les contrats et tests
du dépôt. Ce plan ne décrit pas une fonctionnalité déjà disponible et n'engage pas son
implémentation.

## 1. Résultat attendu et périmètre

Un agent explicitement habilité peut administrer le catalogue des Tools, leurs paramètres
partagés, les connexions des agents et les autorisations des fonctions. Il peut tester une
configuration MCP avant de l'enregistrer, puis vérifier la configuration réellement résolue
d'une connexion. Il distingue toujours « serveur accessible », « fonctions découvertes » et
« fonctions effectivement utilisables par cet agent ».

Créer un Tool intégré optionnel **ToolAdmin**, code `tool_admin`, inactif par défaut,
distinct de `galaris_admin` et du service système `galaris`. L'accès conversationnel reste
désactivé initialement ; son activation suit le réglage existant des Tools optionnels.

Parcours de référence :

1. Examiner les Tools existants pour éviter un doublon.
2. Tester une URL MCP avec son authentification ; obtenir les fonctions et les diagnostics.
3. Créer le Tool avec son schéma de connexion, puis configurer les paramètres partagés.
4. Créer une connexion inactive pour un agent, renseigner ses paramètres et ses permissions.
5. Tester cette connexion, l'activer, puis lire son catalogue effectif.
6. Modifier une configuration ou révoquer une fonction et vérifier l'effet courant.
7. Examiner les dépendances avant de supprimer une connexion ou un Tool personnalisé.

La V1 couvre les serveurs MCP HTTP et SSE, notamment le cas URL + Bearer token, ainsi que
les paramètres et autorisations des Tools intégrés optionnels. Elle peut administrer les
configurations file-share, messenger, listener et task déjà prises en charge par les contrats
existants, avec leurs validations de domaine. Elle ne crée aucun nouveau bridge ou provider.

La création ou modification de commandes `stdio`, leur lancement par le test MCP, l'installation
de logiciels, le déploiement de serveurs et la gestion des rôles/utilisateurs RBAC restent hors
V1. Une configuration `stdio` existante reste identifiable en lecture expurgée. Le support
agentique d'exécutables nécessiterait un périmètre dédié ; le schéma humain existant n'est pas
une autorisation implicite d'exécution pour ToolAdmin. L'import/export YAML n'est pas nécessaire
au parcours initial ; éviter une seconde voie de mutation avant d'avoir qualifié les contrats.

## 2. Socle constaté et écarts à traiter

| Surface actuelle | Réutilisation et limite constatée |
|---|---|
| [Modèle Tool](../../back/app/tools/models.py), [schémas](../../back/app/tools/schemas.py), [service](../../back/app/tools/tool_service.py) | Catalogue, configuration MCP et autres capacités, schéma de connexion, paramètres globaux et accès conversationnel existent. Le code n'est pas modifiable via `ToolUpdate`. |
| [Routes Tools](../../back/app/tools/router.py), [assertions](../../back/app/tools/assertions.py) | CRUD, projections publiques sans secrets et protections des définitions intégrées existent ; une partie des contrôles et de la sérialisation est portée par HTTP. Ne pas appeler les handlers depuis MCP. |
| [Diagnostic MCP](../../back/app/tools/mcp_diagnostics.py) | `diagnose_mcp_connection` teste une configuration non persistée, avec diagnostic DNS/TCP/TLS/authentification/protocole/découverte. La sortie actuelle contient noms et descriptions, pas les schémas complets des fonctions. |
| [Connexions](../../back/app/connection/models.py), [service](../../back/app/connection/connection_service.py), [routes](../../back/app/connection/router.py) | Une connexion par couple agent/Tool ; paramètres locaux, globaux et forcés ; chiffrement et états de fonctions. Le test HTTP de connexion est distinct du diagnostic détaillé des Tools. |
| [Façade Tools](../../back/app/tools/facade.py), [façade Connexions](../../back/app/connection/facade.py) | Les ports actuels n'exposent pas toutes les mutations et projections administratives nécessaires. |
| [Catalogue intégré](../../back/app/tools/mandatory_tools.py), [chargeur MCP](../../back/app/tools/mcp_loader.py), [catalogue](../../back/app/tools/catalog.py) | Groupes natifs, connexion active, restrictions par fonction, runtime et contexte ; contrôle courant des appels natifs déjà montés. |
| [Rafraîchissement](../../back/app/tools/catalog_refresh_service.py) | Réconciliation des catalogues et de l'index, avec résultat partiel et absence d'élagage en cas de découverte incomplète. Ne pas transformer cet index en autorité de permission. |
| [Secrets](../../back/app/tools/secrets.py) | Projections publiques et valeurs littérales chiffrées existent. Les arguments MCP, traces et checkpoints restent à qualifier pour les nouvelles opérations d'administration. |

Deux distinctions sont contractuelles :

- **Définition intégrée / service obligatoire.** Les définitions intégrées sont non éditables.
  Les Tools optionnels intégrés gardent leurs réglages administrables : paramètres globaux,
  accès conversationnel, connexions et fonctions. Les services `galaris`, `conversation`,
  `memory`, `file_sharing` sont obligatoires et leurs mutations restent refusées.
- **Permission globale / surcharge locale.** La résolution actuelle est : surcharge de la
  connexion, sinon état global du Tool, sinon autorisé. `default` supprime une surcharge.
  Un refus global n'est donc pas un veto sur une autorisation locale explicite. Le plan conserve
  cette règle et rend ses conséquences visibles ; il ne change pas silencieusement le RBAC.

Ces constats reposent sur une lecture du code et des tests, sans essai réseau ou recette runtime
réalisés pour ce plan. La suppression d'un Tool lié, l'atomicité des mutations multi-paramètres,
les invalidations et les contrôles des serveurs MCP externes devront être qualifiés ; leur
présence partielle dans les services ne suffit pas à établir la garantie de bout en bout.

## 3. Surface MCP proposée

Les noms ci-dessous appartiennent tous au code `tool_admin`. Les listes sont filtrables et
paginées côté serveur : 50 éléments par défaut, maximum 500 ; toute interface paginée propose
`[10, 20, 50, 100, 500]`. Les mutations renvoient l'état appliqué expurgé, pas un simple « OK ».

| Fonction | Contrat proposé |
|---|---|
| `tool_admin_list` | Catalogue administratif, recherche, filtres intégré/personnalisé/système/capacité. Distinct du catalogue personnel `tools_list`. |
| `tool_admin_get` | Définition publique, paramètres globaux expurgés, capacités et actions autorisées sur la cible. |
| `tool_admin_create` | Créer une définition personnalisée ; code unique, configurations typées, aucun remplacement implicite. |
| `tool_admin_update` | Modifier les champs permis avec précondition de version ; distinguer omission, effacement explicite et secret inchangé. |
| `tool_admin_impact` | Compter et lister de façon paginée les connexions, agents et références concernées ; retourner une empreinte de l'état examiné. |
| `tool_admin_delete` | Supprimer un Tool personnalisé sans dépendances, avec précondition ; sinon retourner les blocages. Aucune cascade globale implicite. |
| `tool_admin_global_params_set` | Écriture partielle des valeurs héritées, indicateur `forced`, effacement explicite ; impact sur les connexions concernées. |
| `tool_admin_conversation_set` | Modifier le réglage d'accès conversationnel d'un Tool optionnel, sans changer ses permissions de fonctions. |
| `tool_admin_mcp_test` | Tester une configuration candidate non persistée ou celle d'un Tool existant, avec authentification résolue côté serveur. |
| `tool_admin_function_list` | Découvrir les fonctions, afficher leur état global et la source/connexion utilisée pour la découverte. |
| `tool_admin_function_get` | Lire le détail borné d'une fonction : description, schéma d'entrée, schéma de sortie et annotations si fournis. |
| `tool_admin_function_set` | Écrire `default`, `enabled` ou `disabled` au niveau Tool ; retourner l'impact et signaler les surcharges locales qui restent applicables. |
| `tool_admin_connection_list` | Filtrer par Tool, agent et activation, y compris les connexions inactives. |
| `tool_admin_connection_get` | Configuration locale et effective expurgée ; origine local/global/défaut et caractère forcé des paramètres. |
| `tool_admin_connection_create` | Créer une connexion inactive par défaut pour un couple agent/Tool existant ; conflit explicite si elle existe déjà. |
| `tool_admin_connection_update` | Modifier l'activation ; identité agent/Tool immuable dans cette commande. |
| `tool_admin_connection_delete` | Supprimer une connexion optionnelle et ses paramètres/états locaux selon les règles partagées, avec précondition. |
| `tool_admin_connection_params_set` | Écriture partielle atomique et validée des paramètres locaux, secrets en écriture seule. |
| `tool_admin_connection_param_delete` | Retirer une surcharge locale et montrer la valeur héritée résultante, expurgée si secrète. |
| `tool_admin_connection_test` | Tester la configuration résolue d'une connexion sans l'activer ni enregistrer des paramètres temporaires. |
| `tool_admin_connection_function_list` | Fonctions découvertes, états local/global, résultat de la cascade et disponibilité réelle dans le runtime/contexte cible. |
| `tool_admin_connection_function_set` | Écrire l'état local à trois valeurs et renvoyer l'état effectif. |
| `tool_admin_catalog_refresh` | Réconcilier les catalogues des agents concernés par un Tool ou une sélection explicite de connexions ; compte rendu complet/partiel et erreurs expurgées. |

Les DTO définitifs seront arrêtés au premier lot. Ne pas inventer d'URI `galaris://tool/` ou
`galaris://connection/` tant qu'aucun provider ne les prend en charge : utiliser les identifiants
typés existants. Le catalogue distant peut varier selon les credentials ; une découverte sous
une connexion ne prouve pas l'existence ou l'autorisation des mêmes fonctions pour toutes les autres.

### Articulation avec AgentAdmin

Le [plan AgentAdmin](tool-agent-admin.md) prévoit déjà `agent_connection_*` et des lectures des
Tools depuis un agent. Conserver ce parcours centré sur l'agent. ToolAdmin porte le catalogue
global, ses paramètres, permissions et diagnostics, avec un parcours centré sur le Tool.
Les deux surfaces doivent appeler les **mêmes services de connexion**, validations, projections
et invalidations. Elles contrôlent chacune leur délégation ; posséder AgentAdmin ne donne pas
implicitement les droits globaux ToolAdmin. Aucun lot ne dépend de l'implémentation préalable
de l'autre plan. Formaliser le contrat commun avant de développer les mutations des deux côtés.

## 4. Délégation et effets administratifs

Proposition de portée : l'activation humaine de `tool_admin` constitue une délégation
d'administration globale des Tools et connexions, affinée par ses fonctions autorisées,
comme les packages administratifs existants. Cette portée doit être indiquée dans la description
du Tool et formalisée dans une décision avant implémentation. Ne pas fabriquer un utilisateur
humain dans un worker ni hériter tacitement des droits du responsable.

- Vérifier l'identité serveur de l'appelant, sa connexion ToolAdmin active et la fonction
  autorisée à chaque appel, y compris sur un serveur déjà monté ; les lectures suivent aussi
  cette règle. Revalider avant l'application d'un effet différé.
- Maintenir les privilèges et périmètres humains existants pour HTTP (`TOOL_ACCESS`,
  `TOOL_EDIT`, `CONNECTION_ACCESS`, `CONNECTION_EDIT`, gestion des agents).
  Les services partagés reçoivent un contexte d'autorisation explicite adapté à chaque entrée.
- Résoudre agent et Tool d'une connexion côté serveur. Ne pas autoriser une cible à partir
  d'un identifiant annexe fourni par le modèle.
- Réserver à l'administration humaine l'attribution et la modification de la délégation
  ToolAdmin elle-même, globalement et par connexion, y compris son accès conversationnel.
  Empêcher aussi AgentAdmin de contourner cette règle. Une chaîne de modifications de paramètres
  ou de permissions ne doit pas permettre à l'appelant de s'accorder les fonctions refusées.
- L'attribution d'autres capacités administratives reste une opération sensible de gestion
  de connexions : la matrice du premier lot doit identifier les Tools qui en portent et fixer
  leur délégabilité, au lieu de les traiter implicitement comme des intégrations ordinaires.
- Préserver les restrictions des services obligatoires et des définitions intégrées dans
  les services communs, pas uniquement dans les décorateurs des routes HTTP.

Les erreurs attendues sont structurées : accès refusé, cible absente, configuration invalide,
conflit, dépendances bloquantes, échec réseau, résultat partiel. Les descriptions et schémas
renvoyés par un serveur externe sont des données non fiables ; ils ne peuvent pas déclencher
une mutation ou modifier la délégation.

## 5. Diagnostic MCP et secrets

Réutiliser le constructeur MCP et le diagnostic actuels, avec une couche de préparation commune
pour les entrées HTTP et MCP. Ne pas réimplémenter l'authentification ou un second client MCP.

Deux modes doivent être explicites :

- **Candidat** : URL, transport HTTP/SSE, méthode d'authentification et paramètres temporaires ;
  aucune écriture de Tool, connexion, permissions ou index. Un test réussi ne sauvegarde rien.
- **Existant** : Tool ou connexion autorisés ; résoudre les secrets et l'héritage comme le runtime.
  Une éventuelle surcharge temporaire doit respecter les valeurs globales forcées et n'est jamais
  persistée. Tester une connexion inactive n'autorise pas l'exécution de ses fonctions métier.

Le test effectue la négociation MCP et `list_tools`, jamais `call_tool`. Un HTTP 200 ou un port
ouvert ne suffit pas. Un serveur MCP valide avec zéro fonction reste un succès de protocole
avec catalogue vide. La réussite est horodatée et décrit l'état testé ; elle ne garantit ni
la disponibilité future ni le succès d'un appel métier.

Retourner `success`, catégorie d'échec, étapes diagnostiques, durée et fonctions découvertes.
Étendre le contrat existant avec un résumé paginé et un détail à la demande pour les schémas,
des plafonds d'octets/fonctions et un indicateur de troncature. Ne jamais présenter une découverte
incomplète comme un catalogue exhaustif. Borner la durée totale, les pages distantes et les
appels concurrents ; fermer les sessions même après annulation.

Pour le cas URL + token, privilégier un paramètre `token` secret et `auth.param`, résolu côté
serveur. L'agent réutilise un secret configuré sans pouvoir le lire. La saisie d'un nouveau
secret passe par les surfaces humaines existantes ou une référence opaque dont le contrat doit
être défini si nécessaire ; ne pas supposer qu'un coffre de références existe déjà.
Un parcours de test avant création doit pouvoir recevoir le secret sans le placer dans le
contexte du modèle : ce point d'entrée sécurisé fait partie du lot diagnostic. Aucune extraction
automatique de token depuis une conversation ou un document.

Les réponses montrent seulement présence/origine/nom du paramètre secret. Qualifier aussi
la non-divulgation dans les arguments tracés, erreurs, checkpoints, URL, headers et exports ;
le chiffrement en base ne couvre pas ces autres chemins. Les valeurs masquées ne doivent jamais
remplacer un secret existant lors d'une mise à jour.

Une destination modifiée ne doit pas recevoir automatiquement le secret d'une autre destination.
Lier l'usage du secret à la cible autorisée et traiter explicitement changement d'origine,
redirections et résolution DNS. Prévoir une politique réseau compatible avec les MCP privés
auto-hébergés, sans blocage indistinct du LAN : destinations internes autorisées explicitement,
refus des services de métadonnées et des destinations interdites, validation à chaque redirection,
pas de transfert d'Authorization vers une autre origine. La délégation d'administration ne doit
pas transformer le diagnostic en accès réseau arbitraire avec credentials réutilisés.

## 6. Cohérence, concurrence et architecture

Implanter ToolAdmin dans les modules propriétaires existants `app.tools` et `app.connection`,
avec rattachement des fonctions de leurs `mcp.py` au même code. Aucun nouveau module métier
n'est nécessaire pour le seul groupe de fonctions. Étendre les façades publiques et extraire
uniquement les orchestrations HTTP nécessaires ; ne pas propager les imports privés historiques.

Inventorier les consommateurs avant extraction : routes Tools/Connexions, UI des trois onglets,
catalogues et recherche, synchronisation intégrée, runtimes MCP, bridges/listeners utilisant
les paramètres et futur AgentAdmin. Préserver leurs protections et notifications.

- Prévoir des préconditions de version/empreinte pour les mises à jour et suppressions,
  vérifiées atomiquement ; l'impact lu précédemment ne doit pas devenir une autorisation périmée.
  `updated_at` d'un Tool seul ne couvre pas ses connexions et permissions : arrêter les unités
  de concurrence au premier lot.
- Valider tout un lot de paramètres avant écriture. Les commits internes actuels de plusieurs
  services doivent être examinés avant de promettre une mutation atomique sous le wrapper MCP.
- Conserver l'unicité agent/Tool sous concurrence et retourner un conflit récupérable. Pour
  une réponse perdue, fournir une lecture de réconciliation par code ou couple agent/Tool ;
  ne pas recréer aveuglément un objet ni annoncer l'absence d'effet sans preuve.
- Refuser par défaut la suppression d'un Tool encore lié. Exiger le retrait explicite des
  dépendances, puis vérifier de nouveau dans la transaction. La suppression de connexion suit
  les règles de nettoyage et de cycle de vie de son domaine ; ne pas laisser un listener orphelin.
- Après mutation, invalider/reconstruire uniquement les catalogues concernés. Une panne de
  rafraîchissement après persistance produit un résultat « enregistré, rafraîchissement partiel »
  avec reprise possible, pas un échec incitant à rejouer la mutation entière.
- Vérifier la révocation sur les serveurs déjà montés et l'usage de nouveaux credentials par les
  appels suivants, tant pour les fonctions natives que pour les MCP externes. Ne pas prétendre
  annuler un effet distant déjà envoyé. Une session ancienne ne doit pas contourner une révocation.
- Le rafraîchissement massif devient un Process durable s'il dépasse le budget d'un appel court,
  avec progression et résultat final. Ne pas garder de verrou DB pendant une attente réseau.

Aucun changement de schéma n'est prescrit par anticipation. Si les versions, références de
secrets ou opérations durables nécessitent une évolution de modèle, la justifier au lot concerné
et utiliser `database`, `back-conventions` et, si pertinent, `core-dbadmin`. Aucune migration
manuelle ni nouvelle dépendance n'est présumée nécessaire.

## 7. Lots et critères de réception

| Lot | Travail | Preuve attendue |
|---|---|---|
| 1 — Contrats | Matrice de délégation, fonctions/DTO, secrets candidats, destinations autorisées, concurrence, dépendances et services communs avec AgentAdmin ; décision structurelle. | Matrice appelant × cible × action et scénarios synthétiques autorisés/refusés ; aucun choix de sécurité implicite avant les mutations. |
| 2 — Parcours de lecture et test | Déclaration optionnelle, catalogue administratif, projections expurgées et diagnostic MCP partagé. | Une configuration non enregistrée réussit la négociation et liste les fonctions ; aucune écriture ni fonction distante exécutée ; échecs classés. |
| 3 — Catalogue et configuration | Création/modification, paramètres globaux, accès conversationnel, impact et suppression protégée. | Création puis lecture/modification/suppression d'un Tool synthétique ; conflits, dépendances et secrets inchangés vérifiés. |
| 4 — Connexions et droits | CRUD des connexions, héritage des paramètres, états globaux/locaux, contrôle de délégation. | Connexion configurée inactive, testée, activée puis révoquée ; projection des droits cohérente et autres agents préservés. |
| 5 — Propagation | Catalogues/index, rotation de credentials, changements de contexte, rafraîchissement et reprise. | Ancien serveur incapable de contourner une révocation ; panne de découverte sans élagage abusif ; résultat partiel exact. |
| 6 — Recette et documentation | Parcours assemblé via un agent, contrôle dans l'UI, FR/EN, cartographie et qualification transversale. | Parcours de référence complet, refus hors délégation, réouverture fidèle et aucun secret dans les traces inspectées. |

## 8. Validation et livraison futures

Étendre les garanties existantes du [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md),
sans écrire un test par wrapper :

- `app/tools/tests/test_router.py`, `test_system_tools.py`, `test_mandatory_tools.py` :
  protections communes HTTP/MCP, Tool inactif initialement, absence de réactivation à la synchro.
- `test_mcp_diagnostics.py`, `test_secrets.py`, `test_global_params.py` et
  `app/connection/tests/test_encryption.py` : succès/vide, erreurs 401/403, DNS/TLS/timeout,
  faux endpoint HTML, schémas volumineux, annulation, secrets masqués et absence d'écriture.
- `app/connection/tests/test_connections.py`, `test_service.py`, `test_function_states.py` :
  unicité, atomicité, héritage forcé, cascade à trois états, restrictions et suppression liée.
- `app/tools/tests/test_live_authorization.py`, `test_mcp_loader.py`, `test_agent_registry.py`,
  `test_catalog_refresh_service.py` : découverte effective, révocation courante, isolement des
  agents, sessions externes, index partiel et reprise. Ajouter la prévention de l'auto-attribution
  via les deux surfaces ToolAdmin/AgentAdmin lorsqu'elles sont présentes.

Les workflows de persistance utilisent la DB isolée et les vrais services ; remplacer uniquement
les frontières externes. Employer un serveur MCP synthétique pour les erreurs et le catalogue
variable selon les credentials. Tester explicitement qu'aucun `call_tool` n'a été envoyé.
La qualification de destinations privées et de rotation ne doit pas utiliser de secrets réels
dans les fixtures ou les rapports versionnés.

Exécuter les suites ciblées via `make tests ARGS='…'`, puis `make typecheck` et
`make architecture-check`. La recette assemblée vérifie découverte depuis un agent délégué,
création, paramétrage, activation, permissions, erreur, reprise, suppression et réouverture dans
l'UI ; vérifier aussi contexte/runtime, erreurs navigateur et requêtes échouées. Si l'interface
de saisie sécurisée évolue, exercer clavier, mobile et fermeture des modales par leur fond.

À l'implémentation, mettre à jour les parcours utilisateur FR/EN Tools/Connexions, le catalogue
fonctionnel et la documentation du skill système Galaris. Exécuter `make project-context`,
`make docs-prepare`, puis `make docs-update` pour l'index de développement dans le cadre de la
livraison. Ne pas annoncer ToolAdmin dans les guides d'usage comme disponible au stade du plan.

Avant publication, `make validate` doit qualifier le snapshot final ; lire le résumé complet.
Terminer par revue des modes d'échec, du diff et `git diff --check`. Rapporter séparément les
contrôles automatisés, les parcours exercés et les limites réseau/runtime restantes. Retirer
le plan après réalisation et transfert des contrats durables vers décisions, documentation et tests.
