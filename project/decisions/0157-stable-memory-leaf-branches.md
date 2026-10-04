# 0157 — Branches mémoire exclusives et placement adapté au volume

Statut : accepté pour le premier lot. Date : 2026-10-04.

## Décision

La première étape du [plan multiechelle](../plans/graphe-memoire-multiechelle.md) utilise
le contrat léger existant. `relation_count` compte les voisins distincts admissibles sur
toutes les pages, y compris les suggestions ; la pagination locale ne prouve pas l'exclusivité.
Un item est une feuille uniquement s'il a un seul voisin global et un lien confirmé vers
une ancre ayant plusieurs voisins. Topics, contacts, conversations et dossiers restent
individuels. Les suggestions seules ne constituent pas une branche. Les doublons de liens
ne multiplient pas les membres et un voisin supplémentaire hors page interdit le repli.

À partir de huit feuilles chargées et visibles, l'ancre représente la branche avec un compteur.
Le zoom ouvre les branches à partir de 1,8 et replie à 1,35 ; ces
seuils distincts évitent les oscillations. Un clic sur le groupe cadre son ancre et l'ouvre.
**Détails des branches** donne aussi accès aux membres au clavier et au toucher sans changer
le cadrage. Le compteur global conserve les items chargés, y compris les membres repliés.
Les nœuds partagés et leurs liens demeurent individuels.

Jusqu'à 600 items chargés, le frontend conserve le moteur ECharts `force` animé utilisé
avant ce chantier : répulsion, gravité et absence d'attraction entre hubs, avec une friction
initiale réduite à 0,35 pour diminuer l'élan et les rotations.
Ce seuil borne chaque pas à 179 700 paires au maximum dans le moteur quadratique existant.
Les distances et symboles s'adaptent à la surface disponible. Dans cette petite fenêtre,
les feuilles repliées restent dans la simulation avec leurs liens masqués : elles sont
déjà placées lorsque le dépliage les révèle, sans changement de topologie ni redistribution.
L'item sélectionné est fixé pendant la consultation ; fermer le détail ou désélectionner
conserve les positions et le cadrage, y compris par un clic dans le fond du graphe.
Le placement initial converge naturellement, sans limite arbitraire de durée ; les rééquilibrages après modification du
graphe durent au plus 0,7 seconde avec une friction de 0,12. L'option publique
de friction est ensuite mise à zéro pour arrêter le moteur aux positions atteintes.
Le zoom, le déplacement de caméra, le repli/dépliage, la sélection, la désélection et le thème ne relancent
pas la physique ; la navigation arrête un mouvement encore en cours. Les minuteurs sont
remplacés à chaque recalcul et annulés au changement de contexte ou à la destruction.
La caméra et l'identité des nœuds sont conservées, sans promesse de coordonnées immobiles.
Le zoom ouvre toutes les branches de cette petite fenêtre mobile plutôt que de lire des
positions privées du moteur.

Les nœuds révélés au zoom ou par le dépliage apparaissent par fondu et légère croissance
sur place, avec les transitions natives ECharts : 320 ms, échelonnés sur une vague de
120 ms au maximum. Seuls les nouveaux symboles sont animés ; les symboles existants et
les coordonnées ne sont pas interpolés. Un zoom supplémentaire conserve l'animation
en cours sans relancer les forces. Au-delà de 500 symboles visibles ou avec
`prefers-reduced-motion: reduce`, l'apparition est immédiate. Le moteur de rendu assure
l'annulation lorsqu'un nœud est replié ou que le graphe est remplacé.

