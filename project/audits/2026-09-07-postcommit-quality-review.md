# Revue de qualité et de fiabilité après les corrections R01–R25

État examiné : `b8a8b8dfb57b0cd6bc0e6b484ac3cb1b353177ef`, le 7 septembre 2026.
Le worktree était propre. Cette revue ajoute uniquement ce rapport et ses preuves ;
elle ne modifie pas le runtime et ne crée aucun commit.

Des modifications de prévisualisation frontend et de plans sont apparues dans le worktree
pendant la fin de la revue, après les validations rapportées. Elles sont préservées et ne
font pas partie de cet état audité. Les résultats ci-dessous restent attachés à `b8a8b8df`.

## Conclusion

Le socle de contrôle s'est renforcé : typage strict effectif, lint frontend, essais de
concurrence, protections de reprise et outillage de livraison. Les suites passent sur
ce commit. Il reste néanmoins des défauts dans **la composition des garanties** : une
réservation mémoire peut empêcher sa propre livraison, une annulation peut arriver trop
tard pour arrêter une écriture, et un lease présent en base n'empêche pas toujours un
ancien worker de publier son résultat.

J'ai reproduit **10 contre-exemples** : 8 cas backend et 2 frontend. Ils étayent neuf
constats, le Lab étant testé séparément pour l'annulation et le remplacement du lease.
Ces reproductions ont des périmètres explicités ci-dessous ; elles ne sont pas toutes
des pannes observées dans une installation réelle.

Priorité : corriger A01–A09 avec leurs tests de non-régression, puis traiter les limites
de ressources et la chaîne de qualification. Le découpage architectural doit accompagner
ces corrections par domaine, avec des extractions limitées et des contrats de comportement.

## Périmètre et méthode

L'inventaire parcourt toutes les racines `back`, `front`, `harness_manager`,
`browser-executor`, `ssh-executor`, `bin` et `e2e` — sept racines — pour les extensions
Python, TypeScript, Vue, JavaScript MJS et shell. Résultat : **1 318 fichiers hors tests,
309 437 lignes ; 546 fichiers de tests, 111 356 lignes**. Commentaires et traductions sont
compris. Les configurations Docker/CI, manifestes et documents d'architecture ont été
examinés séparément. L'[inventaire par domaine](2026-09-07-postcommit-evidence/inventory.md)
conserve les 122 groupes ; sa [version JSON](2026-09-07-postcommit-evidence/inventory.json)
ajoute les plus grandes unités.

La cartographie compte **69 modules backend**, **33 frontend**, **494 handlers HTTP/WebSocket**,
**99 tables** et **128 outils MCP natifs**. L'inventaire complet n'est pas une affirmation
de lecture manuelle ligne par ligne des 309 437 lignes. La lecture détaillée porte sur
les contrats, propriétaires de données, parcours critiques et frontières identifiés dans
la matrice finale. Les suites couvrent aussi les domaines non approfondis manuellement.

Les statuts utilisés sont :

- **Reproduit** : scénario exécuté sur le code réel, avec DB/fichiers réels lorsque précisé ;
- **Constaté dans le code** : chemin vérifié, sans reproduire toutes ses conditions réelles ;
- **Amélioration structurelle** : objectif de maintenance ou de qualification, sans prétendre
  qu'une taille de fichier ou une absence de test local prouve un bug.

## Vérifications de cet état

| Vérification | Résultat |
|---|---|
| `make tests` | **3 305 passés**, 8 avertissements de dépendances, 148,88 s |
| `make typecheck` | Pyright : 0 diagnostic ; **376 tests frontend passés** ; 4 517 paires FR/EN et messages chinois vérifiés |
| `make lint format-check architecture-check` | Conformes ; **27 tests d'architecture passés** ; cartes à jour |
| `make tests-harness-manager tests-browser tests-executor` | **26 / 13 / 9 tests passés** |
| `make tests-e2e` | **48 passés** sur Chromium, Firefox et WebKit, 2,8 min |
| Sondes backend supplémentaires | **8 contre-exemples reproduits**, 0,37 s hors préparation DB |
| Sondes frontend supplémentaires | **2 contre-exemples reproduits** |

