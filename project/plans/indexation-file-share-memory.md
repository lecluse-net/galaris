# Catalogue de fichiers par agent, indexation Memory et entretien Dream

Statut : `partial` — proposition du 29 septembre 2026, précisée le 1er octobre 2026.

Socle implémenté : préférence par Tool ; catalogue privé par agent, connexion, empreinte
de configuration et runtime ; observations de la façade publique ; fiches Memory
`file`/`directory` éditables dans Memory et recherche lexicale immédiate ; notes via un port contrôlé ; relations
directes établies par les listes non récursives ; suppressions explicites et rejet des
réponses antérieures ; revalidation de connexion et d'accès source à la lecture/recherche.
Le renommage prouvé dans le même binding conserve l'identité et les notes ; une copie ou
une réapparition après suppression crée une nouvelle identité. Une panne d'indexation
n'annule pas l'opération externe réussie (`indexing_status=failed`).

Implémentés également : parcours périodique par pages avec frontière/curseur durables,
budgets, reprise/backoff et annulation ; réconciliation des listes directes complètes ;
vérification périodique des URI connues ; journal durable de réparation sans rejouer les
mutations externes ; enrichissement versionné via Dream et ses options de médias ;
suivi agent/racine, progression, couverture partielle et erreurs dans Memory.
Une acquisition explicite d'une ressource admissible enrichit la même fiche catalogue,
sans créer une seconde fiche `image_description` ni redemander cette version à Dream.

La première validation globale du 2 octobre a rencontré des échecs MCP puis un blocage
dans le fixture `synthetic_mcp`. Le fixture réinitialise désormais le drapeau global d'arrêt
SSE entre serveurs ; un test couvre explicitement le démarrage après un arrêt précédent,
en HTTP et SSE. Les contrôles globaux interrompus ne valent pas qualification de publication :
seul le rapport complet d'un snapshot inchangé peut la prouver.

La qualification synthétique du 1er octobre couvre 1 000, 10 000 et 100 000 entrées.
Recherche avec contrôle source synthétique, p50/p95 : 30,87/45,07 ms, 67,35/72,86 ms et
496,17/536,50 ms. Écriture de référence sans observation : 0,08/0,12 ms ; avec observation
et journal durable : 54,13/61,63 ms. Médiane et p95 par rang supérieur sur 10 recherches
et 20 écritures par mode. Ces mesures n'incluent aucun réseau provider réel,
aucune inférence ni qualification sémantique. Les cibles proposées de 200 ms de recherche
et 50 ms d'observation n'étaient pas atteintes. Le statut reste `partial` pour les capacités
avancées et la qualification des installations réelles décrites ci-dessous ; les six lots fonctionnels
de parcours, réconciliation, réparation, Dream, suivi et mesure sont présents.

Nouvelle mesure du 2 octobre, après `ANALYZE` sur chaque volume : recherche p50/p95
44,13/327,95 ms à 1 000 entrées, 62,41/71,60 ms à 10 000, 180,75/192,04 ms à 100 000 ;
observation indexée 23,80/31,55 ms, référence sans observation 0,08/0,15 ms. Le premier
appel à froid explique le maximum à 1 000 entrées ; il reste au-dessus de 200 ms.
Même corpus, mêmes 10 recherches et 20 écritures : la qualification avec statistiques
fraîches a d'abord révélé un plan défavorable à 5 711,74 ms au p95, recalculant le binding
100 000 fois. Les plans finaux montrent des calculs par connexion, des candidats lexicaux
matérialisés et l'utilisation des index GIN `pg_trgm` sur titre et texte pour le `ILIKE`.
Un index partiel des tombstones borne leur contrôle dans l'observation. Le test conserve
les plans sous `artifacts/` et vérifie le nombre d'exécutions des contrôles de paramètres.
Les objectifs sont atteints à 100 000 entrées dans cette qualification synthétique ; ils
ne constituent pas une garantie de latence réseau, d'inférence ou de démarrage à froid.

Qualification des adapters : un vrai échange SSH/SFTP sur un serveur éphémère couvre la
fiche Console, les changements externes et l'isolation ; le client Nextcloud réel face à
un pair WebDAV synthétique couvre 503 entrées, pagination, reprise 503 et révocation 403.
Ce dernier scénario ne vaut pas qualification d'une installation Nextcloud réelle ; celle-ci
exige une connexion et un répertoire de test dédiés.

Périmètre resserré le 1er octobre 2026 : Console et ressources des Tools portant la capacité
`file_share`, hors Mail. Les autres accès de la façade ne sont pas des sources de ce catalogue.

## 1. Résultat attendu et périmètre de l'analyse

Chaque agent dispose d'un catalogue interrogeable des ressources auxquelles il a accès via
`app.file_share` : fichiers, répertoires et collections virtuelles. Il peut retrouver une ressource
par nom, chemin, métadonnées, texte extrait, résumé ou notes personnelles ; consulter son URI
canonique ; et continuer à la manipuler avec les outils génériques existants.

Le point d'entrée est exclusivement `app.file_share` : il énumère les schémas accessibles
à l'agent, décide lesquels peuvent être indexés, puis délègue aux providers. Aucun scanner,
worker Memory ou mécanisme Dream ne sélectionne directement un service externe. Nextcloud
est un exemple de provider, pas un lot de réalisation ni une branche du pipeline.

L'admission est positive : Console active ou transport de fichiers d'un Tool connecté doté
de `file_share`, hors Mail. La façade fournit directement les périmètres admissibles au
scanner ; celui-ci n'énumère pas tous les schémas pour appliquer sa propre liste d'exclusions.

| Source | Décision de périmètre |
|---|---|
| `console://` | Incluse, dans le home SSH autorisé. |
| Tools `file_share` tels que Nextcloud, AFFiNE et Grav | Inclus selon leurs capacités effectives, sous leur code de Tool. |
| `memory://` | Exclue : l'index ne devient jamais sa propre source. |
| `document://`, y compris Datasets et PJ | Exclus : les documents sont déjà des objets Memory et leur indexation existe. |
| `galaris://`, toutes collections | Exclu : aucune indexation ou fédération métier, documentation ou skills dans ce plan. |
| `https://` et `http://` | Exclus : les informations Web retenues passent par les documents et les conversations. |
| Mail, quel que soit le code du Tool | Différé : un futur chantier portera sur les mails eux-mêmes, pas seulement leurs PJ ; aucune acquisition ici. |
| Transports Messenger, quel que soit le code du Tool | Exclus : Dream produit déjà les souvenirs conversationnels ; aucun inventaire exhaustif des messages ou PJ ici. |

Un Tool peut porter à la fois `file_share` et Messenger. L'admission s'applique au transport
effectivement résolu pour la ressource : les fichiers Nextcloud sont admissibles, ses PJ Talk
ne le sont pas. Le schéma ou le seul booléen `has_file_share` ne suffit donc pas à admettre
toutes les URI de ce Tool. Ces gardes valent pour scans, observations et enrichissements.

Pour les schémas admissibles et énumérables, un parcours récursif régulier inventorie tous
les répertoires et fichiers autorisés, avec pagination et reprise. Par défaut, cette
découverte conserve dans Memory l'arborescence, les noms, les URI source et les métadonnées,
sans lecture documentaire ni appel LLM. Chaque fichier possède ainsi sa fiche avant d'être
analysé. Les observations des opérations ordinaires complètent cet inventaire.

Un mécanisme Dream distinct construit ensuite le résumé dans l'item Memory correspondant
au document et à sa version source. Une modification invalide les enrichissements anciens
et programme leur actualisation ; une suppression confirmée retire les résultats courants.
Le schéma `memory://` est exclu avant tout parcours, observation d'indexation ou création de
job : les fiches produites ne peuvent jamais redevenir les sources de leur propre indexation.

Les contrats et tests du dépôt font autorité. Ce plan porte le catalogue de ressources,
son parcours périodique et ses enrichissements ; aucune couverture d'installation n'est
mesurée par cette revue documentaire.

