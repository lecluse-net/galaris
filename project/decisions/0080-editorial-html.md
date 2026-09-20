# 0080 — HTML éditorial canonique, profils et médias documentaires

Statut : accepté — 9 septembre 2026.

## Décision

Les corps éditoriaux des six catégories Memory, les documents, les descriptions et suivis
Goal, les objectifs Task et les deux champs de profil Agent utilisent des fragments
sémantiques `text/html`, profil version 1. Le HTML persisté est la seule source de vérité.
Les ressources natives, les messages de chat et l’intégralité des skills gardent leur format.

`core.util.rich_text` possède la normalisation déterministe, la validation préalable à nh3,
les limites et l’extraction textuelle. `rich-text` interdit les images ; `document` les
autorise exclusivement comme références aux pièces jointes du même document. Memory détermine
le profil depuis le type et la protection métier ; les documents Goal restent sans images.
Les métadonnées d’attachements et leurs manifestes sont exclusivement administrés par le service.

Le frontend utilise CKEditor 5 avec son composant Vue officiel, son interface native et
DOMPurify. Les tableaux, poignées d’images, déplacements, légendes, recherche/remplacement
et édition de source appartiennent à CKEditor. Les raccordements Galaris couvrent uniquement
les pièces jointes, liens, thèmes et synchronisation. Les paquets sont auto-hébergés sous
GPL 2 ou ultérieure (`licenseKey: 'GPL'`) ; l’article 5.3.4 de la licence CeCILL 2.1 du dépôt
prévoit cette combinaison. Les extensions commerciales et services cloud ne sont pas activés.
Les contributions `front/app/*/richContent.ts` apportent la recherche et la résolution de liens
au composant commun. Le bouton Lien Galaris ouvre une modale Quasar avec recherche, filtres
par type, sélection de cible et texte éditable ; l’insertion utilise la commande native de lien.
Les commandes natives et ce bouton occupent deux lignes d’icônes, avec retour automatique
sur écran étroit. La barre de menus est masquée, y compris en plein écran. Le focus dans le
document garde une bordure neutre. Les sélecteurs de titre et de taille de police affichent
leur valeur en texte et leurs listes offrent un aperçu des tailles. Aucun outil d’images
personnalisé n’est ajouté.
Le menu Styles utilise les commandes natives de conteneur et de classes HTML pour sept
encadrés colorés à plusieurs paragraphes. **Précision acceptée le 10 septembre 2026 :**
le document reste un texte enrichi lisible et imprimable. Les nouvelles écritures refusent
les scripts. Les sources historiques restent intactes ; leur lecture et leur restauration
présentent les scripts comme du code littéral, sans exécution.
Les pages HTML interactives, scènes 3D, vidéos et autres fichiers sont des pièces jointes,
consultées dans les visionneuses de ressources existantes. Le HTML est accepté comme fichier
et visualisé dans une iframe sans `allow-same-origin`, jamais injecté dans l'application.
Le collage et la source détectent les pages complètes et proposent une pièce jointe ou
l'extraction du seul texte enrichi ; annuler préserve le document.
Les href de présentation sont applicatifs ; les
URI persistées restent `document://`, `memory://` et les ressources `galaris://` implémentées.
Les Topics et contacts sont liés par leur item Memory canonique.

Le contrat HTML conserve les figures, légendes, colonnes et styles éditoriaux bornés de
CKEditor. Le modèle garde les URI canoniques ; seul le rendu d’édition résout les images en
URL temporaires autorisées. Les changements sont transmis immédiatement à l’autosauvegarde,
y compris après publication d’une image. Les dialogues hôtes Quasar autorisent le focus dans
les panneaux natifs de CKEditor, qui sont attachés au corps de la page.

