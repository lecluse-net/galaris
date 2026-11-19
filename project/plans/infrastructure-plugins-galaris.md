# Plugins Galaris — conception de distribution et activation

- Statut : `partial`
- Revue des sources : 2026-11-18.

## Résultat recherché

Installer un bundle versionné, déclaratif ou exécutable, puis activer ses contributions
dans une génération cohérente du backend et du frontend. Dans **Administration → Plugins**,
chaque plugin a une fiche avec son code, son libellé, sa version, sa description et ses
capacités. L'administration peut expliquer la compatibilité de chaque version, désinstaller
le plugin en conservant les données réutilisables et demander séparément leur purge.
Le futur App Store réutilise l'installateur local.

Le bootstrap statique de `back/modules.py` et `front/modules.ts` reste le socle courant ;
il ne constitue pas une infrastructure d'installation de plugins.
`plugins` représente une origine de distribution/confiance, pas une quatrième couche
métier. Les contributions passent par les surfaces publiques de core/app/bridge.
Le [chantier d'écosystème](cible.md#écosystème-signé) porte la direction produit.

Le pilote déclaratif installe et active des bundles de fiches de Service depuis
**Administrer → Plugins**. Son contrat et son parcours sont dans le
[guide des bundles](../../docs/fr/dev/plugin-bundles.md) et la
[décision 0300](../decisions/0300-declarative-plugin-installation.md).

## Familles de contributions

Un plugin est une unité de distribution ; il peut fournir plusieurs contributions
typées. Un même bundle pourrait associer un stockage, un Service préconfiguré, un lecteur
et un éditeur. Une famille n'impose ni un package distinct ni un nouveau domaine métier.
Les familles ci-dessous sont une cible de conception, pas des extensions déjà disponibles.

| Famille | Contributions envisagées | Domaine hôte / frontière |
|---|---|---|
| Interfaces File Share | Transports de stockage, navigation paginée, métadonnées, lecture/écriture, copie, déplacement, suppression et partage selon capacités réelles. Google Drive, Dropbox, Proton Drive, autres clouds ou stockages spécialisés. | `app.file_share` conserve les URI et opérations génériques ; `app.connection` possède configuration et secrets. |
| Fournisseurs | Modèles LLM, embeddings, reranking, image, vidéo, transcription et synthèse vocale. | Ports publics des domaines IA/média ; résolution, admission, coûts et suivi restent gouvernés par l'hôte. |
| Fiches de Service et outils | Définitions de Service préconfigurées, instructions, paramètres non secrets et outils appelables. Une fiche peut être purement déclarative. | `app.services` expose le Service et ses fonctions, `app.mcp` expose les outils et `app.connection` gère les comptes. |
| Capacités et protocoles de Service | Ajout d'un protocole à une capacité existante, contribution d'une capacité et de ses protocoles, ou fourniture d'un adaptateur d'exécution. | `app.services` compose le catalogue et les sélections. Les domaines hôtes possèdent les contrats d'exécution de leurs capacités. |
| Visualisation de fichiers | Lecteurs pour formats spécialisés, miniatures, inspection de métadonnées, navigation dans une archive ou un assemblage, rendu 2D/3D. | Extension des aperçus et lecteurs ; la source peut appartenir à n'importe quel provider File Share autorisé. |
| Édition de fichiers | Éditeurs spécialisés d'image, audio, vidéo, CAO ou scène 3D, opérant sur une URI externe sans imposer son import dans Documents. | Sauvegarde par le provider propriétaire ; capacités et contrôle de concurrence vérifiés avant de proposer l'édition. |
| Formats de document | Types créables et éditables dans la bibliothèque : CAO, MAO, image, vidéo, scène 3D et autres projets spécialisés. | `app.document` conserve identité, métadonnées, ACL, classification et révisions ; le plugin apporte le format et ses comportements. |
| Import, export et analyse | Convertisseurs de formats, OCR, extraction de texte/structure, indexation spécialisée et export d'un projet ou d'un rendu. | Ports des domaines Document, aperçu et acquisition/recherche ; dérivés traçables, bornés et soumis aux droits de la source. |
| Exécution agentique | Drivers, harnais, capacités et adaptateurs de runtimes externes. | Contrat `app.agent` ; persistance, transitions et leases restent dans `app.task`. |
| Canaux et événements externes | Bridges Messenger/voix, calendriers, webhooks et sources d'événements. | Traduction vers les façades canoniques, sans workflow Task parallèle dans le plugin. |
| Processus métier | Adaptateurs de moteurs, activités métier et préréglages de véritables workflows. | `app.process` possède définitions BPMN, historique et grants ; un outil technique isolé ne devient pas un Process. |
| Interfaces et packages métier | Vues, panneaux spécialisés, tableaux de bord, skills, modèles d'agents ou packs métier combinant plusieurs contributions. | Slots SDK et façades des domaines concernés ; aucun accès implicite aux données ou aux Services du fait du pack. |

Premières qualifications avec quatre bundles synthétiques construits hors du dépôt.
Une fiche de Service éprouve la distribution de données. Un fournisseur IA éprouve le
chargement backend. Un protocole de Service éprouve l'éditeur, la Connexion et le dispatch.
Un format documentaire simple éprouve le chargement frontend et la récupération des données
après retrait. Un connecteur File Share et un lecteur de fichiers vérifient ensuite que la
composition couvre aussi les ressources externes.

### Réemploi de connecteurs de stockage

Évaluer un bridge Galaris vers **Rclone** afin de réutiliser ses connecteurs Google Drive,
Dropbox et d'autres stockages, plutôt que réimplémenter chaque API. Le plugin expose des
profils de fournisseurs explicites ; les locators Rclone et sa configuration restent internes.
Le schéma d'une connexion reste le code du Service, conformément au contrat File Share.
Une interface commune ne prouve pas des garanties identiques : qualifier pagination,
identité des fichiers de même nom, exports Google Docs/Sheets/Slides, renouvellement OAuth,
fraîcheur des métadonnées, taille des transferts et écritures concurrentes par fournisseur.

Pour **Proton Drive**, comparer ce réemploi à un bridge vers le **CLI officiel Proton**.
Lors de la revue, le backend Rclone Proton est classé expérimental et documente des limites
de cache en présence d'autres clients ; le SDK Proton direct n'est pas encore présenté
comme prêt pour les applications tierces en production. Le CLI officiel fournit une piste
de prototype, pas une intégration Galaris déjà qualifiée. Vérifier connexion par navigateur,
persistance/renouvellement de session et fonctionnement sans interface graphique dans Docker.
Références à revalider au prototype : [support Rclone](https://rclone.org/tiers/),
[backend Proton](https://rclone.org/protondrive/),
[CLI Proton](https://proton.me/support/drive-cli),
[SDK Proton](https://github.com/ProtonDriveApps/sdk#current-status).

La première expérience vise Google Drive via Rclone : connexion, navigation, lecture,
création, modification et copie vers un autre provider, avec refus d'accès et conflits.
Comparer ensuite Dropbox et Proton sans annoncer les opérations non vérifiées. Galaris
conserve l'isolation des connexions/agents, les secrets côté serveur, les limites de
transfert et les erreurs explicites. Les binaires doivent être versionnés et fournis par
l'image/SDK au premier palier, ou par un service externe supervisé explicitement supporté ;
le plugin n'installe pas arbitrairement des dépendances au démarrage.

### Services préconfigurés

Un plugin peut distribuer une définition de Service, ses schémas, libellés FR/EN,
instructions et paramètres non secrets. Une fiche sélectionne des protocoles disponibles,
qu'ils soient intégrés à Galaris ou fournis par un plugin. Elle déclare ses dépendances de
contribution avec leurs versions compatibles. Le même protocole peut servir à plusieurs fiches
et être ajouté directement à un Service existant par son administrateur.

L'activation publie la fiche dans le catalogue existant. L'enregistrement explicite dans
l'éditeur crée une copie locale avec provenance, selon le [contrat des fiches YAML][catalogue].
Une nouvelle version peut proposer des valeurs actualisées. L'administrateur choisit les
changements à appliquer à sa copie. Les secrets, sessions et comptes sont configurés dans
les Connexions et restent locaux. Installation, activation, création d'une Connexion et
autorisation d'appel correspondent à quatre décisions distinctes.

### Capacités et protocoles de Service

La [décision 0274][capacites] distingue la fonction rendue (par exemple Messagerie) de
son protocole (par exemple OneBot). `GET /api/services/capabilities` alimente déjà le menu
**Ajouter un protocole**. Les sélections ont la forme `protocole.capacité` et chaque Service
choisit au plus un protocole par capacité. Le code actuel associe les capacités intégrées
à des champs typés tels que `mcp_config`, `file_share_config` et `mail_config`. La
conservation d'un identifiant externe fournit la portabilité du Service. Son exécution
exige un adaptateur enregistré.

| Contribution | Contrat proposé |
|---|---|
| Capacité | Code stable, libellés FR/EN et contrat d'opérations. Une capacité intégrée garde son domaine hôte. Une nouvelle capacité peut publier ses propres fonctions via Services/MCP. Une intégration à une surface métier de Galaris exige un port explicite de ce domaine. |
| Protocole | Identifiant `protocole.capacité`, version de contrat, schéma des réglages fixes et rôles de Connexion avec types, caractère obligatoire, contraintes et paramètres génériques suggérés. Déclaration des opérations, de la sonde et du mode entrant/sortant selon les fonctions réellement fournies. |
| Implémentation | Point d'entrée backend ou endpoint isolé, version du contrat supportée et opérations typées. Un protocole peut réutiliser une implémentation présente. Un nouvel adaptateur File Share ou Messenger se branche sur le port du domaine concerné. |
| Sélection du Service | Protocole choisi, version du schéma de configuration, `settings` et `param_map`. L'identité de la Connexion et les valeurs résolues appartiennent au contexte d'exécution. |

**Configuration.** OneBot fournit le modèle pour les champs fixes et les références.
`settings` contient les choix communs au Service, par exemple une plateforme.
`param_map` associe chaque rôle technique à un paramètre ordinaire, par exemple
`user_id` ou `token`. L'éditeur standard rend les champs à partir du catalogue et
réutilise les sélecteurs de paramètres. La création d'un paramètre exige une action
explicite. Deux rôles ou protocoles peuvent référencer le même `login`, `password`
ou `token`. Le serveur valide types et références et vérifie leurs usages avant
suppression. Les valeurs propres au compte et les secrets sont saisis dans l'éditeur
standard de Connexion. La validation s'applique aussi aux fiches YAML, imports et API.

**Persistance et compatibilité.** Ajouter à la surface Services une collection
`protocol_configs` indexée par identifiant de sélection, avec une enveloppe versionnée
pour les protocoles externes. Les champs intégrés restent la source de leurs réglages au
premier palier. Le catalogue et la résolution proposent une lecture commune de ces deux
origines, avec une configuration canonique par sélection. Les identifiants et configurations
indisponibles restent exportables et survivent à l'enregistrement par un client ancien.
Une mise à jour historique qui ignore `protocol_configs` ne peut effacer ni ses entrées
ni leurs références de paramètres. Le retrait explicite passe par le nouveau contrat.
Leurs opérations et leur sélection pour de nouveaux Services sont indisponibles tant que
l'implémentation compatible manque. Une configuration orpheline reste visible et peut être
détachée explicitement. Une éventuelle migration de champs intégrés vers l'enveloppe se
qualifie protocole par protocole avec DbAdmin.

**Exécution.** Galaris résout le protocole, la fonction et une Connexion précise. Il
applique les autorisations de l'acteur, les modes Actif/Bloqué/Sur demande, les accords
de contexte et les ACL, puis appelle l'adaptateur avec les seules données nécessaires.
Les opérations sur les ressources respectent les contrats File Share, Messenger ou du
domaine concerné. Réutiliser le port de sonde existant pour tester une connexion enregistrée,
avec délais bornés et diagnostics expurgés. Pour une entrée asynchrone, Galaris expose un
point d'entrée gouverné et transmet les événements au domaine propriétaire de la réception,
avec authentification, isolation par Connexion et idempotence des doublons. Le SDK définit
l'arrêt des écouteurs et l'invalidation des appels tardifs. L'identité des Services système
et leurs protections sont réservées à Galaris.

[catalogue]: ../../docs/fr/dev/service-catalog.md
[capacites]: ../decisions/0274-provider-tool-protocols.md

### Lecteurs, éditeurs et formats documentaires

Séparer trois contrats composables : **visualiser une ressource**, **éditer son format**
et **créer un type de Document révisé**. Un lecteur seul reste utile sans éditeur ; un éditeur
de fichier externe ne crée pas automatiquement de Document. Exemple de bundle CAO : lecteur
d'assemblages, miniature, import/export, éditeur et type documentaire partageant le même codec.
Autres cas : session MAO multipiste avec médias liés, image à calques, montage vidéo avec
sources et rendus, scène 3D avec géométries, matériaux, textures et animations.

Le descripteur de contribution précise formats/MIME et versions acceptés, détection bornée,
capacités lecture/édition/création/export, version du codec et du schéma de contenu,
composant frontend et éventuel convertisseur/runtime serveur. La sélection entre plusieurs
lecteurs/éditeurs est déterministe, respecte le choix utilisateur et ne remplace pas implicitement
les formats natifs. Définir un port d'édition pour l'UI et, si pertinent, des opérations typées
utilisables par les agents, soumises aux mêmes validations et autorisations.

Les [formats de document](../../docs/fr/dev/document-formats.md) disposent désormais d'une
façade extensible sous l'autorité de `app.document`, avec catalogue de capacités et TCK.
Le chargeur de plugins devra utiliser ces mêmes ports et associer les preuves à son bundle
effectif ; aucune installation dynamique ni certification de code tiers n'est livrée par ce socle.
Les nouveaux formats
apparaissent dans la bibliothèque commune et réutilisent partage, classification, recherche,
historique et révisions ; ne pas créer une bibliothèque ou des ACL parallèles par format.

Les binaires restent des fichiers immuables de `core.storage` retenus par leurs révisions.
Un projet multifichier demande un snapshot cohérent de son fichier principal et de ses assets,
avec références validées et sans accès implicite aux fichiers externes. Arbitrer archive autonome
ou manifeste d'assets immuables avant le premier type multifichier ; toute sauvegarde publie
une révision complète ou conserve la précédente en cas d'échec. Une référence externe ne transmet
jamais ses droits ; les snapshots et rendus ne doivent pas contourner ces droits.
Les Documents Texte et Données gardent leurs contrats ; les Process restent des ressources
BPMN de `app.process`, sans nouveau type documentaire exécutable pour les héberger.

Contrat de sauvegarde : validation du format, contrôle de révision/ETag adapté au propriétaire,
conflit explicite, état modifié conservé après erreur et fermeture/navigation gérées sans perte
silencieuse. Pas de promesse de collaboration temps réel ni d'édition sans perte pour tout format.
Un export avec perte est explicite et ne remplace pas le projet natif sans choix utilisateur.
Le lecteur conserve un mode lecture seule lorsque l'édition ou l'autorisation manque.

Les aperçus, miniatures, caches et rendus sont des dérivés distincts du projet source.
Le port `core.preview.PreviewConverter` offre déjà une base de conversion temporaire, avec
conservation de la source et nettoyage testé ; il ne fournit ni éditeur ni type documentaire.
Les parseurs, codecs et moteurs lourds requièrent limites de taille/CPU/mémoire/temps et,
selon leur confiance, un worker isolé. Le réseau et les secrets ne sont accessibles que par
les capacités accordées ; un asset ou projet ne peut pas charger librement scripts ou plugins.
Le frontend respecte les mêmes garanties d'isolation que les autres contributions du bundle.

Après désactivation ou retrait, conserver type/version du contenu, métadonnées, révisions
et assets. Prévoir une fiche générique et un téléchargement/export des originaux encore
autorisés sans exécuter le plugin absent ; signaler l'éditeur indisponible et permettre sa
réinstallation compatible. Ne pas convertir silencieusement un projet en Texte/Données.

## Contrats proposés

| Objet | Rôle |
|---|---|
| Plugin | Code public unique et stable, identité de l'éditeur. Une seule fiche par code, quel que soit le nombre de versions installées ou de contributions. |
| Version publiée | SemVer et empreinte immuables, libellé, description et liste des contributions de cette version. |
| Installation | Présence locale vérifiée, verdict de compatibilité, version désirée et décision de forçage dev éventuelle. |
| Génération | Version de Galaris, ensemble cohérent de releases backend/frontend, schémas retenus et référence à la dernière génération fonctionnelle. |
| Permissions / événement | Grants locaux de version précise ; décisions et erreurs administratives expurgées. |
| Catalogue / store | Métadonnées distantes et interface locale, sans autorité d'activation distante. |

Domaine candidat `app.plugin` pour workflow, persistance, RBAC et administration.
Infrastructure core indépendante pour archives, manifests, stockage immuable, boot
et contrats techniques ; composition racine avec les ports des domaines.

### Fiche et capacités du plugin

| Champ du manifeste | Contrat |
|---|---|
| Code | Obligatoire, unique et stable sur toutes les versions. Privilégier un code qualifié par l'éditeur, par exemple `example.studio`. Le registre associe le code à une identité d'éditeur vérifiée et refuse une réattribution silencieuse lors d'un import ou d'un téléchargement. |
| Libellé et description | Obligatoires, avec textes FR/EN. Ils sont fournis par la version du plugin et visibles avant installation. L'interface les rend comme du texte. |
| Version | SemVer du bundle. Le code et la version identifient une publication immuable dont l'empreinte est vérifiée. |
| Capacités | Liste complète des contributions de cette version. Chaque entrée identifie sa famille, son code stable, son libellé et sa version de contrat. La liste accepte plusieurs entrées d'une même famille. |

Un plugin « Studio » peut déclarer deux fournisseurs IA et trois formats de document.
L'interface affiche cinq entrées nommées, regroupées en deux familles. Le manifeste
sert de source à l'aperçu et au catalogue. Lors de l'activation, l'hôte vérifie
que les contributions déclarées correspondent aux enregistrements effectifs. Le choix
d'une version porte sur le bundle entier. Les réglages et usages de chaque contribution
restent configurables dans son domaine.

### Contenu de l'archive et SDK

Une version de plugin se distribue dans un seul ZIP. Le backend, le frontend et les
données fournis partagent le même manifeste, la même signature et le même cycle de vie.
Les Samples du dépôt sont organisés par plugin sous `plugins/sample/`.

Le ZIP contient un manifeste, les contributions déclaratives, les licences et crédits,
les empreintes, la provenance et la signature. Les contributions exécutables ajoutent
un paquet Python préparé (wheel, format à qualifier) ou une référence déclarée à un runtime
isolé, ainsi que les assets frontend précompilés s'il y a lieu. Le manifeste déclare aussi
les compatibilités Galaris/SDK/runtime, les points d'entrée, les permissions demandées,
les dépendances et les politiques de données. Un schéma de configuration ou de contenu
a sa propre version de données.

La composition racine fournit un SDK par famille qui reprend les façades publiques.
Un point d'entrée natif produit les descripteurs et implémentations déclarés dans le
manifeste. Pour un runtime isolé, un adaptateur hôte traduit le même contrat en appels
versionnés et bornés. L'hôte valide les entrées et sorties et applique les permissions
avec le contexte courant. Les opérations du SDK reposent sur des ressources et des
connexions ciblées. L'accès à la base, aux secrets globaux, à la session navigateur et
aux services internes du cœur est hors du contrat du SDK.

Conserver des releases externes sur volume dédié, hors checkout/image, avec staging,
quarantaine, versions par digest et registres desired/effective/last-known-good.
Le frontend n'accède qu'aux artefacts publics, jamais au volume général de données.

## Chargement backend et frontend

- Le backend charge au démarrage les points d'entrée explicitement sélectionnés, depuis
  le répertoire de leur release. Le premier palier utilise les dépendances fournies
  par l'image ou le SDK. Les espaces de noms protègent les contributions du cœur et
  détectent les collisions entre plugins avant l'activation.
- L'hôte enregistre les contributions typées et leurs versions. Les routes spécialisées,
  privilèges et points d'intégration UI rejoignent le SDK à mesure que des familles
  en établissent le besoin. Les données déclaratives passent par les validateurs des domaines.
- Le frontend natif charge les modules précompilés depuis des URL immuables par empreinte,
  via le manifeste de la génération effective. L'hôte fournit les runtimes Vue/Quasar/Pinia/
  Router/i18n. Le chargement et le nettoyage passent par les points d'intégration du SDK.
  Un changement de génération demande aux clients ouverts de recharger. Les appels utilisant
  une contribution périmée reçoivent un état explicite et s'arrêtent.

## Données et schéma

| Politique | Application |
|---|---|
| Référentiel géré par le plugin | Par exemple un profil fournisseur et ses métadonnées. L'hôte traduit les données déclaratives vers un dataset DbAdmin validé par le domaine propriétaire. Réconciliation par clé naturelle, provenance et liste de champs possédés. Une collision avec une donnée locale bloque la contribution. |
| Modèle ou initialisation unique | Par exemple une fiche de Service, un document modèle ou une définition de workflow. Le domaine crée la copie sur demande avec un reçu d'import idempotent. Réimporter ou mettre à jour le plugin préserve les modifications, les suppressions et les droits révoqués localement. |
| Données d'usage | Les Services configurés, les Connexions, les Documents et révisions, et les runs appartiennent à leurs domaines respectifs. Le retrait du plugin conserve leurs identités, références et historique. |

Le premier palier contribue des données aux domaines existants via ces contrats. Les
tables propres aux plugins sont un lot ultérieur. DbAdmin reste l'autorité sur `public`.
Séparer `schema_installed` de `runtime_enabled` et conserver dans la cible de schéma une
description validée des objets après retrait du code. Qualifier une représentation de
schéma indépendante du runtime avant d'autoriser ces tables. Les transformations suivent
les contrats DbAdmin d'expansion et de contraction, avec vérification de périmètre,
idempotence et postconditions. Une action indispensable en cours doit pouvoir reprendre
avant le retrait de son code. Les jeux de données permanents et réconciliations du
plugin cessent de s'appliquer après désactivation. Les domaines conservent leurs références.
[Contrat DbAdmin](../../docs/fr/dev/dbadmin.md)

## Cycle de vie et confiance

### Compatibilité des versions et forçage en développement

À l'import, à l'activation et après un changement de version de Galaris, vérifier
la plage de versions hôte, les versions des contrats SDK et des contributions requises,
les dépendances résolues, la plateforme/runtime et les versions de données lisibles.
Le rapport nomme la contrainte, la valeur observée et la valeur attendue. Vérifier la
compatibilité dans les deux sens avant une mise à jour avec retour automatique.
Une génération fixe les versions et empreintes exactes résolues. Les identifiants
stables préservent les références lorsque les versions changent. Deux archives différentes
portant la même identité et la même version sont traitées comme une collision.

En développement, `APP_ENV=dev` au sens exact des settings, un administrateur peut
**forcer l'installation inactive** si la version de Galaris est hors plage ou si la
branche courante n'a pas de version de release exploitable. Il voit le diagnostic et
confirme la dérogation pour le digest du bundle et la révision hôte courante. L'activation
reste une action distincte. Elle peut utiliser cette dérogation dans ce même contexte dev
après avoir passé les validations de contrats et les sondes requises. Changer de branche,
de révision ou d'environnement impose une nouvelle évaluation. En production, les
commandes et API refusent le forçage et le bootstrap ignore toute dérogation dev lors
de la sélection d'une génération. Une version devenue compatible suit alors le chemin normal.

Les contrôles d'intégrité, de signature, de révocation, de structure, de namespaces,
de dépendances, de versions de contrat/runtime reconnues, de données et de permissions
restent obligatoires pour tout bundle, y compris forcé. Journaliser qui a forcé quel
écart, pour quel digest et quelle révision. Un échec de chargement conserve le diagnostic
et permet de revenir à une génération validée pour l'hôte courant.

### Installation et activation

1. Importer dans un espace de staging non exécutable. Vérifier les limites du ZIP, les
   chemins, types de fichiers, empreintes, signature, compatibilité et collisions. Publier
   les fichiers immuables et l'état installé inactif de façon idempotente. Toute exécution
   de code de qualification intervient après validation de l'origine, dans l'environnement prévu.
2. Sérialiser les modifications de génération. Revalider dépendances, permissions et
   artefacts, prévisualiser les effets en base, puis préparer la génération candidate.
   Les changements destructifs passent par une opération distincte.
3. Charger le candidat au redémarrage, converger via DbAdmin avant d'ouvrir l'API et
   vérifier les sondes. Promouvoir ensemble les contributions backend/frontend. Sur
   échec, restaurer la dernière génération compatible avec l'hôte et les données.
   En cas de transformation incompatible, conserver un diagnostic administrable et
   suivre le plan de reprise. Le retour du code précédent ne restaure pas la base.

Une mise à jour installe la nouvelle release à côté de l'ancienne. Avant d'appliquer,
afficher les contributions ajoutées, retirées ou incompatibles, les effets sur les
configurations et données existantes et les permissions élargies. Conserver l'ancienne
release tant qu'une génération de retour arrière la référence. Les mises à jour qui
changent un format de données prévoient une conversion explicite et une preuve de lecture
par la génération de retour, ou une procédure de reprise documentée.

Le mode natif initial exige la confiance accordée au cœur de Galaris. Une signature
atteste la provenance et l'intégrité. L'exécution tierce à droits limités exige un
runtime isolé, une identité dédiée, des limites réseau et de ressources, des accès
ciblés et, pour du code web, une interface isolée sur une autre origine. Toute mise à
jour qui élargit le périmètre demande un accord local.

### Désactivation, désinstallation et purge

1. **Prévisualiser l'impact.** Lister les dépendants installés ou actifs, Services,
   protocoles, Connexions, Documents, travaux en cours et données retenues. Une
   dépendance active bloque l'opération jusqu'à un choix explicite sur le dépendant.
   Identifier les appels ou travaux à terminer, annuler ou refuser selon le contrat de leur domaine.
2. **Désactiver.** Refuser les nouvelles admissions, arrêter les écouteurs et callbacks
   du plugin et rendre les références concernées indisponibles dans la nouvelle génération.
   Conserver l'archive installée pour réactivation. Les Services et Connexions restent
   éditables dans leurs limites, les opérations des autres protocoles restent utilisables,
   et les Documents conservent leurs originaux et leur historique.
3. **Désinstaller.** Retirer les points d'entrée, les contributions de catalogue, les
   routes, les assets publiés et les droits d'exécution propres au plugin. Conserver
   un reçu de retrait, les identités des contributions, les réglages et données utilisateurs,
   ainsi que la description des objets SQL retenus. Libérer les artefacts devenus
   inaccessibles aux générations effectives, désirées ou de retour arrière et aux
   opérations en cours. La conservation temporaire pour reprise est visible. Une
   réinstallation compatible peut rattacher les références et la configuration existantes.
   Elle requiert de nouvelles décisions d'activation et de permissions du plugin.
4. **Purger.** Présenter précisément les données et objets appartenant au plugin,
   vérifier les références encore actives, puis demander confirmation et sauvegarde
   selon la politique applicable. Tracer la purge et sa reprise via les contrats des
   domaines et, pour le schéma public, DbAdmin.

Le retrait s'effectue par génération avec un reçu durable. Après interruption, rejouer
la phase inachevée. Le nettoyage physique attend la confirmation de la génération et
reste réessayable indépendamment. Le processus d'installation et de retrait conserve
un diagnostic expurgé avec étape, cause, code d'échec et release concernée.

## Interface d'administration des plugins

Prévoir une page **Administration → Plugins** dès le lot d'installation locale.
La liste présente une ligne par code avec le libellé, le code, la version effective
ou la version installée si le plugin est inactif, son état et un résumé des capacités.
La recherche couvre le code et le libellé. Les filtres portent sur l'état et la famille
de contribution. La fiche détaille la description, l'éditeur et l'origine, ainsi que
chaque capacité nommée. Elle indique la version consultée et distingue les versions
installées, désirée et effective lorsqu'elles diffèrent. La prévisualisation d'une mise
à jour montre les capacités ajoutées, retirées ou modifiées.

- **Importer une archive.** Afficher la fiche issue du manifeste, le signataire, la
  compatibilité, les dépendances et les permissions demandées avant installation.
  Présenter le contrôle de forçage uniquement dans le cas dev autorisé.
- **Gérer les versions et les opérations.** Proposer l'activation, la mise à jour,
  le retour arrière, la désactivation et la désinstallation selon les droits et l'état.
  Afficher l'impact avant retrait et donner à la purge son propre parcours. Suivre
  l'opération après fermeture de la page ou redémarrage.
- **Diagnostiquer.** Exposer le journal des opérations avec étape, état et erreurs
  expurgées. Afficher le blocage précis pour une dépendance, une incompatibilité ou
  une sonde en échec. La lecture de l'inventaire local reste disponible sans catalogue
  distant.

Appliquer les privilèges côté API et dans l'interface pour la lecture, l'installation,
l'approbation des permissions, l'activation, le retour arrière, la désinstallation et
la purge. Lors de la réalisation, utiliser la référence graphique et les composants
standards de Galaris, puis vérifier le parcours au clavier et en petit viewport.

## Reprise du chantier

**Livré.** Diagnostics expurgés et persistants dans `/data/update-diagnostics`, Sample
Partage de fichiers avec protocole et fiche de Service dans le même ZIP et comparaison de PNG dans Dessin. Le catalogue HTTPS administré
vérifie l'index signé, son expiration, les empreintes et les révocations à l'acquisition.

**Vérifié.** 65 tests backend ciblés et 59 scénarios Chromium sont passés. Le
[parcours sur la pile assemblée](../../e2e/specs/plugin-release-lifecycle.spec.mjs)
confirme qu'un échec de chargement backend de la v2 laisse la v1 utilisable, que les
révisions se téléchargent après retrait et que l'éditeur fonctionne après réinstallation.
Le typage strict, les traductions et la documentation FR/EN ont été vérifiés.

**Premier chantier à la reprise.** Étendre ce parcours à un vrai redémarrage avec
PostgreSQL et les fichiers conservés, puis à une v2 incompatible uniquement côté navigateur
et à deux processus backend. Vérifier le chargement de la version sélectionnée, la
lisibilité des révisions et le retrait des contributions sur tous les processus.

Restent ouverts l'isolation du code tiers et la supervision de ses dépendances, les
migrations de schéma propres aux plugins, les autres façades installables et la publication
officielle de l'App Store.

## Lots et réception

Le registre actuel installe les manifests `1` et `2`. Le second peut publier dans
l'instance standard un format binaire, un profil IA, un convertisseur, des modèles
JSON et un protocole de partage de fichiers. Le Sample Partage de fichiers combine
ce protocole et la fiche du Service dans le même ZIP. Le catalogue local réutilise l'import signé.
Le code s'exécute avec la confiance
de l'hôte et ses services externes sont provisionnés par l'opérateur.
Voir le [contrat livré](../../docs/fr/dev/plugin-bundles.md) pour les limites.

| Lot | Preuve de sortie |
|---|---|
| 0 — Décisions et contrats SDK | Manifeste, identités, versions, permissions, portée DbAdmin et retour arrière. Contrats distincts pour fiche de Service, capacité, protocole et adaptateur, ainsi que pour lecteur, éditeur et format documentaire. Modèle de menace de l'installation et de l'exécution de code. |
| 2 — Backend natif | Fournisseur IA externe opérationnel après activation. Échec d'import ou de sonde avec retour sur une génération compatible et diagnostic conservé. |
| 3 — Protocoles de Service | Premier protocole installable sur la capacité File Share. Étendre le contrat aux autres domaines et qualifier la contribution d'une capacité exposant ses propres fonctions. |
| 4 — Frontend, retrait et qualification | Format externe utilisable sans rebuild du frontend, contenu récupérable après retrait. Une fiche de plugin composite affiche toutes ses contributions et les différences entre versions. Parcours d'administration complet, dont refus RBAC, retour arrière, désinstallation, réinstallation et purge séparée. |
| 5 — Mode isolé | Tester le refus des accès hors périmètre, la protection du cœur et l'arrêt complet après désactivation. |
| 6 — Schéma propre aux plugins | Objets SQL conservés après retrait du code, reprise d'une action interrompue, retour arrière compatible et suppression uniquement par la purge prévue. |
| 7 — App Store | Catalogue HTTPS administré, index signé et téléchargement vérifié disponibles dans Plugins. Restent la chaîne de publication, l'état de fraîcheur dans l'IHM et la politique des révocations de versions déjà installées. |

Le TCK associe au digest du bundle les preuves d'intégrité, reproductibilité,
compatibilité, RBAC, parité FR/EN et reprise du cycle de vie. Les scénarios de réception
qualifient les garanties métier.

- **Services et protocoles.** Réimporter une fiche en préservant les réglages locaux et
  les droits. Ajouter un protocole qui réutilise un paramètre d'un autre protocole.
  Tester deux Connexions, dont un refus pour un autre agent, et la déduplication d'un
  événement entrant. Retirer le plugin, enregistrer une modification du Service avec un
  ancien client et vérifier la conservation de la configuration et le fonctionnement du
  protocole restant. Réinstaller une version compatible et réutiliser la même Connexion.
- **Fournisseurs et stockage.** Vérifier résolution du modèle, accès à la Connexion et
  remontée d'erreurs expurgée. Qualifier isolation de deux Connexions de stockage et
  copie entre fournisseurs.
- **Lecteurs et formats.** Vérifier la préservation de la source lors d'un aperçu,
  les conflits et refus de sauvegarde, puis la récupération des originaux et révisions
  après retrait de l'éditeur. Pour un format multifichier, qualifier un cycle complet avec
  assets et une sauvegarde interrompue.
- **Versions et retrait.** Refuser les incompatibilités structurelles, même en dev.
  Tester le forçage hors plage, le changement de branche et le passage à un environnement
  appliquant les protections de production. Qualifier le retrait avec dépendants, appels
  en vol ou redémarrage interrompu, puis la reprise et le nettoyage des artefacts.
- **Interface de gestion.** Ouvrir la fiche d'un seul plugin qui contient deux
  fournisseurs IA et trois formats de document, retrouver chaque contribution par son
  libellé et comparer deux versions du même code. Vérifier les refus serveur pour
  les opérations réservées et la reprise du suivi après rechargement.

Employer uniquement des ressources synthétiques et exercer le parcours dans l'application
assemblée, y compris permissions, clavier, petit viewport et dépendance indisponible.
Cartographie du dépôt déterministe ; release externe avec son propre rapport et inventaire runtime.

Arbitrages avant implémentation : autorités de signature, format exact des paquets,
source d'identité de la révision hôte hors checkout, partage des runtimes frontend,
superviseur borné, délai de rétention des artefacts et politique de sauvegarde/purge.
La représentation du schéma après retrait et les migrations de configurations intégrées
relèvent de leurs lots respectifs.
Pour les formats spécialisés : registre et migration des formats, identité des assets,
snapshot multifichier, choix de lecteur/éditeur, récupération sans plugin, licences des
codecs et répartition frontend/worker/service externe. La collaboration temps réel et les
formats couverts seront qualifiés séparément, sans prérequis implicite pour tout plugin.
Retirer les lots réalisés vers décisions, SDK, guides et tests.

## App Store — catalogue administré et publication officielle

Le client du catalogue administré est configuré par URL et par clé publique. Il vérifie
la signature et l'expiration de l'index, conserve le dernier numéro accepté et applique
les révocations cumulatives aux acquisitions. Voir le [contrat de publication actuel](../../docs/fr/dev/plugin-bundles.md).

Une première version peut être un **catalogue officiel administré**. Dans la page
Plugins, un onglet **Catalogue** réutilise la fiche de plugin et ses capacités,
avec recherche par famille et affichage des versions, de l'éditeur et de la compatibilité.
L'administrateur sélectionne une version. Galaris télécharge l'archive vérifiée et
l'ouvre dans le parcours d'installation local. Les permissions et l'activation
restent décidées sur l'instance.

L'architecture à qualifier comprend un pipeline de publication, un index signé et un
stockage d'archives immuables adressées par empreinte. Le pipeline valide le manifeste,
le droit de publier sous ce code, la provenance et les preuves de qualification requises.
L'index publie les fiches par version, le digest, les dépendances, les contraintes de
compatibilité et les avis de retrait ou de révocation. Le client vérifie l'index et
l'archive, et conserve un cache local du dernier index validé. Si cet index expire,
la consultation indique son ancienneté et les nouvelles acquisitions attendent une
validation à jour. Les imports locaux et le suivi des plugins installés restent accessibles.

Avant ouverture aux éditeurs tiers, définir les autorités de signature et la rotation
des clés, la délégation par espace de noms, le traitement d'une révocation d'une
version déjà installée, ainsi que les conditions d'acceptation du code et de son
isolation. Évaluer [The Update Framework (TUF)](https://theupdateframework.github.io/specification/latest/)
pour les métadonnées signées, leur expiration et la résistance au rejeu d'un ancien index.
Qualifier ensuite les catalogues privés ou fédérés, avec la même identité de plugin
et le même installateur.
