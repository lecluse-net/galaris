<p align="right"><strong>Français</strong> · <a href="../../en/dev/reliability-operations.md">English</a></p>

# Exploitation des garanties de fiabilité

## Schéma et topologie

Consulter [DbAdmin](dbadmin.md) et la [décision 0073](../../../project/decisions/0073-operational-schema-and-runtime-limits.md).
Exécuter un seul worker Uvicorn par installation. Les caches de paramètres et les connexions
temps réel ne sont pas distribués. `STAGED` et `DEGRADED` signalent des écarts à corriger sans
empêcher une application utilisable de démarrer.

## Budgets et conservation

Les réglages avancés de Tasks exposent `TASK_ROOT_MAX_TOKENS`, `TASK_ROOT_MAX_COST` et
`TASK_ROOT_MAX_SECONDS` (0 = désactivé). Ils couvrent une tâche racine et ses descendants causaux,
y compris les nouvelles tentatives. Les réservations par phase sont des estimations : une phase
active peut dépasser sa réserve et un harnais externe peut déclarer un usage incomplet. Activer
`TASK_BUDGET_SHARE_GOAL` partage ces plafonds entre toutes les tâches des cycles du même Goal,
depuis la création de la première tâche ; les tâches archivées restent comptabilisées.
Les Goals distincts gardent des budgets séparés. Ces contrôles ne garantissent donc
pas un plafond de facture. Augmenter/désactiver le plafond permet la reprise au prochain passage
du scheduler, au plus tard après le délai d’admission de 60 secondes.

Le panneau **Consommation et budgets** du détail d'une tâche charge un instantané à l'ouverture,
actualisable manuellement. `GET /api/tasks/<uuid>/budget` applique le même périmètre de gestion
que la tâche. Il expose la consommation enregistrée de la lignée, les phases actives, les
réservations estimées et le reste après réservations. `null` pour un plafond ou un reste
signifie absence de limite, jamais zéro disponible. Aucun budget n'est activé par cet affichage.
Le relevé ne modifie ni le lease ni l'admission ; la réservation disparaît à l'expiration du bail.

Les quotas HTTP par défaut (1 000/minute/IP et chemin HTTP, configurables dans
**Préférences → Système** via `HTTP_RATE_LIMIT_PER_MINUTE`) sont vérifiés après résolution des
routes modulaires, avant l'autorisation et la validation des champs. Chaque endpoint de login
garde son quota explicite de 10/minute/IP. Le stockage reste local au worker ; les tests de quota
l'activent explicitement. La confiance accordée aux en-têtes proxy se configure au déploiement :
le backend doit rester derrière le proxy de confiance, sans accès direct non fiable.

`TASK_SCHEDULER_FAIRNESS_SECONDS` promeut les tâches anciennes devant les nouvelles demandes.
À 0, les priorités existantes sont conservées. `TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER` borne
les phases simultanées de tous les agents d’un propriétaire (0 = désactivé). Les baux réservent
les places sous verrou transactionnel ; une expiration les libère. Une tâche excédentaire
attend au moins cinq secondes sans changer de phase ni perdre son résultat.

`INCIDENT_TRACE_RETENTION_DAYS` et `LLM_TRACE_RETENTION_DAYS` valent 0 par défaut. Une valeur
positive autorise une purge horaire de 100 détails éligibles au maximum, jamais des lignes
d’incidents ou des coûts. Les fonctions publiques `prune_traces(preview=True)` donnent le nombre
du prochain lot sans mutation. Les détails conversation/process et ceux de tâches potentiellement
requises sont conservés. Sauvegarder les traces nécessaires avant d’activer cette politique.

## Signaux et diagnostic

`runtime_event_loop_lag_seconds` mesure le retard de boucle, et les métriques
`scheduler_periodic_*` les délais et erreurs de
maintenance. La readiness expose `loop_lag_seconds` et `monitor_age_seconds` ; un moniteur vivant
mais sans passage depuis plus de 30 secondes (ou trois intervalles) n’est pas prêt.
Une file qui attend longtemps avec des workers disponibles invite à inspecter les baux, les
budgets et les limites de harnais. Une maintenance répétitivement en échec nécessite d’inspecter
son exception et la disponibilité de son fournisseur. Ne pas redémarrer automatiquement une
phase à effets externes pour faire disparaître ces signaux.

