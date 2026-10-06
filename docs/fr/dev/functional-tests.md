<p align="right"><strong>Français</strong> · <a href="../../en/dev/functional-tests.md">English</a></p>

# Catalogue des garanties fonctionnelles

`back/app/image/tests/test_image_mcp.py` couvre les références d'image sous forme d'URI,
de liste ou de liste JSON encodée, le nettoyage des temporaires et le nom conforme au format
natif sans conversion ni remplacement d'un fichier voisin. Le parcours de
`back/app/memory/tests/test_document_resources.py` génère un PNG synthétique, le copie en pièce
jointe, l'intègre au document et vérifie les droits du lecteur.
`back/app/chat/tests/test_native_facade.py` vérifie l'envoi MCP d'un fichier à un humain,
avec et sans Task, sur de vraies transactions PostgreSQL indépendantes : la synchronisation de
la room ne bloque pas son propre reçu, les octets et le message restent lisibles. Ce scénario
emploie `committed_database` ; les savepoints partageant une connexion masqueraient ce blocage.

L'analyse documentaire relève de `app.llm` et ne crée aucune définition ni exécution
de processus métier. `back/tests/test_document_analysis.py` protège cette séparation,
la reprise des lots de 500 pages sans double facturation, l'annulation, les droits,
la progression par le scheduler et le transfert idempotent des anciens runs techniques.

AgentAdmin est documenté dans [agent-admin.md](agent-admin.md).
`back/app/agent/tests/test_avatars.py` vérifie le stockage JPEG dans une limite de 500 × 500,
les proportions, l’absence d’agrandissement, l’orientation EXIF et la transparence.
Son parcours HTTP remplace un PNG synthétique de plus de 8 Mio par un JPEG compact,
puis vérifie qu’un remplacement invalide conserve l’avatar et sa révision.
`back/app/agent/tests/test_agent_admin.py` protège le CRUD sans contexte humain HTTP,
le périmètre du responsable, les services système et la délégation réservée aux humains,
les 34 fonctions et leur révocation sur un serveur MCP monté. Les appels directs sans Process
vérifient l’image valide, le fournisseur incertain, la révocation, le profil modifié,
l’avatar tardif, la suppression et le rejeu d'une autorisation sans nouvelle soumission.
`back/app/process/tests/test_dbadmin.py` vérifie la purge ciblée des anciens workflows avatar,
y compris leurs jobs et événements, sans supprimer les processus métier ni bloquer leurs Tasks d'attente.
`e2e/specs/agent-admin.spec.mjs` vérifie la création et deux portraits successifs réellement
affichés après navigation Vue sans rechargement, une civilité renommée et le refus après
révocation, avec un fournisseur synthétique.
`front/browser-tests/agents.spec.mjs` retarde la réponse d'un ancien catalogue puis
vérifie qu'elle ne retire pas le portrait chargé par le catalogue courant et que son
URL temporaire est libérée.

`back/app/agent/tests/test_planner_collections.py` couvre les traitements répétés : petits lots
mécaniques connus d'au plus cinq éléments en une feuille sans découverte ni replanification,
décomposition des traitements substantiels ou des lots trop grands/inconnus, une Task
par élément de collection, vagues bornées, inventaire Dataset vérifié avec les ACL, refus des listes
incomplètes ou ambiguës, progression et reprise après rechargement sans rejouer les succès.
Le parcours PostgreSQL conserve l'inventaire figé même si le Dataset est modifié ensuite.

Le corpus synthétique `back/app/lab/planner_boundaries_corpus.json` contient 24 cas de
granularité : collections ordonnées, reprise partielle, volumes inconnus, petits lots,
tâches uniques complexes, PLAN forcé, plan écrit explicitement demandé et clarification.
Il s'importe avec `scripts/import_lab_reference.py --corpus planner-boundaries --install`.
`test_reference_corpus.py` vérifie l'import authentifié, la persistance et les contrats.
Les références sont des exemples sémantiques ; les critères `acceptance_by_case` permettent
de distinguer plans vides, tâches uniques fragmentées et collections manquées. La qualité
requiert des appels réels et une revue des plans, pas seulement ces tests sans modèle.
`back/app/lab/tests/test_evaluation.py` interdit un verdict favorable pour une sortie
sans brief ou étapes, ou mélangeant plan et clarification. Les fixtures de succès des
tests de génération et de revue utilisent donc un vrai plan exécutable.
`back/tests/test_protocol_inference.py` reproduit une réponse fournisseur `response.failed`
contenant un appel d'outil vide : l'inférence et sa trace restent en échec, en flux comme
en réponse JSON, au lieu de transformer cet appel en plan accepté.

Ce catalogue part des usages et des responsabilités des modules. Les suites citées sont les
points d’entrée vérifiables ; une ligne ne signifie ni couverture exhaustive ni qualification
d’un service externe. Les résultats exécutés et les remplacements sont consignés dans
[la revue du 10 septembre](../../../project/audits/2026-09-10-functional-tests.md).

Pour une évolution, préciser la garantie changée et celles à préserver, lire leurs contrats
et tests, puis choisir la couche la moins coûteuse qui prouve l’effet. Conserver un test utile
est une décision à part entière : aucun quota de tests nouveaux par module.

## Parcours traversant plusieurs domaines

`front/browser-tests/async-views.spec.mjs` couvre l'ouverture différée d'un vrai éditeur,
la saisie dans le reste de la page pendant l'attente, la fermeture avant la réponse,
la réouverture et le réessai du chargeur sans perdre le brouillon, sur mobile et desktop.
Un téléchargement de module en échec reste explicite sans imposer un rechargement global.
`provider-resources.spec.mjs` conserve la sélection d'un modèle lorsque le formulaire
arrive après la transition d'onglet. `memory.spec.mjs` impose une seule recherche et une
seule lecture des filtres à l'initialisation de l'agent de la page Mémoire.

`back/tests/test_api_read_cost.py` ouvre et réouvre les Documents via HTTP avec 1 puis
1 000 révisions : contenu courant frais sans matérialiser l’historique, ancienne version
lisible et pagination bornée. Il mesure aussi identité, Agents, bibliothèque, propriétaires
et cycles Goal, puis vérifie les refus après retrait du gestionnaire et du rôle.
`app/agent/tests/test_management_scope.py` couvre l’invalidation du périmètre à l’écriture,
aux changements de rôle, aux fins de transaction et après la réponse ;
`core/user/tests/test_refresh_session.py` couvre le contrôle compte/session regroupé,
les jetons historiques, l’expiration, la révocation et les UserToken.
`core/user/tests/test_token_management.py` exerce les routes HTTP réelles : gestion
des jetons personnels et MCP réservée aux JWT web, refus des UserToken même administrateurs,
absence de mutation après refus, isolation entre propriétaires et fermeture des conversions
UserToken → JWT par `keep-alive` ou changement de rôle. Le parcours web conserve création,
consultation, modification, révocation et renouvellement ; les appels API ordinaires restent possibles.
La même suite vérifie le refus des jetons API pour les comptes, mots de passe, avatars,
MFA, aides masquées, rôle par défaut et préférences LLM/voix, y compris les routes administratives.
Le changement de mot de passe en session web reste possible et révoque l’ancienne session.
`core/user/tests/test_user.py`, `test_help_dismissals.py`, `test_mfa.py` et
`app/llm/tests/test_personal_speech.py` conservent les parcours web de ces réglages.
Les cycles restent lisibles si un document Goal manque, tandis que le détail conserve
son erreur ; `app/goal/tests/test_goal_runner.py` vérifie aussi propriétaire et référent.
Ces budgets SQL synthétiques ne constituent pas une mesure de latence en production.

