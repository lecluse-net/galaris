<p align="right"><strong>Français</strong> · <a href="../../en/user/datasets.md">English</a></p>

# Jeux de données

Ouvrez **Connaissances → Jeux de données** pour créer un ensemble de données JSON.
Sur ordinateur, la liste à gauche permet de sélectionner le jeu de données affiché à droite,
sans arborescence. La recherche et la page courante restent en place lors du changement de
sélection. Sur petit écran, **Retour à la liste** permet de quitter l'éditeur. Les modifications
non enregistrées demandent confirmation avant de changer de jeu de données.
Chaque jeu de données possède une adresse `data://`, un partage et un historique propres.
Les anciens liens documentaires de jeux de données migrés continuent de viser ces mêmes
données ; les modifications et révocations de partage s'appliquent aux deux adresses.
Son contenu peut être un objet, un tableau ou une valeur simple, sans schéma associé.
L'éditeur conserve votre texte en cas de JSON invalide ou de conflit : rechargez
uniquement après avoir conservé les modifications que vous souhaitez reprendre.

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
Les jeux de données gérés par le moteur des processus suivent leur propre cycle de vie.

Les applications HTML/JavaScript dans les Documents peuvent lire et alimenter ces données
via le pont Dataset, avec vos droits et votre consentement personnel pour la révision
courante du Document. Partagez séparément la page et les jeux de données utilisés.
Voir les [applications documentaires](../dev/document-apps.md).

Pour un processus métier, l'agent recueille les informations manquantes et prépare les
variables au format attendu par le processus. Le moteur valide ces variables avant
l'exécution. Les pièces jointes conservent leurs URI de fichiers autorisées.
