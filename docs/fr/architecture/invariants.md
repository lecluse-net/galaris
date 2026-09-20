<p align="right"><strong>Français</strong> · <a href="../../en/architecture/invariants.md">English</a></p>

# Invariants d’architecture

Ces invariants réduisent les ambiguïtés qui coûtent le plus cher lors d’un diagnostic ou
d’une modification. Ils décrivent le runtime actuel ; une évolution doit changer ensemble le
contrat, les tests et cette documentation.

| ID | Invariant | Autorité principale |
|---|---|---|
| INV-01 | PostgreSQL est la source durable des tâches, objectifs, process et journaux métier. | Modèles et services SQLAlchemy |
| INV-02 | `back/core` ne dépend jamais de `app` ni de `bridge`. | `architecture_check.py` |
| INV-03 | Les domaines communiquent par package public, `contracts`, `facade`, `interface` ou port. | Tests AST et revues |
| INV-04 | `app.agent` orchestre ; `app.task` persiste et ordonnance, sans dépendance inverse directe. | `AgentTaskPort` et tests agent |
| INV-05 | Driver, politique et modèle d’un run sont figés avant l’appel du runtime. | Contrats `app.agent` |
| INV-06 | Un stream agentique possède exactement un résultat terminal et rien après. | Façade et tests de streaming |
| INV-07 | Un travail de scheduler est protégé par un lease et audité par une tentative durable. | `Task`, `TaskAttempt` |
| INV-08 | Tous les transports conversationnels convergent vers `app.messenger`. | `Messenger`, `BridgeSpec`, `dispatch_incoming` |
| INV-09 | La déduplication durable d’un message inclut connexion, identifiant distant et direction. | Contrainte du journal messenger |
| INV-10 | Les transitions de process sont monotones ; un état terminal ne rouvre pas. | `process_service.TRANSITIONS` |
| INV-11 | Un chemin temporaire matérialisé par le serveur est borné, nettoyé et ne devient jamais une URI. `console://` est le seul système de fichiers local visible, uniquement avec une console active. | Transports `app.file_share` |
| INV-12 | `core.dbadmin` fait converger tout le schéma PostgreSQL `public` depuis les modèles avec Atlas encapsulé ; aucun autre schéma ni aucune migration Alembic ne coexiste dans ce périmètre. | `core.dbadmin`, `make update`, `make sync-db` |
| INV-13 | Le backend impose le RBAC ; la navigation frontend n’est qu’une représentation. | Routers et tests d’accès |
| INV-14 | Toute chaîne visible conserve la parité anglaise/française. | Contrôles i18n de `make typecheck` |
| INV-15 | Tout outil qui échange un fichier reçoit et rend une URI `app.file_share`; un besoin local est satisfait par une matérialisation temporaire bornée et nettoyée, sans copie persistante imposée à l'appelant. | `resource_service.materialize_resource`, outils image/audio/Messenger |
| INV-16 | Un plan décrit une intention tant que son statut et le code ne prouvent pas sa livraison. | `project/plans/README.md` |
| INV-17 | Les réglages fonctionnels administrables ont `params` pour source durable ; `.env` reste réservé au bootstrap et à l’infrastructure. | `core.params`, ADR 0005 |
| INV-18 | Toute boucle runtime racine enregistrée est supervisée sans déplacer son état métier hors de son domaine ; seule une défaillance critique bloque la readiness. | `core.runtime`, lifespan et tests de santé |
| INV-19 | Un listener à curseur n’avance son acquittement durable qu’après admission complète du lot ; une reprise rejoue depuis le dernier curseur confirmé et s’appuie sur la déduplication canonique. | `app.messenger.journal`, listeners et tests de bridge |
| INV-20 | Un tour vocal est une entité conversationnelle, pas une Task ; le pipeline utilise le harnais interne, le modèle et la projection d’outils du mode conversation, tandis que le temps réel natif conserve la même politique bornée. Un barge-in le marque `INTERRUPTED` et reporte son objectif durable sur le tour suivant. | `app.voice`, façade `app.agent` et contrôleur `app.harness.conversation` |
| INV-21 | Les enrichissements Dream sont séquentiels, idempotents et préemptibles ; ils ne traversent ni `app.agent`, ni un driver, ni MCP. La réconciliation déterministe des liens appartient au worker Memory et n'apparaît ni dans les reçus ni dans la jauge Dream. | `app.dream`, `app.memory.automation`, `DreamReceipt` et garde Voice |
| INV-22 | L'adresse sociale d'un compte humain est `(messaging_id, user_id)` avec le code de bridge et l'identifiant natif exact, sauf Mail dont l'adresse RFC validée est normalisée sans distinction de casse. Chaque adresse forte et chaque `galaris_user_id` résout un contact Memory privé par agent ; seul ce lien utilisateur prouvé ou une fusion administrative explicite peut réunir plusieurs canaux. La fusion repointe atomiquement scopes, liens, messages, rounds et Tasks avant d'oublier le doublon. L'oubli administratif efface les mémoires scellées, vide ces références puis purge le contact et ses identités ; une observation future repart d'un contact neuf. Connexion, room et message restent des routes ou événements techniques et n'entrent jamais dans cette identité. | `app.messenger.contact_memory`, `app.memory.contact_directory`, `app.contact` et tests de fusion/oubli |
| INV-23 | Les liens mémoire dérivés des provenances relient un souvenir à son Topic et, pour une source conversationnelle, à son contact exact. Ils restent bornés, idempotents et ne modifient jamais les ACL du souvenir privé. | `app.memory.link_reconciliation`, scopes Topic/contact et tests de réconciliation |
| INV-24 | Une projection Process ne contient jamais l'entrée ni le snapshot brut ; seules une définition affectée et une sortie réussie, assainie et bornée deviennent des mémoires privées source-managed. | `app.memory.process_projection`, sanitizer Process et tests de projection |
| INV-25 | Un document de travail est un nœud mémoire `document/working`, privé à sa création et modifié par révisions atomiques. Son propriétaire seul gère les grants et l'oubli ; les collaborateurs n'accèdent qu'aux passages bornés et n'écrivent qu'avec un grant explicite. | `app.memory.document_service`, tools MCP Document et tests d'intégration |
| INV-26 | La découverte sémantique d’outils classe uniquement le catalogue MCP effectif déjà filtré. Le planner conserve tous les noms autorisés ; un index ou un top-k ne confère aucun droit et ne masque jamais le manifeste exhaustif. Une réconciliation complète n’élague l’index que lorsque toutes les sources ont répondu. | `app.tools.catalog`, `tool_search_service`, `catalog_refresh_service`, planner et toolset interne |
| INV-27 | Une skill auto-apprise dérive uniquement de preuves observables, bornées et expurgées. Elle appartient à un agent dans les tables dédiées `learned_skills` et `learned_skill_evidences`, reçoit des renforcements positifs ou négatifs idempotents et n'est injectée qu'après confirmation par le nombre configuré de Tasks distinctes et franchissement du seuil de score. Dream parcourt aussi l'historique terminal, une Task par passage. L'apprentissage n'écrit aucun nœud Memory. | `app.dream.outcome_evidence`, `skill.learn_task_outcome`, `app.skill.learning_service` et ADR 0047 |
| INV-28 | Tout system prompt d’exécuteur dérive d’un arbre JSON ordonné rendu en Markdown par la frontière commune. Son suffixe administrable est le dernier nœud, dépend de l’exécuteur et jamais du LLM. La politique d’action conversationnelle est un Param distinct partagé par le texte et la voix ; un run du Lab fige les valeurs effectives et le rendu. | `app.agent.prompt_tree`, `app.agent.executor_prompts`, `core.params`, `app.lab` et ADR 0023 |
| INV-29 | Une nouvelle instruction conversationnelle arbitre explicitement entre création et amendement. Un amendement conserve l’UUID, vérifie scope et révision, refuse les structures actives non sûres et produit un audit idempotent avant reprise. `WAITING` et `PAUSED` sont des projections opérationnelles, jamais des phases persistées. | `TaskAmendment`, `app.task.operational_state`, outils Conversation et ADR 0025 |
| INV-30 | Le contexte implicite d'une Task humaine est sélectionné par contact canonique, jamais par Topic ni par simple room. Son manifeste borné est figé sur la racine avant dispatch et partagé par tout le plan ; seul le Working Set courant reste dynamique. Sans contact prouvé, aucun historique collectif n'est injecté. | `app.agent.context`, providers Messenger/Memory/Task et ADR 0032 |
| INV-31 | Toute ressource fichier échangée entre domaines, outils ou étapes possède une URI canonique résolue par `app.file_share`. Le schéma externe est le code de Tool connecté, les protocoles et schémas natifs sont réservés, les chemins relatifs sont refusés et aucune URI ne contourne ACL ou validation SSRF. | `app.file_share`, Working Set et ADR 0046 |
| INV-32 | Un paramètre effectif de connexion suit une seule cascade : valeur globale imposée, sinon surcharge locale non vide, sinon valeur globale non vide. Les secrets restent chiffrés et la synchronisation d’un Tool intégré ne remplace jamais ses valeurs globales administrées. | `app.tools.global_params`, `app.connection.connection_service` et ADR 0035 |
| INV-33 | Le harness manager hôte ne connaît aucun runtime : il gère des instances Compose, des actions bornées et leurs fichiers. Images, configuration, CLI et API spécifiques restent dans `back/bridge/<runtime>`. | `harness_manager`, `back/bridge/hermes` et ADR 0038 |
| INV-34 | Les dépendances inter-domaines restent sous les plafonds déclarés ; aucun nouvel import privé ni cycle nouveau ou élargi n'est admis sans réduction explicite des baselines backend et frontend. | `back/architecture.toml`, `back/architecture-baseline.json`, `front/architecture-baseline.json`, `architecture_check.py` |
| INV-35 | Tout stream agentique est interrompu et échoue sans retry automatique lorsque le même motif de réflexion ou de texte généré se répète plus de 30 fois consécutives sans activité d'outil. | `app.agent.reasoning_guard`, façade `app.agent` et scheduler `app.task` |
| INV-36 | Un Param de type prompt suit son défaut tant que sa valeur durable reste `NULL`. Une personnalisation conserve l’empreinte du bundle de défauts localisés sur lequel elle repose ; DbAdmin avance les seuls followers et l’administrateur résout explicitement tout défaut plus récent sans écrasement au démarrage. | `core.params`, composant `PromptSettingEditor` et ADR 0048 |
| INV-37 | Un service applicatif, une façade appelée ou une fonction MCP consomme exclusivement la session contextuelle avec `get_db()`. Seules les frontières autonomes auditées — requête spéciale, scheduler/worker, listener, callback détaché, runtime ou CLI/infrastructure — ouvrent une transaction avec `get_db_session()` ; aucune session SQLAlchemy n'est partagée entre branches concurrentes et les canaux longs MCP/WebSocket n'héritent pas de la session HTTP. | `core.database`, wrapper MCP central et test AST des frontières de session |

