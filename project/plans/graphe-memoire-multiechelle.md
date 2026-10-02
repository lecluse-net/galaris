# Plan — Graphe mémoire à plusieurs niveaux de détail

> **Statut :** `design` — conception proposée ; implémentation non engagée.
> **Date de création :** 2 octobre 2026.
> **Demande :** rendre les grandes mémoires lisibles en regroupant les branches, révéler leurs
> détails au zoom et charger progressivement les régions explorées.

## 1. Résultat attendu

Dans **Connaissances → Mémoire → Graphe**, l'utilisateur explore une carte stable de la mémoire
de l'agent sélectionné. Un nœud portant beaucoup de sous-nœuds exclusivement attachés à lui
apparaît plus gros, avec un compteur ; ses branches se révèlent à mesure que l'utilisateur zoome.
Le déplacement charge les régions entrant dans le champ de vision. Le dézoom replie les détails.

La cible supprime la limite globale de nœuds explorables dans l'interface. Elle conserve des
budgets bornés de rendu, de réseau, de cache et de calcul : une région trop dense reste agrégée
et se subdivise au zoom. Aucun élément autorisé ne disparaît définitivement à cause d'un plafond.
La taille totale peut continuer à influer sur la préparation serveur ; seul le travail interactif
doit être principalement déterminé par la zone et le niveau de détail demandés.

| Distance | Représentation |
|---|---|
| Vue d'ensemble | Grands groupes, nœuds structurants, compteurs et relations agrégées. |
| Vue intermédiaire | Branches et sous-groupes de la région explorée. |
| Vue proche | Mémoires individuelles, titres lisibles et relations détaillées pertinentes. |

