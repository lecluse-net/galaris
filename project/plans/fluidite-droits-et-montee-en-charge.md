# Fluidité, droits effectifs et montée en charge de Galaris

Statut `in-progress` · 25 novembre 2026

Pendant qu’une mission lance plusieurs agents et outils, une autre personne doit pouvoir ouvrir un document, envoyer un message, suivre la progression et demander un arrêt. Le travail admis reste identifiable pendant une panne et retrouve une issue explicite après redémarrage. La capacité se juge au nombre de missions correctement terminées, à la réactivité de l’interface et au coût serveur par réussite.

## Ordre de livraison

| Lot | Premier résultat livrable | Condition pour élargir |
|---|---|---|
| 0. Référence | Reproduire le ralentissement solo sur un parcours synthétique assemblé et situer le temps perdu | Même parcours et mêmes résultats reproductibles à froid et à chaud |
| 1. Outils et fichiers | Deux catalogues MCP de base par agent et runtime, préparation mutualisée des accès fichiers | Gain sur huit démarrages simultanés, parité des outils et révocation pendant un run |
| 2. Partage | Projection complète agent/utilisateur sur Documents, comparée au calcul actuel | Parité des lectures **et** écritures, suppressions et restaurations correctes, coût de propagation soutenable |
| 3. Interactivité | Réduire les réveils inutiles, borner le fond, limiter les relectures navigateur | Dialogue et contrôle disponibles sous charge, files qui se résorbent et maintenances qui aboutissent |
| 4. Capacité d’exécution | Sortir un premier exécuteur du processus interactif, puis qualifier deux exécuteurs | Limites globales, reprise après perte d’un worker, aucun effet externe rejoué à l’aveugle |
| 5. Exploitation | Qualifier 30 puis 50 utilisateurs actifs, l’endurance, le redémarrage complet et la restauration | Résultats reproductibles sur le matériel cible, procédure de retour vérifiée |

Après la référence, les lots 1 et 2 peuvent avancer indépendamment. Chaque livraison garde un chemin de retour utilisable sur les données déjà créées. Les étapes ci-dessous décrivent des travaux et des critères de réception.

### Point d’avancement dans le dépôt

| Parcours | Travail engagé | Prochaine preuve à obtenir |
|---|---|---|
| Démarrage MCP | Le montage réutilise les schémas et catalogues. Le harnais limite à quatre les préparations locales de tâches simultanées par worker. Deux campagnes ont mesuré le délai d’arrêt au départ et en pleine vague. | Mesurer depuis l’envoi jusqu’à l’affichage dans le navigateur et expliquer les pointes de retard de la boucle événementielle. |
| Documents et fichiers | La page et ses droits proviennent d’une lecture PostgreSQL. La projection suit les documents JSON, les équipes, les comptes humains et la création, le changement de responsable et l’archivage des agents. Un test exerce 32 lecteurs pendant un archivage en attente. | Qualifier la restauration des ressources et la contention entre plusieurs rédacteurs avant de basculer les lectures sur la projection. |
| Dream et suivi des tâches | Le délai entre deux recherches de travail Dream augmente après des cycles vides. La liste des tâches applique les progressions reçues et regroupe les relectures. | Mesurer la latence d’un nouvel envoi et d’un arrêt pendant un pic, ainsi que le rattrapage après reconnexion. |
| Exécution et exploitation | Le scheduler réserve une place interactive avant prise. Les appels LLM partagent leur plafond en base. Le test lance deux processus puis interrompt le détenteur de la place. | Mesurer le débit soutenu sur le matériel cible, les pannes du fournisseur et l’indisponibilité de PostgreSQL pendant une mission. |

Sur 100 appels d’outil synthétiques avec 1 Kio de résultat chacun, les 200 sauvegardes
d’un tour texte totalisent 50 195 916 octets chiffrés avec l’instantané complet à chaque
écriture et 2 538 145 avec les modifications successives. L’état final relu est identique.
Cette mesure porte sur le contenu envoyé par l’application. Les écritures physiques de
PostgreSQL et son journal de transactions restent à mesurer. [Stockage des discussions](../../back/app/conversation/checkpoint_journal.py)

Avec 25 discussions, 25 tâches et 50 propriétaires, trois vagues comparent dans le
même banc 50 places de montage MCP conversationnel à quatre. La file Task conserve
quatre places. À quatre places de discussion, l’arrêt envoyé au départ prend 217–288 ms
contre 472–501 ms. L’arrêt envoyé 150 ms plus tard prend 399–869 ms contre 323–393 ms.
Le p95 du premier texte reçu par le consommateur Python atteint 773–1 202 ms contre
688–744 ms. Les deux limites sont réglables indépendamment. Un parcours Chromium
distinct mesure 1,85 s de l’envoi jusqu’au premier texte visible avec un modèle synthétique.
Ces essais mesurent des vagues de démarrage et ne déterminent pas le débit soutenu.
[Banc mixte](../../back/tests/test_agent_startup_concurrency.py) · [Parcours chat](../../e2e/specs/chat.spec.mjs)

Les tests ciblés couvrent les suppressions physiques de partage, d’utilisateur et d’agent dans PostgreSQL, l’isolation de trois appels MCP simultanés dont deux tâches du même agent, ainsi que les mises à jour d’une ligne de tâche pendant une réponse HTTP tardive. Un essai distinct sur l’application assemblée doit encore mesurer la latence réellement perçue par les utilisateurs. [Droits et cascades](../../back/app/share/tests/test_access_parity.py) · [Isolation des montages MCP](../../back/app/services/tests/test_mcp_loader.py) · [Concurrence de la liste Task](../../front/app/task/storeConcurrency.test.mjs)

Le montage MCP agrégé suivi de la préparation d’une action Process passe de **36 à 17 lectures SQL**, avec une connexion ou avec 50 connexions supplémentaires. En discussion, la description des services disponibles pour une tâche reste à deux lectures sur ce même jeu de données. Le cache de base est borné à 256 entrées par processus. Deux agents aux règles identiques peuvent partager les définitions. Chaque découverte relit les règles effectives, puis applique les capacités du runtime et les restrictions du tour. Les comptes, clients, ressources et autorisations d’exécution restent attachés à l’appel. [Mesure SQL et révocations](../../back/app/services/tests/test_catalog_sql_budget.py)

La découverte d’un outil multimédia vérifie uniquement les modèles candidats pour cet appel. Sur le profil synthétique du test, le contrôle d’une seule fonction demande trois lectures SQL, contre douze pour l’ensemble des fonctions spécialistes. La désactivation du modèle ou du fournisseur reste visible sur le serveur MCP déjà monté. [Contrôle des modèles multimédias](../../back/app/multimedia/tests/test_multimedia.py)

La première campagne de référence lançait trois vagues de huit montages avec PostgreSQL, un modèle simulé répondant après 20 ms et un arrêt HTTP authentifié sur une tâche indépendante à chaque vague. Deux exécutions ont donné les plages suivantes avant l’optimisation du démarrage à froid.

