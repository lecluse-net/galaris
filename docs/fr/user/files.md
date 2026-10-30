<p align="right"><strong>Français</strong> · <a href="../../en/user/files.md">English</a></p>

# Explorer les fichiers d’un agent

L’accès à **Fichiers** utilise `FILE_ACCESS` ou `FILE_EDIT`. Le second autorise aussi les
mutations de fichiers. Les Documents, Datasets et souvenirs conservent leurs propres droits :
un droit Fichiers ne les ouvre pas, et lire une pièce jointe depuis son domaine ne demande
pas un droit global Fichiers. Les périmètres des agents et les ACL restent appliqués.
**Préférences → Fichiers** (`/params/files`) rassemble l’indexation : sélectionnez un agent
pour consulter ses parcours, lancer ou annuler une indexation et relancer les réparations.
Cette page utilise séparément `FILE_INDEX_ACCESS` ou `FILE_INDEX_RUN` ; le second autorise
les actions. Elle est accessible sans droit d’exploration Fichiers ni droit Dream.

Lorsqu'une suppression est confirmée, ou que l'indexation constate la disparition d'un
fichier externe, l'item mémoire lié est supprimé avec ses contenus et index si aucune
autre URI ne le rattache à une ressource. Une panne ou un refus d'accès ne déclenche
pas cet effacement. Un item partagé entre plusieurs emplacements reste conservé
jusqu'à la disparition du dernier emplacement.

Dans **Connaissances → Fichiers**, cliquez sur la carte d’un agent pour ouvrir son
navigateur. Le sélecteur permet ensuite de changer d’agent sans désélectionner
l’agent courant. Le compteur à sa droite indique les éléments chargés
dans le répertoire courant. L’arborescence présente les
schémas connus de son système de fichiers virtuel : console SSH, documents,
ressources Galaris et fournisseurs connectés. Elle respecte le périmètre des agents
que vous pouvez gérer et les droits propres à chaque ressource.

Lorsqu’aucun emplacement n’est sélectionné, la grille centrale affiche les schémas
disponibles sous forme de dossiers. Cliquez sur l’un d’eux pour ouvrir sa racine,
puis un répertoire dans l’arborescence ou dans la grille centrale.
Le fil d’Ariane et le bouton de répertoire parent permettent de remonter. Les fichiers
disposent d’une miniature lorsque leur format peut être rendu ; une icône reste
disponible sinon. Cliquez sur un fichier pour afficher son aperçu, sur un Document,
une tâche, un Dataset ou un échange pour ouvrir sa vue métier existante. Les formats
sans lecteur intégré se téléchargent.

Dans **Galaris → Skills**, cliquez sur un skill générique ou personnel pour ouvrir sa
modale de lecture, avec `SKILL.md` affiché en premier. Ses fichiers restent consultables
dans cette modale. Les skills génériques sont regroupés dans des dossiers virtuels portant
le nom de leur catégorie ; **Sans catégorie** rassemble les skills non classés.
Seules les catégories contenant des skills accessibles sont affichées. Le classement ne
déplace aucun fichier et conserve les liens des skills, même après renommage ou changement
de catégorie. **Compétences personnelles** conserve les dossiers nommés d’après le prénom
et le nom de chaque agent. Le sélecteur de pièces jointes permet toujours de parcourir les
fichiers du skill.

Dans **Documents** (`document://`), les répertoires apparaissent directement à la racine,
avec les fichiers qui ne sont classés dans aucun répertoire accessible. Ouvrir un répertoire
affiche ses sous-répertoires et ses fichiers, sans mélanger les fichiers des niveaux inférieurs.
Un fichier classé dans plusieurs répertoires apparaît dans chacun d’eux ; son URL reste la même.
Le fil d’Ariane suit les noms des répertoires, y compris après l’ouverture d’un lien direct.
Les répertoires deviennent visibles dès qu’un document accessible se trouve dans leur branche,
même sans partage explicite du répertoire. Les classements de tous les utilisateurs sont pris
en compte ; les autres fichiers restent soumis à leurs propres droits.

Les documents Texte et Données sont regroupés dans cet emplacement. Les documents Texte
affichent une miniature et les documents Données leur icône dédiée. Il n’y a plus
d’emplacement `data://` séparé dans Fichiers ; les URI `data://…` existantes restent utilisables.

Dans **Galaris → Goals**, cliquez sur un objectif pour ouvrir directement sa modale.
Les cycles ne sont pas affichés dans les listes ni dans la recherche de Fichiers ;
consultez-les depuis le Goal. Les objectifs sans cycle restent accessibles.

Dans **Galaris → Dépôts de code**, cliquez sur le chemin d’un dépôt pour ouvrir
l’éditeur de code. L’accès exige `CODE_ACCESS` et les droits propres au dépôt.
Fermer la fenêtre masque l’éditeur ; le rouvrir conserve les fichiers non enregistrés.

