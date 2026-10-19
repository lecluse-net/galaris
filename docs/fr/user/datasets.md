<p align="right"><strong>Français</strong> · <a href="../../en/user/datasets.md">English</a></p>

# Jeux de données

Ouvrez **Connaissances → Jeux de données** pour créer un ensemble de données JSON.
Les jeux de données se gèrent dans cette bibliothèque dédiée ; ils ne figurent plus
dans la bibliothèque Documents ni dans sa création.
Un ancien lien documentaire vers un jeu de données ouvre désormais son éditeur dédié.
Un document HTML peut lire ses valeurs pour les afficher ou les utiliser, avec les droits
et l'autorisation de son lecteur. Dans la barre d'outils, **Insérer un lien ou un fichier**
puis **Ajouter une PJ interne** ouvre le sélecteur file_share : choisissez l'emplacement
`data://`, puis les jeux souhaités. Leurs citations sont insérées dans le texte, sans PJ.
Le jeu conserve son adresse, son historique et son partage. Retirer la citation ne supprime
pas les données ; partager le document ne partage pas ses jeux de données.
Cliquez sur un jeu de données pour ouvrir son éditeur dans une modale, sur ordinateur
comme sur petit écran. Fermez-la avec la croix, Échap ou un clic sur l’arrière-plan pour
retrouver la liste, sa recherche et sa page courante. Les modifications non enregistrées
demandent confirmation avant de fermer. Dans le chat, les cartes Dataset ouvrent cette
même modale dédiée avec le contenu JSON complet, l’historique et les droits disponibles.
Dans un document, collez une adresse `data://` ou le lien `/dataset/…` de cette installation,
puis choisissez **Afficher une carte** dans le menu contextuel du lien. Le clic sur le titre
de la carte ouvre la modale Dataset sans quitter le document. Le contenu JSON reste dans
le Dataset ; le document conserve uniquement sa référence.
Le filtre **Agent propriétaire** limite la liste aux jeux d'un agent géré. **Tous les agents**
rétablit tous les jeux accessibles, y compris ceux appartenant à un utilisateur. La recherche
et la pagination s'appliquent au résultat filtré.
Chaque jeu de données possède une adresse `data://`, un partage et un historique propres.
Les nouveaux jeux de données se créent ici, séparément des Documents HTML. Un agent utilise
`file_create(path="data://", name="Réponses", content="[]")` et conserve l'adresse retournée.
Le contenu JSON complet est obligatoire ; il ne faut pas fabriquer une adresse `document://`
en remplaçant le début de l'adresse obtenue.
Les anciens liens documentaires de jeux de données migrés continuent de viser ces mêmes
données ; les modifications et révocations de partage s'appliquent aux deux adresses.
Son contenu peut être un objet, un tableau ou une valeur simple, sans schéma associé.
L'éditeur conserve votre texte en cas de JSON invalide ou de conflit : rechargez
uniquement après avoir conservé les modifications que vous souhaitez reprendre.
Le JSON est indenté à l'ouverture et dans l'historique. Cet affichage conserve les valeurs
exactes et n'enregistre aucune modification à lui seul.

Lorsqu'un agent met à jour une partie du JSON, ses lectures lui fournissent les repères
de ligne nécessaires à l'édition, avec la révision à respecter et les lignes partielles
à compléter avant remplacement.

**Propriétaire** et **Partage** figurent sur une même ligne. Le propriétaire ou un administrateur
autorisé peut transférer le jeu de données à un agent qu'il gère ou à lui-même ; un administrateur
des jeux de données peut aussi choisir un autre utilisateur actif. Le transfert est immédiat,
conserve le brouillon et l'historique, et laisse l'ancien propriétaire en écriture.
Les jeux en lecture seule ne peuvent pas être transférés.

Dans l'éditeur, **Partage** reprend les règles des Documents : privé, groupes ou public
pour les utilisateurs authentifiés, avec des destinataires agents, utilisateurs ou groupes
en lecture ou en écriture. Seul le propriétaire ou un administrateur autorisé peut modifier
ce partage ; le droit d'écriture ne donne pas le droit de repartager. Les groupes suivent
leurs membres actuels. Un jeu de données en lecture seule ne peut pas être repartagé.

**Utilisations** liste les documents qui contiennent sa référence, les définitions et
exécutions de processus qui le référencent, et les agents dont les traces d'outils conservées
mentionnent son URI. Chaque catégorie respecte vos droits sur ses sources. Les URI construites
dynamiquement et les historiques déjà purgés peuvent manquer ; une mention dans une trace
ne prouve pas que l'accès a réussi.

**Supprimer** demande confirmation et retire l'accès au jeu de données. Ses contenus
historisés restent conservés ; les références existantes peuvent devenir indisponibles.
Les anciens jeux de données créés pour des processus se suppriment selon les mêmes droits.
Les données et fichiers des exécutions actuelles sont stockés dans les runs et restent indépendants.

Les applications HTML/JavaScript dans les Documents peuvent lire et alimenter ces données
via le pont Dataset, avec vos droits et votre consentement personnel pour la révision
courante du Document. Partagez séparément la page et les jeux de données utilisés.
Voir les [applications documentaires](../dev/document-apps.md).

Pour un processus métier, l'agent recueille les informations manquantes et prépare les
variables au format attendu par le processus. Le moteur valide ces variables avant
l'exécution. Les pièces jointes conservent leurs URI de fichiers autorisées.

Chaque document, jeu de données et définition de processus conserve un partage indépendant. Modifier les droits d’une ressource ne modifie pas ceux d’une autre ressource liée. La mise à jour conserve les partages existants, y compris les accès par groupe. Voir le [mécanisme de partage](../dev/sharing.md).