| Charge | Premier texte | Accusé d’arrêt HTTP |
|---|---:|---:|
| Huit démarrages du même agent, première vague d’un nouveau processus | 696–711 ms | 665–678 ms |
| Même agent, deux vagues suivantes | 168–270 ms | 148–274 ms |
| Huit agents distincts, processus déjà chaud | 181–392 ms | 174–366 ms |

Sur cette référence, le montage MCP médian du même agent prenait 583 ms à la première vague puis 51 ms aux deux suivantes. Le chronométrage commence au lancement du montage et s’arrête au premier fragment reçu par le consommateur Python. [Parcours reproductible](../../back/tests/test_agent_startup_concurrency.py)

Le profil de la première vague a identifié deux opérations synchrones sur la boucle HTTP. L’inspection RBAC prépare maintenant les dépendances des routes incluses par FastAPI avant la première requête. Dans le conteneur isolé, cette inspection a pris 456 ms contre 2 ms avec le parcours antérieur, pour les mêmes 775 noms de routes protégées. Le montage compile désormais les outils d’administration et multimédias initialement indisponibles lorsqu’ils deviennent visibles ou sont demandés directement. Sur la première comparaison Documents, Fichiers et Process, la première vague a compilé 67 fonctions natives contre 138 auparavant. Le premier texte médian est passé de 715 ms à 411–416 ms et l’accusé d’arrêt de 688 ms à 379–385 ms. [Préparation des routes](../../back/core/authorize/guard_provider.py) · [Montage MCP](../../back/app/services/mcp_loader.py)

Sur un agent connecté uniquement à Process, la découverte du catalogue agrégé passe de huit à deux lectures SQL. La découverte native directe respecte aussi ce budget. Une activation après montage donne accès à l’outil lors de deux découvertes et d’un appel simultanés. Une révocation reste opposable lors de l’appel suivant. [Budget SQL](../../back/app/services/tests/test_catalog_sql_budget.py) · [Autorisations en concurrence](../../back/app/services/tests/test_live_authorization.py)

Deux exécutions du banc étendu ont ensuite lancé trois vagues par palier. À 30 et 50, chaque agent a un propriétaire distinct. À chaque vague, un propriétaire envoie en parallèle une commande HTTP authentifiée d’annulation sur une tâche indépendante. Les plages ci-dessous donnent les extrêmes des mesures par vague, avec un p95 calculé sur les premiers fragments de cette vague. Le processus est déjà chaud aux paliers de 30 et 50.

| Pointe synthétique | Premier texte médian | Premier texte p95 | Accusé d’arrêt HTTP |
|---|---:|---:|---:|
| 8 montages du même agent, première vague à froid | 407–417 ms | 425–427 ms | 399–406 ms |
| 8 montages du même agent, vagues suivantes | 125–137 ms | 147–158 ms | 132–140 ms |
| 8 agents, un propriétaire | 135–323 ms | 158–347 ms | 140–324 ms |
| 30 agents, 30 propriétaires | 502–781 ms | 512–792 ms | 502–780 ms |
| 50 agents, 50 propriétaires | 775–1 420 ms | 845–1 609 ms | 843–1 608 ms |

Chaque exécution a produit les 288 réponses attendues et confirmé en base les 12 annulations. Le catalogue a compilé 63 outils à la première vague et zéro ensuite. À 30 agents, les six accusés d’arrêt dépassaient la cible de 500 ms. À 50, l’accusé le plus lent atteignait 1,61 s. [Banc reproductible](../../back/tests/test_agent_startup_concurrency.py)

### Préserver les commandes interactives pendant le montage MCP

Le harnais rend sa connexion SQL après la préparation du contexte. Il admet ensuite quatre préparations locales de catalogue de tâche par worker, avec un plafond configurable via `AGENT_MCP_MOUNT_CONCURRENCY`. La découverte distante et le travail du modèle s’exécutent après la libération de la place. L’annulation HTTP applique désormais le périmètre de gestion à la lecture qui verrouille la tâche, ce qui évite de charger au préalable la tâche et son agent. [Montage MCP](../../back/app/harness/mcp_toolset.py) · [Annulation](../../back/app/task/task_service.py)

Deux exécutions du même banc comparent quatre montages simultanés avec un témoin qui admet toute la vague. Les deux configurations utilisent le même chemin d’annulation. Chaque ligne donne les extrêmes sur six vagues à chaud, avec un propriétaire par agent et un pool PostgreSQL de test de 15 connexions maximum. Chaque vague comporte deux demandes d’arrêt sur des tâches indépendantes. La seconde est programmée 150 ms après le départ et son délai inclut le retard de réveil de la boucle.

| Agents | Montages simultanés | Arrêt au départ | Arrêt en pleine vague | Premier texte p95 par vague |
|---:|---:|---:|---:|---:|
| 30 | 30 | 373–631 ms | 298–565 ms | 471–739 ms |
| 30 | 4 | 75–125 ms | 146–612 ms | 502–903 ms |
| 50 | 50 | 806–1 218 ms | 626–1 007 ms | 829–1 235 ms |
| 50 | 4 | 65–115 ms | 121–280 ms | 827–1 174 ms |

À 50 agents, l’arrêt envoyé au départ passait 252 à 623 ms dans l’acquisition de connexions SQL avec le témoin, contre 0 à 7,1 ms avec quatre montages. À 30 agents, onze arrêts sur douze sont passés sous 500 ms. Le douzième a pris 612 ms pendant une vague où la boucle événementielle a pris 351 ms de retard. Le p95 du premier texte à 30 agents varie davantage avec le plafond. Chaque exécution a livré les 528 réponses attendues aux paliers de 8, 30 et 50 montages et confirmé en base les 30 annulations. Les mesures portent sur le harnais local, PostgreSQL et un modèle simulé à 20 ms. Le fournisseur distant, le scheduler complet, le rendu navigateur, l’endurance et la reprise après redémarrage restent à qualifier. [Banc de charge et tests de révocation](../../back/tests/test_agent_startup_concurrency.py)

Un troisième passage a mesuré le temps de collecte du ramasse-miettes Python qui recouvre chaque requête. À 50 agents dans le témoin, deux arrêts en pleine vague ont pris respectivement 1 031 et 951 ms, dont 419 et 294 ms pendant des collectes. Avec quatre montages simultanés, les trois arrêts en pleine vague ont pris 220 à 237 ms, dont au plus 28 ms de collecte. À 30 agents avec ce plafond, le retard maximal de la boucle a atteint 378 ms alors que les trois arrêts en pleine vague ont pris 182 à 218 ms. Le dépassement de 612 ms de la campagne précédente ne s’est pas reproduit pendant cette mesure.

### Coût de préparation et de streaming par agent