En vue proche, les fichiers et pièces jointes lisent d'abord les dérivés préparés par Dream
via une lecture autorisée `cached_only`, puis déclenchent les dérivés absents par les
endpoints autorisés existants. Les images remplacent les carrés, avec une
taille plus grande, sans modifier les positions. Le budget desktop est de 256 images,
512 à partir de huit cœurs, ou 64 sur un client explicitement limité ; le mobile utilise
96 images (32 sur un client limité). La lecture utilise 12 demandes simultanées pour un
budget d'au moins 256 images, huit pour au moins 96, sinon quatre. La génération utilise
une file séparée de deux demandes ; une pièce jointe asynchrone conserve sa place pendant
les lectures de suivi avec attente progressive (une minute au plus). La RAM est une
indication approximative et plafonnée : son absence n'implique pas un client limité.
La surface d'écran et la petite taille des anciens carrés ne limitent plus la capacité.
Les dérivés indisponibles libèrent leur place ; la recherche de remplacement est bornée
à deux fois le budget. La sélection et la proximité du cadrage déterminent les priorités.
Les captures restent dans un cache borné lorsque la vue les masque ; elles ne sont pas
expirées périodiquement. Le contexte d'accès et la version de l'item bornent leur durée
de vie. Hystérésis et marge de conservation évitent les oscillations pendant la navigation.
Les petites images ne sont pas réencodées ; les grandes sont réduites en WebP à 160 pixels.
L'arrivée des captures met à jour le rendu par lots de 80 ms. Une absence définitive conserve
le carré et autorise un réessai programmé après cinq minutes, sans déplacement de caméra.
Une capture obtenue dans la popover invalide immédiatement l'absence mémorisée et transmet
ses octets au graphe dans le même contexte d'agent, sans conserver de cache global.
Le lifecycle public d'extension ECharts fournit les coordonnées pour le cadrage ; aucun
accès à une méthode privée de l'instance ni aucune mutation de positions n'est nécessaire.

Les documents HTML partagent le même budget d'images et le cache local. La préparation
du snapshot portable enregistré utilise la file lente de deux demandes et l'endpoint
documentaire existant, qui conserve ses contrôles de révision, d'accès et de cache.
Les scripts ne sont pas exécutés ; les Datasets conservent le symbole documentaire.
Les fichiers et PJ audio portent une note blanche dans leur carré cyan, via un marqueur
vectoriel partagé. Leur classification reprend MIME et extensions des lecteurs existants,
enrichis par les métadonnées d'une source de catalogue résolue. Ils ne consomment aucun
budget de miniature ni aucune génération.

Au-delà de 600 items chargés, le squelette utilise le placement borné Barnes–Hut de
60 à 180 itérations, puis des positions radiales pour les feuilles. Les positions survivantes
sont fixées et les feuilles masquées réservent leur emprise par un symbole absent.
Le zoom ouvre seulement les ancres présentes dans le viewport ; repli/dépliage, filtres et
thème ne recalculent pas ce placement. Les plafonds existants restent en place.
Un changement de périmètre ou une invalidation des accès invalide les réponses anciennes.

À un zoom inférieur ou égal à 0,75, la vue d'ensemble réduit les symboles, retire les ombres,
limite les titres aux hubs et masque les liens de détail, sauf ceux de la sélection.
Le zoom supérieur ou égal à 0,95 restitue ces liens et titres. Les liens masqués restent
dans les données et la simulation : le niveau de détail ne change pas la topologie ni les
relations canoniques. Ce sont des niveaux de rendu, pas encore une hiérarchie de communautés.

Les titres ont un budget lié à la surface du viewport, plafonné à 80, avec priorité aux
ancres et aux items récents ; ECharts masque les collisions. Le survol et la sélection
retrouvent le titre. Les ombres sont retirées au-delà de 500 symboles dessinés. Le placement
et les ensembles de branches éliminent les références aux items disparus.

## Portée et limites

Cette projection est temporaire et limitée aux 3 000 nœuds et 8 000 liens déjà chargés.
Les pages, les contenus, les liens et les ACL canoniques sont conservés sans nouveau schéma.
Elle ne réduit pas le nombre de pages HTTP et réserve encore une position ECharts par item.
Le réseau, le calcul et la mémoire ne deviennent donc pas indépendants du volume chargé.
Les mesures synthétiques de chargement comparent ce lot au rendu précédent ; elles ne
qualifient pas la latence d'un provider distant ni une mémoire de 100 000 items.