Les pièces jointes raster sont vérifiées par décodage avant publication. Les révisions HTML
conservent `content_images`. Une suppression de pièce jointe la retire de la liste courante,
mais conserve ses octets jusqu’à l’oubli du document : cette rétention conservatrice protège
les révisions restaurables et les brouillons. Les téléchargements appliquent les droits actuels
et utilisent `private, no-store`. Copier une image vers un autre document exige une lecture
autorisée suivie d’un nouvel attachement local. Une insertion explicite de cartouche de lien
utilise l’extraction de métadonnées de `app.file_share` commune avec Messenger, dont YouTube
oEmbed. Pour les pages web, le port `core.preview` est branché au bootstrap de `app.browser`
sur `capture_public_page_thumbnail` et son cache, déjà utilisés par les discussions : aucun
autre moteur de capture n’est créé. YouTube conserve sa miniature vidéo. Le serveur borne le téléchargement,
décode l'image et enregistre une miniature JPEG comme pièce jointe. Les cartes YouTube sont
enrichies à l’affichage par le lecteur officiel `youtube-nocookie.com`, à partir d’un identifiant
vidéo validé. En édition, le lecteur est un élément UI de CKEditor, absent du modèle sauvegardé ;
la lecture applique le même rendu. Le lecteur est placé sous les informations, en pleine largeur,
et masque la miniature séparée. Les vidéos restent à l’échelle, sans recadrage. Les cartes de
pièces jointes audio, vidéo et PDF portent la classe `galaris-media-audio`, `galaris-media-video`
ou `galaris-media-pdf` et utilisent le même contrôleur de rendu éphémère : les lecteurs natifs
chargent les octets via le téléchargement authentifié existant, puis libèrent leur URL Blob au retrait.
Le type MIME de la PJ ou l’extension du nom permet aussi de lire les anciennes cartes.
Les PDF utilisent l’iframe Blob de la visionneuse existante, en pleine largeur.
Les présentations « bloc en page » et « bloc sous page » partagent leur feuille de style dans
`core.util`. `ResourcePreviewBlock` fournit la structure commune des blocs sous les documents
et dans les discussions ; CKEditor conserve la structure éditoriale `blockquote`, avec le même
style en page. Les actions d’insertion restent propres aux PJ absentes du contenu.
L’impression et le PDF gardent la miniature ou le lien statique. Aucun
iframe arbitraire n’est accepté dans la source du document. Le cartouche persiste
comme un `blockquote.galaris-link-card` avec texte, liens et image canonique. Coller une URL
seule insère un lien. Sa bulle native CKEditor propose de le convertir en carte et la bulle de
la carte permet de revenir au lien, sans modale ni bouton dans la barre d’outils principale.
Les liens web et Galaris ouvrent un nouvel onglet avec `noopener noreferrer`, y compris
depuis la bulle native et Ctrl/Cmd-clic ; le document courant reste ouvert.
La récupération distante n’a lieu qu’après le choix de la carte ; un refus des métadonnées
n’empêche pas d’utiliser la capture partagée de la page. Si les deux sont indisponibles,
la carte conserve l’adresse du site. Le code conserve le collage littéral. La surface visuelle
des cartes est partagée avec les aperçus des discussions.
Le navigateur collecte la description et le nom du site avec la capture ; ces métadonnées
sont conservées dans le même cache et réutilisées par les discussions et documents.
Les documents de travail exposent aussi une capture de leur HTML enregistré dans les cartes
des messages, la liste latérale du Chat et la bibliothèque. Le cache de cette capture est propre au document, à sa révision
de contenu, à sa version de métadonnées, à la version du rendu et au hash de l’instantané. Un fichier compagnon
`*.revision.json` conserve explicitement la révision miniaturisée. Les accès sont revérifiés
avant chaque lecture du cache ; une capture ancienne ne peut pas remplacer une plus récente.
Les captures sont regroupées par document et supprimées après chaque modification enregistrée
ou suppression, avant la notification temps réel. Une capture en cours revérifie sa version
avant publication. Chaque miniature écoute directement les changements de son document et
la reconnexion, sans dépendre de l’actualisation de sa liste parente. Les notifications couvrent
aussi les droits directs des utilisateurs humains.
Le frontend prépare le même instantané que l’impression et l’export PDF, avec leurs styles
et leurs images incorporées, puis l’envoie avec la révision et la version de métadonnées.
Le serveur refuse un instantané devenu obsolète ; son hash isole les variantes de cache entre lecteurs.
Le navigateur isolé reçoit cet instantané statique avec ses images locales matérialisées,
sans accès réseau ni scripts. Le frontend charge les miniatures visibles à la demande et
ignore les réponses devenues obsolètes après révision, changement de document ou de session.
Chromium imprime uniquement la première page avec les mêmes réglages que l’export PDF.
Le haut de cette page est recadré à pleine largeur puis réduit à 520 × 320 pixels.
La longueur totale ne réduit jamais l’ensemble du document en une bande verticale.