Le catalogue conversationnel et le texte qui décrit les capacités des tâches utilisent désormais la même lecture des connexions actives. Sur deux services, le montage passe de 10 à 8 lectures SQL et de 6 à 4 quand la fonction visible est désactivée pour le propriétaire. Le test révoque puis rétablit cette fonction et vérifie en parallèle les droits d’un second agent. [Test du catalogue](../../back/app/services/tests/test_catalog_sql_budget.py)

Sur 100 appels d’outil successifs et 200 sauvegardes avec un résultat synthétique de 1 Kio par outil, le temps CPU du harnais passe de 0,725 à 0,439 s. Le pic d’allocations suivi par Python est de 1,12 Mo dans les deux cas. Un reçu avec référence de réponse se rattache directement au bon tour. Les anciens reçus conservent la recherche historique. Sur 10 000 fragments de texte sans spectateur, avec 39 blocs déjà affichables, la projection locale passe de 286 à 157 ms CPU en médiane sur trois passages par version. Cette dernière mesure isole le traitement Python et exclut les écritures SQL. [Reprise des outils](../../back/app/harness/tests/test_checkpoint.py) · [Projection d’activité](../../back/app/task/live_checkpoint.py)

Un appel en attente d’une place fournisseur écoute les libérations validées dans PostgreSQL. Un listener est partagé par processus, boucle et base en contention. La vérification périodique avec un délai dispersé de 1,5 à 2,5 s permet l’admission après perte d’une notification. Un test interrompt le processus détenteur et vérifie l’expiration, le réveil à la réconciliation et la libération normale du permis suivant. [Cycle des permis](../../back/tests/test_inference_lifecycle.py)

Le contrôle des droits de dialogue est passé de cinq à deux lectures SQL dans le scénario d’un membre d’équipe. Les listes demandent uniquement les identifiants autorisés. Pour un flux ouvert, le contrôle porte sur l’agent demandé et relit les droits actuels. Une sortie d’équipe ou son archivage retire l’accès dès la lecture suivante. [Politique de dialogue et tests de révocation](../../back/app/agent/tests/test_dialogue_policy.py)

### Saturation du pool à l’envoi des messages

Le premier essai à 50 comptes a épuisé le pool PostgreSQL de 20 connexions et ses 20 connexions supplémentaires. Les requêtes HTTP conservaient leur transaction de préparation pendant que le journal et l’admission attendaient une autre connexion. L’admission conservait aussi sa connexion pendant la vérification du mode Deep. Des envois ont échoué à l’expiration des 30 s d’attente. Les deux étapes rendent désormais leur connexion avant de passer la main. Le test HTTP rejoue le même envoi avec une seule connexion disponible et vérifie que le journal renvoie le même message admis. [Parcours de publication](../../back/app/messenger/native_facade.py) · [Test de non-régression](../../back/app/chat/tests/test_attachment_http.py)

Le banc dédié se lance avec `make tests-e2e ARGS='--config agent-load.config.mjs --project=chromium'`. Chaque compte possède sa session. Le banc mêle lecture de documents, délégation, dialogue et arrêt à des moments variables. Il compte les missions terminées à la fin de la fenêtre, puis contrôle le résultat des demandes encore en cours. Le rapport conserve les échantillons de premier texte dans Chromium, les confirmations d’arrêt en base et les files échantillonnées. Le nombre de places pour les tours de conversation et leurs notifications se règle par worker avec `CONVERSATION_WORKER_CONCURRENCY` (4 par défaut). Le plafond de montage MCP se règle indépendamment. [Banc de charge](../../e2e/load/agent-load.spec.mjs)

### Charge mixte sur l’application assemblée

Chaque palier reçoit du trafic pendant 90 s. Trois comptes utilisent Chromium et les autres l’API. Chaque compte possède son agent et le rôle administrateur des fixtures E2E. Le fournisseur de dialogue émet le premier fragment puis attend 1,2 s avant de terminer sa réponse. Le temps d’arrêt comprend la confirmation de l’état durable par une sonde espacée de 350 ms. Le débit compte les missions effectivement terminées pendant la fenêtre. Les effectifs de premier texte incluent les réponses aux demandes encore en cours à la fin de la fenêtre.

| Comptes | Places par worker | Premier texte p95 (effectif) | Lecture document p95 | Arrêt confirmé p95 | Missions/min | Tours en attente à 90 s | Missions terminées après vidange |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 4 | 33,7 s (9) | 1,42 s | 4,10 s | 15,8 | 18 | 32 |
| 50 | 4 | 66,8 s (6) | 1,80 s | 5,50 s | 10,0 | 33 | 28 |
| 30 | 8 | 30,4 s (9) | 1,72 s | 5,96 s | 17,9 | 12 | 38 |
| 50 | 8 | 51,2 s (6) | 2,30 s | 9,08 s | 15,2 | 28 | 36 |

Les quatre paliers ont terminé toutes les missions attendues et confirmé les arrêts. À 50 comptes, huit places augmentent le débit et réduisent l’attente avant le premier texte sur cette campagne. Le p95 de l’arrêt passe cependant de 5,50 s à 9,08 s et la lecture documentaire ralentit aussi. Le réglage par défaut reste à quatre places. La priorité pour la suite est de maintenir le traitement des commandes interactives pendant que les conversations et leurs notifications saturent le worker.

Avec quatre places, deux premiers textes sur six ont dépassé 65 s à 50 comptes. La vidange a pris 27,5 s après la fenêtre. Les journaux backend des deux paliers totalisent 711 lectures de liste de salons et 776 lectures de boîte de réception pour trois navigateurs par palier. Mesurer la part de ces relectures déclenchée par des événements concernant les autres salons avant d’étendre la concurrence. Une campagne par configuration et ce petit nombre de réponses navigateur donnent un ordre de grandeur. L’endurance sur une heure, les permissions d’utilisateurs ordinaires à ce niveau de charge et un fournisseur distant restent à qualifier.

### Rafraîchissements du Chat personnel sous charge

Dans le témoin à 50 comptes et quatre places par worker, les trois navigateurs ont reçu 12 signaux de message pour les salons ouverts et 579 pour d’autres salons. La liste personnelle et la boîte de réception réagissaient aussi aux salons que ces comptes administrateurs pouvaient consulter au nom d’un agent. Le serveur précise désormais le périmètre du signal pour chaque destinataire autorisé. La vue déléguée continue de traiter les événements. Un salon précédemment visible dans la vue personnelle déclenche une vérification HTTP, et une notification en attente est annulée à la perte de l’accès personnel. Si un badge peut encore inclure ce salon, les signaux rapprochés partagent une vérification différée. [Décision de diffusion](../../back/app/chat/events.py) · [Test de révocation](../../back/app/chat/tests/test_push_service.py) · [Gestion des compteurs](../../front/app/chat/inboxSubscription.test.mjs)

Ces comptes de requêtes GET couvrent les trois navigateurs réunis, après l’ouverture des salons et jusqu’à la fin des demandes en cours. Les visites des autres comptes passent par l’API. Les deux campagnes utilisent le même scénario et quatre places par worker.

