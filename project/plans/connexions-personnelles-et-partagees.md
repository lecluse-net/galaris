# Connexions personnelles et partagées entre agents

- Statut : `design` — conception à relire ; aucune implémentation engagée.
- Date : 2026-11-13.
- Demande : permettre aux utilisateurs de posséder des connexions aux Tools, de les
  partager avec plusieurs agents comme des documents et de définir des autorisations
  différentes pour chaque agent.
- Ce plan ne constitue pas une autorisation d'implémenter, de synchroniser une base,
  de déployer ou de créer un commit.

## 1. Résultat attendu

Un utilisateur crée une connexion à un fournisseur, configure une seule fois ses
paramètres ou son compte OAuth, puis la partage avec plusieurs agents. Chaque agent
utilise cette même connexion avec ses propres permissions de fonctions. Modifier les
permissions d'un agent ne modifie pas celles des autres. Retirer son accès ne détruit
ni le compte partagé ni les accès des autres destinataires.

Exemple de réception : une connexion « Compte fournisseur » appartient à un humain.
Deux agents y ont accès ; le premier peut consulter et envoyer des mails, le second
peut consulter mais son envoi est bloqué. Les deux utilisent les mêmes identifiants
serveur. Une demande d'accord du premier ne donne aucun accord au second.

La propriété et le partage reprennent exactement les contrats communs utilisés par
Documents : propriétaire humain ou agent, privé par défaut, destinataires humains,
agents et équipes, lecture/écriture, Public authentifié, gestion du partage distincte
de l'écriture et protection contre les sauvegardes concurrentes. Une connexion reste
une ressource de `app.connection`, pas un Document.

## 2. État actuel vérifié

La revue porte sur le checkout de développement, qui contient d'autres travaux,
notamment sur Documents, Calendar et les formulaires de connexion. Les préserver et
relire leurs contrats avant toute réalisation.

| Surface | Constat et conséquence |
|---|---|
| `back/app/connection/models.py`, `schemas.py` | `Connection.agent_id` est obligatoire. Le propriétaire et l'utilisateur de la connexion sont aujourd'hui confondus. |
| `ConnectionParam`, `ConnectionOAuth` | Paramètres et OAuth référencent déjà l'identité de connexion ; conserver cette identité évite de dupliquer les comptes. |
| `ConnectionFunctionState`, `connection_service.resolve_function` | Les surcharges appartiennent à la connexion. Elles doivent devenir propres à l'agent utilisateur. |
| `connection_service`, `router`, `admin_service`, `agent_admin_service`, `function_permissions` | Les listes, droits de gestion et mutations s'appuient largement sur l'agent de la connexion. |
| `back/app/share/{models,contracts,access,service}.py` | Contrats et stockage communs disponibles ; `connection` doit être ajouté aux types acceptés, y compris à la contrainte SQL. |
| `back/app/document/{models,item_sharing,access}.py` | Référence pour la propriété, l'acteur humain, la gestion réservée du partage et les versions concurrentes. Les classements/répertoires documentaires ne concernent pas les connexions. |
| `front/app/share/` | Sélecteur de propriétaire, panneau, destinataires et contrôleur asynchrone réutilisables. |
| `back/app/tools/{mcp_loader,mcp_authorization,authorization,protocols}.py` | Plusieurs contrôles exigent aujourd'hui `connection.agent_id == actor_agent_id`. Les remplacer par la résolution d'accès et de politique du véritable appelant. |
| `back/app/connection/oauth_service.py` | La liaison OAuth inclut actuellement l'agent et le Tool ; préserver les grants existants demande une migration ou une compatibilité explicite. |
| `back/app/tools/dbadmin.py`, `mandatory_tools.py` | La création des connexions système reste liée à chaque agent ; son idempotence doit être préservée. |
| `back/app/connection/tests/test_mail_accounts.py` | Plusieurs comptes par fournisseur existent pour Mail. Les autres Tools ont une unicité agent/Tool ; plusieurs connexions accessibles rendent les sélections implicites ambiguës. |