`app/browser/tests/test_network_permissions.py` couvre permissions durables par agent/origine,
réponses par texte et boutons, refus, nouvelle demande après suppression ou expiration,
concurrence entre sessions SQL, priorité de la connexion, DNS mixtes, filtres et droits HTTP
des gestionnaires. `browser-executor/network-proxy.test.mjs` utilise Chromium et des serveurs
synthétiques pour vérifier POST, redirections, isolation, HTTPS avec validation du certificat,
WebSocket et révocation. `front/browser-tests/permissions.spec.mjs` vérifie la liste réelle,
ses filtres, la suppression, la fermeture par fond de modale et le réessai après erreur.
La même suite backend vérifie l’accord couvrant tous les sites, sa révocation, la priorité des
filtres et la séparation du réseau local, ainsi que le français, le chinois et la langue par défaut.
Les accords historiques par site ne sont pas élargis ; les anciennes questions sont remplacées
avant de recueillir un accord pour tous les sites.
`app/tools/tests/test_action_authorizations.py` vérifie l’accord permanent par fonction et
connexion, la reprise sans rejeu de l’action initiale et l’exécution suivante sans question.
Elle couvre aussi le claim concurrent, le refus non répétable, l’expiration, les quotas,
la révocation du contexte ou de la configuration, YOLO et les préconditions des fichiers.
Une copie reprend après un accord ponctuel ou permanent seulement si la source observée
est inchangée ; le changement de mode ne retire pas sa précondition.
Le choix permanent refuse une configuration MCP changée, y compris si le changement
survient entre la préparation de l'appel et la création de sa question.
Les routes HTTP réelles refusent le jeton système d'un runtime sans son contexte,
acceptent un contexte valide, refusent un contexte révoqué et conservent les clients MCP indépendants.
`app/connection/tests/test_function_modes_migration.py` prouve sur PostgreSQL la conversion
des anciens booléens, le rollback et le rejeu après un choix humain ultérieur.
`app/harnesses/tests/test_runtime_control.py` vérifie les appels suspendus, la réponse de claim
perdue et le redémarrage sans réexécution. Les workflows Mail et Process vérifient les permis
avant effet et la réconciliation après une issue inconnue.
`app/process/tests/test_common_authorizations.py` exerce le transport MCP et les transactions
réels : pause, révocation, changement de workflow, reprise après la fin de la Task,
réponse perdue et priorité d'un callback terminal sur une observation révoquée.
`bridge/deepseek_harness/tests/test_runtime_authorizations.py` exerce les routes HTTP
du runtime pour l'accord, le refus, la révocation et l'annulation, sans relancer le SDK.
`make tests-harness-runtimes` exerce les SDK embarqués Codex, Claude, Hermes et DeepSeek,
avec modèle et transports externes synthétiques : aucun effet avant accord, refus, reprise
de l’appel exact et continuation MCP. Cette qualification ne prouve pas un déploiement.
La réponse d’autorisation DeepSeek est retardée dans le transport synthétique : le test
attend l’état suspendu avant de répondre et annule les workers encore actifs en cas d’échec.
Les diagnostics ToolAdmin utilisent des serveurs HTTP/SSE synthétiques successifs et vérifient
les bornes du catalogue sans exécuter ses fonctions. Chaque serveur repart avec son indicateur
d'arrêt SSE réinitialisé, car la bibliothèque le conserve au niveau du processus de test.
`e2e/specs/tool-authorizations.spec.mjs` vérifie dans l’application assemblée l’accord et le
refus, la réouverture, le clavier, YOLO et les fonctions bloquées à 390 et 1440 pixels.
`front/browser-tests/action-authorizations.spec.mjs` couvre le choix permanent avec sa portée
explicite, les trois langues, le clavier, le mobile et le réessai après un refus HTTP.

La stabilisation du journal et du streaming est couverte par
`back/app/agent/tests/test_reasoning_guard.py` (fragments irréguliers, snapshots rejoués,
absence de faux positif sur un mot découpé) et `back/app/incident/tests/test_capture.py`
(tentatives distinctes, clés historiques, diagnostic après rollback, enrichissement sans doublon
ni fuite dans le résultat MCP). Les tests de rétention empêchent une observation tardive de
restaurer une trace expirée. `test_editorial_html.py` conserve le contenu et la révision après
refus de mutation ; `app/image/tests/test_image_mcp.py` conserve le rejet des URL privées et
le guidage vers l'URI canonique, sans contacter le fournisseur d'images.

Les aides contextuelles des écrans métier restent visibles jusqu’à une fermeture
explicite, mémorisée définitivement par compte et par aide. Les écrans courants et le
menu Préférences restent sans aide. Le Lab porte une explication de sa philosophie
uniquement sur son accueil ; `lab-access.spec.mjs` couvre cette distinction et le
journal des échecs sans aide. `core/user/tests/test_help_dismissals.py` prouve la persistance, l’isolation
des comptes et l’idempotence sur l’API réelle. `context-help.spec.mjs` couvre la croix,
« J’ai compris », réouverture, préférences préexistantes, erreurs et nouvelle tentative,
réponses tardives et changement de compte avec les composants Vue/Quasar réels.
Les textes restent dans les catalogues des domaines ; modifier une traduction ne
réinitialise jamais le statut « vu ».

`front/browser-tests/client-config.spec.mjs` couvre la génération Codex/Claude Code
depuis les jetons utilisateur : sélection de profils disponibles, copie sans secret,
profils incomplets, droits, états vide/erreur, réouverture et réponses tardives.
Le parcours utilise la vraie page et les composants Quasar sur mobile et desktop.

`back/tests/test_profile_gateway.py` vérifie que les références à des tâches,
modèles ou runs dans les résultats d'outils des clients externes restent du contenu
sur les API de profils OpenAI et Anthropic : streaming terminé, modèle conservé,
aucune corrélation déduite du texte. `test_anthropic_api.py` et
`test_call_router_lineage.py` préservent la corrélation des runtimes gérés.

Le nom du jeton API est figé dans les traces LLM : `test_profile_gateway.py`
couvre Messages, Chat Completions, Responses, embeddings et décisions, ainsi que
renommage/suppression, jeton sans nom et alternance avec une session navigateur.
`test_inference_lifecycle.py` vérifie sa transmission au worker sans hériter du
jeton d'un autre appel. `front/browser-tests/llm-calls.spec.mjs` couvre son affichage
et les appels historiques ou rattachés à un agent.

Le suivi des tâches pendant la génération d'arguments d'outil est couvert par
`app/harness/tests/test_message_fragments.py` et `test_executor_streaming.py` :
progression durable sans faux résultat d'outil, arrêt des flux silencieux et des deltas
vides. `test_inference_lifecycle.py` vérifie sur PostgreSQL que les boucles de suivi,
les leases et le journal ne retransfèrent pas les requêtes complètes ; les scénarios
de reprise et `test_protocol_inference.py` préservent ordre, erreurs et comptabilité.
Le même scénario impose zéro requête pendant une fenêtre de silence, puis une livraison
sur notification ; il couvre plusieurs lecteurs et un commit entre lecture et attente.
`core/tests/test_commit_notifications.py` vérifie commits, savepoints et rollbacks.
`tests/test_scheduler_wakeups.py` vérifie les réveils après mutations durables, les délais
de retry et l'absence de scans des files au repos malgré une maintenance périodique.

La structure documentaire de la #168 est couverte par
`back/app/memory/tests/test_document_structure.py` : une mémoire par PJ, conservation obligatoire
des descriptions d'images, projection sans modèle, dossiers visibles récursivement depuis les
documents autorisés et classements personnels séparés. Les scénarios utilisent une vraie base,
y compris des connexions concurrentes et un ancien travail Dream rejoué. `memory.spec.mjs`
vérifie l'invalidation d'une vue ouverte et le rejet d'une réponse antérieure à la révocation.

La [campagne du 12 septembre](../../../project/audits/2026-09-12-functional-regressions.md)
renforce les admissions et reprises de Process, la facturation et la livraison des médias,
la publication des évaluations, les sessions, les limites de ressources et la synchronisation
DbAdmin. Les défauts reproduits sont reliés à leurs scénarios et à des mutations exécutables
dans `project/regressions.json`.

Les chargements différés sont également vérifiés par `select-lifecycle.spec.mjs`
(fermeture/réouverture, réponses tardives, sélection enregistrée et révocation) et
`e2e/specs/deferred-tabs.spec.mjs` (onglets Connexions/Autorisations avec vraie API et DB,
sélection d'agent et conservation du filtre en revenant sur l'onglet, mobile et desktop).
Ce dernier reproduit aussi une réponse tardive de la bibliothèque Documents pendant le
chargement de la page suivante : la sélection automatique ne doit pas annuler la navigation.
Les répétitions E2E partagent une base isolée : les références créées portent des libellés
uniques, et les scénarios utilisent la recherche et la pagination pour retrouver leurs données.
Le driver local `internal`, quand sa définition est disponible, ne déclenche pas de
lectures d'état du superviseur. Les autres drivers restent inspectés, dont le driver
réseau commun aux runtimes Codex, Claude et DeepSeek. Une indisponibilité du catalogue
ne masque pas leur supervision ni sa reprise après erreur.
Les sélecteurs sans champ de recherche sont parcourus au clavier, y compris leurs options
virtualisées ; les civilités restent sélectionnables au-delà des 500 premières références.
Avant un rechargement volontaire, ils attendent les réponses HTTP concernées. Le collecteur
`e2e/page-errors.mjs` conserve les erreurs JavaScript et réseau ; il exclut une erreur XHR
native de WebKit uniquement si une annulation de la même requête est observée.
Son attente suit les événements de fin ou d'échec des requêtes en cours, puis les requêtes
déclenchées par leurs réponses, jusqu'à la fin de cette séquence. Elle exclut le long polling
Socket.IO et couvre aussi la navigation juste après connexion.
Lors d'une navigation complète, les requêtes du document quitté ne participent plus à
cette attente : une requête lancée pendant son remplacement peut disparaître sans événement
de fin. Les erreurs restent observées et les requêtes du nouveau document sont suivies.
Les parcours de crédits attendent chaque résultat visible ; ils n'attendent pas les lectures
de quota annulées au changement de fournisseur, tout en conservant l'observation des erreurs.
Les tests de push vérifient l'admission, la déduplication et les effets durables des réponses
du fournisseur (succès, abonnement disparu, refus et indisponibilité), avec une vraie DB.