Garanties proposées :

- un fichier observé devient trouvable lexicalement avant le succès annoncé de l'indexation ;
- les opérations fichier restent utilisables sans modèle LLM ou vectoriel ;
- deux agents ne partagent ni leurs notes ni leur catalogue privé par simple égalité d'URI ;
- une génération de résumé, de texte extrait ou d'embeddings est attachée à une version source ;
- une analyse ancienne ne peut réintroduire un fichier supprimé ou remplacer une analyse récente ;
- une absence dans une page, une recherche ou une réponse partielle ne provoque aucune purge ;
- les droits actuels restent prioritaires sur les caches, les notes et les embeddings ;
- le statut de couverture distingue explicitement connu, parcouru complètement et analysé ;
- un format non analysable peut rester connu par son nom et sa place dans l'arborescence ;
- un schéma exclu ne produit ni scan, ni fiche de fichier, ni job d'enrichissement ;
- un fichier inchangé conserve sa fiche et son résumé sans nouvel appel modèle.

« Tous les services » signifie une intégration commune pour tout provider compatible avec la
façade. Cela ne signifie pas qu'un provider dépourvu de liste permette soudain un inventaire
exhaustif. Ces limites deviennent visibles et les adapters sont complétés là où leur API le permet.

## 2. Manques à couvrir et socle à réutiliser

Réutiliser les contrats de [file-share](../../back/app/file_share/resource_contracts.py),
la [structure Memory](../decisions/0106-document-structure-memory.md),
le [rappel documentaire](../decisions/0108-memory-document-retrieval.md),
la [préparation documentaire commune](../decisions/0151-resumable-document-analysis.md)
et la [cohérence Nextcloud](../decisions/0147-nextcloud-file-consistency.md).
Leurs lecteurs, droits, pagination, index et checkpoints ne sont pas à réimplémenter.

| Périmètre | Travail restant pour le catalogue |
|---|---|
| Ressources externes | Catalogue durable agent/binding, observation commune, notes privées, version source et retrait prouvé. |
| Console | Découverte et curseurs exhaustifs ; une liste bornée ne prouve pas un inventaire complet. |
| AFFiNE et Grav | Adapter liste/stat/version et découverte selon les capacités réelles ; aucune complétude inventée en l'absence d'API. |
| Sources exclues ou différées | Aucun catalogue, scan, observation ou enrichissement nouveau ; préserver leurs mécanismes Memory/Dream existants. |
| Audio et vidéo | Raccorder analyses et transcriptions à la fiche de la source ; qualifier les résumés visuels séparément de la piste audio. |

Le parcours périodique file-share doit fonctionner pendant les Tasks actives ; Dream,
préemptible par Task/Voice, reste chargé des résumés et enrichissements. Une ressource
connue par son titre n'est pas une ressource analysée. Les descriptions d'images existantes
n'attestent pas la fraîcheur ni les droits actuels d'une source externe. Le nettoyage du
stockage natif ne prouve pas la disparition d'une source distante.

Les expériences de pertinence, de provenance fine et d'utilité aval restent dans le
[plan Memory](amelioration-globale-memoire.md). La matrice de réception du présent plan
porte les nouvelles garanties du catalogue, pas une nouvelle implémentation de ces socles.

### 2.1 Vérification du socle au 1er octobre 2026

Cette inspection porte sur le code et les tests présents dans le dépôt ; elle n'est ni un
test d'exécution ni une mesure de couverture des comptes connectés.

| Surface vérifiée | Contrat actuel et conséquence pour le lot 0 |
|---|---|
| [`ResourceSchemeDescription`](../../back/app/file_share/resource_contracts.py) | Expose schéma, libellé, exemple, capacités et caractère natif ; ne porte ni politique d'indexation, ni racines, ni identité de binding. Ces champs sont à introduire avant le scanner. |
| [`list_schemes`](../../back/app/file_share/resource_service.py) | Décrit les schémas natifs et les codes des Tools connectés. Les capacités annoncées sont assemblées selon le service ; elles ne constituent pas une certification d'inventaire complet du transport. |
| Console dans [`resource_list`](../../back/app/file_share/resource_service.py) | Liste bornée, sans curseur accepté. Une liste tronquée ne permet pas de poursuivre l'inventaire ; conserver une couverture partielle, sans retrait d'absents. Messenger reste exclu. |
| [`Nextcloud.resource_list_page`](../../back/bridge/nextcloud/file_share.py) | Curseur lié au compte, à la racine et au mode récursif ; empreinte des enfants pour détecter un changement de dossier. Ce socle permet la reprise, sans garantir un snapshot cohérent de l'arbre entier. |
| [`MailAttachmentTransport`](../../back/bridge/mail/file_transport.py) | Le transport actuel ne couvre que les PJ d'un message connu. Mail est différé, même s'il porte `file_share` ; le futur chantier doit traiter les mails eux-mêmes. |
| [`AffineResourceTransport`](../../back/app/file_share/bridges.py) et [`GravFileClient`](../../back/bridge/grav/client.py) | AFFiNE possède un adaptateur de métadonnées pour un blob explicite, sans liste générale ; Grav ne fournit pas les protocoles `resource_info`/`resource_list`. Commencer par les URI connues lorsque leur admission est démontrée. |
| [`MemoryItem`](../../back/app/memory/models.py) | La contrainte des natures autorise seulement `memory`, `document`, `attachment`, `folder`. Ajouter `file`/`directory` exige d'adapter aussi les contraintes de propriété et de gestion de source, pas seulement les DTO. |
| [`upsert_source_managed_item`](../../back/app/memory/service.py) | L'identité gérée repose sur le couple kind/ref ; le helper crée un item sans paramètre de nature. Un nouveau port de projection doit porter explicitement la nature et l'identité agent/binding, en préservant les consommateurs existants. |

Le lot 0 commence par ces écarts. Aucune racine récursive ne doit être déduite de
`example`, du seul code du Tool ou de la présence de la capacité `list`.

## 3. Architecture proposée

Répartir les responsabilités dans les modules existants :

| Domaine | Responsabilité proposée |
|---|---|
| `app.file_share` | Énumération et admissibilité des schémas, racines autorisées, identité/binding des providers, catalogue par agent, observations, parcours régulier et preuve de couverture, versions et état des sources, service d'indexation et validation d'accès source |
| `app.memory` | Nœuds `file`/`directory`, notes et textes recherchables, liens, FTS/embeddings, admission et oubli des projections |
| `app.dream` | Résumés et enrichissements des fiches découvertes, réparations opportunistes avec budgets et checkpoints ; utilise exclusivement la façade file-share pour accéder aux sources |
| Domaines propriétaires | Source canonique et ACL des documents, PJ, conversations, Tasks, Goals, Process, skills, documentation |
| Bridges | Traduction des métadonnées, listes, versions, événements et accès propres au service |
| Frontend Memory/Dream | Recherche, arbre, notes, progression et diagnostic des périmètres |

Un **service d'indexation interne à `app.file_share`** suffit au départ. Un nouveau module ou
service Docker ne se justifie que par une isolation/concurrence réellement nécessaire et
mesurée. Les grosses analyses et le rendu restent isolés dans leurs workers existants ou un
processus borné ; ils ne tournent jamais dans la transaction d'une liste de fichiers.

Contrats publics envisagés, noms à stabiliser pendant le lot initial :

- `ResourceObservation` : contexte serveur, binding, URI, version, type d'observation et preuve ;
- `ResourceScanPage` : périmètre, génération de scan, entrées, curseur, complétude et erreurs ;
- `ResourceEnrichment` : type d'analyse, contenu/référence dérivée, version source et provenance ;
- côté Memory : upsert de projection, publication d'enrichissement, édition de notes et retrait ;
- `ResourceAccessVerifier` : port de validation d'accès, enregistré au bootstrap pour que
  Memory ne doive pas importer le service interne `file_share` et créer un cycle.

