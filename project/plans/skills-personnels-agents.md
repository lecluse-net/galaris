# Skills personnels des agents

- Statut : `in-progress`.
- Date : 2026-10-23.
- Portée : parcours agent MCP et consultation humaine implémentés ; activation en développement vérifiée après accord utilisateur, aucune intervention en production.
- Demande : permettre à un agent de créer et administrer ses propres skills lorsqu'il en a le droit,
  les consulter dans un onglet dédié et les séparer des skills génériques.
- Précisions utilisateur : un skill personnel n'est jamais partageable. Le retrait de sa propriété
  le transforme en skill normal, dont les autorisations deviennent administrables.
- Architecture retenue pour la conception : un seul Tool `skills`, renommé depuis
  `skill_management`, avec les portées `usage`, `personal`, `team`, `all`.
  Les personnels sont adressés sous `galaris://skill/personnal/<agent_id>/…`.

## Reprise du 23 octobre

Le premier lot prépare `app.skill.models`, `contracts` et `interface` : identité stable,
propriété privée, auteur distinct, révision, délégation serveur `usage/personal/team/all`,
création personnelle, lectures et activation avec contrôle de concurrence. Le stockage
sépare les propriétaires ; les anciens catalogues, la matrice et les projections par
code excluent les personnels. Voir la [décision 0222](../decisions/0222-personal-skill-package-boundary.md).

L'onglet **Skills personnels** expose désormais la consultation humaine dans le périmètre
de gestion courant : liste paginée, propriétaire, filtre par agent, recherche et lecture du
`SKILL.md` et des références. Il est indépendant de Dream. Les API `/skills/personal`
contrôlent les droits humains sans prendre l'identité de l'agent sélectionné.

Le Tool unique `skills` et sa migration conservant les connexions sont implémentés,
ainsi que la délégation humaine globale, les commandes MCP, File Share et les harnais.
Les créations et mutations appliquent les budgets, la confidentialité et les révisions.
Le retrait de propriété conserve un reçu rejouable et un staging récupérable. La suppression
et la restauration d'un agent conservent ses packages privés sans les réactiver.
L'onglet permet de consulter les fichiers. La délégation se configure par le paramètre
`tools.management_scope` dans Tools → Connexions → la connexion Skills. Ce paramètre local,
sans héritage global, est réutilisable par les futurs Tools concernés. Restent les actions humaines d'édition/suppression/conversion
dans cet onglet, ainsi que la qualification après activation sur une installation dédiée.
Les modifications transverses sont coordonnées avec les sessions Memory/Document et Mail.
Les tests passent exclusivement par PostgreSQL éphémère. La synchronisation de la base
de développement partagée a ensuite été explicitement autorisée et exécutée : DbAdmin
converge sans erreur, et la projection du Tool `skills` expose les quatre portées.

Précision utilisateur : un agent de portée `team` appartenant à trois équipes peut gérer
pour les agents inclus dans au moins l'une des trois. Les droits sont l'union de ses équipes
actives, réévaluée à chaque appel ; l'appartenance seule ne donne pas de droit sans délégation.
Les personnels restent privés et ne sont jamais affectables aux collègues.

## Résultat attendu

L'écran Skills possède un onglet **Skills personnels** qui liste les skills des agents, avec leur
propriétaire et un filtre par agent. Les humains y voient uniquement les agents de leur périmètre
de gestion. Les skills génériques restent dans leur liste et leur matrice d'autorisations.

Un agent peut découvrir et charger les génériques autorisés et ses propres skills. La portée
personnelle lui permet aussi de créer, modifier et supprimer ses skills. La portée globale lui
permet d'administrer tous les skills et de distribuer les génériques aux agents : un DRH agentique
peut ainsi gérer leurs autorisations. Ces niveaux portent sur les opérations et les ressources
autorisées au sein d'un même Tool, sans multiplier les Tools par rôle.

