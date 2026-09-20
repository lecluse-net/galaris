<p align="right"><strong>Français</strong> · <a href="../../en/user/rich-content.md">English</a></p>

# Écrire et relier des contenus riches

Les mémoires, documents, descriptions et suivis d’objectifs, consignes de tâches, fiches de
poste et personnalités utilisent CKEditor 5 et son interface native. La mise en forme est conservée à
l’enregistrement : titres, listes, soulignement, surlignage, citations, code et tableaux.
Le menu Tableau permet d’ajouter des lignes/colonnes, de fusionner ou séparer les cellules et
d’activer une ligne d’en-tête. Faites glisser une bordure pour régler les largeurs.
La barre d’outils propose alignement, recherche/remplacement, annulation et plein écran.
Ses commandes sont regroupées en blocs **Lecture**, **Édition**, **Texte**, **Paragraphe** et
**Insertion**, avec de petits titres et des infobulles, y compris en plein écran. Les blocs
se réorganisent selon la largeur disponible, sans barre de menus.
Le **mode simple**, utilisé pour les champs de texte enrichi, comprend le bloc **Lecture**
avec **Source** et **Plein écran**. Le **mode complet** des documents ajoute l’affichage en
page et son bouton **Pleine largeur**, les insertions documentaires, l’impression et les
exports PDF/ZIP dans **Édition**. La dictée et la lecture vocale apparaissent dans **Lecture**
dans les deux modes, avec vos modèles personnels. En lecture seule, **Lire le texte** reste
disponible et la dictée est masquée. Sélectionnez un passage pour ne lire que celui-ci, ou
laissez le curseur sans sélection pour lire tout le texte.
La barre reste accessible au défilement tant que le document est à l’écran, même après un clic sur le fond.
Cliquer dans le document conserve sa bordure neutre.
Les sélecteurs de titre et de taille de police affichent leur valeur en texte. Leurs listes
présentent les titres et les tailles avec un aperçu de leur grandeur.

## Couleurs des dossiers

Les couleurs des répertoires de documents indiquent leur rôle : **bleu** pour les dossiers
personnalisés propres à un agent, **rouge** lorsqu’ils contiennent au moins un document partagé
entre agents, **vert** pour les dossiers d’objectifs, partagés ou non. L’infobulle précise
le rôle et le partage. Les droits réels des documents déterminent le partage ; deux dossiers
de même nom chez deux agents ne sont pas nécessairement partagés. « Goals » et « Objectifs »
désignent la même catégorie. Les couleurs restent les mêmes dans l’arborescence et le sélecteur,
y compris lorsqu’une recherche masque une partie des documents.

## Liens

Le bouton **Lien Galaris** ouvre une recherche de contenus accessibles : saisissez au moins
deux caractères, filtrez par type, sélectionnez une cible, puis ajustez le texte du lien avant
de l’insérer. La sélection de texte et sa mise en forme sont conservées. La modale se ferme
aussi en cliquant sur l’arrière-plan.
Utilisez le bouton de lien natif pour saisir une URL ou une référence Galaris. Le libellé appartient à votre texte ; renommer la cible ne
casse pas la référence. Un lien ne partage pas sa cible : les droits sont vérifiés à l’ouverture.
En lecture, cliquez pour ouvrir dans un nouvel onglet en conservant le document affiché.
En édition, le clic place le curseur et Ctrl/Cmd-clic ouvre la cible dans un nouvel onglet. Le menu du lien
propose explicitement Ouvrir, modifier et retirer le lien.

## Encadrés et pièces jointes

Le menu **Styles** propose Information, Attention, Question, Erreur, Stop, Interdit et
À examiner. Sélectionnez un ou plusieurs paragraphes puis choisissez un style : ils forment
un encadré avec une icône et un fond adapté au thème. Choisissez un autre style pour le
changer, ou cliquez de nouveau sur le style actif pour retirer l’encadré.