Réutiliser `ResourceDescriptor` et les DTO de recherche ; ne pas laisser circuler les modèles
ORM internes entre les domaines. Les workers autonomes ouvrent des sessions courtes ; les
services appelés dans un contexte utilisent sa session. Aucun appel réseau sous verrou long.

### 3.1 Admissibilité des schémas et prévention des boucles

La préférence utilise le paramètre standard **`tools.fileindexing`** : `excluded` (défaut),
`known_uris` ou `recursive`. La valeur globale du Tool est héritée par ses connexions ; une
surcharge locale peut la remplacer, sauf si la valeur globale est imposée. Ce même mécanisme
configure Console, y compris embarquée, sans rendre sa définition SSH éditable. La préférence
ne modifie aucune permission source et les synchronisations conservent les valeurs administrées.

Le provider annonce les modes supportés ; le serveur refuse un mode non supporté. Mail et
les Tools sans `file_share` restent exclus. Console accepte actuellement les URI connues ;
le parcours automatique attend sa pagination reprenable. Nextcloud annonce le parcours,
AFFiNE et Grav les URI connues. Les transports Messenger d'un Tool mixte restent exclus.
Ce réglage prépare l'admission du futur catalogue : il ne constitue pas un scanner ni une
preuve que les fichiers ont déjà été indexés.

Étendre la description publique des schémas de `file_share` par une politique d'indexation
calculée côté serveur à partir du provider, de ses capacités et du binding autorisé. Les
noms des champs restent à stabiliser ; trois modes doivent être distingués :

| Mode | Comportement |
|---|---|
| Exclu | Aucun parcours ni observation générant une fiche ou un job ; motif explicite |
| URI connues | Observation de sources autorisées déjà rencontrées ; aucun inventaire complet annoncé |
| Parcours récursif | Racines autorisées énumérables, pages et curseurs, parcours régulier reprenable |

Les exclusions et le report de Mail définis en section 1 s'appliquent avant tout scan,
hook d'observation, matérialisation générant une fiche ou job d'enrichissement. Aucun port
de fédération des documents ou métiers natifs n'est ajouté dans ce chantier. Les dérivés
internes et alias conservent leur origine et ne deviennent pas de nouvelles sources indexables.

Le scanner consomme cette politique depuis `file_share` ; il ne contient aucune liste de
services externes admissibles. Les nouveaux providers rejoignent le même pipeline selon
leurs capacités effectives. La faculté de lister un schéma et celle de parser le contenu
d'un fichier sont distinctes : une erreur d'extraction n'empêche pas sa fiche structurelle.

La récursion suit uniquement les relations de collection validées par `file_share`, sans
suivre les URI citées dans le contenu, les fiches Memory ou les résumés. Dédupliquer les
collections visitées par binding et identité, détecter les cycles et curseurs sans progrès,
et persister la frontière. Une borne atteinte conserve un parcours partiel reprenable ;
elle ne rend jamais un inventaire tronqué complet.

## 4. Modèle de données et identité

### 4.1 Catalogue par agent

Entités logiques proposées ; le lot 0 vérifie lesquelles nécessitent réellement une table :

| Entité | Données et contraintes essentielles |
|---|---|
| Binding de provider | Agent, connexion/Tool si applicable, namespace ou compte logique, génération de configuration, capacités d'indexation ; identité serveur sans secret |
| Entrée du catalogue | Binding, identité opaque provider lorsqu'elle existe, URI courante, nature, parent explicite, nom/MIME/taille/date, version source, état de présence, timestamps d'observation, lien vers Memory canonique/projeté |
| Périmètre et run de scan | Racine, profondeur/filtres, début/fin, curseur/frontière persistée, génération, preuve de couverture complète, compteurs/erreurs et reprise |
| Observation/job durable | Identité d'événement/opération, entrée ou périmètre, version/génération, payload minimal, statut, lease, retry/backoff et cause de l'effet |
| Enrichissement | Entrée/version source, type, version de pipeline, langue/modèle/question si utile, texte/locator/artefact dérivé, provenance, couverture et statut |
| Annotation personnelle | Agent + entrée, texte HTML révisé, auteur humain ou agent et tâche éventuelle ; modification optimiste, distincte des dérivés générés |

Toutes les clés primaires sont des UUID ou entiers ; les colonnes suffixées `_id` sont de vraies
FK. Les identifiants distants s'appellent `external_id`, `external_key` ou équivalent.
Prévoir les index de binding/état, parent, URI/clé stable, version et jobs disponibles ; éviter
un snapshot massif en JSONB comme seul index. Aucun chemin hôte ni credential n'est conservé.

Unicité : agent + binding/génération + identité source. Une URI seule ne suffit pas : la même
`nextcloud://Reports/report.pdf` peut désigner deux comptes différents ; une modification de
connexion peut faire désigner un autre compte par la même URI. Une génération retirée n'est
jamais silencieusement réaffectée au nouveau compte. Les natives possèdent aussi leur binding
de domaine/runtime, notamment la console SSH.

Quand le provider possède une identité stable, le déplacement conserve la fiche et ses notes.
Sinon : alias uniquement après un move réellement réussi et observé ; un renommage découvert
de l'extérieur reste suppression/création si aucune preuve fiable n'établit son identité.
Un checksum égal n'est pas une preuve de même objet ni une autorisation de fusion.
La réutilisation d'un chemin après suppression ne réattache pas automatiquement les anciennes
notes : distinguer la nouvelle incarnation, sauf preuve de restauration de la même identité.

### 4.2 Projection dans Memory

Ajouter `node_kind=file` et `node_kind=directory`, généralement `memory_type=working`,
gérés par source, privés et appartenant à l'agent. Conserver `folder` pour le classement
documentaire. Une collection virtuelle peut être un `directory` avec une sous-nature explicite
`collection` ; ne pas fabriquer un arbre en découpant des locators opaques.

Une projection doit avoir une identité source incluant agent/binding, compatible avec l'unicité
globale actuelle de `(managed_source_kind, managed_source_ref)`. Le service
`upsert_source_managed_item` et les contraintes actuelles doivent être adaptés explicitement
pour produire ces natures ; passer simplement un nouveau libellé au helper existant ne suffit pas.

Les ressources déjà canoniques dans Memory restent `document`/`attachment`/`memory`, hors
de ce catalogue. Aucune fiche ni annotation supplémentaire n'est créée pour les documents,
projections métier ou corpus documentaire. Les notes par agent concernent uniquement les
sources admissibles ; les résultats sont regroupés par ressource/binding.

La fiche sépare : métadonnées autoritatives, notes personnelles, texte extrait et analyses
générées. Une synchronisation de nom/date/taille ne réécrit jamais les notes. Le titre et le
contenu sont éditables avec l'éditeur Memory existant ; chaque champ modifié manuellement
est préservé lors des observations suivantes. L'identité, l'URI et les références source
restent contrôlées par le catalogue. Les fiches restent privées et protégées de l'oubli
ordinaire ; leur édition ne modifie pas le fichier source. Les fiches existantes deviennent
éditables par une réconciliation idempotente, sans annuler un verrouillage ultérieur choisi
par leur propriétaire.

Le payload éditorial de la fiche/annotation suit le profil HTML Memory. Les octets source
restent dans le provider ; le texte extrait, les locators et les dérivés sont des projections
bornées. Un Dataset garde son JSON canonique. Il ne faut pas recopier les binaires dans Memory.

Relations proposées : contenance parent/enfant, ressource analysée/artefact dérivé,
référence au document/Task/Process/skill canonique et notes associées. Réutiliser les relations
existantes lorsque leur sens convient ; sinon nommer et documenter une nouvelle relation.
Chaque projection possède ses liens et ne supprime jamais les liens manuels d'une autre politique.

## 5. Mise à jour lors de l'utilisation des tools