Un skill avec propriétaire est strictement privé à cet agent : aucune affectation à un autre
agent, aucun partage, aucun transfert de propriété. Un administrateur humain ou un agent de portée
globale peut explicitement retirer la propriété. Le skill devient alors générique, quitte l'onglet personnel et rejoint les règles
ordinaires d'autorisation. Cette conversion ne l'active automatiquement pour personne.
L'administration globale d'un personnel est un accès de gestion privilégié ; elle ne l'affecte
pas à l'administrateur pour son propre usage et ne le rend pas partageable.

## État vérifié avant implémentation du socle

| Surface inspectée | Comportement actuel et conséquence |
|---|---|
| `back/app/skill/models.py` | `Skill` indexe les packages, avec `code` globalement unique, `system`, catégorie et activation globale. Aucun propriétaire. `AgentSkill` et `AgentSkillCategory` portent les surcharges d'activation. |
| `back/app/skill/storage.py` | Les packages utilisateurs sont des répertoires sous `GALARIS_SKILLS_ROOT/<code>`. Les skills système viennent du dépôt et sont protégés. Frontmatter, chemins, archives et écritures ont déjà des validations à préserver. |
| `back/app/skill/skill_service.py` | La disponibilité suit la cascade agent → catégorie → global. La matrice matérialise les couples agents/skills. Les créations actuelles alimentent la bibliothèque commune. |
| `back/app/skill/resource_facade.py` | Une connexion `skill_management` active permet l'accès aux fichiers des packages utilisateurs. `create_skill_file` peut créer un package par son `SKILL.md`, sans propriétaire. |
| `back/app/skill/mcp.py` | Deux lectures administratives : `skills_list(agent_id, ...)` et `skill_read(skill_code)`. L'identité appelante n'y filtre actuellement pas une propriété personnelle ; ajouter un champ propriétaire ne suffirait donc pas. |
| `back/app/file_share/galaris_provider.py` | Les opérations `file_*` routent `galaris://skill/<code>/<path>` vers la façade Skill. C'est la surface à réutiliser pour les fichiers, sans lecteur MCP concurrent. |
| `back/app/tools/mandatory_tools.py`, `descriptions.py` | `skill_management` est optionnel, inactif par défaut, et correspond à une administration commune. Il ne faut pas devoir l'accorder pour écrire seulement ses propres skills. |
| `back/app/skill/projection.py`, `back/app/harness/skills.py` | Les skills affectées et les skills apprises admissibles alimentent les projections et capabilities. Plusieurs identités sont encore réduites au seul `code`. |
| `back/app/harnesses`, bridges Hermes, Codex, Claude Agent et DeepSeek Harness | Les providers consomment les snapshots et projettent actuellement les répertoires par code. Préserver la réconciliation avant exécution, sans redémarrer une Task en cours, décrite par la décision 0131. |
| `front/app/skill/pages/index.vue` | Onglets bibliothèque, skills apprises si l'apprentissage est actif, et autorisations selon les droits. Aucun onglet personnel. |
| `back/app/skill/router.py` | Les lectures de bibliothèque utilisent les privilèges Skills ; les mutations communes demandent une portée globale. Les skills apprises utilisent déjà `current_management_scope` pour limiter les agents visibles. |

Les **skills apprises** existent déjà dans `LearnedSkill`, avec propriétaire agent, preuves,
score et suspension. Leur contenu est autoritatif en base ; `.learned/` n'est qu'une projection.
Elles restent dans leur onglet et leur mécanisme actuels. Les skills personnels demandés ici sont
des packages éditables volontairement, indépendants de Dream et de ses seuils d'apprentissage.

Sources complémentaires : [0047](../decisions/0047-evidence-reinforced-learned-skills.md),
[0131](../decisions/0131-harness-skill-reconciliation.md),
[flux agentique](../../docs/fr/architecture/flows/agent-execution.md) et
[catalogue de tests](../../docs/fr/dev/functional-tests.md).
Cette section décrit le diagnostic initial. Depuis, les workflows agent et les consommateurs
sont testés sur PostgreSQL éphémère et l'onglet est exercé dans le navigateur isolé ;
aucun comportement de production n'a été testé.