La hiérarchie est une projection d'affichage, sans modification des liens, contenus, Topics,
propriétaires ou droits canoniques. Ce chantier porte sur une carte 2D ; la
[piste 3D](cible.md#piste-optionnelle--visualisation-3d-de-la-mémoire) reste distincte.

## 2. Faits établis et limites de l'inspection

Inspection du checkout au 2 octobre 2026, incluant les modifications déjà présentes. Les constats
ci-dessous viennent du code et des tests lus ; aucune mesure de performance ni recette navigateur
n'a été exécutée pour cette conception.

| Surface | Comportement constaté |
|---|---|
| [MemoryGraph.vue](../../front/app/memory/components/MemoryGraph.vue) | Charge successivement les pages de racines ; plafonds de 3 000 nœuds et 8 000 liens ; rendu ECharts Canvas avec placement `force`. Le filtrage des éléments affichés ne constitue pas une sélection spatiale. |
| [memoryService.ts](../../front/app/memory/services/memoryService.ts) | Expose le chargement de racines ; le composant ne pilote pas l'expansion backend au zoom. |
| [Contrats HTTP](../../back/app/memory/schemas.py) et [router](../../back/app/memory/router.py) | `/memory/graph/roots` et `/memory/graph/expand` fournissent des pages bornées, des curseurs et des nœuds légers sans contenu mémoire. Aucun contrat de viewport ni position 2D n'est exposé. |
| [Service Memory](../../back/app/memory/service.py) | Les racines sont ordonnées par activité ; l'expansion parcourt les relations voisines. Ces racines ne constituent pas une hiérarchie de groupes. |
| Rafraîchissement frontend | Relit les racines récentes toutes les 30 secondes ; l'événement websocket `memory/invalidate` et la reconnexion déclenchent une invalidation. Ce mécanisme ne fournit pas un flux spatial de deltas. |
| [Tests du service](../../back/app/memory/tests/test_service.py), [filtres](../../back/app/memory/tests/test_browse_filters.py), [structure documentaire](../../back/app/memory/tests/test_document_structure.py) | Couvrent notamment pagination, voisins, rôles, filtres et exclusion des relations inaccessibles. Ils restent les garanties à préserver. |

Hypothèse à vérifier en premier : quelle part de la densité provient réellement de branches
exclusives, et quelle part provient de zones fortement interconnectées ? Le seul regroupement
des feuilles pourrait apporter un premier gain sans résoudre l'ensemble du problème.

## 3. Périmètre et consommateurs

Les consommateurs directs sont l'onglet Graphe, son inspecteur, les ouvertures de détail,
les services/types frontend et les deux endpoints existants. Inventorier leurs appels réels
avant de modifier un contrat ; ne pas déduire leurs consommateurs du seul composant principal.

Préserver la recherche et la liste Memory, les documents et Datasets, le rappel agentique,
les projections de sources et le catalogue de fichiers. Le
[plan Memory](amelioration-globale-memoire.md) possède les évolutions du rappel et de l'organisation
canonique ; le [catalogue File Sharing](indexation-file-share-memory.md) possède l'indexation.
Le présent plan consomme leurs nœuds accessibles sans réimplémenter ces mécanismes.

Conserver les filtres existants, la période d'activité, les rôles graphiques, la distinction
entre liens confirmés et suggérés, l'ouverture des documents/dossiers et la sélection de l'agent.
L'agent sélectionné reste le périmètre implicite de la carte.

## 4. Architecture proposée

### 4.1 Regroupement topologique et hiérarchie de visualisation

Commencer par les branches dont la seule connexion extérieure est leur nœud d'ancrage.
Vérifier cette propriété côté serveur sur le graphe admissible complet, avec la sémantique
des liens explicitée ; une page frontend partielle ne prouve jamais qu'un voisin est exclusif.
Les suggestions ne doivent pas provoquer des changements continuels d'appartenance : les
traiter séparément et conserver leur nature dans les liens agrégés.

Réutiliser ensuite les dossiers, Topics et conversations lorsqu'ils offrent une structure
compréhensible. L'appartenance à plusieurs ensembles impose un choix de placement déterministe
et la conservation des liens transversaux. Les cycles ne deviennent pas artificiellement
des relations parent/enfant dans les données canoniques.

Pour les zones denses restantes, comparer un regroupement structurel déterministe avec une
subdivision spatiale. Retenir la solution la plus simple qui permet de descendre jusqu'aux
nœuds individuels, y compris pour un hub géant, des cycles et des nœuds isolés. Aucun appel LLM
n'est nécessaire à la navigation ou à la construction initiale de la hiérarchie.

À un instant donné, chaque mémoire est représentée exactement une fois : individuellement
ou dans un groupe replié. Un parent réel restant visible ne doit pas être compté de nouveau
parmi ses descendants. Les compteurs portent sur des membres uniques admissibles, et non sur
le nombre d'arêtes. Un regroupement virtuel se distingue d'un véritable item ouvrable.

Les liens franchissant les groupes sont agrégés entre leurs représentants visibles, avec
direction, type et statut confirmé/suggéré préservés. Au dépliage, leurs extrémités sont remappées
vers les représentants plus fins. Les arêtes hors écran et celles qui traversent la fenêtre
exigent une politique explicite : trait agrégé, indicateur de continuation ou navigation vers
la destination, sans charger récursivement tout le voisinage.

### 4.2 Carte stable et projection reconstruisible

La projection appartient à `app.memory`. Elle associe aux nœuds/groupes une identité stable,
leur parent de visualisation, une position, une emprise spatiale et les informations nécessaires
aux niveaux de détail. Ces objets sont reconstruisibles à partir des données canoniques.
Les noms et tables éventuels seront fixés après le lot de cadrage.

Préparer la hiérarchie et le placement hors de la requête interactive. Les enfants occupent
une région réservée dans l'emprise du groupe ; l'ouverture d'une branche conserve la caméra
et les positions des régions non modifiées. Une relaxation locale peut être évaluée, sans
simulation globale à chaque zoom ni ajustement automatique de la carte entière.

Construire une génération en staging, puis la publier atomiquement. Une interruption conserve
la dernière génération valide ; les mutations arrivées pendant le calcul sont reprises ensuite.
La reconstruction est idempotente, reprenable et bornée en concurrence. En cas de restructuration,
conserver autant que possible l'ancre de caméra et l'identité de l'item sélectionné.

Évaluer un index spatial simple dans PostgreSQL à partir de mesures et de plans de requêtes.
Ni PostGIS ni un nouveau service ne sont des prérequis. Toute évolution du schéma passe par
SQLAlchemy et `core.dbadmin`, avec les skills `database` et `core-dbadmin` selon les opérations.

### 4.3 Droits, filtres et versions

Appliquer les droits actuels avant de produire les membres, compteurs, titres et relations
d'un groupe. Une mémoire cachée ne peut pas influer sur un compteur, un libellé ou une géométrie
visible qui révélerait son existence. Définir une projection par périmètre autorisé ou un
mécanisme équivalent démontrant cette isolation ; ne pas simplement filtrer une carte globale.

Les filtres définissent les éléments admissibles ; le contexte structurel nécessaire à leur
navigation doit être autorisé et identifié explicitement. Fixer au cadrage la sémantique des
compteurs et des groupes vides pour recherche, types, Topic, contact et période d'activité.
Le passage du temps peut faire sortir une mémoire du filtre, même sans mutation serveur.

Séparer génération de placement, révision des données et version d'accès. L'identité d'une vue
et de ses caches comprend l'utilisateur/rôle effectif, l'agent, les filtres et les versions
pertinentes. Une ancienne génération de placement ne permet jamais de contourner une révocation.

### 4.4 Contrat de chargement spatial

Ajouter un contrat de vue sous `/memory/graph` après inventaire des consommateurs. Le nom exact
de la route reste à choisir. Préserver les endpoints existants pendant la transition.

La requête décrit : périmètre agent, filtres, rectangle en coordonnées de carte, dimensions
d'écran utiles au détail, niveau de détail demandé et génération connue. Le serveur valide
coordonnées, emprise et budgets ; la caméra ne confère aucun droit.

La réponse contient : génération/révision, groupes ou nœuds avec positions/emprises, compteurs,
liens représentatifs et état de couverture. Aucun contenu complet de mémoire ne circule dans
ces réponses. Une vue trop dense revient sous une forme plus agrégée avec des possibilités
de raffinement ; elle ne renvoie pas seulement les premiers éléments en omettant les autres.

Au premier accès, distinguer projection en préparation, région chargée, vide et erreur. Prévoir
une vue provisoire sûre et bornée si la projection n'est pas prête, sans la présenter comme
exhaustive. Une génération expirée conduit à une resynchronisation explicite.

### 4.5 Navigation et budget de détail

Le niveau de détail dépend de l'emprise projetée de chaque groupe, de sa densité et de l'espace
disponible. Un petit groupe peut s'ouvrir plus tôt qu'un grand. Deux seuils distincts d'ouverture
et de fermeture évitent l'oscillation autour d'une frontière ; la taille des hubs suit une
progression atténuée et plafonnée en pixels. Les libellés ont leur propre budget de lisibilité.

Limiter les requêtes pendant les gestes, précharger une marge autour du viewport et annuler
les demandes obsolètes. Une réponse n'est applicable qu'au bon contexte et à la bonne génération.
Un cache borné conserve les régions récemment explorées ; le rendu évince les éléments éloignés.
Épingler l'item sélectionné et ses informations nécessaires sans retenir tout son voisinage.

Prévoir une recherche/localisation d'un item autorisé, révélant son chemin dans la hiérarchie.
Elle doit permettre d'atteindre aussi un nœud isolé ou ancien. Le clic sur un groupe peut centrer
et zoomer ; le clic sur un item conserve l'inspection et l'ouverture du détail. Les boutons de
zoom, le clavier et le tactile offrent les mêmes possibilités de raffinement.

Conserver ECharts comme candidat initial. Mesurer sa capacité à afficher les positions imposées
et les changements locaux. Comparer un moteur WebGL seulement si les budgets interactifs ne sont
pas atteints ; un remplacement du moteur ne fournit pas la hiérarchie ni le chargement spatial.
Les couleurs suivent exclusivement la palette Solaire et les chaînes passent par i18n.

### 4.6 Actualisation progressive

Réutiliser le transport websocket du projet pour annoncer les révisions/régions invalidées.
Le navigateur ne reçoit pas un flux exhaustif de la mémoire : il recharge les régions actives
concernées. Les deltas détaillés sont une optimisation ultérieure si les mesures les justifient.

Après commit canonique, regrouper les invalidations et mettre à jour les projections concernées.
Une création ou suppression ajuste les compteurs et le placement local ; un changement de lien
peut rendre une branche non exclusive et imposer son reclassement. Les droits sont vérifiés
immédiatement à la lecture, même si le calcul de projection est encore en attente.

Traiter doublons, événements hors ordre, pertes d'événements, reconnexion et retard du worker.
Les révisions empêchent les anciennes réponses de ressusciter des items supprimés. Prévoir
une resynchronisation bornée et un rafraîchissement de secours ; fermer la vue nettoie requêtes,
abonnements et timers. Une erreur récupérable conserve la carte autorisée et permet de réessayer.

## 5. Lots et portes de passage

| Lot | Travail et livrable | Critère de passage |
|---|---|---|
| 0 — Cadrage et référence | Inventorier les consommateurs ; caractériser feuilles, hubs, cycles et groupes existants ; mesurer le parcours actuel sur données synthétiques ; fixer filtres, isolation, budgets et algorithme initial. | Hypothèses vérifiées ; contrats et protocole de mesure écrits ; objectifs chiffrés acceptés avant l'optimisation. |
| 1 — Branches exclusives | Ajouter une projection serveur minimale de repli ; compteur, taille et expansion au zoom ; placement local stable et maintien des liens transversaux. | Un hub avec beaucoup de feuilles devient lisible et explorable ; aucune exclusivité déduite d'une page incomplète. Ce lot ne prétend pas supprimer le plafond global. |
| 2 — Hiérarchie et carte | Étendre aux sous-groupes, cycles, communautés denses et isolés ; construire positions/emprises et générations reprenables ; qualifier l'isolation par périmètre. | Descente déterministe jusqu'à chaque item ; positions stables ; reconstruction/interruption sans carte incohérente ni fuite d'accès. |
| 3 — Chargement spatial | Introduire le contrat viewport ; cache borné, préchargement, éviction, annulation et localisation ; traiter les arêtes traversantes. | Parcours de bout en bout au-delà de 3 000 nœuds sans chargement exhaustif initial. Retirer le plafond global seulement après cette preuve. |
| 4 — Actualisation | Invalidation par région/révision, mutations locales, reprise et reconnexion ; gestion prioritaire des révocations et changements de contexte. | Carte et compteurs convergent après mutations ; réponses obsolètes et pertes d'événements couvertes ; retour dans une zone fiable. |
| 5 — Qualification et livraison | Comparer les mesures ; recette assemblée desktop/mobile ; choisir le moteur sur résultats ; documenter architecture et parcours, puis valider l'ensemble. | Matrice de réception passée, risques restants explicités et mécanisme de retour à la vue précédente vérifié. |

Chaque lot reste limité au contrat qu'il change. Aucun ajout de dépendance, abstraction générique
ou paramètre permanent sans besoin démontré. Le statut du plan évolue dans l'index à chaque
changement de phase ; une décision acceptée est rédigée lorsque les choix structurants sont arrêtés.

## 6. Matrice de réception

Renforcer les scénarios existants avant d'en ajouter, selon le
[catalogue fonctionnel](../../docs/fr/dev/functional-tests.md). Les fixtures restent synthétiques.

| Garantie observable | Vérification principale |
|---|---|
| Un hub et ses feuilles se replient puis se révèlent, sans clignotement ni perte d'accès. | Composant réel : zoom avant/arrière, seuils, compteur, sélection et ouverture d'un enfant. |
| Chaque item admissible est représenté une fois ; chaque lien transversal peut être retrouvé. | Règles pures et DB : étoile, branches profondes, cycle, multi-appartenance, isolés ; invariants de couverture/comptage et de remappage. |
| Une page partielle ne transforme pas un nœud partagé en feuille exclusive. | DB : relation supplémentaire au-delà de la première page, avec lien confirmé et suggéré. |
| L'expansion locale conserve les repères et ne recentre pas la carte. | Parcours navigateur : ancre/sélection retrouvable après dépliage, repliage et mutation locale. |
| Une mémoire ancienne reste atteignable au-delà du plafond historique. | DB et E2E : localisation puis navigation vers un item hors des premières pages, avec plus de 3 000 items. |
| Agent, rôle, ACL, source et filtres bornent aussi groupes, compteurs et caches. | Intégration des droits/filtres existants ; comparer les vues avec/sans données cachées ; révocation pendant une requête et changement d'agent. |
| Le réseau et la mémoire navigateur restent bornés après une longue exploration. | Mesurer déplacements/retours ; contrôler éviction, nombre de requêtes et absence de parcours global implicite. |
| Une réponse ancienne ou une reconstruction interrompue ne remplace pas la génération valide. | Intégration : publication concurrente, mutation pendant calcul, suppression, reprise idempotente et génération expirée. |
| La vue se rétablit après erreur ou reconnexion sans perdre ses repères autorisés. | E2E : erreur/retry, notifications perdues/dupliquées/hors ordre, fermeture/réouverture et reconnexion. |
| Les commandes restent utilisables sur mobile et au clavier. | Application assemblée sous/au-dessus de 1024 CSS px ; pincement, zoom explicite, focus, plein écran, ouverture du détail et fermeture par backdrop. |

## 7. Mesures avant/après

Utiliser le même protocole, les mêmes filtres, droits, matériels et données pour comparer
l'affichage actuel et les lots. Étudier au moins 1 000, 10 000 et 100 000 items, dont un hub
disproportionné, des branches profondes, une communauté dense, des isolés et des droits hétérogènes.
Ces volumes sont des points de qualification proposés, pas des capacités déjà démontrées.

Mesurer à froid et à chaud : temps jusqu'à la première carte utilisable, latence p50/p95 des
vues et expansions, octets transférés, requêtes SQL et lignes examinées, temps de frame pendant
zoom/déplacement, mémoire/cache navigateur, durée et mémoire de construction serveur, et délai
de convergence après mutation. Ajouter le nombre d'actions nécessaires pour retrouver un item
et ouvrir son contenu, afin de mesurer aussi l'utilité de la nouvelle présentation.

Les objectifs chiffrés sont fixés au lot 0 et conservés avec le protocole. Le contrôle principal
est qu'une navigation comparable ne charge pas une quantité proportionnelle à toute la mémoire.
Les budgets de rendu et de requête doivent être respectés même dans une région exceptionnellement
dense, en augmentant l'agrégation plutôt qu'en omettant arbitrairement des nœuds.

Conserver diagnostics et résultats détaillés sous `artifacts/`. Les preuves versionnées ne
contiennent que corpus synthétiques, mesures agrégées et conclusions techniques.

## 8. Arbitrages ouverts et livraison

À résoudre avant les lots concernés : politique des liens suggérés ; partage du calcul entre
périmètres sans fuite d'informations ; coût des filtres et de la recherche ; algorithme de
regroupement dense ; stabilité lors d'une nouvelle génération ; index spatial ; readiness au
premier accès ; budgets chiffrés et seuils de détail. Le choix éventuel d'un autre moteur suit
la qualification, avec parité des interactions et de la présentation.

L'introduction est progressive, avec possibilité de retrouver la vue précédente pendant la
qualification. Les projections ajoutées restent supprimables/reconstructibles sans perte
canonique. Aucun changement du rappel, des limites MCP ou de la rétention Memory n'est impliqué
par la suppression du plafond d'affichage.

À chaque lot implémenté : tests ciblés, `make typecheck`, `make architecture-check` et suites
proportionnées ; relecture du diff pour accès, ressources non bornées, réponses tardives et
consommateurs. Mettre à jour les parcours FR/EN, le catalogue des tests et les décisions retenues ;
préparer les cartes générées avec `make docs-prepare`. Avant publication sans CI, exécuter
`make validate`, lire ses résultats complets, puis terminer par `git diff --check`.

Ce document constitue uniquement le plan demandé. Il ne démontre ni une implémentation,
ni un gain mesuré, ni une validation système ou un déploiement.
