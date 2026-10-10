# 0166 — Rendu 3D par lots du graphe mémoire

- Statut : Accepted
- Date : 2026-10-10

La page Mémoire ouvre une carte 3D Three.js tout en conservant le moteur 2D ECharts.
Les deux moteurs utilisent le même chargement autorisé, les regroupements et détails
existants. La sélection continue d'émettre l'identité canonique et les relations.
Il n'y a pas de nouveau modèle métier ni de dépendance supplémentaire.

Le placement 2D personnel est conservé séparément. Un Web Worker réserve les positions
manquantes. La 3D donne la priorité aux racines de schémas File Share, sujets et contacts,
puis aux dossiers/répertoires, documents et autres détails. Les relations `parent_of`
confirmées conservent la répartition latérale précédente des fichiers et ajoutent de la
profondeur ; l'écart suit la longueur latérale du lien avec une variation déterministe,
sans grands plans rigides ni nouvelle disposition en spirale.
Les cycles restent représentables. Les natures masquées ont
une carte temporaire recalculée, sans modifier les positions canoniques enregistrées.
La profondeur courante des survivants est conservée lors des ajouts.

Un `InstancedBufferGeometry` partage un quad et un shader entre les marqueurs visibles.
Les offsets en espace écran imposent les deux tailles éloignée/proche. Les relations
utilisent des rubans instanciés, afin de respecter leurs épaisseurs en pixels CSS
sur WebGL, avec suggestions discontinues. Leur courbure quadratique reprend les
valeurs de la 2D, y compris les relations parallèles. Chaque instance dessine un tronçon
de quatre segments ; les liens longs à l'écran utilisent davantage de tronçons, jusqu'à
64 segments par lien. Le nombre dépend de la longueur projetée et de la courbure, pour
viser une erreur de corde inférieure au pixel sans suréchantillonner les liens presque
droits, avec des paliers et une hystérésis. Le CPU masque entièrement une relation dès
qu'une extrémité passe derrière le plan proche de la caméra, puis estime son étendue,
écarte les enveloppes hors champ et actualise les buffers uniquement lors d'un changement
de tronçons ou de regroupement. Les shaders calculent les points et normales ; les
liens restent dans un seul appel de dessin. Le décalage de courbure est borné pour les
extrémités hors champ. Les cellules 3D sont
testées contre le frustum avant projection ; un index écran sert au picking, aux titres
et à la place des aperçus. Les cellules denses de marqueurs de même couleur/forme
représentent aussi les éléments non structurés par des groupes d'affichage. Le seuil
de dépliage dépend de leur densité et de leur taille projetée, avec hystérésis. Cliquer
un groupe approche et déplie sa cellule ; ses membres conservent leurs identités.
Les groupes ne sont ni des souvenirs ni des préférences métier enregistrées. Les liens
équivalents en type, direction et statut sont regroupés ; les liens internes réapparaissent
au dépliage. Aucun lien canonique n'est supprimé. Des coordonnées relatives à la caméra, et des positions
haute/basse précision pour les liens, évitent la dérive au zoom profond.

Les styles des marqueurs et relations sont calculés par les mêmes fonctions que la 2D :
accents, bordures, ancienneté, types de liens, confiance, épaisseurs et opacités. En 3D,
les épaisseurs sont renforcées d'un facteur de 2,25 au loin et de 1,25 de près pour leur
lisibilité, en conservant les différences entre types et les pointillés.
Les formes géométriques ont des bordures explicites et les contacts/conversations des
angles arrondis. Un atlas de 1024 × 1024 pixels, limité à 64 glyphes publics distincts,
réutilise les SVG GNOME des dossiers et les chemins Material des documents et médias.
Il ne dépend ni du nombre d'items ni de leurs miniatures privées. Les chemins sont
ajustés à leurs limites comme en 2D ; les dossiers conservent leur artwork complet.
La résolution tardive du type de fichier actualise son glyphe sans relancer le placement.
La taille éloignée des marqueurs 2D/3D vaut 56 % de leur taille de base plafonnée, contre
110 % en vue proche ; avancer davantage ne les agrandit plus. Les positions et la
navigation restent inchangées. Les labels n'ont
aucun fond. L'atlas et ses chargements sont libérés avec la scène ; marqueurs et liens
conservent deux appels de dessin, indépendamment du nombre d'items.

Le rendu est déclenché par les interactions et changements, sans boucle au repos ni
simulation globale pendant la navigation. Les labels sont limités à 12/80 selon la
distance. Les images autorisées réutilisent `GraphThumbnails`, avec un budget borné,
des lectures uniquement près du champ visible et une taille maximale native. Elles
forment une couche DOM bornée, distincte de l'atlas des glyphes publics. Une miniature entière
est sélectionnable, pas uniquement son centre.