## Modèle et invariants proposés

Étendre `Skill` dans `app.skill`, sans nouveau domaine métier ni stockage dans Memory :

- `owner_agent_id`, FK nullable vers `agents.id` : `NULL` signifie générique ; une valeur signifie personnel.
- Conserver une provenance de création agent indépendante de la propriété, via un champ d'audit
  adapté ou une FK `creator_agent_id` immuable. Le retrait du propriétaire n'efface pas l'auteur.
- Un skill système est toujours générique et sans propriétaire ; aucune conversion en personnel.
- Un skill personnel n'a ni activation globale ni catégorie partagée. La base et le service
  refusent les configurations incompatibles, sans compter sur l'interface.
- L'identité métier distingue portée, propriétaire et code. Conserver l'unicité des codes
  génériques et rendre un code personnel unique pour son propriétaire, par index uniques partiels.
  Deux agents peuvent utiliser le même code, et un générique peut porter ce même code.
- L'identifiant primaire du skill reste stable pendant le retrait de propriété. Remplacer les
  résolutions ambiguës par code par une référence typée ou un identifiant avec contrôle de portée.
- Ajouter une révision de package pour les mutations de contenu, métadonnées et propriété.
  Les écritures et la conversion partagent le même contrôle de concurrence ; une révision de
  fichier seule ne protège pas une conversion concurrente du package entier.

Réutiliser `AgentSkill` uniquement pour l'activation personnelle du propriétaire : création avec
`active=True`, désactivation explicite possible, aucun couple pour un autre agent. La résolution
personnelle ignore entièrement l'héritage global et les catégories. Une absence d'association
personnelle n'active rien. La matrice complète reste réservée aux génériques, dans le service
comme dans les datasets DbAdmin.

Le propriétaire est fixé à l'agent créateur à partir du contexte authentifié. Aucun argument MCP,
frontmatter, chemin ou import ne permet de choisir un autre propriétaire. Une mutation ordinaire
ne peut ni changer ni effacer `owner_agent_id`.

## Permissions et accès

Renommer le Tool `skill_management` en **Skills** (`skills`). Le paramètre dédié de connexion
`tools.management_scope` porte `usage`, `personal`, `team`, `all`. Il est local, sans héritage
global, modifiable uniquement par un humain habilité à éditer les connexions et gérer tous
les agents. Sa définition est réutilisable par les futurs Tools concernés.

| Opération | Usage (`usage`) | Personnel (`personal`) | Équipe (`team`) | Tous (`all`) |
|---|---|---|---|---|
| Lire pour utilisation | Génériques autorisés et personnels propres actifs. | Idem. | Idem ; administration distincte de l'usage. | Idem ; administration distincte de l'usage. |
| Créer | Non. | Ses personnels. | Ses personnels. | Personnels propres ou génériques. |
| Modifier/supprimer et activer un personnel | Non. | Les siens. | Les siens et ceux des agents partageant au moins une équipe active. | Tous les agents. |
| Modifier/supprimer un générique | Non. | Non. | Non. | Oui, hors packages système. |
| Affecter les génériques/catégories | Non. | Non. | Aux agents de l'union de ses équipes et à soi-même. | À tous. |
| Retirer une propriété | Non. | Non. | Non. | Oui, par commande explicite et auditée. |

Les packages système restent protégés contre les mutations de contenu et la suppression, même
avec la portée `all` ; leurs autorisations ordinaires restent administrables. « Tous » désigne
la portée de gestion, sans abolir les invariants du domaine.

Les droits humains restent distincts : consultation avec privilèges Skills et périmètre de
gestion des agents ; mutations avec `SKILL_EDIT` dans ce périmètre ; affectations génériques
avec `SKILL_ASSIGN` ; retrait de propriété avec `SKILL_EDIT` et gestion globale. Un humain hors
périmètre n'accède pas aux personnels. Ne jamais exécuter un accès humain sous l'identité de
l'agent sélectionné dans un filtre.