Le démarrage initial utilise `task_objective_preparation_seconds`, `task_admission_seconds`
et `task_initial_queue_wait_upper_bound_seconds`. Ces histogrammes sont émis à la première
prise en charge lorsque les bornes correspondantes ont été enregistrées. Toutes les sources de
tâches enregistrent désormais leur mise en file ; la conversation mesure en plus la préparation.
La dernière mesure inclut la persistance avant commit et les éventuelles pauses avant la
première prise en charge : c’est un maximum, pas une preuve de saturation. Les reprises et les
tâches historiques sans mesure sont exclues. L’ancien `task_queue_wait_seconds`, dérivé de
`updated_at`/`created_at`, n’est plus émis ; actualiser les tableaux de bord sans mélanger les
deux séries. Les durées restent consultables dans la fiche tâche et le détail du round après
redémarrage, indépendamment de la disponibilité de Logfire.

`Task.lifecycle_timing` conserve séparément file, traitement sous bail, pauses utilisateur,
attentes externes et backoff, avec leur répartition par phase. Pour une tâche historique,
consulter les heures de traitement récupérées depuis `llm_calls` ; l’heure de commit ancienne
ne peut pas être reconstituée exactement si aucune trace ne l’a enregistrée.
Les coûts du dispatcher sont projetés depuis les appels persistés, même quand la réponse
est tronquée et que le dispatcher utilise sa décision de repli. Un appel mis à jour plusieurs
fois est compté une seule fois et un abonnement conserve un coût facturé nul.
Les résultats réussis des façades d’inférence communes utilisent la même comptabilité, afin
que la préparation d’un objectif ou un briefing ne remplace pas un coût connu par une estimation.
Les écritures de fichiers vers un transport Messenger enregistrent leur reçu après l’envoi :
la notification finale reconnaît l’URI et la destination exactes et ne renvoie pas la même image.

Les livraisons de conversation et notifications Task/Process `UNKNOWN` se résolvent dans le
détail du tour, avec preuve et privilège d’édition dans le périmètre de l’agent. La décision est
enregistrée par tentative ; un bail actif ou une tentative obsolète empêche sa résolution.
Cette opération ne renvoie aucun message et ne relance aucun travail. Vérifier la destination avant de
marquer l’envoi livré ou abandonné ; l’incertitude ne justifie pas un renvoi automatique.

### Possibilités de vérification par transport

Ce tableau décrit les adaptateurs présents, pas toutes les possibilités théoriques des API.
Une recherche par texte seul ne constitue jamais un reçu : deux envois légitimes peuvent avoir
le même contenu. Conserver l’identifiant distant et la destination lorsqu’ils sont connus.

| Transport | Clé réutilisable après redémarrage | Recherche disponible dans Galaris | Traitement de `UNKNOWN` |
|---|---|---|---|
| Chat interne | Journal canonique local ; pas de clé d’envoi exposée au contrat Messenger | Messages persistés et liens de tour | Vérifier le message durable et sa destination, puis résoudre |
| Matrix | Non : le client génère un nouveau `txnId` à chaque appel | Historique paginé et identifiants d’événements | Vérification distante ; ne pas rappeler `send_to_room` pour rechercher un reçu |
| Nextcloud Talk | Pas de clé durable d’envoi dans l’adaptateur | Historique paginé ; vérification des fichiers par leur nom DAV unique | Vérification distante puis résolution avec preuve |
| OneBot | Pas de clé durable d’envoi dans l’adaptateur | Historique récent selon l’implémentation, sans curseur durable | Vérification distante ; absence dans cette fenêtre insuffisante pour renvoyer |
| Telegram | Pas de clé durable d’envoi dans l’adaptateur | Journal local ; pas d’historique distant via cet adaptateur | Vérifier dans le client destinataire |
| WhatsApp | Pas de clé durable d’envoi dans l’adaptateur | Journal local ; pas d’historique distant via cet adaptateur | Vérifier dans le client destinataire |

