# 0099 — Classement personnel des documents par tags hiérarchiques

Statut : Accepted — 2026-09-14.

## Garantie

Chaque utilisateur retrouve les documents classés dans ses dossiers hiérarchiques et, par
défaut, les documents non classés dans la liste inférieure. Le toggle « Non classés » permet
d'y afficher tous les documents lorsqu'il est désactivé. L'accès ne duplique pas les documents selon les agents qui
les rendent accessibles. Le classement reste possible avec un simple droit de lecture.

## Décision

`app.memory` possède `DocumentTag` (utilisateur, parent, nom, icône, position) et `DocumentTagAssignment`
(tag, document, position). `DocumentListPosition` conserve l'ordre de la liste par utilisateur,
indépendamment de l'ordre mixte dossiers/documents dans chaque branche. Les associations sont uniques et idempotentes. La propriété de l'arbre et
les droits de lecture sont vérifiés côté serveur. Les mutations d'un arbre sont sérialisées
par utilisateur afin que des déplacements concurrents ne créent pas de cycle.
L'interface emploie « dossier » ; les noms techniques des contrats existants restent inchangés.

Le classement ne modifie ni le contenu, ni la révision, ni les dates, ni les accès du document.
Un document peut porter plusieurs tags personnels. « Non classés » signifie sans tag de
l'utilisateur courant. La suppression d'un tag détruit toute sa descendance et retire le
classement personnel des documents concernés, y compris leurs éventuels autres tags personnels,
afin qu'ils redeviennent orphelins. Le document et les tags des autres utilisateurs restent intacts.
La révocation de l'accès masque le document des listes et interdit toute nouvelle
opération de classement, sans donner un droit de lecture via une association préexistante.

La bibliothèque conserve l'union des accès humains et des agents gérés. Les filtres de
propriétaire désignent le propriétaire effectif (agent ou utilisateur), jamais un lecteur.
Recherche, classement, branche de tags, propriétaire, création et modification s'appliquent
avant pagination et comptage. Le tri utilise l'identifiant comme départage stable. Les bornes
API sont des instants avec fuseau, début inclus et fin exclue ; l'interface convertit la date
locale de fin inclusive au début du lendemain. Une date de modification absente utilise la
création pour l'affichage, le filtre et le tri.

La colonne de navigation contient l'arbre au-dessus de la liste filtrable, avec séparation horizontale
redimensionnable à la souris ou au clavier. Sa hauteur relative est mémorisée localement par
utilisateur. Chaque branche charge tous ses documents directs au dépliage par lots serveur de
500, sans pagination visible. La liste inférieure conserve sa pagination (50 par défaut,
choix 10/20/50/100/500). Les sous-tags chargent leurs propres documents, sans
dupliquer les descendants dans la branche parente. Les erreurs sont réessayables et les réponses
d'une branche fermée ou d'une ancienne session sont ignorées. Recherche, filtres et tri s'appliquent
uniquement à la liste inférieure ; les branches suivent leur ordre personnel. Le toggle « Non classés »,
placé avec les autres filtres, n'affecte que la liste
inférieure, s'applique côté serveur avant pagination et revient à son état activé à la
réinitialisation ou au changement d'utilisateur. Dans l'arbre, chaque document affiche uniquement
son titre et son icône ; la liste inférieure conserve auteur et dates. Le compteur de documents
et le choix du nombre par page sont regroupés avec la pagination dans le pied de liste.
Les filtres détaillés apparaissent dans un menu temporaire, avec une paire de bornes par type de date.
QTree reçoit un nœud par document pour dessiner les connecteurs de chaque ligne ; l'axe vertical
part sous l'icône du dossier. Il n'y a pas de séparateurs entre documents dans l'arbre.
Le glisser-déposer
d'un document remplace atomiquement tous ses tags personnels par le tag de destination ; un
dépôt dans la liste des documents sans tag retire ses tags personnels. Les tags des autres utilisateurs
restent intacts. La liste ne présente plus de bouton ni de compteur de classement à droite
des documents ; le classement s'effectue par déplacement dans l'arborescence.

Le centre d'une ligne de dossier reçoit les éléments à ranger ; ses bords supérieur et
inférieur servent à insérer avant ou après. Les documents peuvent être réordonnés entre eux
et parmi les sous-dossiers. Le serveur reçoit un nœud d'ancrage, vérifie la destination et les
droits, puis renumérote les frères sous le verrou utilisateur en une transaction, sans perdre
les lignes masquées par les filtres ou la pagination. Un ancrage périmé est rejeté avant mutation.
Réordonner la liste ne change pas le classement et réactive le tri manuel. L'ordre par titre reste
le défaut de l'API pour ses autres consommateurs ; la navigation choisit explicitement l'ordre manuel.