### Fonctions communes et contrôle de portée

Conserver une seule famille de fonctions, sans variantes `personal_*` et `admin_*` du même CRUD.
Les noms ci-dessous sont des contrats proposés à figer au lot 0 :

| Surface | Rôle et portée vérifiée |
|---|---|
| `skills_list` | Par défaut, catalogue utilisable de l'appelant. Une vue d'administration ou une cible étrangère exige `team` dans son périmètre, ou `all`. Filtrer côté serveur avant pagination. |
| `skill_read` | Lecture du seul `SKILL.md`, avec identité non ambiguë. Usage autorisé ou accès administratif `team/all` explicitement demandé. |
| `file_list`, `file_search`, `file_info`, `file_read` | Accès aux fichiers et références par URI, dans les mêmes portées de lecture. |
| `file_create`, `file_write`, `file_edit`, `file_append`, `file_delete`, `file_move` | Création/édition des packages et annexes : portée `personal` pour les siens, `all` pour l'administration globale. Les limites de suppression/move du `SKILL.md` restent applicables. |
| `skill_update` | Modification des métadonnées du package, par exemple son libellé, avec contrôle de révision et de portée ; le contenu des fichiers reste géré par `file_*`. |
| `skill_set_enabled`, `skill_delete` | Activation personnelle et suppression logique du package complet ; mêmes fonctions pour gestion propre ou globale selon la cible. |
| `skill_set_authorization`, `skill_set_category_authorization` | Portée `team` dans son périmètre, ou `all` ; distribuer les génériques avec les états et héritages existants. |
| `skill_release_ownership` | Portée `all` uniquement ; conversion personnelle → générique, avec révision et reçu d'opération. |

Les fonctions `file_*` restent rattachées au Tool `file_sharing`. Elles délèguent au même contrôle
de portée du domaine Skill que les commandes du Tool `skills`. Les nouveaux noms ne créent pas
un second lecteur de ressources ou une seconde implémentation du CRUD.

La présence d'une connexion `skills` ou d'une fonction dans un toolset n'est jamais une preuve
d'administration. Chaque appel évalue l'acteur authentifié, la portée persistée courante,
l'opération et sa cible. La cible ou un argument `scope=all` ne peuvent pas élargir la portée.
Les fonctions impossibles pour un niveau peuvent être masquées à la découverte pour simplifier
le catalogue ; ce masquage complète le contrôle, sans le remplacer.

Composer cette politique avec les modes Actif/Bloqué/Sur demande et les restrictions de contexte
existants : un accord sur une fonction ne donne pas une portée supérieure. Une baisse de portée
de `all` vers `personal` bloque aussitôt les prochaines mutations étrangères et génériques ; une
baisse vers `usage` bloque toutes les écritures, sans supprimer le droit d'utiliser ses skills.
Une connexion désactivée ne conserve aucun pouvoir de gestion. Ne pas coupler le chargement
ordinaire de skills déjà autorisés à la possession d'un droit d'administration.

Seule une autorité habilitée peut changer la portée d'un agent. Ni le CRUD de skills, ni
l'autorisation d'attribuer un générique, ni l'édition ordinaire des paramètres de connexion ne
permettent de s'octroyer `all` ou de l'accorder à un autre agent. La délégation des portées est
distincte de la distribution des skills.

Vérifier les droits sur chaque accès par ID ou URI et filtrer recherches, compteurs, erreurs,
téléchargements et métadonnées. Hors accès administratif `team` autorisé ou `all`, un personnel étranger est
introuvable. La portée administrative autorise sa gestion, jamais sa projection comme skill utilisable
par un autre agent tant que la propriété demeure.

## Séparation des fichiers et des URI

Conserver les URI génériques existantes et introduire une collection personnelle distincte :

```text
galaris://skill/<code>/SKILL.md
galaris://skill/personnal/<agent_id>/<code>/SKILL.md
```