| Usage | Garantie observable | Preuves principales |
|---|---|---|
| Message → tâche | La demande source et les pièces jointes survivent à une synthèse incomplète ; le contexte la complète sans historique aval. Une redelivery retrouve la tâche admise, sans doubler ni réécrire son objectif | `back/app/messenger/tests/test_journal.py`, `back/app/conversation/tests/test_task_admission.py`, `test_task_objective.py`, `test_service.py` |
| Approbation de dossier | La demande conserve la langue du chat ; le participant autorisé répond par numéro sans round LLM, ou par un choix interprété ; DbAdmin répare les anciens destinataires sans approuver | `back/app/dream/tests/test_topic_classification.py`, `back/app/messenger/tests/test_service_incoming.py`, `front/app/chat/services/chatService.test.mjs` |
| Tâche → conversation | Une fin durable livre son résultat une fois ; une reprise retrouve le message | `back/app/conversation/tests/test_service.py`, `e2e/specs/chat.spec.mjs` |
| Activité et reprise | Le résultat terminal du round prime sur les erreurs de tentatives ; une indisponibilité des choix ne révoque pas la sélection et une nouvelle recherche permet la reprise | `back/app/conversation/tests/test_monitoring_service.py`, `front/browser-tests/execution.spec.mjs`, `front/browser-tests/topics.spec.mjs` |
| Choix chargés à la demande | Les sélecteurs agents/sujets vides ne chargent rien avant ouverture ; une annulation, un changement d’agent ou une fermeture de formulaire ne produit pas de fausse erreur ; une panne réelle reste visible et permet une nouvelle recherche | `front/browser-tests/filter-loading.spec.mjs`, `front/browser-tests/goals.spec.mjs`, `front/browser-tests/topics.spec.mjs`, `front/core/api.test.mjs` |
| Process → tâche en attente | Un callback autorisé libère l’attente ; doublons et événements tardifs préservent résultat et erreur | `back/app/process/tests/test_recovery.py`, `test_worker_concurrency.py` |
| Document → fichier → agent | Le contenu, sa révision, ses URI et ses ACL restent cohérents entre lecture et écriture | `back/app/memory/tests/test_editorial_html.py`, `back/app/file_share/tests/test_resource_service.py`, `e2e/specs/editorial-html.spec.mjs` |
| Document Dataset | Type immuable, JSON source préservé, erreurs sans révision, partage/classement/icône communs, copie/restauration et conflits ; CodeEditor conserve le brouillon invalide | `back/app/memory/tests/test_dataset_documents.py`, `test_document_classification.py`, `test_document_library.py`, `front/browser-tests/dataset-documents.spec.mjs`, `e2e/specs/dataset-documents.spec.mjs` |
| HTML interactif dans un document | Formulaires HTML directs vers Dataset partagé, ACL et accords personnels liés à la révision ; révocation, copie non autorisée entre Datasets, validation JSON et quotas entre workers ; texte éditable et barre habituelle, code uniquement dans Source ; impression et PDF statiques avec filtrage des ressources ; isolation, WebRTC, saturation du pont et réponses tardives | `back/app/memory/tests/test_document_apps.py`, `front/browser-tests/document-apps.spec.mjs`, `e2e/specs/document-apps.spec.mjs` |
| Arrêt / reprise / concurrence | Un ancien worker ne remplace pas le propriétaire courant ; les effets ambigus ne sont pas rejoués aveuglément | `back/app/task/tests/test_active_lease.py`, `back/app/harness/tests/test_checkpoint.py`, `back/tests/test_durable_concurrency.py` |
| Accusé d’outil perdu | Une commande SSH reste unique après perte de réponse et relecture PostgreSQL ; un timeout MCP après effet bloque le rejeu ; le retry conserve le journal | `make tests-recovery`, `back/app/harness/tests/test_ssh_checkpoint_recovery.py`, `back/app/harness/tests/test_execution_evidence.py`, `back/app/console/tests/test_durable_operations.py` |

## Domaines applicatifs

`app/harness/tests/test_conversation_interrupt.py` interrompt un vrai agent Pydantic AI
pendant une génération bloquée et vérifie qu'un outil déjà commencé termine une seule fois.
`test_conversation_prompt.py` couvre le branchement dans le contrôleur réel et la conservation
du brouillon dans sa trace. Les intégrations Conversation conservent les messages en rafale,
refusent un lease étranger et distinguent reprise sans effet et consommation après effet.
`app/tools/tests/test_mcp.py` distingue les fonctions autorisées mais absentes du run des
fonctions montées, en FR/EN, sans exposer les fonctions refusées. Le test du serveur agrégé
dans `test_mcp_loader.py` vérifie que cette découverte observe bien le serveur du run.

`app/conversation/tests/test_service.py` couvre l'arrêt conversationnel répété d'une Task
active, réussie ou en erreur : résultat, cause et révision terminaux sont conservés, et
la portée d'agent reste obligatoire. `app/tools/tests/test_mcp_loader.py` distingue un
refus HTTP 403 distant d'un refus local dans le diagnostic français/anglais, sans changer
la catégorie d'erreur utilisée pour les effets ni exposer URL ou réponse du fournisseur.

Les tests `app/harness/tests/test_execution_evidence.py` font poursuivre ou arrêter un
véritable agent Pydantic AI après des erreurs MCP, sans arrêt terminal imposé ni répétition
des effets lors de la reprise. `test_runtime_guards.py` conserve leur visibilité comme
erreurs. `app/file_share/tests/test_path_normalization.py` vérifie les écritures SFTP
vers des dossiers absents et le confinement dans le home. Ce contrat remplace l’arrêt
automatique sur erreur observée ; les interruptions sans réponse restent réconciliées.

Le contrat dispatcher du 16 septembre est couvert par `test_dispatcher_planning.py` et
`back/tests/test_dispatcher_inference.py` : un round humain produit `EXEC standard` sans appel LLM,
les pairs IA gardent leurs limites et les inférences v1 gelées restent rechargeables. Dans
`test_conversation_prompt.py` et `test_executor_streaming.py`, une réponse réussie sans outil ou
répétitive ne provoque aucun jugement ni relance ; l'exécuteur peut toujours admettre le travail.
Les anciens tests de rejet d'action/artefact et de comparaison de formulations sont retirés avec
ces contraintes. `test_action_guard.py` conserve les garanties de reprise sur erreur et de
livraison idempotente ; `test_scheduler.py` vérifie qu'un ancien verdict de garde ne contourne
plus l'exigence de checkpoint après un effet.
Le lot suivant ajoute la matrice des capacités de chaque provider et l'application distincte
d'EXEC standard, EXEC high et PLAN. `test_dispatcher_inference.py` prouve la persistance
d'une décision de Task à choix unique sans appel LLM ; `test_registry.py` protège la reprise des
anciennes décisions. Le Lab contrôle les mêmes couples via `test_contracts_and_passes.py`.

Le corpus synthétique `back/app/lab/dispatcher_boundaries_corpus.json`, importable avec
`scripts/import_lab_reference.py --corpus dispatcher-boundaries --install`, oppose les lots
reprenables séparément aux documents uniques, chapitres liés, sites cohérents et petits lots
mécaniques. Il remplace l'ancienne assertion de formulation imposant toujours EXEC high en cas
de doute. `test_reference_corpus.py` vérifie son import autorisé, sa persistance et ses contrats ;
ces tests ne mesurent pas le routage du modèle. Comparer les prompts avant/après dans le Lab avec
le même modèle et plusieurs répétitions, en examinant séparément les PLAN manqués et les PLAN
abusifs, notamment sur les documents uniques.

La matrice durable du dispatcher couvre FR/EN et Chat/Responses avec le SDK réel, une base
isolée et le seul transport fournisseur simulé. Une sortie sans route suivie d'une correction
valide conserve les deux sorties dans le journal, mais seule la correction fixe langue et
effort. Un pair IA conserve sa politique sans retry : une sortie invalide entraîne `END`
dans la langue du contexte. Une sortie valide sans champs facultatifs conserve les défauts
historiques `standard` et `en`. La relecture restitue le même résultat validé sans nouvel
appel, avec les coûts et corrélations de chaque tentative physique. Cela ne qualifie ni les
comptes réels ni plusieurs objets concurrents dans une même réponse fournisseur.

Les fichiers `test_*.py` ci-dessous se trouvent sous `back/app/<module>/tests/`, sauf chemin
explicite. Les fichiers `*.spec.mjs` se trouvent sous `front/browser-tests/`.