La clé Matrix évite un doublon pour une même transaction distante ; son renouvellement à chaque
appel ne permet pas une reprise idempotente après crash. Les adaptateurs actuels ne fournissent
pas de recherche fiable par clé persistée qui autoriserait une réconciliation automatique
générale. La commande humaine conserve donc l’incertitude tant qu’aucune preuve n’est disponible.

## Validation navigateur

`make tests-e2e ARGS='--repeat-each=3'` exécute les mêmes scénarios sur Chromium, Firefox et
WebKit, sans relance automatique des échecs. Le test PWA active le vrai service worker et
remplace le shell dans un volume propre à l’exécution ; les autres scénarios bloquent les
workers pour isoler leur contrat. Traces et journaux restent sous `artifacts/e2e/<exécution>/`.
`GALARIS_E2E_DEBUG=pw:browser make tests-e2e` ajoute le diagnostic des processus navigateur.

Sous Linux, WebKit utilise le port GTK officiel via Xvfb. Le port WPE headless du build 2336
(Playwright 1.62.1) a produit des crashs natifs intermittents pendant la saisie MFA, y compris
sans traces et sans le filtre graphique de la carte. Le protocole signale `crashed: true` ;
ce défaut WPE n’est pas considéré comme corrigé. GTK conserve les mêmes actions, assertions
et traces ; cette couverture ne remplace pas un essai sur Safari/iOS réels.

Le chat rattrape les projections HTTP manquantes tant que sa réponse reste provisoire,
puis arrête ce rattrapage à convergence ou à la fermeture du store. Sans autorisation de
notification, il n’attend pas le worker et n’interroge pas le service push natif. Les abonnements
déjà autorisés continuent à être restaurés.

## Livraison et retour arrière

`make build-release RELEASE_REF=<commit>` archive le commit puis construit/exporte quatre images
dans `artifacts/releases/<commit>`. Les changements non commités ne font pas partie de cet
artefact. Les bases sont figées par digest ; les paquets système sont résolus à la construction.
L’objectif est de promouvoir les mêmes images, sans promettre une reconstruction bit à bit.

Exécuter `make tests-release RELEASE_DIR=<dossier>` : les parcours navigateur utilisent les
images exactes, sans montage du code applicatif, puis les exécuteurs sont testés et toutes
les images scannées. `TESTED_IMAGE_IDS` lie cette qualification au manifeste. Promouvoir avec
`APP_ENV=prod make update RELEASE_DIR=<dossier>` : import et vérification des identités,
`--no-build --pull never --wait`, puis contrôle des conteneurs démarrés. Sans `RELEASE_DIR`,
`make update` conserve son fonctionnement historique avec reconstruction.
`MANAGED_HARNESSES` précise les images de harnais incluses via `RELEASE_HARNESS_IMAGES_FILE`
ou leur statut externe. Conserver le dossier précédent et une sauvegarde DB/fichiers/clés.

Un retour arrière d’image ne restaure pas les données supprimées par une contraction. Vérifier
d’abord la compatibilité du schéma ; sinon restaurer ensemble DB, fichiers et clés.

`UPGRADE_PREVIOUS_IMAGE=<image@sha256:...> UPGRADE_CANDIDATE_IMAGE=<image candidate>
make tests-upgrade` exerce la convergence d'un schéma rempli, le login, un document et sa pièce
jointe, les refus ACL, une seconde synchronisation, puis la restauration sous l'ancienne image.
La release précédente est une entrée obligatoire de la CI. Le mode explicite
`UPGRADE_FROM=<commit> make tests-upgrade` reste disponible pour les régressions de source ;
il utilise les dépendances candidates et ne qualifie pas une ancienne image. Aucun volume de
l'installation n'est utilisé.

## Progression et pression