| Comptes | Listes de salons avant → après | Boîtes de réception avant → après | Détails d’autres salons avant → après | Premier texte p95 avant → après | Arrêt confirmé p95 avant → après |
|---:|---:|---:|---:|---:|---:|
| 30 | 384 → 50 | 418 → 66 | 930 → 0 | 37,9 → 28,2 s | 4,02 → 3,54 s |
| 50 | 322 → 25 | 353 → 35 | 973 → 0 | 68,5 → 69,5 s | 5,31 → 4,29 s |

À 50 comptes, les trois parcours HTTP passent de 1 648 à 60 lectures alors que les navigateurs ont reçu 651 signaux d’autres salons sur le passage final. Chaque palier a terminé toutes les missions et confirmé tous les arrêts. Les six tours saisis dans Chromium à 50 comptes ont attendu entre la création du tour et sa première prise en charge 39,7 s en médiane et 53,1 s au p95. De la prise en charge à la fin durable, le p95 est de 8,4 s. À 30 comptes, les mesures correspondantes sur onze tours sont de 16,4 s en médiane, 19,9 s au p95 et 8,6 s. Ces durées proviennent des horodatages PostgreSQL des tours et de leurs premières tentatives. Le prochain point à qualifier est le délai d’admission des conversations interactives sous concurrence, en suivant aussi l’âge des tâches de fond et le délai de livraison des notifications.

### Livraison des missions pendant une conversation

Le banc attend le message Messenger de chaque mission synthétique. Son horodatage
permet de mesurer le délai après la fin de la tentative. Il mesure aussi l'attente
des tours saisis au clavier avant la première prise en charge. Un test PostgreSQL
avec deux salons maintient l'observateur d'activité bloqué jusque pendant l'arrêt
du worker et vérifie que les deux tours redeviennent disponibles à la reprise.
[Réveil et interruption](../../back/tests/test_scheduler_wakeups.py) · [Partage des places](../../project/decisions/0178-conversation-worker-recovery.md)

La diffusion Chat vérifie l'identité liée au salon, l'agent et les droits du
destinataire à chaque signal. Sur un message personnel, ce contrôle a demandé
3 lectures SQL contre 16 avec le chargement de la fiche du salon. Pour Web Push,
une seule requête sélectionne les abonnements actifs des destinataires dont
le salon est audible. Le contrôle de présence écarte ensuite les utilisateurs
qui consultent déjà la page. [Destinataires et révocations](../../back/app/chat/tests/test_push_service.py)

Les vérifications du rôle pour un même destinataire partagent une lecture pendant
la diffusion d'un signal. Le signal suivant reprend les droits en base. Un réveil
ordinaire évite les recherches dans les files de livraison et d'autorisation
précédemment constatées vides. Un commit pertinent, un démarrage ou une échéance
de trente secondes déclenche leur réexamen. [Rôles WebSocket](../../back/core/tests/test_websocket.py)

Comparaison sur la fenêtre de 90 secondes décrite plus haut. Le délai de
notification part de la fin de la tentative de tâche et s'arrête à la création
du message Messenger. Les attentes et latences sont des p95.

| Comptes | Version | Admission Chat | Premier texte (échantillons) | Arrêt confirmé | Lecture document | Notification mission | Missions/min | Missions livrées après vidange |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 30 | Témoin | 29,1 s | 39,1 s (9) | 3,51 s | 1,55 s | 96,8 s | 16,5 | 33/33 |
| 30 | Avec modifications | 28,4 s | 44,1 s (9) | 6,66 s | 1,38 s | 9,8 s | 13,9 | 29/29 |
| 30 | Répétition du palier seul | 22,8 s | 30,2 s (11) | 3,00 s | 1,42 s | 4,8 s | 19,8 | 38/38 |
| 50 | Témoin | 51,2 s | 66,9 s (6) | 4,33 s | 1,86 s | 92,0 s | 11,9 | 31/31 |
| 50 | Avec modifications | 46,8 s | 56,8 s (6) | 3,92 s | 1,71 s | 6,2 s | 13,3 | 33/33 |

À 30 comptes, le premier texte et l'arrêt varient assez entre passages pour
écarter toute conclusion de gain reproductible sur ces deux délais. Le délai de
livraison baisse sur les deux passages. À 50 comptes, l'admission concentre encore
46,8 s au p95. Il reste à qualifier cette attente en charge soutenue avec davantage
de navigateurs et un fournisseur réel.

### Anciens salons, rattrapage du flux et 30 à 50 navigateurs connectés

Avec douze missions actives et mille missions terminées depuis une semaine, la préparation des
missions liées au salon passe de 1 014 lectures PostgreSQL à deux. Les scénarios avec zéro et
cent anciennes missions demandent également deux lectures. La sélection temporelle et la limite
des résultats terminaux s'appliquent en base. Les enfants actifs des missions retenues sont lus
ensemble. [Test avec historique synthétique](../../back/app/conversation/tests/test_service.py)

Sur une trace contenant cinquante blocs de réflexion, le rattrapage de cent fragments du même
bloc de réponse transmet environ 0,6 ko contre 45 ko pour le résultat complet. Une coupure de
séquence antérieure à ce bloc déclenche la lecture HTTP. Sur mille blocs identifiés dont la
moitié figure dans le résultat terminal fourni, la réconciliation passe de 389 à 4,3 ms en
médiane sur cinq appels par version dans le conteneur de développement. Les deux versions
produisent le même résultat. [Contrat de streaming](../../back/app/conversation/tests/test_runtime_stream.py)

Chaque compte du banc garde maintenant un onglet Chromium authentifié. Trois comptes saisissent
leurs demandes dans le Chat. Les autres conservent la boîte de réception du shell ouverte
pendant leur parcours API. Le serveur confirme le nombre de comptes connectés au début et à la
fin de la mesure. Un passage par palier, avec quatre places par worker et un fournisseur simulé,
donne les résultats suivants. [Scénario de charge](../../e2e/load/agent-load.spec.mjs)

| Comptes connectés | Signaux du salon du compte / autres salons | Admission Chat p95 | Premier texte p95 (effectif) | Lecture document p95 | Arrêt confirmé p95 | Missions livrées |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 204 / 0 | 28,6 s | 37,8 s (9) | 1,68 s | 3,53 s | 31/31 |
| 50 | 209 / 0 | 61,0 s | 77,4 s (6) | 2,36 s | 6,78 s | 28/28 |

Les deux paliers ont chacun confirmé 25 arrêts. À 50 comptes, 31 tours attendaient encore
à la fin de la fenêtre de charge. La file conversationnelle et les lectures interactives
restent au-dessus des objectifs. Les campagnes précédentes utilisaient trois navigateurs
au total, ce qui limite la comparaison des latences de bout en bout.

### Coût de prise d'un dialogue et observateur lent