Toutes les miniatures utilisent `core.preview.thumbnails` : clé SHA-256 de l'URL ou URI
canonique, fichier PNG directement dans `GALARIS_THUMBNAIL_ROOT`, limites communes de
520 × 320 sans bandes ajoutées ni aplatissement de la transparence. Le lieu d'affichage
ne participe pas à la clé. Une pièce jointe `.url` utilise la clé de sa cible ; sa suppression
n'invalide pas la capture du site. Les pièces jointes HTML utilisent le même rendu navigateur
que les discussions, sans miniature concurrente du code source. Les autorisations restent
vérifiées par le domaine avant la lecture du cache. Les anciens caches ne sont pas migrés.
Les liens `document://<uuid>/attachments/<uuid>` ouvrent leur visionneuse sous les droits actuels.
Les fichiers s’insèrent dans le contenu : images natives ou cartouches cliquables pour les
autres formats. La gestion des pièces jointes est une fenêtre ouverte depuis la barre d’outils,
avec une liste sous le texte limitée aux fichiers non insérés, donnant accès à leur visionneuse
et à leur suppression. Le filtrage suit les liens et images du contenu, pas les URI citées comme code.
L'impression et le PDF reproduisent uniquement le corps du document. L'export ZIP conserve
un instantané HTML statique et les fichiers avec des liens relatifs, sans créer de révision.

Les éditions documentaires utilisent des révisions attendues et des blocs HTML complets.
Un conflit d’autosauvegarde ne fusionne pas silencieusement deux modifications du même champ :
le brouillon reste conservé et l’utilisateur choisit. Un jugement Goal commencé avant une
édition humaine du suivi est abandonné puis réévalué. Les écritures HTTP éditoriales exigent
`X-Editorial-Profile-Version: 1` pour empêcher un ancien frontend de reconvertir le HTML.

La fiche de poste et la personnalité sont injectées telles que persistées, y compris dans
les exécuteurs Task/conversation/voix et le profil Hermès. L’arbre de prompt conserve des
sections HTML explicites et le suffixe existant. Les chaînes décodées du transport conservent
exactement ces fragments. Les extraits de recherche ne remplacent jamais ces champs.

## Migration et vérification

Trois actions DbAdmin liées aux colonnes introduites convertissent par lots de 500, avec
sources préservées et postconditions. Memory conserve les révisions immuables ; Agent et Task
conservent leurs valeurs antérieures dans les champs de sauvegarde dédiés. Le format déclaré,
jamais une détection heuristique, commande la conversion. Les images anciennes non rattachées
restent des exceptions explicites. Une simulation Memory est disponible avec
`python -m app.memory.html_migration` dans le conteneur backend.

Les projections sont régénérées et l’index sémantique versionné utilise le texte visible.
Les dépendances de test couvrent le corpus HTML, les refus actifs, les ACL d’images, la rétention,
les blocs/révisions, le rejeu de migration, les prompts décodés et l’éditeur réel dans Chromium.

Le retour arrière conserve les écritures HTML et les images nouvelles. Il nécessite une
version applicative capable de les lire ; remettre un ancien frontend Markdown ou reconvertir
tout le stockage en Markdown n’est pas un retour arrière admissible.

Voir les guides [développeur](../../docs/fr/dev/editorial-html.md) et
[utilisateur](../../docs/fr/user/rich-content.md).