Le corps du document reste du texte enrichi. Les pages HTML interactives, scènes 3D,
vidéos et autres contenus sont joints au document et ouverts dans leur visionneuse.
Pour insérer de nouveaux fichiers directement dans le texte, déposez-les à l’endroit voulu
ou placez le curseur puis collez les fichiers copiés. Plusieurs fichiers peuvent être envoyés
ensemble ; leur insertion suit l’ordre choisi et la position reste conservée pendant l’envoi.
Une progression permet d’annuler l’envoi. Les images gardent également les commandes natives de CKEditor.
Le bouton **Pièces jointes** de la barre d’outils ouvre la gestion des fichiers : déposez-les
dans cette fenêtre ou utilisez **Ajouter**, puis l’icône **Insérer dans le document** dans les
actions de l’aperçu. Cette icône apparaît uniquement pour les fichiers absents du contenu.
Les images s’affichent dans le texte ; les vidéos, sons et PDF disposent d’un lecteur intégré,
en édition comme en lecture. Les autres fichiers deviennent des cartouches cliquables ouvrant
leur visionneuse. Les fichiers absents du contenu restent listés sous le texte, avec leurs actions
d’ouverture et de suppression. Une PJ insérée dans le contenu disparaît de cette liste et y
revient si son insertion est retirée. La fenêtre de gestion donne accès à toutes les PJ. Chaque envoi
affiche sa progression et peut être annulé. Une page HTML complète collée dans l'éditeur
ou sa source déclenche un choix : joindre la page intacte, récupérer seulement son texte
enrichi, ou annuler. Les scripts des anciennes versions restent lisibles comme code.

Collez une URL seule dans le document : elle devient un lien cliquable, sans modale.
Cliquez sur ce lien puis **Afficher une carte** dans le menu flottant de CKEditor pour insérer
le titre, la description disponible et une miniature, notamment pour YouTube. **Afficher l’URL**
dans le menu de la carte permet de revenir au lien. La carte est récupérée seulement après ce choix.
Vous pouvez répéter ces changements d’affichage : une carte avec miniature est réutilisée pendant
l’édition, sans télécharger à nouveau la page ni dupliquer sa pièce jointe.
Si un site refuse les aperçus automatiques, la carte conserve son adresse sans inventer de métadonnées.
Les pages web utilisent le générateur de captures et le cache des discussions ; YouTube utilise
la miniature de la vidéo. La carte reprend aussi la présentation des aperçus des discussions.
La description publiée par le site est conservée avec la capture et affichée dans les deux contextes.
Dans un bloc de code, l’URL reste du texte.
Les cartes YouTube affichent le lecteur officiel directement dans le document, en lecture et en
édition, sous le titre et la description. Le lecteur occupe toute la largeur de la carte ;
la miniature est masquée pendant cet affichage. Les vidéos restent entièrement visibles, sans
recadrage. Les PDF insérés disposent aussi d’un aperçu en pleine largeur, dans un cadre au
nombre d’or (largeur / hauteur ≈ 1,618). L’icône **Ouvrir le PDF en plein écran**, à droite du titre, ouvre la
visionneuse avec le fichier déjà chargé. L’impression et le PDF conservent
la miniature et le lien. Les aperçus exigent une URL HTTPS
publique ; un lien simple reste possible. La miniature est conservée avec le document.
Un lien vers une pièce jointe ouvre sa visionneuse (Ctrl/Cmd-clic en édition).

Les aperçus ont deux présentations communes : **bloc en page**, intégré au contenu avec son
lecteur éventuel, et **bloc sous page**, horizontal : miniature à gauche, informations à droite,
avec ses actions en icônes. Les blocs sous les
documents et les aperçus des discussions utilisent le même composant.
L’URL éventuelle apparaît sur sa propre ligne sous les autres informations.
Les miniatures conservent les proportions et la transparence du fichier : elles sont réduites
dans une limite de 520 × 320 pixels, sans ajout de bandes blanches. Leur affichage occupe la
hauteur ou la largeur disponible selon leur format, en gardant l’image entière.

Le bouton **Imprimer** de l’éditeur ouvre la boîte d’impression du navigateur avec le contenu
en cours, y compris les modifications non encore enregistrées. L’impression conserve les
images, tableaux et encadrés sur fond clair, sans les commandes de l’éditeur. Elle utilise
le contenu statique du document : les scripts et leurs éléments générés ne sont pas imprimés.