Conserver exactement le segment `personnal` demandé. La hiérarchie est : `skill/` → `personnal/`
→ propriétaire → package → fichiers. `galaris://skill/personnal/` ne montre que la branche de
l'appelant aux niveaux `usage` et `personal` ; en vue d'administration, `team` couvre l'union
de ses équipes et `all` tous les agents. `galaris://skill/personnal/<agent_id>/` liste les packages de cet
agent selon les mêmes contrôles. Le propriétaire dans l'URI identifie une cible, jamais un acteur.
La racine `skill/` expose séparément sa branche personnelle et ses packages génériques autorisés ;
elle ne mélange pas leurs lignes dans les catalogues applicatifs.

Les réponses rendent les URI canoniques exactes et les métadonnées de portée/propriétaire. Le
routage reconnaît la branche `personnal` avant la résolution ordinaire d'un code générique.
Réserver ce segment pour les nouvelles créations génériques et vérifier les éventuels packages
historiques nommés `personnal` avant migration : définir leur compatibilité sans écrasement,
renommage silencieux ou interprétation d'un ancien chemin comme un accès personnel.

Les packages personnels sont persistés séparément, par exemple sous
`GALARIS_SKILLS_ROOT/.personal/<owner-agent-id>/<code>/`. Ce sous-répertoire n'est jamais parcouru
comme bibliothèque générique par un rescan. La base reste l'autorité de la propriété ; ne pas la
déduire d'un fichier `SKILL.md`, d'un nom de répertoire ou d'une projection externe.

Créer le premier `SKILL.md` par `file_create` crée le package personnel avec son propriétaire et
son activation. Les fichiers suivants passent par les opérations existantes. Préserver validation
du frontmatter, chemins relatifs, refus des liens symboliques, bornes de taille et écritures atomiques.
L'absence de console n'empêche ni création ni lecture.
Conserver les limites de fichiers existantes et borner aussi le nombre et le volume cumulés des
packages personnels par agent ; fixer ces budgets avant d'ouvrir la création autonome.

Aucun endpoint de partage ou d'affectation ne prend un personnel comme cible. Refuser aussi
`file_copy` et `file_move` pour exporter un package personnel hors de son espace ou le transformer
en générique ; ce changement de statut appartient exclusivement à la commande de retrait.
Les temporaires internes nécessaires à une exécution ne deviennent pas des ressources partagées.
Cette garantie concerne les ressources et les autorisations ; elle ne prétend pas empêcher un
acteur autorisé à lire de reformuler un texte dans une autre sortie.

## Retrait de propriété : passage au catalogue générique

Prévoir une commande administrative explicite, distincte de `SkillUpdate`, disponible en HTTP
pour l'humain habilité et en MCP par `skill_release_ownership` pour un agent de portée `all`.
Exemple de contrat HTTP à figer :
`POST /skills/{skill_id}/release-ownership`, avec `expected_revision` et un éventuel nouveau code.

1. Vérifier le droit de conversion de l'acteur : `SKILL_EDIT` et gestion globale côté humain,
   ou portée `all` côté agent ; puis état personnel, propriétaire existant et révision.
2. Vérifier le code dans l'espace générique. En cas de collision, répondre en conflit et demander
   un autre code ; aucun écrasement ou renommage silencieux. Si renommé, adapter le frontmatter validé.
3. Préparer le déplacement du package depuis le stockage personnel vers le stockage générique.
4. Retirer la propriété, supprimer l'activation personnelle, laisser la catégorie vide et
   l'activation globale désactivée ; reconstruire les associations génériques avec héritage
   désactivé. Le précédent propriétaire ne garde aucun accès implicite.
5. Journaliser auteur de l'action, ancien propriétaire et identité stable. Invalider les projections
   affectées ; ne rendre le succès qu'après une transition cohérente des métadonnées et fichiers.