| Module | Usage et risques à protéger | Suites à conserver ou renforcer |
|---|---|---|
| `agent` | Choisir un agent autorisé, appliquer sa politique, produire un résultat terminal cohérent | `test_management_scope.py`, `test_facade.py`, `test_executor_lifecycle.py`, `agents.spec.mjs` |
| `harness` | Exécuter outils et streaming, reprendre sans répéter les effets, libérer les ressources | `test_checkpoint.py`, `test_runtime_cancellation.py`, `test_executor_streaming.py` |
| Frontière des harnais | Refuser les résultats et événements invalides avant publication, fermer les flux, respecter les capacités déclarées | `make tests-harness-contracts`, `app/agent/tests/test_driver_boundary.py` |
| Politique des harnais | Même configuration pour tous, conflits SQL, restriction des outils à l’appel, checkpoints opaques et retry sûr | `test_execution_configuration.py`, `test_checkpoint_contract.py`, `harness-policy.spec.mjs` |
| SDK réels des harnais | Exécuter dans les quatre images épinglées avec modèle local ; vérifier la connexion MCP DeepSeek | `make tests-harness-runtimes`, `artifacts/harness-runtimes/summary.txt` |
| `harnesses` | Changer de runtime sans perdre une tâche active ; révoquer/configurer selon les droits | `test_service.py`, `test_runtime_actions.py`, `test_router.py`, `configuration.spec.mjs` |
| `task` | Créer, suspendre, reprendre, terminer et supprimer une tâche ; préserver budget et propriété du lease | `test_task_service.py`, `test_workflow.py`, `test_active_lease.py`, `test_budget.py`, `task-panel.spec.mjs` |
| Nouvelle demande après échec | Conserver la relance conversationnelle délibérée et manuelle ; une création indépendante préserve l'état, l'erreur et le résultat de la tâche échouée et reste idempotente. Le choix sémantique entre relance et création relève des consignes du modèle | `back/app/tools/tests/test_mcp_loader.py`, `back/app/conversation/tests/test_service.py`, `back/app/task/tests/test_task_service.py` |
| Working Set Task | Conserver les ressources racine/enfants, checkpoints et première capsule lors de commits concurrents ; enregistrement idempotent et rollback avec l'appelant | `back/app/task/tests/test_working_set.py` (sessions PostgreSQL indépendantes) |
| Amendement conversationnel | Tolérer les seules révisions techniques avec une définition connue ; refuser avant interruption un checkpoint incompatible ou une exécution sans point de reprise vérifiable, même apparus après lecture ; préserver la cible et permettre une création indépendante explicite et idempotente dans le même document | `back/app/task/tests/test_amendment_service.py`, `back/app/conversation/tests/test_service.py`, `test_task_admission.py`, `back/app/agent/tests/test_checkpoint_contract.py`, `back/app/agent/tests/test_realtime.py` |
| Remplacement explicite | Enregistrer un seul successeur texte/voix, attendre le nettoyage ou une preuve d'arrêt valide, reprendre après changement de worker, préserver les autres pauses et tâches ; bloquer sur une relance, une coordination ou un changement de contexte du prédécesseur | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `back/app/agent/tests/test_driver_boundary.py` |
| Propriétaires et événements tardifs | Refuser le renouvellement d'un lease expiré ; ne pas remplacer le round affiché à partir d'un événement d'un autre round, demander une réconciliation serveur | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `front/app/chat/runtimeState.test.mjs` |
| Rattrapage Chat | Préserver la conversation courante face aux succès/refus HTTP tardifs ; conserver une réponse utile si une requête plus récente échoue ; réarmer les trous de stream pendant HTTP et après changement de sélection ; une révocation courante purge toujours le contenu | `front/browser-tests/chat-recovery.spec.mjs` (page et store réels, frontière HTTP remplacée) |
| Caches client et avatars | Mutualiser cinquante bulles et les écrans consommateurs ; borner taille et durée ; séparer les endpoints autorisés ; invalider après mutation/session ; préserver les autres lecteurs après annulation ; mutualiser les sélecteurs sans conserver les listes | `front/browser-tests/chat-avatars.spec.mjs`, `front/browser-tests/avatar-cache.spec.mjs`, `front/core/util/sessionReadCache.test.mjs` |
| Catalogues partagés | Réutiliser agents, titres, groupes et paramètres entre ouvertures ; relire après F5, expiration, sauvegarde ou rafraîchissement forcé ; isoler les brouillons et ignorer les réponses supplantées | `front/browser-tests/agents.spec.mjs`, `front/app/agent/agentStore.test.mjs`, `front/app/agent/services/agentService.test.mjs`, `front/core/params/paramsStore.test.mjs` |
| Interruption et reconnexion Chat | Une correction supplante le round en cours ; les deux entrées et une seule réponse finale restent visibles après fin hors ligne puis rechargement, sur les trois moteurs de navigateur | `e2e/specs/chat.spec.mjs` (stack complète, contrôleur scripté à son port public) |
| Commandes conversationnelles | Conserver la demande entière lorsque l'arrêt nécessite une interprétation ; arrêter immédiatement une cible unique sur commande simple ; les demandes de fichiers et le contexte documentaire passent au modèle sans envoi lexical ; une préparation supplantée conserve les entrées sans effet | `back/app/harness/tests/test_conversation_prompt.py`, `back/app/conversation/tests/test_service.py` |
| Préparation conversationnelle | Interrompre dispatcher/objectif sans consommer les entrées ni admettre une Task obsolète ; arrêter l'inférence possédée et conserver les ressources utiles de reprise | `back/app/conversation/tests/test_service.py`, `test_scheduler.py`, `test_task_objective.py`, `back/app/harness/tests/test_conversation_interrupt.py`, `back/tests/test_structured_inference.py` |
| `goal` | Suspendre/reprendre un objectif, respecter son calendrier, juger les cycles et conserver leur filiation | `test_goal_runner.py`, `test_goal_settings.py`, `test_referrer_wait.py`, `goals.spec.mjs`, `schedule.spec.mjs` |
| `messenger` | Admettre, dédupliquer, router et livrer dans la bonne conversation et connexion | `test_journal.py`, `test_ingest.py`, `test_interactions.py`, `test_mcp_routing.py`, `test_mcp_files.py` |
| `conversation` | Préserver contexte, admissions, résultats, notifications et résolution sans renvoi d’effets | `test_service.py`, `test_task_admission.py`, `test_delivery_resolution_http.py`, `e2e/specs/reliability.spec.mjs` |
| `chat` | Envoyer, archiver/restaurer, retrouver le streaming, isoler salons/utilisateurs et répondre aux choix sans LLM (boutons, reprise, expiration) | `test_authorization.py`, `test_events.py`, `test_native_facade.py`, `chat.spec.mjs`, `chat-interactions.spec.mjs`, `e2e/specs/chat.spec.mjs` |
| Chat et document | Ouvrir et modifier dans l’éditeur complet ; enregistrer avant l’envoi et transmettre l’URL au prompt seulement si le document est affiché ; conserver sélection et curseur après passage au champ de message, transmettre un extrait borné de la zone visible et invalider les repères obsolètes, en HTML, Source et Dataset ; préserver le brouillon en cas d’échec ; réserver le panneau intégré au desktop (≥ 1024 px), avec ses commandes dans la barre du titre du document ; ouvrir une modale sur mobile ; redimensionner les deux dispositions desktop à la souris, au toucher et au clavier sans perdre l’édition ; garantir au document en colonne au moins 560 px, avec passage automatique en disposition empilée si la place manque ; garder la colonne de droite visible sur desktop et conserver contenu et discussion après reconnexion | `front/browser-tests/chat-document-workspace.spec.mjs`, `back/app/conversation/tests/test_service.py`, `back/app/chat/tests/test_native_facade.py`, `back/app/memory/tests/test_document_library.py`, `back/app/memory/tests/test_document_grants.py` |
| `voice` | Démarrer/annuler un appel, traiter le tour dans le bon canal, fermer les médias | `test_session.py`, `test_multichannel_routing.py`, `test_realtime_engine.py`, `voice.spec.mjs` |
| `memory` | Rechercher, créer, partager et restaurer sans perte de contenu, de révision ni de droits | `test_document_library.py`, `test_document_grants.py`, `test_editorial_html.py`, `test_semantic_search.py`, `memory.spec.mjs` |
| Actions Dream à la demande | Déclenchement manuel indépendant du scheduler ; propriété et droits ; brouillons et éditions concurrentes préservés ; régénération des miniatures existantes des fichiers, pièces jointes et documents HTML ; ancien cache conservé après échec ; résultats en toasts, relance et réponses tardives sur mobile/bureau | `back/app/memory/tests/test_manual_dream.py`, `test_file_catalogue.py`, `test_document_thumbnails.py`, `front/browser-tests/memory.spec.mjs`, `e2e/specs/memory-graph.spec.mjs` |
| Recherche mémoire unifiée | Liste réunit souvenirs sans date filtrés par pertinence et correspondances temporelles indépendantes ; les souvenirs datés hors période ne passent pas par le rappel ordinaire ; pagination et tri après filtrage ; ouverture et oubli des résultats, repli lexical explicite | `test_browse_filters.py`, `test_semantic_search.py`, `front/browser-tests/memory.spec.mjs` |
| Temporalité mémoire | Dates partielles dans le fuseau global Galaris et changements d'heure ; nettoyage des anciens fuseaux sans perte de dates, d'historique ni d'acquisition ; correction, droits et portée contact ; contexte sans requête, pagination et budget ; recherche à date cible combinée aux filtres, parcours HTTP et refus d'accès ; filtre obligatoire dès la première recherche, saisie et affichage indépendants du fuseau du navigateur, reprise après erreur sur mobile/bureau | `back/app/memory/tests/test_temporal.py`, `back/app/memory/tests/test_browse_filters.py`, `front/browser-tests/memory.spec.mjs`, `e2e/specs/memory-temporal.spec.mjs` |
| Miniatures des documents | Réutiliser l’instantané d’impression et ses images pour le début de la première page ; conserver la révision miniaturisée ; renouveler le cache après modification ; revérifier les droits sans relire le contenu ni l’historique ; différer les aperçus hors écran, borner les chargements et annuler les travaux obsolètes sans empêcher l’ouverture du document | `back/app/memory/tests/test_document_thumbnails.py`, `front/browser-tests/document-thumbnails.spec.mjs`, `front/core/util/previewQueue.test.mjs`, `browser-executor/pdf.test.mjs` |
| Miniatures Office et tableurs | Convertir la première page des fichiers Office et la première page imprimée des tableurs ; éviter OCR et extraction analytique ; séparer les checkpoints de l’analyse complète ; préserver l’original, les droits et le cache partagé ; reprendre après échec et nettoyer les temporaires après annulation ; afficher et télécharger sur desktop et mobile, y compris après réouverture | `back/app/memory/tests/test_document_thumbnails.py`, `front/browser-tests/document-thumbnails.spec.mjs`, `e2e/specs/office-thumbnails.spec.mjs` |
| `contact` | Retrouver le bon interlocuteur sans exposer les contacts d’un autre périmètre | `test_service.py`, `test_router.py` |
| `topic` | Classer et retrouver les sujets, rechercher au-delà de la première page, ignorer les réponses obsolètes | `test_service.py`, `test_router.py`, `test_sequential_detection.py`, `topics.spec.mjs` |
| `dream` | Extraire/relier des connaissances sans réécrire le contenu existant, reprendre les traitements | `test_memory_extraction.py`, `test_claim_timeout.py`, `test_skill_learning.py` |
| `skill` | Créer/lire une procédure, préserver fichiers et permissions, appliquer les décisions d’apprentissage | `test_service.py`, `test_storage.py`, `test_learning.py`, `skills.spec.mjs` |
| `process` | Lancer, suivre, annuler et reprendre un traitement externe ; préserver ses états terminaux | `test_recovery.py`, `test_process_core.py`, `test_router_scope.py`, `test_worker_concurrency.py`, `execution.spec.mjs` |
| `tools` | Découvrir les outils autorisés, refuser les accès interdits, masquer les secrets ; révocation avant effet dans un serveur natif déjà monté, réactivation et isolation entre agents | `test_admin_access.py`, `test_agent_registry.py`, `test_secrets.py`, `test_resource_effects.py`, `test_live_authorization.py` |
| Recherche Web | Préserver requête, encodage, ordre et langue configurée ; distinguer recherche vide, partielle, dégradée et échec ; conserver les sources valides, masquer les exceptions brutes et annuler le transport sans bloquer la boucle | `back/app/tools/tests/test_search.py` (frontière HTTP remplacée, client et outil réels) |
| Paramètres d’indexation des Tools | Configurer `tools.fileindexing` par Tool et par connexion avec héritage, surcharge, valeur imposée et limites du provider ; reprendre les anciennes préférences sans les réappliquer ; respecter la valeur effective dans les recherches et le parcours automatique ; enregistrer depuis la Console embarquée et reprendre après erreur ; traduire les libellés internes dans les trois langues | `back/app/tools/tests/test_file_indexing.py`, `back/app/memory/tests/test_file_catalogue.py`, `front/browser-tests/tool-parameters.spec.mjs`, `e2e/specs/tool-parameters.spec.mjs` (desktop/mobile) |
| Administration ToolAdmin | Tester/créer un candidat sans fuite de secret dans le modèle ou les checkpoints ; connexion initialement inactive, héritage, atomicité, conflits, dépendances et interdiction d’auto-délégation ; révocation et rotation sur les anciens clients FastMCP/Pydantic AI ; Process massif reprenable, annulable et revalidé | `back/app/tools/tests/test_tool_admin.py`, `test_admin_network.py` ; `e2e/specs/tool-admin.spec.mjs` (application assemblée, clavier, fermeture et réouverture, desktop/mobile) |
| Disponibilité de la recherche | Un HTTP 200 sans sources ne valide pas le diagnostic ; une dégradation conserve les sources et produit un verdict distinct | `back/app/tools/tests/test_search.py` ; `make check-search` pour le corpus externe volontaire, avec relecture humaine de la pertinence |
| `document_show` (Conversation) | Exposer l'outil uniquement dans le chat interne autorisé, indépendamment de la connexion Memory et des anciens refus de fonctions du service système (ADR 0105) ; vérifier l'accès au document et les révocations ; ouvrir et rouvrir la visionneuse sans perdre les brouillons ni appliquer une demande à une autre conversation | `back/app/memory/tests/test_document_show.py`, `front/browser-tests/chat-document-workspace.spec.mjs` |
| `connection` | Activer/configurer une connexion et ses fonctions sans exposer ses secrets ou un autre agent | `test_connections.py`, `test_encryption.py`, `test_function_states.py` |
| `mcp` | Exposer les capacités et propager l’identité d’exécution dans les outils | `back/tests/test_realtime_security.py`, `back/app/tools/tests/test_mcp.py`, `back/core/authorize/tests/test_guard_provider.py` |
| `file_share` | Lire/copier/modifier via URI canonique, respecter ACL et limites, nettoyer les temporaires | `test_resource_service.py`, `test_transport.py`, `test_web_transport.py`, `test_galaris_provider.py` |
| Nextcloud fichiers | Préserver les noms réservés, parcourir au-delà de 500 entrées, rejeter les écritures concurrentes, conserver une source modifiée pendant un déplacement, refuser les suppressions de dossiers et les faux succès OCS | `back/bridge/nextcloud/tests/test_file_share.py` : vraie façade et vrai client, serveur HTTP synthétique |
| `console` | Exécuter dans le périmètre autorisé et transporter les fichiers sans traversée de chemin | `test_console.py`, `make tests-executor` |
| `browser` | Naviguer et restituer une ressource avec sessions, limites et erreurs explicites ; codes publics bornés, expiration sans rejeu automatique et nouvelle ouverture possible | `test_service.py`, `test_mcp.py`, `make tests-browser` |
| `llm` | Résoudre fournisseur/modèle, préserver paramètres fonctionnels, budgets et droits, conserver trace et coûts ; pause/reprise, relecture et protection contre les écritures tardives | `test_subscription_policy.py`, `test_structured_service.py`, `test_call_lineage.py`, `back/tests/test_provider_catalog.py`, `back/tests/test_provider_parameters.py`, `back/tests/test_inference_lifecycle.py`, `back/tests/test_protocol_inference.py`, `back/tests/test_structured_inference.py`, `back/tests/test_dispatcher_inference.py`, `execution.spec.mjs` |
| Consommation et crédits fournisseurs | Lire fenêtres, budgets et soldes avec les droits fournisseur, sans exposer les identifiants ; afficher les crédits supplémentaires ChatGPT à côté des fenêtres sans jauge de solde ; préserver unités, portée compte/clé, zéro et dépassement ; ne pas fabriquer de jauge sans plafond ; ne pas afficher de panneau de solde ou de consommation Fireworks ; actualiser et ignorer les réponses obsolètes ; masquer les clés enregistrées, conserver une clé omise et supprimer explicitement chaque clé après confirmation ; désactiver le fournisseur si la clé supprimée est obligatoire ; préserver les saisies après une erreur ; chiffrer, remplacer et supprimer la clé de gestion OpenRouter sans changer la clé d’inférence | `back/bridge/openai/tests/test_quota.py`, `back/app/llm/tests/test_provider_quotas.py`, `front/browser-tests/provider-quota.spec.mjs`, `front/browser-tests/provider-autosave.spec.mjs`, `e2e/specs/provider-usage.spec.mjs` |
| `audio` | Lire/transcrire un média canonique et livrer son résultat sans perte ni fuite de fichier | `test_audio_mcp.py`, `test_audio_service.py`, `test_summary_service.py` |
| `image` | Générer/lire des images et conserver ressources et traçabilité de l’appel | `test_image_mcp.py`, `test_image_service_trace.py` |
| Entrées multimodales natives | Fournir images, audio, vidéo et PDF au modèle compatible ; conserver provenance, droits, budget et médias à la reprise, sans outil d'analyse préalable | `app/harness/tests/test_native_media.py`, `test_media_resource_policy.py`, `tests/test_pydantic_ai_internal_model.py`, `app/messenger/tests/test_ingest.py` |
| `multimedia` | Suivre les générations longues, authentifier les callbacks et publier les médias | `test_multimedia.py`, `test_callback_security.py`, `test_providers.py` |
| `lab` | Isoler les jeux/items, conserver les paramètres, appliquer droits et deux passes ; reprendre les répétitions sans doublon, arrêter au budget et conserver les revues indépendantes avant révélation du juge ; générer des jeux synthétiques complets, propres à chaque contrat et à relire, sans écraser un jeu ni une saisie en cours ; afficher les aperçus sans HTML en conservant les entrées originales, les pourcentages par résultat et la moyenne indépendante du filtre, en excluant les notes absentes et en comptant les zéros | `test_authorization.py`, `test_contracts_and_passes.py`, `test_run_publication.py`, `test_stability_and_review.py`, `test_synthetic_datasets.py`, `lab.spec.mjs`, `lab-access.spec.mjs`, `lab-insights.spec.mjs`, `lab-synthetic.spec.mjs` |
| Comparaison Lab | Lire deux évaluations de chacun des dix Labs avec les droits du mécanisme ; préserver scores nuls et absents, incompatibilités et manquants ; bilan global indépendant de la page distinguant cas/répétitions, jugements absents et erreurs ; ambiguïtés sur les deux runs complets ; retrouver les régressions critiques et par critère hors page malgré un meilleur score global ; médianes appariées et effectifs ; navigation sans réponse périmée | `app/lab/tests/test_comparison.py`, `app/lab/tests/test_mcp.py`, `lab-comparison.spec.mjs` |
| Campagne Lab délai/coût/qualité | Importer les quatre parcours synthétiques FR/EN sans appel de modèle ni écrasement ; exécuter leurs outils simulés ; mesurer la première sortie texte/outil en poursuivant le flux jusqu'au résultat ; préserver coût, durée et mesure après rejugement | `app/lab/tests/test_reference_corpus.py`, `app/llm/tests/test_structured_service.py`, `app/lab/tests/test_contracts_and_passes.py` |
| Première sortie utile | Ignorer raisonnement, décisions internes et texte vide ; conserver les mesures initiales après reprise ; ne compter qu'une fois les appels simultanés ; preuve absente inconnue et portée agent conservée | `app/llm/tests/test_timing.py`, `app/task/tests/test_activity_snapshot.py`, `app/conversation/tests/test_monitoring_service.py`, `execution.spec.mjs` |
| Continuité documentaire ancienne | Retrouver l'URI après cinquante échanges sans document, avec titre/révision actuels et provenance ; exclure autre contact, document interdit, absent ou supprimé | `app/conversation/tests/test_context.py` |
| MCP Lab | Piloter les dix contrats avec le catalogue réel ; conserver les effets et reçus atomiques, les révisions, les autorisations courantes et la pagination ; publier une génération une seule fois, comparer les traitements et distinguer les avis d'agents ; attribuer et retirer le skill dédié | `app/lab/tests/test_mcp.py`, `app/skill/tests/test_storage.py`, `lab-insights.spec.mjs` |
| `incident` | Regrouper les échecs, diagnostiquer/résoudre selon les droits, conserver la preuve du correctif | `test_incident_service.py`, `test_router.py`, `test_retention.py`, `lab-access.spec.mjs`, `e2e/specs/incident.spec.mjs` |
| `dashboard` / frontend `index` | Montrer les indicateurs du périmètre autorisé avec des agrégations bornées ; réutiliser les mois consultés, actualiser et invalider le cache au changement de droits | `test_dashboard_service.py`, `dashboardStore.test.mjs`, `dashboard.spec.mjs`, `shell.spec.mjs`, `preferences.spec.mjs` |
| `onboarding` | Initialiser l’application sans écraser une configuration existante | `test_services.py` |
| `webhook` | Authentifier et identifier une livraison entrante sans admettre deux fois le même événement | `test_router.py`, `test_delivery_identity.py` |