Les observations se prennent **dans la façade publique**, pas uniquement dans les wrappers MCP.
Les appels Python, usages par Process, générateurs média et matérialisations spécialisées doivent
donc bénéficier de la même indexation. Vérifier aussi les chemins qui utilisent directement
un transport, les callbacks et les destinations de livraison. Une livraison Messenger
n'admet pas sa destination ; seule sa source fichier admissible peut être observée.

| Opération | Mise à jour à produire |
|---|---|
| `file_schemes` | Réconcilier les bindings/capacités et la politique d'indexation ; programmer les racines des schémas admissibles ; aucun fichier inventé par la seule présence du schéma |
| `file_list` | Upsert des entrées vues et des relations explicites ; noter couverture/cursor ; retraits limités aux enfants d'une liste complète et cohérente |
| `file_info` | Actualiser les métadonnées et la version ; distinguer inférence et existence réellement vérifiée |
| `file_search` | Observer les hits et leur version ; un non-hit ne prouve jamais une absence |
| `file_read` / matérialisation | Observer l'accès et la version réellement lue ; ne pas remplacer un texte extrait complet par le fragment paginé retourné |
| create/write/append/edit | Observer la ressource résultante ; invalider les dérivés de l'ancienne version ; programmer uniquement les étapes devenues nécessaires |
| copy | Observer destination et provenance de copie ; conserver l'identité de la source et garder les notes privées séparées |
| move | Alias ou identité déplacée selon preuve ; actualiser parents/URI ; traiter les descendants si un déplacement de collection est réellement supporté |
| delete | Retirer immédiatement la projection active après succès source ; cascader la portée uniquement si la suppression de collection est supportée et confirmée |
| échec d'accès/existence | Classer not-found, denied, timeout, source-unavailable, version-conflict ; aucune suppression sur une panne ou un refus ambigu |

Le premier upsert de catalogue, sa projection lexicale et l'intention d'indexation sont petits
et sans LLM. L'index vectoriel est asynchrone ; la réponse indique son état réel. Coalescer les
observations identiques : plusieurs lectures inchangées n'ajoutent ni révision textuelle ni
recalcul d'embeddings. La date `last_seen` et les usages ne contaminent pas l'empreinte sémantique.
Chaque hook applique d'abord la politique du schéma : lire une fiche `memory://` ne produit
aucune observation d'indexation, même si cette lecture traverse la façade générique.

Les mutations des domaines canoniques exclus n'alimentent pas ce catalogue.
Pour les mutations fichier admissibles, il n'existe pas de transaction atomique entre le provider et SQL :
préparer un reçu d'opération/reprise avant l'effet lorsque nécessaire, puis enregistrer le
résultat confirmé. Si l'effet distant réussit et la mise à jour locale échoue, rendre le
succès fichier et l'état d'indexation incomplet distinctement, sans inciter à rejouer une
création/copie déjà réalisée. Le reçu est repris ou son périmètre réconcilié. L'impossibilité
d'établir l'effet reste explicitement incertaine ; un retry n'est pas un nouvel effet aveugle.

Une API qui promet « analyse enregistrée en Memory » ne rend son succès qu'après persistance
du résultat acquis ; son checkpoint permet de reprendre l'écriture sans réappeler le modèle.
Ce contrat préserve la garantie actuelle de `image_read`.

## 6. Versions, enrichissements et miniatures

### 6.1 Version source

Séparer trois versions : ressource externe, contenu projeté Memory et pipeline d'analyse.
Préférer révision/ETag fort/checksum fourni ; sinon date + taille donne seulement un signal
faible, à compléter par digest lors d'une lecture autorisée. Pour une analyse longue, capturer
la version avant lecture, lire les octets correspondants de manière conditionnelle lorsque
possible, puis revalider avant publication. Sans garantie provider, signaler l'incertitude et
ne pas publier la génération comme vérifiée contre une version forte.

Une modification connue invalide immédiatement texte/résumé/miniature/embeddings anciens
pour les recherches courantes ; les notes personnelles restent conservées et marquées à
revoir. Les anciennes générations peuvent être retenues en historique selon politique,
mais ne sont pas présentées comme description actuelle. Une description générée à partir
d'un fichier doit porter l'empreinte de **ses octets**, pas seulement celle de son résumé.

Chaque passage périodique compare la version observée à celle de la fiche et à celle du
dernier résumé. Un fichier inchangé ne déclenche aucun nouvel appel LLM. Un changement de
nom ou de parent met à jour l'arborescence ; avec une identité stable et une version de
contenu inchangée, il préserve le résumé. Une version de contenu différente rend le résumé
obsolète et remet la fiche dans les candidats Dream. Si le provider ne distingue pas
métadonnées et contenu, un digest autorisé permet cette distinction avant réanalyse.

Pour les providers sans version forte, date et taille ne suffisent pas à garantir la
détection de toutes les modifications. Prévoir une revérification périodique bornée des
octets avec digest ; publier le délai et les limites de cette vérification. Avant d'écrire
un résumé acquis, comparer encore binding, version et droits : un ancien résultat ne peut
pas écraser le résumé d'une version plus récente.

### 6.2 Catalogue des enrichissements

| Type | Source et traitement | Provenance et limites |
|---|---|---|
| Nom/métadonnées | Provider, sans modèle | Champs réellement observés, date/force de vérification |
| Texte brut/code/HTML/Markdown/JSON | Extraction locale bornée ; HTML générique lu inerte | Lignes/blocs/champs et version ; pas d'exécution de code/script |
| PDF et bureautique | Réutiliser la préparation commune `core.document` et les façades d'analyse documentaire | Pages, paragraphes, feuilles/cellules ; OCR séparé pour pages image |
| Image | Analyse spécialisée existante ; OCR si requis | Modèle, instruction, langue et digest ; distinction description/OCR |
| Audio | Transcription, puis résumé optionnel ; analyse sonore distincte | Timestamps et limites ; distinguer musique, bruit et parole |
| Vidéo | Piste audio, scènes/frames si spécialiste autorisé | Timestamps et modalités couvertes ; audio seul annoncé explicitement |
| Miniature | Renderer/rendu déterministe et cache | Artefact dérivé versionné ; sa création ne prouve aucune analyse sémantique |
| Résumé | Réduction du texte/des analyses disponibles | Parties couvertes, méthode, langue/modèle ; jamais substitut silencieux au texte intégral |
| Note personnelle | Humain ou agent, révision attendue | Auteur/tâche/date et visibilité privée ; jamais écrasée par Dream |
| Synthèse de répertoire | Agrégat déterministe puis résumé optionnel | Enfants autorisés et version du périmètre ; complétude explicite |

Étendre l'acquisition actuelle à une publication structurée d'enrichissement, commune aux
tools et à Dream. Une question ciblée à `image_read` ne remplace pas automatiquement le
résumé général : conserver le type/l'instruction de l'analyse et composer la fiche selon
une règle déterministe. Une réponse identique au même traitement/version est idempotente.

Demander une miniature crée/actualise la fiche et son état de dérivé. Si le renderer a
réellement extrait un texte utile, ce texte peut être publié avec sa provenance ; sinon
aucun contenu sémantique n'est inventé. Un résumé se fonde sur une extraction existante
ou programme celle qui manque. Réutiliser les dérivés valides au lieu de retélécharger et
réanalyser le même fichier à chaque consultation.

Bornes nécessaires : octets, pages/cellules/frames/durée, expansion d'archives, temps de
conversion, taille des textes et nombre de passages. Un plafond produit `partial` ou
`unsupported` et sa cause, jamais une prétendue indexation complète. Ne pas ouvrir les
archives ni parcourir les liens/symlinks de façon implicite. Contenus non fiables traités
comme données, y compris les instructions incluses dans un fichier.

## 7. Recherche rapide et intégration Memory

Utiliser le moteur Memory canonique pour noms/métadonnées projetés, notes, textes extraits
et analyses. Conserver une consultation hiérarchique paginée sur le catalogue pour les
grands répertoires ; ne pas charger tout l'arbre pour chercher un fichier.