Pour un nouveau tour avec entrée, le worker vérifie la présence d'un message lors
de la sélection du tour et conserve le jeton de bail qu'il vient d'écrire. Le test
PostgreSQL borne ce parcours à deux lectures. Si l'entrée semble absente, une
seconde vérification sous verrou précède l'annulation. Les livraisons avancent
sans relancer de lecture dans une file de dialogues déjà constatée vide.

Dans deux salons dont les observateurs restent bloqués, les deux contrôleurs
démarrent. L'arrêt du worker libère les observateurs et remet les deux tours
en attente, sans bail actif. Le test place aussi un tour sans entrée en tête
de file pour vérifier que son annulation laisse démarrer les deux suivants.
[Prise et reprise des tours](../../back/tests/test_scheduler_wakeups.py)

Deux passages du même scénario à 50 comptes connectés, avec quatre places et
90 secondes de trafic, ont donné les mesures suivantes. Les latences sont des p95.

| Mesure | Témoin | Après modification |
|---|---:|---:|
| Attente avant prise du tour dans les salons sondés | 91,8 s | 63,4 s |
| Prise du tour jusqu'à sa fin durable dans ces salons | 10,1 s | 13,1 s |
| Premier texte visible (nombre de réponses mesurées) | 110,3 s (3) | 80,8 s (6) |
| Arrêt confirmé | 10,24 s | 5,69 s |
| Lecture d'un document | 3,75 s | 2,27 s |
| Fin de mission jusqu'au message de notification | 14,2 s | 8,8 s |
| Tours en attente à la fin de la fenêtre | 34 | 33 |
| Missions livrées après vidange | 22/22 | 27/27 |

Le passage après modification a confirmé 25 arrêts et reçu zéro message d'un
autre salon. Le témoin a confirmé 21 arrêts. La variation entre campagnes sur
machine partagée et le faible effectif de premiers textes limitent l'attribution
du gain de latence. L'attente avant prise reste supérieure à une minute au p95.
[Scénario Chromium](../../e2e/load/agent-load.spec.mjs)

### Livraison avec une seule connexion PostgreSQL

Le test du Chat limite le pool à une connexion et renvoie deux fois le même
message entrant. Il suit maintenant aussi sa réponse. Sur le témoin, le
transport acceptait cette réponse, puis le journal Messenger attendait une
deuxième connexion et le tour se terminait avec une livraison inconnue.
Le worker a déjà enregistré son intention d'envoyer lorsqu'il entre dans
Messenger. Il peut donc rendre la connexion après le contrôle des destinataires,
puis rendre celle éventuellement reprise par le transport avant l'écriture
indépendante du reçu. Le texte de fin de mission et les notifications de
Process emploient également ce mode d'envoi. [Test avec pool borné](../../back/app/chat/tests/test_attachment_http.py)

Le banc Chromium mesure désormais aussi la durée de chaque tentative de
conversation entre sa prise et sa clôture en base. Les groupes correspondent
au dialogue, à la demande qui crée une mission et au dialogue que l'utilisateur
arrête. Ces durées se recouvrent entre workers et excluent la publication qui
suit la clôture. [Mesure après vidange](../../e2e/load/agent-load.spec.mjs)

Sur le parcours de finalisation avec transport synthétique et observateur du lien
publié, les quatre variantes de sujet demandaient initialement 13 lectures SQL.
Le budget est désormais de 9. Le test vérifie aussi le sujet reçu par l'observateur,
le retrait du marqueur temporaire et la présence du lien vers le message dès
la notification. [Test de finalisation](../../back/app/conversation/tests/test_service.py)

| Charge mixte à 50 comptes, quatre places | Témoin | Après modification |
|---|---:|---:|
| Durée cumulée des tentatives de dialogue | 177,6 s (24) | 202,0 s (24) |
| Durée cumulée des tentatives lançant une mission | 91,8 s (25) | 92,0 s (26) |
| Durée cumulée des tentatives arrêtées | 95,3 s (24) | 104,4 s (24) |
| Attente avant prise du tour sondé, p95 | 74,4 s | 73,6 s |
| Premier texte visible, p95 | 93,6 s (4) | 96,9 s (5) |
| Confirmation d'arrêt, p95 | 5,78 s | 6,98 s |
| Lecture de document, p95 | 2,73 s | 2,68 s |
| Missions livrées après vidange | 25/25 | 26/26 |

Chaque passage a confirmé 24 arrêts et comptait encore 31 tours en file à la
fin de la fenêtre. Le dialogue représente environ la moitié du temps cumulé des
tentatives. Ces deux passages sur machine partagée ne montrent pas de réduction
du délai avant le premier texte.

## 0. Établir le coût d’un parcours complet

L’audit MCP local a observé, sur une liste de 50 résultats suivie d’une ouverture, un p95 passant de 1,80 s à 3,44 s entre quatre et huit clients, pour environ 3,5 parcours/s dans les deux cas. Dans un essai distinct, l’enregistrement de 98 fonctions a pris 64 ms CPU en médiane par requête. Les essais ont aussi relevé une croissance mémoire. Dream, sur une base neuve, a consacré une part importante de ses lectures à vérifier l’activité et à chercher du travail éligible. Ces mesures désignent des expériences à rejouer sur la version courante. L’attribution du ralentissement signalé reste ouverte. [Campagne et conditions de mesure](../audits/optimisation-generalisee/README.md)

Construire un parcours combinant conversation et délégation, appels MCP concurrents, recherche documentaire, lecture de pièces jointes, suivi temps réel et annulation. Comparer un utilisateur avec 1, 4 et 8 tâches, puis 10, 30 et 50 utilisateurs actifs. Distinguer des agents différents et plusieurs tâches du même agent. Exercer un stockage synthétique ancien, une bibliothèque densément partagée et un serveur au repos. Fixer matériel, quotas, volume, taux d’arrivée et durée. Alterner témoin et candidat sur plusieurs répétitions. Un fournisseur simulé à latence fixe isole Galaris, puis un fournisseur réel sur une campagne autorisée qualifie le bout en bout.

| Question | Mesures à conserver par palier |
|---|---|
| L’interface répond-elle pendant les travaux ? | p50/p95/p99 de navigation, lecture, envoi et accusé d’arrêt. Mesurer séparément premier texte, arrêt effectif, erreurs et reconnexion |
| Où part le temps d’une mission ? | Attente d’admission, préparation MCP et contexte, premier appel modèle, outils, checkpoints, livraison et durée totale. Succès métier, qualité sur corpus identique, coût et jetons par réussite |
| Quelle ressource sature ? | CPU et retard de boucle par processus, RSS pendant la charge et après retour au repos, attente du pool SQL, requêtes et lignes par opération, verrous, I/O, octets HTTP/WebSocket et recalculs côté navigateur |
| La capacité est-elle durable ? | Débit d’arrivée et de sortie, âge du plus ancien travail par classe et propriétaire, taux de reprises, mémoire et temps de vidange après le pic |

