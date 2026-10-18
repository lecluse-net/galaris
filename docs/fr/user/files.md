<p align="right"><strong>Français</strong> · <a href="../../en/user/files.md">English</a></p>

# Explorer les fichiers d’un agent

Dans **Connaissances → Fichiers**, cliquez sur la carte d’un agent pour ouvrir son
navigateur. Le sélecteur permet ensuite de changer d’agent sans désélectionner
l’agent courant. Le compteur à sa droite indique les éléments chargés
dans le répertoire courant. L’arborescence présente les
schémas connus de son système de fichiers virtuel : console SSH, documents, données,
ressources Galaris et fournisseurs connectés. Elle respecte le périmètre des agents
que vous pouvez gérer et les droits propres à chaque ressource.

Ouvrez une racine, puis un répertoire dans l’arborescence ou dans la grille centrale.
Le fil d’Ariane et le bouton de répertoire parent permettent de remonter. Les fichiers
disposent d’une miniature lorsque leur format peut être rendu ; une icône reste
disponible sinon. Cliquez sur un fichier pour afficher son aperçu, sur un Document,
une Task, un Dataset ou un échange pour ouvrir sa vue métier existante. Les formats
sans lecteur intégré se téléchargent.

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
point, sont masqués. Tous les schémas connus sont affichés, y compris HTTPS.
Un message précise lorsqu’un schéma permet l’accès par URI sans liste à sa racine.

Sur mobile, **Afficher les emplacements**, près du fil d’Ariane, ouvre l’arborescence.
La navigation se fait par les emplacements, les répertoires et le fil d’Ariane.
Les fournisseurs sans liste à leur racine ou sans curseur de continuation
signalent cette limite ; ouvrez un sous-répertoire disponible pour poursuivre.

La racine `file://` contient les fichiers internes indépendants de l’agent sélectionné
et les pièces jointes auxquelles il a accès. Chaque fichier apparaît une seule fois,
même s’il porte plusieurs références. Les droits des pièces jointes restent ceux de
leur domaine propriétaire ; un retrait d’accès s’applique au prochain chargement.
La console n’apparaît
que si l’agent possède une connexion SSH active ; elle est limitée à son répertoire
personnel. Cette page n’ajoute aucun droit ni aucune copie persistante de fichier.
