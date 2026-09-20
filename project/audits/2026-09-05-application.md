# Audit fonctionnel et technique — 5 septembre 2026

Liste destinée aux corrections futures. Aucun correctif applicatif n’a été réalisé dans cet audit.

Les corrections demandées ensuite sont suivies dans
[le bilan des 20 corrections](2026-09-05-corrections.md). Les constats ci-dessous conservent
l'état initial observé et ne décrivent donc pas nécessairement le code corrigé.

## Périmètre et limites

Point de départ : commit `7ecad86a`, worktree initialement propre. Des modifications concurrentes
sont apparues pendant l’analyse, notamment dans l’authentification, les WebSockets, les événements
LLM et les tâches. Elles ont été préservées. Les résultats des commandes ci-dessous sont donc des
observations datées de cette session, pas une certification du worktree après ces modifications.

L’inventaire porte sur les **65 modules backend et 33 modules frontend déclarés**. La revue a
croisé les déclarations, contrats, modèles, services, endpoints, principaux écrans et tests.
La profondeur varie selon les domaines ; il ne s’agit pas d’une lecture exhaustive de chaque
fonction ni d’un test manuel de chaque écran. Les intégrations externes ont été examinées dans le
code et avec leurs tests, sans envoyer de messages ni effectuer d’appels réels aux fournisseurs.
Les parcours navigateur E2E et la charge réelle restent à valider.

Les 20 points ci-dessous comprennent des défauts de logique, de robustesse ou de validation,
ainsi que **deux arbitrages produit explicitement identifiés**, AUD-13 et AUD-16.
Un scénario déduit du code est distingué d’une reproduction exécutée.
Lors de la relecture finale, les éditions concurrentes avaient déjà ajouté la documentation
manquante d’AUD-18 et modifié plusieurs tests/fixtures d’AUD-20. Ces deux points conservent leur
observation initiale avec leur statut de suivi ; ils ne doivent pas être traités comme des constats
inchangés du dernier worktree.

- **P1** : risque de perte d’événements, résultat métier faux ou workflow bloqué ; traiter en premier.
- **P2** : fonctionnement dégradé, limitation cachée ou contrôle de qualité défaillant.
- **P3** : incohérence limitée ou documentation opérationnelle à compléter.

## Liste des points à traiter

### AUD-01 — P1 — Topics : des titres chinois sans rapport sont considérés comme identiques

**Constat.** La normalisation conserve uniquement `[a-z0-9]`. Deux titres entièrement chinois
deviennent donc deux chaînes vides. `SequenceMatcher` leur attribue une similarité de `1.0` ;
`prefer_reuse()` peut alors remplacer une proposition de nouveau sujet par un sujet existant
sans rapport, avec une confiance maximale. D’autres écritures non latines sont concernées.

**Preuve exécutée.** Les fonctions extraites du code donnent un score de `1.0` pour
`旅行计划` et `数据库备份`, avec des mots-clés eux aussi différents.

**Correction envisagée.** Normalisation Unicode ; ne jamais déclarer équivalents deux résultats
de normalisation vides. Ajouter des cas chinois et d’autres écritures aux tests de réutilisation.

