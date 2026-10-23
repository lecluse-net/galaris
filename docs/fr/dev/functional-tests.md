<p align="right"><strong>Français</strong> · <a href="../../en/dev/functional-tests.md">English</a></p>

# Catalogue des garanties fonctionnelles

Ce catalogue indique où chercher une preuve existante avant de modifier un contrat.
Il décrit les garanties couvertes par les suites ; leur présence ne signifie pas qu'elles
ont été exécutées sur votre checkout. Pour choisir une commande et comprendre sa portée,
consultez la [méthode de test](testing.md).

| Garantie à vérifier |
|---|
| [JSON et droits Dataset](#datasets) |
| [Processus natifs et interactions humaines](#processes) |
| [Éditeur Git et reprise des sessions](#code) |
| [Parcours entre domaines](#workflows) |
| [Garanties des domaines](#domains) |
| [Infrastructure et interface communes](#shared) |
| [Documents et interactions](#documents) |
| [Catalogue des fichiers](#files) |
| [Portée, supervision et commandes durables](#scope) |

## Interface partagée et édition documentaire

`metric-card.spec.mjs` protège la valeur affichée, le chargement, l’activation facultative
à la souris et au clavier et l’état sélectionné de `MetricCard`. Les historiques texte et
voix gardent leurs paramètres de filtre et leur remise à zéro ; `execution.spec.mjs` couvre
les filtres exclusifs des Tasks. `dialogs.spec.mjs` exerce `DialogHeader` dans les confirmations
et les détails : titre accessible, fermeture, réouverture et défilement sur mobile.
`dataset-dialog.spec.mjs` conserve la protection des brouillons JSON invalides lors de la fermeture.

`panel-state.spec.mjs` couvre les annonces de chargement, d’absence et de refus d’accès,
la reprise au clavier et son branchement aux trois panneaux du chat. Les scénarios
d’historique de `metric-card.spec.mjs` vérifient aussi la recherche et les dates de
`HistoryToolbar`. `core/util/usePaginatedQuery.test.mjs` protège les données lors d’un
échec, la concurrence, le changement de contexte, la destruction et la correction bornée
des pages hors limites. `process-loading.spec.mjs` exerce ses deux consommateurs Process :
réouverture, isolement des processus, réponses tardives et reprise après erreur.

`presentation.spec.mjs` vérifie le démarrage selon la langue du navigateur, la préférence
personnelle et la reprise après échec du téléchargement d’un catalogue sans recharger la page.
`core/i18n/loading.test.mjs` couvre les téléchargements partagés, le repli anglais et les
réponses obsolètes ; `authStore.test.mjs` empêche une ancienne session de modifier le profil.
Les tests `locale-catalogs.test.mjs` préservent tous les messages des catalogues générés ;
`report-build.test.mjs` vérifie les mesures de démarrage par langue.

`editor-toolbar.spec.mjs` vérifie les menus au clic droit des tableaux, liens, images,
cartes, agents, processus, blocs de code et objets HTML sur mobile et bureau : commandes au pointeur et au clavier, ciblage direct, fusion/scission des cellules,
styles, langage, lecture seule et fermeture lors d’un changement de document.
La même suite couvre les sélections de texte, titres et listes, les commandes de mise en forme
dans les liens et cellules, le presse-papiers enrichi, les coupes refusées ou tardives et le
blocage du clic droit et l’absence de barres contextuelles en lecture seule ou visualisation,
avec ouverture des liens et fonds de cartes au clic gauche sur mobile et bureau.
`e2e/specs/editorial-html.spec.mjs` vérifie aussi les propriétés d’un tableau par clic droit,
leur sauvegarde réelle et leur conservation après rechargement.
Ce parcours vérifie également le changement de niveau de titre depuis **Style** au clic droit,
sa sauvegarde puis son rechargement.

`context-menus.spec.mjs` protège l’ouverture au clic droit et au clavier sans bouton dédié, la
fermeture, les changements de disponibilité, les erreurs récupérables et la conservation du
menu natif sur le texte sélectionné. Il vérifie aussi les protections documentaires,
les états terminaux des tâches et l’ouverture d’une conversation sans menu contextuel.
Cette suite couvre aussi les sous-menus au survol : passage entre fenêtres imbriquées,
remplacement des voisins, fermeture, focus clavier, tactile et éléments désactivés.
La fermeture extérieure couvre aussi la zone d’origine, les événements dont la propagation
est arrêtée et les cadres embarqués, en conservant le focus et l’action du contrôle cliqué.

`attachment-rename.spec.mjs` vérifie la saisie d’un nom, les erreurs récupérables et
la fermeture du dialogue dans les composants réels. Son parcours E2E vérifie sur mobile
et bureau le renommage documentaire, la réouverture, le renommage depuis Fichiers et
la conservation du corps, de la révision, de l’identité et des octets. Les tests backend
Documents, Chat, Dataset et Process couvrent les droits et la lecture du seul nom dans
`files`, sans réécriture des métadonnées documentaires. Le navigateur et le parcours E2E
ouvrent aussi un fichier déjà en cache après un renommage réalisé ailleurs.

`document-apps.spec.mjs` vérifie le contraste du texte HTML isolé avec des couleurs CSS
imposées et des panneaux clairs/sombres. La bascule de thème sur mobile et bureau ne
redémarre pas les scripts, n’efface pas les champs et n’émet aucune modification du contenu.
Les parcours d’impression conservent les styles lisibles et les valeurs calculées.
L’export d’un formulaire entièrement hors écran conserve aussi ses valeurs courantes :
la capture ne dépend pas du rafraîchissement visuel de l’iframe, suspendu par Chromium.
Un panneau documentaire étroit sur un grand écran garde les boutons de formulaire accessibles
au défilement, y compris sous WebKit, après redimensionnement et en plein écran. La fermeture
de l’éditeur restitue la configuration de défilement du conteneur hôte.

`rich-text.spec.mjs` couvre le choix d’un style de tableau dans sa galerie contextuelle,
l’annulation/rétablissement, le changement et le retrait du style, puis une réouverture réelle,
la lecture et le rendu imprimable sur mobile et bureau. Colonnes, fusions et légende sont
préservées ; les nouvelles lignes héritent de la présentation. `core/util/tests/test_rich_text.py`
vérifie la conservation des 18 combinaisons par la normalisation HTML backend.
Les changements de thème adaptent le rendu sans nouvelle édition ni modification du HTML ;
la réouverture et la lecture suivent le thème actif, tandis que l’impression et le PDF restent clairs.

`document-print.spec.mjs` vérifie que le PDF conserve les diagrammes de processus, leurs
participants et les portraits d’agents. Images et cartes y restent sans liens actifs, tandis
que les liens textuels ordinaires restent utilisables. Le scénario produit un vrai PDF
synthétique pour contrôler son rendu et ses annotations de liens.

`front/browser-tests/tiptap-preservation.spec.mjs` couvre la conservation du corpus HTML
dans Tiptap, la sérialisation, la réouverture et la lecture : références canoniques, tableaux et
HTML/CSS/JavaScript opaque. Une vraie scène Three.js exerce le runtime isolé hors ligne,
ses contrôles et une capture statique non vide, sans exécution dans l’origine de l’éditeur.
La vue Source documentaire et son scénario de focus dans Discussion sont retirés ; les
scénarios de sélection rendue restent dans `chat-document-workspace.spec.mjs`. La vue Source
des champs `rich-text` reste couverte par `source-editing.spec.mjs`, et `rich-text.spec.mjs`
vérifie son absence dans les documents et les changements de profil sur mobile et ordinateur.
Le texte entre objets statiques indépendants et les tableaux à couleur héritée restent éditables ;
les régions à CSS/scripts partagés conservent leur source et son ordre. Le passage d’une sélection
d’objet au texte avant la saisie préserve l’objet. Le parcours de tableau vérifie aussi que
fusionner/scinder est disponible uniquement pour une sélection compatible.
Les suites existantes d’édition, de pièces jointes, de voix, d’exports et de Chat conservent
leurs garanties avec les commandes Quasar. Les citations internes sont qualifiées dans
leurs modales métier par `galaris-links.spec.mjs` et `process-references.spec.mjs` ; l’ancien
test d’ouverture d’un Goal dans un onglet est remplacé par ce contrat actuel.

`rich-text.spec.mjs` vérifie que la taille choisie par la poignée d’une image est conservée
à la fin du geste, après modification de ses propriétés, puis dans un nouvel éditeur et
en lecture : image de bloc, en ligne, enveloppée ou dans une cellule, agrandie ou réduite.
La réouverture recrée le composant ; réinjecter sa dernière valeur ne suffit pas à exercer
ce contrat. `e2e/specs/editorial-html.spec.mjs` couvre la sauvegarde réelle de cette taille
et son maintien après rechargement du document.
Les mêmes suites protègent l’alignement réel des images en bloc à gauche, au centre et à droite :
commandes sur mobile et bureau, propriétés, réouverture, lecture et sauvegarde via les vraies API.
La présence de boutons d’alignement ou le centrage par défaut ne prouve pas leur effet sur une image.

`document-resources.spec.mjs` distingue la sélection d’images en édition de leur ouverture
directe en lecture seule, avec ou sans lien. `document-apps.spec.mjs` conserve la saisie
et les commandes autour d’un bloc HTML groupé ; sa lecture seule ouvre une capture plein
écran sans scripts ni nouvelle sauvegarde, sur mobile et bureau.

`front/browser-tests/chat-home.spec.mjs` vérifie que l’accueil et le panneau Conversations
incluent les mêmes conversations, anciennes ou sans message. L’ancien filtre par défaut
sur sept jours et sa bascule sont retirés ; recherche, pagination, reprise après erreur et
rejet des réponses tardives après filtrage restent couverts.

`app/memory/tests/test_process_references.py` protège les références Process et Run :
droits indépendants et révocation, manifeste borné, concurrence et diagrammes de runs
figés. Les scénarios `process-references.spec.mjs` couvrent miniatures, modales,
choix lien/diagramme, zoom et sauvegarde HTML sans UI injectée.
`e2e/specs/process-document-references.spec.mjs` exerce le parcours avec les vraies API.
`internal-file-picker.spec.mjs` couvre la sélection multiple à travers les dossiers et
les recherches, sur mobile et bureau. `dataset-documents.spec.mjs` vérifie l'insertion
de citations sans écriture de manifeste ni copie des fichiers existants, avec conservation
de la sélection mise en forme. `file-browser.spec.mjs` couvre leur ouverture par URI,
le refus d'accès et la reprise. La collection de PJ exclut les anciens manifestes internes ;
les tests de références backend conservent leurs garanties de droits, concurrence et rejeu.
Les anciens scénarios d'ajout/détachement dans la liste de PJ sont remplacés par ce contrat.
Les menus fusionnés conservent les liens web, la sélection de texte et l'upload dans
`galaris-links.spec.mjs`, `mobile-editor-toolbar.spec.mjs` et `document-upload.spec.mjs`.
`galaris-links.spec.mjs` remplace les scénarios de l'ancienne recherche de liens par le
sélecteur interne commun, notamment dans le formulaire Memory au menu réduit : conservation
du texte et de sa mise en forme, annulation, fermeture, reprise après erreur et rejet d'une
sélection après changement de contenu. La navigation et la sélection multiple restent
couvertes par `internal-file-picker.spec.mjs`.
`agents.spec.mjs` couvre la carte insérée, son avatar, le choix lien/carte, la sauvegarde
sans UI injectée et l'ouverture de la carte complète par son titre en lecture et en édition,
sur mobile et bureau ; en lecture seule, l’avatar ouvre aussi la fiche.
`galaris-links.spec.mjs` vérifie le clic simple sur le titre des cartes documentaires,
la sélection par clic droit et l’ouverture des cartes et liens dans le texte au clic simple, même en édition. Il vérifie aussi que
les tâches s'ouvrent et se rouvrent en modale sans navigation, en lecture et en édition.

`chat-document-workspace.spec.mjs` vérifie que les liens et cartes documentaires remplacent
le document dans le Chat sans changer de page, avec historique précédent/suivant, sauvegarde
avant navigation, refus d’accès et rejet des réponses après fermeture. Le document transmis au
message suivant est celui affiché après navigation. `document-navigation.spec.mjs` et
`document-dialog-navigation.spec.mjs` conservent les contextes Documents et modale. Les trois
suites vérifient aussi l’action contextuelle **Ouvrir dans une modale**, sans remplacer le
document d’origine ni partager son historique en édition. En lecture seule, le fond d’une carte
ouvre directement sa cible dans le contexte courant, sans barre contextuelle.
`goals.spec.mjs` vérifie la même garantie pour les objectifs, avec leurs actions et sans
modifier la sélection d'un objectif déjà ouverte ailleurs.

`document-flows.spec.mjs` exerce le dépôt depuis la liste et l’arborescence : lien titré sans
déplacement de la source, conversion en carte, sauvegarde, réouverture et ouverture de la cible
en modale. `galaris-links.spec.mjs` vérifie le titre lors du collage d’une URI ou URL documentaire,
l’annulation, le refus d’accès et les réponses tardives.
`e2e/specs/document-links.spec.mjs` exerce les deux sources de glisser-déposer avec les vraies
API, la persistance après rechargement, le retour carte/lien et le maintien du classement.
Le document contenant appartient à un agent et la référence privée à l’utilisateur : les
titres, cartes et modales doivent résoudre les droits de la cible sans réutiliser ceux de
l’agent du document contenant. Les fixtures de bibliothèque distinguent les droits humains
des droits agents ; une autorisation humaine systématique masquerait cette régression.
`galaris-links.spec.mjs` vérifie la miniature et la copie de l’UUID au clic et au clavier,
en lecture et en édition, sur mobile et bureau, y compris pour une ancienne carte sans UUID.
La copie ne modifie pas le document et n’ouvre pas la cible. `document-print.spec.mjs` conserve
la miniature et l’UUID dans le rendu PDF, sans bouton ni lien actif sur la carte.
`document-resources.spec.mjs` couvre l'insertion répétée et le glisser-déposer de PJ
existantes sans nouvel envoi ; l'ancienne contrainte masquant l'insertion est supprimée.

`app/share/tests` vérifie l’exclusivité des configurations, l’isolation entre ressources et propriétaires, les droits de lecture/écriture et l’interdiction de repartager comme simple éditeur. La migration PostgreSQL couvre Documents, Dataset et Process, les trois types de destinataires, les accès généraux et de groupes, les suppressions logiques, le rejeu après révocation et le rollback d’une copie interrompue. Les scénarios de partage frontend communs incluent aussi Dataset.

`front/browser-tests/owner-select.spec.mjs` protège la sélection commune : accès aux propriétaires
par recherche et pages indépendantes par type, listes courtes sans pagination, identité humaine
courante, fermeture au clavier et lecture seule, sur mobile et bureau. Les filtres Documents
conservent le couple type/identifiant sans demander deux champs. Les scénarios Process vérifient
le transfert, les conflits et les brouillons conservés ; les tests HTTP refusent un transfert
hors périmètre ou par un simple éditeur et préservent l’ancien propriétaire comme éditeur.
Le parcours E2E des processus internes transfère puis rouvre une définition dans l’application.
La sélection commune vérifie aussi les images réelles des utilisateurs et agents et la
réutilisation des avatars entre ouvertures. `front/app/share/ownerCache.test.mjs` exerce les
services Documents, Dataset et Process : requêtes simultanées mutualisées, expiration à cinq
minutes, copies indépendantes, séparation des ressources et versions, invalidation de session
et réessai après erreur. Le scénario Process vérifie le rechargement à la réouverture après
expiration, sans perdre le brouillon.


`app/tools/tests/test_action_authorizations.py` vérifie aussi que les anciens accords
automatiques non consommés sont invalidés avant exécution, directement ou par réconciliation.
`app/agent/tests/test_agents.py` refuse les anciens réglages d’approbation dans les écritures API.

`app/process/tests/test_definition_storage.py` vérifie que le BPMN est stocké dans Process,
sans création de Document, ainsi que le transfert des anciens contenus, historiques et
droits, le rejeu et le rollback d'un lot invalide. `test_document_library.py` refuse les
types Process et Dataset à la création documentaire. Le parcours E2E Process vérifie aussi
l'absence de la définition dans la bibliothèque Documents avant de la modifier et l'exécuter.

`tests/test_module_loading.py` vérifie les imports obligatoires Task, plusieurs ordres de
chargement et les jobs injectés, y compris le rafraîchissement Process. Les suites embedding LLM,
recherche Tools et Memory protègent l'identité des index et les replis. Les scénarios
`app/memory/tests/test_mcp.py` passent par `file_search`/`file_read` pour les droits, le contexte
du contact et les lectures bornées ; les anciens wrappers MCP retirés ne servent plus de parcours.

Le transfert des textes natifs vers les colonnes SQL et sa sauvegarde immuable sont
couverts par `back/app/memory/tests/test_inline_content.py` : octets exacts et rejeu,
historique et synthèses, rollback, sources absentes ou altérées, UTF-8/NUL et suppression.

`app/memory/tests/test_document_library.py` couvre aussi les anciens documents `form` :
liste et filtre HTML, lecture, droits et conservation du contenu sans réécriture.
`e2e/specs/document-refresh.spec.mjs` vérifie la redirection de `/memory/documents` vers
`/documents` avec la sélection conservée, puis le rafraîchissement et le partage.

<a id="datasets"></a>

## Datasets et contrats typés

Le scénario `test_obsolete_process_markers_do_not_override_dataset_deletion_rights` vérifie
les anciens marqueurs de processus sur `data://`, les alias et les appels Memory : droits,
versions, écritures, pièces jointes et suppression logique avec historique conservé.
Les tests HTTP de propriété couvrent aussi leur suppression autorisée. Le scénario des
données de run vérifie qu'une telle suppression ne modifie ni les valeurs ni les fichiers du run.

`app/dataset/tests/test_ownership.py` vérifie les transferts sous droits et version de verrou,
la conservation du contenu et des accès, et le refus des cibles hors périmètre.
Le scénario Dataset frontend conserve le brouillon lors d'un transfert et indente les
révisions ; `formatJson.test.mjs` protège la précision des nombres et les échappements.
Le parcours E2E Dataset vérifie le transfert, la réouverture et le retour au propriétaire initial.

`app/dataset/tests/test_datasets.py` vérifie aussi qu'une création native ne crée pas de
projection Memory et que les alias historiques suivent métadonnées, révisions, révocations
de droits et suppression. Les lectures et écritures restent celles de Dataset.
`test_document_library.py` vérifie l'exclusion des Datasets historiques des résultats,
totaux et mots-clés, leur lecture conservée et le refus du type Dataset à la création
documentaire. `e2e/specs/dataset-documents.spec.mjs` exerce les deux bibliothèques séparées.
Le GET documentaire d'un Dataset historique retourne sa référence canonique sans contenu.
Les tests de PJ Dataset vérifient les liens vivants, les droits indépendants, les conflits,
les doublons, le détachement sans suppression et la liste File Sharing. Les anciens tests
d'édition JSON dans DocumentEditor sont remplacés par la résolution vers DatasetEditor et
son test de brouillon JSON invalide ; le parcours Datasets conserve l'historique/restauration.
Les tests HTML vérifient aussi la lecture d'une valeur native actuelle sans Document Dataset.

`app/dataset/tests` couvre le codec commun, le JSON libre à chaque écriture, les alias
vérifiés, les droits, les révisions et la restauration. `test_schema_removal.py` vérifie la
contraction DbAdmin et son rejeu sur une base synthétique peuplée, sans perte de contenus,
d'historique, de droits ou de PJ. `e2e/specs/datasets.spec.mjs` exerce l'éditeur assemblé.
Les suites Memory et Process conservent les contrôles de consentement, quotas concurrents,
révocation des droits, profils historiques et intégration moteur.
La saisie et la collecte HTML restent couvertes par les tests des applications documentaires.
`test_management.py` vérifie le remplacement atomique des droits agents/utilisateurs/groupes,
le refus du repartage par un éditeur et en lecture seule, les versions obsolètes, la suppression
et les utilisations filtrées avant pagination. Le parcours E2E Dataset exerce le même composant
de partage que les Documents, découvre une application documentaire puis confirme la suppression.
Il vérifie aussi le changement de sélection dans la bibliothèque, la conservation de la recherche,
la confirmation des brouillons non enregistrés, le retour mobile et la création depuis la liste.

Ce catalogue part des usages et des responsabilités des modules. Les suites citées sont les
points d’entrée vérifiables ; une ligne ne signifie ni couverture exhaustive ni qualification
d’un service externe. Les résultats exécutés et les remplacements sont consignés dans
[la revue du 10 septembre](../../../project/audits/2026-09-10-functional-tests.md).

Pour une évolution, préciser la garantie changée et celles à préserver, lire leurs contrats
et tests, puis choisir la couche la moins coûteuse qui prouve l’effet. Conserver un test utile
est une décision à part entière : aucun quota de tests nouveaux par module.

## Audio et catalogues fournisseurs

Les suites `tests/test_transcription_service.py` et `core/util/tests/test_http_multipart.py`
protègent l'envoi audio depuis des octets ou un fichier et la fermeture des handles après
erreur ou annulation. `tests/test_audio_resource_discovery.py` couvre les catalogues vocaux
publics, leur cache séparé par fournisseur, son expiration et le réessai après panne.

<a id="processes"></a>

## Processus métier internes

Le scénario de convergence de `test_native_bpmn.py` couvre les bifurcations directes et
imbriquées par des activités ordinaires, les six ordres de réponse et une seule admission
de la tâche suivante. Il conserve aussi un cas de passerelle historique. Le parcours
`ordinary activities can branch` de `native-processes.spec.mjs` construit les branches et
leur réunion par les poignées ordinaires, sans bloc de parallélisme à ajouter.

`back/app/process/tests/test_run_execution_state.py` vérifie l'atomicité des données
fonctionnelles et des reçus du run, le rejeu idempotent, les rollbacks et le refus des
écritures tardives après un état terminal. Les scénarios existants de
`test_native_bpmn.py` couvrent les fusions concurrentes, la perte d'accusé de réception
et les fichiers transmis aux sous-processus. Le test de stockage vérifie aussi l’absence
de création de Dataset/Document et l’héritage puis la révocation des droits du processus
sur les variables et les fichiers gérés.

`test_run_observation.py` protège les dates de début et de fin de la liste native.
`front/app/process/runTiming.test.mjs` vérifie que la durée commune aux deux moteurs
exclut l’attente initiale, se fige en fin d’exécution et reste indisponible sans début.

`front/browser-tests/process-loading.spec.mjs` vérifie que le catalogue s'affiche sans
télécharger les fiches d'exécution ni attendre les agents et le contrôle n8n. Les runs
ne sont chargés qu'au dépliage du processus ; les sous-listes restent isolées et une erreur
de chargement permet un réessai, sur ordinateur et mobile. La pagination conserve les totaux
serveur et les pages indépendantes ; le rafraîchissement global recharge les sous-listes
ouvertes sans changer leur page, comme les événements d’exécution et les reconnexions.
Le retour de l’éditeur conserve recherche, agent, tri, pagination et dépliage sur ordinateur
et mobile ; changer d’utilisateur réinitialise ces préférences.
Une rafale pendant un chargement lent déclenche un seul rechargement supplémentaire ;
replier la liste retire ses abonnements aux événements.
Les filtres moteur/archives, les descriptions natives et les compteurs en direct se vérifient
sans charger de fiche d’exécution ; une réponse tardive d’un filtre précédent est ignorée.
Les diagnostics n8n restent dans une modale refermable
pendant la synchronisation ; le bandeau distingue une connexion cassée d’une intégration
non configurée. La ligne et l’icône d’édition ouvrent le processus sans déplier les exécutions ;
la zone de la flèche à gauche déplie les exécutions sans naviguer, avec accès au clavier.
L’éditeur externe conserve les brouillons après
échec, respecte la lecture seule et ignore une réponse tardive d’un autre processus. Les fiches
retardées restent refermables et se rouvrent sur ordinateur/mobile. Le scénario de mesure
joint les requêtes de modules, leur volume décodé et le délai d'affichage, sans seuil temporel
fragile. `e2e/specs/process-catalogue.spec.mjs` ouvre la liste puis l'éditeur avec les vraies
API, déplie cinq exécutions réellement lancées, enregistre une description externe puis la
relit après rechargement et interdit le chargement des profils complets des agents. `storeConcurrency.test.mjs`
protège l'affichage indépendant des définitions et la conservation des agents lors d'un filtre.

`back/app/process/tests/test_catalogue_performance.py` mesure les listes autorisées sur une
base PostgreSQL isolée avec cinq exécutions et force les seuils de compilation JIT qui
reproduisaient plusieurs secondes de latence. Il vérifie le budget interactif des listes
d'exécutions et de définitions ainsi que le rétablissement des paramètres de transaction
après commit et rollback. Les tests de permissions des processus conservent les refus,
les partages et l'exclusion des définitions orphelines ; l'optimisation du filtre d'accès
retire les branches de dossiers et de pièces jointes inutiles à ces listes.
`test_catalogue.py` protège la pagination commune au-delà de 500 définitions, les recherches
littérales et les archives, les droits distincts des runs natifs et externes, les attentes
humaines et le nombre borné de lectures SQL. La mesure de transfert compare l’ancienne liste
complète avec une page sur les mêmes données synthétiques.

`front/browser-tests/native-processes.spec.mjs` exerce le diagramme d'exécution dans les
modales du Chat, de la définition et du suivi ainsi que le contenu partagé : activité en cours,
résultats/données en lecture seule, activité non exécutée et rejet d'une réponse tardive
après changement de nœud. Le parcours Chat vérifie aussi fermeture/réouverture sur ordinateur
et mobile ; son scénario de processus externe conserve la lecture des entrées/sorties.
Les entrées Chat, catalogue et suivi réutilisent la même modale native, y compris son en-tête.
Le scénario temps réel vérifie le statut, la durée et le coût de cette modale,
les événements filtrés par run, les mises à jour pendant
des requêtes en cours, la fiche ouverte jusqu'au résultat final, la reconnexion et le
nettoyage des abonnements à la fermeture. Les statistiques retardées ne bloquent ni
l'ouverture du graphe ni sa progression, et une réponse tardive d'un autre run est ignorée.
Le scénario externe de `chat.spec.mjs` vérifie aussi la lecture du résultat actualisé par
WebSocket, les actions limitées aux privilèges, la fermeture et la réouverture du détail partagé.
`test_native_bpmn.py` vérifie les permissions et la consultation
indépendante de la pagination générale, avec isolation des corps de boucle et limite de 500.

Les modales de processus restent utilisables lorsque le téléchargement d'un écran d'un
autre domaine est indisponible. `topic-detail.spec.mjs` conserve la lecture, les erreurs,
le réessai et la fermeture des autres types de ressources. `chat.spec.mjs` vérifie le tri
chronologique, la conservation de la position au chargement des runs plus anciens et le
défilement vers les nouveaux runs sur ordinateur et mobile.

`test_run_observation.py` couvre la participation figée, les rôles inutilisés, les ACL
héritées du Process, la révocation de l'administration dédiée et le cycle
attente/pause/reprise/arrêt. Les scénarios de suivi de `native-processes.spec.mjs`
exercent les commandes sur la même exécution, la confirmation d'arrêt, la lecture seule
et la disparition des attentes terminées. Le parcours assemblé reprend une activité
humaine après pause puis recueille sa réponse dans le Chat.

Le scénario d'historique de `front/browser-tests/native-processes.spec.mjs` vérifie la
pagination serveur des sauvegardes, le réessai d'une page en erreur et la conservation
du brouillon pendant la navigation dans l'historique. Les confirmations de retour et de
suppression sont exercées avec annulation et erreur serveur, sans perte du brouillon.
`test_native_bpmn.py` vérifie les droits HTTP, le refus de supprimer l'état courant,
la pagination sans cet état et la conservation des exécutions après suppression d'une sauvegarde.

Le profil v2 est couvert par `test_typed_values.py` et les scénarios typés de
`test_native_bpmn.py` : transport récursif, nullable omis, défauts, types stricts,
round-trip XML, sorties locales, protection du Dataset global, intégration idempotente
après accusé perdu, conflits et URI sans transfert. Les six ordres de convergence de
trois tâches humaines n'admettent qu'un successeur. REST utilise un serveur HTTP
synthétique avec les vraies connexions ; les refus HTTP sont conservés. Les tests du port
de code remplacent seulement le runner distant et vérifient attente, identité, refus
sans runner et confirmation d'arrêt ; ils ne qualifient aucune isolation système.
Les composants testent la sauvegarde des déclarations, les brouillons invalides et
omission/null/false. Le parcours assemblé typé utilise un vrai utilisateur affecté,
le formulaire de sortie et PostgreSQL, avec refus des défauts invalides à la sauvegarde.
Les garanties de pool partagé décrites ci-dessous concernent le profil historique v1.

`back/app/process/tests/test_native_bpmn.py` exerce le compilateur, les expressions,
Documents/grants/Datasets réels, la reprise Task, les droits humains et orphelins,
FOR/WHILE, convergence, arrêt à la première erreur, debugger et appels courants. Les services et PostgreSQL
restent réels ; la réponse du harnais est synthétique. La campagne Lab admet et observe
un vrai Run sans mock externe. `front/browser-tests/native-processes.spec.mjs` monte
les composants réels avec des réponses HTTP synthétiques : connexions/clavier,
lecture seule, conservation des brouillons et sauvegarde avec révision attendue.
Les acteurs survivent à l'aller-retour XML ; les inversions humain/agent sont refusées.
La suite vérifie l'agent réellement affecté et l'écriture des données de son run, ainsi que
l'attente humaine, le refus d'un autre utilisateur, la désactivation,
les réponses répétées et l'annulation. Les composants construisent le flux depuis Début,
insèrent depuis les poignées en préservant les conditions et filtrent les acteurs compatibles.
La réponse humaine conserve son brouillon après une erreur réseau. Les captures synthétiques
servent à l'inspection visuelle en clair, sombre et mobile, sans figer la présentation.
Le glisser-déposer change les acteurs agents et humains au dépôt, conserve types et liens,
refuse les lignes incompatibles et annule sur Échap ou révocation de l'édition. Le parcours
assemblé vérifie l'affectation après sauvegarde, rechargement et lancement.
`e2e/specs/native-processes.spec.mjs` exerce l'application assemblée : édition et
sauvegarde, Task réellement admise, suivi de fin, données persistantes et graphe du Run
préservé après modification de la définition. API et PostgreSQL restent réels ; seul
le harnais est synthétique. Les paramètres de pagination encodés dans l'URL sont aussi
vérifiés par HTTP avec les droits réels sur les routes Process et Lab.
Les données JSON sont vérifiées dans le champ accessible de l’exécution ; l’ancienne
assertion d’ouverture par clic sur le libellé « Données du run » est retirée.

Le parcours de `test_activity_controls.py` utilise le vrai scheduler, ses leases,
la façade Agent, le client du harnais, MCP HTTP et PostgreSQL ; seul le harnais distant est
synthétique. Il couvre la perte du résultat distant avant la réponse humaine, la réconciliation
sans nouvel effet, un nouveau tour consommant la réponse, une deuxième question dans la tâche
suivante, la pause du processus, le redémarrage de l'engine et l'unique notification finale.
Les tests protègent aussi les anciennes références, les retraits concurrents, le rollback
et une activité déléguée qui continue d'échanger dans la conversation de lancement.

`app/process/tests/test_decisions.py` exerce les deux branches des IF IA/code/humain,
les droits et reçus humains, la modification du Dataset par retour Python ordinaire et
le vrai worker Monty : accès système/réseau refusés, boucle et saturation bornées.
Les parcours Chromium assemblés exécutent une tâche code, puis un IF code ou le clic
humain False dans Chat. Les composants vérifient les deux poignées et les modes par acteur.
Le parcours humain ajoute une activité par poignée, sauvegarde, lance, répond depuis
la boîte d'activités affectées et vérifie la reprise jusqu'à la fin du Run.
Le JSON métier et les pièces jointes sont communs à toutes les tâches d'un Run : les
tests vérifient lecture/écriture via File Sharing, révisions dépassées, préservation
des modifications parallèles, accès humain/agent, boucles et isolation entre Runs.
Les anciens oracles de schémas, slots et affectations sont retirés avec ces fonctions ;
le compilateur vérifie qu'ils ne créent plus d'exigences cachées. Le brouillon JSON
invalide est protégé sur les arguments Tool qui restent éditables. Le parcours humain
assemblé édite le Dataset, ajoute un fichier et vérifie leur conservation jusqu'à la fin.
L'arrêt sur erreur remplace les anciens tests de réessai/secours : une seule tentative,
aucun successeur, annulation des branches actives, codes d'erreur conservés pour les
exécuteurs et les enfants, données préservées. Les exceptions inattendues sont aussi couvertes.
Les suites Dataset/partage couvrent les consommateurs communs. Elles ne qualifient
pas à elles seules les effets d'un harnais ou d'un serveur n8n réel.

<a id="code"></a>

## Dépôts Git dans la discussion

`back/app/console/tests/test_repository_listing.py` couvre la découverte SFTP bornée,
les chemins depuis le home, les worktrees, les liens symboliques et les résultats partiels.
`back/app/code/tests/test_workspaces.py` couvre aussi la découverte réservée au propriétaire,
les refus HTTP hors discussion et l’association explicite sans démarrer l’IDE.
`front/browser-tests/chat-code-workspace.spec.mjs` exerce l’ouverture depuis la liste sans
message de l’agent, au clavier et sur mobile, le retry, les résultats partiels et les réponses tardives.

`back/app/code/tests/test_workspaces.py` vérifie les grants exacts, la déduplication,
les tickets expirés, la révocation et le refus de changer de cible avec PostgreSQL réel.
Le déploiement Console couvre les droits de gestion, la vérification du tunnel avant publication
des paramètres chiffrés, les changements de droits pendant l’installation et la conservation
des URI des seuls checkouts inchangés. Une session ouverte empêche de changer son runtime.
`front/browser-tests/console-recovery.spec.mjs` protège le déploiement direct sans test SSH
préalable dans la fenêtre, les blocages globaux explicitement expliqués au clic, le retry,
les réponses tardives et la sauvegarde qui conserve le credential sans le renvoyer au navigateur.
Le parcours avec `ConnectionList` et son formulaire réel vérifie que Tester et Déployer
conservent l’activation enregistrée, même après modification non enregistrée, annulation et
réouverture, pour une Console active comme pour une Console volontairement inactive.
Le panneau vérifie aussi les changements de thème Galaris sans API de synchronisation IDE,
les réponses retardées et la navigation explicite sans remplacer un buffer. La qualification
native exerce le diff d’un fichier et les vues de changements indexés/non indexés.
La maintenance automatique sélectionne uniquement les Consoles externes actives déjà configurées,
vérifie un service à jour même avec des sessions ouvertes, refuse un remplacement avec sessions
actives et conserve les paramètres d’accès. Les erreurs distantes reconnues indiquent l’étape
et le motif ; un motif inconnu ou une sortie distante privée ne sont jamais réaffichés.
Une panne ne divulgue pas de secret et n’empêche pas
les autres cibles d’être vérifiées. `make tests-update` protège l’exécution après disponibilité
du backend et la propagation d’un échec de maintenance à `make update`.
Les échecs injectés imposent aussi un journal privé de l’étape et du code de sortie pour les
déploiements depuis les sources et les releases. `core/tests/test_update_diagnostics.py`
vérifie la conservation des causes et des sorties utiles sans secrets, les permissions,
la rétention bornée et le repli explicite lorsque le stockage échoue. La CLI de maintenance
doit afficher le chemin du diagnostic et poursuivre les autres cibles.
`code-executor/tests/test_deployment.py` vérifie l’orchestration avec une frontière Docker
simulée, dont l’exigence d’une colonne PID pour `docker top` et le refus de remplacer un
éditeur dont des processus de session sont actifs. Le contrôleur demande `pid,comm` et
compare les noms de processus sans leurs PID. Les suites natives ci-dessous vérifient
séparément code-server réel et ses montages.
`make tests-code` vérifie également ce contrat de `docker top` avec Docker réel sur un
conteneur jetable suspendu, pour ne pas qualifier le seul comportement d’un double de test.
`front/browser-tests/chat-code-workspace.spec.mjs` exerce les composants du panneau partagé,
la conservation de l’iframe non enregistrée et l’isolation des séquences/rooms ; son contenu
IDE est une fixture explicite. La suite documentaire existante protège ses propres parcours.
`make tests-code` utilise Bubblewrap, un Git réel et une forge SSH synthétique pour les
montages, les worktrees, l’identité partagée, pull/push et un rebase en conflit.
`make tests-code-browser` utilise code-server réel pour les changements externes et le
conflit de sauvegarde natif, puis le transport Console réel vers une cible SSH préparée.
Les archives de profils sont restaurées avec leurs brouillons ; une sauvegarde échouée,
une maintenance concurrente ou une archive dangereuse laisse les données protégées.
Elle exerce également le lancement à ticket, le cookie scoped, les workers, WebSockets
et la sauvegarde sur l'origine unique, derrière les proxies Nginx et Vite réels,
à travers la passerelle Galaris avec PostgreSQL réel, dans Chromium,
Firefox et WebKit, y compris l'expiration suivie d'une reprise du cookie et des WebSockets
sans remplacement du buffer. L'arrêt réel du processus IDE vérifie la sauvegarde dans
une fenêtre de récupération avec l'ancien brouillon toujours accessible. Le panneau
vérifie aussi l'annulation par backdrop et la confirmation avant un second remplacement.
Les droits retirés et les cibles modifiées restent refusés.
L'aperçu Markdown Firefox est une limitation acceptée, surveillée par un scénario distinct
en échec attendu ; les scénarios d'édition restent entièrement bloquants. Les mesures agrégées d'ouverture,
d'actualisation, de mémoire et de CPU sont jointes aux résultats du runtime synthétique.
Les résultats de ces dernières qualifications sont des artefacts d’exécution ; leur
présence au catalogue ne remplace pas une exécution réussie.

## Médias et preuves acquises

`app/voice/tests/test_audio_pacing.py` exerce les pistes réelles du Chat, de Matrix et
de Nextcloud avec une horloge synthétique commune : cadence sans dérive due à l'encodage
ou aux réveils tardifs, reprise sans rafale après une suspension, PCM et timestamps
préservés, interruption pendant l'attente et annulation sans perte de trame. Les tests
de vidage seuls ne détectaient pas cette dérive. Ces mesures isolent le transport ;
elles ne mesurent pas la latence du fournisseur vocal ni celle du réseau réel.

`app/voice/tests/test_realtime_engine.py` reproduit un outil suspendu pendant une reprise
de parole : l'interruption et l'audio suivant passent sans attendre son résultat. Le même
moteur vérifie les annulations fournisseur, les événements tardifs, l'ordre des outils,
le round d'autorité conservé, la file bornée, la fermeture après erreur, l'annulation au
raccrochage et une seule relance après les résultats et autorisations. Les fournisseurs
et outils de ces scénarios sont entièrement synthétiques.

La révocation et la suppression différée des flux audio sont couvertes par
`app/voice/tests/test_monitoring_service.py`, `test_runtime_control.py` et `test_session.py` :
transactions PostgreSQL réelles, propriétaire distant, erreurs tardives de fermeture,
reprise du nettoyage, permissions HTTP et écritures tardives refusées.
`front/browser-tests/voice.spec.mjs` exerce aussi la confirmation du raccrochage,
la conservation du tour pendant un nettoyage, le réessai et les réponses tardives après
navigation. Les transports audio et API des composants sont synthétiques ; aucun appel
réel réparti entre deux processus avec redémarrage n'est certifié par ces scénarios.

`back/app/image/tests/test_image_mcp.py` couvre les références d'image sous forme d'URI,
de liste ou de liste JSON encodée, le nettoyage des temporaires et le nom conforme au format
natif sans conversion ni remplacement d'un fichier voisin. Le parcours de
`back/app/memory/tests/test_document_resources.py` génère un PNG synthétique, le copie en pièce
jointe, l'intègre au document et vérifie les droits du lecteur.
`back/app/chat/tests/test_native_facade.py` vérifie l'envoi MCP d'un fichier à un humain,
avec et sans Task, sur de vraies transactions PostgreSQL indépendantes : la synchronisation de
la room ne bloque pas son propre reçu, les octets et le message restent lisibles. Ce scénario
emploie `committed_database` ; les savepoints partageant une connexion masqueraient ce blocage.

L'analyse documentaire relève de `app.llm` et ne crée aucune définition ni exécution
de processus métier. `back/tests/test_document_analysis.py` protège cette séparation,
la reprise des lots de 500 pages sans double facturation, l'annulation, les droits,
la progression par le scheduler et le transfert idempotent des anciens runs techniques.
Le cache de préparation temporaire réutilise les conversions, revalide les droits et disparaît
avec son espace de travail.
Les scénarios HTML paramétrés de `front/browser-tests/attachment-previews.spec.mjs` protègent
le lecteur commun des PJ Documents, messages et liens : interaction isolée sous CSP restrictive,
téléchargement des octets d'origine, nouvel onglet et réouverture sur petit écran sans upload
de prévisualisation. L'ancien contrat de copie HTML temporaire avec ticket est retiré ;
les tests du stockage Chat protègent désormais aussi le round-trip d'une PJ HTML ordinaire.
Le même scénario raccorde les passages acquis au round sans préparation ni nouvelle inférence,
vérifie l'isolation agent/Task/URI, les versions obsolètes et les reçus tardifs.
`back/app/dream/tests/test_conversation_memory.py` protège la capture d'un audio sans texte,
l'attribution et la langue, les répétitions, la revalidation avant application et après capture
(lecture, rappel et graphe), ainsi que la conservation d'une provenance indépendante.
`test_acquisition_automation.py` bloque la réacquisition d'un fait oublié depuis une révision
tardive du même round, tout en admettant une correction.
`test_search_performance.py` vérifie aussi le budget de requêtes par page pour les nouvelles
provenances conversationnelles sur un corpus synthétique de 6 000 souvenirs, sans cache
persistant des droits et sans élargir la portée privée de l'agent.
Les requêtes avec CTE sont incluses. La politique de planification ne modifie pas les
paramètres de connexion des transactions suivantes, après commit comme après rollback.
`test_memory_extraction.py` vérifie qu'une provenance ajoutée par LINK ne rend pas un
souvenir manuel ou un document préexistant dépendant de cette preuve conversationnelle.

## Administration des agents

AgentAdmin est documenté dans [agent-admin.md](agent-admin.md).
`back/app/agent/tests/test_avatars.py` vérifie le stockage JPEG dans une limite de 500 × 500,
les proportions, l’absence d’agrandissement, l’orientation EXIF et la transparence.
Son parcours HTTP remplace un PNG synthétique de plus de 8 Mio par un JPEG compact,
puis vérifie qu’un remplacement invalide conserve l’avatar et sa révision.
`back/app/agent/tests/test_avatar_generation.py` vérifie la génération humaine avec le profil
LLM par défaut, les droits de gestion, l’indisponibilité du modèle et la conservation de
l’avatar après une erreur ou une modification concurrente. Le parcours du bouton dans
`e2e/specs/agent-admin.spec.mjs` vérifie l’affichage et la réouverture avec un fournisseur
synthétique ; `front/browser-tests/agents.spec.mjs` vérifie le réessai et les réponses tardives.
`back/app/agent/tests/test_agent_admin.py` protège le CRUD sans contexte humain HTTP,
le périmètre du responsable, les services système et la délégation réservée aux humains,
les 34 fonctions et leur révocation sur un serveur MCP monté. Les appels directs sans Process
vérifient l’image valide, le fournisseur incertain, la révocation, le profil modifié,
l’avatar tardif, la suppression et le rejeu d'une autorisation sans nouvelle soumission.
`back/app/process/tests/test_dbadmin.py` vérifie la purge ciblée des anciens workflows avatar,
y compris leurs jobs et événements, sans supprimer les processus métier ni bloquer leurs Tasks d'attente.
`e2e/specs/agent-admin.spec.mjs` vérifie la création et deux portraits successifs réellement
affichés après navigation Vue sans rechargement, une civilité renommée et le refus après
révocation, avec un fournisseur synthétique.
`front/browser-tests/agents.spec.mjs` retarde la réponse d'un ancien catalogue puis
vérifie qu'elle ne retire pas le portrait chargé par le catalogue courant et que son
URL temporaire est libérée.

## Organisation des Tasks et planification

`back/app/agent/tests/test_conversation_dispatch.py` protège la préanalyse réservée au mode
conversation et conditionnée à Décision : références exactes, réponse versus suivi, lancement
indépendant, absence de conclusion avec contexte incomplet, erreur et annulation.
`back/tests/test_decision_workflows.py` vérifie la résolution réelle du profil et la persistance
des inférences conversationnelles, avec remplacement du seul transport HTTP. Le scénario du
contrôleur dans `back/app/harness/tests/test_conversation_prompt.py` vérifie l'injection dans le
prompt, les pièces jointes et la responsabilité de l'exécuteur sans analyse. Ces tests ne
mesurent ni la qualité sémantique ni la latence d'un modèle réel.

`back/app/task/tests/test_execution_scope.py` vérifie le refus d'écriture hors périmètre avant
tout effet, sa cause distincte d'une erreur d'arguments, sa transmission MCP jusqu'au modèle
avec ou sans checkpoint et la réussite après un amendement sourcé. Le test de preuve externe
dans `back/app/harness/tests/test_execution_evidence.py` interdit de falsifier ce diagnostic
comme une preuve native. Les modèles de ces parcours sont synthétiques ; ils ne qualifient
pas l'obéissance d'un fournisseur réel à la consigne de ne pas réessayer.

`back/app/agent/tests/test_planner_collections.py` couvre les traitements répétés : petits lots
mécaniques connus d'au plus cinq éléments en une feuille sans découverte ni replanification,
décomposition des traitements substantiels ou des lots trop grands/inconnus, une Task
par élément de collection, vagues bornées, inventaire Dataset vérifié avec les ACL, refus des listes
incomplètes ou ambiguës, progression et reprise après rechargement sans rejouer les succès.
Le parcours PostgreSQL conserve l'inventaire figé même si le Dataset est modifié ensuite.
Il couvre les créations natives `data://` et les anciens alias documentaires vérifiés,
sans exiger la livraison d'un inventaire interne. `app/dataset/tests/test_datasets.py`
vérifie le refus d'un appel de création sans JSON avant effet, puis sa correction sans
ressource supplémentaire ni Document HTML de substitution.

Ces scénarios couvrent aussi les clôtures durables demandées après erreur ou blocage :
rapport exécuté sans reprendre les dépendances, échec global conservé, rechargement,
réveils idempotents et bilan actualisé après reprise manuelle. `test_planner_service.py`
couvre une clôture elle-même en erreur. `test_document_retrieval.py` vérifie la recherche
documentaire par nom sans rappel sémantique ni passages du corps, avec pagination et refus ACL.

`back/app/agent/tests/test_task_organization.py` protège le choix d'organisation dans
l'inférence existante, l'attente sans exécution, l'expiration et la réponse tardive.
`back/app/task/tests/test_work_tracking.py` vérifie avec PostgreSQL la reprise des jalons,
les écritures concurrentes, la révision, les droits, les pauses, l'idempotence et la
préservation des checkpoints, y compris une sauvegarde d’exécution entre lecture et écriture du suivi.
Le corpus synthétique `task_organization_corpus.json`
s'importe avec `scripts/import_lab_reference.py --corpus task-organization --install`.
Ses huit cas complètent les quinze frontières de routage ; une comparaison avec modèle
réel mesure décisions et latence, sans certifier la réalisation complète des missions.

Le corpus synthétique `back/app/lab/planner_boundaries_corpus.json` contient 24 cas de
granularité : collections ordonnées, reprise partielle, volumes inconnus, petits lots,
tâches uniques complexes, PLAN forcé, plan écrit explicitement demandé et clarification.
Il s'importe avec `scripts/import_lab_reference.py --corpus planner-boundaries --install`.
`test_reference_corpus.py` vérifie l'import authentifié, la persistance et les contrats.
Les références sont des exemples sémantiques ; les critères `acceptance_by_case` permettent
de distinguer plans vides, tâches uniques fragmentées et collections manquées. La qualité
requiert des appels réels et une revue des plans, pas seulement ces tests sans modèle.
`back/app/lab/tests/test_evaluation.py` interdit un verdict favorable pour une sortie
sans brief ou étapes, ou mélangeant plan et clarification. Les fixtures de succès des
tests de génération et de revue utilisent donc un vrai plan exécutable.
`back/tests/test_protocol_inference.py` reproduit une réponse fournisseur `response.failed`
contenant un appel d'outil vide : l'inférence et sa trace restent en échec, en flux comme
en réponse JSON, au lieu de transformer cet appel en plan accepté.

<a id="workflows"></a>

## Parcours traversant plusieurs domaines

Le parcours `front/browser-tests/memory-3d.spec.mjs` exerce 10 000 nœuds et 20 000 relations
synthétiques en 3D. Il vérifie la couverture des groupes spatiaux,
leur ouverture vers un item canonique, les filtres, le clavier, le réessai 3D après une perte WebGL,
le changement d'agent et les miniatures retardées jusqu'à leur taille native. Les cas de
huit feuilles retiennent la première page jusqu'après l'initialisation d'une scène vide :
ils protègent le cadrage d'ensemble à l'arrivée des données et le maintien du groupe ouvert.
Le premier pixel de glissement et la rotation conservent la position à l'écran d'un
nœud décentré ; l'aller-retour restitue la pose caméra initiale. Le geste avec le clic gauche reste une rotation autour de l'objet pressé,
sans ouverture ; seul le clic immobile ouvre. Un glissement gauche commencé sur le fond
translate le graphe avec le pointeur sans modifier l'orientation, depuis la vue d'ensemble
ou une vue tournée, y compris après zoom sur desktop/mobile avec les boutons gauche et droit.
Le déplacement à l'écran suit celui de la souris sans accélérer à l'approche des nœuds ;
l'aller-retour restaure le cadrage et le déplacement s'arrête au relâchement.
La navigation traverse un nœud puis
continue en espace vide, avec boutons, molette et pincement. Le zoom à la molette conserve
le centre d'une miniature décentrée sous le pointeur à l'approche et au recul, sans rotation,
se dirige aussi vers un fond vide et retrouve une vue d'ensemble stable au recul maximal.
La taille native des
aperçus est vérifiée avant de dépasser leur plan ; leur présence après dépassement
n'est plus une contrainte de zoom. Le compteur de frames confirme l'arrêt du rendu au repos. Le parcours HTTP réel
`e2e/specs/memory-graph.spec.mjs` conserve positions et filtres après réouverture en 3D.
`app/memory/tests/test_graph_state.py` protège les caméras indépendantes et les valeurs invalides.
`front/app/memory/graph3dCamera.test.mjs` vérifie avec une projection Three.js que les
graphes larges, hauts et profonds sont entiers, centrés et utilisent le viewport desktop/mobile,
y compris avec de grandes coordonnées ; les graphes vides et à un seul nœud gardent une pose finie.
Les cas desktop/mobile protègent l'affichage d'une première page pendant l'attente de la
suivante, la navigation conservée, le réessai après erreur, les répertoires connus dès
l'ouverture et leurs fichiers à l'approche, puis leur réouverture. Un lien dont une
extrémité est derrière la caméra reste absent jusqu'au recentrage. `graph3dChildren.test.mjs`
vérifie concurrence bornée, curseurs, pagination complète des dossiers proches, arrêt des pages
suivantes hors champ et rejet des réponses obsolètes. `graphRefresh.test.mjs` protège la fusion
des différences, les données inchangées, les réponses concurrentes et les suppressions confirmées.
Les parcours desktop/mobile vérifient les actualisations périodiques et reconnexions sans
effacement, le maintien de la caméra, les titres modifiés sans nouveau placement, les erreurs
temporaires et le retrait sur refus d'accès. Un dossier de 501 fichiers traverse deux pages,
le réessai, la réouverture puis l'ajout et la suppression de fichiers en arrière-plan.
Le test `graph_hierarchy` du catalogue traverse les vrais services de ressources,
la pagination des enfants, les filtres et les sources disparues ou révoquées.
Les tests du catalogue vérifient aussi les titres de racines persistés depuis le libellé du
Tool, le repli sur le schéma, la réparation des anciens titres et les noms personnalisés.

`front/browser-tests/async-views.spec.mjs` couvre l'ouverture différée d'un vrai éditeur,
la saisie dans le reste de la page pendant l'attente, la fermeture avant la réponse,
la réouverture et le réessai du chargeur sans perdre le brouillon, sur mobile et desktop.
Un téléchargement de module en échec reste explicite sans imposer un rechargement global.
`provider-resources.spec.mjs` conserve la sélection d'un modèle lorsque le formulaire
arrive après la transition d'onglet. `memory.spec.mjs` impose une seule recherche et une
seule lecture des filtres à l'initialisation de l'agent de la page Mémoire.

`back/tests/test_api_read_cost.py` ouvre et réouvre les Documents via HTTP avec 1 puis
1 000 révisions : contenu courant frais sans matérialiser l’historique, ancienne version
lisible et pagination bornée. Il mesure aussi identité, Agents, bibliothèque, propriétaires
et cycles Goal, puis vérifie les refus après retrait du gestionnaire et du rôle.
`app/agent/tests/test_management_scope.py` couvre l’invalidation du périmètre à l’écriture,
aux changements de rôle, aux fins de transaction et après la réponse ;
`core/user/tests/test_refresh_session.py` couvre le contrôle compte/session regroupé,
les jetons historiques, l’expiration, la révocation et les UserToken.
`core/user/tests/test_token_management.py` exerce les routes HTTP réelles : gestion
des jetons personnels et MCP réservée aux JWT web, refus des UserToken même administrateurs,
absence de mutation après refus, isolation entre propriétaires et fermeture des conversions
UserToken → JWT par `keep-alive` ou changement de rôle. Le parcours web conserve création,
consultation, modification, révocation et renouvellement ; les appels API ordinaires restent possibles.
La même suite vérifie le refus des jetons API pour les comptes, mots de passe, avatars,
MFA, aides masquées, rôle par défaut et préférences LLM/voix, y compris les routes administratives.
Le changement de mot de passe en session web reste possible et révoque l’ancienne session.
`core/user/tests/test_user.py`, `test_help_dismissals.py`, `test_mfa.py` et
`app/llm/tests/test_personal_speech.py` conservent les parcours web de ces réglages.
Les cycles restent lisibles si un document Goal manque, tandis que le détail conserve
son erreur ; `app/goal/tests/test_goal_runner.py` vérifie aussi propriétaire et référent.
Ces budgets SQL synthétiques ne constituent pas une mesure de latence en production.

`app/dataset/tests/test_list_performance.py` vérifie les droits, tailles UTF-8 et checksums
des listes sans charger les contenus JSON, ainsi que la révocation à la réouverture.
`app/memory/tests/test_search_history_budget.py` protège la recherche de documents partagés :
droits de lecture/écriture conservés, nombre de requêtes borné et historique non matérialisé.
`app/tools/tests/test_catalog_sql_budget.py` contrôle les lectures groupées du catalogue MCP,
l'héritage des modes de fonctions et la prise en compte immédiate d'une désactivation.
`app/task/tests/test_tree_performance.py` exerce pause et reprise d'un arbre en base réelle,
sans retirer les autres raisons d'attente ni modifier les tâches terminées.
La comparaison Lab garde ses contrôles d'ambiguïté avec un budget indépendant de la taille
de page dans `app/lab/tests/test_comparison.py`. Les recherches vectorielles restent exactes ;
les compteurs et les pages de doublons partagent leur calcul dans un même snapshot SQL.
`app/memory/tests/test_vector_read_cost.py` compare les résultats à un corpus vectoriel
synthétique connu et vérifie l'isolation entre propriétaires. Le scénario
`app/task/tests/test_list_plan.py` compare les buffers de la même page sur 20 000 tâches,
avec et sans les index temporels, uniquement dans la base éphémère.

`app/browser/tests/test_network_permissions.py` couvre permissions durables par agent/origine,
réponses par texte et boutons, refus, nouvelle demande après suppression ou expiration,
concurrence entre sessions SQL, priorité de la connexion, DNS mixtes, filtres et droits HTTP
des gestionnaires. Il vérifie aussi le mode public sans question, l’héritage global et la surcharge
par agent, le retour aux demandes par site, les refus explicites et le maintien du blocage local.
Le défaut public des installations neuves et la conservation du mode des instances existantes,
y compris sans paramètre enregistré, sont vérifiés avec deux synchronisations successives.
`browser-executor/network-proxy.test.mjs` utilise Chromium et des serveurs
synthétiques pour vérifier POST, redirections, isolation, HTTPS avec validation du certificat,
WebSocket et révocation. `front/browser-tests/permissions.spec.mjs` vérifie la liste réelle,
les demandes sans réponse, les réponses ponctuelles exclues des accords permanents, la révocation
MCP vers « Sur demande », la fermeture par fond de modale et le réessai après erreur sur mobile et
desktop. Elle couvre aussi les réponses réseau et les réponses tardives après changement d’onglet.
La même suite backend vérifie l’accord couvrant tous les sites, sa révocation, la priorité des
filtres et la séparation du réseau local, ainsi que le français, le chinois et la langue par défaut.
Les accords historiques par site ne sont pas élargis ; les anciennes questions sont remplacées
avant de recueillir un accord pour tous les sites.
`app/tools/tests/test_action_authorizations.py` vérifie l’accord permanent par fonction et
connexion, la reprise sans rejeu de l’action initiale et l’exécution suivante sans question.
Pour chaque fournisseur de harnais externe enregistré (Hermès, DeepSeek Harness, Codex,
Claude Agent et OpenAI Messages configuré), elle vérifie aussi l’accord par type d’action, la séparation
des harnais et des capacités, la reprise dans un autre contexte, la révocation et les changements
de configuration, d’affectation, de responsable et de version de politique. Les scénarios navigateur
`action-authorizations.spec.mjs` et `permissions.spec.mjs` couvrent le choix et sa révocation.
Le harnais interne est explicitement exclu de ces accords de runtime.
Elle couvre aussi le claim concurrent, le refus non répétable, l’expiration, les quotas,
la révocation du contexte ou de la configuration, les accords explicites et les préconditions des fichiers.
Les scénarios d’expiration comparent réponse tardive, nouvel appel et réconciliation :
ils libèrent une vraie tâche en attente sans exécuter l’action. L’annulation et le timeout
d’un outil natif après son envoi conservent un résultat incertain et interdisent son rejeu.
`app/voice/tests/test_conversation_service.py` vérifie qu’un accord ou un refus reçu avant
la suspension du tour reste à traiter, puis réveille ce tour après sa mise en attente.
`bridge/hermes/tests/test_executor_history.py` simule la disparition d’une exécution distante
à la reprise : l’attente se termine en erreur sans rejeu, en conservant les effets et coûts tracés.
Une copie reprend après un accord ponctuel ou permanent seulement si la source observée
est inchangée ; le changement de mode ne retire pas sa précondition.
Le choix permanent refuse une configuration MCP changée, y compris si le changement
survient entre la préparation de l'appel et la création de sa question.
Les routes HTTP réelles refusent le jeton système d'un runtime sans son contexte,
acceptent un contexte valide, refusent un contexte révoqué et conservent les clients MCP indépendants.
`app/connection/tests/test_function_modes_migration.py` prouve sur PostgreSQL la conversion
des anciens booléens, le rollback et le rejeu après un choix humain ultérieur.
`front/browser-tests/system-tools.spec.mjs` vérifie les trois choix à chaque niveau :
une exception locale décoche le groupe global sans le bloquer ; un choix global remet
cette connexion en héritage, y compris après réouverture sur desktop et mobile.
Il vérifie aussi les choix immédiats pendant une réponse retardée, leur sauvegarde
ordonnée, les lignes indépendantes, les refus et les réponses perdues après commit,
ainsi que les changements de connexion et la réouverture pendant une sauvegarde.
`app/connection/tests/test_connections.py` vérifie l'atomicité de cette sauvegarde,
la conservation des autres connexions et types de capacités, le refus d'un responsable
à périmètre limité et le rollback des deux effets après un échec du commit. Les appels
globaux sans option de remise en héritage conservent leurs exceptions locales.
La sauvegarde ne déclenche aucune redécouverte du catalogue. La recherche effective
reste filtrée et indexe les nouvelles fonctions visibles lors de la requête suivante
(`app/tools/tests/test_tool_search_service.py`). Le parcours assemblé
`e2e/specs/tool-authorizations.spec.mjs` retarde une réponse de la véritable API,
enchaîne les choix dans l’interface, relit les règles et exerce leurs effets via MCP.
`app/harnesses/tests/test_runtime_control.py` vérifie les appels suspendus, la réponse de claim
perdue et le redémarrage sans réexécution. Les workflows Mail et Process vérifient les permis
avant effet et la réconciliation après une issue inconnue.
`bridge/mail/tests/test_common_authorizations.py` vérifie aussi la copie du MIME accepté dans
Sent, sa réparation après panne IMAP ou perte de réponse APPEND et l'absence de second envoi
SMTP. `test_imap_client.py` couvre la relecture par Message-ID et la déduplication d'une copie
déjà créée par le serveur.
Il couvre les décisions Chat/journal, leurs appels concurrents, le refus des autres utilisateurs
et des décisions opposées, le rattachement idempotent des anciens liens par DbAdmin et la reprise
du MIME exact sans SMTP au moment de la décision. `e2e/specs/mail-approval.spec.mjs` exerce les
accords et refus communs depuis les deux interfaces ainsi que les anciennes validations Mail,
avec accès au détail et aux actions du journal sur mobile et bureau.
Seuls les transports externes et la continuation du runtime sont synthétiques.
`app/process/tests/test_common_authorizations.py` exerce le transport MCP et les transactions
réels : pause, révocation, changement de workflow, reprise après la fin de la Task,
réponse perdue et priorité d'un callback terminal sur une observation révoquée.
`bridge/deepseek_harness/tests/test_runtime_authorizations.py` exerce les routes HTTP
du runtime pour l'accord, le refus, la révocation et l'annulation, sans relancer le SDK.
`make tests-harness-runtimes` exerce les SDK embarqués Codex, Claude, Hermes et DeepSeek,
avec modèle et transports externes synthétiques : aucun effet avant accord, refus, reprise
de l’appel exact et continuation MCP. Cette qualification ne prouve pas un déploiement.
Les scénarios vérifient aussi les noms, arguments, retours, identités et échecs des outils
Codex, Claude et DeepSeek ; Hermes conserve son historique natif. Les tests de projection
Task et de reconnexion conservent des aperçus bornés et masqués sans modifier les reçus.
`execution.spec.mjs` exerce leur lecture et réouverture au clavier à 390 et 1280 pixels ;
le scénario Task de `e2e/specs/chat.spec.mjs` traverse WebSocket, rechargement et terminaison.
La réponse d’autorisation DeepSeek est retardée dans le transport synthétique : le test
attend l’état suspendu avant de répondre et annule les workers encore actifs en cas d’échec.
`test_runtime_adapter.py` impose un délai d'inactivité HTTP inférieur au temps d'attente humaine :
en-têtes immédiats, keepalives MCP et natifs, accord et refus tardifs, un seul appel et aucun
effet avant accord. La qualification SDK exerce aussi le vrai client MCP sur la réponse SSE,
avec un seul effet après la continuation et aucun après refus.
Les diagnostics ToolAdmin utilisent des serveurs HTTP/SSE synthétiques successifs et vérifient
les bornes du catalogue sans exécuter ses fonctions. Chaque serveur repart avec son indicateur
d'arrêt SSE réinitialisé, car la bibliothèque le conserve au niveau du processus de test.
`e2e/specs/tool-authorizations.spec.mjs` vérifie dans l’application assemblée l’accord et le
refus, la réouverture, le clavier, les accords explicites et les fonctions bloquées à 390 et 1440 pixels.
`front/browser-tests/action-authorizations.spec.mjs` couvre le choix permanent avec sa portée
explicite, les trois langues, le clavier, le mobile et le réessai après un refus HTTP.

`app/task/tests/test_agent_run_trace.py` protège le mouvement des arguments d'outils
sans résultat visible, son isolation par run et la préservation des reçus. `activity.test.mjs`
et le scénario de silence de `front/browser-tests/execution.spec.mjs` vérifient l'alerte après
inactivité, sa disparition au mouvement suivant et son absence pendant une attente déclarée
ou une consultation indisponible. Cette alerte n'interrompt aucune exécution.

Les scénarios de reprise du même fichier vérifient la commande manuelle, les erreurs et
refus, le blocage des doubles clics et l'isolation des réponses tardives après changement de
Task, run, tentative ou réouverture. `app/task/tests/test_call_recovery.py` couvre la commande
durable, ses versions, les droits HTTP et sa remise au seul propriétaire du lease courant.
`app/harness/tests/test_call_recovery.py` vérifie la fermeture de l'appel avant sa reprise,
les effets acquis et le budget conservés, ainsi que le refus d'interrompre un outil actif.
Le parcours de silence de `e2e/specs/chat.spec.mjs` exerce la discussion assemblée,
PostgreSQL, le scheduler et le harnais interne réels avec un fournisseur synthétique :
tentative courante conservée, même Task, appel fermé puis reprise guidée et résultat durable.

`app/conversation/tests/test_service.py` protège aussi les commandes humaines Pause, Stop,
Reprendre, Relancer et Répondre maintenant : tentative exacte, inputs conservés, suppression
du brouillon, round arrêté immuable et refus de reprendre des effets incertains.
Le scénario pause puis envoi conserve la demande initiale et le complément, reprend
automatiquement et couvre aussi un message reçu pendant la mise en pause.
Les tests de harnais vérifient que Répondre maintenant contourne le dispatcher et expose
zéro outil au modèle. `front/browser-tests/conversation-control.spec.mjs` exerce clavier,
doubles clics, erreurs réessayables, droits et réponses tardives sur les composants réels.
`front/app/chat/liveState.test.mjs` et `front/browser-tests/chat-recovery.spec.mjs`
protègent la disparition de la réponse arrêtée, même après des fragments tardifs et
réouverture, tout en conservant la demande humaine, la pause et une réponse dont l’arrêt
a été refusé. L’ancienne attente d’un bloc de réponse arrêtée réouvrable est retirée.
Les deux parcours de contrôle de `e2e/specs/chat.spec.mjs` utilisent Chat, PostgreSQL,
le scheduler et le harnais réels avec un fournisseur synthétique ; ils couvrent réouverture,
reprise, disparition après arrêt, nouvelle demande et reprise automatique après un complément.
L’action Répondre maintenant reste couverte côté API/harnais ; son bouton a été retiré du Chat.

L'admission par fournisseur est couverte par `app/llm/tests/test_provider_scheduler.py`
et `tests/test_inference_lifecycle.py` : priorité, places protégées, partage entre modèles
et appels natifs, changement à chaud, arrêt/pause/expiration en file, transcription vocale
sous charge et libération après annulation d'une transcription ou image native. Le test
de transport dans `tests/test_protocol_inference.py` compare les commits du journal,
préserve les grands fragments Unicode et conserve l'arrêt anticipé du raisonnement.
`front/browser-tests/provider-autosave.spec.mjs` vérifie sauvegarde de 0, réouverture,
validation et préservation des autres paramètres.

La stabilisation du journal et du streaming est couverte par
`back/app/agent/tests/test_reasoning_guard.py` (fragments irréguliers, snapshots rejoués,
absence de faux positif sur un mot découpé) et `back/app/incident/tests/test_capture.py`
(tentatives distinctes, clés historiques, diagnostic après rollback, enrichissement sans doublon
ni fuite dans le résultat MCP). Le scénario de récupération conversationnelle de ce même
fichier exige `SUCCEEDED` réellement persisté avant de marquer les incidents LLM/outils du
round comme récupérés. Il conserve ceux d’un autre run et refuse ce marquage en attente d’accord,
après interruption, remplacement, perte de lease, annulation, échec ou livraison incertaine.
Le test de protocole avec fournisseur suspendu vérifie que le texte SSE et sa supervision
arrivent avant la fin de la génération. Une régression dédiée vérifie la diffusion du dernier
fragment sans nouvel événement fournisseur, y compris pendant la limitation de fréquence.
`app/llm/tests/test_stream_performance.py` mesure les octets diffusés et requêtes SQL sur
de grands contextes synthétiques, borne la mémoire des traces et vérifie supervision lente,
fin immuable et réveils séparés. `front/browser-tests/stream-progress.spec.mjs` couvre les
deltas Unicode, leur rattrapage et les événements tardifs ; `storeCatchUp.test.mjs` conserve
tous les fragments d'une rafale avec une seule projection et annule le rendu après déconnexion.
Le regroupement des deltas consécutifs est comparé au traitement séquentiel pour Unicode,
fragments vides, raisonnement, outils, coûts, erreurs, doublons, trous, snapshots, resets,
tentatives et fin du stream. Les événements entrants et projections déjà publiées restent immuables.
`front/app/task/aiResult.test.mjs` conserve l'ordre des blocs lors de fusions de longues
traces, y compris les messages manquants, les identifiants d'outils modifiés et les mélanges
de messages historiques et identifiés. Le parcours Chat exige un fragment visible avant la fin.
`storeCatchUp.test.mjs` vérifie aussi le partage des seules lectures de contrôles encore
en cours, leur relance après erreur et leur isolation à la navigation, à la reconnexion,
au changement de session et aux transitions d'appel. Le navigateur conserve messages frais
et brouillon pendant ces lectures lentes, sans requêtes de commandes en doublon.
Les tests de rétention empêchent une observation tardive de
restaurer une trace expirée. `test_editorial_html.py` conserve le contenu et la révision après
refus de mutation ; `app/image/tests/test_image_mcp.py` conserve le rejet des URL privées et
le guidage vers l'URI canonique, sans contacter le fournisseur d'images.

Les aides contextuelles des écrans métier restent visibles jusqu’à une fermeture
explicite, mémorisée définitivement par compte et par aide. Les écrans courants et le
menu Préférences restent sans aide. Le Lab porte une explication de sa philosophie
uniquement sur son accueil ; `lab-access.spec.mjs` couvre cette distinction et le
journal des échecs sans aide. `core/user/tests/test_help_dismissals.py` prouve la persistance, l’isolation
des comptes et l’idempotence sur l’API réelle. `context-help.spec.mjs` couvre la croix,
« J’ai compris », réouverture, préférences préexistantes, erreurs et nouvelle tentative,
réponses tardives et changement de compte avec les composants Vue/Quasar réels.
Les textes restent dans les catalogues des domaines ; modifier une traduction ne
réinitialise jamais le statut « vu ».

`front/browser-tests/client-config.spec.mjs` couvre la génération Codex/Claude Code
depuis les jetons utilisateur : sélection de profils disponibles, copie sans secret,
profils incomplets, droits, états vide/erreur, réouverture et réponses tardives.
Le parcours utilise la vraie page et les composants Quasar sur mobile et desktop.

`back/tests/test_profile_gateway.py` vérifie que les références à des tâches,
modèles ou runs dans les résultats d'outils des clients externes restent du contenu
sur les API de profils OpenAI et Anthropic : streaming terminé, modèle conservé,
aucune corrélation déduite du texte. `test_anthropic_api.py` et
`test_call_router_lineage.py` préservent la corrélation des runtimes gérés.

Le nom du jeton API est figé dans les traces LLM : `test_profile_gateway.py`
couvre Messages, Chat Completions, Responses, embeddings et décisions, ainsi que
renommage/suppression, jeton sans nom et alternance avec une session navigateur.
`test_inference_lifecycle.py` vérifie sa transmission au worker sans hériter du
jeton d'un autre appel. `front/browser-tests/llm-calls.spec.mjs` couvre son affichage
et les appels historiques ou rattachés à un agent.

`tests/test_llm_call_trace.py` couvre aussi les fournisseurs Responses qui terminent les
arguments d’une fonction seulement dans un événement `done` : suffixe manquant ajouté une fois,
appels séparés conservés et préfixe contradictoire rejeté avant effet. Le scénario traverse
le proxy et le SDK Pydantic AI réels.

Le suivi des tâches pendant la génération d'arguments d'outil est couvert par
`app/harness/tests/test_message_fragments.py` et `test_executor_streaming.py` :
progression durable sans faux résultat d'outil, arrêt des flux silencieux et des deltas
vides. Le scénario de progression distingue texte, réflexion fragmentée et vrais outils :
les fragments de réflexion ne forcent pas une sauvegarde chacun et la clôture reste immédiate.
`app/agent/tests/test_message_contracts.py` conserve une occurrence par invocation dans
`tools_used`, même avec de nombreux fragments et plusieurs appels du même outil.
`app/dataset/tests/test_datasets.py` vérifie l'édition depuis une lecture JSON partielle,
les fins de ligne LF/CRLF/CR, la conservation du contenu voisin, les conflits et les droits.
`test_inference_lifecycle.py` vérifie sur PostgreSQL que les boucles de suivi,
les leases et le journal ne retransfèrent pas les requêtes complètes ; les scénarios
de reprise et `test_protocol_inference.py` préservent ordre, erreurs et comptabilité.
Le même scénario impose zéro requête pendant une fenêtre de silence, puis une livraison
sur notification ; il couvre plusieurs lecteurs et un commit entre lecture et attente.
`core/tests/test_commit_notifications.py` vérifie commits, savepoints et rollbacks.
`tests/test_scheduler_wakeups.py` vérifie les réveils après mutations durables, les délais
de retry et l'absence de scans des files au repos malgré une maintenance périodique.
Il vérifie aussi la prise en charge d'un round pendant une actualisation Chat qui
verrouille sa Room, sans rattrapage périodique. Le scénario de sérialisation dans
`app/conversation/tests/test_service.py` utilise des claims simultanés sur plusieurs
connexions et préserve les inputs du successeur.

Ces scénarios couvrent aussi l'arrêt propre pendant le dispatcher, l'historique, les pièces
jointes et la préparation d'une Task, ainsi que plusieurs expirations successives sans
épuiser le budget des véritables erreurs. Les checkpoints confirmés sont conservés ; un ancien
token, un journal incertain ou illisible et une livraison sans reçu ne permettent aucun rejeu.
Un reçu Messenger déjà persisté est rattaché sans renvoi. Les suites Harness de cancellation,
checkpoints et interruption vérifient la reprise de l'historique et l'absence de double effet.
`test_runtime_cancellation.py` utilise aussi un vrai serveur/client FastMCP : l'annulation
avant ou après effet conserve l'appel en attente ; sa reprise idempotente précède toute
nouvelle décision du modèle, conserve arguments et identité, sans rejouer les résultats
achevés du lot. Une mutation non idempotente sans reçu reste bloquée.

La structure documentaire de la #168 est couverte par
`back/app/memory/tests/test_document_structure.py` : une mémoire par PJ, conservation obligatoire
des descriptions d'images, projection sans modèle, dossiers visibles récursivement depuis les
documents autorisés et classements personnels séparés. Les scénarios utilisent une vraie base,
y compris des connexions concurrentes et un ancien travail Dream rejoué. `memory.spec.mjs`
vérifie l'invalidation d'une vue ouverte et le rejet d'une réponse antérieure à la révocation.

La [campagne du 12 septembre](../../../project/audits/2026-09-12-functional-regressions.md)
renforce les admissions et reprises de Process, la facturation et la livraison des médias,
la publication des évaluations, les sessions, les limites de ressources et la synchronisation
DbAdmin. Les défauts reproduits sont reliés à leurs scénarios et à des mutations exécutables
dans `project/regressions.json`.

Les chargements différés sont également vérifiés par `select-lifecycle.spec.mjs`
(fermeture/réouverture, réponses tardives, sélection enregistrée et révocation) et
`e2e/specs/deferred-tabs.spec.mjs` (onglets Connexions/Autorisations avec vraie API et DB,
sélection d'agent et conservation du filtre en revenant sur l'onglet, mobile et desktop).
Ce dernier reproduit aussi une réponse tardive de la bibliothèque Documents pendant le
chargement de la page suivante : la sélection automatique ne doit pas annuler la navigation.
Les répétitions E2E partagent une base isolée : les références créées portent des libellés
uniques, et les scénarios utilisent la recherche et la pagination pour retrouver leurs données.
Le driver local `internal`, quand sa définition est disponible, ne déclenche pas de
lectures d'état du superviseur. Les autres drivers restent inspectés, dont le driver
réseau commun aux runtimes Codex, Claude et DeepSeek. Une indisponibilité du catalogue
ne masque pas leur supervision ni sa reprise après erreur.
Les sélecteurs sans champ de recherche sont parcourus au clavier, y compris leurs options
virtualisées ; les civilités restent sélectionnables au-delà des 500 premières références.
Avant un rechargement volontaire, ils attendent les réponses HTTP concernées. Le collecteur
`e2e/page-errors.mjs` conserve les erreurs JavaScript et réseau ; il exclut une erreur XHR
native de WebKit uniquement si une annulation de la même requête est observée.
Son attente suit les événements de fin ou d'échec des requêtes en cours, puis les requêtes
déclenchées par leurs réponses, jusqu'à la fin de cette séquence. Elle exclut le long polling
Socket.IO et couvre aussi la navigation juste après connexion.
Lors d'une navigation complète, les requêtes du document quitté ne participent plus à
cette attente : une requête lancée pendant son remplacement peut disparaître sans événement
de fin. Les erreurs restent observées et les requêtes du nouveau document sont suivies.
Les parcours de crédits attendent chaque résultat visible ; ils n'attendent pas les lectures
de quota annulées au changement de fournisseur, tout en conservant l'observation des erreurs.
Les tests de push vérifient l'admission, la déduplication et les effets durables des réponses
du fournisseur (succès, abonnement disparu, refus et indisponibilité), avec une vraie DB.

| Usage | Garantie observable | Preuves principales |
|---|---|---|
| Message → tâche | La demande source et les pièces jointes survivent à une synthèse incomplète ; le contexte la complète sans historique aval. Une redelivery retrouve la tâche admise, sans doubler ni réécrire son objectif | `back/app/messenger/tests/test_journal.py`, `back/app/conversation/tests/test_task_admission.py`, `test_task_objective.py`, `test_service.py` |
| Approbation de dossier | La demande conserve la langue du chat ; le participant autorisé répond par numéro sans round LLM, ou par un choix interprété ; DbAdmin répare les anciens destinataires sans approuver | `back/app/dream/tests/test_topic_classification.py`, `back/app/messenger/tests/test_service_incoming.py`, `front/app/chat/services/chatService.test.mjs` |
| Tâche → conversation | Une fin durable livre son résultat une fois ; une reprise retrouve le message | `back/app/conversation/tests/test_service.py`, `e2e/specs/chat.spec.mjs` |
| Activité et reprise | Le résultat terminal du round prime sur les erreurs de tentatives ; une indisponibilité des choix ne révoque pas la sélection et une nouvelle recherche permet la reprise | `back/app/conversation/tests/test_monitoring_service.py`, `front/browser-tests/execution.spec.mjs`, `front/browser-tests/topics.spec.mjs` |
| Choix chargés à la demande | Les sélecteurs agents/sujets vides ne chargent rien avant ouverture ; une annulation, un changement d’agent ou une fermeture de formulaire ne produit pas de fausse erreur ; une panne réelle reste visible et permet une nouvelle recherche | `front/browser-tests/filter-loading.spec.mjs`, `front/browser-tests/goals.spec.mjs`, `front/browser-tests/topics.spec.mjs`, `front/core/api.test.mjs` |
| Process → tâche en attente | Un callback autorisé libère l’attente ; doublons et événements tardifs préservent résultat et erreur | `back/app/process/tests/test_recovery.py`, `test_worker_concurrency.py` |
| Process → humain → messagerie | Demande privée interne ou externe, réponse JSON simple convertie en valeurs typées, fichier seul avec URI source, échec de livraison repris, refus d'un autre auteur ou d'une réponse tardive ; aucun message sans rapport ne termine l'étape. Une activité IA attend sans Task auxiliaire, reprend même après une réponse rapide et conserve une pause utilisateur ; anciennes attentes retirées, doublons idempotents, Dataset et message final conservés | `back/app/process/tests/test_human_messaging.py`, `back/app/process/tests/test_activity_controls.py`, `back/app/harness/tests/test_conversation_prompt.py`, `e2e/specs/native-processes.spec.mjs` |
| Document → fichier → agent | Le contenu, sa révision, ses URI et ses ACL restent cohérents entre lecture et écriture | `back/app/memory/tests/test_editorial_html.py`, `back/app/file_share/tests/test_resource_service.py`, `e2e/specs/editorial-html.spec.mjs` |
| Datasets et compatibilité documentaire | Bibliothèques et créations séparées, identité native `data://`, JSON source préservé et erreurs sans nouvelle ressource/révision ; droits et historique propres, copie/restauration et conflits ; anciens alias et brouillons invalides préservés. Le parcours Datasets remplace la création Dataset dans Documents | `back/app/memory/tests/test_dataset_documents.py`, `test_document_library.py`, `back/app/dataset/tests/test_datasets.py`, `front/browser-tests/dataset-documents.spec.mjs`, `e2e/specs/dataset-documents.spec.mjs`, `e2e/specs/datasets.spec.mjs` |
| HTML interactif dans un document | Formulaires HTML directs vers Dataset partagé, ACL et accords personnels liés à la révision ; révocation, copie non autorisée entre Datasets, validation JSON et quotas entre workers ; texte éditable et barre habituelle, sans vue Source documentaire ; impression et PDF statiques avec filtrage des ressources ; isolation, WebRTC, saturation du pont et réponses tardives | `back/app/memory/tests/test_document_apps.py`, `front/browser-tests/document-apps.spec.mjs`, `e2e/specs/document-apps.spec.mjs` |
| Arrêt / reprise / concurrence | Un ancien worker ne remplace pas le propriétaire courant ; les effets ambigus ne sont pas rejoués aveuglément | `back/app/task/tests/test_active_lease.py`, `back/app/harness/tests/test_checkpoint.py`, `back/tests/test_durable_concurrency.py` |
| Accusé d’outil perdu | Une commande SSH reste unique après perte de réponse et relecture PostgreSQL ; un timeout MCP après effet bloque le rejeu ; le retry conserve le journal | `make tests-recovery`, `back/app/harness/tests/test_ssh_checkpoint_recovery.py`, `back/app/harness/tests/test_execution_evidence.py`, `back/app/console/tests/test_durable_operations.py` |

<a id="domains"></a>

## Domaines applicatifs

`app/harness/tests/test_conversation_interrupt.py` interrompt un vrai agent Pydantic AI
pendant une génération bloquée et vérifie qu'un outil déjà commencé termine une seule fois.
`test_conversation_prompt.py` couvre le branchement dans le contrôleur réel et la conservation
du brouillon dans sa trace. Les intégrations Conversation conservent les messages en rafale,
refusent un lease étranger et distinguent reprise sans effet et consommation après effet.
`app/tools/tests/test_mcp.py` distingue les fonctions autorisées mais absentes du run des
fonctions montées, en FR/EN, sans exposer les fonctions refusées. Le test du serveur agrégé
dans `test_mcp_loader.py` vérifie que cette découverte observe bien le serveur du run.

`app/tools/tests/test_tool_arguments.py` conserve la validation des arguments obligatoires,
types et objets imbriqués après retrait des clés inconnues d'un schéma fermé. Les tests MCP
du loader couvrent ce retrait sur les runtimes interne et Hermès, sans modifier la sortie
structurée ni exposer les valeurs ignorées. Les parcours d'autorisation et de ToolAdmin
conservent l'accord avant effet, la révocation et la rotation des credentials sur un appel
corrigé, y compris externe. `app/harness/tests/test_execution_evidence.py` vérifie que
l'avertissement atteint un vrai agent Pydantic AI et son checkpoint sans réexécuter l'effet.

`app/harness/tests/test_runtime_cancellation.py` reprend un véritable agent Pydantic AI après
accord ou refus en conservant les arguments et les consignes actualisées. Le compactage préserve
les appels à réessayer et les mutations refusent les marqueurs d'omission (`test_agent_history_compaction.py`,
`app/file_share/tests/test_resource_service.py`, `test_mcp_paths.py`). La délégation vérifie
les droits documentaires avant création (`app/memory/tests/test_document_sharing.py`) ;
`app/task/tests/test_collab.py` conserve l'identité des enfants de même libellé, attend leur
résultat avant réussite et consomme une seule fois leurs résultats lors de réveils concurrents.
Les autorisations décidées par API résolvent aussi le choix Chat, même déjà en traitement
(`test_action_authorizations.py`), et ses réponses conservent la langue (`test_native_facade.py`).
Les parcours documentaires exercent les photos natives dans la sandbox, le réessai après
refus et l'annulation des chargements d'une ancienne révision (`document-apps.spec.mjs`).

`app/conversation/tests/test_service.py` couvre l'arrêt conversationnel répété d'une Task
active, réussie ou en erreur : résultat, cause et révision terminaux sont conservés, et
la portée d'agent reste obligatoire. `app/tools/tests/test_mcp_loader.py` distingue un
refus HTTP 403 distant d'un refus local dans le diagnostic français/anglais, sans changer
la catégorie d'erreur utilisée pour les effets ni exposer URL ou réponse du fournisseur.

Les tests `app/harness/tests/test_execution_evidence.py` font poursuivre ou arrêter un
véritable agent Pydantic AI après des erreurs MCP, sans arrêt terminal imposé ni répétition
des effets lors de la reprise. Le même parcours couvre une exception, un échec explicite
en JSON texte ou structuré, son enveloppe d’avertissement et une erreur dont le diagnostic
texte accompagne un JSON incomplet. Les issues externes déclarées ne prouvent jamais un
rejet avant effet. `test_agent_history_compaction.py` borne aussi les longues collections
et les retours récents dépassant le contexte, conserve les contrôles de pagination et
laisse les résultats originaux et arguments d’appels en erreur intacts ; les aperçus portent
un marqueur refusé avant écriture. Les consignes falsifiées d’un MCP imitant le schéma
d’erreur de Galaris ne remplacent pas ses consignes de vérification.
`test_runtime_guards.py` conserve leur visibilité comme
erreurs. `app/file_share/tests/test_path_normalization.py` vérifie les écritures SFTP
vers des dossiers absents et le confinement dans le home. Ce contrat remplace l’arrêt
automatique sur erreur observée ; les interruptions sans réponse restent réconciliées.

Le contrat dispatcher du 16 septembre est couvert par `test_dispatcher_planning.py` et
`back/tests/test_dispatcher_inference.py` : un round humain produit `EXEC standard` sans appel LLM,
les pairs IA gardent leurs limites et les inférences v1 gelées restent rechargeables. Dans
`test_conversation_prompt.py` et `test_executor_streaming.py`, une réponse réussie sans outil ou
répétitive ne provoque aucun jugement ni relance ; l'exécuteur peut toujours admettre le travail.
Les anciens tests de rejet d'action/artefact et de comparaison de formulations sont retirés avec
ces contraintes. `test_action_guard.py` conserve les garanties de reprise sur erreur et de
livraison idempotente ; `test_scheduler.py` vérifie qu'un ancien verdict de garde ne contourne
plus l'exigence de checkpoint après un effet.

`test_conversation_protocol.py` bloque avant effet un lancement issu d'un faux échange,
conserve la véritable réponse humaine et autorise les citations explicites. Les tests
du filtre dans `test_conversation_context.py` couvrent le découpage du stream et les blocs
de code ; `test_conversation_prompt.py` vérifie que le texte affiché et enregistré reste
dans le tour courant. `test_runtime_instructions.py` inspecte les payloads Chat et Responses.
`app/conversation/tests/test_process_admission.py` vérifie les permissions Process persistées :
réponse sans lancement, paramètres exacts, multiplicité, reprise, concurrence et décision tardive.
Les scénarios de `test_activity_controls.py` conservent le parcours complet question,
réponse humaine, reprise et activité suivante.
Le lot suivant ajoute la matrice des capacités de chaque provider et l'application distincte
d'EXEC standard, EXEC high et PLAN. `test_dispatcher_inference.py` prouve la persistance
d'une décision de Task à choix unique sans appel LLM ; `test_registry.py` protège la reprise des
anciennes décisions. Le Lab contrôle les mêmes couples via `test_contracts_and_passes.py`.

Le corpus synthétique `back/app/lab/dispatcher_boundaries_corpus.json`, importable avec
`scripts/import_lab_reference.py --corpus dispatcher-boundaries --install`, oppose les lots
reprenables séparément aux documents uniques, chapitres liés, sites cohérents et petits lots
mécaniques. Il remplace l'ancienne assertion de formulation imposant toujours EXEC high en cas
de doute. La version v2 contient 15 cas, dont des objectifs globaux sans liste ni nombre
d'éléments : migration d'un carnet, restauration d'une bibliothèque et correction de périmètre
d'un fonds. Le routage attendu est PLAN lorsque ces demandes impliquent des livrables distincts
à découvrir. Les contre-exemples restent EXEC pour une synthèse unique issue de pages à découvrir
ou un petit renommage mécanique après inventaire. L'import crée un nouveau dataset v2 sans
écraser les campagnes v1 ; aucun prompt de dispatcher n'est modifié par ce corpus.
`test_reference_corpus.py` vérifie son import autorisé, sa persistance et ses contrats ;
ces tests ne mesurent pas le routage du modèle. Comparer les prompts avant/après dans le Lab avec
le même modèle et plusieurs répétitions, en examinant séparément les PLAN manqués et les PLAN
abusifs, notamment sur les documents uniques.

La matrice durable du dispatcher couvre FR/EN et Chat/Responses avec le SDK réel, une base
isolée et le seul transport fournisseur simulé. Une sortie sans route suivie d'une correction
valide conserve les deux sorties dans le journal, mais seule la correction fixe langue et
effort. Un pair IA conserve sa politique sans retry : une sortie invalide entraîne `END`
dans la langue du contexte. Une sortie valide sans champs facultatifs conserve les défauts
historiques `standard` et `en`. La relecture restitue le même résultat validé sans nouvel
appel, avec les coûts et corrélations de chaque tentative physique. Cela ne qualifie ni les
comptes réels ni plusieurs objets concurrents dans une même réponse fournisseur.

`back/app/agent/tests/test_prompt_tree.py` vérifie que la politique de révision documentaire
atteint les exécuteurs Task, texte et voix, même avec une personnalité personnalisée et sans
skill chargé. Cette preuve porte sur la transmission des consignes ; elle ne mesure pas la
qualité éditoriale d'un modèle après plusieurs mises à jour du même document.

Les fichiers `test_*.py` ci-dessous se trouvent sous `back/app/<module>/tests/`, sauf chemin
explicite. Les fichiers `*.spec.mjs` se trouvent sous `front/browser-tests/`.

| Module | Usage et risques à protéger | Suites à conserver ou renforcer |
|---|---|---|
| `agent` | Choisir un agent autorisé, appliquer sa politique, produire un résultat terminal cohérent | `test_management_scope.py`, `test_facade.py`, `test_executor_lifecycle.py`, `agents.spec.mjs` |
| `harness` | Exécuter outils et streaming, reprendre sans répéter les effets, libérer les ressources | `test_checkpoint.py`, `test_runtime_cancellation.py`, `test_executor_streaming.py` |
| Chargement des compétences | Charger les seules compétences autorisées selon leur configuration, indépendamment de l'identité de l'agent ; découvrir et charger les modèles associés en conversation texte et voix par tours, préserver les révocations et le repli sur configuration invalide | `app/harness/tests/test_skills.py`, `app/harness/tests/test_conversation_prompt.py`, `app/harness/tests/test_executor_streaming.py` |
| Frontière des harnais | Refuser les résultats et événements invalides avant publication, fermer les flux, respecter les capacités déclarées | `make tests-harness-contracts`, `app/agent/tests/test_driver_boundary.py` |
| Politique des harnais | Même configuration pour tous, conflits SQL, restriction des outils à l’appel, checkpoints opaques et retry sûr | `test_execution_configuration.py`, `test_checkpoint_contract.py`, `harness-policy.spec.mjs` |
| Réessai par driver | Journal d'effets interne conservé ; réessai réseau géré explicite avec nouvelle inférence, mêmes paramètres Task et reçus archivés, pour Tasks simples et plans ; arrêt ou observation de l'ancien acteur avant nouvelle autorité ; récupération automatique par observation du même acteur sans nouvelle soumission | `back/app/task/tests/test_task_service.py`, `back/app/harnesses/tests/test_checkpoint_recovery.py`, `back/app/agent/tests/test_checkpoint_contract.py`, `back/app/tools/tests/test_action_authorizations.py` |
| SDK réels des harnais | Exécuter dans les quatre images épinglées avec modèle local ; vérifier la connexion MCP DeepSeek | `make tests-harness-runtimes`, `artifacts/harness-runtimes/summary.txt` |
| `harnesses` | Changer de runtime sans perdre une tâche active ; révoquer/configurer selon les droits | `test_service.py`, `test_runtime_actions.py`, `test_router.py`, `configuration.spec.mjs` |
| `task` | Créer, suspendre, reprendre, terminer et supprimer une tâche ; préserver budget et propriété du lease | `test_task_service.py`, `test_workflow.py`, `test_active_lease.py`, `test_budget.py`, `task-panel.spec.mjs` |
| Nouvelle demande après échec | Conserver la relance conversationnelle délibérée et manuelle ; une création indépendante préserve l'état, l'erreur et le résultat de la tâche échouée et reste idempotente. Le choix sémantique entre relance et création relève des consignes du modèle | `back/app/tools/tests/test_mcp_loader.py`, `back/app/conversation/tests/test_service.py`, `back/app/task/tests/test_task_service.py` |
| Working Set Task | Conserver les ressources racine/enfants, checkpoints et première capsule lors de commits concurrents ; enregistrement idempotent et rollback avec l'appelant | `back/app/task/tests/test_working_set.py` (sessions PostgreSQL indépendantes) |
| Preuves de livraison Task | Refuser les faux succès avec un autre fichier, une autre destination, une autre Task ou un fichier périmé ; préserver les reçus natifs, la livraison Conversation, l'URI exacte sur place et la reprise sans envoi en double | `back/app/agent/tests/test_planner_service.py`, `back/app/agent/tests/test_executor_lifecycle.py`, `back/app/tools/tests/test_resource_effects.py` |
| Amendement conversationnel | Tolérer les seules révisions techniques avec une définition connue ; refuser avant interruption un checkpoint incompatible ou une exécution sans point de reprise vérifiable, même apparus après lecture ; préserver la cible et permettre une création indépendante explicite et idempotente dans le même document | `back/app/task/tests/test_amendment_service.py`, `back/app/conversation/tests/test_service.py`, `test_task_admission.py`, `back/app/agent/tests/test_checkpoint_contract.py`, `back/app/agent/tests/test_realtime.py` |
| Remplacement explicite | Enregistrer un seul successeur texte/voix, attendre le nettoyage ou une preuve d'arrêt valide, reprendre après changement de worker, préserver les autres pauses et tâches ; bloquer sur une relance, une coordination ou un changement de contexte du prédécesseur | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `back/app/agent/tests/test_driver_boundary.py` |
| Propriétaires et événements tardifs | Refuser le renouvellement d'un lease expiré ; ne pas remplacer le round affiché à partir d'un événement d'un autre round, demander une réconciliation serveur | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `front/app/chat/runtimeState.test.mjs` |
| Rattrapage Chat | Préserver la conversation courante face aux succès/refus HTTP tardifs ; conserver une réponse utile si une requête plus récente échoue ; réarmer les trous de stream pendant HTTP et après changement de sélection ; une révocation courante purge toujours le contenu | `front/browser-tests/chat-recovery.spec.mjs` (page et store réels, frontière HTTP remplacée) |
| Caches client et avatars | Mutualiser cinquante bulles et les écrans consommateurs ; borner taille et durée ; séparer les endpoints autorisés ; invalider après mutation/session ; préserver les autres lecteurs après annulation ; mutualiser les sélecteurs sans conserver les listes | `front/browser-tests/chat-avatars.spec.mjs`, `front/browser-tests/avatar-cache.spec.mjs`, `front/core/util/sessionReadCache.test.mjs` |
| Lectures et PJ du chat | Mutualiser les acquittements, avancer vers le dernier message visible sans parallélisme, permettre le réessai et isoler les sélections/sessions ; différer les PJ hors écran, partager deux transferts, conserver les aperçus chargés, annuler les anciens contextes et préserver ouverture, téléchargement et réessai | `front/app/chat/storeCatchUp.test.mjs`, `front/browser-tests/attachment-previews.spec.mjs` |
| Récupération des envois du chat | Conserver texte et PJ après coupure, réessayer un envoi inchangé avec la même identité et les mêmes URI de PJ, accepter un reçu canonique malgré la perte de réponse HTTP ; libérer la saisie après le POST sans attendre le rafraîchissement et préserver un nouveau brouillon ou une autre conversation lors d’un reçu tardif | `front/browser-tests/chat-recovery.spec.mjs`, `front/browser-tests/chat.spec.mjs`, `back/app/messenger/tests/test_journal.py` |
| Coût du fil de chat | Une rafale d’activité ne recharge pas la liste des conversations, mais une invalidation de message concurrente et une reconnexion le font ; les dates partagent leur formateur par langue ; les longs textes préservent Unicode, liens et code sans créer un nœud par caractère | `front/app/chat/storeCatchUp.test.mjs`, `front/browser-tests/chat-recovery.spec.mjs`, `front/browser-tests/presentation.spec.mjs` |
| Sélection des agents | Trier les réponses API par prénom puis nom avant pagination, conserver les droits ; reprendre le dernier choix non nul entre Mémoire et Contacts et dans le sélecteur partagé, sans remplacer un choix explicite ni restaurer un agent indisponible ; effacer la préférence au changement de session | `back/app/agent/tests/test_agents.py`, `test_selection.py`, `front/browser-tests/agent-selection.spec.mjs`, `select-lifecycle.spec.mjs` |
| Catalogues partagés | Réutiliser agents, titres, groupes et paramètres entre ouvertures ; relire après F5, expiration, sauvegarde ou rafraîchissement forcé ; isoler les brouillons et ignorer les réponses supplantées | `front/browser-tests/agents.spec.mjs`, `front/app/agent/agentStore.test.mjs`, `front/app/agent/services/agentService.test.mjs`, `front/core/params/paramsStore.test.mjs` |
| Interruption et reconnexion Chat | Une correction supplante le round en cours ; les deux entrées et une seule réponse finale restent visibles après fin hors ligne puis rechargement, sur les trois moteurs de navigateur | `e2e/specs/chat.spec.mjs` (stack complète, contrôleur scripté à son port public) |
| Commandes conversationnelles | Conserver la demande entière lorsque l'arrêt nécessite une interprétation ; arrêter immédiatement une cible unique sur commande simple ; les demandes de fichiers et le contexte documentaire passent au modèle sans envoi lexical ; une préparation supplantée conserve les entrées sans effet | `back/app/harness/tests/test_conversation_prompt.py`, `back/app/conversation/tests/test_service.py` |
| Préparation conversationnelle | Interrompre dispatcher/objectif sans consommer les entrées ni admettre une Task obsolète ; arrêter l'inférence possédée et conserver les ressources utiles de reprise | `back/app/conversation/tests/test_service.py`, `test_scheduler.py`, `test_task_objective.py`, `back/app/harness/tests/test_conversation_interrupt.py`, `back/tests/test_structured_inference.py` |
| `goal` | Suspendre/reprendre un objectif, respecter son calendrier, juger les cycles et conserver leur filiation | `test_goal_runner.py`, `test_goal_settings.py`, `test_referrer_wait.py`, `goals.spec.mjs`, `schedule.spec.mjs` |
| `messenger` | Admettre, dédupliquer, router et livrer dans la bonne conversation et connexion | `test_journal.py`, `test_ingest.py`, `test_interactions.py`, `test_mcp_routing.py`, `test_mcp_files.py` |
| `conversation` | Préserver contexte, admissions, résultats, notifications et résolution sans renvoi d’effets | `test_service.py`, `test_task_admission.py`, `test_delivery_resolution_http.py`, `e2e/specs/reliability.spec.mjs` |
| `chat` | Envoyer, archiver/restaurer, retrouver le streaming, isoler salons/utilisateurs et répondre aux choix sans LLM (boutons, reprise, expiration) | `test_authorization.py`, `test_events.py`, `test_native_facade.py`, `chat.spec.mjs`, `chat-interactions.spec.mjs`, `e2e/specs/chat.spec.mjs` |
| Chat et document | Ouvrir et modifier dans l’éditeur complet ; enregistrer avant l’envoi et transmettre l’URL au prompt seulement si le document est affiché ; conserver sélection et curseur après passage au champ de message, transmettre un extrait borné de la zone visible et invalider les repères obsolètes, en HTML ; préserver le brouillon en cas d’échec ; réserver le panneau intégré au desktop (≥ 1024 px), avec ses commandes dans la barre du titre du document ; ouvrir une modale sur mobile ; redimensionner les deux dispositions desktop à la souris, au toucher et au clavier sans perdre l’édition ; garantir au document en colonne au moins 560 px, avec passage automatique en disposition empilée si la place manque ; garder la colonne de droite visible sur desktop et conserver contenu et discussion après reconnexion | `front/browser-tests/chat-document-workspace.spec.mjs`, `back/app/conversation/tests/test_service.py`, `back/app/chat/tests/test_native_facade.py`, `back/app/memory/tests/test_document_library.py`, `back/app/memory/tests/test_document_grants.py` |
| `voice` | Démarrer/annuler un appel, traiter le tour dans le bon canal, fermer les médias | `test_session.py`, `test_multichannel_routing.py`, `test_realtime_engine.py`, `voice.spec.mjs` |
| `memory` | Rechercher, créer et restaurer les souvenirs privés et les documents ; partager les documents sans perte de contenu, de révision ni de droits | `test_document_library.py`, `test_document_grants.py`, `test_editorial_html.py`, `test_semantic_search.py`, `memory.spec.mjs` |
| Séparation documents/mémoire | Sauvegarder avant expansion, vérifier l'archive immuable, transférer depuis celle-ci puis retirer les colonnes uniquement après validation ; conserver l'archive et ses ressources après oubli ; préserver contenus, URI, historiques et droits après rollback et rejeu ; distinguer contenu documentaire et synthèse, leurs révisions et l’ancienneté ; rechercher les deux dans un seul résultat et masquer les deux après révocation ; conserver les souvenirs autonomes privés sans titre éditable ; ouvrir, sauvegarder, supprimer et miniaturiser le contenu documentaire complet via son contrat distinct, même avec une synthèse vide | `back/app/memory/tests/test_document_split.py` (PostgreSQL et Atlas réels), `test_document_retrieval.py`, `front/browser-tests/memory.spec.mjs`, `document-deletion.spec.mjs`, `document-resources.spec.mjs`, `document-thumbnails.spec.mjs`, `execution.spec.mjs`, `e2e/specs/editorial-html.spec.mjs`, `file-indexing.spec.mjs`, `session-races.spec.mjs` |
| Retrait des types de mémoire | Nettoyer les champs système sans modifier mots-clés, contenus JSON, valeurs testées ou expériences Lab d'autres mécanismes ; préserver rollback et idempotence | `back/tests/test_memory_snapshot_normalization.py` |
| Actions Dream à la demande | Déclenchement manuel indépendant du scheduler ; propriété et droits ; brouillons et éditions concurrentes préservés ; régénération des miniatures existantes des fichiers, pièces jointes et documents HTML ; ancien cache conservé après échec ; résultats en toasts, relance et réponses tardives sur mobile/bureau | `back/app/memory/tests/test_manual_dream.py`, `test_file_catalogue.py`, `test_document_thumbnails.py`, `front/browser-tests/memory.spec.mjs`, `e2e/specs/memory-graph.spec.mjs` |
| Recherche mémoire unifiée | Liste réunit souvenirs sans date filtrés par pertinence et correspondances temporelles indépendantes ; les souvenirs datés hors période ne passent pas par le rappel ordinaire ; pagination et tri après filtrage ; ouverture et oubli des résultats, repli lexical explicite | `test_browse_filters.py`, `test_semantic_search.py`, `front/browser-tests/memory.spec.mjs` |
| Admission mémoire robuste | Chaque occurrence garde sa propre révision et son chemin : un résultat valide ne réadmet pas un extrait ou un chemin obsolète du même UUID, quel que soit l'ordre des pages ; les occurrences valides répétées gardent leur ordre d'entrée et chaque liaison du chemin doit rester acceptée ; la recherche paginée conserve l'extrait de la révision actuelle. Une collision des noms anonymes SQLAlchemy ne fait pas échouer le rappel ; les souvenirs propres et les documents partagés restent accessibles, les souvenirs privés d'un autre agent restent exclus | `test_recall_admission.py`, `test_document_structure.py`, `test_file_catalogue.py` |
| Benchmark mémoire apparié (opt-in) | Versions figées sur les mêmes fixtures synthétiques ; admission courante ou de référence cohérente jusqu'au brief ; état réinitialisé et ordre alterné ; rappel retrouvé/injecté, erreurs, latence et SQL ; lots jusqu'à 500 résultats sur 6 000 souvenirs, révisions et chemins invalidés volontairement | `back/tests/test_memory_benchmark_campaign.py`, `back/tests/test_memory_admission_benchmark.py`, protocole : `back/scripts/memory_benchmark/README.md` |
| Preuves du rappel conversationnel | Noms et surnoms avec accents composés/décomposés ou formes Unicode compatibles ; projection actualisée à l'édition ; nom complet distinct de mots répartis entre plusieurs personnes ; profils et événement présents dans un petit budget, jusque dans le contexte préparé ; rôles de plusieurs personnes conservés ; cible indirecte et relation en rappel lexical/hybride sans contourner accès, contact, validité ou temporalité ; répétitions rétrogradées sans perdre chiffres, dates ou contradictions | `test_document_retrieval.py`, `test_recall_admission.py` |
| Temporalité mémoire | Dates partielles dans le fuseau global Galaris et changements d'heure ; nettoyage des anciens fuseaux sans perte de dates, d'historique ni d'acquisition ; correction, droits et portée contact ; contexte sans requête, pagination et budget ; recherche à date cible combinée aux filtres, parcours HTTP et refus d'accès ; filtre obligatoire dès la première recherche, saisie et affichage indépendants du fuseau du navigateur, reprise après erreur sur mobile/bureau | `back/app/memory/tests/test_temporal.py`, `back/app/memory/tests/test_browse_filters.py`, `front/browser-tests/memory.spec.mjs`, `e2e/specs/memory-temporal.spec.mjs` |
| Miniatures des documents | Réutiliser l’instantané d’impression et ses images pour la première page entière ; produire un WebP sans perte de 320 × 320 maximum, avec proportions conservées ; enregistrer `Document.thumbnail_id` et conserver un seul fichier courant, sans JSON ni historique de miniatures ; nettoyer les anciens caches ; invalider le pointeur après modification et refuser les captures tardives ; revérifier les droits sans relire le contenu ni l’historique ; différer les aperçus hors écran, borner les chargements et annuler les travaux obsolètes sans empêcher l’ouverture du document | `back/core/preview/tests/test_thumbnails.py`, `back/app/memory/tests/test_document_thumbnails.py`, `front/browser-tests/document-thumbnails.spec.mjs`, `front/core/util/previewQueue.test.mjs`, `browser-executor/pdf.test.mjs` |
| Miniatures Office et tableurs | Convertir la première page des fichiers Office et la première page imprimée des tableurs ; éviter OCR et extraction analytique ; séparer les checkpoints de l’analyse complète ; préserver l’original, les droits et le cache partagé ; reprendre après échec et nettoyer les temporaires après annulation ; afficher et télécharger sur desktop et mobile, y compris après réouverture ; proposer uniquement le téléchargement de l’original sans plein écran pour les formats sans lecteur, dans les pièces jointes, fichiers indexés et discussions | `back/app/memory/tests/test_document_thumbnails.py`, `front/browser-tests/document-thumbnails.spec.mjs`, `attachment-previews.spec.mjs`, `e2e/specs/office-thumbnails.spec.mjs` |
| `contact` | Périmètre agent et `MEMORY_EDIT` ; nom unique, regroupement par sélection/fusion et scission atomique sans suppression d’identité, avec conservation de l’historique ; création de contacts mail indépendants des utilisateurs/agents, validation et doublons concurrents ; rollback des projections lors d’une erreur de scission ; rejet du rattachement direct par API ; Chat interne représenté uniquement par l’utilisateur Galaris et nettoyage idempotent ; brouillon, annulation, reprise et réponses tardives sur mobile/bureau | `test_service.py`, `test_router.py`, `app/memory/tests/test_messenger_contact.py`, `app/memory/tests/test_source_projection.py`, `front/browser-tests/contacts.spec.mjs` |
| `topic` | Classer et retrouver les sujets, rechercher au-delà de la première page, ignorer les réponses obsolètes | `test_service.py`, `test_router.py`, `test_sequential_detection.py`, `topics.spec.mjs` |
| `dream` | Extraire/relier des connaissances sans réécrire le contenu existant, reprendre les traitements | `test_memory_extraction.py`, `test_claim_timeout.py`, `test_skill_learning.py` |
| `skill` | Créer/lire une procédure, préserver fichiers et permissions, appliquer les décisions d’apprentissage | `test_service.py`, `test_storage.py`, `test_learning.py`, `skills.spec.mjs` |
| `process` | Lancer, suivre, annuler et reprendre un traitement externe ; préserver ses états terminaux | `test_recovery.py`, `test_process_core.py`, `test_router_scope.py`, `test_worker_concurrency.py`, `execution.spec.mjs` |
| `tools` | Découvrir les outils autorisés, refuser les accès interdits, masquer les secrets ; révocation avant effet dans un serveur natif déjà monté, réactivation et isolation entre agents | `test_admin_access.py`, `test_agent_registry.py`, `test_secrets.py`, `test_resource_effects.py`, `test_live_authorization.py` |
| API REST des Tools | Héritage et surcharge des identifiants, connexion active propre à l'agent, modes d'authentification, erreurs HTTP, redirections, limites de taille et timeout ; sauvegarde, réouverture et désactivation du formulaire desktop/mobile et parcours assemblé avec identifiants masqués | `app/tools/tests/test_rest.py`, `front/browser-tests/system-tools.spec.mjs`, `e2e/specs/tools-rest.spec.mjs` |
| Recherche Web | Préserver requête, encodage, ordre et langue configurée ; distinguer recherche vide, partielle, dégradée et échec ; conserver les sources valides, masquer les exceptions brutes et annuler le transport sans bloquer la boucle | `back/app/tools/tests/test_search.py` (frontière HTTP remplacée, client et outil réels) |
| Paramètres d’indexation des Tools | Configurer `tools.fileindexing` par Tool et par connexion avec héritage, surcharge, valeur imposée et limites du provider ; reprendre les anciennes préférences sans les réappliquer ; respecter la valeur effective dans les recherches et le parcours automatique ; enregistrer depuis la Console embarquée et reprendre après erreur ; traduire les libellés internes dans les trois langues | `back/app/tools/tests/test_file_indexing.py`, `back/app/memory/tests/test_file_catalogue.py`, `front/browser-tests/tool-parameters.spec.mjs`, `e2e/specs/tool-parameters.spec.mjs` (desktop/mobile) |
| Administration ToolAdmin | Tester/créer un candidat sans fuite de secret dans le modèle ou les checkpoints ; connexion initialement inactive, héritage, atomicité, conflits, dépendances et interdiction d’auto-délégation ; révocation et rotation sur les anciens clients FastMCP/Pydantic AI ; rafraîchissement massif retournant ses résultats directement, avec droits revérifiés et processus métier préservés | `back/app/tools/tests/test_tool_admin.py`, `test_admin_network.py` ; `e2e/specs/tool-admin.spec.mjs` (application assemblée, clavier, fermeture et réouverture, desktop/mobile) |
| Disponibilité de la recherche | Un HTTP 200 sans sources ne valide pas le diagnostic ; une dégradation conserve les sources et produit un verdict distinct | `back/app/tools/tests/test_search.py` ; `make check-search` pour le corpus externe volontaire, avec relecture humaine de la pertinence |
| Mise à jour des images d'infrastructure | Récupérer les images déclarées, dont SearXNG, en dev et prod avant le build et le redémarrage ; un téléchargement échoué laisse les services actifs et fait échouer la commande | `make tests-update` (recettes Make réelles, frontière Docker remplacée) |
| `document_show` (Conversation) | Exposer l'outil uniquement dans le chat interne autorisé, indépendamment de la connexion Memory, en appliquant les refus de fonction du service système ; vérifier l'accès au document et les révocations ; ouvrir et rouvrir la visionneuse sans perdre les brouillons ni appliquer une demande à une autre conversation | `back/app/memory/tests/test_document_show.py`, `front/browser-tests/chat-document-workspace.spec.mjs` |
| `connection` | Activer/configurer une connexion et ses fonctions sans exposer ses secrets ou un autre agent | `test_connections.py`, `test_encryption.py`, `test_function_states.py` |
| OAuth MCP | Retour direct localhost, CIMD/DCR et négociation du secret client, client pré-enregistré en repli, PKCE, chiffrement, retour unique et expirant, isolation et refus HTTP ; code d’appareil avant le relais, intervalle/slow_down, refus terminal et jeton tardif après déconnexion ; clients HTTP/SSE réels ; relais téléchargé sur un vrai port HTTP, contrôles Host/state, expiration et port occupé ; parcours navigateur desktop/mobile, nouvel onglet, erreurs et annulation au changement de connexion | `app/connection/tests/test_mcp_oauth.py`, `app/connection/tests/test_oauth_loopback.py`, `front/browser-tests/mcp-oauth.spec.mjs` |
| `mcp` | Exposer les capacités et propager l’identité d’exécution dans les outils | `back/tests/test_realtime_security.py`, `back/app/tools/tests/test_mcp.py`, `back/core/authorize/tests/test_guard_provider.py` |
| `file_share` | Lire/copier/modifier via URI canonique, respecter ACL et limites, nettoyer les temporaires | `test_resource_service.py`, `test_transport.py`, `test_web_transport.py`, `test_galaris_provider.py` |
| Fichiers internes et migration | Déplacer uniquement les octets internes avec empreintes vérifiées et reprise après interruption ; préserver mémoire, documents, historiques, journal et anciens liens ; ne jamais ouvrir un fournisseur externe ; effacer une PJ devenue inutile sans supprimer un fichier encore référencé ; reprendre une purge interrompue sans réutiliser son UUID | `back/core/storage/tests`, `back/app/memory/tests/test_managed_files.py`, `test_service.py`, `back/app/file_share/tests/test_managed_http.py`, `e2e/specs/office-thumbnails.spec.mjs` |
| Nextcloud fichiers | Préserver les noms réservés, parcourir au-delà de 500 entrées, rejeter les écritures concurrentes, conserver une source modifiée pendant un déplacement, refuser les suppressions de dossiers et les faux succès OCS | `back/bridge/nextcloud/tests/test_file_share.py` : vraie façade et vrai client, serveur HTTP synthétique |
| Samba fichiers | Énumérer les partages accessibles, parcourir, lire, éditer et transférer des fichiers ; rejeter les conflits de version et les comptes sans droit d'écriture ; confiner la racine | `back/bridge/samba/tests/test_file_share.py`, `test_share_rpc.py` ; `make tests-samba` lance un vrai serveur Samba isolé |
| `console` | Exécuter dans le périmètre autorisé et transporter les fichiers sans traversée de chemin | `test_console.py`, `make tests-executor` |
| `browser` | Naviguer et restituer une ressource avec sessions, limites et erreurs explicites ; codes publics bornés, expiration sans rejeu automatique et nouvelle ouverture possible | `test_service.py`, `test_mcp.py`, `make tests-browser` |
| `llm` | Résoudre fournisseur/modèle, préserver paramètres fonctionnels, budgets et droits, conserver trace et coûts ; pause/reprise, relecture et protection contre les écritures tardives | `test_subscription_policy.py`, `test_structured_service.py`, `test_call_lineage.py`, `back/tests/test_provider_catalog.py`, `back/tests/test_provider_parameters.py`, `back/tests/test_inference_lifecycle.py`, `back/tests/test_protocol_inference.py`, `back/tests/test_structured_inference.py`, `back/tests/test_dispatcher_inference.py`, `execution.spec.mjs` |
| Consommation et crédits fournisseurs | Lire fenêtres, budgets et soldes avec les droits fournisseur, sans exposer les identifiants ; afficher les crédits supplémentaires ChatGPT à côté des fenêtres sans jauge de solde ; préserver unités, portée compte/clé, zéro et dépassement ; ne pas fabriquer de jauge sans plafond ; ne pas afficher de panneau de solde ou de consommation Fireworks ; actualiser et ignorer les réponses obsolètes ; masquer les clés enregistrées, conserver une clé omise et supprimer explicitement chaque clé après confirmation ; désactiver le fournisseur si la clé supprimée est obligatoire ; préserver les saisies après une erreur ; chiffrer, remplacer et supprimer la clé de gestion OpenRouter sans changer la clé d’inférence | `back/bridge/openai/tests/test_quota.py`, `back/app/llm/tests/test_provider_quotas.py`, `front/browser-tests/provider-quota.spec.mjs`, `front/browser-tests/provider-autosave.spec.mjs`, `e2e/specs/provider-usage.spec.mjs` |
| `audio` | Lire/transcrire un média canonique et livrer son résultat sans perte ni fuite de fichier | `test_audio_mcp.py`, `test_audio_service.py`, `test_summary_service.py` |
| `image` | Générer/lire des images et conserver ressources et traçabilité de l’appel | `test_image_mcp.py`, `test_image_service_trace.py` |
| Entrées multimodales natives | Fournir images, audio, vidéo et PDF au modèle compatible ; conserver provenance, droits, budget et médias à la reprise, sans outil d'analyse préalable | `app/harness/tests/test_native_media.py`, `test_media_resource_policy.py`, `tests/test_pydantic_ai_internal_model.py`, `app/messenger/tests/test_ingest.py` |
| `multimedia` | Lancer et suivre les générations par les tools MCP, suivre les générations longues, authentifier les callbacks et publier les médias | `test_multimedia.py`, `test_callback_security.py`, `test_providers.py` |
| `lab` | Isoler les jeux/items, conserver les paramètres, appliquer droits et deux passes ; reprendre les répétitions sans doublon, arrêter au budget et conserver les revues indépendantes avant révélation du juge ; générer des jeux synthétiques complets, propres à chaque contrat et à relire, sans écraser un jeu ni une saisie en cours ; afficher les aperçus sans HTML en conservant les entrées originales, les pourcentages par résultat et la moyenne indépendante du filtre, en excluant les notes absentes et en comptant les zéros | `test_authorization.py`, `test_contracts_and_passes.py`, `test_run_publication.py`, `test_stability_and_review.py`, `test_synthetic_datasets.py`, `lab.spec.mjs`, `lab-access.spec.mjs`, `lab-insights.spec.mjs`, `lab-synthetic.spec.mjs` |
| Comparaison Lab | Lire deux évaluations de chacun des dix Labs avec les droits du mécanisme ; préserver scores nuls et absents, incompatibilités et manquants ; bilan global indépendant de la page distinguant cas/répétitions, jugements absents et erreurs ; ambiguïtés sur les deux runs complets ; retrouver les régressions critiques et par critère hors page malgré un meilleur score global ; médianes appariées et effectifs ; navigation sans réponse périmée | `app/lab/tests/test_comparison.py`, `app/lab/tests/test_mcp.py`, `lab-comparison.spec.mjs` |
| Campagne Lab délai/coût/qualité | Importer les quatre parcours synthétiques FR/EN sans appel de modèle ni écrasement ; exécuter leurs outils simulés ; mesurer la première sortie texte/outil en poursuivant le flux jusqu'au résultat ; préserver coût, durée et mesure après rejugement | `app/lab/tests/test_reference_corpus.py`, `app/llm/tests/test_structured_service.py`, `app/lab/tests/test_contracts_and_passes.py` |
| Première sortie utile | Ignorer raisonnement, décisions internes et texte vide ; conserver les mesures initiales après reprise ; ne compter qu'une fois les appels simultanés ; preuve absente inconnue et portée agent conservée | `app/llm/tests/test_timing.py`, `app/task/tests/test_activity_snapshot.py`, `app/conversation/tests/test_monitoring_service.py`, `execution.spec.mjs` |
| Continuité documentaire ancienne | Retrouver l'URI après cinquante échanges sans document, avec titre/révision actuels et provenance ; exclure autre contact, document interdit, absent ou supprimé | `app/conversation/tests/test_context.py` |
| MCP Lab | Piloter les dix contrats avec le catalogue réel ; conserver les effets et reçus atomiques, les révisions, les autorisations courantes et la pagination ; publier une génération une seule fois, comparer les traitements et distinguer les avis d'agents ; attribuer et retirer le skill dédié | `app/lab/tests/test_mcp.py`, `app/skill/tests/test_storage.py`, `lab-insights.spec.mjs` |
| `incident` | Regrouper les échecs, diagnostiquer/résoudre selon les droits, conserver la preuve du correctif | `test_incident_service.py`, `test_router.py`, `test_retention.py`, `lab-access.spec.mjs`, `e2e/specs/incident.spec.mjs` |
| `dashboard` / frontend `index` | Montrer les indicateurs du périmètre autorisé avec des agrégations bornées ; réutiliser les mois consultés, actualiser et invalider le cache au changement de droits | `test_dashboard_service.py`, `dashboardStore.test.mjs`, `dashboard.spec.mjs`, `shell.spec.mjs`, `preferences.spec.mjs` |
| `onboarding` | Initialiser l’application sans écraser une configuration existante | `test_services.py` |
| `webhook` | Authentifier et identifier une livraison entrante sans admettre deux fois le même événement | `test_router.py`, `test_delivery_identity.py` |

### Sélection et création de sujets

`chat-recovery.spec.mjs` vérifie sur mobile et bureau le retour et l’avance du navigateur
entre conversations et vers l’accueil du Chat, sans doublon lors d’une resélection. Les réponses
tardives d’une conversation hors liste ne remplacent pas la conversation retrouvée.
`chat-document-workspace.spec.mjs` annule le changement si le document ouvert ne peut pas être
sauvegardé, puis permet le réessai. `e2e/specs/chat.spec.mjs` alterne clics et historique natif
pendant une réponse en cours, sans mélange entre conversations ni perte de la réponse achevée.

`front/browser-tests/chat-window.spec.mjs` compare le nombre de bulles montées pour
1 000 messages synthétiques et protège les extrémités, les réponses et la visibilité de lecture.
Le chat complet et le lecteur de discussions franchissent le seuil de virtualisation
en chargeant des pages de 50 messages, sur desktop et mobile, puis se rouvrent en bas.
Les scénarios conservent l’ancre avec des hauteurs variables, des ajouts d’historique,
le streaming et le redimensionnement ; ils couvrent aussi le focus, la sélection,
le clavier, la recherche native, le cache Markdown et la lecture audio hors écran.
La recherche native et les interactions actives peuvent conserver davantage de bulles.

`front/browser-tests/chat-performance.spec.mjs` mesure sur des données synthétiques les
relectures de l’historique pendant 20 fragments, les rendus Markdown pendant une rafale,
les lectures de cartes et miniatures au retour sur un message, et les octets de Blob
retenus après consultation de 40 pièces jointes. Il protège le texte final complet,
les réponses vides en pause, le relais vers le message durable, le rechargement après
éviction, l’expiration, l’invalidation hors écran, les réponses tardives et l’isolation
entre agents et sessions. Les médias visibles, ouverts ou en lecture sont protégés de
l’éviction ; les autres aperçus se partagent 32 entrées et 32 Mio par fil. Les caches
partagés des cartes et miniatures expirent après 30 secondes et sont invalidés lors
des modifications documentaires, reconnexions et changements de session ; ils ne stockent
pas les téléchargements originaux. `services/chatPreviews.test.mjs` vérifie le partage
des requêtes, les copies indépendantes et l’enrichissement des métadonnées après capture.

`TopicSelect` centralise la recherche paginée et la sélection par identifiant de sujet.

`front/browser-tests/topic-detail.spec.mjs` vérifie sur desktop et mobile l’ouverture des
cibles d’un sujet en modale (tâches, conversations, documents, jeux de données et mémoires dans leur onglet dédié),
le clavier, la fermeture par l’arrière-plan, le réessai après refus et les réponses tardives.
L'accès direct aux rounds texte/audio depuis le sujet est retiré avec leurs onglets et compteurs ;
leur consultation reste couverte dans `execution.spec.mjs` et `voice.spec.mjs`.
`app/dream/tests/test_resource_topics.py` couvre les associations directes aux documents et
datasets : reprise du checkpoint, modes de création, contenu conservé, décisions tardives,
filtrage par droits, fusion et suppression du sujet.
`resource-topic-assignment.spec.mjs` exerce le badge partagé dans les éditeurs Documents et
Datasets sur mobile/bureau : première affectation, réaffectation, audit, droits, réessai après
erreur et conservation des brouillons, y compris du JSON invalide. Le test PostgreSQL couvre
également le verrou de métadonnées, les refus et la priorité de l'affectation manuelle sur
un ancien reçu Dream, sans nouvelle révision de contenu.
`e2e/specs/resource-topics.spec.mjs` vérifie l'affectation depuis les deux éditeurs dans
l'application assemblée, la persistance après rechargement et les ressources listées dans le sujet.
`front/browser-tests/room-discussion.spec.mjs` couvre le calage initial et à la réouverture,
le chargement automatique en haut avec conservation de la position, l’actualisation en bas,
la flèche de retour aux derniers messages, les requêtes bornées, les erreurs et les changements
de discussion pendant un chargement, sur desktop et mobile.
La projection documentaire (`app/conversation/tests/test_service.py`) retire les documents
supprimés avant le décompte et la pagination. `chat-document-workspace.spec.mjs` couvre aussi
une suppression reçue avant l’arrivée d’une liste HTTP ; `document-deletion.spec.mjs` vérifie
l’indication historique « Document supprimé » en français et en anglais, sans accès au contenu.
Les formulaires activent `allow-create` : nouvelle conversation, paramètres de conversation,
message avec `@topic`, réaffectation depuis un badge, éditeur d’affectation des tâches et
conversations texte/voix, et cible de fusion. Le bouton `+` exige `TOPIC_EDIT` et
`AGENT_MANAGE_ALL`, conformément à l’API de création des sujets globaux. Un champ `readonly`
ou désactivé ne permet pas la création. Les filtres de tâches et d’historiques texte/voix
conservent `allow-create=false` tout en restant sélectionnables.

Le filtre Mémoire est distinct : ses valeurs sont des identifiants de fiches `MemoryItem`
projetées depuis les sujets et autorisées pour l’agent sélectionné. Il conserve son catalogue
Mémoire et ne propose aucune création ; lui substituer des identifiants de sujets casserait
le contrat du filtre. Les sujets du laboratoire sont des données de jeux d’évaluation.

Garanties : le sujet créé devient la sélection du formulaire sans perdre son brouillon ;
annulation, erreur, révocation des droits ou changement de contexte ne remplacent pas la
sélection par une réponse obsolète. La fusion exclut le sujet source et utilise la recherche
paginée commune. Preuves : `topics.spec.mjs`, `chat.spec.mjs`, `select-lifecycle.spec.mjs`
et `filter-loading.spec.mjs` dans `front/browser-tests/`.

<a id="shared"></a>

## Infrastructure et interface commune

Pour les couleurs des barres système Android, les assertions DOM/CSS de
`front/browser-tests/presentation.spec.mjs` vérifient le thème du canevas web et l’indication
`theme-color`, y compris après changement de préférence, réouverture, `pageshow` et retour au
premier plan. Une indication absente est recréée. Le manifeste fournit un repli natif sombre
avec `theme_color` et `background_color` ; ce repli reste sombre en thème clair.
La compilation vérifie que ces deux champs sont explicitement présents et non vides dans le
manifeste généré ; `front/scripts/report-build.test.mjs` couvre leur suppression ou leur vidage.
Un viewport mobile émulé ne valide pas leur rendu natif. Vérifier la PWA installée sur Android
avec navigation à trois boutons, au lancement et après retour au premier plan, dans les thèmes
clair et sombre du système, y compris avec un thème Galaris opposé ; contrôler aussi une
installation existante après actualisation du WebAPK.

| Domaine | Garantie | Preuves |
|---|---|---|
| `core.user` | Connexion, MFA, renouvellement concurrent, révocation et dernier administrateur | `back/core/user/tests/test_user_flow.py`, `test_refresh_concurrency.py`, `test_admin_invariants.py`, `e2e/specs/session-races.spec.mjs` |
| Inscription publique | Premier compte administrateur unique même en concurrence ; inscriptions suivantes fermées par défaut et réglables sans octroyer de droits ; page fermée, erreurs réseau et réponses tardives | `back/core/user/tests/test_registration_policy.py`, `back/core/params/tests/test_runtime_preferences.py`, `front/browser-tests/registration.spec.mjs` |
| `core.authorize` | Les droits du router et des ressources refusent réellement les accès | `back/core/authorize/tests/test_route_security.py`, `test_resource_rules.py`, `test_assertions.py` |
| `core.params` | Conserver une personnalisation ou adopter explicitement un nouveau défaut ; retrouver tous les réglages après dépliage, préserver les brouillons et les droits dans les préférences sur ordinateur et mobile | `back/core/params/tests/test_services.py`, `test_dbadmin.py`, `front/browser-tests/preferences.spec.mjs`, `params-layout.spec.mjs` |
| `core.dbadmin` | Converger sans perte de données ; reprendre, respecter dépendances et contributions indépendantes ; contrôler les enums avant nettoyage, préserver défauts/propriétaires/droits, annuler le lot et reprendre après interruption ou expiration d'un verrou | `back/core/dbadmin/tests/test_postgresql_transitions.py`, `test_enum_safety.py`, `test_actions.py`, `test_registry.py`, `make tests-upgrade` |
| Civilités initiales | Peupler une base neuve une seule fois ; préserver ensuite renommages, genres, ajouts et suppressions, même de toutes les lignes | `back/app/agent/tests/test_dbadmin.py` |
| Civilités traduites | Traduire les clés initiales côté frontend, les conserver à l’enregistrement sans renommage et préserver les libellés personnalisés | `front/browser-tests/agents.spec.mjs` |
| DB / runtime | Sessions isolées, concurrence, timeout et arrêt sans abandon de ressources | `back/core/tests/test_database_context.py`, `test_runtime_timeouts.py`, `back/tests/test_durable_concurrency.py` |
| i18n / navigation / API | Catalogues cohérents, navigation selon les droits, réponses du bon compte et de la bonne requête | `make typecheck`, `front/core/api.test.mjs`, `front/browser-tests/lab-access.spec.mjs`, `e2e/specs/session-races.spec.mjs` |
| Contenu / aperçu / fichiers | Éditer, relire, imprimer sans altération ni exécution indue ; adapter automatiquement la largeur de page au conteneur, y compris en plein écran et en lecture seule, sans perdre le contenu ni le choix manuel ; libérer les pièces jointes | `back/core/util/tests/test_rich_text.py`, `back/core/preview/tests/test_conversion.py`, `front/browser-tests/rich-text.spec.mjs`, `document-print.spec.mjs`, `document-layout.spec.mjs`, `model3d.spec.mjs` |
| Raccourcis documentaires | Qualification dans Chromium, Firefox et WebKit : titres, alignements, exposants/indices, annuler/rétablir, listes, tableaux et caractères insécables ; distinguer Ctrl+Alt, AltGr et les caractères Option simulés ; préserver sélection, liens, navigation, focus et plein écran ; ouvrir l’aide et imprimer en lecture seule sans modifier le contenu ; faire défiler l’aide sans recouvrir le titre ; préserver les champs enrichis et Source ; enregistrer puis rouvrir le contenu. Les dispositions natives Windows/macOS restent hors du runner Linux | `front/browser-tests/document-shortcuts.spec.mjs`, `e2e/specs/editorial-html.spec.mjs` |
| PWA / livraison | Recharger automatiquement les onglets après un déploiement échoué en conservant la session et la conversation ; qualifier les images, sauvegardes et restaurations | `e2e/specs/pwa.spec.mjs`, `back/tests/test_release_qualification.py`, `make tests-release`, `make tests-restore` |
| Outillage documentaire hors ligne | Générer les cartes FR/EN depuis le checkout courant sans accès aux secrets, aux volumes applicatifs ni au réseau ; refuser lectures interdites, écritures des sources et connexion depuis le code exécuté ; ne publier que les sorties attendues et préserver le checkout en cas d'échec | `bin/test-documentation.sh`, `bin/test-documentation-confinement.sh`, `make tests-documentation` |

## Bridges : tester l’adaptation une fois par protocole

Les suites propres aux bridges vivent dans `back/bridge/<module>/tests/`. Les règles de
messagerie et de processus restent testées dans leurs domaines canoniques : ne pas les copier
pour chaque provider. Les doubles réseau prouvent requêtes, conversions, refus et retries
locaux ; ils ne prouvent pas la réception sur un compte distant réel.

| Module(s) | Contrat d’adaptation | Preuves |
|---|---|---|
| `matrix` | Identités, envoi/réception et voix | `test_client.py`, `test_messenger.py`, `test_voice.py` |
| `nextcloud` | Talk, credentials, messages, appels et signalisation | `test_credentials.py`, `test_messenger.py`, `test_call_listener.py`, `test_signaling.py` |
| `one_bot` | Routage d’événement/API et connexion du hub | `test_hub.py`, `test_router_routing.py`, `test_messenger_routing.py` |
| `telegram` | Messages et reprise de livraison | `test_messenger.py`, `test_delivery_retry.py` |
| `whatsapp` | Authentification du bridge, API et livraison Messenger | `test_router.py`, `test_client.py`, `test_messenger_send.py` |
| `mail` | MIME, identités, connexion autorisée, messages, fichiers et validation privée Chat/journal ; réception avant lecture, contacts propres à l’agent, accord ponctuel/permanent, refus, doublons concurrents et reprise après interruption | `test_assertions.py`, `test_connection_resolution.py`, `test_mime.py`, `test_messenger.py`, `test_file_transport.py`, `test_chat_approvals.py`, `test_inbound.py` ; navigateur `mail-inbound.spec.mjs` ; E2E `mail-approval.spec.mjs`, `mail-inbound.spec.mjs` |
| `calendar` | Dates/récurrences, limites et opérations autorisées | `test_ical.py`, `test_calculation_limits.py`, `test_service.py`, `test_mcp.py` |
| `n8n` | Traduire démarrage, callback et annulation vers Process | `test_n8n_bridge.py` |
| `harness` | Manager, diagnostic et cycle de vie du conteneur | `test_manager.py`, `test_diagnostics.py`, `make tests-harness-manager` |
| `hermes` | Exécution, annulation, historiques, secrets et rattachement de session | `test_executor_cancellation.py`, `test_executor_history.py`, `test_session_binding.py`, `back/tests/test_driver_conformance.py` |
| `claude_agent`, `codex`, `deepseek_harness` | Contrat du provider et adaptation du runtime | leurs `test_harness_provider.py`, `test_stream_trace.py` pour Claude/Codex, `test_runtime_adapter.py` pour DeepSeek |
| `openai` | Ressources, authentification et protocole temps réel | `test_resources.py`, `test_runtime_auth.py`, `test_realtime.py` |
| Autres providers conditionnels | Enregistrement, configuration, découverte et adaptation dans le catalogue partagé | `back/tests/test_provider_catalog.py`, `test_provider_bridges_register_profiles_and_service_facades`, suites `app.llm` et `app.multimedia` |
| `youtube` (support) | Restituer la transcription et ses erreurs | `test_transcript_service.py` |

Les autres providers déclarés sont `openrouter`, `mammouth`, `anthropic`, `deepseek`,
`fireworks`, `groq`, `mistral`, `models_dev`, `together`, `cerebras`, `google`, `xai`, `nvidia`,
`huggingface`, `cohere`, `perplexity`, `elevenlabs`, `sunoapi`, `byteplus`, `azure_speech`,
`ollama`. La suite partagée ne qualifie pas exhaustivement toutes leurs opérations. Ajouter
un cas spécifique lorsqu’une différence de protocole le justifie, pas une copie du workflow
canonique. Leurs modules frontend de configuration suivent les mêmes contrats de formulaire.

<a id="documents"></a>

## Documents et interactions communes

- Les scénarios de raccourcis de `front/browser-tests/document-classification.spec.mjs`
  couvrent le survol, le focus, la création, la confirmation de suppression, les champs de
  saisie, les dialogues et les documents protégés ou occupés.
  `e2e/specs/document-library-shortcuts.spec.mjs` exerce création de sous-dossier et de
  document, renommage enregistré et suppression confirmée dans l’application assemblée.

- `front/browser-tests/document-bulk.spec.mjs` : sélection limitée à la page, filtres de dossier,
  pagination, ajout/retrait de mots-clés et de partages sans écraser les réglages hétérogènes,
  transfert de propriété et suppression avec bilan partiel.
- `e2e/specs/document-bulk.spec.mjs` : parcours Documents assemblé en bureau et mobile,
  récursion des dossiers, conservation des mots-clés et partages réels, non-classés et suppression.

### Préférence personnelle d’ouverture des documents du chat

Le profil enregistre par utilisateur le choix écran splitté ou modale, avec écran splitté
par défaut pour les comptes nouveaux et existants. Le réglage n’est visible que lorsque
la messagerie interne est activée et accessible. Le clic principal sur une PJ document
respecte ce choix sur desktop ; sur mobile, ou sans accès à la coédition, il ouvre une modale.
Les icônes permettent toujours de choisir explicitement une autre ouverture disponible.
Un échec de sauvegarde conserve le choix précédent.

Garanties : `back/core/user/tests/test_user.py`,
`front/browser-tests/preferences.spec.mjs` et `front/browser-tests/chat-document-workspace.spec.mjs`.

Revue de dépendance : `app/chat` consomme uniquement les exports publics `useAuthStore`
et `DocumentOpenMode` de `core/user` pour lire et enregistrer la préférence. Cette dépendance
applicative vers l’infrastructure utilisateur n’ajoute ni import privé ni cycle.

`front/browser-tests/dataset-dialog.spec.mjs` vérifie l’ouverture de l’éditeur Dataset depuis
le Chat, la confirmation de fermeture avec brouillon invalide, la réouverture, la conservation
du filtre de bibliothèque et la conversion des URI/URL Dataset collées en cartes persistantes
ouvrant la modale en lecture et en édition sans copier leur JSON. La bibliothèque ouvre
l'éditeur dans la page sur ordinateur et mobile ; le scénario vérifie le séparateur à la
souris et au clavier, puis le retour à la liste et la réouverture avec le filtre conservé.
Le parcours assemblé `e2e/specs/datasets.spec.mjs` conserve sauvegarde, historique,
restauration, partage et confirmation des brouillons dans l'éditeur intégré.

`dataset-navigation.spec.mjs` monte la route réelle et utilise l'historique du navigateur
sur mobile et bureau : visites, retours à la liste, filtres conservés, resélection sans doublon,
JSON invalide, annulation ou abandon du brouillon et réessai après échec de sauvegarde.
`e2e/specs/dataset-browser-history.spec.mjs` exerce ce parcours dans l'application complète
avec les vraies API, sur Chromium, Firefox et WebKit.

### Classement personnel des documents

La bibliothèque Datasets possède le même principe d'arborescence et de liste, avec un
classement indépendant. `back/app/dataset/tests/test_library.py` vérifie l'isolation entre
utilisateurs, les filtres combinés et le tri paginé, la conservation du JSON et des droits,
les refus HTTP et les cycles concurrents. `front/browser-tests/dataset-library.spec.mjs`
exerce les menus, sous-dossiers, déplacements, suppression avec retour aux non classés,
filtres et réponses tardives. `e2e/specs/datasets.spec.mjs` vérifie la persistance des dossiers
et déplacements dans l'application assemblée, en plus de l'édition et du partage.

`front/browser-tests/document-navigation.spec.mjs` couvre l’historique précédent/suivant
sur bureau et mobile : ouvertures depuis la bibliothèque ou une route documentaire,
activation au clavier, nouvelle branche après un retour, absence de doublon consécutif,
retrait des visites supprimées et préservation du brouillon et du curseur d’historique
après un refus de sauvegarde, puis sauvegarde et réouverture après reprise.
Les parcours Documents, Chat et modales utilisent aussi le véritable historique du navigateur :
retour/avance natifs alternés avec les flèches documentaires, URL et conversation conservées,
annulation du retour après un échec de sauvegarde et indépendance des modales imbriquées.
Ils retiennent aussi une réponse pendant des retours rapides et vérifient qu’une branche
créée dans une modale conserve la navigation du parent et sauvegarde son brouillon.
`e2e/specs/document-browser-history.spec.mjs` exerce les trois contextes dans le shell complet,
ainsi que les retours/avances après rechargement, sur Chromium, Firefox et WebKit.
Les liens et cartes documentaires naviguent dans le même onglet en lecture, édition et lecture
seule, pour les URI et les URL locales (`galaris-links.spec.mjs`) ; les autres ressources gardent
leur modale et les pièces jointes leur lecteur. `document-flows.spec.mjs` et
`e2e/specs/document-links.spec.mjs` vérifient le retour au document contenant la référence.
Le parcours E2E utilise les flèches avec le shell complet : le menu du compte ne doit pas
intercepter leur activation, un risque absent du montage de composant seul.
`document-dialog-navigation.spec.mjs` couvre l’historique propre à la modale, les liens et
cartes sans changement de route ni fenêtre imbriquée, la nouvelle branche et la réouverture,
la portée d’agent initiale conservée sans la transmettre aux documents privés liés, le clavier,
la sauvegarde refusée ou effectuée pendant un chargement, les droits refusés et les réponses
tardives après fermeture. Les consommateurs existants sont exercés dans
`chat-document-workspace.spec.mjs`, `topic-detail.spec.mjs` et `file-browser.spec.mjs`.

`front/browser-tests/document-flows.spec.mjs` retient les réponses annexes et de suppression :
contenu utilisable avant les catalogues, retrait anticipé et restauration de la ligne courante
en cas de refus, propagation d'un titre sauvegardé dans l'arbre et la liste avant relecture,
regroupement des notifications pendant une lecture lente et réutilisation des catalogues.
`test_library_performance.py` compare les lectures SQL avec/sans catalogues, à résultats identiques,
sur 100 puis 1 000 documents et jusqu'à 100 000 révisions ; le compteur inclut `WITH`.
Il couvre aussi le dépliage des dossiers et sous-documents sur 120 puis 960 documents synthétiques,
avec le contexte utilisateur et les périmètres d'agents limité ou global. Les résultats et les
droits restent vérifiés ; un budget d'accès aux pages PostgreSQL détecte les réévaluations
imbriquées des droits, même lorsque les données sont en cache. Les mesures sont écrites dans
`artifacts/memory-tree-benchmark*.json`. Les scénarios de classement vérifient que les filtres
« tous » et « classés » donnent les mêmes branches, avec les mêmes droits et la même pagination ;
le filtre « non classés » continue d'exclure ces documents.

- `back/app/memory/tests/test_goal_folders.py` : classement automatique par utilisateur et Goal,
  respect des dossiers manuels et des droits courants, reprise globale par lots, homonymes,
  renommage, suppression/recréation, déclencheurs Goal/User/partage/provenance, concurrence avec
  les déplacements manuels, rollback et relance administrative protégée.
- `back/app/memory/tests/test_document_classification.py` : tags privés, classement en lecture
  seule sans mutation du document, arbre sans cycles, suppression récursive avec confirmation
  conditionnelle et retour des documents parmi les orphelins sans toucher au classement d'autrui,
  filtres avant pagination et retrait effectif des documents dont l'accès est révoqué ; déplacement
  atomique remplaçant les tags de l'utilisateur, ordre personnel persistant des frères mixtes et
  de la liste, rejet des ancrages périmés, palette SVG privée durable et validation des SVG.
  Les dossiers précèdent toujours les documents ; le tri alphabétique dans les deux sens est
  persistant, privé, insensible à la casse et aux accents, sans modifier les documents.
  Les icônes personnelles des documents survivent au classement et ne modifient pas le contenu ;
  la révocation d'accès interdit leur lecture et leur modification.
  Les notifications de classement ne concernent que leur propriétaire et identifient les dossiers
  touchés ; elles ne déclenchent pas l'invalidation globale réservée aux changements d'accès.
  `test_goal_folders.py` vérifie aussi les notifications ciblées du worker de classement,
  l'absence de notification lors d'une reprise sans changement et le renommage sans relire les documents.
  `test_document_structure.py` vérifie qu'une description de pièce jointe notifie seulement sa mémoire.
- `front/browser-tests/document-classification.spec.mjs` : déplacement par glisser-déposer,
  retour aux documents non classés par déplacement, création immédiate de dossiers et sous-dossiers suivie du renommage
  direct avec annulation, choix d'émojis
  Unicode, dossiers colorés, polices de pictogrammes et téléversement réutilisable, recherche
  française, filtres compacts, toggle des documents non classés activé par défaut et réinitialisable,
  branches chargées intégralement au dépliage et indépendantes de la recherche de liste,
  réordonnancement des dossiers et documents conservé à la réouverture,
  barre contextuelle au survol et au clavier, création d'un frère juste après le dossier,
  édition explicite remplaçant le double-clic, actions tactiles, tri A→Z/Z→A avec dossiers en premier,
  dépliage/repliage récursif limité à la branche et reprise après erreur de positionnement ou de tri,
  ouverture, repliage et réouverture des dossiers vides sans nouvelle requête,
  rafraîchissement limité aux dossiers concernés sans retirer les autres lignes pendant une réponse
  lente, renommage sans recharger les documents et effacement immédiat lors d'une révocation d'accès,
  réconciliation après reconnexion sans démonter les lignes, maintien du contenu en cas d'erreur
  de rafraîchissement et renouvellement du jeton sans perdre dossiers ouverts ni filtres,
  suppression vide immédiate ou confirmée avec annulation, réponses tardives et reprise après erreur.
  Les déplacements documentaires confirmés s'affichent sans attendre les lectures de
  rafraîchissement ; un second déplacement reste possible, une ancienne réponse ne rétablit
  pas le premier classement, et un refus conserve la position puis permet un réessai.
  Le choix d'icône se propage entre arbre et liste, persiste à la réouverture et ignore les réponses
  périmées après sauvegarde ou changement de session ; l'icône par défaut et les erreurs restent utilisables.
  Dans la liste et l'arbre, l'icône d'un document ouvre le document sans sélecteur d'icône ; le choix reste disponible dans l'éditeur et l'icône d'un dossier reste modifiable.
- `e2e/specs/document-folder-create.spec.mjs` : création depuis un sous-dossier, classement
  personnel persisté, création de sous-documents et dépliage après rechargement de la bibliothèque assemblée.
  `test_document_classification.py` couvre aussi l'isolation personnelle, la lecture seule,
  les cycles, les ancres périmées, les déplacements de branches et les parents supprimés ou illisibles ;
  `document-classification.spec.mjs` vérifie le dépliage récursif, les erreurs/reprises,
  les déplacements et le changement de session sur ordinateur et mobile.
- `front/browser-tests/memory.spec.mjs` et `document-sharing.spec.mjs` : pagination à la demande,
  ouverture mobile, création et sauvegarde avec l'identité humaine.
- `e2e/specs/document-refresh.spec.mjs` : modification distante via l'API et les vrais événements
  websocket, requêtes limitées au dossier concerné et à la page visible, lignes conservées dans l'arbre et la liste.
- `e2e/specs/resource-sharing.spec.mjs` : partage Documents/Processus entre deux sessions,
  destinataire sans privilège administrateur, lecture puis écriture sans droit de repartager,
  rechargement mobile, réouverture et révocation. `app/share/tests/test_concurrency.py`
  vérifie les conflits entre connexions PostgreSQL et l'indépendance des ressources ;
  `test_upgrade.py` migre un ancien schéma peuplé, interrompt le transfert et vérifie sa reprise.
- `front/browser-tests/document-deletion.spec.mjs` : suppression confirmée retirée immédiatement
  de la bibliothèque desktop/mobile, même pendant une lecture lente ; les réponses capturées
  avant suppression ne réintroduisent pas le document et les notifications se regroupent en
  un seul rafraîchissement de la liste après suppression.

### Défilement des modales

Le contenu long défile sans déplacer le titre ni masquer sa fermeture, sur ordinateur et
mobile. Les actions de pied restent accessibles et les formulaires conservent leurs
brouillons, leur validation et leur sauvegarde après défilement. Garanties :
`front/browser-tests/dialogs.spec.mjs`, `teams.spec.mjs`, `lab-comparison.spec.mjs` et
`lab-insights.spec.mjs`. Les parcours `skills.spec.mjs`, `galaris-links.spec.mjs` et
`chat-document-workspace.spec.mjs` couvrent les panneaux, éditeurs et dialogues imbriqués.

Dans le chat, supprimer un document depuis l’éditeur ou en temps réel retire sa ligne et
ferme son panneau desktop ou sa modale, tout en conservant le brouillon du message.
Un refus laisse le document disponible ; une notification répétée ou une réponse de liste
tardive ne le réintroduit pas. Garantie : `chat-document-workspace.spec.mjs`.

### Barre d’édition mobile

Les modales et leur arrière-plan couvrent la barre d’outils du document ouvert en écran
partagé, y compris après défilement lorsque la barre devient flottante. La fermeture et la
réouverture préservent le document ; la mise en forme reste utilisable dans la modale.
Garantie : `front/browser-tests/chat-document-workspace.spec.mjs`.

Après défilement, la barre d’outils conserve toute la largeur de l’éditeur pendant le
redimensionnement du panneau, sans nouveau défilement ni perte de contenu. Elle reste
bornée par le document, y compris après perte du focus. Garanties :
`front/browser-tests/editor-toolbar.spec.mjs` et `chat-document-workspace.spec.mjs`.

Sous 1024 px, l’éditeur partagé aligne les icônes à leur largeur naturelle, avec retour à la
ligne selon la place disponible, sans groupes visuels ni défilement. L’ordre suit les fonctions :
édition, mise en forme, voix, liens, fichiers et partage, selon les capacités du champ. Toutes
les actions sont directement accessibles sans menu de débordement. Le changement de largeur
conserve le contenu et la dictée en cours.

Le partage prépare le contenu actuel en PDF puis ouvre le partage natif sur une action
explicite. L’URL Galaris accompagne le partage lorsqu’elle est acceptée, sans être ajoutée au
PDF. En l’absence de partage de fichiers, le dialogue propose l’enregistrement du PDF.
L’annulation et le changement de document empêchent de proposer un PDF devenu obsolète.

Garanties : `mobile-editor-toolbar.spec.mjs`, `document-voice.spec.mjs`,
`rich-text.spec.mjs` et `document-print.spec.mjs` dans `front/browser-tests/`.

<a id="files"></a>

## Catalogue privé de fichiers et maintenance

L'indexation se pilote dans **Dream → Indexation**. **Suivi** s'ouvre par
défaut ; **Historique** conserve les filtres et le détail des opérations. Le parcours
assemblé `e2e/specs/file-indexing.spec.mjs` vérifie ces onglets, leur réouverture et
l'absence du panneau d'indexation dans Mémoire, sur ordinateur et mobile.

Revue de dépendance : le sélecteur d'agent de Dream utilise uniquement les exports publics
`AgentSelect` et `useAgentStore` de `app/agent`. Le lien `app/dream → app/agent` est nécessaire
pour choisir le propriétaire du catalogue ; il n'ajoute ni import privé ni cycle.

`back/app/memory/tests/test_memory_urls.py` vérifie l'unique table de rattachement
des URL, le SHA-256 des octets texte et binaires sur le nœud, la colonne nullable
d'URL principale, sa stabilité et les déplacements/suppressions. La transition
PostgreSQL couvre rollback, rejeu et retrait de l'ancienne colonne du catalogue.
La disparition de la dernière ressource efface l'item mémoire, ses contenus et son
index vectoriel ; les autres URI, les pannes temporaires et les rollbacks préservent
la mémoire. `app/dataset/tests/test_datasets.py` couvre aussi l'effacement des projections
migrées sans perte de l'historique Dataset, et son annulation transactionnelle.

`back/app/memory/tests/test_file_catalogue.py` vérifie les observations, la séparation des
agents et bindings, les champs personnels éditables, les tombes et réponses tardives,
la réparation durable sans rejouer les effets, la reprise de pages de plus de 500 entrées,
les budgets/annulations, l'enrichissement versionné, les modifications externes et le RBAC.
Elle vérifie les fiches initialement vides et le nettoyage idempotent des anciennes descriptions
JSON techniques, avec conservation des notes, contenus personnels et révisions historiques.
Elle vérifie aussi l'identité SHA-256 par agent, le regroupement entre stockage et Messenger,
les notes et titres personnels, le résumé partagé historisé, les changements de copie,
le déplacement avec rattachement au nouveau répertoire et le refus d'un aperçu après
révocation ou modification des octets. `memory.spec.mjs` exerce miniatures et plein écran
depuis le détail du graphe, réouverture après un événement de plein écran tardif,
erreurs/reprises et réponses tardives lors d'un changement d'agent.
`e2e/specs/file-indexing.spec.mjs` vérifie avec les API réelles les miniatures, aperçus,
téléchargements originaux et réouvertures sur desktop et mobile, avec un provider synthétique.
Elle exerce aussi le scheduler Dream réel : un répertoire par tour inactif, reçus et jauges,
absence d'appel LLM, checkpoint atomique et rejouable, reprise après conflit de révision,
reparcours hebdomadaire sans doublon, ajouts/retraits et minuit local avec changement d'heure.
`back/app/memory/tests/test_file_catalogue_scale.py` qualifie des catalogues synthétiques de
1 000, 10 000 et 100 000 entrées et compare les écritures avec/sans observation. Les résultats
sont des mesures locales avec provider synthétique, sans promesse de latence distante.
`front/browser-tests/file-indexing.spec.mjs` couvre le suivi, le lancement et l'annulation,
l'erreur/retry et le rejet de réponses tardives après changement d'agent sur desktop/mobile.
`front/browser-tests/memory.spec.mjs` compare les couleurs réellement rendues des fichiers et
répertoires à leur légende, après filtrage et changement de thème, sur desktop et mobile.
`front/browser-tests/thumbnail-fit.spec.mjs` compare les proportions des images décodées
aux rectangles des aperçus réellement affichés en 3D, sur desktop et mobile : paysage,
portrait, carré, panorama et document, au premier affichage, après dézoom/zoom et filtrage.
Il vérifie aussi les octets originaux et la limite des dimensions natives en pixels.
Les assertions des transformations ECharts sont retirées avec le moteur 2D ; ces parcours
3D conservent les garanties de proportions et de réutilisation du cache.
Un répertoire synthétique de 84 images vérifie aussi les miniatures simultanées et leur
réutilisation avec une estimation de mémoire navigateur réduite, sur desktop annonçant 2 ou
16 cœurs. Les miniatures chargées restent en cache après un déplacement complet hors champ,
sans être dessinées, puis reviennent sans nouvelle lecture. Les petits graphes précédents
ne détectaient pas le plafond erroné de 64 miniatures. Les rectangles des aperçus ne se
chevauchent pas en vue proche ; un zoom supplémentaire atteint leurs dimensions natives
en pixels et ne les dépasse pas.
`memory.spec.mjs` vérifie également l'ouverture et le zoom de graphes synthétiques de 500, 3 000 et 10 001 nœuds,
sans perte de nœuds lors de la pagination, puis leur dépliage complet sans nouvelle requête.
Les titres restent filtrés pour éviter les superpositions au zoom maximal ; les
racines anciennes restent identifiables par leur URI ou leur titre personnalisé dans les deux thèmes.
L'ancienne assertion imposant tous les titres au zoom maximal est retirée : elle protégeait
la superposition qui rendait les cartes denses illisibles. Les dimensions réellement dessinées
vérifient les deux tailles fixes, éloignée/proche, et l'absence d'agrandissement au-delà du seuil proche.
Un cas de 2 760 souvenirs liés à douze sujets et à un contact vérifie le regroupement,
la conservation des deux connexions, l'ouverture locale, l'accès à un enfant, la réorganisation
après masquage d'une nature et la restauration du cadrage initial,
sur desktop/mobile. Les anciens cas de branches exclusives ne reproduisaient pas ce voisinage partagé.
Le dézoom minimal garde tous les points dans la fenêtre et centre leur étendue ; les symboles
conservent leur taille proche jusqu'au zoom d'un million de fois le cadrage initial.
`graphBranches.test.mjs` reproduit l'absence de regroupement avant correction et protège les
voisins hors page, suggestions, types/directions des relations et natures distinctes.
Le cas de volume inclut 5 000 nœuds non repliables et 10 000 liens, au-delà des anciens plafonds.
Le test unitaire de proximité des communautés est aussi exercé sur 4 800 items : il détecte
un placement initial indépendant des relations que la stabilisation bornée ne peut pas corriger.
Une topologie mixte de
sujets, contacts transversaux, documents/items partagés et isolés vérifie le mouvement réel
des positions, la convergence naturelle, la proximité des communautés, les positions conservées
au zoom et au dépliage, le cadrage conservé et les niveaux de détail
au dézoom, avec maintien des liens entre nœuds affichés ; les captures desktop/mobile sont inspectées.
Les branches exclusives sont exercées sur desktop/mobile : compteur, zoom avec hystérésis,
commande clavier via les boutons de zoom, ouverture d'un enfant, cadrage au dépliage et positions conservées à la fermeture
du détail. Le clic ouvre directement la modale sur desktop et mobile ; les métadonnées
(nature, visibilité, dernière activité, nombre d'accès), le contenu, les voisins dossiers et
conversations, la fermeture par arrière-plan ou Échap et la réouverture sont exercés.
Les anciennes assertions sur le popover et son bouton Voir sont remplacées par ce parcours.
Les parcours du contrôle de dépliage global retiré sont remplacés par le zoom ; le repli
manuel d'une branche avec un enfant sélectionné ne fait plus partie de l'interface.
Le rendu réel vérifie le fondu intermédiaire des nouveaux symboles au zoom, puis leur
visibilité complète, ainsi que l'apparition immédiate avec réduction des animations.
La stabilité des coordonnées est vérifiée dans le mode de grande fenêtre de 3 000 items.
Les erreurs/reprises et une réponse retardée après changement d'agent sont couvertes.
Le scénario de réponse tardive attend la fin du serveur simulé et vérifie l'annulation de
la requête ; il n'attend plus un événement de réponse réseau après une annulation effective.
Les parcours desktop/mobile restaurent les coordonnées et natures masquées après
réouverture, ajoutent des nœuds visibles et masqués sans déplacer les anciens, puis
reprennent une sauvegarde échouée. `graphState.test.mjs` vérifie les lots incrémentaux,
les modifications pendant une requête, les conflits de révision, la reconstruction d'un
format incompatible et la reprise automatique après échec de restauration. Les parcours
3D vérifient aussi le réessai sans déplacement de caméra. Les tests DB
`test_graph_state.py` vérifient l'isolation entre utilisateurs/contextes, les droits,
les révocations et la conservation des coordonnées lors d'une sauvegarde partielle,
ainsi que la reconstruction des états/coordonnées invalides dans la seule vue privée concernée.
L'ancienne assertion imposant le mode interne `force` après repli est remplacée par
la conservation effective des coordonnées : une vue enregistrée utilise un placement explicite.
`front/app/memory/graphBranches.test.mjs` couvre les règles d'exclusivité, doublons, cycles,
isolés, positions survivantes et placement selon les liens ; ce dernier scénario échoue avec
la grille qui ignorait les relations.
`front/app/memory/graphVisibility.test.mjs` couvre la conservation et le partage du poids des
éléments masqués, les parents et représentants successifs, les doublons, cycles, suggestions,
enfants non chargés et le plafond de quatre fois le diamètre. Les parcours `memory.spec.mjs`
vérifient le masquage/réaffichage en 3D sur mobile et desktop ; `memory-3d.spec.mjs` vérifie
les compteurs d'enfants différés et d'items hors cadrage, la taille réelle des pixels de dossiers
avec 84 enfants non chargés et le maintien de tous leurs textes malgré le budget ordinaire et les chevauchements.
Les scénarios ECharts de simulation, de caméra et de repli 2D sont retirés avec ce moteur.
La navigation, le contenu, la pagination, les filtres et la réouverture restent couverts par
les scénarios 3D et HTTP réel cités ici ; le parcours de modales reste dans `memory.spec.mjs`. `graph3dCamera.test.mjs` protège le
cadrage des représentants agrandis sur un petit écran. Le test DB de pagination vérifie le voisin supplémentaire
hors page, confirmé ou suggéré, et les liens inaccessibles. `e2e/specs/memory-graph.spec.mjs`
exerce repli/dépliage, clavier, zoom, ouverture du contenu et retour au graphe dans l'application
assemblée, avec API réelle et base synthétique isolée ; les positions, natures masquées
et cadrage survivent aussi à une navigation complète. Les tests WebDAV vérifient que les lectures de
métadonnées suivent le nombre de dossiers pour 300 et 3 000 fichiers, avec repli individuel
et nouveaux contrôles après révocation. Le scénario fournisseur vérifie aussi la résolution
groupée des fichiers d'un Tool combinant File Share et Messenger.
`e2e/specs/file-indexing.spec.mjs` exerce l'application assemblée et son API réelle.
Le navigateur **Connaissances → Fichiers** est couvert par
`front/browser-tests/file-browser.spec.mjs` : navigation, chargement au défilement,
reprise après erreur sans perte des entrées, aperçu au clavier et changement d’agent
pendant une réponse tardive, menus de mutation, confirmations, refus d’accès et
renommage du répertoire ouvert.
Le même scénario utilise l’historique réel du navigateur sur mobile et bureau pour
restaurer agent et répertoire, sans doubler une sélection courante, après erreur ou
réponse tardive, et depuis une URL copiée. `internal-file-picker.spec.mjs` conserve
la sélection entre dossiers et recherches sans modifier la navigation de la page hôte.
Les scénarios d’historique montent la vraie route, afin d’exercer ses gardes : un
brouillon Dataset reste intact après l’annulation du retour, puis se ferme seulement
après confirmation d’abandon.
`app/file_share/tests/test_browser_mutations.py` protège les contrôles HTTP de portée,
les noms invalides, les collisions sans écrasement et la confirmation récursive explicite.
Les scénarios Nextcloud, Samba et SFTP vérifient les opérations sur répertoires,
la conservation du contenu et les racines protégées ; Samba et SFTP utilisent de vrais serveurs isolés.
`app/file_share/tests/test_managed_http.py` vérifie ses
routes HTTP assemblées, les refus de portée et de ressource, le contenu autorisé et
la continuation des fichiers indépendants. `app/memory/tests/test_managed_files.py`
vérifie que la liste et la recherche `file://` incluent les pièces jointes Document et
Chat autorisées, réappliquent les droits après révocation et continuent sans doublon
ni fuite à travers des pages de fichiers refusés. `app/console/tests/test_file_listing.py`
vérifie plusieurs pages SFTP non ordonnées, sans doublon ni omission, les curseurs
liés au répertoire et l’exclusion des symlinks et chemins extérieurs au home.
`e2e/specs/file-browser.spec.mjs` vérifie la page assemblée sur mobile et bureau
avec les vraies API : sélection d’agent, fichiers internes et pièces jointes depuis
`file://`, réouverture des aperçus
et modale documentaire sous le bon périmètre.

<a id="scope"></a>

## Portée et commandes durables

`app/conversation/tests/test_task_objective.py` et `test_service.py` couvrent aussi la
résolution d'un document de suivi pour une demande de continuation : provenance des extraits,
accord limité à l'écriture, admission durable et héritage sans élargissement par les enfants.

`app/agent/tests/test_execution_scope.py` et `app/task/tests/test_execution_scope.py`
vérifient héritage sans élargissement, amendement via le port, version inconnue, couverture
du plan et provenance des cibles. Le wrapper réel conserve un refus avant tout effet,
y compris après un amendement pendant l'autorisation. La décision survit au rollback
de l'outil et ne rend pas le checkpoint périmé ; l'activité la restitue après relecture.
`tests/test_inference_lifecycle.py` couvre préparation sans appel, départ concurrent,
reçu idempotent et révision périmée, échéance globale en préparation/exécution/pause et
journal partiel. `app/task/tests/test_replacement.py` fige les descendants et préserve
les autres travaux ; `app/process/tests/test_lifecycle_workflows.py` couvre arrêt demandé,
confirmation tardive et terminal incertain sans réécriture ni rejeu. PostgreSQL et les
façades sont réels, les fournisseurs et moteurs distants synthétiques.

Les mêmes tests de portée mesurent les deux préflights d'un appel de modification avec
1 et 30 tâches productrices : le nombre de lectures doit rester borné, sans requête par
ressource. `app/task/tests/test_activity_snapshot.py` vérifie qu'une longue demande ne
gonfle pas le résumé de portée renvoyé à chaque actualisation ; le contrat durable reste
complet. Les mesures locales sous `artifacts/` sont distinctes d'une qualification de
charge réelle ou de la latence des fournisseurs.

Le test de bornes du graphe admet les pages d'expansion de 500 nœuds et refuse 501,
en remplacement de l'ancienne limite de 100. Le scénario Lab d'inférence structurée
vérifie le contrat Dispatcher v5, ses valeurs d'organisation par défaut, ses retries
et ses coûts ; `test_dispatcher_planning.py` conserve la résolution des inférences v4
figées, sans leur ajouter les champs d'organisation.

## Règle de maintenance

Une garantie a une preuve principale et, si nécessaire, une preuve d’assemblage E2E.
Une nouvelle fonction interne n’exige pas automatiquement un nouveau test. Une nouvelle
branche métier, un refus, une perte de donnée possible ou un effet rejouable exige une preuve.
Un changement volontaire indique l’avant/après ; une suppression de test indique ce qui est
repris et ce qui ne constitue plus une exigence. Mesurer les régressions échappées, l’instabilité,
la durée et les mutations pertinentes, pas un objectif de nombre de tests.

## Rafraîchissement Chat et corrections ciblées

`front/app/chat/storeCatchUp.test.mjs` et `front/browser-tests/chat-recovery.spec.mjs`
vérifient le regroupement des signaux, la conservation d'une invalidation reçue pendant
une lecture, la reprise après erreur et les changements de conversation. Les messages,
les réponses en cours et le brouillon restent utilisables pendant le rafraîchissement.

`app/memory/tests/test_document_thumbnails.py` exerce les deux chemins de rendu PDF
avec la vraie bibliothèque dans un sous-processus concurrent. Un crash natif échoue
sans arrêter le worker pytest. `app/messenger/tests/test_link_preview.py` conserve
normalisation et déduplication pour les documents et fichiers gérés. Le scénario de
`app/connection/tests/test_encryption.py` protège les valeurs chiffrées, historiques,
vides ou indéchiffrables des dictionnaires de connexion.

### Références documentaires aux objets métier

`front/browser-tests/business-references.spec.mjs` exerce les URI et URL des tâches,
objectifs, sujets, discussions, rounds texte, appels et tours vocaux : collage titré,
cartes compactes réversibles, conservation du contenu, ouverture et réouverture en modale,
copie, fermeture par le fond, recherche avec reprise et réponses obsolètes. Le lecteur
exerce aussi le menu contextuel et le clavier. Les cartes de tâches et d'échanges ne
contiennent aucun corps d'exécution. Le parcours assemblé est dans
`e2e/specs/business-references.spec.mjs` : copie depuis Activité, collage, sauvegarde,
rechargement et fiches Task/Topic. La validation des identités et la normalisation sont
couvertes par `back/core/util/tests/test_rich_text.py`. Le test des restrictions du menu
Task conserve les interdictions de mutation terminale sans figer le nombre d'actions
non destructives.