### Sélection et création de sujets

`TopicSelect` centralise la recherche paginée et la sélection par identifiant de sujet.
Les formulaires activent `allow-create` : nouvelle conversation, paramètres de conversation,
message avec `@topic`, réaffectation depuis un badge, éditeur d’affectation des tâches et
conversations texte/voix, et cible de fusion. Le bouton `+` exige `TOPIC_EDIT` et
`AGENT_MANAGE_ALL`, conformément à l’API de création des sujets globaux. Un champ `readonly`
ou désactivé ne permet pas la création. Les filtres de tâches et d’historiques texte/voix
conservent `allow-create=false` tout en restant sélectionnables.

Le filtre Mémoire est distinct : ses valeurs sont des identifiants de fiches `MemoryItem`
projetées depuis les sujets et autorisées pour l’agent sélectionné. Il conserve son catalogue
Mémoire et ne propose aucune création ; lui substituer des identifiants de sujets casserait
le contrat du filtre. Les sujets du laboratoire sont des données de jeux d’évaluation.

Garanties : le sujet créé devient la sélection du formulaire sans perdre son brouillon ;
annulation, erreur, révocation des droits ou changement de contexte ne remplacent pas la
sélection par une réponse obsolète. La fusion exclut le sujet source et utilise la recherche
paginée commune. Preuves : `topics.spec.mjs`, `chat.spec.mjs`, `select-lifecycle.spec.mjs`
et `filter-loading.spec.mjs` dans `front/browser-tests/`.