Les [sondes et instructions de rejeu](2026-09-07-postcommit-evidence/README.md) restent hors
des suites produit : leurs assertions décrivent les défauts, pas le comportement souhaité.
Les fournisseurs sont simulés ; aucun appel payant ni compte distant n'a été utilisé.
Les E2E de cette revue utilisent la stack de test habituelle. Ils ne constituent pas
une nouvelle qualification d'un bundle de production immuable. Les essais de restauration,
d'upgrade, de couverture et les scans d'images du [lot précédent](2026-09-07-review-completion.md)
sont des preuves historiques distinctes, non réexécutées ni présentées comme nouvelles ici.

## Défauts et risques prioritaires

### A01 — P1 — Les budgets de génération et de livraison peuvent se bloquer mutuellement

**Reproduit sur le contrat de réservation ; chaîne d'appel vérifiée.**
`MultimediaEngine.get_run` réserve 800 000 000 octets jusqu'à la fin de la livraison.
La livraison Messenger appelle `upload_file_path`, puis Telegram/WhatsApp réservent trois
fois la taille du fichier dans le même budget global de 1 073 741 824 octets. Pour 100 Mo,
le cumul atteint 1,1 milliard : la réservation interne expire tandis que la réservation
externe ne peut être libérée. Le seuil de cette combinaison est d'environ **91,25 Mo**,
inférieur à la limite de sortie multimédia de 100 Mo.

Sources : `back/app/multimedia/engine.py:158`, `back/core/util/byte_budget.py:18`,
`back/app/file_share/messenger_transport.py:153`, `back/bridge/telegram/messenger.py:352`
et `back/bridge/whatsapp/messenger.py:341`. La sonde n'envoie pas de fichier : elle reprend
exactement les montants et démontre l'impossibilité de composer ces réservations.

Autre conséquence à traiter : l'attente d'admission locale de 30 s devient `engine_timeout`
et consomme les tentatives de départ dans `process_service.py:1643`, bien qu'aucun fournisseur
n'ait été contacté. Une pression locale prolongée peut ainsi devenir un échec définitif.

**Piste :** définir une réservation par phase ou une enveloppe transmissible aux sous-opérations,
compter les allocations réellement simultanées, distinguer attente locale et tentative distante.
**Critère :** une sortie de 100 Mo vers Messenger est livrable sous la limite globale ; une
file saturée reste en attente et ne consomme pas de tentative fournisseur.

### A02 — P1 — Le succès fournisseur n'est pas protégé jusqu'à la livraison finale

**Reproduit au niveau du moteur.** `MultimediaEngine._receive`, à partir de
`back/app/multimedia/engine.py:109`, protège les Process déjà terminaux. En revanche,
un Process encore actif ayant reçu et persisté son fichier peut voir `provider_state=success`
remplacé par `error` lors d'une observation tardive. La sonde sauvegarde un reçu audio,
applique une erreur tardive puis obtient une vue Process en erreur malgré le reçu présent.

Le budget local sérialise normalement les appels du même agent dans un processus Python.
La course de production concerne notamment plusieurs processus : ce verrou mémoire n'est
pas un verrou distribué. Le callback HTTP actuel n'appelle pas `_receive` ; il n'est pas
présenté ici comme l'origine de cette course.

**Piste :** protéger en base les étapes admission, résultat fournisseur, acquisition des
fichiers et livraison ; conserver le succès fournisseur indépendamment d'un retard de
livraison, et journaliser une observation contradictoire sans détruire la preuve.
**Critère :** un polling ancien ne fait régresser ni un résultat durable ni sa comptabilité,
y compris entre deux workers et après redémarrage.

### A03 — P2 — Une création Memory annulée peut encore créer un fichier orphelin