L'interface confirme explicitement : « Ce skill deviendra générique. Ses autorisations devront
ensuite être configurées. » Il disparaît de la liste personnelle, apparaît dans la bibliothèque
générique et sa matrice d'autorisations devient accessible. Aucun bouton de partage n'est présent
avant cette conversion. Le transfert vers un autre propriétaire et la conversion inverse restent
hors périmètre.

Prévoir un reçu d'opération pour qu'un double clic ou rejeu restitue la conversion sans refaire le
déplacement ni réinitialiser des autorisations déjà modifiées ensuite. Les anciennes URI personnelles
ne restent pas un chemin de lecture vers le nouveau générique ; ne pas créer de redirection qui
conserverait implicitement les anciens droits. Afficher la nouvelle URI dans le résultat.

La base et le disque n'ayant pas de transaction commune, utiliser staging/quarantaine et un état
de reprise explicite si nécessaire. Tester panne avant/après déplacement, échec de commit et échec
de nettoyage ; conserver l'original et la cause primaire jusqu'à publication certaine. Aucune étape
intermédiaire ne doit exposer le package simultanément dans les deux portées.

## Chargement par les agents et compatibilité des harnais

Le catalogue effectif d'un agent réunit trois ensembles identifiés : génériques autorisés,
personnels actifs dont il est propriétaire, skills apprises admissibles. L'agrégation pour
l'exécution ne les fusionne pas dans l'administration et ne change pas leurs droits.

Introduire une référence publique de package contenant identité stable, portée, propriétaire,
code et emplacement autorisé. Éviter d'ajouter une convention de préfixe au `code` métier pour
simuler la propriété. Les adaptateurs attribuent des noms de capability, outils et répertoires
de projection distincts et déterministes. Qualifier les contraintes de noms/frontmatter de chaque
provider ; si une adaptation est nécessaire, elle touche la projection, jamais le contenu source.
Un homonyme doit rester accessible à côté du générique et de l'appris : aucun écrasement ou `skip`
silencieux. Cette qualification est un préalable au choix final des identifiants projetés.

Inventaire minimal des consommateurs à adapter :

- `skill_service` : résolutions par code, catalogue, autorisations, matrice, catégories et suppression.
- `resource_facade`, MCP et provider `galaris://` : toutes les lectures et mutations, y compris
  chemins annexes, recherche, transferts et métadonnées.
- `app.harness.skills` : capabilities eager/différées et accès aux ressources en Task, texte et voix.
- `app.skill.projection`, `app.agent` et `app.harnesses` : snapshots, empreintes et préparation.
- Bridges Hermes, Codex, Claude Agent et DeepSeek Harness ; injection bornée des harnais réseau
  sans projection. Auditer aussi les utilitaires historiques qui utilisent directement le stockage.

Préserver la décision 0131 : contenu courant au prochain démarrage, invalidation durable,
échec de préparation bloquant, retrait des fichiers devenus non autorisés et aucun redémarrage
d'une Task en cours. Une reprise distante avec checkpoint conserve son contexte existant.
Créer ou modifier un skill ne garantit pas que le modèle le charge dans le tour déjà ouvert ;
la réponse de mutation indique sa disponibilité pour la prochaine construction du contexte.
Les contrôles d'accès aux outils restent actifs même si un texte a déjà été chargé.

## Onglet « Skills personnels »

Ajouter cet onglet à `/skill`, à côté de la bibliothèque générique et des skills apprises,
indépendamment de l'activation de Dream. Il présente la liste des skills de tous les agents du
périmètre humain autorisé, puis permet de filtrer par agent propriétaire et de rechercher.

Afficher propriétaire, nom/code, description, activation personnelle, validité, nombre de fichiers
et dernière modification. Prévoir consultation du `SKILL.md` et de ses références, édition et
suppression selon les droits. Le retrait de propriété est réservé à l'administrateur global,
avec confirmation et gestion du conflit de code. Pour la première version, la création personnelle
vient de l'agent lui-même ; un humain peut ensuite administrer ce package dans son périmètre.
Un DRH agentique de portée `all` effectue les mêmes opérations par MCP, avec audit de son identité
réelle ; l'onglet conserve la visibilité des propriétaires et des actions réalisées.