Les jobs de mesure indépendants s'exécutent toutes les dix secondes. Les labels sont
limités au moteur ou au type de notification ; aucun contenu, identifiant de compte
ou secret n'est une dimension de métrique. Seuils initiaux à calibrer en préproduction :

| Indicateur | Seuil initial | Action |
|---|---|---|
| `process_oldest_pending_seconds` | > 60 s pendant 2 min | Vérifier la file et la disponibilité du moteur, sans resoumettre un effet incertain |
| `process_oldest_observation_seconds` | > 120 s pendant 2 min | Examiner le dernier échec ; corriger connexion/credentials puis rafraîchir le même run |
| `process_unknown_runs` | > 0 pendant 2 min | Séparer indisponibilité d'observation et livraison incertaine |
| `runtime_event_loop_lag_seconds` | > 1 s pendant 1 min | Corréler CPU et I/O, réduire la charge et rétablir les composants en échec |
| `task_oldest_ready_seconds` | > 60 s pendant 5 min | Examiner l'admission et les agents occupés |
| `task_expired_leases` | > 0 pendant deux mesures | Contrôler boucle, pool SQL et reprise du scheduler |
| `conversation_oldest_notification_seconds` | > 60 s pendant 5 min | Vérifier la destination et résoudre avec preuve |
| `buffered_io_reserved_bytes` | > 90 % de 1 Gio pendant 5 min | Réduire la charge binaire ; examiner les opérations actives |
| `db_pool_checked_out / db_pool_capacity` | > 90 % pendant 1 min | Rechercher les transactions longues avant d'augmenter le pool |
| `db_pool_acquisition_seconds` | p95 > 0,5 s pendant 1 min | Distinguer attente de place, connexion et pré-ping ; examiner les timeouts |
| `temporary_filesystem_free_bytes` | < 1 Gio | Libérer le stockage temporaire avant de relancer les transferts |

L'âge d'observation inclut les runs jamais observés. L'âge d'une notification Task
part de sa dernière mise à jour ; ce n'est pas un percentile de livraison. L'histogramme
du pool mesure toute l'acquisition, attente, ouverture et pré-ping compris, avec issue
`acquired`, `timeout` ou `error`. Les mesures de boucle et du système complètent ces jauges.
Les jauges horaires `db_relation_storage_bytes` (données, TOAST et index) et
`db_relation_estimated_rows` (estimation du catalogue) suivent chaque table sans scanner ses contenus.

Objectifs initiaux d'exploitation : login/lecture HTTP p95 < 1 s hors fournisseur,
attente d'admission p95 < 60 s hors quota et absence de lease expiré sous charge nominale.
Ce sont des objectifs à mesurer, pas des résultats déduits du test local.
`tests/test_durable_concurrency.py` exerce une admission saturée avec login réel,
32 lectures d'identité concurrentes, copie de 4 Mio, renouvellement réel de lease,
deux pairs WebRTC locaux et encodage base64 hors boucle. Il mesure p95, hausse RSS,
retard de boucle et trames reçues ; il ne mesure pas la facturation d'un fournisseur distant.

## Rétention et réparation des médias

`GET /api/processes/retention/preview` exige l'administration Process et la portée
Agent globale. L'aperçu ne modifie rien ; ses compteurs représentent le prochain lot.
La purge traite au plus 500 runs et 500 événements par run à chaque passage.
`GET /api/processes/runs/<uuid>/export` permet un export de diagnostic avant purge,
avec administration Process et contrôle du périmètre Agent. Les événements sont paginés
par `after_event` et `next_event`, 50 par défaut, options 10/20/50/100/500.
Les capacités de téléchargement et secrets nommés sont masqués ; les payloads exportés
restent bornés par le sanitizer. Cet export de diagnostic ne remplace pas la sauvegarde
DB/fichiers nécessaire à une restauration complète. Désactiver la rétention pendant
un export de plusieurs pages pour éviter qu'une purge intervienne entre deux lectures.
Les jetons refresh expirés depuis sept jours sont purgés par lots de 500 ; les jetons
non expirés restent disponibles pour détecter les rejeux. Les comptes rendus et
compteurs de coût LLM sont conservés quand les traces de contenu expirent.