Dans le bloc **Édition**, **Exporter en PDF** télécharge directement le contenu en cours
sous le nom du document, avec l’extension `.pdf`. Le texte reste sélectionnable ; les images,
tableaux et encadrés sont conservés sur des pages A4 claires. Comme pour l’impression, seuls
les contenus statiques sont exportés. L’export nécessite les droits de lecture et ne crée
pas de révision du document.

L’icône pleine de fichier compressé de Bootstrap Icons, dont l’infobulle indique **Exporter le document et ses pièces jointes (ZIP)**, télécharge un fichier
contenant `document.html` et un dossier `attachments/`. Décompressez l'ensemble pour conserver
les liens entre le texte et les fichiers. La limite est de 64 Mio, dont 12 Mio pour le texte
et les images intégrées. Les éventuelles dépendances externes des fichiers restent externes.

Les documents s’ouvrent en **Largeur fixe** : une page A4 avec des marges de 10 mm, adaptée
à l’impression. Un bouton à icône bascule entre largeur fixe et **Pleine largeur** pour travailler
sur de grands tableaux ; il est activé en pleine largeur. Il fonctionne aussi en plein écran et ne modifie pas
le contenu enregistré. Sur mobile, la page s’adapte à la largeur de l’écran.

## Images des documents

Les documents de travail ordinaires permettent de choisir une image locale, de la coller ou
de la déposer avec les commandes natives de CKEditor. Sa barre contextuelle permet de renseigner
le texte alternatif, la légende et la largeur. Le téléversement affiche sa progression.
Les images restent des pièces jointes du document, disponibles via le bouton **Pièces jointes**.

Les images ne sont pas autorisées dans les autres mémoires, profils, tâches, descriptions ou
suivis de Goals. Cette règle reste valable lorsqu’un document Goal est ouvert dans la
bibliothèque. Les images distantes par URL et les SVG ne sont pas acceptés.

Retirer une image du texte conserve sa pièce jointe. Supprimer cette pièce jointe la retire de
la liste, mais les versions historiques restent restaurables avec les droits actuels. Oublier
définitivement le document supprime aussi ces ressources, sauf protection métier.

## Enregistrement et historique

Un document se sauvegarde automatiquement. Attendez l’état enregistré avant de fermer votre
navigateur. Un brouillon est également conservé dans l’onglet pour retrouver une édition
interrompue. Si deux personnes modifient le même contenu, un message conserve votre brouillon
et vous laisse choisir entre votre version et la version distante. Aucun choix automatique
ne remplace une modification concurrente.

L’historique présente les versions dans leur format d’origine et permet de comparer contenu,
liens, tableaux et images. Restaurer une version crée une nouvelle révision ; cela ne rétablit
pas les anciens partages. La fiche de poste et la personnalité sont également conservées en
HTML dans les prompts des agents. L’inspection propose la source exacte et un aperçu riche.

Après cette mise à jour, rechargez l’application ou la PWA. Un ancien client est refusé lors
d’une écriture éditoriale ; conservez d’abord tout brouillon encore présent dans cet ancien écran.
Les skills et leur édition Markdown restent inchangés.

Les contenus riches suivent automatiquement le thème clair ou sombre de l’application, en
lecture comme en édition et en plein écran. Texte, fond, liens, tableaux et code changent
ensemble ; les surlignages gardent une encre sombre lisible sur leur couleur pastel. Changer
de thème ne modifie pas le contenu enregistré.

Sélectionnez une image pour afficher les poignées natives : faites glisser un coin pour régler
sa largeur en conservant les proportions, ou utilisez le menu de taille. Déplacez l’image par
glisser-déposer. La barre contextuelle permet aussi de régler l’habillage, la légende et le
texte alternatif. Chaque modification peut être annulée.

Dans un tableau, la barre contextuelle expose directement lignes, colonnes, en-têtes,
fusion/séparation et suppression. Sélectionnez plusieurs cellules par glissement avant de les
fusionner ; faites glisser leur bordure verticale pour redimensionner une colonne. Les commandes
inapplicables sont désactivées. Les mises en forme actives sont indiquées en bleu dans la barre
principale, dont les commandes sont regroupées et les icônes compactes.


## Dicter et écouter un texte enrichi

