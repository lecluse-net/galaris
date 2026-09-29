# Catalogue de fichiers par agent, indexation Memory et entretien Dream

Statut : `design` — proposition du 29 septembre 2026, non implémentée.

## 1. Résultat attendu et périmètre de l'analyse

Chaque agent dispose d'un catalogue interrogeable des ressources auxquelles il a accès via
`app.file_share` : fichiers, répertoires et collections virtuelles. Il peut retrouver une ressource
par nom, chemin, métadonnées, texte extrait, résumé ou notes personnelles ; consulter son URI
canonique ; et continuer à la manipuler avec les outils génériques existants.

L'observation d'une ressource alimente ce catalogue sans demander au modèle de mémoriser chaque
fichier. Une analyse réussie enrichit sa fiche, une modification invalide ses anciens dérivés,
une suppression confirmée retire ses résultats courants. Dream découvre les ressources encore
inconnues et réconcilie les périmètres autorisés, avec reprise après interruption.

L'analyse porte sur les contrats, implémentations et tests du worktree courant, consultés après
la cartographie générée. Des modifications locales préexistent notamment dans `file_share` et
Nextcloud : la pagination des transports et les opérations conditionnelles avec ETag décrites
ci-dessous tiennent compte de ces modifications. Leur lecture ne démontre ni leur validation
complète, ni leur publication, ni leur déploiement. Aucune base ni installation distante n'a été
inspectée : cet inventaire décrit les mécanismes, pas le nombre de fichiers effectivement indexés.

Garanties proposées :

- un fichier observé devient trouvable lexicalement avant le succès annoncé de l'indexation ;
- les opérations fichier restent utilisables sans modèle LLM ou vectoriel ;
- deux agents ne partagent ni leurs notes ni leur catalogue privé par simple égalité d'URI ;
- une génération de résumé, de texte extrait ou d'embeddings est attachée à une version source ;
- une analyse ancienne ne peut réintroduire un fichier supprimé ou remplacer une analyse récente ;
- une absence dans une page, une recherche ou une réponse partielle ne provoque aucune purge ;
- les droits actuels restent prioritaires sur les caches, les notes et les embeddings ;
- le statut de couverture distingue explicitement connu, parcouru complètement et analysé.

« Tous les services » signifie une intégration commune pour tout provider compatible avec la
façade. Cela ne signifie pas qu'un provider dépourvu de liste permette soudain un inventaire
exhaustif. Ces limites deviennent visibles et les adapters sont complétés là où leur API le permet.

## 2. Ce qui existe réellement

### 2.1 Façade et découverte des ressources

[`resource_contracts.py`](../../back/app/file_share/resource_contracts.py) définit déjà :
`ResourceContext` avec agent/runtime/tâche, `ResourceDescriptor` avec URI, nature collection,
nom, MIME, taille, date, révision, checksum, ETag, capacités et métadonnées ; `ResourceListing`
avec troncature et curseur ; et des résultats de recherche avec provenance, passages et couverture.

[`resource_service.py`](../../back/app/file_share/resource_service.py) fournit les opérations
`resource_info/list/read/create/write/append/edit/copy/move/delete/search`, ainsi que la
matérialisation temporaire bornée. [`mcp.py`](../../back/app/file_share/mcp.py) les expose via
l'unique Tool `file_sharing`. Les schémas externes sont les codes exacts des Tools connectés,
et non les noms génériques des bridges.

Ce socle **ne possède pas de catalogue durable général par agent**, ni de notification commune
persistée à chaque observation. Un descripteur rendu par un tool n'est donc pas automatiquement
un item Memory. Le Working Set mémorise certaines URI, états et reçus de livraison pour les
Tasks ; il n'est ni un inventaire global ni un index de contenu.

### 2.2 Matrice de couverture courante