## Infrastructure et interface commune

| Domaine | Garantie | Preuves |
|---|---|---|
| `core.user` | Connexion, MFA, renouvellement concurrent, révocation et dernier administrateur | `back/core/user/tests/test_user_flow.py`, `test_refresh_concurrency.py`, `test_admin_invariants.py`, `e2e/specs/session-races.spec.mjs` |
| Inscription publique | Premier compte administrateur unique même en concurrence ; inscriptions suivantes fermées par défaut et réglables sans octroyer de droits ; page fermée, erreurs réseau et réponses tardives | `back/core/user/tests/test_registration_policy.py`, `back/core/params/tests/test_runtime_preferences.py`, `front/browser-tests/registration.spec.mjs` |
| `core.authorize` | Les droits du router et des ressources refusent réellement les accès | `back/core/authorize/tests/test_route_security.py`, `test_resource_rules.py`, `test_assertions.py` |
| `core.params` | Conserver une personnalisation ou adopter explicitement un nouveau défaut ; retrouver tous les réglages après dépliage, préserver les brouillons et les droits dans les préférences sur ordinateur et mobile | `back/core/params/tests/test_services.py`, `test_dbadmin.py`, `front/browser-tests/preferences.spec.mjs`, `params-layout.spec.mjs` |
| `core.dbadmin` | Converger sans perte de données ; reprendre, respecter dépendances et contributions indépendantes ; contrôler les enums avant nettoyage, préserver défauts/propriétaires/droits, annuler le lot et reprendre après interruption ou expiration d'un verrou | `back/core/dbadmin/tests/test_postgresql_transitions.py`, `test_enum_safety.py`, `test_actions.py`, `test_registry.py`, `make tests-upgrade` |
| Civilités initiales | Peupler une base neuve une seule fois ; préserver ensuite renommages, genres, ajouts et suppressions, même de toutes les lignes | `back/app/agent/tests/test_dbadmin.py` |
| Civilités traduites | Traduire les clés initiales côté frontend, les conserver à l’enregistrement sans renommage et préserver les libellés personnalisés | `front/browser-tests/agents.spec.mjs` |
| DB / runtime | Sessions isolées, concurrence, timeout et arrêt sans abandon de ressources | `back/core/tests/test_database_context.py`, `test_runtime_timeouts.py`, `back/tests/test_durable_concurrency.py` |
| i18n / navigation / API | Catalogues cohérents, navigation selon les droits, réponses du bon compte et de la bonne requête | `make typecheck`, `front/core/api.test.mjs`, `front/browser-tests/lab-access.spec.mjs`, `e2e/specs/session-races.spec.mjs` |
| Contenu / aperçu / fichiers | Éditer, relire, imprimer sans altération ni exécution indue ; adapter automatiquement la largeur de page au conteneur, y compris en plein écran et en lecture seule, sans perdre le contenu ni le choix manuel ; libérer les pièces jointes | `back/core/util/tests/test_rich_text.py`, `back/core/preview/tests/test_conversion.py`, `front/browser-tests/rich-text.spec.mjs`, `document-print.spec.mjs`, `document-layout.spec.mjs`, `model3d.spec.mjs` |
| Raccourcis documentaires | Mettre en forme et annuler au clavier, imbriquer les listes avec Tab, conserver la navigation des tableaux et l’indentation du code ; préserver Source et lecture seule ; enregistrer puis rouvrir les titres | `front/browser-tests/document-shortcuts.spec.mjs`, `e2e/specs/editorial-html.spec.mjs` |
| PWA / livraison | Recharger une nouvelle version et qualifier les images, sauvegardes et restaurations | `e2e/specs/pwa.spec.mjs`, `back/tests/test_release_qualification.py`, `make tests-release`, `make tests-restore` |
| Outillage documentaire hors ligne | Générer les cartes FR/EN depuis le checkout courant sans accès aux secrets, aux volumes applicatifs ni au réseau ; refuser lectures interdites, écritures des sources et connexion depuis le code exécuté ; ne publier que les sorties attendues et préserver le checkout en cas d'échec | `bin/test-documentation.sh`, `bin/test-documentation-confinement.sh`, `make tests-documentation` |