Les boutons **Précédent** et **Suivant** du navigateur retrouvent les agents,
emplacements et répertoires visités. Le fil d’Ariane et le bouton de répertoire parent
participent au même historique. L’URL conserve l’agent et l’emplacement courants :
vous pouvez la copier ou recharger la page pour les retrouver, sous réserve de vos droits.
La navigation du sélecteur de pièces jointes reste locale à sa fenêtre.
Si un jeu de données ouvert contient un brouillon non enregistré, le retour demande
confirmation avant de le fermer ; annuler conserve le brouillon et l’emplacement courant.

Un clic droit sur un fichier ou un répertoire ouvre son menu contextuel ; au clavier,
utilisez **Maj+F10** sur l’élément. Sur mobile, un appui prolongé ouvre ce menu ; les
icônes sont plus petites et le bouton **⋮** est masqué. Sur ordinateur, ce bouton donne
accès aux mêmes actions dans la grille. Le menu propose **Renommer** et **Supprimer** selon vos
droits d’édition et les capacités du fournisseur. Les répertoires de la console SSH,
de Nextcloud et de Samba peuvent ainsi être renommés et supprimés ; les racines restent protégées.
Sur un dépôt Git dans `console://`, le menu propose aussi **Ouvrir dans l’éditeur de code**
avec le privilège `CODE_ACCESS`. Les checkouts et les worktrees sont reconnus à l’ouverture
du menu. Utilisez le menu du dossier ou faites un clic droit dans la zone des fichiers
du dépôt ouvert. Le clic revérifie les droits du dépôt et ouvre l’éditeur sans créer de discussion.
Fermer puis rouvrir l’éditeur conserve les brouillons non enregistrés dans le navigateur.

Pour renommer, saisissez le nom complet, extension comprise pour un fichier, puis validez.
Le contenu est conservé et aucun élément existant n’est écrasé. Les fichiers internes et
pièces jointes gardent leur URI ; un fichier ou répertoire externe change de chemin.
Une erreur conserve la saisie pour réessayer. Le nom interne est commun aux vues métier,
aux aperçus et aux téléchargements.

La suppression demande confirmation et, pour un répertoire, inclut tout son contenu.
Seuls les fichiers internes indépendants de l’agent sont supprimables depuis `file://` ;
les pièces jointes possédées par un domaine conservent ses règles de suppression.
Les projections métier et sources en lecture seule ne proposent pas de mutation.
Après une action, la grille et l’arbre sont actualisés. Si le répertoire ouvert est
supprimé, le navigateur revient à son parent. En cas d’échec pendant une suppression,
actualisez pour vérifier les éléments restants avant de réessayer.

Les vidéos des partages Samba, Nextcloud/WebDAV, AFFiNE, de la console SSH et des
fichiers internes se lisent progressivement, sans attendre le téléchargement complet.
Le lecteur peut demander directement une autre portion pour avancer dans la vidéo ;
la limite de 512 Mio des aperçus téléchargés ne s’applique pas à ce parcours.
Le format et les codecs doivent être pris en charge par votre navigateur. Les liens
HTTPS publics utilisent aussi cette lecture lorsque leur taille est connue ; si le
serveur distant ignore les plages d’octets, un déplacement peut nécessiter de relire
les octets précédents. Les autres fournisseurs conservent leur aperçu habituel.

La liste se complète en défilant, sans contrôle de pagination. L’arborescence affiche
uniquement les sous-répertoires reçus au fil du chargement, sans message ni contrôle
de pagination ; s’il n’y en a aucun, rien n’est affiché dessous. Après une erreur,
**Réessayer** reprend le chargement sans supprimer les fichiers déjà affichés.
**Actualiser** relit le répertoire courant. Changer d’agent ferme ses aperçus et
retire immédiatement les fichiers de l’agent précédent.

Les schémas s’ouvrent comme des rubriques d’accordéon sans flèche. L’arborescence
contient uniquement les répertoires visibles. Les messages d’état et les erreurs
s’affichent dans la zone centrale des fichiers ; les erreurs et leur bouton
**Réessayer** sont signalés en rouge. Les fichiers et répertoires cachés, dont le nom commence par un
point, sont masqués. Seuls les schémas permettant de lister les fichiers à leur racine
sont affichés. Les autres restent accessibles par leurs URI.

Sur mobile, **Afficher les emplacements**, près du fil d’Ariane, ouvre l’arborescence.
La navigation se fait par les emplacements, les répertoires et le fil d’Ariane.
Les fournisseurs sans curseur de continuation signalent cette limite ; ouvrez un
sous-répertoire disponible pour poursuivre.

La racine `file://` contient les fichiers internes indépendants de l’agent sélectionné
et les pièces jointes auxquelles il a accès. Chaque fichier apparaît une seule fois,
même s’il porte plusieurs références. Les droits des pièces jointes restent ceux de
leur domaine propriétaire ; un retrait d’accès s’applique au prochain chargement.
La console n’apparaît
que si l’agent possède une connexion SSH active ; elle est limitée à son répertoire
personnel. Cette page n’ajoute aucun droit ni aucune copie persistante de fichier.