Références : [partage commun](../decisions/0200-exclusive-resource-sharing.md),
[protocoles fournisseurs](../decisions/0274-provider-tool-protocols.md),
[partage documentaire](../../docs/fr/user/rich-content.md#partager-un-document) et
[DbAdmin](../../docs/fr/dev/dbadmin.md). Ces sources et les tests restent
autoritaires ; le présent plan décrit une cible non réalisée.

## 3. Modèle cible et séparation des responsabilités

### Connexion commune

Conserver `connections.id` et `tool_id`. Ajouter un libellé permettant de distinguer
plusieurs comptes, `owner_user_id` / `owner_agent_id`, une référence exclusive de
partage de type `connection` et une version pour les mutations concurrentes.
Les deux propriétaires sont des FK réelles ; une contrainte exige exactement un
propriétaire. Réutiliser `Shareable` / `ShareReference` et leurs contraintes plutôt
que créer une table parallèle de destinataires.

La connexion possède les paramètres communs, les secrets, le grant OAuth et son
activation globale. Une désactivation globale suspend tous les usages ; la désactivation
locale d'un agent ne doit pas interrompre les autres. La suppression du compte et le
retrait d'un partage sont deux opérations distinctes.

Étudier l'application de `HistoryMixin` pour les nouvelles garanties d'audit et de
suppression, en vérifiant les cascades et la purge existantes : ne pas transformer
implicitement la politique de suppression pendant ce chantier.

### Usage et autorisations par agent

Créer un état d'usage propre au couple `(connection_id, agent_id)`, unique en base,
portant l'activation locale et les délégations qui sont réellement propres à cet agent.
Une nouvelle table de fonctions référence cet usage par une vraie FK et porte une
unicité `(usage_id, capability_kind, function_name)`.

Les noms de tables définitifs seront figés lors du contrat technique. Le découpage
attendu est le suivant :

| Donnée | Propriétaire de la donnée |
|---|---|
| Identifiants, paramètres ordinaires, OAuth | Connexion commune |
| Propriétaire et destinataires | Connexion et `app.share` |
| Activation locale, surcharge Actif/Bloqué/Sur demande | Usage de cette connexion par cet agent |
| Décision ponctuelle, accord mémorisé, contexte d'exécution | Mécanismes existants d'autorisation, toujours liés à l'agent réel |
| Portée administrative, notamment `tools.management_scope` | Délégation propre à l'agent ; jamais un secret ou un pouvoir commun hérité du propriétaire |

Une ligne d'usage ne constitue jamais un droit d'accès. Les partages d'équipe et Public
restent évalués à la demande ; ne pas matérialiser leurs membres comme des grants directs.
Sans état local enregistré, appliquer les défauts existants. Créer l'état local seulement
lorsqu'un réglage le nécessite, sans multiplier les lignes à chaque lecture.

La cascade de fonctions devient : surcharge de l'agent pour cette connexion, puis
règle globale du Tool, puis défaut logiciel. Ne pas ajouter un niveau commun de
fonctions qui modifierait silencieusement cette cascade. Les anciens réglages locaux
seront transférés uniquement à l'agent historique ; ils ne deviendront pas les droits
de tous les nouveaux destinataires. Couvrir outils, ressources et prompts.

### Propriété et partage comme Documents

- Le propriétaire conserve l'accès. Un utilisateur peut créer et retrouver une
  connexion personnelle sans posséder d'agent.
- Lecture : consulter les métadonnées autorisées et utiliser les fonctions permises.
  Écriture : modifier la configuration de la connexion avec les contrôles RBAC et
  restrictions métier existants. Ces droits ne désignent pas les opérations distantes :
  l'envoi d'un mail dépend de la permission de fonction de l'agent.
- Aucun lecteur, éditeur ou modèle ne récupère les secrets. Un secret est remplaçable
  par les chemins d'édition autorisés, avec la sémantique actuelle conserver/effacer.
  OAuth garde ses exigences de session humaine et d'autorisation.
- L'écriture ne donne pas le droit de repartager ou de transférer la propriété.
  Réutiliser les règles de propriétaire, de périmètre de gestion et d'administration
  applicables à ce domaine, sur le modèle documentaire.
- Agents, utilisateurs et équipes peuvent être destinataires. Les appartenances sont
  relues ; les groupes sélectionnés ne changent pas automatiquement avec le propriétaire.
- Public donne accès aux acteurs authentifiés de l'application. Conserver les règles
  Public/Lecture avec rédacteurs particuliers, Public/Écriture et retraits redondants du
  panneau commun, sans inventer une variante dédiée aux connexions.
- Plusieurs droits se cumulent comme dans Documents. Retirer un grant direct ne retire
  pas un droit encore accordé par une équipe ou Public ; afficher le droit effectif.
- Le responsable humain d'un agent ne transmet pas ses connexions personnelles à cet
  agent par simple propriété. Les identités humaines et agentiques restent distinctes.

## 4. Résolution d'accès et consommateurs

Introduire dans la façade Connection une résolution explicite de la connexion pour
l'acteur. Pour un agent, elle vérifie le propriétaire ou les grants effectifs, l'activation
globale, l'activation locale, le Tool, puis la politique de fonction de cet agent.
Chaque frontière d'exécution utilise cette résolution ; la présence dans le catalogue
ou dans un cache ne suffit pas à autoriser un appel.

Inventorier et traiter les consommateurs par groupes :

1. API et interface : mes connexions, partagées avec moi, propriétaire, édition,
   paramètres, OAuth, partage, transfert et suppression avec bilan des usages concernés.
2. Outils : découverte, index de recherche, chargement MCP, REST, ressources, prompts,
   modes conversationnels, fonctions natives et autorisations ponctuelles.
3. Fichiers et protocoles : partage de fichiers, Mail, Calendar, ressources exactes,
   sélection du compte et ACL des ressources du domaine.
4. Flux persistants : listeners, polling, webhooks, connexions Messenger/voix, sessions
   distantes, synchronisation et reprises après interruption.
5. Administration : ToolAdmin, AgentAdmin, portées locales, permissions, synchronisation
   des connexions obligatoires et suppression d'un Tool.

Avec plusieurs connexions accessibles au même Tool, annoncer leur identité et leur
libellé ; exiger une sélection exacte si le contexte ne désigne pas déjà le compte.
Ne jamais choisir arbitrairement la connexion propriétaire plutôt qu'une partagée.
Conserver les URI existantes et leur rattachement au bon compte.

L'usage d'une connexion ne vaut pas droit sur une ressource du fournisseur projetée
dans Galaris : les ACL Calendar, Documents, Process et autres domaines restent applicables.
Éviter que deux agents partagés créent des synchronisations, curseurs, rappels ou
exécutions techniques en double pour le même compte.

Pour les événements entrants, dissocier la réception du compte et le routage vers les
agents. Un partage seul ne doit pas déclencher une Task chez tous les destinataires.
Figer le contrat de routage dans `app.messenger` avant d'adapter les bridges concernés ;
préserver le routage historique pendant la migration. Qualifier aussi un compte possédé
par un humain sans agent : configuration et réception ne peuvent plus supposer un agent
propriétaire unique.

Les outils système obligatoires conservent leurs connexions par agent et protections.
Un partage ou un droit d'édition ne contourne jamais une délégation administrative ni
les opérations réservées à l'humain. Ne pas attribuer au destinataire la portée du
propriétaire ou un compte technique interne réservé à celui-ci.

Les caches doivent séparer données communes et droits par agent. Une modification de
partage, d'équipe, de compte, de fonction ou d'activation invalide les projections
concernées. Revalider avant un nouvel effet, y compris après un accord humain et lors
d'une reprise ; une opération distante déjà exécutée conserve son reçu et son état.

## 5. Migration DbAdmin : préservation et reprise

### Stratégie

Procéder par expansion, transfert vérifié et contraction différée. Les modèles
SQLAlchemy décrivent la cible ; des `DbAdminAction` indispensables dans le domaine
Connection effectuent le transfert par les contrats publics de `core.dbadmin`.
Pas d'Alembic, d'Atlas direct ou de migration dans le lifespan.

La première livraison conserve les colonnes et tables historiques nécessaires à la
preuve et à la reprise. La nouvelle application utilise exclusivement le nouveau
modèle ; les anciennes données ne sont pas une seconde source de permissions.
Le retrait définitif des sources attend une livraison ultérieure qualifiée.

### Données à préserver

Pour chaque connexion historique :

- Conserver son `id`, son Tool, ses paramètres, leur chiffrement, son activation et
  toutes les FK dépendantes, URI, journaux, reçus et historiques associés.
- Initialiser `owner_agent_id` avec l'ancien `agent_id`, sans transfert automatique
  à son responsable humain, et créer un partage privé exclusif sans nouveau destinataire.
- Initialiser l'usage de l'ancien agent et transférer ses surcharges de fonctions avec
  les valeurs exactes `enabled`, `disabled`, `ask`, leur héritage et leur type de capacité.
- Déplacer les délégations propres à cet agent, dont la portée administrative, vers
  son état local. Ne pas partager ces pouvoirs avec les futurs destinataires.
- Préserver les comptes Mail multiples, les connexions désactivées, les exceptions
  système et les liens éventuels vers des agents supprimés logiquement.
- Préserver les autorisations en attente et leurs reçus. Si une empreinte change,
  invalider explicitement l'accord incompatible sans rejouer une opération déjà effectuée.

Ne fusionner aucune connexion au motif qu'elle possède les mêmes identifiants qu'une
autre. Cela changerait propriété, identité et autorisations. Le partage d'un compte
existant reste une action explicite ultérieure.

### Phases et postconditions

| Étape | Travail et preuve attendue |
|---|---|
| Préparation | Qualifier le schéma réellement publié, ses contraintes et l'ordre des contributions DbAdmin existantes. Capturer hors `public`, si nécessaire, la correspondance ancien agent/connexion et les politiques sources, sans secrets en clair. Vérifier la copie avant toute transformation destructive. |
| Expansion | Ajouter propriété, partage et états par agent. Prévoir explicitement les anciennes contraintes d'unicité et colonnes `NOT NULL` : elles ne doivent pas empêcher une nouvelle connexion humaine. Qualifier l'ordre d'élargissement du CHECK de `share_configs` avant insertion du type `connection`. |
| Transfert `AFTER_EXPAND` | Copier par SQL ensembliste ou lots bornés, sans connexion externe. Préserver identités et FK. Vérifier chaque transfert et enregistrer sa preuve dans la même transaction. Réunir les opérations dépendantes dans un handler ordonné ; les actions n'ont pas de graphe de dépendances. |
| Vérification | Aucune propriété manquante ou double, aucun partage manquant/réutilisé, aucun usage historique manquant, mêmes politiques effectives pour chaque ancien agent, aucune nouvelle exposition et mêmes dépendances. Vérifier les sources, pas seulement un compteur de lignes. |
| Convergence | Resserrer les contraintes cibles après satisfaction des preuves. Seul `converged` autorise le démarrage ; un backfill incomplet conserve les sources et bloque le service avec un diagnostic exploitable. |
| Contraction ultérieure | Retirer les sources devenues inutiles après qualification de l'upgrade, de la reprise et des consommateurs. Ne pas supprimer les preuves dans la première livraison. |

Une migration relancée ne doit jamais restaurer une permission ou un partage révoqués,
réactiver un usage désactivé, réattribuer un ancien propriétaire ou écraser un paramètre
modifié depuis le transfert. Distinguer la preuve immuable de copie de l'état métier
courant, avec clés de reprise stables et marqueurs par élément vérifié. Tester aussi
un crash après commit des données mais avant mise à jour du journal DbAdmin.

### OAuth, compatibilité et exploitation

Définir une liaison OAuth fondée sur l'identité stable du compte, indépendante de
l'agent qui l'utilise. Qualifier une conversion ou une lecture compatible des anciens
grants, sans réauthentification systématique ni extension des scopes fournisseur.
Les autorisations navigateur en cours restent liées à leur initiateur humain ; une
ancienne demande incompatible est invalidée explicitement. Les refresh concurrents
de plusieurs agents partagent la synchronisation du compte.

La synchronisation DbAdmin ne contacte pas les fournisseurs. Estimer volumes, index,
temps de verrouillage et coût de démarrage sur des données synthétiques représentatives.
Injecter les échecs de préparation, copie, postcondition et contraction ; conserver
étape, cause et emplacement sans secret. Documenter la reprise après chaque phase.

Un retour à l'ancien binaire n'est pas un rollback garanti : il ne sait pas représenter
un propriétaire humain ni les partages et permissions multiples. Prévoir une sauvegarde
avant mise à jour et qualifier la restauration hors ligne ; ne pas promettre une simple
réversibilité par changement de branche après de nouvelles écritures.

## 6. Interface à prévoir

Réutiliser les formulaires de paramètres et OAuth actuels, `OwnerSelect` et le panneau
de partage commun. Prévoir « Mes connexions » et « Partagées avec moi », avec propriétaire,
Tool, compte et droits effectifs. Une vue agent affiche ses connexions propres et
partagées et ses autorisations locales ; elle distingue clairement une modification
de compte commune d'une modification de permissions pour cet agent seulement.

La sélection de l'agent dans l'éditeur de permissions ne doit pas changer le compte
ni écrire dans les règles des autres agents. Conserver les saisies sur erreur, gérer
les réponses tardives et conflits de version, puis recharger les droits confirmés.
Un retrait de partage actualise la liste sans effacer le compte.

La référence graphique `/graphic-reference`, les composants communs, Solaire, les
catalogues FR/EN, les modales fermables et la pagination standard restent applicables.
Ne pas créer un éditeur spécial de paramètres pour les connexions humaines.

## 7. Lots de réalisation proposés

1. **Contrats et inventaire.** Figer les acteurs, droits, politiques par agent, sélection
   de compte, délégations et routage entrant. Compléter l'inventaire des consommateurs
   avec les tests existants. Formaliser ensuite la décision structurelle dans
   `project/decisions/`, sans présenter le présent design comme implémenté.
2. **Schéma et migration.** Implémenter les modèles et actions dans une branche isolée,
   qualifier l'ancien schéma peuplé et les pannes/reprises avant de synchroniser une base
   de développement partagée. Conserver les sources historiques.
3. **Premier parcours complet.** Connexion humaine, partage à deux agents, fonctions
   différentes et révocation d'un seul agent, via API et application assemblée. Vérifier
   aussi une connexion historique migrée avant d'étendre aux autres consommateurs.
4. **Consommateurs par familles.** MCP/REST, fichiers, Mail/Calendar, puis listeners,
   Messenger/voix et administration. Vérifier chaque famille avec son compte partagé
   et ses comportements existants ; ne pas livrer un catalogue qui annonce un accès
   encore refusé ou mal routé par son transport.
5. **Qualification et documentation.** Régression ciblée, contrôle des caches, usages
   concurrents, parcours FR/EN et preuves de migration. Mettre à jour les guides utilisateur
   et administrateur, générer les cartes et exécuter `make docs-prepare`. Aucun déploiement
   ou commit n'est impliqué par ce plan.

## 8. Critères de réception et vérifications

| Garantie observable | Vérification prévue |
|---|---|
| Un humain sans agent crée et retrouve sa connexion privée | API avec RBAC puis parcours navigateur avec réouverture et conservation des paramètres |
| Le partage suit Documents pour humains, agents, équipes et Public | Paramétrer les contrats communs de `app.share` ; vérifier propriété, cumul, membres vivants, transfert et écriture sans repartage |
| Deux agents partagent un compte avec des autorisations différentes | Intégration réelle : une même fonction autorisée pour A et refusée pour B, modification locale sans effet sur l'autre ; couvrir `ask`, ressources et prompts |
| L'accès retiré est réellement perdu, même avec un ancien catalogue ou accord | Tests d'exécution après retrait direct, sortie d'équipe, désactivation locale/globale, attente humaine et reprise ; conserver les droits accordés par une autre source |
| Une permission locale ne suffit pas sans partage | Conserver une ligne d'usage et tenter l'appel après suppression du dernier droit d'accès |
| Le bon compte est utilisé et les secrets restent côté serveur | Plusieurs comptes accessibles, refus d'ambiguïté, appels et URI exacts, inspection des réponses et erreurs ; OAuth avec fournisseur simulé à la frontière |
| Le partage ne délègue pas l'administration du propriétaire | Tests négatifs ToolAdmin/AgentAdmin, portée locale, actions humaines réservées et identité réelle de l'appelant |
| Les événements entrants et synchronisations ne sont pas dupliqués | Réception unique, routage explicite, redelivery, reprise et retrait d'un destinataire avec maintien des autres |
| La migration conserve les contrats et peut reprendre | Base PostgreSQL isolée : ancien binaire réellement publié peuplé de données synthétiques, pipeline Atlas réel, comparaison des droits/identités, pannes et rejeu après révocation |
| L'interface reste utilisable après erreurs et changements de contexte | Composants réels et quelques E2E : chargement/vide/existant, refus, retry, sauvegarde, partage concurrent, navigation et réouverture ; contrôle clavier/mobile et erreurs réseau |

Étendre d'abord les suites existantes : `app/share/tests`,
`app/connection/tests/test_connections.py`, `test_function_states.py`,
`test_mcp_oauth.py`, `test_mail_accounts.py`, les tests d'autorisations et de chargement
dans `app/tools/tests`, puis les tests propres aux transports concernés. Ajouter une
suite d'upgrade Connection si aucune suite existante ne couvre ce transfert.
Toutes les fixtures sont synthétiques. Les tests d'interaction protègent les droits,
les effets et les reprises, sans figer la présentation.

À la réalisation : tests ciblés via `make tests`, contrôles frontend concernés,
`make typecheck`, `make architecture-check`, génération du contexte et documentation
selon les surfaces modifiées, puis revue des modes de panne et `git diff --check`.
`make validate` reste exclusivement à l'initiative de l'utilisateur. Les contrôles
réalisés et les parcours non exercés seront explicitement distingués à la livraison.

## 9. Points à qualifier avant de figer l'implémentation

- L'ordre réel d'expansion des contraintes de partage, les colonnes historiques et
  la compatibilité des actions déjà publiées doivent être prouvés sur l'upgrade réel.
- Inventorier les paramètres qui portent une délégation propre à l'agent ; ne pas
  déplacer tous les paramètres ordinaires dans une nouvelle couche de surcharges.
- Figer le routage des comptes partagés entrants et la propriété des sessions distantes
  ou ressources locales, qui supposent actuellement un agent unique.
- Définir comment les accords en attente restent valides ou sont invalidés lorsque
  les empreintes OAuth, de configuration ou de politique évoluent.

Ces qualifications conditionnent la réalisation complète ; elles ne réduisent pas la
demande à un partage visuel ou au seul protocole Mail. Aucun changement de base,
aucun test runtime et aucune intervention en production ne sont réalisés par ce plan.