Sources : [normalisation et score](../../back/app/topic/service.py#L78),
[réutilisation automatique](../../back/app/topic/service.py#L644).

### AUD-02 — P1 — Calendriers : une panne peut être interprétée comme une disponibilité

**Constat.** Lorsque la lecture distante échoue sans cache exploitable, `events_for_agent()`
ignore le calendrier. `availability_for_agent()` interprète ensuite l’absence d’événements comme
`available=True`. La recherche de créneaux utilise également ce résultat incomplet. Avec un cache,
aucune fraîcheur maximale n’est imposée dans ce chemin.

**Preuve exécutée.** Avec un calendrier configuré, une erreur distante simulée et aucun cache,
la fonction renvoie effectivement `available=True`.

**Correction envisagée.** Propager un état « disponibilité inconnue/incomplète », la liste des
sources en erreur et l’âge du cache ; ne pas annoncer un créneau certain avec des données manquantes.

Sources : [lecture et disponibilité](../../back/bridge/calendar/service.py#L319),
[créneaux libres](../../back/bridge/calendar/service.py#L407).

### AUD-03 — P2 — Calendriers : le plafond de 500 événements fausse les conflits

**Constat.** Les calculs de disponibilité et de créneaux demandent une liste plafonnée à 500,
puis filtrent les événements bloquants. Un rendez-vous après ce plafond disparaît du calcul.
Le plafond est adapté à une réponse paginée, mais pas à la détermination d’une disponibilité.

**Preuve exécutée.** 500 événements transparents suivis d’un événement occupé dans la même plage
produisent `available=True`. Une recherche couvrant beaucoup d’événements peut également proposer
des créneaux déjà occupés en fin de période.

**Correction envisagée.** Calculer sur l’ensemble des intervalles bloquants, ou refuser de conclure
si le résultat a été tronqué. Séparer limite d’affichage et calcul métier.

Sources : [troncature](../../back/bridge/calendar/service.py#L356),
[calculs](../../back/bridge/calendar/service.py#L368).

### AUD-04 — P1 — Calendriers : les déclencheurs peuvent être définitivement perdus

**Constat.** `sync_feed()` enregistre `last_checked_at` avant d’avoir durablement créé tous les
déclencheurs. `_claim()` enregistre ensuite un déclencheur `pending` avant son dispatch et refuse
toute empreinte déjà présente. `_dispatch()` peut enfin le marquer `error`. Aucun chemin de reprise
des déclencheurs `pending/error` n’est présent dans la boucle de synchronisation examinée.

**Scénarios déduits du code.** Arrêt après l’avancement du curseur : des occurrences ne sont
jamais créées. Arrêt après `_claim()` : déclencheur coincé. Erreur transitoire de dispatch :
occurrence consommée et non rejouée. L’idempotence actuelle empêche les doublons, mais aussi la reprise.

**Correction envisagée.** Enregistrer les occurrences et l’avancement du curseur dans une même
transaction, puis les traiter avec une file durable, lease et reprise idempotente. Tester chaque
frontière d’interruption, y compris après création de la tâche et avant finalisation du déclencheur.

Sources : [claim](../../back/bridge/calendar/service.py#L534),
[dispatch](../../back/bridge/calendar/service.py#L576),
[synchronisation](../../back/bridge/calendar/service.py#L630).

### AUD-05 — P1 — Telegram : les albums sont acquittés avant leur persistance

**Constat.** `_settle_album_updates()` appelle `get_updates(offset=max(seen)+1)` pour collecter
les morceaux suivants d’un album. Cette étape précède `_process_batch()` et le dispatch durable.
Or Telegram considère les événements précédents comme confirmés dès cet appel avec un offset supérieur.

**Scénario déduit du code et du protocole.** Si le backend s’arrête ou si le dispatch échoue
après la collecte, Telegram a déjà oublié les premiers événements. Revenir au curseur local précédent
ne les récupère pas. Des messages ordinaires présents dans le même lot peuvent également être touchés.

**Correction envisagée.** Journaliser durablement chaque update avant tout appel qui l’acquitte,
puis assembler les albums depuis ce journal. Tester interruption et erreur durant l’assemblage.

Sources : [collecte des albums](../../back/bridge/telegram/messenger.py#L509),
[ordre du traitement](../../back/bridge/telegram/messenger.py#L531),
[contrat officiel Telegram, getUpdates](https://core.telegram.org/bots/api#getupdates).

### AUD-06 — P1 — Processus : certaines fins ne réveillent pas la tâche appelante

**Constat.** `_record_refresh_failure()` peut terminer un run en `error`, et `cancel_run()` en
`cancelled`, sans appeler `_resolve_await_if_terminal()`. Les chemins callback, refresh réussi et
épuisement des tentatives de démarrage le font pourtant.

**Scénario déduit du code.** Une tâche attend un processus ; le processus est annulé ou dépasse
son seuil d’échecs de refresh. Le run est terminé, mais son enfant d’attente reste suspendu jusqu’à
un autre mécanisme de résolution, notamment son expiration. Le parent ne reçoit pas immédiatement
le résultat réel.

**Correction envisagée.** Faire converger toutes les transitions terminales vers la même
finalisation idempotente. Tester annulation en file, annulation distante et échec du refresh avec
une véritable tâche d’attente liée.

Sources : [échecs du refresh](../../back/app/process/process_service.py#L1183),
[annulations](../../back/app/process/process_service.py#L1306),
[résolution attendue](../../back/app/task/collab.py#L225).

### AUD-07 — P1 — Processus : un callback rejoué ne répare pas une finalisation interrompue

**Constat.** `receive_callback()` committe l’événement et l’état terminal, puis résout la tâche
d’attente. Si cette résolution échoue ou si le backend s’arrête entre les deux, le prochain callback
portant le même `event_id` retourne immédiatement comme doublon. Il ne reprend pas la résolution.
Un refresh d’un run déjà terminal retourne lui aussi immédiatement.

**Scénario déduit du code.** Le transport externe réessaie correctement son callback, mais la tâche
appelante reste en attente malgré un processus terminé avec succès. La déduplication du callback
ne garantit donc pas la réalisation de tous ses effets internes.

**Correction envisagée.** Rendre la notification du terminal durable et réconciliable ; au minimum,
rejouer sans danger la résolution d’attente lors d’une redelivery déjà enregistrée.

Source : [callback et retour anticipé sur doublon](../../back/app/process/process_service.py#L1248).

### AUD-08 — P2 — Processus : les annulations en cours sortent du polling automatique

**Constat.** `refresh_active_runs()` ne sélectionne que `running`, `waiting` et `unknown`.
`cancel_run()` committe pourtant `cancelling` avant l’appel distant.

**Scénario déduit du code.** Une erreur réseau pendant l’annulation ou une confirmation distante
différée laisse le run en `cancelling`. Sans callback, il ne sera plus rafraîchi automatiquement.

**Correction envisagée.** Inclure les annulations en cours dans la réconciliation ; borner l’appel
d’annulation et prévoir le traitement des états intermédiaires retournés par l’engine.

Sources : [polling](../../back/app/process/process_service.py#L1150),
[demande d’annulation](../../back/app/process/process_service.py#L1330).

### AUD-09 — P2 — OneBot : la fermeture de l’ancienne connexion supprime la nouvelle

**Constat.** `register()` remplace le socket associé à `platform:user_id`. Le `finally` de
l’ancienne connexion appelle ensuite `unregister()` avec cette seule clé, sans vérifier l’identité
du socket enregistré.

**Preuve exécutée.** Enregistrer deux sockets successifs pour la même identité, puis nettoyer
l’ancien, retire le nouveau du hub.

**Correction envisagée.** Passer le socket ou une génération à `unregister()` et ne supprimer que
la connexion correspondante. Tester les reconnexions qui se chevauchent.

Sources : [hub](../../back/bridge/one_bot/client.py#L337),
[nettoyage de connexion](../../back/bridge/one_bot/router.py#L204).

### AUD-10 — P2 — OneBot : fuite des réponses en attente si l’envoi échoue

**Constat.** `call()` ajoute la future à `pending_responses`, puis exécute `send_text()` avant
d’entrer dans le `try/finally` qui nettoie cette future.

**Scénario déduit du code.** Le socket échoue au moment de l’envoi, ou l’appel est annulé à cet
instant. L’entrée reste dans le dictionnaire sans délai de nettoyage. Des déconnexions répétées
accumulent ces entrées.

**Correction envisagée.** Placer l’envoi dans le bloc protégé ; nettoyer et annuler les futures
sur toutes les sorties, y compris lors de la fermeture du socket.

Source : [envoi et nettoyage](../../back/bridge/one_bot/client.py#L373).

### AUD-11 — P2 — WhatsApp : la limite de taille est appliquée après lecture intégrale

**Constat.** Sans `Content-Length` fiable, `_receive_webhook()` appelle `request.body()` puis
compare la taille à la limite configurée. Le corps a déjà été intégralement alloué en mémoire.
Cette lecture précède aussi la validation de signature.

**Impact déduit du code.** Le seuil propre au webhook ne borne pas la mémoire consommée par
une requête. Les éventuelles limites du proxy restent une protection distincte.

**Correction envisagée.** Lire le flux par blocs avec arrêt dès dépassement, comme le fait déjà
le webhook générique. Couvrir les corps sans en-tête de longueur.

Sources : [réception WhatsApp](../../back/bridge/whatsapp/router.py#L201),
[lecteur borné existant](../../back/app/webhook/router.py#L21).

### AUD-12 — P2 — Webhook générique : certains JSON valides et corps non UTF-8 provoquent une erreur non gérée

**Constat.** Le résultat de `json.loads()` est annoté `dict` sans contrôle à l’exécution. `[]`,
`null`, `42` ou une chaîne atteignent `data.get()` et lèvent `AttributeError`. Le décodage UTF-8
est également effectué hors du traitement des erreurs prévu.

**Preuve exécutée.** Les quatre types JSON non objets provoquent `AttributeError` dans le
service réel extrait du code. Le handler ne traduit pas cette exception en erreur client.

**Correction envisagée.** Valider le type de payload et l’encodage à la frontière HTTP, rendre
un 400/422 explicite, conserver le comportement de texte brut seulement pour les entrées prévues.

Sources : [lecture du payload](../../back/app/webhook/router.py#L107),
[premier accès à data](../../back/app/webhook/functions.py#L24).

### AUD-13 — P2 — Dashboard/LLM : arbitrer le sens du « coût facturé » historique

**Comportement volontaire, pas régression avérée.** Le dashboard utilise le statut d’abonnement
**courant** du modèle pour recalculer les coûts de mois passés. Les traces LLM possèdent pourtant
leur propre `cost` et `is_subscription` figés. Le comportement est explicitement documenté et testé.

**Incohérence produit possible.** Changer aujourd’hui le mode de facturation d’un modèle change
le « coût facturé » affiché pour un mois déjà terminé, sans modifier les traces. Deux écrans
peuvent donc donner des montants différents pour les mêmes appels.

**Arbitrage proposé.** Distinguer « coût historique enregistré » et « estimation avec la configuration
actuelle », ou confirmer que le second est bien l’indicateur voulu et le nommer clairement.
Ne pas modifier ce comportement comme un simple bug sans revoir son contrat.

Sources : [agrégats](../../back/app/dashboard/dashboard_service.py#L54),
[test du changement rétroactif](../../back/app/dashboard/tests/test_dashboard_service.py#L190),
[contrat documenté](../../docs/fr/architecture/flows/agent-execution.md#L666).

### AUD-14 — P2 — Utilisateurs : la suppression d’un propriétaire d’agent échoue sans explication métier

**Constat.** `agents.user_id` est une FK `ON DELETE RESTRICT`. `user_service.delete()` effectue
un DELETE direct sans contrôle des agents possédés, et les routes de suppression ne traduisent
pas cette violation d’intégrité.

**Scénario déduit du code.** Supprimer un utilisateur ayant un agent, éventuellement supprimé
logiquement, produit une erreur de base non transformée en conflit métier. L’interface ne propose
pas de résoudre la dépendance avant de supprimer le compte.

**Correction envisagée.** Renvoyer un 409 expliquant les dépendances, puis proposer la réaffectation
des agents. Conserver la protection référentielle.

Sources : [FK propriétaire](../../back/app/agent/models.py#L40),
[suppression](../../back/core/user/user_service.py#L401),
[API](../../back/core/user/router.py).

### AUD-15 — P2 — Frontend : plusieurs listes et sélecteurs ne dépassent jamais 500 éléments

**Constat.** `authService.getUsers()` et `agentService.getAgents()` chargent une seule page de
500 lignes. L’écran Utilisateurs applique ensuite pagination et recherche localement. `TopicSelect`
charge lui aussi uniquement les 500 premiers sujets et filtre ce sous-ensemble dans le navigateur.
Charger le sujet déjà sélectionné par son ID ne permet pas de chercher un autre sujet hors de la page.

**Scénario déduit du code.** Au-delà de 500 comptes/agents/sujets, des objets existants deviennent
inaccessibles dans ces listes ou sélecteurs, sans indication de troncature. Le choix « 500 par page »
ne signifie pas « maximum de 500 objets dans l’application ».

**Correction envisagée.** Pagination serveur avec total et recherche serveur ; pour les sélecteurs,
chargement à la demande et conservation séparée de la sélection courante.

Sources : [service utilisateurs](../../front/core/user/services/authService.ts#L192),
[table et filtre](../../front/core/user/pages/users.vue#L9),
[service agents](../../front/app/agent/services/agentService.ts#L140),
[sélecteur de sujets](../../front/app/topic/components/TopicSelect.vue#L88).

### AUD-16 — P2 — Administration : décider d’un garde-fou pour le dernier administrateur actif

**Arbitrage produit.** Le service de mise à jour accepte `is_active=False` sans vérifier qu’un
autre administrateur actif subsiste. Le bootstrap public reste fermé tant qu’un compte existe,
même désactivé. L’administrateur peut donc rendre l’administration inaccessible par une opération
autorisée, sans solution de récupération offerte par ce parcours.

**Proposition.** Interdire la désactivation/retrait du dernier administrateur actif, ou prévoir
une procédure de récupération explicite. Le même invariant devrait couvrir les affectations de rôle.

Sources : [désactivation](../../back/core/user/user_service.py#L271),
[fermeture du bootstrap](../../back/core/user/user_service.py#L189),
[formulaire d’administration](../../front/core/user/components/UserAdminForm.vue#L46).

### AUD-17 — P3 — Utilisateurs : la langue fournie à la création administrative est ignorée

**Constat.** `UserCreate` hérite du champ `language`, mais `user_service.create()` ne le transmet
pas au modèle. Le bootstrap initial et la mise à jour le font.

**Scénario déduit du code.** Un client crée un utilisateur avec `language="fr"` ou `"zh"` ; la
préférence n’est pas enregistrée, bien que la requête soit acceptée.

**Correction envisagée.** Persister ce champ à la création et vérifier le contrat de réponse.

Sources : [schéma accepté](../../back/core/user/schemas.py#L21),
[création administrative](../../back/core/user/user_service.py#L242).

### AUD-18 — P3 — Skills/MCP : documentation de huit outils Topics — prise en charge concurrente

**Statut à la relecture finale.** Une modification concurrente de
`back/app/skill/system_skills/galaris/SKILL.md` a ajouté la section Topics et les huit noms manquants.
Le manque observé initialement est donc pris en charge dans le worktree. Vérifier les signatures
et relancer le test avant de clôturer ce point ; ne pas refaire cet ajout.

**Constat observé par test.** `test_system_skill_documents_every_native_mcp_tool` signale huit
outils absents du skill système : `topic_list`, `topic_get`, `topic_items_list`, `topic_create`,
`topic_update`, `topic_item_move`, `topic_merge`, `topic_split`.

**Impact.** Le catalogue effectif peut exposer ces outils, mais le guide transversal distribué
aux agents ne les explique pas. Le test contractuel prévu pour maintenir cette parité échoue.

**Correction envisagée.** Documenter cette surface dans le package système, ou formaliser un autre
mécanisme de documentation et adapter le test au contrat réellement retenu.

Sources : [test](../../back/app/skill/tests/test_storage.py#L79),
[guide système](../../back/app/skill/system_skills/galaris/SKILL.md),
[outils Topics](../../back/app/topic/mcp.py).

### AUD-19 — P2 — Architecture : la cartographie générée bloque la commande de contrôle

**Constat exécuté.** `make architecture-check` s’arrête dès `project-context-check` : les quatre
fichiers `project-map.md/json` français et anglais sont signalés périmés. Le contrôle des frontières
exécuté séparément en lecture seule répond néanmoins `architecture contracts are satisfied`.

**Impact.** L’index recommandé aux développeurs diverge du code et la commande complète n’atteint
pas ses tests d’architecture. Cela ne démontre pas une violation des frontières de modules.

**Correction envisagée.** Quand les changements concurrents seront stabilisés, exécuter
`make project-context`, revoir le diff puis relancer `make architecture-check`. Ne pas éditer
manuellement les fichiers générés ni relever la baseline pour faire disparaître l’échec.

Sources : [commande de contrôle](../../Makefile#L295),
[cartographie](../../docs/fr/architecture/generated/project-map.md).

### AUD-20 — P2 — Qualité : la suite backend n’est pas verte et certains résultats dépendent du contexte

**Statut à la relecture finale.** Des corrections concurrentes touchent précisément les fixtures,
tests de façade, listes de routes, attente de référent et tests de traces cités ici. Aucun résultat
global postérieur à cet ensemble de modifications n’est revendiqué par cet audit. La prochaine
action est leur validation sur un état stabilisé.

**Constat exécuté.** Suite complète : **30 échecs / 2 958 succès**, sur 2 988 tests.
Relance ciblée des tests utilisateurs et de trois surfaces agent/objectifs : **3 échecs / 32 succès**.
Les sept échecs utilisateurs de la suite complète ne réapparaissent pas dans cette sélection.

**Analyse.** Plusieurs tests utilisent des doubles incomplets ou des contrats anciens. Par exemple :
absence de session DB dans des tests de façade ; anciennes listes d’endpoints autorisés ; faux serveur
WebSocket sans `disconnect()` ; test d’attente de référent plaçant explicitement le parent en
`SUCCESS` avant une transition maintenant réservée à l’exécution. Ce dernier échec ne prouve pas
que le workflow de production effectue cette transition illégale.

**Correction envisagée.** Stabiliser un checkout, isoler les interférences entre tests et aligner les
fixtures sur les contrats courants. Les éditions concurrentes interdisent d’attribuer tous les écarts
à une seule cause. Traiter les échecs de contrôle comme une dette propre ; ne pas les convertir en
« 30 bugs utilisateurs » et ne pas assouplir les assertions sans analyse.

Sources : [fixtures partagées](../../back/conftest.py),
[test d’attente](../../back/app/goal/tests/test_referrer_wait.py#L164),
[contrat de suspension](../../back/app/task/collab.py#L502),
[listes de routes](../../back/core/authorize/tests/test_route_security.py).

## Résultats des vérifications

Commandes exécutées pendant la session du 5 septembre 2026, approximativement de 15 h 39 à
15 h 50, heure de Paris. Les tests backend ont utilisé la base éphémère de `make tests`.

| Vérification | Résultat observé |
|---|---|
| `make typecheck` | Pyright : 0 erreur ; vue-tsc : succès ; 313 tests frontend réussis |
| Parité i18n incluse dans `make typecheck` | 4 451 paires anglais/français et 4 451 messages chinois vérifiés |
| `make tests` | 2 958 succès, 30 échecs, 12 warnings |
| Relance utilisateurs + attente référent + dispatcher/briefing | 32 succès, 3 échecs |
| `make architecture-check` | Arrêt sur les 4 cartographies périmées |
| `architecture_check.py --root /repo`, conteneur avec dépôt monté en lecture seule | Contrats d’architecture satisfaits |
| `make tests-browser` | 7 tests réussis |
| `make tests-harness-manager` | 10 tests réussis |
| Reproductions par extraction des fonctions/classes et doubles sans DB ni réseau | AUD-01, AUD-02, AUD-03, AUD-09, AUD-12 reproduits |

Familles des 30 échecs de la suite complète :

| Domaine | Nombre | Observations |
|---|---:|---|
| `app.agent` | 9 | Dispatcher, briefing, préparation de requête et checkpoints ; 7 erreurs de contexte DB |
| `app.console` | 1 | Test du helper sans contexte DB pour le nouveau contrôle de portée |
| `app.dream` | 1 | Libellé attendu de proposition de sujet différent du libellé courant |
| `app.goal` | 1 | Fixture plaçant le parent en `SUCCESS` avant la suspension |
| `app.skill` | 1 | Huit outils Topics non documentés dans le skill système |
| `app.task` | 1 | Test MCP de tâche fille sans contexte DB |
| `bridge.hermes` | 2 | Tests de synchronisation des skills sans contexte DB |
| `core.authorize` | 3 | Listes attendues des routes publiques/authentifiées devenues incomplètes |
| WebSockets | 3 | Doubles de test et contrat de validation de session |
| `core.user` | 7 | Bootstrap reçoit 403 dans la suite complète ; ces tests passent dans la relance ciblée |
| Traces LLM | 1 | Faux objet incompatible avec `LLMCallRead` |

Les logs complets de travail ont été conservés temporairement sous `/tmp/galaris-audit-*.log`.
Ils ne constituent pas des artefacts versionnés. Aucun appel de test aux comptes externes réels
n’a été nécessaire.

## Couverture par module et fonctionnalité

« Pas de constat supplémentaire » signifie qu’aucun défaut suffisamment étayé n’a été retenu dans
les surfaces examinées ; cela ne signifie pas que le module est exempt de bugs. Les noms groupés
ci-dessous désignent explicitement les modules partageant la même surface technique.

| Module backend | Fonctionnalités examinées ou couvertes par les tests exécutés | Résultat |
|---|---|---|
| `core.user` | Bootstrap, connexion/MFA, refresh, profils, avatars, tokens, CRUD utilisateurs | AUD-14 à 17, 20 ; modifications concurrentes à revalider |
| `core.authorize` | Privilèges, assertions, portée des agents, routes publiques, rôles | AUD-16, 20 |
| `core.params` | Lecture, secrets masqués, paramètres et prompts, application à chaud | Pas de constat supplémentaire |
| `core.dbadmin` | Orchestration, verrou, schéma, datasets, transitions et tests PostgreSQL | Tests exécutés ; pas de constat supplémentaire |
| `app.incident` | Liste, détail, regroupements, statut, purge et accès | Pas de constat supplémentaire |
| `app.tools` | Catalogue effectif, refresh MCP, index et dégradation de découverte | AUD-18 pour la documentation des outils natifs |
| `app.agent` | Registre, dispatcher, briefing/planner, contrat de stream, checkpoints, management | AUD-15, 20 |
| `app.harness` | Exécution interne, historique, médias, budget, interruption | Tests exécutés ; pas de constat supplémentaire |
| `app.harnesses` | Choix du runtime, catalogue, client réseau, capacités et supervision | Tests exécutés ; pas de constat supplémentaire |
| `app.connection` | Connexions, portée des agents, paramètres, activation et droits | Pas de constat supplémentaire |
| `app.skill` | Packages système, fichiers, droits, import, apprentissage | AUD-18, 20 |
| `app.webhook` | Authentification, réception, limite de taille, création de tâche | AUD-12 |
| `app.llm` | Fournisseurs, modèles/profils, gateways, corrélation, traces et coût | AUD-13, 20 ; changements concurrents à revalider |
| `app.topic` | Classement/réutilisation, liste, déplacement, fusion/scission et MCP | AUD-01, 15, 18 |
| `app.memory` | Recherche, ACL, documents, révisions, append/edit, pièces jointes et projections | Tests exécutés ; pas de constat supplémentaire |
| `app.contact` | Identités, contacts accessibles, fusion, oubli et références canoniques | Tests exécutés ; pas de constat supplémentaire |
| `app.dream` | Receipts, leases, reprises, propositions de sujets et monitoring | AUD-01, 20 |
| `app.task` | États, scheduler, leases, coordination, attentes de processus et MCP | AUD-06 à 08, 20 |
| `app.goal` | CRUD, parenté, planning, cycles, pause/reprise, référent humain | AUD-20 ; pas de régression runtime déduite du seul test échoué |
| `app.dashboard` | Totaux mensuels, historiques, coûts et portée des agents | AUD-13, arbitrage explicite |
| `app.lab` | Accès aux évaluations, datasets, exécutions et diagnostics | Tests exécutés ; pas de constat supplémentaire |
| `app.messenger` | Journal canonique, déduplication, livraison, médias, curseurs et dispatch | AUD-05, 09 à 11 côté bridges |
| `app.chat` | Rooms, messages, pièces jointes, aperçus HTML, identité, appels et API | Tests exécutés ; listes de routes à actualiser dans AUD-20 |
| `app.conversation` | Historique, rounds, documents, inspection, liens de tâches/processus | Tests exécutés ; dépend d’AUD-06/07 pour les processus |
| `app.browser` | Sessions, validation d’URL, captures bornées, sidecar et miniatures | 7 tests sidecar réussis ; pas de constat supplémentaire |
| `app.image` | Génération/description, modèles spécialisés, ressources et traces | Tests exécutés ; pas de constat supplémentaire |
| `app.audio` | Découpage, normalisation, transcription et résumé | Tests exécutés ; pas de constat supplémentaire |
| `app.onboarding` | Détection des étapes configurées et possibilités selon les droits | Pas de constat supplémentaire |
| `app.voice` | Appels, transports, transcription/synthèse, inspection et modification des tours | Tests exécutés ; pas de constat supplémentaire |
| `app.file_share` | URI, lecture/écriture, copie, matérialisation, providers et ACL | Tests exécutés ; pas de constat supplémentaire |
| `app.console` | Connexions SSH, clés, helper, executor et supervision | AUD-20 pour le test du helper |
| `app.process` | Démarrage durable, retries, callbacks, annulation, refresh et attentes | AUD-06 à 08 |
| `app.mcp` | Tokens dédiés, endpoint stateless, exposition d’outils et contexte | Tests exécutés ; AUD-18 sur le guide des outils |
| `bridge.harness` | Gestion des runtimes et composition Docker | Tests exécutés ; 10 tests du gestionnaire réussis |
| `bridge.claude_agent` | Provider de harnais, templates runtime et traduction de stream | Tests exécutés ; aucun appel fournisseur réel |
| `bridge.codex` | Provider, runtime, credentials et traduction de stream | Tests exécutés ; aucun appel fournisseur réel |
| `bridge.deepseek_harness` | Provider, configuration et adaptation runtime | Tests exécutés ; aucun appel fournisseur réel |
| `bridge.n8n` | Démarrage, webhook, identifiant d’exécution, statut, résultat et annulation | AUD-06 à 08 dans la couche canonique |
| `bridge.mail` | Lecture, pièces jointes, envoi idempotent, issue incertaine et approbation | Tests exécutés ; pas de constat supplémentaire |
| `bridge.calendar` | CRUD, lecture, disponibilité, créneaux et déclenchements | AUD-02 à 04 |
| `bridge.hermes` | Driver, supervision, skills et intégration de mémoire | AUD-20 pour les tests de skills |
| `bridge.one_bot` | Authentification du socket, hub, réception, envoi et reconnexion | AUD-09, 10 |
| `bridge.matrix` | Réception `/sync`, curseurs, historique et traduction canonique | Curseur persisté après traitement ; pas de constat supplémentaire |
| `bridge.nextcloud` | Polling Talk, historique, erreurs, médias et dispatch | Reprises de curseur examinées ; pas de constat supplémentaire |
| `bridge.telegram` | Polling, albums, curseurs et traduction canonique | AUD-05 |
| `bridge.whatsapp` | Signature, vérification webhook, statut de livraison et limites | AUD-11 |
| `bridge.openrouter` | Enregistrement, découverte, Responses, transcription et accounting | Surface et tests communs examinés ; validation externe restante |
| `bridge.openai` | API, OAuth Codex, découverte, Responses et temps réel | Surface et tests présents examinés ; validation externe restante |
| `bridge.anthropic` | Enregistrement et découverte du fournisseur | Surface examinée ; validation externe restante |
| `bridge.deepseek` | Enregistrement et politique Responses | Surface examinée ; validation externe restante |
| `bridge.fireworks` | Enregistrement, capacités et politique Responses | Surface examinée ; validation externe restante |
| `bridge.groq` | Enregistrement, capacités et politique Responses | Surface examinée ; validation externe restante |
| `bridge.mistral` | Enregistrement et capacités | Surface examinée ; validation externe restante |
| `bridge.models_dev` | Contribution de métadonnées au catalogue | Surface examinée ; validation externe restante |
| `bridge.together` | Enregistrement du fournisseur | Surface examinée ; validation externe restante |
| `bridge.cerebras` | Enregistrement du fournisseur | Surface examinée ; validation externe restante |
| `bridge.google` | Gemini, Cloud TTS, découverte et synthèse | Surface examinée ; validation externe restante |
| `bridge.xai` | Enregistrement et transport Responses | Surface examinée ; validation externe restante |
| `bridge.nvidia` | Enregistrement et politique Responses | Surface examinée ; validation externe restante |
| `bridge.huggingface` | Enregistrement et politique Responses | Surface examinée ; validation externe restante |
| `bridge.cohere` | Enregistrement et capacités | Surface examinée ; validation externe restante |
| `bridge.perplexity` | Enregistrement, adaptation protocole et Responses | Surface examinée ; validation externe restante |
| `bridge.elevenlabs` | Découverte, synthèse et transcription dont temps réel | Surface examinée ; validation externe restante |
| `bridge.azure_speech` | Découverte et synthèse | Surface examinée ; validation externe restante |
| `bridge.ollama` | Découverte, installation/suppression et adaptation OpenAI | Surface et tests présents examinés ; validation externe restante |

Infrastructure hors liste de modules : sessions SQLAlchemy, middleware, WebSockets, chargeur de
modules, Make/Compose et contrôles d’architecture. Les travaux concurrents sur l’authentification
et les WebSockets demandent une nouvelle validation une fois stabilisés.

| Module(s) frontend | Fonctionnalités couvertes par l’inventaire, la lecture ciblée ou les contrôles | Points retenus |
|---|---|---|
| `core/user` | Connexion, inscription initiale, comptes, profil, tokens | AUD-14 à 17, 20 |
| `core/authorize` | Rôles, affectations, sélecteurs et profil de droits | AUD-16 |
| `core/params` | Paramètres, secrets, sections et configuration des harnais | Aucun constat supplémentaire |
| `app/index` | Shell responsive, accueil, onboarding, dashboard | AUD-13 |
| `app/agent` | Liste, édition, managers, avatars, harnais, tokens MCP | AUD-15 |
| `app/harnesses` | Détail et sélection de harnais | Aucun constat supplémentaire |
| `app/tools` | Catalogue, configuration et tests de connexion | AUD-18 côté guide des outils |
| `app/connection` | Paramètres, autorisations et courrier | Aucun constat supplémentaire |
| `app/skill` | Catalogue, autorisations et skills appris | AUD-18 |
| `app/llm` | Modèles, profils, fournisseurs et historique d’appels | AUD-13 |
| `app/task` | Liste, détail, activité et commandes | AUD-06 à 08 côté backend |
| `app/conversation` | Historique et détail de rounds | AUD-06/07 côté processus |
| `app/chat` | Messagerie, rooms, fichiers et appels | Pas de parcours E2E manuel dans cet audit |
| `app/voice` | Historique des appels et tours | Aucun constat supplémentaire |
| `app/dream` | Monitoring, receipts et explication de classement | AUD-01 côté classement |
| `app/topic` | Dossiers, contenu, fusion/scission et sélecteur | AUD-01, 15 |
| `app/goal` | Objectifs, arbre, planning et historique des cycles | AUD-20 côté tests |
| `app/memory` | Mémoire, graphe, bibliothèque, documents et contacts | Aucun constat supplémentaire |
| `app/lab` | Évaluations et incidents | Aucun constat supplémentaire |
| `app/process` | Définitions, exécutions, refresh, annulation | AUD-06 à 08 |
| `app/console` | Configuration et supervision executor | Aucun constat supplémentaire |
| `bridge/nextcloud`, `bridge/matrix` | Contributions de configuration/traduction | Pas de parcours avec serveur réel |
| `bridge/telegram`, `bridge/whatsapp`, `bridge/one_bot` | Contributions de configuration/traduction | AUD-05, 09 à 11 côté backend |
| `bridge/n8n`, `bridge/calendar` | Contributions de configuration | AUD-02 à 08 côté backend |
| `bridge/claude_agent`, `bridge/codex`, `bridge/deepseek_harness` | Contributions à la sélection des runtimes | Aucun constat supplémentaire |
| `bridge/hermes`, `bridge/ollama` | Configuration et supervision | Aucun constat supplémentaire |

## Ordre de correction proposé

1. **Fiabilité métier** : AUD-01, 02, 04, 05, 06 et 07.
2. **Reprises et limites** : AUD-03, 08 à 12, 14 et 15.
3. **Contrôles fiables** : AUD-19 et 20, sur un checkout stabilisé ; ajouter les régressions manquantes.
4. **Contrats produit et finitions** : arbitrer AUD-13/16, puis AUD-17 ; valider la prise en charge d’AUD-18.

Pour chaque correctif, repartir du scénario décrit et ajouter un test au niveau de son contrat.
La réussite des tests actuels ne couvre pas à elle seule les interruptions entre deux commits,
les corps sans longueur annoncée ni les jeux de données dépassant les plafonds implicites.