Aucun sélecteur de destinataire, partage, catégorie commune ou autorisation globale n'apparaît
pour un personnel. Le catalogue générique et l'onglet Autorisations excluent ces lignes côté
serveur, y compris leurs recherches et compteurs. Le filtre propriétaire ne vaut jamais droit.
Des DTO explicites distinguent les trois familles pour éviter un mélange dans l'état frontend.

Prévoir chargement, liste vide, erreur/retry, réouverture, réponses tardives lors d'un changement
de propriétaire filtré et disparition d'une ligne convertie/supprimée. Pagination serveur à 50,
options `[10, 20, 50, 100, 500]`, clavier et petit viewport. Respecter Solaire, boutons Quasar,
fermeture des modales par arrière-plan et parité i18n FR/EN. Tester les effets et les refus,
sans figer la disposition de l'onglet dans des assertions de présentation.

## Évolution des données et suppression d'un agent

Tous les packages ordinaires existants restent génériques : nouveau propriétaire `NULL`,
aucune inférence à partir des anciens logs ou `created_by`. Conserver leurs codes, fichiers,
catégories et autorisations. Les `LearnedSkill` restent inchangées. Ne pas attribuer rétroactivement
un skill à l'agent qui aurait historiquement créé ses fichiers.

Faire évoluer les modèles et index par `core.dbadmin`. Adapter ses datasets et le rescan pour
ne créer la matrice complète que pour les génériques, préserver les propriétaires et ne jamais
restaurer un personnel sous forme générique. Si une transformation de données est nécessaire,
utiliser les actions/reconcilers DbAdmin avec postconditions, sans migration manuscrite.

Le renommage `skill_management` → `skills` est une évolution d'identité du Tool, pas une création
concurrente. Préserver les relations existantes : connexions, paramètres, états par fonction,
restrictions de contexte et références des autorisations. Faire converger déclarations MCP,
descriptions, UI et contrôles vers le nouveau code. Qualifier les reçus/accords déjà persistés :
un accord ancien ne doit ni élargir une portée ni contourner la nouvelle politique.

Migrer explicitement les anciennes connexions administratives actives vers `all`, pour préserver
la délégation large déjà accordée, et conserver les désactivations existantes. Les nouvelles
connexions et les valeurs de portée absentes/inconnues ne reçoivent jamais `all` implicitement :
défaut `usage`, valeur invalide refusée. La migration utilise l'état historique identifié, pas
la simple présence d'une connexion au Tool renommé. Aucun Tool personnel séparé n'est créé.

La suppression d'un agent ne retire jamais automatiquement sa propriété : cela publierait ses
skills. Avec la suppression logique actuelle de l'agent, conserver le rattachement pour audit,
rendre les skills inactifs et les retirer de toute projection. Le contenu reste récupérable par
une administration globale selon une politique explicite. Une éventuelle purge physique doit
supprimer/archiver ces données ou être bloquée, jamais appliquer `ON DELETE SET NULL` sur le
propriétaire. Tester la restauration sans activation silencieuse.

## Lots de réalisation et critères de réception