**Reproduit avec de vrais fichiers.** `NativeFileStorage.create` attend directement
`asyncio.to_thread(_atomic_write, ...)` (`back/app/memory/storage.py:67`). Annuler la coroutine
n'arrête pas le thread : la sonde reçoit `CancelledError`, puis le thread crée le fichier.
L'appelant n'a jamais reçu son identifiant. Dans `memory/service.py:751`, la création du
fichier précède l'objet DB et le bloc de nettoyage ; ce cas échappe donc à ce nettoyage.

`create_stream` contient aussi des écritures, flush et remplacement en thread sans attendre
leur fin de manière protégée lors de l'annulation. Le helper `core.util.transfers` fournit
déjà un exemple plus robuste pour cette frontière.

**Piste :** terminer ou annuler proprement la phase fichier avant de rendre l'annulation,
puis supprimer une création non référencée. Ajouter une réconciliation prudente des fichiers
orphelins, avec ancienneté minimale et inventaire avant suppression. Pour la durabilité après
coupure système, vérifier aussi la synchronisation du répertoire après remplacement atomique.
**Critère :** annulation à chaque point d'attente : aucun fichier durable non référencé,
aucune écriture sur descripteur fermé, ancienne révision conservée.

### A04 — P1 — Une racine facultative peut bloquer le superviseur entier

**Reproduit par injection d'une racine qui ne termine pas son démarrage.**
`RuntimeSupervisor._try_start`, `stop` et la relance attendent directement les callbacks
sans délai propre (`back/core/runtime.py:168`, `:290`, `:311`). Le démarrage est séquentiel ;
`back/main.py` attend sa fin avant d'ouvrir le lifespan. `critical=False` n'isole donc pas
une coroutine de démarrage ou de nettoyage bloquée.

**Piste :** délais de démarrage et d'arrêt par composant, surveillance indépendante et
nettoyage borné. Une intégration facultative reste dégradée pendant la reprise ; une racine
indispensable détermine toujours correctement la readiness.
**Critère :** racine facultative bloquée au démarrage ou à l'arrêt : API et supervision des
autres racines continuent ; aucune seconde instance n'est lancée tant que l'ancienne n'est
pas effectivement arrêtée. Aucun blocage réel de cette nature n'a été observé pendant l'audit.

### A05 — P1 — Le plafond des récurrences calendaires intervient après l'allocation

**Reproduit avec le parseur réel.** `events_between` et `due_actions` appellent
`recurring_ical_events...between`, puis vérifient la longueur de la liste
(`back/bridge/calendar/ical.py:100`, `:125`, `:134`). Un petit calendrier récurrent de la
sonde produit **5 000 occurrences** avant le rejet à 1 000. Les appels sont synchrones depuis
les services async ; une expansion plus importante peut immobiliser la boucle et empêcher
un timeout asyncio de s'exécuter à temps.

**Piste :** borner l'expansion elle-même, les fenêtres et les règles de récurrence ; isoler
le calcul potentiellement coûteux hors de la boucle, avec une limite de travail réellement
interrompable. Conserver le curseur avant le lot non admis.
**Critère :** calendrier petit mais explosif : coût CPU/mémoire borné avant matérialisation,
les autres calendriers et les renouvellements de leases continuent.

### A06 — P1 — Le Lab publie sans revérifier le lease et l'annulation

**Deux courses reproduites avec transactions PostgreSQL indépendantes.** Dans
`back/app/lab/mechanism_evaluation_service.py:2514`, le worker prend un lease puis exécute
l'inférence. À `:2687`, il ajoute son résultat, incrémente les compteurs et efface le lease
sans comparaison atomique de son jeton. À `:2707`, il lit `cancel_requested` depuis l'objet
ORM déjà chargé, sans recharger la demande concurrente.

La première sonde enregistre une annulation pendant l'inférence : le run finit `partial`
avec `cancel_requested=True`. La seconde remplace le jeton dans une autre transaction :
l'ancien worker efface ce nouveau jeton et publie quand même. Elle démontre l'absence de
contrôle du jeton, sans prétendre avoir simulé deux appels fournisseurs réels.

