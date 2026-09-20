# 0112 — Actions contextuelles des dossiers et dossiers avant documents

Statut : Accepted

La ligne d'un dossier expose au survol et au focus une barre d'actions : créer un frère
immédiatement après le dossier, créer un enfant, modifier le nom/l'icône et supprimer.
Le bouton Modifier remplace le double-clic ; les raccourcis clavier restent disponibles.
La barre reste visible sur écran mobile ou sans survol. Un menu complémentaire propose le
tri A→Z/Z→A et le dépliage/repliage de la branche entière.

Les dossiers précèdent toujours les documents dans l'arborescence, y compris pour les
positions enregistrées avant cette décision. Les déplacements manuels conservent l'ordre
relatif au sein de chaque catégorie ; la possibilité historique d'intercaler un document
avant un dossier n'est plus un contrat.

Le tri alphabétique porte sur les enfants directs du dossier. Il enregistre atomiquement
les positions privées, séparément pour les dossiers puis les documents, sans changer les
révisions ni les droits des documents. Il ignore la casse et les accents. Il ne définit pas
un mode de tri automatique pour les créations suivantes. Le service refuse un dossier appartenant
à un autre utilisateur et publie la notification de classement ciblée définie par la décision 0110.

Le dépliage/repliage est local à l'interface, comprend tous les sous-dossiers et conserve le
cache des branches. La création d'un frère utilise la création puis l'ancrage persisté existants ;
si l'ancrage échoue, le dossier créé reste visible et modifiable avec un avertissement explicite.

Les tests PostgreSQL couvrent la persistance, les accents, l'isolation et les documents en lecture
seule. Les tests navigateur couvrent les actions au clavier et sur mobile, la réouverture, le tri,
le dépliage ciblé et les erreurs de mutation.