Comportement proposé :

- `file_search("memory://", ...)` retrouve aussi les nouveaux nœuds autorisés ;
- `file_search("nextcloud://Root/", ...)` et autres providers cherchent l'index limité à
  l'agent, au binding, à la racine et à la profondeur demandés ;
- en couverture incomplète, proposer un mode hybride avec recherche provider disponible,
  budgets et provenance ; ne pas rendre une liste vide comme preuve d'absence globale ;
- séparer `name` (noms/chemins), `text` (texte et notes) et `semantic` (hybride canonique)
  pour les providers externes, et préserver la recherche Memory toujours hybride actuelle ;
- une option de fraîcheur explicite permet de demander la vérification/parcours source,
  sans effectuer un crawl exhaustif caché pour toute recherche interactive ;
- nom exact, URI et identité exacte restent résolus déterministement ; noms de fichiers
  courts, extensions, accents et noms multilingues demandent une couverture lexicale adaptée.

Les résultats exposent la fiche `memory://...` et **l'URI source à utiliser**, la nature,
le binding courant, la version, le passage/locator, la dernière vérification et les étapes
d'indexation disponibles. Ne pas confondre l'URI de lecture des notes avec celle du binaire.
Une recherche dans une collection documentaire continue à renvoyer `document://...` lorsque
le nœud réel est un document. Regrouper les hits issus de plusieurs enrichissements du même
fichier sans perdre leurs passages complémentaires.

Étendre le manifeste vectoriel avec une représentation des passages extraits lorsque
nécessaire. Les nombres de lignes/pages/timestamps et l'empreinte source doivent rester
retrouvables ; utiliser les jobs et l'admission du moteur existant. Sans modèle vectoriel,
recherche lexicale immédiate et dégradation explicite. Le modèle configuré dans le profil
reste l'unique modèle autorisé ; aucun modèle de repli silencieux.

Le rappel automatique doit garder ses budgets et sa sélectivité. Un catalogue de 100 000
fichiers ne devient pas 100 000 faits à injecter au prompt. Les métadonnées seules servent
d'abord à la découverte ; n'injecter que les fiches/passages pertinents. Un voisinage de
répertoire n'est pas une preuve de pertinence du contenu. Les scopes contact/conversation
actuels restent applicables aux analyses issues de ces contextes.

## 8. Droits, révocation et partage

L'accès se compose de propriétaire agent, binding actuel/connexion active, restrictions
du contexte et ACL/existence source. Une annotation Memory ne crée jamais un accès au
fichier. Toutes les surfaces doivent appliquer cette règle : recherche, browse, lecture,
graphe, passages, miniatures, compteur, export et brief des drivers.

Pour les domaines internes, réévaluer les ACL par leur port SQL courant. Pour les services
externes, la liste autorisée connue n'est pas une ACL actuelle. Prévoir une validation
provider des candidats avant de rendre leur contenu, idéalement groupée. Un `resource_info`
qui ne vérifie pas l'existence n'est pas suffisant. Sans preuve actuelle pour un contenu
sensible, omettre le résultat et signaler la dégradation ; ne pas attendre Dream pour
masquer un binding désactivé ou un refus observé.

**Arbitrage de performance explicite** : vérifier les ACL distantes à chaque résultat peut
coûter un aller-retour réseau. Une fraîcheur distante garantie ne peut être simultanément
présumée sans événement fiable ou validation. Les sources internes ont une admission locale
rapide ; les providers distants doivent mesurer leur validation groupée. Un éventuel cache
d'autorisation TTL constitue un mode à fraîcheur bornée, à décider et documenter séparément,
jamais présenté comme une révocation distante instantanée.

La validation finale compare également la version/génération du candidat, comme l'admission
Memory actuelle : un résultat calculé avant suppression/reconfiguration est rejeté.
Un accès partagé documentaire ne doit pas devenir une permission durable stockée dans un
companion privé : sa dépendance au document/PJ et au manifeste actif reste revalidée.
Un graphe ne traverse pas de répertoire interdit pour joindre deux nœuds visibles.
Les sous-branches interdites ne contaminent ni résumé du parent ni compteur visible.

Notes privées par défaut, même si deux agents lisent le même fichier. Les descriptions
documentaires communes restent compatibles avec leur contrat actuel ; ne pas les privatiser
ou les multiplier rétroactivement sans décision explicite. Un partage futur de notes exige
une action distincte et ne partage pas les credentials ni le fichier. Les ACL documentaires
existantes continuent à gouverner leur source canonique.

Les URI contenant tokens, credentials ou signatures éphémères ne sont pas persistées telles
quelles dans les mémoires, jobs ou logs. Les liens de téléchargement techniques ne remplacent
pas l'URI canonique du provider. HTTPS reste exclu ; conserver les protections SSRF et
matérialisation bornée existantes pour les opérations de la façade.

## 9. Détection des disparitions et purge

États de présence à distinguer : présent, absence suspectée, supprimé confirmé, accès refusé,
source indisponible. Les états de traitement (texte prêt, analyse en attente/erreur, etc.) sont
séparés ; une panne d'extracteur ne transforme jamais la source en fichier supprimé.

Preuves recevables de suppression : succès de `file_delete`, événement provider fiable,
not-found réellement autoritatif, ou absence dans un inventaire **complet et cohérent** du
périmètre exact. Un provider qui masque un refus en 404 ne donne pas nécessairement une
preuve de suppression ; classer ce cas selon son contrat.

Pour une réconciliation, marquer les entrées vues dans une génération et ne retirer les
absentes qu'après la clôture complète. Suivre aussi les observations concurrentes : une
création/lecture positive postérieure au début du scan ne peut être effacée par une ancienne
page. Verrou/génération/ordre d'événements et revalidation ciblée évitent cette course.
La date d'arrivée d'une réponse ne prouve pas la fraîcheur de son observation : une lecture
commencée avant un delete peut revenir après lui. Capturer un jeton de génération au début
de l'opération, puis vérifier ce jeton à l'application ; une ancienne réponse positive ne
réactive pas une entrée tombstonée. Un événement de restauration fiable peut créer ou
réactiver l'incarnation appropriée, sans supprimer cette garde générale.

Un parcours multi-page terminé n'est pas nécessairement un snapshot cohérent : si l'arbre
change pendant le scan, utiliser token de snapshot/delta lorsque disponible ; sinon détecter
les changements et confirmer les absences par une vérification ciblée ou un second passage.
La pagination Nextcloud actuelle détecte certains changements de dossier ; elle ne constitue
pas à elle seule un snapshot atomique de tout le share.

Interdictions : purge depuis une recherche filtrée, une page partielle, un scan annulé,
une racine différente, un listing sans permission, ou une réponse de cache périmée.
Le retrait d'un périmètre d'indexation/connexion retire ses projections, pas les fichiers
distants. Pour des racines qui se recouvrent, conserver l'entrée encore justifiée par un
autre périmètre valide et ne retirer que les liens appartenant au scope abandonné.

Purge proposée en deux temps :

1. exclusion immédiate des résultats/briefs/graphes, invalidation des dérivés et annulation
   logique des jobs anciens ; les tombstones bloquent les événements et checkpoints tardifs ;
2. nettoyage durable des chunks/manifeste, extraits, résumés, miniatures, payloads de jobs et
   références dérivées, avec retries et preuves ; rétention bornée des tombstones.

La fiche automatique supprimée disparaît de l'index actif. Les annotations rédigées suivent
une politique distincte : proposition de corbeille privée hors rappel, puis effacement au
délai configuré, avec effacement immédiat sur demande. Cela évite une perte silencieuse de
notes lors d'un incident ou d'un déplacement mal identifié. Ne pas confondre cette corbeille
avec une conservation active des fichiers supprimés. Les PJ documentaires retenues pour
d'anciennes révisions suivent leur contrat existant.