**Piste :** reprendre le run sous verrou après l'inférence, vérifier propriétaire et jeton,
recharger l'annulation, rendre résultat/compteurs/clôture atomiques et idempotents. S'appuyer
sur le contrôle de jeton déjà présent dans `app.goal.runner` plutôt que créer une nouvelle
sémantique. Définir la conservation et le coût d'un résultat produit après annulation.
**Critère :** ancien worker sans lease : aucun effet sur l'état courant ; annulation durable
respectée ; résultat et coût comptés une seule fois après reprise.

### A07 — P2 — Une action Process terminée tardivement réouvre l'ancienne sélection

**Reproduit sur le vrai store Pinia.** La garde de `openRun` protège deux lectures concurrentes,
mais `refreshRun(A)` et `cancelRun(A)` rappellent inconditionnellement `openRun(A)` après
leur attente (`front/app/process/stores/processStore.ts:144`). Rafraîchir A, sélectionner B,
puis laisser A terminer ramène l'affichage à A.

**Piste :** capturer sélection et génération au départ de toute action ; mettre à jour la
liste sans réouvrir une fiche qui n'est plus sélectionnée. Appliquer aussi la règle aux
erreurs tardives et aux fermetures de dialogue.
**Critère :** rafraîchir/annuler/supprimer A puis ouvrir B ou fermer : aucune action tardive
ne reprend le contrôle de l'interface.

### A08 — P2 — Quitter une room hors ligne n'annule pas son abonnement différé

**Reproduit sur le vrai module WebSocket avec socket simulé.** `joinRoom` ajoute un callback
`once('connect')`, alors que `leaveRoom` ne fait rien hors ligne
(`front/core/websocket.ts:120`, `:145`). Joindre puis quitter une room avant reconnexion
émet encore `room.join` pour cette ancienne room.

**Piste :** maintenir l'ensemble des abonnements souhaités, réconcilier à chaque connexion
et retirer les intentions au départ/logout. Éviter l'accumulation de callbacks anonymes.
**Critère :** seuls les abonnements encore souhaités sont rétablis, sans doublon. La sonde
ne démontre pas de contournement des ACL serveur ; le défaut concerne le cycle d'abonnement.

### A09 — P1 — Le masquage Atlas ne couvre pas le mot de passe encodé dans une URL

**Reproduit avec un secret synthétique.** `_atlas_database_url` encode les caractères réservés
du mot de passe, mais `_scrub` et `_bounded_plan` remplacent seulement sa forme brute
(`back/core/dbadmin/_internal/atlas.py:39`, `:54`, `:60`). Une URL passée au scrubber conserve
un mot de passe entièrement décodable lorsque celui-ci contient notamment `@`, `:` ou `/`.

L'exposition dépend d'un message Atlas contenant cette URL. Aucun secret réel ni aucune
fuite en production n'ont été recherchés ou observés.

**Piste :** masquer structurellement les credentials des URL, couvrir les encodages usuels
et appliquer le même filtre à tous les chemins d'erreur/plan. Garder des erreurs utiles.
**Critère :** tests avec secrets réservés/encodés : aucun secret récupérable dans les sorties,
sans supprimer les informations nécessaires au diagnostic DbAdmin.

## Compléments à planifier

### A10 — P2 — Borner les entrées TTS avant leur mise en mémoire

**Constaté dans le code.** Le nouveau budget de décodage intervient après réception du
contenu. `back/bridge/elevenlabs/speech.py:205` utilise un `client.post` qui charge la réponse
avant `SpeechResult`; il n'y a pas de limite d'octets à cette frontière. La protection du
décodeur ne borne donc pas l'allocation amont. `media_transport.py` vérifie également la
taille après extension du tampon et utilise un timeout par opération HTTP, pas un délai
global propre à cette fonction.