## Bridges : tester l’adaptation une fois par protocole

Les suites propres aux bridges vivent dans `back/bridge/<module>/tests/`. Les règles de
messagerie et de processus restent testées dans leurs domaines canoniques : ne pas les copier
pour chaque provider. Les doubles réseau prouvent requêtes, conversions, refus et retries
locaux ; ils ne prouvent pas la réception sur un compte distant réel.

| Module(s) | Contrat d’adaptation | Preuves |
|---|---|---|
| `matrix` | Identités, envoi/réception et voix | `test_client.py`, `test_messenger.py`, `test_voice.py` |
| `nextcloud` | Talk, credentials, messages, appels et signalisation | `test_credentials.py`, `test_messenger.py`, `test_call_listener.py`, `test_signaling.py` |
| `one_bot` | Routage d’événement/API et connexion du hub | `test_hub.py`, `test_router_routing.py`, `test_messenger_routing.py` |
| `telegram` | Messages et reprise de livraison | `test_messenger.py`, `test_delivery_retry.py` |
| `whatsapp` | Authentification du bridge, API et livraison Messenger | `test_router.py`, `test_client.py`, `test_messenger_send.py` |
| `mail` | MIME, identités, connexion autorisée, messages, fichiers et validation privée Chat/journal (reprise, concurrence, refus) | `test_assertions.py`, `test_connection_resolution.py`, `test_mime.py`, `test_messenger.py`, `test_file_transport.py`, `test_chat_approvals.py` ; E2E `mail-approval.spec.mjs` |
| `calendar` | Dates/récurrences, limites et opérations autorisées | `test_ical.py`, `test_calculation_limits.py`, `test_service.py`, `test_mcp.py` |
| `n8n` | Traduire démarrage, callback et annulation vers Process | `test_n8n_bridge.py` |
| `harness` | Manager, diagnostic et cycle de vie du conteneur | `test_manager.py`, `test_diagnostics.py`, `make tests-harness-manager` |
| `hermes` | Exécution, annulation, historiques, secrets et rattachement de session | `test_executor_cancellation.py`, `test_executor_history.py`, `test_session_binding.py`, `back/tests/test_driver_conformance.py` |
| `claude_agent`, `codex`, `deepseek_harness` | Contrat du provider et adaptation du runtime | leurs `test_harness_provider.py`, `test_stream_trace.py` pour Claude/Codex, `test_runtime_adapter.py` pour DeepSeek |
| `openai` | Ressources, authentification et protocole temps réel | `test_resources.py`, `test_runtime_auth.py`, `test_realtime.py` |
| Autres providers conditionnels | Enregistrement, configuration, découverte et adaptation dans le catalogue partagé | `back/tests/test_provider_catalog.py`, `test_provider_bridges_register_profiles_and_service_facades`, suites `app.llm` et `app.multimedia` |
| `youtube` (support) | Restituer la transcription et ses erreurs | `test_transcript_service.py` |

Les autres providers déclarés sont `openrouter`, `mammouth`, `anthropic`, `deepseek`,
`fireworks`, `groq`, `mistral`, `models_dev`, `together`, `cerebras`, `google`, `xai`, `nvidia`,
`huggingface`, `cohere`, `perplexity`, `elevenlabs`, `sunoapi`, `byteplus`, `azure_speech`,
`ollama`. La suite partagée ne qualifie pas exhaustivement toutes leurs opérations. Ajouter
un cas spécifique lorsqu’une différence de protocole le justifie, pas une copie du workflow
canonique. Leurs modules frontend de configuration suivent les mêmes contrats de formulaire.

## Règle de maintenance

Une garantie a une preuve principale et, si nécessaire, une preuve d’assemblage E2E.
Une nouvelle fonction interne n’exige pas automatiquement un nouveau test. Une nouvelle
branche métier, un refus, une perte de donnée possible ou un effet rejouable exige une preuve.
Un changement volontaire indique l’avant/après ; une suppression de test indique ce qui est
repris et ce qui ne constitue plus une exigence. Mesurer les régressions échappées, l’instabilité,
la durée et les mutations pertinentes, pas un objectif de nombre de tests.

### Préférence personnelle d’ouverture des documents du chat

Le profil enregistre par utilisateur le choix écran splitté ou modale, avec écran splitté
par défaut pour les comptes nouveaux et existants. Le réglage n’est visible que lorsque
la messagerie interne est activée et accessible. Le clic principal sur une PJ document
respecte ce choix sur desktop ; sur mobile, ou sans accès à la coédition, il ouvre une modale.
Les icônes permettent toujours de choisir explicitement une autre ouverture disponible.
Un échec de sauvegarde conserve le choix précédent.

Garanties : `back/core/user/tests/test_user.py`,
`front/browser-tests/preferences.spec.mjs` et `front/browser-tests/chat-document-workspace.spec.mjs`.

Revue de dépendance : `app/chat` consomme uniquement les exports publics `useAuthStore`
et `DocumentOpenMode` de `core/user` pour lire et enregistrer la préférence. Cette dépendance
applicative vers l’infrastructure utilisateur n’ajoute ni import privé ni cycle.

### Classement personnel des documents

- `back/app/memory/tests/test_goal_folders.py` : classement automatique par utilisateur et Goal,
  respect des dossiers manuels et des droits courants, reprise globale par lots, homonymes,
  renommage, suppression/recréation, déclencheurs Goal/User/partage/provenance, concurrence avec
  les déplacements manuels, rollback et relance administrative protégée.
- `back/app/memory/tests/test_document_classification.py` : tags privés, classement en lecture
  seule sans mutation du document, arbre sans cycles, suppression récursive avec confirmation
  conditionnelle et retour des documents parmi les orphelins sans toucher au classement d'autrui,
  filtres avant pagination et retrait effectif des documents dont l'accès est révoqué ; déplacement
  atomique remplaçant les tags de l'utilisateur, ordre personnel persistant des frères mixtes et
  de la liste, rejet des ancrages périmés, palette SVG privée durable et validation des SVG.
  Les dossiers précèdent toujours les documents ; le tri alphabétique dans les deux sens est
  persistant, privé, insensible à la casse et aux accents, sans modifier les documents.
  Les icônes personnelles des documents survivent au classement et ne modifient pas le contenu ;
  la révocation d'accès interdit leur lecture et leur modification.
  Les notifications de classement ne concernent que leur propriétaire et identifient les dossiers
  touchés ; elles ne déclenchent pas l'invalidation globale réservée aux changements d'accès.
  `test_goal_folders.py` vérifie aussi les notifications ciblées du worker de classement,
  l'absence de notification lors d'une reprise sans changement et le renommage sans relire les documents.
  `test_document_structure.py` vérifie qu'une description de pièce jointe notifie seulement sa mémoire.