Pour une livraison multimédia incertaine :

1. Lire `GET /api/multimedia/runs/<run>/deliveries` et vérifier la destination distante.
2. Attendre l'expiration du `delivery_lease_until`. Conserver le numéro de tentative.
3. Envoyer `POST /api/multimedia/runs/<run>/deliveries/<receipt>/resolve` avec
   `attempt_number`, `evidence` et `decision`. `attach` exige l'URI canonique d'un
   fichier accessible dont les octets correspondent au reçu ; `retry_absent` exige
   une absence vérifiée et aucune URI. Un simple timeout ne prouve pas l'absence.
4. Rafraîchir le même Process. Le média existant est livré ou rattaché, jamais régénéré.

La résolution est historisée et idempotente pour une même tentative et une même preuve.
Un résultat terminal reste immuable. Tant qu'un reçu conserve des octets non livrés,
la rétention ne supprime pas son Process ; résoudre la livraison avant de réclamer cet espace.

## Budgets des transferts

La matérialisation accepte une limite d'octets et un délai global (120 s par défaut).
HTTP compte les octets décompressés ; SFTP et Messenger reçoivent la même limite.
Mail ne télécharge plus une pièce jointe pour calculer son descripteur : sa taille peut
être inconnue. La lecture MIME entière est plafonnée par la politique Mail et par
`2 × limite demandée + 1 000 000` octets d'enveloppe MIME. Un petit fichier contenu
dans un message dépassant cette enveloppe est refusé. L'admission reste réservée
jusqu'à la fin du thread IMAP ; son socket de lecture est interrompu après 120 s,
en plus des délais de connexion/opération configurés.

Les copies SDK/base64 sont prises en compte dans des enveloppes prudentes, avec 1 Gio
partagé et quatre opérations maximum, une par identité d'opération. Les moteurs multimédia
réservent 800 Mo ; leur concurrence effective peut donc être inférieure à quatre.
Le décodage vocal utilise la même admission et produit des lots de 50 trames.
La piste Talk borne sa file à 100 trames de 20 ms ; le producteur attend et un
barge-in invalide les fragments de la génération précédente. Ce plafond ne garantit
pas la RSS totale du backend ou des modèles.

## Sauvegarde cohérente et objectifs de reprise

Avant une sauvegarde de livraison, arrêter l'admission puis attendre ou interrompre les
écrivains applicatifs, y compris les harnais, avant de capturer DB, `/data`, clés et
états externes. Un `pg_dump` seul ne crée pas un instantané atomique des fichiers.
Archiver les identités d'images et les clés avec la sauvegarde, dans un emplacement protégé.

Objectifs initiaux : RPO nul pour la fenêtre de maintenance gelée ; RTO de 15 minutes
pour une petite installation, à confirmer sur son volume réel. Les scripts affichent
la durée de l'exercice ; ce nombre ne comprend pas la détection d'incident ni le transfert
d'une sauvegarde distante. Refaire le test avec le volume de production avant d'affirmer
ces objectifs. Le rollback restaure le schéma et les fichiers puis utilise l'ancien code
ou l'ancienne image ; ne jamais supposer qu'une image précédente tolère une contraction.

L'exercice `make tests-restore` démarre deux producteurs indépendants de documents et de reçus
fichiers, attend au moins dix écritures de chacun, puis demande et attend leur arrêt avant
le dump et l'archive. Il vérifie chaque objet et son SHA-256 après restauration, ainsi que
le nombre d'écritures acquittées. Le RPO mesuré concerne cette frontière de maintenance ;
il ne promet pas une sauvegarde à chaud atomique de fournisseurs externes.

## Contrôles de code

### Chargement frontend et évaluation agentique

Le build frontend imprime `frontend_build_bytes` via `scripts/report-build.mjs` : taille brute
et gzip du graphe d'imports statiques (JS/CSS), séparée de tous les chunks. L'éditeur HTML est
asynchrone : consulter un document ne doit pas initialiser son moteur d'édition. La mesure
exclut les polices et les appels API ; le service worker conserve son précache complet,
donc le volume téléchargé pour une installation PWA n'est pas celui du graphe initial.