Définir taille et délai global dans les contrats Speech/Media, streamer avant accumulation,
compter les octets décodés et propager l'annulation jusqu'au transport. Tester réponse sans
Content-Length, flux lent, compression et plusieurs synthèses simultanées. Réutiliser les
primitives existantes après correction de A01, sans multiplier les plafonds contradictoires.

### A11 — P2 — Donner au webhook générique une identité de livraison

**Constaté dans le code.** `back/app/webhook/functions.py:120` appelle `task_service.create`
sans clé d'idempotence, alors que cette fonction accepte une telle clé à `:280`. Un retry
du webhook après perte de réponse crée un nouveau travail pour le même événement externe.
Ce chemin est distinct du journal Messenger, qui possède déjà sa déduplication.

Définir une identité émetteur/connexion/événement, persister admission et référence Task,
puis renvoyer le même reçu lors d'une redelivery. Ne pas dédupliquer simplement par texte :
deux demandes intentionnellement identiques doivent rester possibles. Tester la perte de
réponse après commit et les collisions entre connexions.

### A12 — P2 — Étendre la rétention causale aux traces conversationnelles et Process

**Limite existante confirmée.** `back/app/llm/retention.py:34` exclut tous les appels portant
un `conversation_round_id` ou `process_run_id`, même quand ce travail est terminé et consommé.
La rétention configurée n'est donc pas un plafond général de ces traces. Ce conservatisme
protège les preuves ; il ne faut pas le remplacer par une suppression aveugle selon l'âge.

Définir pour chaque consommateur quand il libère prompts/réponses bruts, conserver coûts,
identités et reçus, puis ajouter aperçu/export/compteurs par motif de protection. Mesurer
la croissance sur plusieurs semaines simulées, incluant travail actif et livraison incertaine.

### A13 — P2 — Paginer les relations coûteuses, pas seulement les lignes principales

**Constaté dans le code.** `_item_options` charge toutes les révisions de chaque MemoryItem
(`back/app/memory/service.py:283`). La bibliothèque documentaire l'emploie à `:2683` et lit
ensuite tous les mots-clés visibles pour chaque page. Une page de 50 documents ne borne donc
ni le nombre de révisions chargées ni le travail sur l'ensemble du corpus.

Séparer les projections de liste et de détail ; charger l'historique uniquement à la demande,
avec pagination. Calculer les facettes en SQL ou les mettre en cache avec invalidation définie.
Ajouter des budgets de requêtes, de lignes chargées et de mémoire sur des documents ayant
beaucoup de révisions ; le seul benchmark de reconstruction sémantique ne couvre pas ce chemin.

### A14 — P2 — Lier la promotion à la preuve d'upgrade du couple exact de versions

**Constaté dans les scripts.** La CI de release exécute bien `tests-upgrade` avant
`tests-release`. Mais ce dernier crée `TESTED_IMAGE_IDS` après E2E/scans sans enregistrer la
preuve d'upgrade ; `bin/update-release.sh:7` exige ce fichier, pas le couple ancienne/nouvelle
image testé. Le parcours local peut donc produire le marqueur sans essai d'upgrade.

Ajouter au manifeste : commit des tests, digest précédent, digest candidat, résultat de
convergence et de restauration, limites du jeu de données, statut des harnais externes.
La promotion vérifie la correspondance avec l'installation visée. Un bundle qualifié pour
une autre version précédente doit être distingué d'un bundle qualifié pour cette installation.
Conserver le chargement sans rebuild et le chemin de restauration coordonnée déjà implémentés.

### A15 — P2 — Faire porter les contrôles sur les frontières réellement fragiles

**Amélioration des contrôles.** Les dix sondes passent entre les suites actuelles. La couverture
ciblée de `back/coverage-critical.ini` inclut checkpoints et réparation multimédia, mais pas
`app.multimedia.engine`, le stockage natif Memory, le superviseur ni le worker Lab. Le pourcentage
global du sous-ensemble ne garantit pas chaque contrat. Par ailleurs, Make formate 24 modules,
alors que l'étape de formatage de `.github/workflows/quality.yml` n'en liste que six.

