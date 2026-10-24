# Audit des privilèges et réorganisation RBAC

Date : 24 octobre 2026. L'inventaire initial ci-dessous porte sur le code après suppression
des anciens privilèges et routes de gestion Hermès, avant réorganisation.

**Contrôle complémentaire :** le [dernier audit](2026-10-24-rbac-final-control.md) confirme
les 109 codes mais reproduit cinq écarts sur Process, Topics, Mail et les libellés des
historiques. Il précise les fonctions encore mutualisées. Le bilan d'implémentation ci-dessous
ne constitue donc pas une qualification exhaustive de leur séparation fonctionnelle.

**État livré dans le dépôt :** le garde central est corrigé et les 24 droits fonctionnels
explicitement confirmés sont implémentés, soit 109 privilèges. La projection unique des rôles,
les politiques API/paramètres/événements et les menus/onglets sont intégrés selon la
[décision 0233](../decisions/0233-functional-domain-privileges.md). La base de développement
est convergée ; rôles, affectations et listes personnalisées sont conservés. Aucun déploiement
en production n'a été effectué. Les sections 1 à 8 conservent les observations de l'audit
initial ; le bilan de réalisation figure à la fin.

## Résultat

Une réorganisation est justifiée. Le problème principal est la répartition des pouvoirs :
des domaines indépendants utilisent les mêmes droits, alors que le Lab dispose déjà de droits
très spécialisés. Le catalogue compte 85 privilèges, dont 22 pour le Lab. Aucun code déclaré
n’est entièrement sans consommateur dans le code applicatif.

L’audit a aussi reproduit un défaut du garde central : des paramètres transmis par le client
peuvent remplacer la politique d’une assertion déclarée par le serveur. Cette correction doit
précéder toute extension du catalogue. Ajouter des droits sur ce socle ne garantit pas leur
séparation effective.

Les fournisseurs et modèles possèdent déjà `LLM_PROVIDER_ACCESS` et `LLM_PROVIDER_EDIT`.
Ils partagent cependant cette paire ; les profils LLM utilisent `PARAMS_*`, et les journaux
d’appels utilisent `TASK_*`. L’absence de codes portant les noms des écrans masque donc plusieurs
situations différentes.

## Méthode et couverture

- Inventaire des déclarations des modules actifs et des usages de production Python/Vue/TypeScript,
  hors tests, imports, traductions et accesseurs générés.
- Import de l’application dans un processus isolé, sans lifespan ni accès aux données métier,
  puis inspection des routes, gardes, assertions et paramètres effectivement enregistrés.
- Lecture des contrats, services et tests des domaines cités dans la demande ; recherche des
  réemplois dans les autres modules.
- Évaluation du véritable helper de visibilité de navigation, avec les contributions actives
  fusionnées et des profils synthétiques. Les prédicats de disponibilité liés à l’installation
  ne sont pas exécutés.
- Reproductions HTTP sur des utilisateurs, rôles, équipes et agents entièrement synthétiques,
  avec PostgreSQL éphémère. Aucune reproduction n’utilise l’application ou les données réelles.

| Mesure | Résultat |
|---|---:|
| Privilèges déclarés | 85 |
| Modules déclarant des privilèges | 22 |
| Privilèges du Lab | 22, soit environ 26 % |
| Enregistrements HTTP | 793 |
| Enregistrements WebSocket FastAPI | 2 |
| Fonctions d’endpoint distinctes, HTTP et WebSocket | 731 |
| Enregistrements HTTP avec garde RBAC | 733 |
| Parmi eux, accès large aux utilisateurs authentifiés | 27 |
| Routes HTTP déclarées publiques | 13 |
| Routes HTTP avec authentification indépendante | 47 |
| Entrées de navigation, y compris sous-entrées | 54 |
| Gardes portant des paramètres de politique serveur | 15 |

Les enregistrements incluent les montages et alias de protocole ; ils ne sont pas un nombre
d’écrans ni de fonctions métier. Les deux WebSockets ont leurs contrôles propres dans
`app.code.gateway` et `bridge.one_bot.router`. Leur absence de décorateur HTTP ne constitue pas,
à elle seule, un défaut d’authentification. Socket.IO possède également ses politiques d’événements.

Les inventaires détaillés et les reproductions restent sous `artifacts/rbac-audit-2026-10-24/` :
matrice des 85 codes, matrice des domaines, navigation, enregistrements de routes et cas synthétiques.
Ce rapport versionné conserve uniquement les conclusions et mesures agrégées.