Chaque dossier propose un bouton + qui crée immédiatement un sous-dossier nommé « Nouveau
dossier », ouvre son parent et sélectionne le nom pour le renommer directement. Le bouton +
racine, placé après le dernier dossier, suit le même comportement. Annuler le renommage conserve le dossier déjà créé et son
nom initial ; un échec de création n'ajoute aucun dossier fictif. Le double-clic sur le nom active un
champ dans l'arbre (Entrée ou perte du focus pour enregistrer, Échap pour annuler). Le bouton
Supprimer remplace le menu d'actions. Le serveur supprime directement un tag vide ; pour une
branche contenant des documents ou des sous-tags, il retourne un bilan sans mutation, puis
l'interface demande confirmation. La requête confirmée recalcule la branche sous le verrou
de l'utilisateur et effectue toute la suppression en une transaction. Le déplacement des tags
reste disponible par glisser-déposer ; il n'y a plus de modale d'édition du tag.

Le simple clic sur l'icône ouvre une palette avec recherche et choix de collection :
émojis Unicode standard rendus par la police de l'appareil, dossiers SVG Solaire (ouverts
ou fermés, 11 couleurs), polices Material Design Icons et Font Awesome Free, et SVG
téléversés. Les polices sont fournies par `@quasar/extras` ; leurs CSS et catalogues sont
chargés à la demande. La grille utilise un défilement virtuel. Les noms et mots-clés des
émojis proviennent d'Emojibase 17.0.0 ; le catalogue est chargé dans la langue active.

Les références `emoji:…`, `folder:…`, `folder-open:…` et `font:…` sont vérifiées côté
serveur contre le catalogue généré depuis les mêmes sources. Les anciennes références
OpenMoji et Fluent SVG sont converties en références Unicode à la lecture ; les fichiers
SVG d'émojis sont supprimés. Changer de police d'émojis modifie leur dessin, pas le
répertoire Unicode : les polices de pictogrammes apportent les sujets supplémentaires.

`DocumentTagIcon` conserve les SVG privés téléversés indépendamment des tags. Ils restent
limités à 64 Kio et validés sans contenu actif ou externe, puis affichés comme images,
jamais injectés dans le DOM. Les dossiers et composants utilisent Solaire.

`DocumentIcon` conserve une icône personnelle par couple utilisateur/document, avec les mêmes
références validées que les dossiers, sauf les références `folder:` et `folder-open:` réservées
aux dossiers. La palette des documents s'ouvre sur les émojis et ne propose pas la collection
de dossiers ; les anciennes références de dossiers reviennent à l'icône de document par défaut
à la lecture, sans réécriture des données. Un droit de lecture suffit pour personnaliser son affichage.
Ce choix ne modifie ni contenu, ni révision, ni dates, ni droits ; il est indépendant du classement
et reste présent après déplacement ou suppression d'un dossier. Une valeur nulle rétablit
l'icône `description` existante. Les icônes d'un document inaccessible ne sont plus exposées.

Le composant frontend `DocumentIcon` affiche cette icône cliquable à gauche du titre dans
la bibliothèque, l'éditeur, les conversations et leurs aperçus, les tâches, les sujets et les
vues de détail mémoire. Il est fourni aux autres modules par `WorkingDocumentIcon`, via la
contribution `documentEditor.ts` existante, pour ne pas créer de dépendance circulaire vers mémoire.
La palette des dossiers est réutilisée avec le bon aperçu par défaut.
Un store Pinia commun regroupe les résolutions par lots de 500 au maximum, déduplique les
demandes et répercute les sauvegardes immédiatement entre vues. Le changement de session vide
le cache et ferme les palettes ; les réponses de l'ancienne session et les résolutions plus
anciennes qu'une sauvegarde ne peuvent pas remplacer le choix courant. Un échec de sauvegarde
conserve l'icône confirmée et permet de réessayer.

Les URI `document://` et les liens entre documents restent indépendants de ce classement.
Ouvrir un lien hors de la page de résultats ne l'ajoute pas artificiellement à la page.

## Compatibilité

Les anciens `metadata.document_path` et les contrats utilisés par les producteurs existants
sont conservés pour compatibilité, mais ne pilotent plus le rangement humain. L'éditeur ne
propose plus de modifier ce chemin. Les documents existants commencent sans tag personnel ;
aucune copie automatique des chemins ou du classement d'autrui n'est effectuée.

## Vérification

`test_document_classification.py` couvre l'isolation, la lecture seule, les cycles, la
suppression, les filtres avant pagination et la révocation. Les scénarios Chromium
`document-classification.spec.mjs` couvrent les gestes, filtres, réouverture, erreurs et
réponses tardives ; `memory.spec.mjs` et `document-sharing.spec.mjs` conservent les garanties
d'ouverture mobile, de création humaine et de sauvegarde.

L'ancien test de couleurs des dossiers n'est pas repris : il figeait la présentation de
l'arbre par agent supprimé. Le scénario de branche paginée est remplacé par le chargement complet
de 502 documents, sans filtre de liste ni commandes de pagination dans l'arbre, en conservant
les garanties de reprise après erreur et de rejet des réponses tardives.