OrbitControls assure le déplacement latéral et les contrôles tactiles. Un clic gauche
sur le fond choisit son déplacement latéral natif avant le traitement du press et conserve
ce geste jusqu'au relâchement. Dès le premier mouvement, la vue quitte le mode d'ensemble
centré pour que le déplacement ne soit pas annulé. Le glissement
gauche choisit le nœud pressé comme pivot distinct de la cible du regard : caméra et
cible tournent ensemble autour de lui, sans déplacer son image vers le centre. Les
rotations sont calculées depuis la pose au début du geste, avec les limites verticales
du regard ; revenir au point de départ restitue ce cadrage. Un
déplacement est mémorisé pour tout le geste : revenir au départ, annuler ou perdre la
capture ne transforme jamais une rotation en ouverture. Seul un clic primaire immobile
sur le même objet active son détail ; les gestes à plusieurs doigts n'ouvrent rien.
La molette déplace ensemble caméra et cible sur le rayon caméra sous le pointeur,
calculé en coordonnées caméra pour éviter de soustraire de grandes positions mondiales.
Le point visé conserve sa position à l'écran et l'orientation reste inchangée. Le pas
utilise la profondeur du nœud visé, sinon la profondeur visible ; la projection du rayon
sur l'axe de visée conserve une progression axiale uniforme. Le pincement et les boutons
de zoom conservent l'axe central. Le déplacement garde un minimum qui traverse le
plan d'un nœud au lieu de l'approcher indéfiniment, et une vitesse conservée en espace
vide. Il n'y a pas de distance minimale au pivot bloquant l'avance. Les aperçus utilisent
leur profondeur locale. Le cadrage d'ensemble utilise les positions des marqueurs
rendus, la largeur, la hauteur et la profondeur dans l'orientation du regard, avec une
marge pour les glyphes. Il remplit la dimension limitante et centre les limites projetées,
y compris avec des profondeurs différentes. Il ne réserve plus une sphère ajustée au
plus petit angle de vue. Les membres d'une branche repliée ne dilatent plus les limites
de son ancre visible. Le recul maximal et le redimensionnement recalculent ce cadrage
pour l'orientation courante ; le résultat est mis en cache entre changements de données,
de viewport ou d'orientation. Les anciennes caméras d'ensemble plus éloignées sont
ramenées à ce nouveau maximum à la restauration ; les poses de navigation libre sont
conservées. Les crans de molette suivants n'altèrent plus cette vue d'ensemble.
Les boutons ajustement/plein écran restent communs ; les flèches sélectionnent les nœuds
visibles, Entrée ouvre leur contenu et Début recentre tout le graphe.
`camera_3d` est un champ JSONB personnel additionnel, sans changement de schéma ; une
écriture 3D ne remplace pas `camera` 2D. Les contrôles de révision et de périmètre existants
restent obligatoires. Sa version de placement vaut désormais 2 : une caméra du précédent
placement plat est réajustée à l'ouverture. Les branches de ressources visitées et leur
nombre de pages sont enregistrés dans les mêmes préférences privées, filtrés par les accès
à la lecture comme à l'écriture. Le démontage annule workers et requêtes de branches, puis
libère buffers, listeners et contexte WebGL. Une perte de contexte revient à la vue 2D,
avec rechargement de son catalogue complet.

Les API existantes sont étendues sans changer leurs valeurs par défaut. La 3D demande
des pages de 500 nœuds, classées par rôle puis activité, avec jusqu'à 10 000 relations
par page ; la 2D conserve son ordre par activité et ses 2 500 relations par page.
Chaque page 3D est placée et affichée avant de poursuivre, sans réinitialiser une caméra
déjà déplacée. Il n'y a pas de plafond global de nœuds.
Les descendants de répertoires accessibles, identifiés par leur chemin et un `parent_of`
confirmé, sont différés à l'ouverture. À l'approche d'un répertoire visible, l'expansion
charge uniquement ses enfants, par pages de 100, répertoires avant fichiers, avec au plus
deux demandes simultanées. Une nouvelle page nécessite un déplacement de caméra ; le
repos ne draine pas l'arbre. Les pages de branches précédemment visitées sont restaurées
avant la caméra sauvegardée. Un changement d'agent ou de filtres annule les demandes
obsolètes ; les erreurs gardent la carte partielle visible avec le réessai existant.
Chaque page conserve les contrôles d'accès canoniques et les vérifications de source
vivante, sans parcours récursif du provider. Les liens vers des enfants différés ne sont
pas renvoyés avec les racines : leurs vérifications de source sont différées avec eux.
Les pages de racines et d'enfants reprennent les coordonnées 2D privées déjà enregistrées.

Cette lecture progressive du catalogue connu ne prouve pas une ouverture indépendante
du volume total : carte serveur préparée, générations et occurrences du catalogue restent
dans le plan multiechelle. Les tests utilisent des données synthétiques dans le même navigateur ;
les mesures d'actions ne sont pas présentées comme des mesures de FPS sur GPU physique.