## 1. Défaut prioritaire : politique d’assertion remplaçable par le client

Priorité initiale : **P0 de la réorganisation, gravité élevée**. Statut actuel : **corrigé**.

Dans [le garde central](../../back/core/authorize/guard_provider.py), les paramètres de la politique
serveur sont copiés puis recouverts par les paramètres de requête et le JSON ou formulaire.
Les paramètres du chemin sont réappliqués ensuite, mais cela ne protège pas les clés qui
décrivent la politique elle-même.

`RequireAllPrivilegesAssertion` lit ainsi une liste de droits potentiellement remplacée par
le client. `OwnUserOrPrivilegeAssertion` lit une configuration de propriétaire et un droit de
repli soumis au même mécanisme. Voir [les assertions](../../back/core/authorize/assertions.py).

| Reproduction HTTP synthétique | Demande normale | Politique altérée côté client |
|---|---:|---:|
| Créer une équipe avec `TEAM_EDIT`, sans `TEAM_ACCESS` | 403 | 201 |
| Lire les affectations d’un autre utilisateur sans droit administratif | 403 | 200 |
| Créer un token MCP avec `AGENT_EDIT`, sans `MCP_API_ACCESS`, sur son agent géré | 403 | 201 |

Le troisième cas traverse aussi l’exigence de session web et le périmètre de gestion normal.
Le défaut viole donc le contrat explicite de combinaison des droits. L’authentification et
les contrôles de périmètre qui restent actifs ne compensent pas cette violation.

L’inventaire identifie 14 gardes `RequireAllPrivilegesAssertion` et un garde
`OwnUserOrPrivilegeAssertion`. Les consommateurs comprennent les équipes, leurs membres et
anciennes surfaces de groupes d’agents, les accès MCP, une vue du travail actif et la lecture
des affectations. Toutes ces variantes n’ont pas fait l’objet d’une reproduction HTTP ;
les trois cas du tableau sont ceux effectivement démontrés.

Correction recommandée : rendre la configuration déclarée par le serveur autoritaire et
distincte des données de requête. Préserver l’autorité des identités du chemin. Les tests
doivent traverser le garde HTTP complet, avec tentatives de substitution par requête, JSON et
formulaire, et contrôler aussi les demandes légitimes.

Pourquoi les contrôles existants ne l’ont pas détecté : les tests du garde vérifient les
métadonnées enregistrées ; les tests unitaires d’assertion injectent directement une configuration
considérée fiable ; les parcours HTTP couvrent des refus normaux, sans collision entre les clés
de requête et celles de la politique. Les 41 contrôles existants ciblés passent alors que les
trois reproductions de ce défaut échouent sur l’attente de refus.

## 2. Matrice des fonctionnalités à découpler