Avec `APP_ENV=dev` (transmis au frontend par `VITE_APP_ENV`), le cache PWA est désactivé,
y compris pour un build statique. Il est également désactivé avec le serveur Vite.
Le worker ne met en cache aucune ressource et n'intercepte aucune requête ; à l'activation,
il supprime les anciens caches Workbox de son périmètre sans toucher aux autres caches.
Il reste enregistré pour les notifications push.

En développement, Vite sert aussi `/sw.js` pour les navigateurs qui conservent un ancien
worker de production. Cette URL renvoie le worker canonique compilé en script classique,
avec un précache vide, puis rouvre les onglets contrôlés sur leur URL actuelle. Elle conserve
l'inscription du worker et les abonnements push ; les nouvelles pages utilisent ensuite
`/dev-sw.js` et le hot reload. Sans cette compatibilité, `/sw.js` renvoie le HTML de Vite,
la mise à jour du worker échoue et un simple rafraîchissement peut garder l'ancien écran.
Le test navigateur `pwa-recovery.spec.mjs` reproduit ce passage avec un vrai worker Chromium.

Le dashboard mensuel utilise cinq requêtes SQL : les totaux des deux mois sont regroupés,
les statistiques par agent sont filtrées avant agrégation et les mois disponibles sont réunis
en SQL. Le navigateur conserve au plus six mois consultés pendant 30 secondes et partage les
requêtes simultanées d'un même mois. Actualiser relit le serveur et invalide les comparaisons
en cache. Un changement de session, de rôle ou de privilèges efface les données et neutralise
les réponses tardives. Le cache reste en mémoire ; les appels LLM et l'activité en direct
conservent leurs contrats. Ces garanties sont couvertes par les tests Dashboard backend,
`dashboardStore.test.mjs` et `dashboard.spec.mjs`.

Le [corpus public de validation du Lab](lab-reference-corpus.md) prépare des comparaisons
reproductibles sur les contraintes éditoriales et les preuves de résultat.

### Garanties composées et qualification

