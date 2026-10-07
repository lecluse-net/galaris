# Plan — Graphe mémoire à plusieurs niveaux de détail

> **Statut :** `partial` — premier repli de feuilles, positions stables et miniatures de fichiers/documents dans la fenêtre chargée ; hiérarchie, chargement spatial et miniatures de liste à réaliser.
> **Date de création :** 2 octobre 2026.
> **Demande :** rendre les grandes mémoires lisibles en regroupant les branches, révéler leurs
> détails au zoom et charger progressivement les régions explorées.
> **Complément du 4 octobre 2026 :** distinguer les fichiers et documents par leurs miniatures
> dans le graphe et les items mémoire, avec un coût borné lié au niveau de détail affiché.

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
| Vue proche | Mémoires individuelles, titres lisibles, miniatures de fichiers/documents et relations détaillées pertinentes, dans leurs budgets respectifs. |

Dans la liste des items mémoire, une miniature accompagne le titre des fichiers et documents
lorsque la ligne entre dans la zone visible. Dans le graphe, elle apparaît seulement lorsque
l'item individuel est suffisamment lisible à l'écran. Une icône de type sert de remplacement
pendant la préparation, en cas d'échec ou lorsque le budget d'images est atteint ; le nœud
reste représenté, sélectionnable et ouvrable. Les groupes repliés gardent leurs compteurs et
leur identité structurelle, sans charger les aperçus de tous leurs membres.

