<p align="right"><strong>Français</strong> · <a href="../../en/dev/functional-tests.md">English</a></p>

# Catalogue des garanties fonctionnelles

Ce catalogue part des usages et des responsabilités des modules. Les suites citées sont les
points d’entrée vérifiables ; une ligne ne signifie ni couverture exhaustive ni qualification
d’un service externe. Les résultats exécutés et les remplacements sont consignés dans
[la revue du 10 septembre](../../../project/audits/2026-09-10-functional-tests.md).

Pour une évolution, préciser la garantie changée et celles à préserver, lire leurs contrats
et tests, puis choisir la couche la moins coûteuse qui prouve l’effet. Conserver un test utile
est une décision à part entière : aucun quota de tests nouveaux par module.

## Parcours traversant plusieurs domaines

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
d'EXEC standard, EXEC high, BRIEFING et PLAN. `test_dispatcher_inference.py` prouve la persistance
d'une décision de Task à choix unique sans appel LLM ; `test_registry.py` protège la reprise des
anciennes décisions. Le Lab contrôle les mêmes couples via `test_contracts_and_passes.py`.

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
| Working Set Task | Conserver les ressources racine/enfants, checkpoints et première capsule lors de commits concurrents ; enregistrement idempotent et rollback avec l'appelant | `back/app/task/tests/test_working_set.py` (sessions PostgreSQL indépendantes) |
| Amendement conversationnel | Tolérer les seules révisions techniques avec une définition connue ; refuser avant interruption un checkpoint incompatible ou une exécution sans point de reprise vérifiable, même apparus après lecture ; préserver la cible et permettre une création indépendante explicite et idempotente dans le même document | `back/app/task/tests/test_amendment_service.py`, `back/app/conversation/tests/test_service.py`, `test_task_admission.py`, `back/app/agent/tests/test_checkpoint_contract.py`, `back/app/agent/tests/test_realtime.py` |
| Remplacement explicite | Enregistrer un seul successeur texte/voix, attendre le nettoyage ou une preuve d'arrêt valide, reprendre après changement de worker, préserver les autres pauses et tâches ; bloquer sur une relance, une coordination ou un changement de contexte du prédécesseur | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `back/app/agent/tests/test_driver_boundary.py` |
| Propriétaires et événements tardifs | Refuser le renouvellement d'un lease expiré ; ne pas remplacer le round affiché à partir d'un événement d'un autre round, demander une réconciliation serveur | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `front/app/chat/runtimeState.test.mjs` |
| Rattrapage Chat | Préserver la conversation courante face aux succès/refus HTTP tardifs ; conserver une réponse utile si une requête plus récente échoue ; réarmer les trous de stream pendant HTTP et après changement de sélection ; une révocation courante purge toujours le contenu | `front/browser-tests/chat-recovery.spec.mjs` (page et store réels, frontière HTTP remplacée) |
| Interruption et reconnexion Chat | Une correction supplante le round en cours ; les deux entrées et une seule réponse finale restent visibles après fin hors ligne puis rechargement, sur les trois moteurs de navigateur | `e2e/specs/chat.spec.mjs` (stack complète, contrôleur scripté à son port public) |
| Commandes conversationnelles | Conserver la demande entière lorsque l'arrêt nécessite une interprétation ; arrêter immédiatement une cible unique sur commande simple ; un renvoi de fichier supplanté conserve les entrées sans envoi ni erreur | `back/app/harness/tests/test_conversation_prompt.py`, `back/app/conversation/tests/test_service.py` |
| Préparation conversationnelle | Interrompre dispatcher/objectif sans consommer les entrées ni admettre une Task obsolète ; arrêter l'inférence possédée et conserver les ressources utiles de reprise | `back/app/conversation/tests/test_service.py`, `test_scheduler.py`, `test_task_objective.py`, `back/app/harness/tests/test_conversation_interrupt.py`, `back/tests/test_structured_inference.py` |
| `goal` | Suspendre/reprendre un objectif, respecter son calendrier, juger les cycles et conserver leur filiation | `test_goal_runner.py`, `test_goal_settings.py`, `test_referrer_wait.py`, `goals.spec.mjs`, `schedule.spec.mjs` |
| `messenger` | Admettre, dédupliquer, router et livrer dans la bonne conversation et connexion | `test_journal.py`, `test_ingest.py`, `test_interactions.py`, `test_mcp_routing.py`, `test_mcp_files.py` |
| `conversation` | Préserver contexte, admissions, résultats, notifications et résolution sans renvoi d’effets | `test_service.py`, `test_task_admission.py`, `test_delivery_resolution_http.py`, `e2e/specs/reliability.spec.mjs` |
| `chat` | Envoyer, archiver/restaurer, retrouver le streaming, isoler salons/utilisateurs et répondre aux choix sans LLM (boutons, reprise, expiration) | `test_authorization.py`, `test_events.py`, `test_native_facade.py`, `chat.spec.mjs`, `chat-interactions.spec.mjs`, `e2e/specs/chat.spec.mjs` |
| Chat et document | Ouvrir et modifier dans l’éditeur complet ; enregistrer avant l’envoi et transmettre l’URL au prompt seulement si le document est affiché ; préserver le brouillon en cas d’échec ; réserver le panneau intégré au desktop (≥ 1024 px), avec ses commandes dans la barre du titre du document ; ouvrir une modale sur mobile ; redimensionner les deux dispositions desktop à la souris, au toucher et au clavier sans perdre l’édition ; garantir au document en colonne au moins 560 px, avec passage automatique en disposition empilée si la place manque ; garder la colonne de droite visible sur desktop et conserver contenu et discussion après reconnexion | `front/browser-tests/chat-document-workspace.spec.mjs`, `back/app/conversation/tests/test_service.py`, `back/app/chat/tests/test_native_facade.py`, `back/app/memory/tests/test_document_library.py`, `back/app/memory/tests/test_document_grants.py` |
| `voice` | Démarrer/annuler un appel, traiter le tour dans le bon canal, fermer les médias | `test_session.py`, `test_multichannel_routing.py`, `test_realtime_engine.py`, `voice.spec.mjs` |
| `memory` | Rechercher, créer, partager et restaurer sans perte de contenu, de révision ni de droits | `test_document_library.py`, `test_document_grants.py`, `test_editorial_html.py`, `test_semantic_search.py`, `memory.spec.mjs` |
| Miniatures des documents | Réutiliser l’instantané d’impression et ses images pour le début de la première page ; conserver la révision miniaturisée ; renouveler le cache après modification ; revérifier les droits ; charger à la visibilité et ignorer les réponses obsolètes sans empêcher l’ouverture du document | `back/app/memory/tests/test_document_thumbnails.py`, `front/browser-tests/document-thumbnails.spec.mjs`, `browser-executor/pdf.test.mjs` |
| `contact` | Retrouver le bon interlocuteur sans exposer les contacts d’un autre périmètre | `test_service.py`, `test_router.py` |
| `topic` | Classer et retrouver les sujets, rechercher au-delà de la première page, ignorer les réponses obsolètes | `test_service.py`, `test_router.py`, `test_sequential_detection.py`, `topics.spec.mjs` |
| `dream` | Extraire/relier des connaissances sans réécrire le contenu existant, reprendre les traitements | `test_memory_extraction.py`, `test_claim_timeout.py`, `test_skill_learning.py` |
| `skill` | Créer/lire une procédure, préserver fichiers et permissions, appliquer les décisions d’apprentissage | `test_service.py`, `test_storage.py`, `test_learning.py`, `skills.spec.mjs` |
| `process` | Lancer, suivre, annuler et reprendre un traitement externe ; préserver ses états terminaux | `test_recovery.py`, `test_process_core.py`, `test_router_scope.py`, `test_worker_concurrency.py`, `execution.spec.mjs` |
| `tools` | Découvrir les outils autorisés, refuser les accès interdits, masquer les secrets ; révocation avant effet dans un serveur natif déjà monté, réactivation et isolation entre agents | `test_admin_access.py`, `test_agent_registry.py`, `test_secrets.py`, `test_resource_effects.py`, `test_live_authorization.py` |
| Recherche Web | Préserver requête, encodage, ordre et langue configurée ; distinguer recherche vide, partielle, dégradée et échec ; conserver les sources valides, masquer les exceptions brutes et annuler le transport sans bloquer la boucle | `back/app/tools/tests/test_search.py` (frontière HTTP remplacée, client et outil réels) |
| Disponibilité de la recherche | Un HTTP 200 sans sources ne valide pas le diagnostic ; une dégradation conserve les sources et produit un verdict distinct | `back/app/tools/tests/test_search.py` ; `make check-search` pour le corpus externe volontaire, avec relecture humaine de la pertinence |
| `document_show` (Conversation) | Exposer l'outil uniquement dans le chat interne autorisé, indépendamment de la connexion Memory et des anciens refus de fonctions du service système (ADR 0105) ; vérifier l'accès au document et les révocations ; ouvrir et rouvrir la visionneuse sans perdre les brouillons ni appliquer une demande à une autre conversation | `back/app/memory/tests/test_document_show.py`, `front/browser-tests/chat-document-workspace.spec.mjs` |
| `connection` | Activer/configurer une connexion et ses fonctions sans exposer ses secrets ou un autre agent | `test_connections.py`, `test_encryption.py`, `test_function_states.py` |
| `mcp` | Exposer les capacités et propager l’identité d’exécution dans les outils | `back/tests/test_realtime_security.py`, `back/app/tools/tests/test_mcp.py`, `back/core/authorize/tests/test_guard_provider.py` |
| `file_share` | Lire/copier/modifier via URI canonique, respecter ACL et limites, nettoyer les temporaires | `test_resource_service.py`, `test_transport.py`, `test_web_transport.py`, `test_galaris_provider.py` |
| `console` | Exécuter dans le périmètre autorisé et transporter les fichiers sans traversée de chemin | `test_console.py`, `make tests-executor` |
| `browser` | Naviguer et restituer une ressource avec sessions, limites et erreurs explicites ; codes publics bornés, expiration sans rejeu automatique et nouvelle ouverture possible | `test_service.py`, `test_mcp.py`, `make tests-browser` |
| `llm` | Résoudre fournisseur/modèle, préserver paramètres fonctionnels, budgets et droits, conserver trace et coûts ; pause/reprise, relecture et protection contre les écritures tardives | `test_subscription_policy.py`, `test_structured_service.py`, `test_call_lineage.py`, `back/tests/test_provider_catalog.py`, `back/tests/test_provider_parameters.py`, `back/tests/test_inference_lifecycle.py`, `back/tests/test_protocol_inference.py`, `back/tests/test_structured_inference.py`, `back/tests/test_dispatcher_inference.py`, `back/tests/test_briefing_inference.py`, `execution.spec.mjs` |
| Quotas ChatGPT | Lire les fenêtres du compte avec les droits fournisseur, sans exposer les identifiants ; distinguer absence, zéro et erreur ; actualiser et ignorer une réponse devenue obsolète après changement de compte | `back/bridge/openai/tests/test_quota.py`, `front/browser-tests/provider-quota.spec.mjs` |
| `audio` | Lire/transcrire un média canonique et livrer son résultat sans perte ni fuite de fichier | `test_audio_mcp.py`, `test_audio_service.py`, `test_summary_service.py` |
| `image` | Générer/lire des images et conserver ressources et traçabilité de l’appel | `test_image_mcp.py`, `test_image_service_trace.py` |
| Entrées multimodales natives | Fournir images, audio, vidéo et PDF au modèle compatible ; conserver provenance, droits, budget et médias à la reprise, sans outil d'analyse préalable | `app/harness/tests/test_native_media.py`, `test_media_resource_policy.py`, `tests/test_pydantic_ai_internal_model.py`, `app/messenger/tests/test_ingest.py` |
| `multimedia` | Suivre les générations longues, authentifier les callbacks et publier les médias | `test_multimedia.py`, `test_callback_security.py`, `test_providers.py` |
| `lab` | Isoler les jeux/items, conserver les paramètres, appliquer droits et deux passes ; reprendre les répétitions sans doublon, arrêter au budget et conserver les revues indépendantes avant révélation du juge ; générer des jeux synthétiques complets, propres à chaque contrat et à relire, sans écraser un jeu ni une saisie en cours ; afficher les aperçus sans HTML en conservant les entrées originales, les pourcentages par résultat et la moyenne indépendante du filtre, en excluant les notes absentes et en comptant les zéros | `test_authorization.py`, `test_contracts_and_passes.py`, `test_run_publication.py`, `test_stability_and_review.py`, `test_synthetic_datasets.py`, `lab.spec.mjs`, `lab-access.spec.mjs`, `lab-insights.spec.mjs`, `lab-synthetic.spec.mjs` |
| MCP Lab | Piloter les onze contrats avec le catalogue réel ; conserver les effets et reçus atomiques, les révisions, les autorisations courantes et la pagination ; publier une génération une seule fois, comparer les traitements et distinguer les avis d'agents ; attribuer et retirer le skill dédié | `app/lab/tests/test_mcp.py`, `app/skill/tests/test_storage.py`, `lab-insights.spec.mjs` |
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
| `core.dbadmin` | Converger sans perte de données ; reprendre, respecter dépendances et contributions indépendantes | `back/core/dbadmin/tests/test_postgresql_transitions.py`, `test_actions.py`, `test_registry.py`, `make tests-upgrade` |
| Civilités initiales | Peupler une base neuve une seule fois ; préserver ensuite renommages, genres, ajouts et suppressions, même de toutes les lignes | `back/app/agent/tests/test_dbadmin.py` |
| Civilités traduites | Traduire les clés initiales côté frontend, les conserver à l’enregistrement sans renommage et préserver les libellés personnalisés | `front/browser-tests/agents.spec.mjs` |
| DB / runtime | Sessions isolées, concurrence, timeout et arrêt sans abandon de ressources | `back/core/tests/test_database_context.py`, `test_runtime_timeouts.py`, `back/tests/test_durable_concurrency.py` |
| i18n / navigation / API | Catalogues cohérents, navigation selon les droits, réponses du bon compte et de la bonne requête | `make typecheck`, `front/core/api.test.mjs`, `front/browser-tests/lab-access.spec.mjs`, `e2e/specs/session-races.spec.mjs` |
| Contenu / aperçu / fichiers | Éditer, relire, imprimer sans altération ni exécution indue ; adapter automatiquement la largeur de page au conteneur, y compris en plein écran et en lecture seule, sans perdre le contenu ni le choix manuel ; libérer les pièces jointes | `back/core/util/tests/test_rich_text.py`, `back/core/preview/tests/test_conversion.py`, `front/browser-tests/rich-text.spec.mjs`, `document-print.spec.mjs`, `document-layout.spec.mjs`, `model3d.spec.mjs` |
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
| `mail` | MIME, identités, connexion autorisée, messages et fichiers | `test_assertions.py`, `test_connection_resolution.py`, `test_mime.py`, `test_messenger.py`, `test_file_transport.py` |
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
  suppression vide immédiate ou confirmée avec annulation, réponses tardives et reprise après erreur.
  Le choix d'icône se propage entre arbre et liste, persiste à la réouverture et ignore les réponses
  périmées après sauvegarde ou changement de session ; l'icône par défaut et les erreurs restent utilisables.
  Dans l'arbre, l'icône d'un document ouvre le document sans sélecteur d'icône ; celle d'un dossier reste modifiable.
- `front/browser-tests/memory.spec.mjs` et `document-sharing.spec.mjs` : pagination à la demande,
  ouverture mobile, création et sauvegarde avec l'identité humaine.

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