Cibles initiales à calibrer avec la référence sur l’hôte retenu : à 30 utilisateurs actifs, p95 des lectures interactives ordinaires sous 300 ms et des accusés d’envoi ou d’arrêt sous 500 ms. Fixer à partir du pilote un budget de propagation des droits, de reprise après panne et de mémoire par worker. Tenir une charge stable pendant au moins une heure et répéter plusieurs vagues avec retour au repos. Publier dispersion et saturation observée à 50 utilisateurs. Toute mesure de gain inclut la qualité des résultats et le travail effectivement terminé. [Métriques de pression](../../back/core/observability.py) · [Contrats fonctionnels](../../docs/fr/dev/functional-tests.md)

## 1. Calculer les catalogues et les accès fichiers une fois par configuration

1. Mutualiser les définitions immuables, signatures publiques, descriptions et schémas par génération du registre. Mesurer la construction FastMCP elle-même. Le registre Python connaît déjà les définitions, mais les wrappers exécutables capturent le contexte courant.
2. Construire deux vues de base par agent et runtime, **discussion** et **tâche**. Faire consommer le même inventaire versionné au planner, au harnais, à la découverte et à l’annonce des outils. Appliquer ensuite les filtres propres au tour, à la voix, au canal mail, aux capacités et aux ressources disponibles. Lier le contexte, les clients et les autorisations à chaque exécution. Vérifier la parité entre harnais interne, accès MCP HTTP et drivers effectivement concernés.
3. Avancer une révision durable dans la transaction de changement de configuration. Couvrir paramètres, connexions et affectations, fonctions, portées, profils, capacités et génération de plugins. Commencer par une invalidation large et une reconstruction paresseuse. Mutualiser les demandes simultanées d’une même clé, borner entrées et mémoire, écarter une construction achevée sous une ancienne révision. Une notification accélère l’invalidation ; une relecture de révision assure la fraîcheur après perte de notification ou redémarrage. Garder le contrôle vivant au moment d’appeler un outil. Pour un catalogue distant, qualifier la notification de changement ou une durée de fraîcheur bornée par connexion.
4. Grouper dès la construction à froid les lectures de services, connexions et fonctions désactivées. Mutualiser l’inventaire des cibles fichiers et leurs capacités configurées. Conserver langue, console, tâche, liaison de connexion et droits distants au périmètre approprié. Dans une opération cohérente, transmettre le descripteur déjà lu entre contrôle et consommation. Étendre aux descriptions de compétences par révision et aux instructions stables uniquement après attribution d’un coût mesurable.

**Réception.** Démarrer huit tâches du même agent, puis de huit agents. Compter constructions, SQL, CPU et délai avant la première inférence. Désactiver une fonction pendant la construction puis entre découverte et appel. Changer une affectation de connexion, couper un serveur MCP distant, annuler le premier demandeur pendant que les autres attendent, puis redémarrer à froid. Vérifier séparation des contextes, reconstruction réussie après échec et mémoire bornée sur des changements répétés. [Construction du harnais](../../back/app/harness/mcp_toolset.py) · [Montage et contrôles MCP](../../back/app/services/mcp_loader.py) · [Budget SQL existant](../../back/app/services/tests/test_catalog_sql_budget.py)

## 2. Ramener tout partage local à ses bénéficiaires effectifs

La bibliothèque applique les règles vivantes avant le comptage et la pagination. Elle calcule les droits d’équipe pour les agents gérés sur la page, conserve les grants directs dans les métadonnées et évite la recherche des membres lorsqu’un utilisateur ne gère aucun agent. Sur 50 documents partagés en lecture avec 50 agents et un humain, avec un grant direct d’édition par document, le backend recevait 2 600 lignes en trois lectures SQL. Il reçoit désormais 50 lignes en une lecture pour chacun des trois profils mesurés (humain seul, gestion d’un agent, gestion globale). Le profil global reçoit toujours les 50 identifiants de bénéficiaires par document. Le gain mesuré porte sur les allers-retours et les lignes transférées entre PostgreSQL et le backend. [Scénario reproductible](../../back/app/document/tests/test_library_performance.py)

Lors de la suppression d’un document, la transaction retire ses bénéficiaires. Pour une feuille, elle cible la seule configuration concernée. Pour un parent, elle recalcule aussi les droits hérités de ses descendants. Les parcours Texte et Données partagent cette règle. Le scénario de suppression d’un parent JSON vérifie qu’un enfant perd le droit hérité et conserve un droit propre après la suppression d’un dossier. [Héritage et suppressions](../../back/app/document/tests/test_sharing_inheritance.py) · [Projection et rollback des données JSON](../../back/app/dataset/tests/test_management.py)

Les entrées et sorties d’équipe mettent à jour la projection du membre dans la transaction d’adhésion. Un utilisateur qui quitte une équipe d’édition conserve sa lecture directe, y compris si un autre opérateur vient de l’accorder. L’archivage recalcule les partages de l’équipe pour tous leurs bénéficiaires. Les anciennes règles liées aux équipes du propriétaire peuvent toucher des tiers et déclenchent aussi un recalcul de l’héritage. [Héritage et annulation](../../back/app/document/tests/test_sharing_inheritance.py) · [Écritures concurrentes](../../back/app/share/tests/test_concurrency.py)

Un nouveau compte humain actif reçoit les documents publics déjà présents. La désactivation retire ses lignes documentaires en une commande SQL. La réactivation recalcule ses accès depuis les règles actuelles, y compris les droits du propriétaire et les partages directs ou hérités. L’état du compte et la projection sont validés dans la même transaction. Sur un compte membre d’une équipe de 50 agents avec 50 documents partagés, les médianes de quatre comparaisons alternées sont de 2,3 ms contre 5,4 ms pour un recalcul complet sur 1 000 documents, et de 2,9 ms contre 60,1 ms sur 10 000. Ces mesures portent sur la projection PostgreSQL seule. [Parcours du compte](../../back/app/document/tests/test_sharing_inheritance.py) · [Mesure reproductible](../../back/app/document/tests/test_library_performance.py)

Un nouvel agent reçoit les documents publics déjà présents. Réutiliser le code d’un agent archivé laisse ses anciens partages privés inaccessibles au nouvel agent. Une interruption avant le commit restaure le code, l’agent et ses droits. Lorsqu’un changement de responsable affecte un document classé, le calcul d’héritage vérifie aussi les droits des tiers. La vérification de l’assistant initial déjà installé lit désormais une ligne SQL avec 1 ou 51 agents, contre respectivement 3 et 53 auparavant. [Cycle de vie des agents](../../back/app/document/tests/test_sharing_inheritance.py) · [Rejeu de l’initialisation](../../back/app/agent/tests/test_default_agent.py)