Un oubli explicite d'une fiche/annotation établit une suppression d'acquisition au niveau
agent/source/version ou périmètre choisi : Dream ne la recrée pas au prochain scan sans
réactivation autorisée. La purge ne supprime jamais le fichier distant. Une source utilisée
par plusieurs mémoires ne conduit pas à supprimer les autres sources ni un fait rédigé
indépendamment ; invalider la dépendance concernée et rendre la provenance historique claire.

## 10. Parcours régulier file-share et enrichissement Dream

Le parcours structurel régulier appartient au service d'indexation `file_share`. Un worker
durable traite les périmètres arrivés à échéance par pages bornées, via la façade commune.
Il relit les schémas et leur politique, reprend les frontières interrompues, actualise les
fiches et les relations Memory, puis programme le prochain passage. Son avancement régulier
ne dépend pas uniquement des périodes de repos Dream. La cadence reste configurable et
mesurée par agent/binding, sans lancer un crawl complet dans une requête interactive.

Dream traite séparément les fiches sans résumé courant, en accédant à leurs sources via
`file_share`. Le résumé enrichit le même item Memory ; il ne crée pas une mémoire indépendante
à chaque tour. Les mécanismes de réparation opportuniste réutilisent le service du scanner.

Séparer les opérations et leurs responsables :

| Opération proposée | Responsable | Sujet borné et travail |
|---|---|---|
| `file_share.discover` | Worker régulier ; réparation Dream optionnelle | Une page/un dossier autorisé ; actualiser métadonnées/relations et persister la frontière, sans LLM |
| `file_share.reconcile` | Worker régulier ; réparation Dream optionnelle | Une fin de périmètre ou un lot d'absences suspectées ; valider puis retirer de façon idempotente, sans LLM |
| `memory.resource_extract` | Dream | Une entrée/version ; acquérir texte/OCR/transcription selon capacités, limites et options |
| `memory.resource_enrich` | Dream | Une entrée/version/type d'analyse ; écrire le résumé dans la fiche correspondante, avec provenance et couverture |

Les mécanismes existants PJ peuvent déléguer au service commun par étapes, en conservant
leurs options et la garantie de remplissage sans écraser une description rédigée entre-temps.
Ne pas faire tourner deux analyses automatiques concurrentes pour la même source/version.

Racines d'indexation : celles annoncées et autorisées par `file_share` pour les schémas
admissibles. Un schéma en mode URI connues ne produit aucun parcours récursif. Supporter
inclusions/exclusions, profondeur, types, plafond de volume et calendrier par agent/binding.
Le parcours par défaut couvre toutes les branches autorisées des racines admissibles ; une
restriction ou un plafond réduit la couverture annoncée. La découverte d'une collection
autorisée ne permet pas d'explorer d'autres comptes ou rooms.

Le contrat `DreamMechanism` traite un sujet par tour. Utiliser des pages avec checkpoint,
curseurs et frontières durables ; ne pas lancer un crawl complet dans `prepare`. Les
identités de reçus intègrent agent/binding, run de découverte ou version source, type/pipeline
et configuration utile. Un reçu succès n'empêche pas une nouvelle version ni une réparation
explicitement demandée ; un checkpoint déjà acquis ne provoque pas un nouvel appel LLM.

Les mécanismes Dream respectent la préemption Task/Voice actuelle et leur rotation ; le
worker structurel possède ses quotas et son équité entre agents/bindings. Backoff par source
pour les pannes/quota, afin qu'un share malade ne bloque pas les autres. Prévoir statuts
unsupported, excluded, too-large et partial sans boucle de retry permanente. Nombre d'octets,
coût, durée et résultats utiles sont comptabilisés.

Un lancement humain « Indexer maintenant » doit produire un run durable, progressif et
annulable. S'il doit progresser malgré des Tasks actives, cela relève d'une commande
prioritaire distincte du repos opportuniste Dream, exécutée par le même service avec quotas ;
ne pas modifier silencieusement la politique globale de Dream. Le lot 0 choisit la
représentation de ce run et l'usage de `app.process` si le contrat d'exécution longue s'applique.

## 11. Modifications hors des tools et complétude par provider

Trois voies complémentaires : observations immédiates, événements/deltas fiables du provider
lorsqu'ils existent, scans périodiques de réparation. Un hook Galaris ne détecte pas un fichier
modifié par un PC tant qu'aucun événement ou parcours ne l'observe. Il faut publier la latence
de fraîcheur réelle par provider au lieu de promettre du temps réel universel.

| Provider | Ajouts à cadrer pour un inventaire complet |
|---|---|
| Console SSH | Pagination/reprise même pour un répertoire >500 enfants ; symlinks hors home exclus ; version et scans ; watcher optionnel seulement si mécanisme exploitable |
| Nextcloud | Réutiliser pagination/ETags ; vérifier identité stable exposable, changements/deltas/notifications disponibles ; compléter identité/version/grouped stat ; réconciliation des listes concurrentes |
| AFFiNE | Contrat de discovery des workspaces/blobs autorisés et identités/versions ; si indisponible, couverture explicite des seules URI connues |
| Grav | Adapter énumération pages/médias, stat/version et racines ; aucun support fictif de delete/move |
| Nouveau bridge | Tests contractuels obligatoires de découverte, version, validation d'accès, complétude et limitation ; observation seule si son API n'expose pas ces garanties |

Ajouter des capacités d'indexation optionnelles : discover roots, listing paginé complet,
version forte, identité stable, vérification d'accès groupée, delta/watch. Les schémas annoncent
leurs capacités effectives ; une seule capacité `list` ne signifie pas `complete_inventory`.

## 12. API, MCP et parcours utilisateur

Conserver les opérations génériques `file_*`. Ajouter seulement les opérations manquantes :
édition/lecture de notes et lancement/statut/annulation d'indexation, avec rôles clairs entre
tool File Sharing et tool Memory. Les noms exacts restent à fixer dans le contrat ; éviter
des outils séparés par provider. Les miniatures passent par un endpoint autorisé ou une
référence de dérivé, pas par une URL de cache permanente contournant les ACL.

Parcours proposé dans Memory : filtre agent, catégories Fichiers/Répertoires, recherche
globale ou par service/racine, arbre chargé par pages, fiche avec lien source, notes personnelles,
analyses et miniatures, dates/versions et couverture. Ouvrir une source ne nécessite pas de
reconstituer un chemin depuis le titre. Des états vides distinguent aucun fichier connu,
source non parcourue, source indisponible et aucun résultat correspondant.

Dans Dream : choisir agent/services/racines, découverte seule ou enrichissements autorisés,
budget, progression, erreurs, reprise/annulation ; voir ce qui reste à découvrir, extraire,
analyser ou purger. Permissions humaines par périmètre de gestion agent, sans exposer les
fichiers d'un agent non géré. Réutiliser les contrôles RBAC existants quand ils suffisent.

Les vues ouvertes reçoivent des invalidations sans contenu ; elles rejettent les anciennes
réponses après changement d'agent, connexion, révision ou révocation. Conserver i18n FR/EN,
palette Solaire, fermeture des modales par backdrop et pagination 50 avec exactement
`[10, 20, 50, 100, 500]`. La taille 500 est acceptée côté API.

## 13. Performance, budgets et observabilité

Ne pas annoncer un gain avant baseline et comparaison dans les mêmes conditions. Corpus
synthétiques proposés : 1 000, 10 000 et 100 000 entrées ; répertoire >500 enfants ; fichiers
longs avec information en fin ; plusieurs agents/comptes et connexions au même schéma.

Mesurer séparément :

