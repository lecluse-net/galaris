# 0168 — Graphe mémoire exclusivement en 3D et représentants visibles

- Statut : Accepted
- Date : 2026-10-11

Le graphe mémoire utilise uniquement le rendu Three.js décrit dans 0166. Le sélecteur,
le moteur ECharts, son adaptateur de viewport et la dépendance sont supprimés. Une perte
du contexte WebGL affiche une erreur et permet de recréer la scène 3D avec les données
et filtres courants. Elle ne bascule plus vers un autre moteur. Les anciennes préférences
de caméra restent lisibles côté API ; leur présence ne réactive aucune vue 2D.

L'état de présentation enregistré est un cache jetable. Une validation échouée ou un format
incompatible provoque la reconstruction du placement, jamais le blocage de la carte. Les
anciennes ancres de cette seule vue privée sont supprimées, puis les nouveaux points sont
enregistrés avec contrôle de révision. L'API accepte `reset_layout` pour un format reconnu
comme incompatible par le navigateur. Les erreurs réseau gardent leurs réessais, sans
réappliquer un ancien cadrage sur une vue déjà naviguée ; les données Memory ne sont pas modifiées.

Tous les répertoires connus et autorisés sont chargés dès l'ouverture, par pages : le zoom
ne conditionne plus la découverte de leur arborescence. Seuls leurs fichiers restent différés
et se chargent à l'approche, par pages de 500 au maximum avec deux requêtes concurrentes.
Le contrat API précédent `defer_resource_children` reste disponible ; la carte utilise
`defer_resource_files` pour conserver l'ensemble des répertoires.
Les vues d'ensemble denses regroupent spatialement les répertoires au niveau de chaque
partage, sans mélanger les sources. Leur ouverture ne déclenche aucune découverte distante.

Les actualisations périodiques et reconnexions lisent en arrière-plan l'inventaire paginé
des racines et des répertoires entièrement parcourus, puis fusionnent les seules différences
avec la carte courante. Les lectures partielles ou en erreur ne remplacent pas son contenu.
Les pages reçues pendant cette lecture restent conservées. La caméra, les branches ouvertes
et les positions survivent à la fusion ; un changement de titre ne relance pas le placement.
Les changements de session et invalidations explicites des droits gardent leur retrait des
données protégées. Les anciens fichiers d'un répertoire encore partiellement parcouru
restent en place jusqu'à ce qu'un inventaire complet puisse confirmer leur disparition.

Le catalogue enregistre le libellé du Tool comme titre de sa racine, ou son schéma en repli.
Les noms techniques « . » et « / » sont réparés dans la projection Memory, par un reconciler
DbAdmin idempotent. Un changement du libellé du Tool met aussi ces titres à jour dans la
même transaction ; les titres personnalisés valides restent préservés. Le graphe ne résout
aucun libellé de Tool et expose uniquement le titre mémorisé.

Les éléments non affichés transfèrent leur poids à leurs représentants visibles, via les
parents, les branches repliées et les liens confirmés. Les enfants connus mais non chargés
participent au calcul sans compter deux fois les enfants déjà chargés. Le diamètre croît
avec des rendements décroissants jusqu'à quatre fois sa base, sans déplacer les nœuds.
À 84 éléments masqués, le facteur est d'environ 3,4. Les textes de ces représentants
restent affichés même de loin, au-delà du budget de titres ordinaires et malgré les
chevauchements ; ceux-ci sont acceptés pour garder perceptibles les populations masquées.
Les libellés portent uniquement le nom du nœud ; le nombre masqué, variable avec le zoom,
reste dans le compteur global et les informations de survol.

Les tests unitaires protègent le partage et la conservation du poids. Les parcours Chromium
mesurent les pixels réellement rendus d'un dossier de 84 enfants sur desktop et mobile,
vérifient les textes permanents dans une zone dense et le réessai après perte WebGL.
Les tests 2D de simulation et de caméra sont retirés ; leurs garanties de navigation,
contenu, pagination, filtres et réouverture sont couvertes en 3D et avec l'API réelle.