Sur 1 000 documents, 32 personnes ont ouvert simultanément leurs bibliothèques pendant qu’un archivage attendait le verrou de partage. Chacune a reçu les 49 documents publics et son seul document privé, avec le droit d’édition sur celui-ci. Sur trois vagues identiques, le 95e percentile du service backend est passé de 338, 451 et 502 ms à 288, 404 et 289 ms. La vague à 404 ms dépasse la cible indicative de 300 ms. Le chronométrage inclut la session PostgreSQL. La latence HTTP et le rendu du navigateur restent à mesurer. La liste conserve la recherche et les facettes tout en excluant du résultat SQL le texte indexé, son vecteur et le texte source du résumé. [Essais de concurrence et de volume](../../back/app/document/tests/test_library_performance.py)

Sur une équipe synthétique de 50 agents recevant 50 documents, l’ajout d’un utilisateur a produit les mêmes lignes de lecture et d’édition avec les deux méthodes. Sur deux exécutions de quatre comparaisons alternées chacune, la mise à jour ciblée a pris entre 3,6 et 4,7 ms en médiane, sur 1 000 comme sur 10 000 documents. Le recalcul intégral a pris respectivement 6,7 à 8,8 ms et 61 à 82,9 ms. Le chronométrage porte sur la projection après écriture de l’adhésion, dans une transaction PostgreSQL locale. L’attente du verrou sous forte concurrence et la latence HTTP restent à mesurer. [Comparaison reproductible](../../back/app/document/tests/test_library_performance.py)

Les sources durables restent les règles de partage, les intentions propres aux dossiers et documents, les propriétaires et les appartenances. Le partage « équipe Support en édition » reste éditable et explicable. La lecture rapide utilise **une ligne par ressource partagée et bénéficiaire final**, y compris pour les partages globaux ou hérités. Piloter sur Documents et ses pièces jointes, puis inventorier chaque domaine avant extension aux autres ressources partageables. Une pièce jointe documentaire utilise le droit de son parent. Un fournisseur distant continue d’autoriser son propre fichier. Les mémoires personnelles restent privées. [Modèle commun](../../back/app/share/models.py) · [Héritage documentaire](../decisions/0218-personal-tree-sharing-inheritance.md)

**Schéma proposé.** Une table commune avec clé primaire conforme au dépôt, FK `share_id` vers la configuration exclusive, FK `agent_id` et `user_id` vers leurs bénéficiaires respectifs, et booléen obligatoire `can_write`. Une contrainte impose exactement un bénéficiaire. Deux index uniques commençant par le bénéficiaire garantissent une seule ligne par couple bénéficiaire/partage. Un index par `share_id` sert aux recalculs et suppressions. La ligne accorde la lecture, le booléen précise le droit de modification conféré par le partage. Les domaines continuent d’appliquer restrictions de format, lecture seule, RBAC, périmètre d’outil et règles de gestion des partages. Distinguer l’utilisateur agissant directement de celui qui exerce un rôle ou une délégation.

**Suppressions.** Déclarer les trois FK de la projection avec `ON DELETE CASCADE`, orientées des parents vers leurs seules lignes dérivées. Retirer une ligne dérivée ne supprime aucun parent. Une suppression physique de ressource peut laisser sa configuration en place suivant le cycle métier : vérifier le retrait explicite de sa projection. Une suppression logique, une désactivation, une sortie d’équipe et une restauration demandent un recalcul transactionnel. Restaurer à partir des droits en vigueur. Mesurer aussi les verrous et la durée d’une grande cascade.

**Propagation.** Inventorier toutes les écritures : nouveau document ou bénéficiaire, changement de propriétaire, partage direct/global/d’équipe, appartenance du bénéficiaire ou du propriétaire, déplacement, suppression ou restauration de dossier et de ressource. Calculer le meilleur droit survivant sur chaque couple affecté et n’écrire que le delta. Changer le contenu seul laisse la projection intacte lorsque les règles demeurent identiques. Sérialiser les mutations concurrentes d’une même portée et vérifier la révision avant publication. Une future règle « tous sauf » alimentera le même format ; décider séparément de la priorité d’une exclusion face à un partage direct.

Exemple de réception de bout en bout. Une utilisatrice dispose d’un accès direct en lecture et peut aussi éditer grâce au partage du dossier avec son équipe. Elle quitte l’équipe pendant qu’un document est ouvert. Sa prochaine sauvegarde est refusée, le document reste lisible et sa ligne projetée passe à `can_write = false`. La suppression ultérieure du partage direct le retire de la liste et de la recherche. Répéter avec un agent déjà engagé dans une tâche et un appel d’outil préparé avant la révocation.

**Cohérence et volume.** Publier ensemble règle et projection pour les changements ordinaires. Pour une propagation volumineuse, évaluer une génération construite par lots et activée atomiquement après rattrapage des mutations concurrentes. Si une révocation est validée avant cette bascule, les lecteurs de la portée affectée doivent repasser sur le calcul canonique dans la même transaction que la révocation. Si la fraîcheur est indémontrable et la source indisponible, refuser l’accès concerné. Une révocation confirmée s’applique dès la lecture suivante, y compris aux titres, extraits, totaux, miniatures, pièces jointes et notifications.

Pour les recherches, appliquer le filtre d’accès avant le classement, le comptage et la pagination. Un texte ou un vecteur extrait peut être mutualisé entre bénéficiaires autorisés. Pour suivre un lien entre deux ressources, vérifier les deux extrémités. La suppression d’un droit prend effet même si Dream et les indexeurs sont arrêtés. [Index partagé des ressources courantes](../decisions/0325-shared-current-resource-index.md)

**Migration et réception.** Déclarer la table par SQLAlchemy et employer DbAdmin pour la convergence et un reconciler idempotent pour la projection. Éprouver une mise à niveau depuis l’ancienne version peuplée, un remplissage interrompu et une seconde exécution. Maintenir la projection en parallèle du lecteur actuel et comparer dans un même état de base les listes ordonnées, comptes, pages, lecture et édition. Étendre les tests PostgreSQL de parité, concurrence et héritage. Couvrir deux sources indépendantes d’un droit, perte d’édition avec lecture conservée, changement d’équipe en cours de recherche, suppression physique de chacun des parents, archivage/restauration, rollback, mutation pendant reconstruction et révocation distante. Générer des séquences de mutations et comparer après chaque transaction au calcul canonique.

Comparer sur les mêmes corpus le lecteur actuel, une requête partant du bénéficiaire et la jointure projetée avant pagination. Mesurer sélectivité, plans SQL, taille table/index, nombre de lignes réécrites, WAL, verrous et latence de révocation. Inclure 10 000 ressources partagées avec 100 bénéficiaires, soit un million de lignes, ainsi qu’un grand sous-arbre et une distribution de droits clairsemée. La bascule par domaine exige zéro divergence de droits et un bénéfice net sous charge mixte. [Convergence DbAdmin](../../docs/fr/dev/dbadmin.md) · [Parité](../../back/app/share/tests/test_access_parity.py) · [Concurrence](../../back/app/share/tests/test_concurrency.py) · [Héritage](../../back/app/document/tests/test_sharing_inheritance.py)

## 3. Protéger l’interaction et limiter les lectures répétées