| Fonctionnalité | Contrôle actuel principal | Conséquence | Cible proposée |
|---|---|---|---|
| Contacts | `MEMORY_ACCESS`, `MEMORY_EDIT`, `MEMORY_ADMIN` | Impossible de déléguer le carnet de contacts indépendamment des souvenirs | `CONTACT_ACCESS`, `CONTACT_EDIT` |
| Bibliothèque et opérations de fichiers | `MEMORY_ACCESS`, `MEMORY_EDIT` | Gestion de fichiers et gestion de souvenirs sont couplées | `FILE_ACCESS`, `FILE_EDIT`, avec droits de la source conservés |
| Indexation des fichiers | `MEMORY_ACCESS`, `MEMORY_EDIT` | Modifier des souvenirs permet aussi de lancer, arrêter ou réparer l’indexation | `FILE_INDEX_ACCESS`, `FILE_INDEX_RUN` |
| Tableau de bord | `TASK_ACCESS` ou `TASK_EDIT` | Accès aux indicateurs consolidés indissociable des tâches | `DASHBOARD_ACCESS`, borné au périmètre autorisé |
| Historique des conversations texte | `TASK_ACCESS`, `TASK_EDIT` | Lire ou piloter les tâches ouvre aussi la supervision des conversations | `CONVERSATION_ACCESS`, `CONVERSATION_CONTROL` |
| Historique des appels vocaux | `TASK_ACCESS`, `TASK_EDIT` | Supervision vocale couplée aux tâches | `VOICE_HISTORY_ACCESS`, `VOICE_HISTORY_CONTROL` |
| Journaux et contrôle des appels LLM | `TASK_ACCESS`, `TASK_EDIT` ; purge dédiée | Droit de tâches réutilisé pour prompts, réponses et interruption des inférences | `LLM_CALL_ACCESS`, `LLM_CALL_CONTROL` ; conserver `LLM_CALL_PURGE` |
| Supervision Dream | `TASK_ACCESS` et périmètre de gestion global | Domaine distinct sans droit propre ; menu et API ne représentent pas la même condition | `DREAM_ACCESS`, avec exigence de périmètre globale explicite |
| Réglages Dream | `PARAMS_*` | Administration Dream liée aux autres paramètres | `DREAM_EDIT`, avec contrôle des clés de configuration |
| Approbations et permissions mémorisées | `CONNECTION_ACCESS`, `CONNECTION_EDIT` | Configurer les connexions et décider/révoquer des accords sont couplés | `PERMISSION_ACCESS`, `PERMISSION_DECIDE`, `PERMISSION_REVOKE` |
| Fournisseurs et authentifications fournisseur | `LLM_PROVIDER_*` | Droits déjà présents, mais partagés avec le catalogue des modèles | Conserver `LLM_PROVIDER_ACCESS` et `LLM_PROVIDER_EDIT` pour ce domaine |
| Modèles configurés | `LLM_PROVIDER_*` | Ajuster les modèles implique les droits de configuration des fournisseurs | `LLM_MODEL_ACCESS`, `LLM_MODEL_EDIT` |
| Profils et usages LLM | `PARAMS_*` | Configuration LLM liée à l’ensemble des préférences | `LLM_PROFILE_ACCESS`, `LLM_PROFILE_EDIT` |
| Catalogue et politiques globales des harnais | `PARAMS_*` | Administrer les harnais implique l’administration générale des paramètres | `HARNESS_CONFIG_ACCESS`, `HARNESS_CONFIG_EDIT` |

Ces noms sont des propositions, pas des codes déjà disponibles. Le catalogue indicatif ajoute
24 codes, soit 109 au total si chaque séparation est retenue, sans compter d’éventuels
renommages ou consolidations. Ce total n’est pas un objectif de conception.

### Contacts et fichiers : deux séparations concrètement nécessaires

[Les cinq endpoints Contacts](../../back/app/contact/router.py) utilisent les droits Mémoire.
Les mutations vérifient aussi que l’agent appartient au périmètre de gestion de l’utilisateur.
La séparation doit conserver ce contrôle et vérifier les services de contacts reposant sur
le stockage Memory. Ajouter deux constantes au routeur ne suffit pas à qualifier le parcours.

Le domaine File Share expose 23 enregistrements HTTP, dont un accès média avec authentification
indépendante. Les principales lectures, mutations et commandes d’indexation réemploient Mémoire ;
la liste des bridges utilise Tools. Voir [le navigateur](../../back/app/file_share/browser_router.py)
et [les opérations de fichiers](../../back/app/file_share/router.py).

Leurs consommateurs dépassent la page Fichiers : souvenirs, sélecteurs de ressources, pièces
jointes documentaires, médias et indexation. Un nouveau `FILE_ACCESS` ne doit pas devenir une
condition universelle supplémentaire empêchant de consulter une pièce jointe autorisée dans
son domaine. Un `FILE_EDIT` ne doit pas donner le droit de modifier arbitrairement un Document,
Dataset ou Process. Le navigateur interdit déjà certaines mutations de ressources natives et
consulte les capacités de leur provider : [contrat actuel](../../back/app/file_share/browser.py).

### Activités : séparer les contenus, composer la page

[La page Activités](../../front/app/task/pages/index.vue) regroupe conversations texte,
voix, tâches, appels LLM et processus. Les quatre premiers onglets ne disposent pas de filtres
de domaine comparables à celui des processus. Le droit de tâches est utilisé au-delà des tâches
dans les [conversations](../../back/app/conversation/router.py), la [voix](../../back/app/voice/router.py)
et les [appels LLM](../../back/app/llm/call_router.py).

La cible recommandée est une page disponible dès qu’un de ses domaines est accessible, avec
onglets et requêtes limités aux droits correspondants. Un simple `ACTIVITY_ACCESS` couvrant
tous les onglets reproduirait le couplage actuel sous un autre nom.