## Persistance et concurrence

Les caches, registres et listeners en mémoire accélèrent ou relient le runtime ; ils ne
remplacent pas les lignes durables. Une reprise après crash s’appuie sur les statuts, leases,
tentatives, curseurs, clés d’idempotence et événements enregistrés en PostgreSQL.

Toute écriture susceptible d’être rejouée doit posséder une identité stable ou une contrainte
d’unicité. Une notification externe tardive ne doit pas faire régresser une livraison ou
rouvrir un process terminal.

## Supervision du runtime

Le superviseur générique connaît uniquement le cycle de vie et l’état courant des tâches racines.
Il peut relancer le scheduler ou les superviseurs de listeners, mais ne modifie jamais une tâche,
un message, un appel ou un process métier. Avant une relance, il appelle toujours l’arrêt du
domaine afin que celui-ci annule et attende ses enfants.

La liveness décrit le processus HTTP. La readiness ajoute PostgreSQL et les composants critiques.
Un bridge optionnel indisponible produit un état `degraded`, pas une indisponibilité globale. Les
réponses publiques ne contiennent ni message d’exception, ni configuration, ni secret.

## Frontières agentiques

`app.task.agent_adapter` enregistre le port durable consommé par `app.agent`. Le scheduler
peut appeler la façade agentique, mais les contrats et drivers agentiques ne connaissent pas
le modèle SQLAlchemy `Task`. Le harnais interne Pydantic AI reste dans `app.harness` et
Hermès dans `bridge.hermes`.