- **Dream et indexation.** Conserver les conditions de repos et la préemption existantes. Distinguer vérification d’éligibilité, découverte récursive, réparation, contrôle d’URI connue et lancement manuel. Mesurer le SQL au repos et le temps de réaction à une sollicitation. Quand un balayage à vide coûte cher, réveiller sur changement ou échéance durable, espacer les cycles vides et conserver une réconciliation de rattrapage. Reprendre les lots au checkpoint suivant. Mesurer aussi l’ancienneté des travaux différés. [Scheduler Dream](../../back/app/dream/scheduler.py) · [Indexation fichiers](../../back/app/file_share/indexing.py)
- **Admission équitable.** Budgéter les travaux périodiques simultanés, les tâches par utilisateur et par mission, les outils parallèles et chaque appel physique au fournisseur. Préserver les barrières des outils exclusifs. Garantir une capacité pour le dialogue, les contrôles, les renouvellements de bail et les reçus. Libérer les transactions SQL pendant les attentes réseau. Rendre visible le motif d’attente. Vérifier qu’un arbre de vingt tâches aboutit et qu’un autre utilisateur peut commencer pendant son exécution. [Ordonnancement Task](../../back/app/task/scheduler.py) · [Admission LLM](ordonnancement-llm-par-fournisseur.md)
- **Écrans et temps réel.** Partir de la liste Task et du chat. Appliquer les progressions à la ligne ou au fragment concerné, regrouper les rafraîchissements et borner la file de chaque client. Relire si le tri, les droits, la page ou une rupture de séquence le justifient. Une demande d’autorisation, une révocation et le résultat final doivent atteindre la vue ou être récupérés au prochain rattrapage. Tester un client lent, une déconnexion et trente abonnés avec des droits différents. Mesurer requêtes, octets, temps de rendu et délai d’affichage. [Store Task](../../front/app/task/stores/taskStore.ts) · [Autorisations WebSocket](../../back/core/websocket.py) · [Tests du chat](../../front/browser-tests/chat-performance.spec.mjs)

## 4. Isoler les exécuteurs et préparer plusieurs instances

Conserver d’abord un processus HTTP/WebSocket et lui retirer un premier travail de fond identifié par les mesures. Le worker Process supervisé offre un précédent local. Affecter des budgets CPU, mémoire et connexions SQL à chaque rôle et vérifier leur somme sur le serveur. Augmenter le nombre de processus seulement lorsque le poste limitant dispose encore de capacité. [Topologie actuelle](../../back/core/server_mode.py) · [Worker Process](../../back/scripts/process_worker.py)

Avant le deuxième exécuteur d’agents, rendre l’admission fournisseur commune à tous les chemins concernés, qualifier les plafonds par acteur et utiliser les prises de tâches et baux durables existants. Acheminer l’annulation vers le détenteur courant. Une perte de bail interdit à l’ancien détenteur de publier un résultat tardif. Parent, enfants, Goal, Process, attentes humaines et callbacks conservent chacun leur propriétaire et leurs transitions durables. Mesurer les retries avec délais croissants et dispersion, et borner l’accumulation quand le fournisseur ralentit. [Machine d’état](../../docs/fr/architecture/state-machines.md) · [Exécution agentique](../../docs/fr/architecture/flows/agent-execution.md)

La réplication de l’API vient après qualification des workers. Distribuer les changements de paramètres et de droits, le routage des événements et des commandes, ainsi que la propriété des listeners, des flux voix et des jobs périodiques. Garantir un seul traitement logique d’une entrée même si deux instances la reçoivent. Un client reconnecté à une autre instance récupère l’état durable et ses droits courants. Dimensionner séparément API, workers, base et fournisseurs à partir du débit mesuré et des files.

## 5. Qualifier les pannes avant chaque bascule

| Injection en environnement isolé | Résultat observable exigé |
|---|---|
| Arrêt brutal d’un worker avant prise, après prise ou pendant l’attente d’un enfant | Une demande acquittée reste retrouvable. Reprise au bon checkpoint après libération ou expiration du bail. Une pause utilisateur et une annulation restent effectives |
| Perte du worker entre appel externe, effet et reçu, ou après commit avant réponse | Utiliser la clé d’idempotence ou rechercher le reçu distant. En cas d’effet indéterminé, suspendre pour réconciliation. Vérifier avec un compteur d’effets distant que la reprise conserve les effets acquis |
| Fournisseur LLM, bridge ou MCP indisponible, lent ou intermittent | Délai borné, attente explicite et retries maîtrisés. Une panne d’un fournisseur laisse l’interface et les autres fournisseurs utilisables. La reprise produit au plus un résultat terminal, sans événement ultérieur |
| PostgreSQL indisponible, commit d’issue inconnue, puis retour | Aucune admission ou révocation annoncée avant preuve durable. Retrouver la commande par son identité avant toute nouvelle tentative. Contrôler connexions, reprise des files et cohérence des droits |
| Arrêt complet du serveur avec missions, reconstructions et autorisations en cours | Redémarrer à froid depuis les sources durables. Perdre les caches mémoire reste supporté. Rétablir settings, catalogues, leases, contrôles et notifications dans un ordre vérifié. Contrôler l’absence de doubles listeners et de tempête de reconstructions |
| Sauvegarde puis restauration sur une instance vierge | Restaurer base, données et sauvegarde séparée des fichiers au point de cohérence documenté. Vérifier contenus, références binaires, droits et journaux. Réconcilier les effets externes survenus après le point restauré avant de rouvrir les exécuteurs |

Chronométrer l’indisponibilité de l’interface, la reprise du premier travail et la résorption de la file. Fixer des objectifs de reprise et de perte admissible selon le scénario : redémarrer sur stockage intact et restaurer une sauvegarde datée ont des garanties distinctes. Vérifier les signaux de santé, le motif précis d’un blocage et la conservation locale des preuves d’échec même si la télémétrie est coupée. N’utiliser que des jeux synthétiques et des services de test pour les injections.

## Bascule, retour et décision de capacité

Pour chaque lot, conserver une référence reproductible, documenter les consommateurs et exécuter les tests ciblés du contrat modifié, puis le parcours assemblé. Introduire les lectures optimisées progressivement par domaine ou rôle. Prévoir le retour au calcul de droits canonique, la reconstruction à froid des catalogues et le retour à un exécuteur unique après drainage et transfert des baux. Répéter ce retour pendant une mission et après une révocation.

Étendre un lot après vérification des résultats métier, des permissions, de la tenue sous charge et de la reprise. Consigner une divergence de droits, un double effet, une perte de commande acquittée, un état terminal modifié ou une file qui croît durablement comme cause de suspension de la bascule. Publier pour le matériel qualifié le nombre d’utilisateurs actifs, les missions/minute, les limites de chaque fournisseur, le coût par réussite, les délais de reprise observés et le premier point de saturation. Ces données détermineront quel rôle renforcer ensuite.
