<p align="right"><strong>Français</strong> · <a href="../../en/user/documents.md">English</a></p>

# Organiser la bibliothèque documentaire

Ouvrez **Connaissances → Documents** (`/documents`) pour créer et classer les contenus
HTML accessibles. Les [jeux de données JSON](datasets.md) et les [processus](internal-processes.md)
ont leurs bibliothèques propres. Le classement est personnel : il ne donne aucun droit
supplémentaire et ne change pas l'organisation des autres lecteurs.


## Créer et retrouver

Dans la bibliothèque **Documents**, chaque dossier propose une icône **Nouveau document**
parmi ses actions. Renseignez le titre et le propriétaire : le document est automatiquement
classé dans ce dossier, qui se déplie, puis s’ouvre dans l’éditeur. Le bouton de création
général conserve les nouveaux documents parmi les documents non classés.

Dans les filtres de la bibliothèque, le champ unique **Propriétaire** remplace le choix
séparé du type et du nom. Il affiche **Moi**, les utilisateurs, puis les agents ; la recherche
et la pagination par type permettent d’atteindre les grandes listes. Effacer ce champ
rétablit tous les propriétaires ; les autres filtres restent applicables.

## Classer dans les dossiers et sous-documents

Le bouton **⋮** de chaque dossier et le clic droit ouvrent le même menu avec les icônes et les libellés de toutes ses
actions : afficher en liste, créer un document ou un dossier, modifier, trier, déplier,
replier et supprimer. Les raccourcis **Nouveau document**, **Nouveau sous-dossier**, **Modifier**
et **Supprimer** restent visibles sur la ligne, y compris sur mobile.
Au clavier, activez le bouton **⋮** ou utilisez **Maj + F10** sur le dossier ; **Échap** ferme le menu.

Un document peut aussi contenir des **sous-documents**. Utilisez son icône
**Nouveau sous-document**, ou glissez un document existant au centre de sa ligne.
La flèche permet de déplier ses enfants, sur plusieurs niveaux ; cliquer sur le titre
continue d'ouvrir le document. Pour sortir un enfant de son parent, glissez-le dans la zone
des documents non classés ou dans un dossier.
Cette hiérarchie est personnelle, comme les dossiers : chaque document conserve ses
propres droits de partage. Supprimer le parent conserve les enfants ; ceux qui restent
lisibles réapparaissent parmi les non-classés, également si l'accès au parent est retiré.

Après confirmation du serveur, un document déplacé prend sa nouvelle place et un document
supprimé disparaît aussitôt. Le rafraîchissement des listes continue en arrière-plan sans
bloquer le déplacement suivant. Si le serveur refuse un déplacement, le classement reste
inchangé et vous pouvez réessayer.

## Afficher une liste et agir sur la sélection

L’action **Afficher le dossier en liste** ouvre une liste paginée avec titres, miniatures,
propriétaires et mots-clés. Cochez **Inclure les sous-dossiers et sous-documents** pour
parcourir aussi ses descendants. L’action **Afficher les documents non classés en liste**,
près de la recherche, présente les documents sans classement personnel. La pagination
propose 10, 20, 50, 100 ou 500 documents, avec 50 par défaut.

Sélectionnez des documents ou cochez **Sélectionner cette page**, puis ouvrez
**Actions sur la sélection** : supprimer après confirmation, changer le propriétaire,
ajouter ou retirer des mots-clés, ajouter, modifier ou retirer un partage. La sélection
concerne uniquement la page affichée et se vide lors d’un changement de page ou de recherche.
Chaque ajout ou retrait conserve les autres mots-clés et partages propres à chaque document.
Un droit de lecture ou d’écriture s’applique au destinataire choisi sur toute la sélection ;
retirer son partage explicite ne supprime pas les droits hérités d’une équipe ou du partage public.
Les droits du propriétaire restent attachés à la propriété. Un bilan indique les réussites
et les échecs, avec les documents encore accessibles en échec sélectionnés pour une nouvelle tentative.
Une modification concurrente est refusée plutôt que d’écraser les réglages récents.

## Utiliser les raccourcis

Dans la bibliothèque, survolez une ligne de dossier ou de document, ou placez-y le focus
au clavier, pour utiliser les raccourcis. **F2** renomme, **F3** crée un document dans le
dossier ou un sous-document du document, **F4** ouvre le dossier en liste ou le document,
et **F7** crée un sous-dossier (un sous-document sur une ligne de document).
**Suppr** ouvre la confirmation de suppression de la ligne ciblée ; il ne supprime pas la
sélection en masse. Les raccourcis sont suspendus pendant la saisie, dans les menus et les
dialogues, et respectent les droits et protections de chaque document. Le menu contextuel
des dossiers rappelle les touches disponibles.

## Retrouver les changements

Dans **Documents**, les rafraîchissements courants mettent à jour les lignes concernées
sans vider l’arborescence ni la liste. Les dossiers ouverts et les filtres restent en place,
y compris après une reconnexion. Une erreur de rafraîchissement permet de réessayer en
conservant les documents affichés ; une révocation d’accès les retire immédiatement.

## Écrire et partager

Pour faire évoluer un document avec un agent, demandez une mise à jour des passages concernés.
L'agent conserve les informations utiles et peut ajouter des éléments distincts ; les anciennes
versions restent dans les révisions. Précisez si le résultat attendu est un journal chronologique
ou un compte rendu : cette chronologie reste alors pertinente dans le document.

Le [guide des contenus riches](rich-content.md) explique l'édition, les liens et cartes,
les pièces jointes, le partage, les versions et les exports. Pour travailler à côté d'un
agent, ouvrez un document depuis la rubrique Documents de la discussion.