Les [objectifs et règles d'alerte initiaux](operational-objectives.json) définissent métrique,
seuil, durée, diagnostic et réparation. Ils servent à configurer la supervision de
l'installation ; leur présence dans Git ne déploie pas des alertes chez un fournisseur.
Le délai d'admission locale est distinct de la durée fournisseur. Aucun de ces contrôles
ne constitue un plafond garanti de facturation.

`make tests-load` exerce pendant une minute deux pairs WebRTC locaux, des lectures HTTP
authentifiées, l'encodage, une file saturée, une copie de fichier et le heartbeat d'un lease.
`make tests-dbadmin-load` teste 100 000 lignes, les écritures concurrentes, une interruption
sous verrou, l'ajout nullable, le backfill, le resserrement et l'indexation. Le volume peut
être ajusté avec `DBADMIN_LOAD_ROWS` entre 1 000 et 1 000 000. Les deux cibles utilisent une
base éphémère. Les expressions CHECK/exclusion sont observées exactement depuis PostgreSQL ;
leur équivalence sémantique et les transformations destructives ne sont pas automatisées.

Le webhook générique accepte `Idempotency-Key` (1 à 255 caractères). Une même clé pour une
même connexion et un même payload renvoie la même Task, même après perte de réponse.
La réutilisation avec un autre payload renvoie 409 ; sans clé, deux demandes restent distinctes.

Les révisions Memory se consultent avec `limit`/`offset`, 50 par défaut et 500 au maximum.
L'interface conserve l'accès aux pages suivantes. La bibliothèque ne charge pas les relations
de révisions ; les facettes sont dédupliquées en SQL. Les traces LLM libérées par Conversation
et Process suivent désormais la rétention configurée ; les identités, coûts et erreurs restent.
`GET /api/llm-calls/retention/preview`, soumis au privilège de purge et au périmètre Agent,
compte les motifs de protection sans afficher les prompts. Les endpoints existants
`/api/llm-calls/history` et `/api/llm-calls/<uuid>` permettent d'exporter les traces autorisées
avant purge ; geler la rétention pendant un export de plusieurs pages.

Pour inventorier les fichiers natifs non référencés, exécuter dans le conteneur backend
`python scripts/memory_orphans.py`, puis poursuivre avec le `next_cursor` via `--after`.
L'inventaire exclut les fichiers de moins d'un jour et protège les anciennes révisions.
Conserver sa sortie JSON avant toute action. Après arrêt des écrivains, l'outil autonome
accepte `--apply <inventaire.json> --quiescent` ; il revérifie les références, taille et mtime.
Ne pas appliquer cet inventaire dans un backend servant encore des écritures. Cette opération
ne remplace pas une sauvegarde et n'est pas lancée automatiquement.

Pour qualifier un bundle, ajouter `UPGRADE_EVIDENCE_DIR=<bundle>` au lancement de
`make tests-upgrade` avec les images précédente/candidate immuables. Ce passage produit
`UPGRADE_QUALIFICATION.json` seulement après convergence et restauration réussies.
`make tests-release` exige cette preuve et produit `QUALIFICATION.json`, lié à toutes les
identités d'images et à l'empreinte de la preuve d'upgrade. La promotion compare aussi l'image
backend installée à l'ancienne image qualifiée (ou au candidat pour une relance idempotente).
Une nouvelle qualification d'upgrade invalide les anciens marqueurs. Pour une première
installation sans backend existant, les tests d'initialisation du bundle restent requis.

`make lint` exécute Ruff (famille Pyflakes complète et captures de variables de boucle) et
ESLint sur les sources JavaScript, TypeScript et Vue des trois couches. Le build frontend
exige aussi le lint ; les erreurs de template et mutations de props sont bloquantes.
Les fichiers de routage peuvent conserver leurs noms `index.vue` et `[id].vue`.
Le typage strict reste assuré par `make typecheck`, y compris Vite et les bridges.

`make tests-coverage` mesure les branches des contrats DbAdmin, session navigateur,
transitions/budgets Task, Process, reçus multimédia et entrées-sorties bornées. Le seuil
bloquant de 95 % ne représente pas la couverture de tout Galaris. Les lignes et branches
manquantes restent visibles dans `artifacts/coverage.xml`. `make tests-mutations` vérifie
séparément que les gardes de transition sont détectées lorsqu'elles sont affaiblies.

## Mesures reproductibles de croissance et de volumétrie

`make tests ARGS='app/llm/tests/test_retention_growth.py'` simule 84 jours de création,
consommation et purge. Il mesure chaque semaine les lignes brutes, leurs octets logiques,
les motifs de conservation et la taille physique PostgreSQL. Le plateau logique ne signifie
pas que les pages MVCC sont immédiatement rendues au système. Après consommation, la purge
conserve les identités, tokens, coûts et résultats métier. Rapport :
`artifacts/llm-retention-growth.json`.

`make tests ARGS='app/memory/tests/test_library_performance.py'` compare une page de
50 documents sur 100 puis 1 000 documents, avec respectivement 10 000 et 100 000 révisions.
Le test borne les requêtes SQL, les allocations Python et le temps, vérifie les ACL et
interdit le chargement des révisions pendant la projection. Rapport :
`artifacts/memory-library-benchmark.json`. Les allocations Python ne sont pas la RSS totale.

`make tests-dbadmin-load` mesure séparément inspection, expansion nullable, backfill,
resserrement, indexation et rejeu sur 100 000 lignes. Un écrivain concurrent relève ses
latences ; une attente de verrou est observée dans `pg_stat_activity` avant interruption
et reprise d'Atlas. Les durées de convergence incluent inspection et planification, pas
seulement le SQL DDL. Rapport : `artifacts/dbadmin-volume-benchmark.json`. Ces tests utilisent
exclusivement la base éphémère et ne modifient pas les volumes de développement.
