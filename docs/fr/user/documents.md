<p align="right"><strong>Français</strong> · <a href="../../en/user/documents.md">English</a></p>

# Organiser la bibliothèque documentaire

Ouvrez **Connaissances → Documents** (`/documents`) pour créer et classer les contenus
HTML accessibles. Les [jeux de données JSON](datasets.md) et les [processus](internal-processes.md)
ont leurs bibliothèques propres. Le classement est personnel et ne change pas
l'organisation des autres lecteurs. Un répertoire peut accorder automatiquement des droits
supplémentaires sur vos documents, sans partager votre arborescence.

Les documents et leurs résumés partagés sont indépendants des souvenirs personnels
des agents. Partager un document ne partage aucun souvenir ; supprimer une référence
dans le graphe mémoire ne supprime pas le document. Les souvenirs concernant un
document restent privés à l'agent qui les a acquis.


## Rédiger avec un agent

L'icône **Conversation**, dans le groupe **Lecture** de la barre d'outils de l'éditeur,
affiche un panneau à droite du document sur ordinateur. Faites glisser la poignée entre
le document et le chat pour ajuster leurs largeurs, comme entre la bibliothèque et le
document. Au clavier, placez le focus sur cette poignée et utilisez les flèches gauche/droite.
Recherchez une conversation existante ou utilisez **Nouvelle conversation avec un agent**.
Le sélecteur affiche l'avatar de chaque agent et propose une pagination pour les longues
listes : 50 conversations par défaut, avec un choix de 10, 20, 50, 100 ou 500 par page.
Changer de page ou rechercher une conversation conserve l'échange ouvert et son brouillon.
Les échanges restent des conversations accessibles dans **Discussion**. Documents
privilégie la rédaction autour du contenu ouvert ; Discussion privilégie les échanges
et le suivi des activités.

Avant un envoi, les modifications du document sont sauvegardées. Le document ouvert est
indiqué à l'agent sans modifier ses droits d'accès. Si la sauvegarde échoue, le message
reste dans le champ de saisie. Masquer le panneau sur ordinateur conserve la conversation
et le message en cours. Sur mobile, l'icône ouvre une fenêtre de conversation.
L'accès, la création et l'envoi respectent les mêmes privilèges que Discussion.
Une conversation affichée ne produit ni notification sonore, ni toast, ni notification
système pour ses nouveaux messages. Les messages effectivement visibles sont marqués lus.
Masquer le panneau ou l'onglet rétablit les notifications des nouveaux messages non consultés.

Sélectionnez un passage à la souris ou au clavier, puis écrivez votre demande dans le chat.
La sélection est mémorisée avant la perte de focus, même si son surlignage disparaît.
Chaque envoi transmet le texte sélectionné, ses positions de début et de fin et le dernier
curseur, avec l'UUID et la révision sauvegardée du document. Ce fonctionnement est commun
à Documents et au document ouvert dans Discussion. Les positions se rapportent au texte
affiché, pas au HTML. Les extraits longs sont tronqués ; changer de document ou remplacer
son contenu invalide les anciennes positions. Ce contexte reste dans les métadonnées du
message : il ne crée pas de révision documentaire et ne modifie aucun droit d'accès.

Dans l'éditeur, **Plan du document** ouvre à gauche une liste des titres, avec un retrait
selon leur niveau. Tous les titres restent visibles. Le panneau reprend le fond et la
bordure du document. Cliquer sur
un titre rejoint sa section ; le plan suit les modifications des titres et peut être masqué.
L'icône de bibliothèque permet aussi de masquer les dossiers sur ordinateur.

**Liste à cocher** transforme le paragraphe ou la liste sélectionnés en checklist. Cocher
une ligne enregistre son état dans le document, avec sa sauvegarde et ses révisions.
**Entrée** ajoute une ligne ; **Tab** et **Maj+Tab** imbriquent ou désimbriquent les lignes.
Les états restent visibles après réouverture, en lecture seule et dans les exports.
Ces listes ne nécessitent aucun jeu de données.

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

Le clic droit sur chaque dossier ouvre un menu avec les icônes et les libellés de toutes ses
actions : afficher en liste, créer un document ou un dossier, modifier, trier, déplier,
replier et supprimer. Les raccourcis **Nouveau document**, **Nouveau sous-dossier**, **Modifier**
et **Supprimer** restent visibles sur la ligne, y compris sur mobile.
Au clavier, utilisez **Maj + F10** sur le dossier ; **Échap** ferme le menu.

Un document peut aussi contenir des **sous-documents**. Utilisez son icône
**Nouveau sous-document**, ou glissez un document existant au centre de sa ligne.
La flèche permet de déplier ses enfants, sur plusieurs niveaux ; cliquer sur le titre
continue d'ouvrir le document. Pour sortir un enfant de son parent, glissez-le dans la zone
des documents non classés ou dans un dossier.
Cette hiérarchie est personnelle, comme les dossiers : chaque document conserve ses
propres droits de partage, auxquels s'ajoutent ceux de ses répertoires et documents parents.
Supprimer le parent conserve les enfants ; ceux qui restent
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

Dans l’éditeur de document, **Ctrl+F** (ou **Cmd+F**) et l’outil **Rechercher** ouvrent
une barre sous les icônes, avec les champs de recherche et de remplacement. Un nouveau clic
sur **Rechercher** masque la barre ; le texte recherché est conservé à sa réouverture.
Les occurrences sont surlignées pendant la saisie, sans modifier le document. Le contenu
reste accessible. **Entrée** dans la recherche ou **Suivant** sélectionne l’occurrence suivante ; les
options permettent de respecter la casse ou de chercher des mots entiers. **Échap** ou
le bouton de fermeture masque la barre et rend le focus au document.

Pour faire évoluer un document avec un agent, demandez une mise à jour des passages concernés.
L'agent conserve les informations utiles et peut ajouter des éléments distincts ; les anciennes
versions restent dans les révisions. Précisez si le résultat attendu est un journal chronologique
ou un compte rendu : cette chronologie reste alors pertinente dans le document.

Le [guide des contenus riches](rich-content.md) explique l'édition, les liens et cartes,
les pièces jointes, le partage, les versions et les exports. Pour travailler à côté d'un
agent, ouvrez un document depuis la rubrique Documents de la discussion.

## Partage automatique des répertoires

En haut de la liste d'un répertoire (**F4**), le bloc **Partage automatique du répertoire**
permet d'accorder un accès en lecture ou modification à des utilisateurs, agents et groupes,
ou un accès public aux utilisateurs authentifiés. Ces droits se propagent aux sous-répertoires,
documents et sous-documents, y compris ceux ajoutés ensuite. Un document cumule les partages
de tous les répertoires dans lesquels il est classé ; le droit le plus permissif gagne.
Classer un document appartenant à autrui, même modifiable, ne permet pas de le repartager.
Votre arborescence reste personnelle.

Retirer un partage du répertoire, déplacer un document ou supprimer son répertoire retire
uniquement la contribution correspondante. Les partages propres et les autres sources restent
présents. Un droit hérité retiré directement sur un document revient tant que son ancêtre
l'accorde. Chaque `make update` réapplique l'ensemble de ces règles de manière idempotente.