- p50/p95 de liste, search nom/texte/sémantique, première fiche et première miniature ;
- coût du contrôle ACL/source et latence totale vue par l'agent ;
- surcoût p95 d'une observation sur les opérations `file_*` ;
- requêtes DB/provider, octets téléchargés, mémoire et saturation des queues ;
- temps de découverte complète et délai observation → lexical → vectoriel ;
- délai d'une suppression confirmée → retrait, puis → nettoyage physique ;
- couverture métadonnées/texte/analyses, taux de versions obsolètes et erreurs/retries ;
- recalculs, coûts LLM/embeddings, hit rate des dérivés et amplification d'écritures ;
- qualité Recall@k/nDCG, résultats inutiles et utile recherche → ouverture du bon fichier.

Portes absolues : aucune fuite inter-agent/compte/contact, aucune purge sans preuve, aucun
recalcul d'analyse pour une version/pipeline inchangés déjà acquis, aucun appel LLM pendant
un upsert/liste/réconciliation de métadonnées. Objectifs proposés à étalonner au lot 0 :
surcoût observation p95 ≤50 ms et recherche locale nom/texte p95 ≤200 ms sur 100 000 entrées,
hors attente d'une validation distante. Publier aussi le total incluant cette validation ;
ces valeurs sont des cibles, pas des performances constatées.

Réutiliser la journalisation structurée et les diagnostics Memory/Dream ; traces avec IDs,
versions, compteurs et types d'erreur, sans contenu sensible ni URI secrète. Rétention bornée
des runs/observations/dérivés, coalescence, débit par provider, limites par agent et priorité
au travail interactif. Une éventuelle optimisation ANN/pg_trgm/cache vient seulement après
mesure et vérification de fraîcheur/isolement ; PostgreSQL/pgvector existants restent le socle.

## 14. Consommateurs et validations à préserver

Inventaire des surfaces à adapter :

- schémas/contraintes Memory et tous les `Literal` de `node_kind`, discriminants du graphe,
  projections publiques et types frontend ;
- création et oubli source-managed, révisions, annotations, stockage/dérivés et nettoyage ;
- search/browse/lecture/graphes, admission, filtres de scopes et budgets de contexte ;
- `file_list/info/read/search`, opérations de mutation, transferts et matérialisation ;
- profils de contexte communs à tous les drivers, plugin mémoire Hermès et prompts/skills
  runtime qui distinguent la fiche Memory de l'URI source ;
- image/audio/multimedia, document/PJ/miniatures/Web previews, livraisons Messenger et Process ;
- mutations de connexions/paramètres/ACL et leurs événements ;
- Dream receipts, counts, scheduler, monitoring, extraction PJ et worker vectoriel ;
- index documentaire dédié, pages Memory/Dream et recherche des documents existants ;
- DbAdmin, génération des cartes, contrats et catalogue des tests fonctionnels.

Ne pas dédupliquer deux fichiers par leur texte ou similarité via les règles d'acquisition
ordinaires. L'identité de ressource prime. Ne pas oublier des nœuds `file`/`directory` encore
présents par simple vieillissement ; leur durée de vie suit la source et la politique de
périmètre. Les documents restent éditables et leurs révisions/partages n'ont pas de nouveau
comportement implicite.

Tests d'acceptation à construire ou étendre au niveau de chaque garantie :

Tester aussi les sources exclues et différées : lecture, liste et matérialisation de
Documents, Galaris, HTTPS, Mail et Messenger sans fiche, observation d'indexation ni job.
Pour un Tool mixte Nextcloud fichiers/Talk, vérifier que seuls les fichiers sont admis.
Un code de Tool personnalisé ne contourne ni cette garde ni le report de Mail.

| Garantie | Scénario minimal observable |
|---|---|
| Catalogue immédiat | Lister un share synthétique puis rechercher son fichier via Memory, sans LLM ni attente Dream |
| Politique de schémas | Énumérer ensemble un provider récursif, un provider limité aux URI connues et `memory://` ; seules les racines admissibles sont parcourues |
| Absence de boucle | Lire/rechercher/lister les fiches Memory créées, puis relancer le scan : aucun appel de découverte sur `memory://`, aucune nouvelle fiche dérivée et aucun job récursif |
| Pipeline générique | Deux providers synthétiques aux schémas différents, dont un ajouté après le premier scan, rejoignent le même scanner via `file_share` sans branche par nom de service |
| Arborescence par défaut | Scan récursif d'une racine paginée avec documents non parsables : répertoires, parents et noms retrouvables sans téléchargement documentaire ni appel LLM |
| Régularité | Ajouter un fichier hors des tools, avancer l'échéance du scan avec des Tasks actives : découverte au prochain passage ; le résumé suit séparément la politique Dream |
| Résumé dans la fiche | Une fiche structurelle puis enrichissement Dream : même identité Memory, résumé lié à la bonne version ; un second passage inchangé ne réappelle pas le modèle |
| Changement externe | Modifier les octets hors Galaris : prochain scan ou contrôle de digest invalide le résumé courant, puis Dream actualise la même fiche ; résultat ancien tardif rejeté |
| Récursion bornée | Collection cyclique, alias ou curseur répété : arrêt diagnostiqué sans jobs infinis ; une limite conserve la frontière et une couverture partielle |
| Index réutilisable | Lire et lister plusieurs fois la même version : même identité, mêmes notes, pas de nouvel appel modèle |
| Isolation | Même URI sur deux comptes/agents ; recherche/fiche/graphe/miniature sans fuite croisée |
| Version | Ancien résumé prêt après modification du fichier : rejet ; nouveau texte correctement localisé |
| Notes | Note manuelle puis scan, analyse, rename confirmé et changement MIME : note préservée et liée à la bonne incarnation |
| Purge sûre | >500 entrées, pages vides avec cursor, scan partiel/panne/403/conflit : aucun faux retrait |
| Purge effective | Suppression confirmée puis recherche/browse/brief ; dérivés ensuite nettoyés, ancien checkpoint sans effet |
| Scan concurrent | Création/move/lecture après début du scan : la clôture n'efface pas l'observation récente |
| Bindings | Reconfiguration de connexion vers un autre compte : ancienne génération inéligible avant rebuild |
| ACL | Révocation pendant search/miniature/analyse : admission finale refuse l'ancien résultat ; pas de fuite dans les compteurs |
| Reprise | Interruption/lease expiré/restart/multi-worker et réponse tardive : même effet, pas d'analyse facturée à nouveau si checkpoint disponible |
| Effets distants | Copy réussi puis panne de projection : résultat source explicite, reprise de l'index sans nouvelle copie |
| Extraction | Texte long/PDF scanné/tableau/audio/vidéo : passages et modalités couverts déclarés, fin de fichier retrouvable |
| Repli | Provider vectoriel en panne/changement modèle : lexical disponible, ancienne génération vectorielle inéligible |
| Oubli | Oubli explicite puis scan Dream : pas de recréation silencieuse |
| UX | Recherche → fiche → source → note → réouverture ; erreur/retry, changement agent, petit écran et navigation clavier |

Utiliser des fixtures entièrement synthétiques, remplacer les services externes aux frontières
et exercer les vrais workflows DB. Étendre les tests document/PJ existants plutôt que figer
une nouvelle présentation. Tests de propriétés utiles pour l'ordre d'événements, génération
et convergence ; tests AST pour les ports et dépendances ; quelques E2E pour le parcours assemblé.

## 15. Lots de réalisation et portes de sortie

### 15.1 Livrables vérifiables du lot 0

1. Ajouter au contrat public de schéma une politique typée : `excluded`, `known_uris`,
   `recursive`, avec motif et racines autorisées explicites. Distinguer l'admissibilité
   d'indexation du droit de lire la ressource ; `excluded` ne désactive pas `file_read`.
2. Définir un port optionnel de provider qui annonce ses capacités de découverte réelles.
   Un provider admissible non déclaré reste limité aux URI connues ; une racine récursive
   exige une liste reprenable et un périmètre autorisé. La façade fournit les candidats
   Console/Tools `file_share` hors Mail et applique les exclusions de la section 1 au
   transport résolu, y compris pour un Tool mixte fichiers/Messenger.