| Ressources | Déjà indexé ou conservé | Recherche/découverte actuelle | Lacunes pour la cible |
|---|---|---|---|
| `memory://` | Items gouvernés, contenu, sources, révisions, FTS et projection vectorielle | Recherche Memory hybride ; liste sans requête limitée aux nœuds `memory` | Pas un inventaire des fichiers externes ; ne pas indexer récursivement l'index lui-même |
| `document://` HTML | Documents `node_kind=document`, texte intégral indexable et passages HTML localisables | Recherche Memory filtrée documents, ACL vivantes, révisions | Notes personnelles sur une ressource partagée et catalogue fichier commun à ajouter |
| `document://` Dataset | Documents JSON avec les mêmes mécanismes de recherche et de révision | Lecture JSON et indexation du texte de recherche | Provenance fine vers champs/JSON Pointer à formaliser ; ne pas convertir le Dataset en HTML |
| PJ documentaires | Un compagnon `attachment` par PJ, manifeste actif et liens structurels | Nom/métadonnées ; description acquise recherchable et vectorisée lorsqu'elle existe | Pas de texte intégral binaire extrait par défaut ; compagnon commun aux lecteurs autorisés, pas par agent |
| Dossiers de classement documentaire | Nœuds `folder` issus de `DocumentTag`, liens parent/enfant et document/dossier | Visibilité dérivée des documents lisibles ; nœuds vides sans embedding | Ce sont des classements personnels humains, pas les répertoires des providers |
| `console://` | URI de certaines ressources dans les Working Sets | Liste SFTP bornée, lecture, recherche à partir d'une liste ; pas de curseur de reprise | Catalogue, pagination complète, notes, extraction et suivi des modifications hors tools |
| Nextcloud fichier, `<tool.code>://...` | Descriptions privées des images explicitement analysées ; références de travail | WebDAV, métadonnées/ETag, pagination et recherche paginée dans le worktree courant | Pas d'index local général ; recherche texte relit des fichiers et recherche sémantique directe refusée |
| AFFiNE blobs | Références et descriptions d'images acquises | Lecture/copie/upload ; métadonnées d'un blob explicite | Pas de liste générale exposée ; discovery des workspaces/blobs et stabilité de version à qualifier |
| Grav médias | Références et descriptions d'images acquises | Transport de lecture/upload ; capacités génériques limitées | Liste/stat/version/suppression non implémentés par le transport courant ; inventaire des pages/médias à adapter |
| PJ Messenger, `<tool.code>://<room>/<uuid>` | Journal et identité locale durable des PJ ; mémoire conversationnelle distincte | Liste bornée des PJ connues d'une room ; lecture via son bridge | Pas de catalogue fichier par agent, pas de pagination exhaustive de cette liste, pas d'inventaire de tout l'historique distant |
| `mail://attachment/...` | Identités de PJ et références Mail ; mémoire des conversations selon éligibilité | Liste des PJ d'un message connu, lecture bornée ; `resource_info` infère nom/MIME sans prouver l'existence | Découverte de messages via contrat Mail, curseurs de PJ, versions et droits effectifs à adapter |
| HTTPS | Description privée d'une image explicitement analysée, aperçus Web et caches séparés | URI explicite, lecture protégée contre SSRF ; pas d'énumération de site | Index des URL connues, validation fraîcheur/accès, exclusion des URL temporaires ou secrètes ; pas de crawler implicite |
| `galaris://` métiers | Projections Memory de certains domaines, résumés et extractions sélectives | Tasks, rounds texte/voix, Goals, cycles, Process et skills via contrats/ACL de leur domaine | Réutiliser leurs projections ; une exposition fichier n'implique pas une copie intégrale de chaque snapshot dans Memory |
| `galaris://documentation/` | Index dédié `DocumentationPassage` avec FTS et embeddings | Provider documentaire et `documentation_search`, corpus/révisions, droits fonctionnels | Fédération et provenance ; éviter de dupliquer le corpus pour chaque agent |
| Fichiers de skills | Packages administrés et références ; apprentissage Dream distinct | Provider `galaris://skill/` sous autorisation effective | Catalogue par fichier/version à relier au skill existant ; ne pas élargir les droits de gestion |