Les lectures LLM renvoient un schéma comprenant messages de requête, prompt système, réponse,
raisonnement et réponse brute : [LLMCallRead](../../back/app/llm/schemas.py). La délégation d’une
supervision financière ou d’un état d’exécution ne doit pas être assimilée sans décision explicite
à l’accès à ces contenus. Une séparation métadonnées/contenus détaillés peut être nécessaire
si ce rôle d’auditeur est effectivement demandé ; elle n’est pas ajoutée d’office au catalogue.

### Dream : distinguer supervision globale et action sur une ressource

[Le menu Dream](../../front/app/dream/navigation.ts) utilise `TASK_ACCESS` OU
`AGENT_MANAGE_ALL`. Ses vues de supervision imposent `TASK_ACCESS` puis un périmètre global
dans [l’API](../../back/app/dream/router.py). Un utilisateur ne possédant qu’un des deux droits
voit donc une entrée qui ne correspond pas à son autorisation API.

`DREAM_ACCESS` doit représenter la fonction de supervision, sans accorder implicitement la
gestion de tous les agents. Les actions manuelles sur un souvenir restent soumises aux droits
de ce souvenir et au périmètre de son agent. Les traitements autonomes du scheduler ne doivent
pas dépendre d’un rôle humain choisi pour un écran.

### Permissions : le droit de décider ne remplace pas l’identité du décideur

Les [accords d’actions](../../back/app/tools/authorization_router.py), les
[décisions réseau](../../back/app/messenger/permission_router.py) et les fonctions des connexions
réemploient `CONNECTION_*`. Les services imposent en plus l’identité de l’approbateur,
la politique actuelle de l’agent et la validité de la demande.

Les nouveaux droits doivent séparer consultation, décision et révocation. `PERMISSION_DECIDE`
ne doit jamais permettre de répondre à la place d’un autre approbateur ni rendre valable une
ancienne autorisation. Les changements de configuration d’une connexion conservent leurs effets
d’invalidation et leurs propres droits ; ils ne constituent pas une approbation humaine.

## 3. Écarts menus/API et composition des rôles

Priorité : **P1**, principalement délégation et utilisabilité. Les refus serveur restent
nécessaires ; masquer une entrée ne constitue pas une protection serveur.

Le [helper de navigation](../../front/core/navigation/composables/useNavigation.ts) applique un
OU dans une liste de privilèges et filtre récursivement les descendants. Les gardes backend
utilisent aussi un OU, sauf assertion complémentaire. Aucune hiérarchie automatique ne déduit
`ACCESS` de `EDIT` ou de `ADMIN`.

| Profil synthétique | Entrée masquée | Capacité backend existante |
|---|---|---|
| `AGENT_EDIT` seul | Agents | Lecture des agents autorisée par le garde de lecture |
| `LLM_PROVIDER_EDIT` seul | Fournisseurs & modèles | Lecture du catalogue autorisée |
| `MEMORY_EDIT` seul | Contacts | Lecture des contacts autorisée dans le périmètre |
| `MEMORY_ADMIN` seul | Contacts / Mémoire | Gardes de lecture acceptant ce code |
| `MANAGE_ROLE` seul | Rôles & autorisations | Lecture et gestion des rôles autorisées |
| `READ_PRIVILEGE` seul | Rôles & autorisations | Lecture des privilèges autorisée |
| `PARAMS_EDIT` seul | Préférences | Lecture des paramètres autorisée |
| `PROCESS_ADMIN` seul | Processus | Accès à des gardes de consultation Process |

Les probes évaluent le helper réel et les données de navigation, sans monter les pages. Elles
ne prouvent pas la réussite d’un parcours complet : certains composants réclament encore des
catalogues complémentaires. Par exemple, Affectations charge aussi les rôles et recherche les
utilisateurs. Il faut inventorier ces dépendances plutôt que donner automatiquement les droits
d’administration correspondants.

La bibliothèque Fichiers présente une autre situation : `MEMORY_EDIT` autorise certaines
mutations, mais ses lectures exigent exactement `MEMORY_ACCESS`. La règle lecture/édition est
donc hétérogène même à l’intérieur d’un parcours.

## 4. Paramètres génériques : un point de passage à traiter réellement

Priorité : **P1** pour une délégation de configuration.

[L’API Params](../../back/core/params/router.py) liste les paramètres non internes sous
`PARAMS_ACCESS` OU `PARAMS_EDIT`, et modifie toute clé déclarée non interne sous `PARAMS_EDIT`.
Les valeurs secrètes sont masquées à la lecture ; cette protection doit être conservée.