Dans **Mon profil**, le bloc **Modèles** permet de choisir vos réglages personnels.
Pour un autre utilisateur, ouvrez **Utilisateurs → Modifier → Modèles** avec le droit de
modifier les utilisateurs. Ces deux formulaires proposent le même choix de profil et de voix
que les agents, avec l’option de suivre le profil courant. Sélectionnez un profil
dont le modèle de transcription est configuré, puis une voix de synthèse pour la lecture.
Sans profil sélectionné, le profil courant est utilisé. Un profil sélectionné mais incomplet
ne reprend pas les modèles d’un autre profil. Le choix de voix distingue TTS et voix natives
temps réel ; la lecture documentaire nécessite une voix TTS. Les réglages ne sont pas dans
les documents.

Placez le curseur dans le texte, puis cliquez sur l’icône **Dictée** du groupe **Lecture** et
autorisez le microphone. Le texte s’inscrit automatiquement au curseur pendant que vous parlez,
au rythme des transcriptions. L’icône devient **Arrêter la dictée** ; cliquez à nouveau pour
terminer. Le texte est sauvegardé comme les autres éditions. Une capture est limitée à cinq minutes et
20 Mio. La dictée nécessite le droit d’écriture et un navigateur compatible, sur HTTPS ou localhost.

**Lire le texte** lit uniquement le texte sélectionné s’il y a une sélection, sinon tout
le contenu de l’éditeur, avec votre voix. La sélection est figée au démarrage de la lecture. Le HTML, les attributs de mise
en page et les scripts ne sont pas envoyés à la synthèse vocale. Les titres, paragraphes, listes
et tableaux conservent leur texte et leur ordre. Des retours à la ligne séparent les blocs,
les éléments de liste et les cellules des tableaux ; les sauts de ligne du texte sont conservés.
Les documents longs sont lus par morceaux.
Le bouton de lecture démarre la restitution, puis permet de mettre en pause ou de reprendre.
La flèche à sa droite ouvre le menu **Pause** / **Arrêter la lecture**, sans démarrer la lecture.
**Reprendre** continue au même endroit après une pause. Remplacer le contenu ou fermer l’éditeur
arrête aussi la capture ou la lecture en cours. L’audio utilise les fournisseurs configurés dans Galaris.

## Partager un document ou un item mémoire

Les nouvelles ressources sont **Privées**. Cliquez sur le champ **Partage** pour ouvrir les choix :

- **Public**, en lecture ou en écriture, donne accès aux utilisateurs et agents de l’application.
- **Groupes** ajoute les groupes actuels du propriétaire avec le droit choisi.
- La recherche filtrable permet de choisir un groupe, une personne ou un agent. Cliquez sur
  l’œil pour accorder la lecture, ou sur le crayon pour accorder l’écriture, qui inclut la lecture.

Chaque partage apparaît dans un badge gris avec son avatar lorsqu’il s’agit d’une personne ou
d’un agent. L’icône du badge bascule le droit ; sa croix retire cet accès. Les changements sont
enregistrés immédiatement. Un échec conserve l’affichage des derniers droits confirmés et propose
de les recharger. Le propriétaire conserve toujours son accès.

Les groupes sélectionnés restent les mêmes lors d’un changement de propriétaire ou de ses
appartenances. En revanche, leurs membres actuels bénéficient du partage : quitter un groupe
retire l’accès qu’il accorde. Les accès déjà couverts sont exclus ou désactivés dans la recherche.
Elle affiche dix résultats par page, avec une pagination et un choix de taille de page.

**Public/Lecture** permet d’ajouter des rédacteurs particuliers. Basculer leur badge en lecture
retire le partage devenu redondant. **Public/Écriture** remplace les accès particuliers et ne
propose aucun ajout. Retirer Public conserve les accès particuliers encore enregistrés.

Les utilisateurs retrouvent leurs documents accessibles dans **Partagés avec moi**, même sans
agent. Les droits couvrent le texte, les pièces jointes, les aperçus, les exports et l’historique.
Un droit d’écriture ne donne pas le droit de repartager ; le propriétaire et les administrateurs
autorisés gèrent les destinataires. Public reste soumis à l’authentification de l’application.