La grille initialement essayée ignorait les relations et produisait de longs liens croisés ;
elle est abandonnée. Le premier remplacement entièrement figé tassait encore les hubs et
supprimait la relaxation visible appréciée dans l'ancien graphe : le petit graphe revient
donc au moteur animé. Le placement par forces ne garantit pas un minimum global de croisements.
Dans le grand graphe, les nouvelles régions sont placées en fixant celles déjà présentes ;
un changement de liens seul ne réorganise pas cette fenêtre. Une nouvelle région peut étendre le cadrage
automatique ; la stabilité des coordonnées ne garantit pas celle des pixels lors d'ajouts.
Une feuille déjà placée conserve sa position même si son rattachement visuel change.
Une branche très dense reste dense lorsqu'on affiche tous ses membres : la subdivision
hiérarchique, le chargement spatial et les budgets de détail par région appartiennent aux
lots suivants. Le graphe lit désormais les miniatures de fichiers/PJ préparées par le
socle de la [décision 0156](0156-persistent-file-thumbnails.md), et les captures des documents
HTML par leur endpoint existant. Les miniatures dans la liste restent à compléter selon le plan.

## Vérification

Le premier budget de miniatures cumulait un plafond lié à la surface d'écran, un filtre
sur la taille des anciens carrés et des places occupées par des dérivés indisponibles.
Les premières captures, avec peu de fichiers, ne pouvaient pas qualifier cette capacité.
Les captures utilisent désormais des fichiers anciens et un volume supérieur à dix
aperçus, avec des absences simulées. Après séparation des files, suppression du réencodage
des petites images et regroupement du rendu, la capture de la fenêtre de 660 nœuds montre
428 miniatures au même point du parcours que les 142 précédentes. Le retour au même
cadrage conserve le nombre de requêtes (436). Cette inspection ne qualifie pas le débit réseau ni
la fluidité d'une vue ayant atteint le nouveau plafond de 512 images.

Le premier parcours `cached_only` ne déclenchait aucune génération et ne réessayait pas
les absences lorsque la caméra restait immobile. Les captures avec uniquement des dérivés
prêts ne pouvaient pas détecter ce défaut. L'inspection suivante simule une pièce jointe
absente jusqu'à la fin du calcul et un fichier indisponible jusqu'à l'ouverture de sa
popover : les aperçus apparaissent sans déplacement de caméra, puis la capture obtenue
dans la popover est reprise dans le graphe (huit puis neuf images). Aucune erreur Vue
n'est observée. Les tests automatisés de ce changement sont différés pendant les ajustements
visuels, à la demande de l'utilisateur ; la latence réelle des conversions reste à qualifier.

Une capture synthétique mixte inspecte ensuite les documents HTML et les fichiers/PJ
audio reconnus par MIME ou extension. Deux captures documentaires apparaissent dans le
cadrage proche, avec les notes de musique dans les carrés cyan. Les documents passent
par la préparation réelle du snapshot portable côté client et une réponse de rendu
synthétique ; le renderer serveur existant n'est pas réexercé dans cette inspection.
Aucune demande de miniature audio ni erreur Vue n'est observée. Le retour au même
cadrage conserve les images chargées. Les validations automatisées restent différées.

Les règles pures couvrent feuilles, cycles, isolés, doublons, maintien des positions et proximité
des communautés reliées. Ce dernier test échoue avec le placement en grille : il vérifie que
les liens influencent les positions, plutôt que de figer une forme ou des coordonnées exactes.
La première couverture vérifiait le cadrage au zoom, sans vérifier les coordonnées : elle
laissait passer la relance de la physique à chaque changement de détail. Le scénario mixte
vérifie désormais la convergence naturelle et les coordonnées conservées au dépliage et au
zoom ; il échoue avant l'arrêt de cette relance et passe ensuite.
Le test DB existant de pagination et de droits est renforcé avec un voisin suggéré hors page.
Les composants réels exercent repli/dépliage, zoom, clavier, ouverture d'un enfant, conservation
de la caméra, relaxation animée initiale, positions conservées à la fermeture du détail
par son bouton ou un clic dans le fond, niveaux de rendu au dézoom,
apparition progressive des nouveaux symboles et préférence de réduction des animations,
une topologie mixte avec contact transversal et chargement de 500/3 000
items, dont 3 000 nœuds sans branche repliable et 6 000 liens. Les captures sont inspectées.
Le parcours assemblé utilise une API et une base
isolées avec des items synthétiques, sur desktop et mobile. Les résultats détaillés restent
sous `artifacts/` ; les limites de qualification sont conservées dans le plan.