Donner un droit spécialisé aux écrans Harnais, Dream ou Profils LLM, tout en laissant la route
générique accepter les mêmes écritures sans contrôle de domaine, ne réalise pas une séparation.
La politique de clé doit être appliquée au service/API générique et à tous les autres chemins
de lecture ou mutation. Les clés inconnues ou internes restent refusées.

`PARAMS_*` peut rester le droit des véritables réglages globaux, après définition de cette
frontière. La migration d’un ancien rôle large exige un choix explicite de ses responsabilités.

## 5. Ce qu’il faut conserver

| Domaine | Éléments actuels à préserver |
|---|---|
| Ressources Document, Dataset et Process | Droits fonctionnels et ACL de chaque ressource, propriété, partage et conflits de révision indépendants |
| Mémoire | Propriété privée par agent, absence de grants de partage |
| Périmètre des agents | Agent assigné au gestionnaire, extension explicite par `AGENT_MANAGE_ALL`, réévaluation lors des réaffectations |
| Chat | Droits distincts pour accès, création, envoi, appels et usurpation de point de vue, plus périmètre de dialogue |
| Process | Lecture, édition, lancement et administration déjà séparés |
| Skills | Consultation, édition et attribution distinctes |
| Incidents / purges | Droit de purge distinct d’une mutation ordinaire |
| Lab | Paires lecture/édition séparées par mécanisme, avec assertion sur le mécanisme demandé |
| Accès personnels | Profil, MFA, propres sessions et propres rôles restent des fonctions authentifiées ordinaires |
| Protocoles machine | Tokens de runtime, capacités émises et authentifications de bridge gardent leur contrat propre |
| Harnais | Supervision générique ; aucune nouvelle famille de privilèges par marque de runtime |

Le [périmètre de gestion](../../back/app/agent/management_scope.py) est une restriction sur les
objets, pas un remplacement des droits fonctionnels. Les droits d’un rôle humain ne doivent
pas être copiés mécaniquement dans les capacités d’un agent autonome.

Les nouveaux droits doivent aussi atteindre les événements et abonnements temps réel.
[Socket.IO](../../back/core/websocket.py) réemploie notamment `TASK_*` pour Dream, les appels LLM
et la supervision vocale. Corriger seulement les routes HTTP laisserait des politiques divergentes.

## 6. Organisation proposée du catalogue

La délégation se décrit par trois éléments : **fonction autorisée**, **action permise** et
**périmètre des objets**. Les rôles regroupent ces éléments pour les personnes ; ils évitent
d’avoir à attribuer les codes un par un dans les usages courants.

Conserver les noms actuels lorsqu’ils représentent correctement leur domaine. Utiliser pour
les nouveaux codes une sémantique stable : `ACCESS` pour consulter, `EDIT` pour modifier,
`RUN` ou `CONTROL` pour exécuter/piloter, `PURGE` pour la suppression irréversible. Un renommage
général de `READ` vers `ACCESS` n’apporte pas, à lui seul, de meilleure sécurité et n’est pas
prioritaire. Documenter précisément les rares variantes existantes.

Regroupements lisibles proposés : Comptes et rôles ; Équipes ; Agents et périmètres ; Outils ;
Connexions ; Approbations ; Fournisseurs ; Modèles ; Profils LLM ; Harnais ; Contacts ; Fichiers ;
Indexation ; Documents ; Datasets ; Mémoire ; Topics ; Tâches ; Conversations ; Voix ; Appels LLM ;
Process ; Tableau de bord ; Dream ; Incidents ; Lab ; Paramètres globaux ; Infrastructure.

Les listes de privilèges actuelles sont personnalisables. Ne pas écraser les regroupements
manuels pour imposer ce classement. Une vue par domaine issue des déclarations peut compléter
ces listes. Le catalogue devrait expliquer les opérations autorisées et leur périmètre,
plutôt qu’afficher uniquement le code technique ou un nom d’écran.

Exemples de rôles à préparer, sans les créer automatiquement : lecteur de supervision,
opérateur de contacts, gestionnaire de fichiers, responsable des approbations, administrateur
des modèles, administrateur des harnais et administrateur global.

## 7. Migration des rôles et qualification