Une exception contrôlée existe pour `RESUME_COLLABORATION` : elle peut rouvrir la phase d’une
tâche terminée afin d’agréger des enfants de coordination sans rejouer les effets déjà
réussis. Ce n’est pas une autorisation générale de réécrire un état terminal.

Les lectures destinées aux agents complètent la phase durable par un état opérationnel dérivé.
Une attente expose sa nature, la question, l’interlocuteur et l’échéance à partir des enfants de
coordination ; une pause humaine reste distincte. La politique conversationnelle compare ces
candidats avant toute création. L’amendement d’un même livrable passe par `AgentTaskPort`, conserve
la Task racine, écrit `TaskAmendment` et repasse par `CREATE` lorsque le dispatcher doit réévaluer
l’objectif. Les plans matérialisés, enfants délégués actifs et Tasks terminales ne sont jamais
réécrits silencieusement.

## Frontières de messagerie et fichiers

Un bridge authentifie et traduit son protocole. Le domaine messenger journalise, déduplique et
déclenche le workflow commun. Les pièces jointes gardent l'URI du Tool d'origine ; une
matérialisation temporaire bornée n'en change jamais l'identité.

La référence inter-domaines est une URI canonique.
`<tool.code>://room-provider/attachment-uuid` désigne une pièce jointe persistée. Les chemins
relatifs et les anciens schémas locaux implicites sont refusés. Les codes de Tools portant Messenger ou file-share
servent directement de schémas et ne peuvent usurper ni `http`/`https`, ni un schéma natif. Seule
la façade publique `app.file_share` les résout.

Après résolution du kind et de l'identité IA, Messenger projette les seuls expéditeurs humains via
la façade publique Memory. Cette dépendance n'existe dans aucun bridge conversationnel. La
projection est privée par agent, idempotente et fail-open ; le journal canonique permet son rejeu.

Les appels vocaux persistants appartiennent à `app.voice`. Chaque traitement est un
`ConversationRound` invoqué avec `task_id=None`; son `conversation_round_id` assure la corrélation
LLM. Une nouvelle
prise de parole annule le calcul et la lecture audio du tour, mais ne produit jamais un statut
`Task.ERROR`. L'objectif interrompu reste dans la session jusqu'à une réponse complète.

## Vérification

```bash
make project-context-check
make architecture-check
make typecheck
```

Ajouter un test AST lorsqu’un invariant porte sur une dépendance, un test de matrice pour une
machine d’état et un test d’intégration PostgreSQL pour une garantie de persistance.