Centraliser la définition des contrôles Make/CI. Transformer les sondes en vrais tests de
non-régression au moment des corrections ; ajouter matrices d'annulation, changement de lease,
ordre d'observation et réservations imbriquées. Étendre progressivement la couverture par
contrat et la mutation des gardes. Pour le frontend, activer les règles sur les promesses
oubliées aux frontières async ; garder un lint progressif sans reformatage massif.

### A16 — P2 — Poursuivre le découpage avec des responsabilités vérifiables

**Dette mesurée, déjà connue.** Il reste 284 imports privés admis, 25 paires bidirectionnelles
backend et une composante cyclique de 17 domaines ; sept paires frontend. Les tailles actuelles
incluent Memory service **4 008 lignes**, Lab mécanismes **2 963**, page Goal **2 823**, page Agent
**2 442**, planner **2 325**. Les fonctions `_stream` Hermès et `run` conversation interne font
respectivement **649** et **547 lignes**. Ces tailles ne prouvent pas un défaut.

Priorités concrètes : moteur multimédia en étapes durables ; worker Lab séparant claim,
inférence et publication ; Memory séparant listes, révisions et stockage ; composables dédiés
aux actions longues des pages. Employer des DTO/ports étroits, pas seulement réexporter les
modèles ORM pour faire baisser le compteur d'imports privés. Réduire la baseline après chaque
extraction et vérifier que la responsabilité, pas seulement le fichier, est devenue plus simple.

### A17 — P2 — Qualifier les évolutions DbAdmin sur des volumes et verrous réalistes

**Amélioration de qualification.** Le staging nullable et les actions facultatives restent
les bons mécanismes. Les observations d'index ont progressé, mais elles ne constituent pas
encore un contrat complet pour toute contrainte CHECK/exclusion ou toute expression SQL.
La limite de commande Atlas est de 600 s par défaut ; les tests de petits schémas ne mesurent
pas les verrous et scans nécessaires sur une grande table.

Ajouter des scénarios de tables peuplées volumineuses avec écritures concurrentes : ajout,
backfill, resserrement, indexation, interruption et reprise. Faire apparaître le coût attendu
des phases et tester les postconditions avant toute automatisation destructive supplémentaire.
Ne pas imposer une erreur bloquante pour une convergence facultative ou une colonne qui peut
rester nullable pendant le remplissage.

### A18 — P2 — Rendre les objectifs d'exploitation mesurables sur l'installation

**Qualification restante.** Les jauges d'âge, de pool, de stockage et de temporaires sont utiles.
Les seuils du guide restent des points de départ : le test local WebRTC ne représente pas un
réseau TURN, les quotas fournisseurs, toutes les tailles de corpus et la production pendant
plusieurs jours. Les avis de sécurité sans correctif doivent rester inventoriés et suivis.

Définir quelques objectifs : délai d'admission, délai de livraison, âge maximal sans progrès,
temps de reprise et perte admissible à la frontière de sauvegarde. Associer à chacun une alerte,
un diagnostic et une réparation testée. Qualifier l'upgrade depuis la véritable image déployée
et la restauration sur un volume représentatif ; distinguer sauvegarde quiescente et sauvegarde
à chaud. Ne pas annoncer de plafond de facturation à partir des seuls contrôles d'admission.

## Couverture des domaines