- `front/browser-tests/document-classification.spec.mjs` : déplacement par glisser-déposer,
  retour aux documents non classés par déplacement, création immédiate de dossiers et sous-dossiers suivie du renommage
  direct avec annulation, choix d'émojis
  Unicode, dossiers colorés, polices de pictogrammes et téléversement réutilisable, recherche
  française, filtres compacts, toggle des documents non classés activé par défaut et réinitialisable,
  branches chargées intégralement au dépliage et indépendantes de la recherche de liste,
  réordonnancement des dossiers et documents conservé à la réouverture,
  barre contextuelle au survol et au clavier, création d'un frère juste après le dossier,
  édition explicite remplaçant le double-clic, actions tactiles, tri A→Z/Z→A avec dossiers en premier,
  dépliage/repliage récursif limité à la branche et reprise après erreur de positionnement ou de tri,
  ouverture, repliage et réouverture des dossiers vides sans nouvelle requête,
  rafraîchissement limité aux dossiers concernés sans retirer les autres lignes pendant une réponse
  lente, renommage sans recharger les documents et effacement immédiat lors d'une révocation d'accès,
  réconciliation après reconnexion sans démonter les lignes, maintien du contenu en cas d'erreur
  de rafraîchissement et renouvellement du jeton sans perdre dossiers ouverts ni filtres,
  suppression vide immédiate ou confirmée avec annulation, réponses tardives et reprise après erreur.
  Le choix d'icône se propage entre arbre et liste, persiste à la réouverture et ignore les réponses
  périmées après sauvegarde ou changement de session ; l'icône par défaut et les erreurs restent utilisables.
  Dans l'arbre, l'icône d'un document ouvre le document sans sélecteur d'icône ; celle d'un dossier reste modifiable.
- `front/browser-tests/memory.spec.mjs` et `document-sharing.spec.mjs` : pagination à la demande,
  ouverture mobile, création et sauvegarde avec l'identité humaine.
- `e2e/specs/document-refresh.spec.mjs` : modification distante via l'API et les vrais événements
  websocket, requêtes limitées au dossier concerné et à la page visible, lignes conservées dans l'arbre et la liste.

### Défilement des modales

Le contenu long défile sans déplacer le titre ni masquer sa fermeture, sur ordinateur et
mobile. Les actions de pied restent accessibles et les formulaires conservent leurs
brouillons, leur validation et leur sauvegarde après défilement. Garanties :
`front/browser-tests/dialogs.spec.mjs`, `teams.spec.mjs`, `lab-comparison.spec.mjs` et
`lab-insights.spec.mjs`. Les parcours `skills.spec.mjs`, `galaris-links.spec.mjs` et
`chat-document-workspace.spec.mjs` couvrent les panneaux, éditeurs et dialogues imbriqués.

### Barre d’édition mobile

Les modales et leur arrière-plan couvrent la barre d’outils du document ouvert en écran
partagé, y compris après défilement lorsque la barre devient flottante. La fermeture et la
réouverture préservent le document ; la mise en forme reste utilisable dans la modale.
Garantie : `front/browser-tests/chat-document-workspace.spec.mjs`.

Après défilement, la barre d’outils conserve toute la largeur de l’éditeur pendant le
redimensionnement du panneau, sans nouveau défilement ni perte de contenu. Elle reste
bornée par le document, y compris après perte du focus. Garanties :
`front/browser-tests/editor-toolbar.spec.mjs` et `chat-document-workspace.spec.mjs`.

Sous 1024 px, l’éditeur partagé aligne les icônes à leur largeur naturelle, avec retour à la
ligne selon la place disponible, sans groupes visuels ni défilement. L’ordre suit les fonctions :
édition, mise en forme, voix, liens, fichiers et partage, selon les capacités du champ. Toutes
les actions sont directement accessibles sans menu de débordement. Le changement de largeur
conserve le contenu et la dictée en cours.

Le partage prépare le contenu actuel en PDF puis ouvre le partage natif sur une action
explicite. L’URL Galaris accompagne le partage lorsqu’elle est acceptée, sans être ajoutée au
PDF. En l’absence de partage de fichiers, le dialogue propose l’enregistrement du PDF.
L’annulation et le changement de document empêchent de proposer un PDF devenu obsolète.

Garanties : `mobile-editor-toolbar.spec.mjs`, `document-voice.spec.mjs`,
`rich-text.spec.mjs` et `document-print.spec.mjs` dans `front/browser-tests/`.

## Catalogue privé de fichiers et maintenance

L'indexation se pilote dans **Dream → Indexation**. **Suivi** s'ouvre par
défaut ; **Historique** conserve les filtres et le détail des opérations. Le parcours
assemblé `e2e/specs/file-indexing.spec.mjs` vérifie ces onglets, leur réouverture et
l'absence du panneau d'indexation dans Mémoire, sur ordinateur et mobile.

Revue de dépendance : le sélecteur d'agent de Dream utilise uniquement les exports publics
`AgentSelect` et `useAgentStore` de `app/agent`. Le lien `app/dream → app/agent` est nécessaire
pour choisir le propriétaire du catalogue ; il n'ajoute ni import privé ni cycle.

`back/app/memory/tests/test_memory_urls.py` vérifie l'unique table de rattachement
des URL, le SHA-256 des octets texte et binaires sur le nœud, la colonne nullable
d'URL principale, sa stabilité et les déplacements/suppressions. La transition
PostgreSQL couvre rollback, rejeu et retrait de l'ancienne colonne du catalogue.

`back/app/memory/tests/test_file_catalogue.py` vérifie les observations, la séparation des
agents et bindings, les champs personnels éditables, les tombes et réponses tardives,
la réparation durable sans rejouer les effets, la reprise de pages de plus de 500 entrées,
les budgets/annulations, l'enrichissement versionné, les modifications externes et le RBAC.
Elle vérifie les fiches initialement vides et le nettoyage idempotent des anciennes descriptions
JSON techniques, avec conservation des notes, contenus personnels et révisions historiques.
Elle vérifie aussi l'identité SHA-256 par agent, le regroupement entre stockage et Messenger,
les notes et titres personnels, le résumé partagé historisé, les changements de copie,
le déplacement avec rattachement au nouveau répertoire et le refus d'un aperçu après
révocation ou modification des octets. `memory.spec.mjs` exerce miniatures et plein écran
depuis le détail du graphe, erreurs/reprises et réponses tardives lors d'un changement d'agent.
`e2e/specs/file-indexing.spec.mjs` vérifie avec les API réelles les miniatures, aperçus,
téléchargements originaux et réouvertures sur desktop et mobile, avec un provider synthétique.
Elle exerce aussi le scheduler Dream réel : un répertoire par tour inactif, reçus et jauges,
absence d'appel LLM, checkpoint atomique et rejouable, reprise après conflit de révision,
reparcours hebdomadaire sans doublon, ajouts/retraits et minuit local avec changement d'heure.
`back/app/memory/tests/test_file_catalogue_scale.py` qualifie des catalogues synthétiques de
1 000, 10 000 et 100 000 entrées et compare les écritures avec/sans observation. Les résultats
sont des mesures locales avec provider synthétique, sans promesse de latence distante.
`front/browser-tests/file-indexing.spec.mjs` couvre le suivi, le lancement et l'annulation,
l'erreur/retry et le rejet de réponses tardives après changement d'agent sur desktop/mobile.
`front/browser-tests/memory.spec.mjs` compare les couleurs réellement rendues des fichiers et
répertoires à leur légende, après filtrage et changement de thème, sur desktop et mobile.
Elle vérifie également l'ouverture et le zoom de graphes synthétiques de 500 et 3 000 nœuds,
sans perte de nœuds lors de la pagination, puis leur dépliage complet sans nouvelle requête.
Le cas de volume inclut 3 000 nœuds non repliables et 6 000 liens. Une topologie mixte de
sujets, contacts transversaux, documents/items partagés et isolés vérifie le mouvement réel
des positions, la convergence naturelle, la proximité des communautés, les positions conservées
au zoom et au dépliage, le cadrage conservé et les niveaux de détail
au dézoom ; les captures desktop/mobile sont inspectées.
Les branches exclusives sont exercées sur desktop/mobile : compteur, zoom avec hystérésis,
commande clavier, ouverture d'un enfant, cadrage au dépliage et positions conservées à la fermeture
du détail par son bouton ou un clic dans le fond du graphe.
Le rendu réel vérifie le fondu intermédiaire des nouveaux symboles au zoom, puis leur
visibilité complète, ainsi que l'apparition immédiate avec réduction des animations.
La stabilité des coordonnées est vérifiée dans le mode de grande fenêtre de 3 000 items.
Les erreurs/reprises et une réponse retardée après changement d'agent sont couvertes.
`front/app/memory/graphBranches.test.mjs` couvre les règles d'exclusivité, doublons, cycles,
isolés, positions survivantes et placement selon les liens ; ce dernier scénario échoue avec
la grille qui ignorait les relations. Le test DB de pagination vérifie le voisin supplémentaire
hors page, confirmé ou suggéré, et les liens inaccessibles. `e2e/specs/memory-graph.spec.mjs`
exerce repli/dépliage, clavier, zoom, ouverture du contenu et retour au graphe dans l'application
assemblée, avec API réelle et base synthétique isolée. Les tests WebDAV vérifient que les lectures de
métadonnées suivent le nombre de dossiers pour 300 et 3 000 fichiers, avec repli individuel
et nouveaux contrôles après révocation. Le scénario fournisseur vérifie aussi la résolution
groupée des fichiers d'un Tool combinant File Share et Messenger.
`e2e/specs/file-indexing.spec.mjs` exerce l'application assemblée et son API réelle.