La source d’un ancien droit large ne permet pas de déduire l’intention d’un rôle :
`MEMORY_EDIT` a pu être donné pour les contacts, pour les fichiers ou pour les souvenirs.
Une projection automatique vers tous les nouveaux codes reconduirait ce regroupement.
Une projection trop restrictive retirerait des fonctions réellement utilisées.

Avant la migration : simuler les capacités avant/après pour chaque rôle, présenter les écarts,
puis établir une correspondance revue. Ne pas créer des grants de remplacement sans cette
décision. Les listes et affectations existantes restent conservées.

L’exécution appartient à DbAdmin, avec transactions et reprise idempotente. Les suppressions
de codes utilisent la cascade déjà vérifiée sur `role_privileges.privilege_id`. Les grants cibles
nécessaires doivent être persistés avant suppression des sources. Une nouvelle exécution ne doit
ni multiplier les grants ni élargir le périmètre. L’administrateur global garde ses garanties.

La qualification doit couvrir profils sans droit, lecteurs seuls, éditeurs seuls, droits
incomplets, profils de domaines voisins, accès direct par URL, agents étrangers, réaffectation,
révocation en session active et événements tardifs. Les parcours fichiers doivent inclure leurs
consommateurs Document, Dataset, Memory, pièces jointes et providers externes.

## 8. Preuves et limites

- 41 tests existants ciblés passent : contrats de routes, Contacts, mutations du navigateur de
  fichiers, périmètres des agents, agrégats du tableau de bord, isolation du Lab et outils.
- Trois reproductions HTTP synthétiques échouent sur l’attente de refus, confirmant les accès
  indus décrits en section 1. Ces échecs sont des résultats d’audit, pas des corrections livrées.
- Onze probes de navigation vérifient les profils partiels et l’entrée Dream avec le helper réel.
- Les matrices recensent les 85 codes et les gardes enregistrés ; les assertions, services,
  ACL et authentifications indépendantes restent nécessaires pour interpréter chaque entrée.
- Aucun changement d’autorisation, de rôle ou de schéma applicatif n’a été réalisé pour cet audit.
  La fréquence réelle d’usage et les intentions des rôles d’une installation ne sont pas mesurées.
- La couverture HTTP de quelques parcours ne constitue pas une preuve exhaustive sur les
  793 enregistrements. Les pages n’ont pas été qualifiées visuellement dans de nouveaux profils.
- La validation complète réservée à l’utilisateur n’a pas été exécutée.

## Réalisation après confirmation explicite

Les six lots sont implémentés : garde central, navigation, domaines de ressources et
supervision, permissions, activités/configurations et projection des rôles. Les sources de
politique serveur priment sur les données client, tandis que les identités du chemin restent
autoritaires. Huit scénarios HTTP permanents couvrent les collisions requête/JSON/formulaire.

Les droits de lecture/édition restent explicites ; aucune hiérarchie générale ne transforme
un code en un autre. Dream exige toujours le périmètre global pour sa supervision.
Les politiques génériques Params vérifient chaque clé. Les permissions conservent l'identité
de l'approbateur et la session web ; révoquer ne permet pas de réactiver une capacité.
Les transports de fichiers vérifient le domaine de l'URI et les ACL du provider, sans imposer
Files à une pièce jointe Document. Les catalogues minimaux des sélecteurs ne donnent pas
l'administration des agents, utilisateurs, connexions ou harnais.

La projection DbAdmin utilise le delta du modèle Role et une marque d'initialisation par rôle,
avec grants et marque dans la même transaction. Les nouveaux rôles sont explicites ; une
révocation ultérieure n'est pas restaurée. La suppression d'un privilège conserve la cascade
des grants et ne supprime ni rôle ni liste. Les listes existantes ne sont pas reclassées
automatiquement. La correspondance approuvée est publiée dans la décision 0233.

Les tests HTTP et PostgreSQL couvrent les anciens droits seuls, les domaines voisins, les
droits minimaux, la portée, les métadonnées, la projection exacte, le rollback et la révocation.
Les tests navigateur exercent les changements de rôle, les onglets et l'indexation indépendante,
ainsi que les consommateurs existants. Un parcours assemblé Contacts seul sur ordinateur et
mobile complète cette couverture. Le catalogue des garanties et les preuves locales distinguent
les suites ciblées de la validation complète réservée à l'utilisateur.

Cette qualification ne mesure pas la fréquence réelle d'utilisation des droits et ne prouve
pas exhaustivement chaque route de l'application. Les limites de l'inventaire initial restent
applicables à ces mesures historiques.
