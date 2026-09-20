<p align="right"><strong>Français</strong> · <a href="../../en/components/resource-previews.md">English</a></p>

# Aperçus des ressources 3D

Les pièces jointes des discussions, les ressources citées dans les messages et les
pièces jointes des documents utilisent la même visionneuse 3D. La miniature ouvre
une vue interactive avec rotation, zoom, déplacement, recentrage et plein écran.
Le fichier original reste téléchargeable. Échap, le bouton de fermeture ou un clic
sur l’arrière-plan ferment la vue.

Les raccourcis s’appliquent quand la scène a le focus, à l’ouverture, après un clic
dans la scène ou après sélection avec Tab. Le bouton d’aide rappelle les commandes.

| Action | Souris | Clavier |
|---|---|---|
| Tourner autour de l’objet | Bouton gauche + glisser | Flèches |
| Déplacer la vue | Bouton droit + glisser | Maj + flèches |
| Zoomer | Molette ou bouton central + glisser | + / − |
| Recentrer | Bouton de recentrage | Début |
| Fermer | Bouton de fermeture ou arrière-plan | Échap |

Sur écran tactile, un doigt tourne autour de l’objet ; deux doigts déplacent la vue
ou zooment par pincement. Le zoom clavier et les boutons respectent les mêmes bornes
que la souris. Les raccourcis du navigateur avec Ctrl, Alt ou Cmd restent disponibles.

| Format | Affichage |
|---|---|
| GLB | Géométrie et matériaux intégrés, glTF 2.0 |
| glTF | Données et textures intégrées dans le fichier |
| OBJ | Géométrie et couleurs de sommets ; matériau neutre sans MTL ni textures externes |
| STL | Géométrie, fichiers ASCII ou binaires |
| PLY | Maillage ou nuage de points, couleurs de sommets lorsqu’elles sont présentes |

Les fichiers STEP, IFC, FBX et les formats natifs des logiciels de création ne sont
pas interprétés par cette visionneuse. Une ressource GLB/glTF avec des fichiers
externes doit être réexportée avec ses dépendances intégrées. Draco et les textures
KTX2 ne sont pas pris en charge ; la compression Meshopt est prise en charge.
L’affichage est statique : les animations ne sont pas jouées. Les dimensions ne
constituent pas des mesures de fabrication.

## Miniatures et chargement

Les miniatures PNG sont générées dans le navigateur lorsque la pièce jointe devient
visible, avec une marge de préchargement. La génération est séquentielle pour limiter
les contextes graphiques simultanés. Après capture, les géométries, matériaux,
textures et le contexte WebGL sont libérés ; seule la miniature reste en mémoire
pendant l’affichage de la pièce jointe. Il n’y a pas de cache de miniatures côté
serveur : elles sont régénérées après rechargement de la page.

Le moteur Three.js est importé à la demande. La vue interactive dessine à l’ouverture,
au redimensionnement et lors des interactions, sans boucle de rendu permanente.
Les limites sont de 32 Mio par fichier et 2 millions de sommets pour l’aperçu. Un
échec laisse le téléchargement disponible et la vue permet de réessayer.

## Intégration

`front/core/util` expose `Model3dSource`, `model3dFormat`, `Model3dThumbnail` et
`Model3dViewer`. Chaque domaine fournit le nom, le type MIME, la taille lorsqu’elle
est connue, une clé incluant le contexte d’autorisation et une fonction de lecture
via son API autorisée. La visionneuse ne connaît ni les domaines métier ni leurs
identifiants. Les chargements terminés après fermeture ou changement de ressource
sont ignorés et nettoyés.

`FullscreenPreview` accepte `spatial` pour masquer les commandes de zoom 2D : le
zoom et le recentrage sont alors gérés par la caméra 3D. Le glTF est vérifié avant
chargement ; aucune URL externe ou relative issue d’un modèle n’est téléchargée.

Les tests unitaires se trouvent dans `front/core/util/model3d.test.mjs`. Les scénarios
Chromium de `front/browser-tests/model3d.spec.mjs` montent les trois composants réels
avec des API simulées et vérifient les pixels des miniatures, les interactions et le
nettoyage. Ils sont collectés par `make tests-front-components` et la CI, dans un
environnement isolé sans données applicatives. Voir [les couches de test](../dev/testing.md).