| Lot | Travail | Preuve attendue |
|---|---|---|
| 0 — Contrats | Figer les quatre portées du Tool unique `skills`, leur délégation, la hiérarchie `skill/personnal/`, l'activation, la conversion et le mapping des noms de harnais. Inventorier les consommateurs. | Matrice usage/personal/team/all, droits DRH et homonymes qualifiés ; compatibilité du segment réservé et décision structurelle prêtes. |
| 1 — Modèle et services | Propriété, unicité par portée, stockage séparé, politique commune, datasets DbAdmin et conservation de l'existant. | Intégration DB : deux propriétaires homonymes, générique homonyme, cascade générique inchangée, rescan sans publication. |
| 2 — Tool et portées | Renommage sans duplication, politique commune aux commandes et File Sharing, CRUD selon la cible, autorisations et conversion globale. | À fonctions identiques : usage lit mais n'écrit pas ; personal gère seulement ses packages ; all administre l'ensemble et distribue les génériques. B sans all ne trouve pas le personnel de A ; baisse de portée effective à l'appel suivant. |
| 3 — Première exécution | Capabilities internes et snapshots enrichis, application de la réconciliation, puis qualification par groupes de providers. | Parcours complet A crée → prochaine exécution découvre/charge ; B n'a aucun fichier ni contenu. Même code dans trois familles sans perte ; erreur de projection bloque le départ. |
| 4 — Administration humaine | Onglet dédié, filtres, API scoping, contenu et actions autorisées. | Liste multi-agent dans le périmètre, refus hors périmètre, permissions serveur, erreur/retry, navigation/réouverture et réponse tardive. Aucune ligne personnelle dans le catalogue générique. |
| 5 — Retrait de propriété | Conversion humaine ou agent all, collision, staging/reprise, audit et invalidation des projections. | Personnel jamais partageable, même par all ; après conversion, même identité devenue générique, personne activée, autorisations configurables, ancien chemin fermé, rejeu sans effets supplémentaires. |
| 6 — Qualification et documentation | Pannes, suppression/restauration d'agent, limites, parcours FR/EN et documentation des droits. | Matrice de réception complète, données existantes conservées et limites des contextes déjà chargés explicites. |

## Stratégie de vérification

Renforcer les suites existantes avant d'ajouter des scénarios parallèles :

- `back/app/skill/tests/test_service.py`, `test_storage.py`, `test_resource_facade.py`,
  `test_mcp.py` et `test_agent_reads.py` pour propriété, matrice, conflits et périmètres humains.
- `back/app/file_share/tests/test_galaris_provider.py` pour routage, recherche, annexes et refus
  des opérations de partage/copie/move contournant la conversion.
- Suites Tools/Connection pour renommage et conservation des connexions, paramètres, accords
  et désactivations ; contrôle des quatre portées sur les mêmes fonctions, y compris via `file_*`,
  accords Sur demande, catalogue ancien et révocation. Tester le refus d'auto-élévation.
- `back/app/skill/tests/test_projection.py`, `back/app/harness/tests/test_skills.py`,
  `back/app/harnesses/tests/test_skill_sync.py` et suites des bridges pour disponibilité réelle,
  homonymes, disparition, changements de propriétaire et invalidation tardive.
- `front/browser-tests/skills.spec.mjs` pour les interactions durables de l'onglet ; quelques
  parcours assemblés pour création par un agent, utilisation et conversion administrative.

Utiliser services et DB réels pour les workflows ; remplacer seulement les transports externes.
Tester deux créations concurrentes identiques, conflit de révision, mutation pendant conversion,
double conversion, panne de stockage/commit et reprise. Les commandes existantes d'append, move,
delete et import doivent respecter la même isolation ; ne pas limiter les tests au seul `file_write`.
Exercer le parcours DRH : lister administrativement → créer/éditer un générique → attribuer à
un agent → vérifier son chargement → révoquer. Pour un personnel, l'affectation étrangère reste
refusée jusqu'à une conversion explicite ; l'accès administratif all ne l'injecte pas au DRH.
Conserver uniquement des données synthétiques.

À l'implémentation : tests ciblés via `make tests ARGS='…'`, contrôles frontend pertinents,
`make typecheck`, `make architecture-check`, `make docs-prepare` et `git diff --check`.
La validation globale `make validate` reste exclusivement exécutée par l'utilisateur.
La rédaction de ce plan ne justifie ni test de code, synchronisation DB, redémarrage ni déploiement.

Documenter la décision acceptée au moment de l'implémentation ; actualiser les parcours utilisateur
FR/EN, les descriptions des Tools, le skill runtime Galaris et le catalogue de tests. Régénérer
les cartes à partir des sources. Maintenir le statut de ce plan et son entrée dans l'index ;
le statut `in-progress` conserve explicitement les interfaces humaines encore absentes.