3. Stabiliser les DTO de binding, version et preuve d'observation : identité serveur sans
   secret, génération de configuration, version forte/faible/inconnue, existence vérifiée
   ou seulement inférée. La politique générique ne contient aucune branche par code de Tool.
4. Définir le port Memory avec nature explicite et les gardes de publication : incarnation,
   génération et version source. Inventorier les contraintes SQL et consommateurs du helper
   existant avant toute évolution de schéma ; réutiliser les projections documentaires.
5. Tester la politique avec deux providers synthétiques et un provider ajouté via le même
   port : racines autorisées, absence de racine implicite, refus de complétude sur liste
   tronquée sans curseur, exclusions et report de Mail. Les tests d'absence de hooks/jobs suivent au
   lot 1, lorsque ces effets existent réellement.
6. Mesurer la baseline des opérations existantes sur corpus synthétique, puis consigner les
   conditions et résultats. Le catalogue n'existant pas encore, sa latence n'a pas de baseline
   actuelle : la mesurer après le lot 1 avant de comparer une optimisation ultérieure.

Sortie du lot 0 : contrats implémentés et testés, ADR du choix retenu, matrice des capacités
effectives et mesures disponibles avec leurs limites. Une rédaction de DTO ou cette inspection
ne suffit pas à déclarer le lot terminé. Le scan durable, les notes et les résumés ne sont pas
inclus dans sa réception.

### 15.2 Séquence de réalisation

| Lot | Contenu | Preuve de sortie |
|---|---|---|
| 0 — Contrats et baseline | Politique de schémas exposée par `file_share`, exclusion ferme de `memory://`, racines/capacités, identité/binding/version/ACL, complétude et purge ; benchmark courant | Contrats/ADR proposés, scénarios multi-provider et anti-boucle, baseline synthétique et limites explicites |
| 1 — Catalogue et observation | Modèles catalogue + nœuds `file`/`directory`, port Memory, hooks admissibles, relations d'arborescence et lexical immédiat ; retrait explicite et isolation | Deux providers via la même façade → fiches/arbre Memory sans LLM ; lecture de Memory sans réindexation ; update/delete prouvés |
| 2 — Parcours régulier et réconciliation | Runs/racines/échéances issus des schémas, récursion paginée et reprenable, contrôle des versions, clôture cohérente, GC et oubli explicite | Nouveau provider sans branche spécifique ; corpus >500, changements externes, interruptions/cycles/pannes sans faux retrait ; progression hors repos Dream |
| 3 — Résumés Dream et enrichissements communs | Sélection des fiches sans résumé courant, préparation documentaire commune, provenance/version, résumé dans le même item ; notes protégées et checkpoints | Même fiche enrichie puis actualisée après changement ; aucun nouvel appel modèle pour la version inchangée ; résultats tardifs rejetés |
| 4 — Recherche et contexte | Recherche des fichiers admissibles indexée, filtres/passages, briefs et tous drivers ; UI Memory/Dream complète | Parcours assembled et mesures de pertinence/latence/coût ; sources et fiches clairement distinguées |
| 5 — Couverture providers et changements externes | AFFiNE/Grav discovery selon API, événements/deltas fiables, repair des sources sans événements ; adapter SDK contractuel | Matrice de capacités vérifiée par bridge, fraîcheur mesurée et couverture totale uniquement là où démontrée |
| 6 — Qualification et extension | Charge, isolation, rétention, reprise, canari et rollback ; docs FR/EN et compétences runtime | Snapshot validé, résultats mesurés, limites résiduelles et retour arrière prouvé |

Séquence recommandée : construire le pipeline commun depuis les schémas `file_share`, puis
la connaissance structurelle Memory, le parcours périodique et les résumés Dream versionnés.
La réception traverse plusieurs providers par cette même façade ; aucun lot ne cible un
service externe comme point d'entrée. Réutiliser Documents comme référence de non-régression.
Les tests multi-compte, de réutilisation d'URI et d'exclusion de `memory://` font partie du
socle initial. L'intégration d'un provider complète son contrat file-share sans modifier le
scanner générique, Memory ni le mécanisme de résumé.

Pour le démarrage, rattacher uniquement les `image_description` de sources admissibles
à leur fiche agent/source ; les descriptions Web, documentaires et Messenger restent hors catalogue.
préserver révisions et notes, puis dédupliquer l'affichage. Ces anciennes descriptions n'ont
pas de preuve de version source : les marquer historiques/non vérifiées jusqu'à revalidation,
sans inventer leur digest. Les descriptions/PJ natives ne changent pas d'identité. Procéder
par batches avec reprise ; la découverte complète reste un travail asynchrone, pas un crawl
réseau bloquant au démarrage.

Les évolutions de schéma passent par modèles SQLAlchemy et DbAdmin ; action/reconciler
idempotent pour les données existantes, sans migration SQL manuelle. Lors de l'implémentation,
charger `database` et `core-dbadmin` pour cette reprise et les skills frontend/Playwright selon
les surfaces réellement modifiées. Publier les choix structurels acceptés en ADR ; ce plan
ne modifie pas rétroactivement les décisions 0106/0108.

Validation de chaque lot : tests ciblés, `make typecheck`, `make architecture-check` et suites
proportionnées ; `make project-context` quand les modèles/surfaces changent. Mettre à jour les
parcours FR/EN et lancer `make docs-prepare` avant validation/publication. Avant une future
publication, `make validate` sur le snapshot courant et lecture intégrale de son rapport,
`git diff --check` et revue de défaillances. Aucun commit ou déploiement n'est autorisé par la
présente proposition.

Rollback : désactiver discovery/enrichissements et le backend indexé de recherche, revenir
aux opérations provider ; conserver notes/révisions et les ACL renforcées. Ne pas réexposer
les projections révoquées ni restaurer des chunks obsolètes. Une reconstruction réactive
uniquement les générations dont la source, le binding et les droits sont à nouveau validés.

## 16. Principes retenus et arbitrages techniques avant implémentation

Le besoin précisé le 30 septembre 2026 fixe les principes suivants : façade `file_share`
exclusive, discrimination des schémas avec exclusion de `memory://`, parcours récursif
régulier des sources admissibles, arborescence connue par défaut sans LLM, résumé Dream dans
la fiche correspondante et actualisation après changement. Cette section conserve les
arbitrages de conception initiaux ; l'état du runtime et sa qualification sont décrits en
tête de ce plan et dans l'ADR 0155.

Les choix techniques proposés pour les réaliser sont :

1. `file` et `directory` comme nouvelles natures ; `folder` et Documents inchangés.
2. Catalogue, notes et enrichissements par agent/binding pour Console et les Tools
   `file_share` hors Mail ; sources exclues selon la section 1, sans annotation ni fédération
   supplémentaire de leurs objets Memory existants.
3. Métadonnées/arborescence/lexical dès la découverte ou l'observation admissible ; embeddings
   et analyses coûteuses asynchrones, sans contenu inventé pour un fichier non parsable.
4. Parcours et réconciliation périodiques file-share sans LLM ; résumés et enrichissements
   Dream séparés, selon les budgets et options, avec reprise des résultats déjà acquis.
5. Validation source actuelle des résultats sensibles ; possibilité de TTL distincte
   uniquement avec une garantie de fraîcheur bornée assumée.
6. Retrait automatique après preuve ; corbeille bornée pour les notes rédigées, GC des
   dérivés et suppression d'acquisition après oubli explicite.
7. Indexation d'URI connues pour les providers non énumérables, sans annoncer une complétude
   fictive ; adapter la discovery quand leur API la rend possible.
8. Réutilisation PostgreSQL/Memory/Dream et des modules existants ; nouvelle infrastructure
   seulement si les mesures et l'isolation des traitements la justifient.

L'ADR 0155 fixe les racines, les cadences, la rétention technique et les limites du parcours
et de Dream. Restent à qualifier les capacités des providers réels, la validation ACL
groupée, les performances aux volumes cibles et les capacités avancées de ce plan.