Nextcloud peut porter à la fois file-share et Messenger : une room connue sélectionne son
transport Messenger. Il faut conserver cette distinction dans l'identité du provider et dans
la découverte, même lorsque les deux ressources portent le même schéma.

Les autres bridges Messenger ne deviennent des providers fichier que lorsqu'ils annoncent la
capacité `FILES`. La couverture suit le registre effectif de bridges et les connexions actives,
pas une liste de schémas codée en dur. Voir
[`file_share_service.py`](../../back/app/file_share/file_share_service.py),
[`bridges.py`](../../back/app/file_share/bridges.py),
[`interface.py`](../../back/app/file_share/interface.py),
[`messenger_transport.py`](../../back/app/file_share/messenger_transport.py),
[`MailAttachmentTransport`](../../back/bridge/mail/file_transport.py).

### 2.3 Mémoire, notes et enrichissements actuels

[`MemoryItem`](../../back/app/memory/models.py) distingue actuellement :

- `memory_type` : `core`, `working`, `episodic`, `semantic`, `procedural`, `social` ;
- `node_kind` : `memory`, `document`, `attachment`, `folder`.

« Fichier » et « répertoire » doivent étendre la **nature du nœud**, plutôt que les six types
cognitifs. `folder` possède déjà une identité et des ACL documentaires spécifiques ; le
réutiliser pour un répertoire Nextcloud modifierait son contrat.

[`document_structure.py`](../../back/app/memory/document_structure.py) synchronise documents,
PJ et classements sans LLM. Il préserve le texte acquis des PJ et les relations manuelles.
Les liens existants sont `references`, `has_attachment`, `uses_attachment`, `in_folder` et
`parent_of`. Une PJ retirée du manifeste reste conservée pour l'historique, mais disparaît des
lectures/recherches courantes. L'oubli définitif du document élimine ses descriptions associées.

[`record_resource_description`](../../back/app/file_share/resource_description.py) délègue
au contrat Memory [`record_attachment_description`](../../back/app/memory/attachment_description.py).
Son seul consommateur d'analyse actuellement trouvé est `image_read` :

- PJ image documentaire : écrit dans son unique compagnon, après revalidation du document ;
- autre URI : crée/actualise une mémoire privée `image_description`, d'identité agent + hash URI ;
- description identique : pas de nouvelle révision ; échec de stockage : échec de l'outil ;
- les descriptions successives alimentent le contenu courant et son historique, sans
  séparation structurée entre question d'analyse, résumé et notes personnelles ;
- pour les ressources externes, ce companion n'a pas de suivi général de version, disparition
  ou révocation de la connexion source. L'ACL Memory privée ne remplace pas cette vérification.

`audio_transcribe` conserve des transcriptions et, selon l'appel, des résumés comme fichiers
via la façade. Cela ne constitue pas un enrichissement systématique de la fiche Memory de la
source. `audio_read` et `video_read` rendent une analyse et tracent l'appel média sans appeler
le port de description Memory. Voir [`audio/mcp.py`](../../back/app/audio/mcp.py),
[`multimedia/service.py`](../../back/app/multimedia/service.py),
[`image/mcp.py`](../../back/app/image/mcp.py).

`memory_summarize` acquiert un résumé de conversation Messenger, et non le résumé d'une
ressource fichier arbitraire. Son nom ne doit pas être pris comme preuve d'un service de
résumé générique déjà disponible. Voir [`memory/mcp.py`](../../back/app/memory/mcp.py).

Les miniatures document/PJ et aperçus Web ont des caches, des limites et des vérifications
d'accès. Leur génération ne verse pas automatiquement un résumé ou une note dans Memory.
Une miniature graphique n'est d'ailleurs pas une description sémantique. Voir
[`document_thumbnail_service.py`](../../back/app/memory/document_thumbnail_service.py).