| Périmètre | Examen de cette revue | Suite pertinente |
|---|---|---|
| Core API, User, Authorize, Params, WebSocket | Contrats, middleware/sessions, tests globaux, contrôles de routes et lifecycle frontend | A08 ; conserver les courses de révocation déjà corrigées |
| Database, DbAdmin, runtime et utilitaires | Lecture des réservations, transactions, superviseur, URL Atlas ; sondes ciblées | A01, A04, A09, A17 |
| Agent, Harness, Harnesses, Task, Goal | Contrats d'exécution, scheduler, comparaison des leases Goal/Lab, tests et inventaire des grandes unités | A06, A15, A16 ; matrice de crash de chaque driver à étendre |
| Process, Tools, MCP, Connection | Admission, refresh, checkpoints, rétention, exposition MCP et frontières | A01, A02, A07, A12, A16 |
| LLM, multimédia, Audio, Image, Voice | Transports Media/TTS, états fournisseur, livraison, tests et E2E | A01, A02, A10 ; contrats fournisseurs réels non exercés |
| Messenger, Chat, Conversation | Contrats, journal, transport de fichiers, reconnexion et stores ; E2E | A07, A08, A12 |
| FileShare, Memory, documents, Contact, Topic | Stockage natif, listes/révisions, ACL et projections par contrats/tests | A03, A13, A16 ; Contact/Topic n'ont pas une nouvelle revue ligne par ligne |
| Dream, Skill, Lab | Worker Dream, stockage Skill, worker Lab, contrats et tests globaux | A06, A15, A16 ; étendre les essais inter-processus du stockage Skill |
| Dashboard, Onboarding, Incident, Browser | Inventaire, contrats/routes et suites disponibles ; exécuteur réel pour Browser | Contrôles fonctionnels spécifiques à enrichir selon les usages |
| Mail, Calendar, n8n | Contrats, admission durable et reprise ; lecture Calendar/Mail, parseur réel Calendar | A05, A11 ; comptes CalDAV/IMAP/n8n distants non utilisés |
| Telegram, WhatsApp, Nextcloud | Lecture des chemins de livraison, réservations et gestion d'erreurs ; suites réexécutées | A01, A02, A10 |
| Matrix, OneBot et autres bridges de messagerie | Contrats canoniques, inventaire et suites du dépôt | Étendre une matrice commune multiparties/redelivery/annulation ; pas de serveur externe testé |
| Bridges de harnais et fournisseurs IA | Registre/contrats, transports ciblés, tests existants, inventaire des adaptateurs conditionnels | A10, A16 ; aucune qualification de tous les services payants |
| Console, SSH, harness manager | Contrats, contrôle/threads, tests fichiers et cycle de vie ; 26/9 tests | A03 comme règle transversale de gestion des annulations |
| Front core/app/bridge | Inventaire complet, typage/lint, modules Process/WebSocket, grandes vues et trois navigateurs | A07, A08, A15, A16 ; accessibilité complète des 37 pages non certifiée |
| Docker, Make, CI, livraison | Lecture build/load/test/update et workflows ; contrôles exécutés | A14, A15, A18 |
| Documentation et décisions | Confrontation cartographie/contrats/rapports historiques | Maintenir les limites explicites, distinguer preuves locales et qualification de production |

Un module sans fichier de test propre peut être exercé par des suites contractuelles communes.
Inversement, une suite verte n'est pas la preuve que chaque méthode de son module a été relue.
Cette distinction vaut pour tous les groupes de l'inventaire.

## Ordre de travail proposé

1. **Sécuriser les frontières avec un contre-exemple :** A09, A01, A06, A02, A04, A05,
   puis A03/A07/A08. Ajouter le test qui échoue avant correction, puis inverser son attente.
2. **Compléter les garanties opérationnelles :** bornes amont TTS, identité des webhooks,
   rétention causale et publication de la preuve d'upgrade (A10–A14).
3. **Réduire le coût des prochaines évolutions :** projections de lecture, contrôles communs
   Make/CI et extractions ciblées (A13, A15, A16), avec baisse de dette mesurée.
4. **Qualifier l'installation :** gros schémas, charge prolongée, fournisseurs de test,
   restauration et ancienne release authentique (A17/A18).

Dans toutes ces étapes, préserver le choix opérationnel de DbAdmin : **ajouter la colonne
nullable avec diagnostic non bloquant, permettre son remplissage, puis la rendre NOT NULL
lors d'une convergence ultérieure**. Le blocage est réservé à l'impossibilité de fournir
un objet indispensable ou de préserver correctement les données et effets existants.