La hiérarchie est une projection d'affichage, sans modification des liens, contenus, Topics,
propriétaires ou droits canoniques. Ce chantier porte sur une carte 2D ; la
[piste 3D](cible.md#piste-optionnelle--visualisation-3d-de-la-mémoire) reste distincte.

## 2. Faits établis et limites de l'inspection

### Premier lot du 4 octobre 2026

Le graphe replie désormais les branches d'au moins huit feuilles exclusivement reliées à
une ancre. Le compteur de voisins global déjà fourni par le serveur interdit de déduire
l'exclusivité d'une page partielle. Le zoom et le clic sur l'ancre ouvrent leurs membres ;
le dézoom et l'ajustement de la vue les replient. Les positions de
la fenêtre sont animées par le moteur ECharts antérieur jusqu'à 600 items chargés, avec
placement initial à convergence naturelle et rééquilibrage doux de 0,7 seconde lors d'une modification du graphe.
Le zoom, le dépliage et la fermeture du détail conservent les positions, les feuilles étant déjà placées. Au-delà, le placement borné conserve les
coordonnées. Le dézoom masque les liens de détail et certains titres sans modifier les
relations ; le zoom les restitue. Les liens transversaux restent accessibles et les titres
ont un budget avec masquage des collisions. Voir la [décision 0157](../decisions/0157-stable-memory-leaf-branches.md).

Le zoom et le dépliage révèlent les nouveaux nœuds par un fondu et une légère croissance
sur place, sur une courte vague. L'effet est désactivé au-delà de 500 symboles visibles
ou avec la préférence de réduction des animations ; il ne relance pas la physique.

Ce premier lot adapte le lot 1 : le contrat existant suffit au repli de feuilles, sans
nouvelle projection persistante serveur. Le plafond de 3 000 nœuds, les pages HTTP et la
limite de 8 000 liens restent en place. En vue proche, les fichiers et pièces jointes
visibles peuvent remplacer leur carré par un dérivé déjà préparé. Le seuil de zoom possède
une hystérésis (activation à 1,8, retrait à 1,5). La petite taille d'un ancien carré
ne limite plus l'éligibilité de sa miniature. Les miniatures remplacent les carrés et sont
plus grandes (facteur 1,75, avec un minimum de 40 pixels avant application du zoom).
Le budget desktop est de 256 images, ou 512 à partir de huit cœurs annoncés ; une indication
explicite de faible mémoire (au plus 2 Gio) ou deux cœurs limite ce budget à 64. Le mobile
conserve un budget de 96 images (32 sur un client limité). La RAM annoncée par le navigateur
étant approximative et plafonnée, son absence ne classe plus le client comme limité.
La surface d'écran n'impose plus un second plafond de capacité. Les captures indisponibles
libèrent leur place ; la recherche de remplaçants examine au plus deux fois le budget,
avec 12 lectures simultanées sur desktop standard/puissant, huit pour un budget d'au moins
96 images et quatre sur les clients limités. La génération dispose d'une file séparée de
deux demandes, afin que les dérivés prêts passent sans attendre les conversions lentes.
Le cache local conserve deux fois ce budget, avec un plafond
d'octets proportionnel (128 Kio par entrée, minimum 8 Mio), et réduit les images à
160 pixels de côté. Les captures chargées restent en cache quand le zoom ou le cadrage
les masque ; seule une éviction, une version nouvelle ou un changement de contexte
nécessite leur remplacement. Une marge de 100 pixels et une priorité de conservation
évitent les oscillations lors de petits déplacements. La sélection puis la proximité du centre déterminent
la priorité. Les demandes devenues inutiles sont annulées ; un changement de contexte
révoque les URL et ignore les réponses tardives. Les lectures `cached_only` autorisées
servent d'abord les dérivés prêts. Une absence déclenche ensuite la génération par les
endpoints autorisés existants ; les pièces jointes asynchrones sont relues avec attente
progressive pendant une minute au plus, sans quitter leur place dans la file de génération.
Un échec conserve le carré et libère sa place dans le budget d'images ; une nouvelle lecture
est programmée après cinq minutes, même sans déplacer la caméra. Pour les fichiers du catalogue,
la résolution demande un seul emplacement actuel dans l'ordre déterministe des URI,
puis mémorise cet identifiant dans le contexte de la vue et de la version de l'item.
Les aperçus obtenus dans une popover sont transmis au graphe et invalident une absence
mémorisée. Les petites images évitent le réencodage ; les grandes sont réduites en WebP
à 160 pixels. Les mises à jour visuelles sont regroupées sur 80 ms.
Les documents HTML partagent ce budget et ce cache. Leur snapshot portable de la révision
enregistrée passe par la file lente de deux demandes, en réutilisant l'endpoint autorisé
existant et son cache serveur ; aucun script du document n'est exécuté. Les Datasets gardent
leur symbole documentaire. Les fichiers et PJ audio conservent un carré cyan avec une
note de musique, reconnu par MIME ou extension via la classification partagée des lecteurs.
Une source de catalogue résolue enrichit cette détection quand le titre est ambigu.
Ces marqueurs vectoriels ne consomment pas le budget de miniatures et ne déclenchent pas
de conversion audio.
L'arrivée d'une image conserve la caméra et les positions. Aucun chargement spatial
serveur ou affichage de miniatures dans la liste n'est ajouté. La subdivision des grosses branches et l'optimisation
des liens entre régions restent ouvertes. Les constats ci-dessous décrivent la référence
antérieure ; ils ne constituent plus tous la description du rendu actuel.

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

Lecture complémentaire du checkout au 4 octobre 2026, sans mesure ni nouvelle qualification :
la bibliothèque utilise [DocumentThumbnail.vue](../../front/app/memory/components/DocumentThumbnail.vue)
avec observation de visibilité et la [file de previews](../../front/core/util/previewQueue.ts)
limite ses chargements à deux opérations simultanées. L'inspecteur affiche déjà des aperçus
via [MemoryGraphNodeDetail.vue](../../front/app/memory/components/MemoryGraphNodeDetail.vue) et
[MemoryFileResources.vue](../../front/app/memory/components/MemoryFileResources.vue).
La [décision 0156](../decisions/0156-persistent-file-thumbnails.md) décrit les miniatures
persistantes de fichiers et pièces jointes préparées par Dream ; ce socle est à réutiliser.
Les documents HTML suivent encore un parcours différent : `documentThumbnail` lit le contenu,
prépare un snapshot portable puis demande sa capture. Les Datasets n'ont pas de capture HTML.
Le rafraîchissement complet du graphe efface et reconstruit actuellement le rendu ; l'arrivée
d'une miniature ne doit pas emprunter ce parcours et relancer le placement.

## 3. Périmètre et consommateurs

Les consommateurs directs sont l'onglet Graphe, son inspecteur, les ouvertures de détail,
les services/types frontend et les deux endpoints existants. Inventorier leurs appels réels
avant de modifier un contrat ; ne pas déduire leurs consommateurs du seul composant principal.

Préserver la recherche et la liste Memory, les documents et Datasets, le rappel agentique,
les projections de sources et le catalogue de fichiers. Le
[plan Memory](amelioration-globale-memoire.md) possède les évolutions du rappel et de l'organisation
canonique ; le [catalogue File Sharing](indexation-file-share-memory.md) possède l'indexation.
Le présent plan consomme leurs nœuds accessibles sans réimplémenter ces mécanismes.

Le complément miniatures concerne aussi la liste des items mémoire, sur desktop et mobile,
et les nœuds de fichiers, pièces jointes et documents du graphe. Réutiliser les dérivés des
domaines propriétaires et préserver les visionneuses existantes. L'indexation, la génération
des aperçus et leur conservation ne deviennent pas des responsabilités de la projection spatiale.

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

### 4.7 Miniatures liées au niveau de détail

Intégrer les miniatures au budget de détail décrit en 4.5. L'éligibilité dépend de la taille
projetée en pixels, du cadrage et de la densité locale, avec hystérésis ; le nombre total
d'items ne décide pas seul de leur affichage. À distance, conserver les symboles structurels
et des icônes distinctives par type de fichier. À proximité, privilégier l'item sélectionné,
puis les items visibles pertinents. Les titres et états de sélection restent lisibles avec
ou sans image ; conserver un repère de rôle suivant Solaire. Ne pas introduire de mosaïque
de groupe dans le premier lot : elle ajouterait des lectures et un choix de représentativité.

Réutiliser les captures existantes : image réduite, première page PDF/Office, aperçu vidéo
ou 3D, capture du haut d'un document HTML. Les Datasets et formats sans aperçu gardent une
icône spécifique. Pour un fichier possédant plusieurs emplacements, résoudre côté domaine
une source actuelle autorisée de manière déterministe ; ne pas charger toute la liste des
emplacements pour choisir une image, ni créer plusieurs nœuds pour ce seul besoin.

La réponse spatiale peut annoncer une référence opaque, une version et la disponibilité
du dérivé, sans image embarquée, base64, contenu documentaire ou fichier original. Prévoir
une lecture autorisée légère des captures préparées, notamment pour éviter le parcours
contenu/snapshot de chaque document. Une capture manquante ne bloque ni la réponse spatiale
ni la première carte utilisable. Sa préparation reste différée, dédupliquée et bornée par
les mécanismes du domaine ; l'ouverture du graphe ne lance pas la génération de toute la mémoire.
Une miniature documentaire reste un dérivé inerte de la révision enregistrée, sans exécuter
le document ni ouvrir sa visionneuse dans un nœud.

Prévoir une variante réellement réduite pour le graphe ; 96 ou 128 pixels de côté sont des
candidats à mesurer, pas des seuils acceptés. Les captures actuelles peuvent atteindre
520 × 320 : réduire seulement leur taille à l'écran conserve le coût des pixels décodés.
Fixer au lot 0 des budgets séparés de nombre d'images, d'octets transférés et décodés, de
concurrence et de génération serveur. Les chargements suivent le viewport après stabilisation
des gestes, avec une marge bornée et annulation des demandes obsolètes. Pour la liste, appliquer
la même logique aux lignes visibles, y compris avec une page de 500 items.

Le cache d'images comprend le contexte d'accès et la version du dérivé ; chaque lecture
serveur conserve les contrôles de droits actuels. Modification, suppression, révocation,
changement d'agent ou de session invalident les aperçus concernés et empêchent l'application
d'une réponse tardive. Borner les images réellement retenues par le moteur et libérer les
références/URL temporaires après éviction et fermeture, sans compter uniquement sur le cache
interne d'ECharts. Une indisponibilité utilise l'icône de remplacement et une politique de
réessai bornée. Appliquer l'arrivée des images par mises à jour locales regroupées, sans
déplacer les nœuds ni modifier la caméra ou la sélection.

## 5. Lots et portes de passage

| Lot | Travail et livrable | Critère de passage |
|---|---|---|
| 0 — Cadrage et référence | Inventorier les consommateurs ; caractériser feuilles, hubs, cycles et groupes existants ; mesurer le parcours actuel sur données synthétiques ; fixer filtres, isolation, budgets et algorithme initial ; qualifier lecture des dérivés, taille et budgets des miniatures. | Hypothèses vérifiées ; contrats et protocole de mesure écrits ; objectifs chiffrés acceptés avant l'optimisation, avec référence sans miniatures et caches froid/chaud. |
| 1 — Branches exclusives | Premier repli réalisé avec les comptes globaux existants : compteur, expansion au zoom et explicite, relaxation animée jusqu'à 600 items, placement borné au-delà et vue éloignée allégée. Projection serveur persistante reportée au lot 2. | Un hub avec des feuilles devient explorable ; aucune exclusivité déduite d'une page incomplète. Le plafond global reste en place ; les très grosses branches attendent leur subdivision. |
| 2 — Hiérarchie et carte | Étendre aux sous-groupes, cycles, communautés denses et isolés ; construire positions/emprises et générations reprenables ; qualifier l'isolation par périmètre. | Descente déterministe jusqu'à chaque item ; positions stables ; reconstruction/interruption sans carte incohérente ni fuite d'accès. |
| 3 — Chargement spatial | Introduire le contrat viewport ; cache borné, préchargement, éviction, annulation et localisation ; traiter les arêtes traversantes ; activer les miniatures selon le détail et réutiliser leur chargement borné dans la liste. | Parcours de bout en bout au-delà de 3 000 nœuds sans chargement exhaustif initial ; images chargées selon la vue, sans relancer le placement. Retirer le plafond global seulement après cette preuve. |
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
| Les fichiers et documents se distinguent par leurs aperçus en vue proche et dans les lignes visibles, sans perdre titre, sélection ou ouverture. | Composants réels et navigateur : fichiers image/PDF/Office/vidéo/3D, document HTML, Dataset, format sans aperçu et fichier à plusieurs emplacements ; zoom/repli et liste desktop/mobile. |
| Une miniature absente, lente ou en échec ne bloque pas la carte ; son arrivée ne déplace aucun nœud. | Parcours navigateur : cache vide, réponses retardées/hors ordre, erreur et réessai borné ; caméra/sélection conservées et aucun téléchargement original pour un dérivé déjà préparé. |
| Le coût des images reste borné indépendamment de la taille totale de mémoire. | Mesures à froid/chaud : nœuds hors zone préchargée et groupes repliés sans chargement de leurs aperçus ; éviction réelle après déplacements/retours, réouverture et page de 500 items ; révocation et changement d'agent/session pendant un chargement. |
| Une réponse ancienne ou une reconstruction interrompue ne remplace pas la génération valide. | Intégration : publication concurrente, mutation pendant calcul, suppression, reprise idempotente et génération expirée. |
| La vue se rétablit après erreur ou reconnexion sans perdre ses repères autorisés. | E2E : erreur/retry, notifications perdues/dupliquées/hors ordre, fermeture/réouverture et reconnexion. |
| Les commandes restent utilisables sur mobile et au clavier. | Application assemblée sous/au-dessus de 1024 CSS px ; pincement, zoom explicite, focus, plein écran, ouverture du détail et fermeture par backdrop. |

## 7. Mesures avant/après

Première comparaison locale du 4 octobre, sur étoiles synthétiques dans le composant réel
Chromium, avec réponses HTTP simulées, un worker et un contexte navigateur neuf par test.
Le chronomètre couvre montage/imports, pages, premier rendu utilisable et premier clic Zoomer.
Une passe avant/après, sans estimation p50/p95 ni qualification des caches de providers.
Ces premières valeurs portent sur la grille ensuite abandonnée après une régression de forme
sur un graphe mixte ; elles ne mesurent pas le placement organique corrigé :

| Items | Référence avec forces | Premier rendu replié | Pages HTTP avant/après | Symboles dessinés après repli |
|---|---|---|---|---|
| 500 | 2 746 ms | 1 159 ms | 1 / 1 | 1 ancre, 499 feuilles regroupées |
| 3 000 | 3 165 ms | 1 371 ms | 6 / 6 | 1 ancre, 2 999 feuilles regroupées |

Dans une passe distincte, l'affichage explicite de tous les membres a pris 197 ms pour
500 items et 661 ms pour 3 000, sans requête supplémentaire ni changement des coordonnées.
Ces mesures incluent le pilotage Playwright et la lecture du rendu ; elles ne sont pas des
latences de frame. Elles montrent un rendu initial allégé sur cette topologie, sans gain
réseau ni preuve de lisibilité de tous les membres d'une branche de 3 000 items. Cycles,
communautés denses, longues explorations, mémoire décodée et fournisseurs réels restent à mesurer.

Une reprise pendant des travaux concurrents a mesuré 4 965/3 790 ms au chargement et
611/1 669 ms au dépliage pour 500/3 000 items. La charge de la machine n'est pas isolée :
le nombre de symboles dessinés est vérifié, mais un gain de latence reproductible ne peut
pas être conclu de ces passes. Refaire la comparaison répétée sur une machine disponible
avant de fixer des budgets interactifs ou annoncer un facteur d'accélération.

La correction du carré utilisait les liens pour placer le squelette, mais son placement figé
restait trop tassé et supprimait la relaxation visible du graphe antérieur. Le moteur ECharts
animé est donc rétabli jusqu'à 600 items chargés, avec fixation de la sélection et positions
conservées à la fermeture du détail. Le placement borné reste utilisé au-delà. Une vue d'ensemble au dézoom
allège symboles, ombres, titres et liens de détail ; elle n'ajoute pas de hiérarchie serveur.
Une topologie synthétique de 178 nœuds et 303 liens, avec huit sujets, deux contacts,
des documents/items partagés, des feuilles exclusives et des isolés, vérifie la proximité des
communautés, la convergence naturelle, la caméra et les positions conservées au zoom et les niveaux de détail sur desktop/mobile ;
ses captures sont inspectées. Un contact est transversal à tous les sujets. Le test pur de proximité
échoue avant cette correction et passe ensuite. Le parcours de volume comprend désormais
3 000 nœuds non repliables avec 6 000 liens, en plus des étoiles.

Sur ce graphe non repliable, trois calculs locaux Node dans Docker mesurent 379 à 582 ms pour
le placement final, puis 0 à 2 ms pour sa réutilisation. Le premier essai du solveur, avant
réduction du coût géométrique et du nombre d'itérations sur gros squelette, prenait 3 244 à
3 450 ms avec le même protocole. Ces mesures isolent le calcul, sans réseau ni rendu Canvas,
sur une machine à charge variable. Le calcul initial reste synchrone dans le navigateur ;
dans ce mode de grande fenêtre, le repli, le dépliage, les filtres et le thème ne le relancent pas. Elles ne qualifient pas
les téléphones lents, les graphes supérieurs au plafond ni une latence p95.

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

Pour les miniatures, comparer les mêmes parcours avec et sans images, sur desktop et mobile,
avec captures présentes puis absentes. Mesurer nombre d'images chargées/retenues, octets
compressés et mémoire décodée, coût des contrôles de source, captures/conversions déclenchées,
temps de frame et première carte utilisable. Augmenter le nombre total de fichiers à cadrage
et niveau de détail comparables ne doit pas entraîner un chargement proportionnel d'images.
En cas de saturation, réduire les miniatures et conserver les représentants autorisés.

Conserver diagnostics et résultats détaillés sous `artifacts/`. Les preuves versionnées ne
contiennent que corpus synthétiques, mesures agrégées et conclusions techniques.

## 8. Arbitrages ouverts et livraison

À résoudre avant les lots concernés : politique des liens suggérés ; partage du calcul entre
périmètres sans fuite d'informations ; coût des filtres et de la recherche ; algorithme de
regroupement dense ; stabilité lors d'une nouvelle génération ; index spatial ; readiness au
premier accès ; budgets chiffrés et seuils de détail. Le choix éventuel d'un autre moteur suit
la qualification, avec parité des interactions et de la présentation.

Pour les miniatures : format et résolution des variantes, lecture du cache documentaire sans
snapshot complet, priorité des images visibles, seuils d'apparition/disparition, éviction
effective du moteur et politique de réessai. La décision 0156 fournit le socle de fichiers/PJ,
sans démontrer à elle seule le coût d'une utilisation dans un graphe multiechelle.

L'introduction est progressive, avec possibilité de retrouver la vue précédente pendant la
qualification. Les projections ajoutées restent supprimables/reconstructibles sans perte
canonique. Aucun changement du rappel, des limites MCP ou de la rétention Memory n'est impliqué
par la suppression du plafond d'affichage.

À chaque lot implémenté : tests ciblés, `make typecheck`, `make architecture-check` et suites
proportionnées ; relecture du diff pour accès, ressources non bornées, réponses tardives et
consommateurs. Mettre à jour les parcours FR/EN, le catalogue des tests et les décisions retenues ;
préparer les cartes générées avec `make docs-prepare`. Avant publication sans CI, exécuter
`make validate`, lire ses résultats complets, puis terminer par `git diff --check`.

Ce document conserve la cible et les étapes restantes. Le premier lot ne vaut pas qualification
des grands volumes, validation système complète ou déploiement.