### 2.4 Indexation et maintenance réutilisables

Le moteur Memory dispose déjà de FTS PostgreSQL, recherche hybride, filtrage des ACL, liens,
passages, admission finale des candidats, diagnostic de couverture et repli lexical.
[`semantic_index.py`](../../back/app/memory/semantic_index.py) gère intentions transactionnelles,
empreintes, fragments, manifeste d'une génération complète et comparaison avant publication.
Le worker [`automation.py`](../../back/app/memory/automation.py) fournit des jobs durables et
des reprises. Il ne faut pas créer un deuxième moteur vectoriel générique pour les fichiers.

Le moteur ne vectorise pas les nœuds `attachment`/`folder` dont le texte est vide. Le titre et
les métadonnées ne signifient donc pas qu'une pièce jointe est sémantiquement analysée.
L'index des descriptions ne remplace pas un futur index du texte intégral extrait d'un PDF.
L'empreinte du texte du compagnon ne constitue pas non plus la version du fichier externe.

La mémoire conserve également des profils d'agents, projections publiques de Topics, contacts,
Goals et leurs 100 derniers cycles, définitions de Process affectées et 20 dernières réussites
par agent/processus, acquisitions manuelles et extractions sélectives de Tasks/conversations.
Ces projections portent leur sens métier ; elles ne démontrent pas un inventaire intégral des
fichiers accessibles. Voir
[`source_projection.py`](../../back/app/memory/source_projection.py),
[`process_projection.py`](../../back/app/memory/process_projection.py),
[`context.py`](../../back/app/memory/context.py).

Dream possède un registre séquentiel, rotation des mécanismes, leases, reçus, checkpoints,
retries, corrélation des coûts et préemption. Il attend l'absence de travail Task/Voice :
**il ne peut donc pas porter seul une garantie de mise à jour immédiate pendant l'utilisation**.
[`registry.py`](../../back/app/dream/registry.py) enregistre notamment réparation structurelle,
maintenance Memory et analyse des PJ documentaires text/document/image/video. Ces quatre
analyses sont désactivées par défaut, traitent les compagnons vides et ne parcourent pas les
shares externes. Le mécanisme vidéo actuel résume sa piste audio, pas l'ensemble des scènes.
L'audio documentaire n'a pas de mécanisme PJ dédié équivalent.

Le nettoyage des ressources Memory existe aussi, mais son inventaire d'orphelins concerne
le stockage natif et protège les ressources des révisions historiques. Il n'observe pas
les suppressions des shares distants. Réutiliser ses protections pour les payloads dérivés,
sans le transformer en preuve de disparition de leur source. Voir
[`storage_reconciliation.py`](../../back/app/memory/storage_reconciliation.py).

Sources : [`attachment_memory.py`](../../back/app/dream/mechanisms/attachment_memory.py),
[`attachment_processing.py`](../../back/app/dream/attachment_processing.py),
[`scheduler.py`](../../back/app/dream/scheduler.py),
[`runtime_settings.py`](../../back/core/params/runtime_settings.py).

### 2.5 Preuves et limites

Les tests existants consultés couvrent les compagnons/PJ, révocations et conservation des
descriptions, descriptions privées externes, liens structurels, indexation complète et
concurrente, miniatures et reprises Dream :
[`test_document_structure.py`](../../back/app/memory/tests/test_document_structure.py),
[`test_document_retrieval.py`](../../back/app/memory/tests/test_document_retrieval.py),
[`test_dream_attachments.py`](../../back/app/memory/tests/test_dream_attachments.py),
[`test_document_thumbnails.py`](../../back/app/memory/tests/test_document_thumbnails.py),
[`test_resource_service.py`](../../back/app/file_share/tests/test_resource_service.py).
Les tests Nextcloud locaux dans `back/bridge/nextcloud/tests/test_file_share.py` ont également
été consultés ; ce fichier n'est pas encore versionné au moment de cette proposition.

Ces tests n'ont pas été exécutés pour cette analyse. Aucun gain de performance ni état de
couverture d'une installation n'est mesuré. Les décisions
[0106](../decisions/0106-document-structure-memory.md) et
[0108](../decisions/0108-memory-document-retrieval.md) restent les contrats à préserver ;
le plan [d'amélioration Memory](amelioration-globale-memoire.md) conserve les expériences de
pertinence, de provenance fine et d'utilité aval. Ce plan couvre le catalogue de ressources.

## 3. Architecture proposée

Répartir les responsabilités dans les modules existants :

| Domaine | Responsabilité proposée |
|---|---|
| `app.file_share` | Identité/binding des providers, catalogue par agent, observations, parcours et preuve de couverture, versions et état des sources, service d'indexation et validation d'accès source |
| `app.memory` | Nœuds `file`/`directory`, notes et textes recherchables, liens, FTS/embeddings, admission et oubli des projections |
| `app.dream` | Découverte et réconciliation opportunistes, analyses enrichies avec budgets et checkpoints ; utilise les mêmes services que les tools |
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
`collection` ; ne pas fabriquer un arbre en découpant les locators opaques de Mail/Messenger.

Une projection doit avoir une identité source incluant agent/binding, compatible avec l'unicité
globale actuelle de `(managed_source_kind, managed_source_ref)`. Le service
`upsert_source_managed_item` et les contraintes actuelles doivent être adaptés explicitement
pour produire ces natures ; passer simplement un nouveau libellé au helper existant ne suffit pas.

Les ressources déjà canoniques dans Memory restent `document`/`attachment`/`memory`. Le
catalogue peut pointer vers ces items sans les renommer ni recopier le même contenu dans un
nœud `file`. Les notes par agent constituent une annotation privée distincte, et les résultats
sont regroupés par ressource/binding. Le même principe s'applique aux projections métier et
au corpus documentaire : fédérer ou lier, plutôt que recopier sans nécessité.

La fiche sépare : métadonnées autoritatives, notes personnelles, texte extrait et analyses
générées. Une synchronisation de nom/date/taille ne réécrit jamais les notes. Un compagnon
géré reste non éditable par `memory_remember` ou une mutation générique : un port d'annotation
contrôlé autorise l'édition des notes sans donner accès aux métadonnées ni au fichier source.

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
un transport, les livraisons Messenger, callbacks et mutations des domaines canoniques.

| Opération | Mise à jour à produire |
|---|---|
| `file_schemes` | Réconcilier les bindings/capacités ; aucun fichier inventé par la seule présence du schéma |
| `file_list` | Upsert des entrées vues et des relations explicites ; noter couverture/cursor ; retraits limités aux enfants d'une liste complète et cohérente |
| `file_info` | Actualiser les métadonnées et la version ; distinguer inférence et existence réellement vérifiée, notamment pour Mail |
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

Pour les ressources internes, écrire projection/intention dans la transaction du propriétaire.
Pour les mutations externes, il n'existe pas de transaction atomique entre le provider et SQL :
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

### 6.2 Catalogue des enrichissements

| Type | Source et traitement | Provenance et limites |
|---|---|---|
| Nom/métadonnées | Provider, sans modèle | Champs réellement observés, date/force de vérification |
| Texte brut/code/HTML/Markdown/JSON | Extraction locale bornée ; HTML générique lu inerte | Lignes/blocs/champs et version ; pas d'exécution de code/script |
| PDF et bureautique | Réutiliser/étendre l'extracteur isolé Dream | Pages, paragraphes, feuilles/cellules ; OCR séparé pour pages image |
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
quelles dans les mémoires, jobs ou logs. Ne pas supprimer arbitrairement une query HTTPS si
elle définit un autre contenu : obtenir une URI stable vérifiée, ou déclarer cette ressource
non indexable durablement. Conserver les protections SSRF et matérialisation bornée existantes.

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

## 10. Dream : découverte, indexation et enrichissement

Ajouter des mécanismes séparés, tous adossés au même service d'indexation :

| Mécanisme proposé | Sujet borné | Travail |
|---|---|---|
| `file_share.discover` | Une page/un dossier d'un binding et d'un périmètre | Découvrir et actualiser métadonnées/relations, persister la frontière ; sans LLM |
| `file_share.reconcile` | Une fin de périmètre ou un lot de candidats absents | Valider les disparitions et exécuter les retraits idempotents ; sans LLM |
| `memory.resource_extract` | Une entrée/version | Acquérir texte/OCR/transcription selon capacités, limites et options |
| `memory.resource_enrich` | Une entrée/version/type d'analyse | Résumé, analyse image/audio/vidéo ou synthèse utile ; LLM seulement si nécessaire |

Les mécanismes existants PJ peuvent déléguer au service commun par étapes, en conservant
leurs options et la garantie de remplissage sans écraser une description rédigée entre-temps.
Ne pas faire tourner deux analyses automatiques concurrentes pour la même source/version.

Racines d'indexation : natives connues, share/chemins autorisés, workspaces/pages lorsque
énumérables, rooms et messages connus accessibles, URL explicitement découvertes. Supporter
inclusions/exclusions, profondeur, types, plafond de volume et calendrier par agent/provider.
La découverte d'une collection autorisée ne permet pas d'explorer d'autres comptes ou rooms.

Le contrat `DreamMechanism` traite un sujet par tour. Utiliser des pages avec checkpoint,
curseurs et frontières durables ; ne pas lancer un crawl complet dans `prepare`. Les
identités de reçus intègrent agent/binding, run de découverte ou version source, type/pipeline
et configuration utile. Un reçu succès n'empêche pas une nouvelle version ni une réparation
explicitement demandée ; un checkpoint déjà acquis ne provoque pas un nouvel appel LLM.

Respecter la préemption Task/Voice actuelle, la rotation entre mécanismes et l'équité entre
agents/providers. Backoff par source pour les pannes/quota, afin qu'un share malade ne bloque
pas tout Dream. Prévoir statuts unsupported, excluded, too-large et partial sans boucle de
retry permanente. Nombre d'octets, coût, durée et résultats utiles sont comptabilisés.

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
| Messenger | Liste paginée des PJ canoniques connues ; événements entrants/sortants/retraits ; découverte des rooms accessibles ; import d'historique distant seulement si API et autorisations réelles |
| Mail | Découverte paginée des messages/PJ via façade Mail ; clés tenant compte du compte/mailbox/UIDVALIDITY/part selon contrat ; liste complète et signal d'expiration/suppression |
| HTTPS | Index uniquement d'URI durables connues, ETag/Last-Modified si exploitables, politique de refresh ; aucun inventaire arbitraire du Web |
| Natifs métier | Événements du propriétaire, pages filtrées par ACL et références vers projection canonique ; pas d'indexation globale des traces administratives |
| Documentation/skills | Révisions/checksums et droits effectifs ; fédération d'index existant ou projection par fichier, sans double corpus ni double note |
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

| Garantie | Scénario minimal observable |
|---|---|
| Catalogue immédiat | Lister un share synthétique puis rechercher son fichier via Memory, sans LLM ni attente Dream |
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

| Lot | Contenu | Preuve de sortie |
|---|---|---|
| 0 — Contrats et baseline | Stabiliser identité/binding/version/ACL, notes natives vs privées, complétude et purge ; inventorier tous les consommateurs et qualifier les capacités réelles ; benchmark courant | Contrats/ADR proposés, scénarios de réception, baseline synthétique et limites provider explicites |
| 1 — Catalogue et observation | Modèles catalogue + nœuds `file`/`directory`, port Memory, observation de façade et lexical immédiat ; premier parcours Nextcloud avec notes ; retrait explicite et isolation | List → Memory search → note → relecture → update → delete prouvé, y compris panne d'index après effet distant |
| 2 — Discovery/reconciliation | Curseurs complets Console/Messenger/Mail, runs/racines, scan reprenable, clôture cohérente, GC et oubli explicite ; mechanisms Dream déterministes | Corpus >500, interruptions, races et panne provider sans faux retrait ; couverture et progression compréhensibles |
| 3 — Enrichissements communs | Versions/pipelines/provenance, extraction texte/PDF/Office, image/audio/vidéo et thumbnails ; notes protégées et checkpoints | Toute analyse autorisée enrichit le bon fichier/version ; dérivés réutilisés, textes longs correctement couverts |
| 4 — Recherche et contexte | Recherche provider indexée, fédération native/documentation, filtres/passages, briefs et tous drivers ; UI Memory/Dream complète | Parcours assembled et mesures de pertinence/latence/coût ; sources et fiches clairement distinguées |
| 5 — Couverture providers et changements externes | AFFiNE/Grav discovery selon API, événements/deltas fiables, repair des sources sans événements ; adapter SDK contractuel | Matrice de capacités vérifiée par bridge, fraîcheur mesurée et couverture totale uniquement là où démontrée |
| 6 — Qualification et extension | Charge, isolation, rétention, reprise, canari et rollback ; docs FR/EN et compétences runtime | Snapshot validé, résultats mesurés, limites résiduelles et retour arrière prouvé |

Séquence recommandée : construire d'abord le parcours complet Nextcloud + catalogue/notes/
suppression, réutiliser Documents comme référence de non-régression, puis étendre la même
garantie aux groupes de providers. Ne pas généraliser une optimisation de liste à tous les
services sur la seule base du premier test. Les tests multi-compte et de réutilisation d'URI
font partie du premier lot, pas d'une phase finale de durcissement.

Pour le démarrage, rattacher les `image_description` existantes à leur fiche agent/source,
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

## 16. Arbitrages proposés avant implémentation

Les choix suivants rendent le premier lot concret sans dépendre d'un crawler universel :

1. `file` et `directory` comme nouvelles natures ; `folder` et Documents inchangés.
2. Catalogue, notes et enrichissements externes par agent/binding ; descriptions
   documentaires canoniques existantes conservées, annotation privée en complément.
3. Métadonnées/lexical à l'observation ; embeddings et analyses coûteuses asynchrones.
4. Discovery/reconciliation Dream sans LLM ; analyses automatiques activables par type et
   budget, en reprenant les options PJ actuelles sans activation coûteuse implicite.
5. Validation source actuelle des résultats sensibles ; possibilité de TTL distincte
   uniquement avec une garantie de fraîcheur bornée assumée.
6. Retrait automatique après preuve ; corbeille bornée pour les notes rédigées, GC des
   dérivés et suppression d'acquisition après oubli explicite.
7. Indexation d'URI connues pour les providers non énumérables, sans annoncer une complétude
   fictive ; adapter la discovery quand leur API la rend possible.
8. Réutilisation PostgreSQL/Memory/Dream et des modules existants ; nouvelle infrastructure
   seulement si les mesures et l'isolation des traitements la justifient.

Questions techniques encore ouvertes : capacités réelles de discovery/change-feed des comptes
AFFiNE/Grav/Nextcloud visés ; coût et faisabilité de validation ACL groupée ; politique de
corbeille/rétention et volumes cibles ; priorité souhaitée du lancement manuel par rapport au
repos Dream. Elles se résolvent au lot 0 à partir des contracts/API et mesures disponibles,
sans transformer une hypothèse de provider en promesse de produit.
