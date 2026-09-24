<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/agent-execution.md">English</a></p>

# Flux d’exécution agentique

Avant chaque nouvelle exécution, la façade vérifie la révision des skills du
provider sélectionné. Un changement de contenu ou d'autorisation est projeté avant
le démarrage du driver, sans interrompre une Task en cours. Le reçu est invalidé
avant copie et une erreur empêche l'exécution avec une projection périmée. Les
demandes de rafraîchissement sont persistées, indépendamment de l'interface ; le
statut du runtime expose l'état des skills. Une reprise avec checkpoint conserve
les skills et credentials de l'opération distante qu'elle réconcilie. Voir
[0131](../../../../project/decisions/0131-harness-skill-reconciliation.md).

La validation commune des harnais retient le résultat candidat jusqu’à la fermeture
normale du flux et au nettoyage de l’adaptateur. Les messages restent diffusés
immédiatement. Une queue invalide ou bloquée produit un échec avant toute publication
de succès ; `AgentDriverSpec.stream_close_timeout_seconds` borne cette fermeture pour
tous les drivers. Voir la [décision 0098](../../../../project/decisions/0098-harness-stream-acceptance.md).

Les politiques de tous les harnais, y compris l’interne, se règlent dans le catalogue
des harnais. La capacité effective est l’intersection de l’implémentation, de la
configuration et des capacités vérifiées de la sélection. Les checkpoints sont opaques
pour l’orchestration ; leur driver déclare si une reprise ou un amendement est sûr.
Une réponse d’annulation distingue demande reçue et arrêt confirmé. Voir
[0100](../../../../project/decisions/0100-harness-capability-and-recovery-contract.md).

## Inférence élémentaire

Les modèles internes Chat/Responses traversent la façade d’inférence durable de `app.llm`.
Dispatcher et Briefing utilisent aussi l’adaptateur structuré, avec leur schéma et contexte
de validation figés. L’admission est committée avant le départ du worker ; ses leases,
événements et résultats ne remplacent ni les tentatives Task ni les checkpoints d’outils.
`LLMCall` reste la source des coûts des appels physiques. Le pilote d’extraction Memory du Lab
utilise le même journal tout en gardant ses retries métier.

La lecture d’une tentative restitue les messages puis un résultat terminal unique. Une
reconnexion reprend au curseur ; une commande `resume` crée une nouvelle tentative de la
requête figée. Le service ne rejoue aucun outil. Les adaptateurs synchrones et HTTP demandent
l’arrêt lors de leur annulation ; fermer un simple abonnement au journal laisse l’inférence
autonome se poursuivre. Voir les [états d’inférence](../state-machines.md) et
[0097](../../../../project/decisions/0097-durable-inference-lifecycle.md).

## Activité des tâches et provenance

Le harnais interne rend les erreurs d’outil au modèle sous forme structurée, y compris
lorsque leur effet reste incertain. Le modèle décide de vérifier, corriger, poursuivre
ou arrêter. Le checkpoint v4 conserve séparément ces erreurs acquittées et les appels
interrompus sans réponse ; le stream continue de signaler un échec d’outil sans en faire
automatiquement un échec de Task. Voir [0103](../../../../project/decisions/0103-tool-errors-return-to-agent.md).

Le chat et la fiche tâche réhydratent `POST /tasks/activity` à l’ouverture et à la reconnexion,
puis partagent les abonnements aux runs actifs. La projection commune expose état opérationnel,
pause demandée ou acquittée, attentes, dernière tentative et prochaine reprise. `task_get` expose
également cette activité pour les tâches actives et terminales. Le résultat terminal reste
autoritaire, et la façade rejette les événements tardifs avant leur publication.

Les conversations affichent les fragments de texte immédiatement. Les vues Task attendent
la clôture des blocs (`AIMessage.stream_complete`) pour afficher leur texte ou réflexion ;
les états et résultats d'outils restent actualisés pendant l'exécution. Les anciens drivers
sans marqueur attendent l'opération suivante ou le résultat terminal, et les vues par appels
LLM attendent `completed_at`. Les fragments internes restent disponibles aux gardes et
checkpoints. Voir [0087](../../../../project/decisions/0087-task-activity-snapshots.md).

Le checkpoint visuel `TaskAttempt.data.live_activity` est limité à 40 messages de 4 000 caractères,
sans prompts ni charges structurées d’outils. Une écriture JSONB indépendante préserve les reçus
et checkpoints d’effets. Le harnais personnalisé peut sélectionner les appels LLM corrélés avec
`streams_ai_messages=false` ; les harnais intégrés conservent leurs messages natifs. Le frontend
signale la limite de 500 appels chargés et n’additionne pas les deux sources.

La fiche montre la demande initiale conservée à l’admission des nouvelles tâches, la provenance
et les ressources/reçus enregistrés. Les tâches historiques ne sont pas rétroactivement réécrites.
La fiche tâche et le détail du round affichent aussi le démarrage initial des Tasks créées par
la conversation : préparation de l’objectif, admission après préparation et borne maximale
d’attente avant la première prise en charge. `Task.data._startup_timing` conserve les trois
horodatages UTC observés ; `TaskAttempt.data.claimed_at` conserve l’heure réelle de prise en
charge, indépendamment du début de transaction PostgreSQL. Le dernier horodatage d’admission
précède l’INSERT/commit : l’intervalle suivant inclut donc cette persistance et les éventuelles
pauses, et ne prouve pas une saturation du scheduler. Seule la tentative numéro 1 compte ;
les reprises et mises à jour ne réinitialisent pas ces mesures. Toutes les insertions ORM
enregistrent aussi la mise en file dans `Task.lifecycle_timing`, colonne nullable distincte des
données métier. Les changements de phase, bail, pause et backoff cumulent les intervalles
par état et phase, sans modifier les décisions du scheduler. La projection indique depuis
quand ces cumuls sont observés ; une pause pendant un bail actif reste du traitement jusqu’à
la libération du bail. Le temps après expiration d’un backoff redevient du temps en file.
Pour les tâches historiques, la façade LLM récupère les heures réelles des appels persistés,
y compris la préparation lorsque son round appartient sans ambiguïté à une seule tâche.
Elle ne fabrique pas une heure de claim depuis `created_at` ou `updated_at`. Les vues présentent
les intervalles disponibles avec leur source plutôt que des cases « non mesuré ». Les requêtes
sont groupées sur les seules tâches autorisées ; la récupération des appels historiques est
inutile lorsqu’une mise en file a déjà été observée.
Voir la [décision 0087](../../../../project/decisions/0087-task-activity-snapshots.md) pour les bornes,
la réhydratation et la distinction avec le futur contrôle générique des effets.

## Autorité du demandeur

Une connexion `openai-codex` représente un abonnement personnel et désigne son titulaire dans
Galaris. Avant tout transport, la façade LLM recoupe ce titulaire avec le requester durable de la
Task et de sa lignée. Un Goal fige le requester de son référent lors de sa configuration et le
transmet à chaque cycle. Les enfants, délégations, Processes et harnais conservent ainsi la
même autorité sans accepter un identifiant déclaré par le runtime. Sur une instance
mono-utilisateur, les travaux internes sans auteur explicite peuvent revenir au seul titulaire ;
ce repli ne s’applique jamais aux origines Messenger.

Ce flux explique le chemin commun d’une tâche, indépendamment du runtime concret. Le control plane
texte de `app.conversation` possède un contrôleur interne distinct ; les conversations vocales
temps réel conservent leur chemin spécifique sans Task.

```text
Task PostgreSQL ── app.task scheduler/agent_adapter ──► AgentTaskPort
       │                                                │
       └──────────────► app.agent facade ◄──────────────┘
                              │
               dispatcher + politique du driver
                              │
                  planner / briefing éventuels
                              │
             providers de contexte communs, fail-open
 historique gouverné si requis + Working Set courant
                              │
             modèle et stratégie résolus une fois
                              │
                 AgentRunRequest local
                  ├─ AgentRunControl local
                  └─ enveloppe V1 validée
                      ┌───────┴────────┐
                      ▼                ▼
       app.harness           app.harnesses
        Pydantic AI        Chat Completions
                         ├─ URL configurée
                         ├─ bridge.deepseek_harness
                         ├─ bridge.claude_agent
                         └─ bridge.codex
                      └───────┬────────┘
                              ▼
              messages* + ExecutionResult unique
                              ▼
               application puis persistance durable
```

## Propriétaires des décisions

| Décision | Propriétaire |
|---|---|
| Phase, lease, tentative, pause, reprise | `app.task` |
| Driver disponible et descripteur | registre `app.agent` |
| Route EXEC/BRIEFING/PLAN et effort | dispatcher `app.agent` borné par la politique du harnais sélectionné |
| Activation du planner et du briefing | `DriverPipelinePolicy` |
| Tous les usages LLM | niveau texte ou colonne spécialisée du profil effectif, sauf surcharge durable de raisonnement portée par la Task |
| Modèle standard/high | resolver `app.agent`, une fois par run |
| Adaptateur direct ou Kanban interne à Hermès | `bridge.hermes.driver` |
| Session conversationnelle | projection du journal `app.messenger` |
| Rappel de mémoire durable | `app.memory`, ACL et budget avant le driver |
| Ressources actives du travail | Working Set racine possédé par `app.task` |
| Adaptation au runtime Pydantic AI | `app.harness` |
| Adaptation aux Harness réseau | client commun `app.harnesses` |
| Provisionnement DeepSeek Harness | `bridge.deepseek_harness` via `bridge.harness` |
| Provisionnement Claude Agent SDK | `bridge.claude_agent` via `bridge.harness` |
| Provisionnement OpenAI Codex SDK | `bridge.codex` via `bridge.harness` |
| Adaptation historique au runtime Hermès | `bridge.hermes` |
| Validation du stream et application du résultat | façade `app.agent` |
| Projection d'un résultat terminal dans une conversation | `app.conversation` |

`app.task` ne choisit ni le driver, ni le modèle, ni l’activation des aides. Un driver ne
recalcule pas ces décisions après réception de l’`AgentRunRequest`.
Le driver Hermès refuse tout `AgentRunRequest` sans `task_id` : les rounds conversationnels et
vocaux sans Task sélectionnent explicitement le harnais interne avant l’appel d’un driver.
Le proxy LLM applique le même invariant aux requêtes authentifiées d'un runtime géré. Le handshake
MCP reste autorisé avant une Task, car le client Hermès s'initialise au démarrage du conteneur ; la
Task active est injectée dans le contexte des requêtes d'outils. Les jetons MCP créés explicitement
par un utilisateur conservent leur contrat générique.
Une corrélation implicite par seul `agent_id` n'est acceptée que lorsqu'une unique Task est active.
Le gateway consulte d'abord le registre local du run, puis l'unique lease durable de cet agent afin
que la corrélation reste valable derrière plusieurs workers HTTP. Plusieurs correspondances font
échouer cette voie fermée. Chaque provider de Harness externe déclare donc actuellement
`max_parallel_tasks=1`; le scheduler vérifie cette limite sous le verrou transactionnel de l'agent
en comptant les leases non expirés. Le harnais interne expose `max_parallel_tasks=null` et peut
exécuter plusieurs Tasks du même agent, car chacune transporte explicitement `task_id` et
`agent_run_id`. Le service LLM résout en plus la tentative active et redérive le round depuis la
Task. Un Harness n'exécute jamais un round conversationnel et ne transporte donc jamais de
`conversation_round_id` : les conversations texte et voix utilisent exclusivement leur contrôleur
interne dédié.
Les appels bas niveau du contrôleur conversationnel interne conservent en revanche leur corrélation
`agent_id` pour l'audit sans devenir des exécutions de Harness ni des requêtes de runtime managé :
un round conversationnel ou vocal sans Task reste donc autorisé quel que soit le driver configuré
sur l'agent. La configuration
opérateur d'Hermès est possédée par `/api/hermes/configurations` et n'est plus exposée par le CRUD
Agent générique. Sa présentation reste une contribution de `front/bridge/hermes` à l'onglet de la
fiche Agent et au sous-menu `Préférences > Harnais`, sans entrée de navigation autonome.
La cible OpenAI-compatible Hermès — URL, token, modèle et port publié — est une donnée interne
générée par Galaris et n'appartient ni à cette API de configuration opérateur ni à son formulaire.
Le bridge injecte obligatoirement le modèle effectif via le gateway LLM Galaris après toutes les
surcharges Hermès et retire les credentials de fournisseurs directs ; cette politique n'est pas
configurable par agent.
Lorsqu'une connexion Console externe est active, le même bridge résout ses paramètres effectifs
par la surface publique d'`app.connection`, puis les projette dans le backend terminal natif
d'Hermès après les surcharges opérateur. La clé privée déchiffrée et
la confiance d'hôte restent dans des fichiers d’instance bornés (`0600`) ; seul leur chemin apparaît
dans l'environnement Hermès. Des wrappers OpenSSH propres à l’instance imposent le `known_hosts`
Galaris à `ssh` comme à `scp`. Une connexion embarquée ne modifie pas le terminal natif, et la
suppression de la cible externe restaure les valeurs précédentes.

La supervision opérationnelle est distincte de cette configuration. L'écran Agents appelle les
routes génériques `/api/harnesses/agents/{id}/...` de `app.harnesses`. La façade résout la
contribution du driver et n'expose que les capacités réellement disponibles. Hermès contribue son
adaptateur et utilise exclusivement le manager hôte `bridge.harness`. Chaque agent Hermès possède
une instance et un conteneur `<agent.code>-agent` propres ; les boutons de statut, logs,
démarrage, arrêt, mise à jour et redémarrage ne dépendent toutefois pas du nom Hermès dans le
frontend.

Le catalogue `app.harnesses` fusionne deux sources sans les confondre : chaque provider de bridge
fourni par le code possède un Param booléen global d'activation, tandis que la table `Harness` est
réservée aux configurations OpenAI Messages réutilisables et autorise plusieurs occurrences.
Toutes partagent la même grille de cartes et chaque agent ne possède au plus qu'une affectation
runtime `AgentHarness`. L'activation rend une carte sélectionnable sans la masquer lorsqu'elle est
inactive. Une configuration OpenAI Messages, son secret et son modèle sont saisis uniquement sur
sa page de catalogue, jamais dans la fiche Agent. Désactiver une carte ou supprimer une
configuration OpenAI Messages détruit les runtimes affectés puis repasse leurs agents sur le
harnais interne ; l'opération reste interdite pendant une Task non terminale.

Modifier un agent ne provisionne jamais un conteneur. Un changement de Harness persiste d'abord
la nouvelle préférence, marque son runtime `absent` et détruit l'ancien runtime en arrière-plan
après confirmation explicite de la perte de données. Les actions `restart` et `update` de la carte
Agent sont les seules commandes de recréation : elles suppriment l'instance éventuelle, puis la
reprovisionnent en arrière-plan. Tous les providers conteneurisés utilisent l'unique répertoire
d'instance `<agent.code>` et l'unique nom de conteneur `<agent.code>-agent`, indépendamment du
Harness sélectionné. Les configurations OpenAI Messages non conteneurisées deviennent directement
`ready` puisqu'elles ne possèdent aucun runtime local à construire.

La fiche Agent inspecte les Tasks racines non terminales avant ce changement. Lorsqu'elles sont
en pause, elle les nomme, explique qu'une terminaison forcée les marquera en erreur et demande une
confirmation explicite avant d'exécuter cette commande puis de reprendre la sauvegarde. Les Tasks
actives ne sont jamais terminées automatiquement ; elles restent signalées comme bloqueurs jusqu'à
leur fin.

## Séquence nominale

1. Le scheduler réclame une tâche éligible avec un lease durable et crée un `TaskAttempt`.
2. L’adapter convertit le modèle ORM en contrat agentique sans exposer SQLAlchemy au driver.
3. Le dispatcher construit les couples route/effort déclarés par le harnais sélectionné, applique
   les contraintes et n'appelle un modèle que s'il reste plusieurs choix. Un choix unique est
   déterministe ; des contraintes incompatibles échouent, même sans modèle configuré. La décision
   et la liste des choix sont persistées. Il distingue la difficulté de la décomposabilité :
   une opération explicite, bornée, mécanique et simplement vérifiable reste en `EXEC standard`,
   y compris lorsqu'elle emploie plusieurs outils ou applique une action destructive déjà autorisée.
   Le risque détermine les garde-fous, pas l'effort. Un livrable cohérent réellement complexe et
   produit par plusieurs passes de recherche, construction, vérification et livraison reste en
   `EXEC high`. `PLAN` exige plusieurs unités de travail
   indépendamment exécutables dont les résultats durables gagnent à être coordonnés. En cas
   d'ambiguïté entre ces deux routes, `EXEC high` est préféré. Un choix forcé explicite est honoré
   sans réévaluation cachée.
4. Le planner ou le briefing s’exécute si le dispatcher a retenu cette route parmi les capacités
   du harnais. `EXEC high` n'implique aucun briefing automatique pour une nouvelle décision.
   Le planner reçoit tous les noms du catalogue MCP effectif, sans
   plafond global, puis un top-k hybride détaillé calculé après filtrage des droits. La version
   du catalogue est persistée avec le plan et chaque identifiant choisi est validé contre elle.
   Le palier de modèle et son `reasoning_effort` sont deux réglages indépendants du profil LLM :
   le couple est résolu et figé dans l’identité du run avant l’entrée dans le driver.
   L’échelle canonique est `none`, `low`, `medium`, `high`, `xhigh`, `max`; une valeur absente
   signifie « automatique ». La valeur historique `minimal` est normalisée en `low` et n’est plus
   émise. Les bridges et harnesses gérés adaptent cette échelle lorsque leur runtime emploie des
   niveaux différents.
   Une Task peut toutefois porter un `reasoning_effort_override` explicite, choisi à l’admission
   Chat avec `@effort`. Cette commande implique directement `@task`, tandis que `@task` seul
   conserve l’effort de raisonnement du profil. Les deux tags de contrôle sont retirés du texte
   visible et leur intention est transportée dans les métadonnées serveur. La valeur durable a
   priorité sur chaque niveau texte du profil
   pour la construction de l’objectif, le dispatcher, le planner, le briefing, la synthèse et
   l’exécuteur. Elle est héritée par les descendants planifiés ou délégués ; elle ne modifie ni
   l’effort d’exécution `standard`/`high`, ni les usages spécialisés image, audio ou vectoriels.
   Une fois `PLAN` sélectionné — automatiquement pour plusieurs unités réellement décomposables ou
   explicitement par le créateur — le planner produit l'arbre complet en une seule passe. Il juge
   la profondeur d'après la complexité et les composants vérifiables du travail, pas d'après le
   nombre de fichiers ou de livrables : un artefact unique explicitement planifié peut donc devenir
   un groupe de sous-étapes séquentielles qui partagent et raffinent la même ressource durable.
   Cette politique vient du Param Markdown `ai.planner-system-prompt`, également copié dans les
   datasets Planner du Lab. Le serveur ajoute séparément les limites effectives et le contrat du
   cycle de clarification ; ces garde-fous ne sont pas du texte expérimental.
   Chaque mécanisme texte lit son niveau partagé dans l’unique profil effectif de l’agent :
   `ultra-low` pour Dream, `low` pour le dispatcher et la conversation rapide, `standard` pour le
   briefing, l’exécuteur et le suivi des Goals, `high` pour l’exécuteur high, le planner et le Lab.
   `Agent.profile_id = NULL` sélectionne
   le profil courant ; un identifiant renseigné sélectionne exclusivement ce profil et une colonne
   vide n’en consulte aucun autre. Le modèle du planner est réutilisé pour sa synthèse finale.
5. Les providers enregistrés composent la session, le contexte partagé et leurs métadonnées. Le
   contexte Messenger est figé à la position du message déclencheur et hérité par chaque feuille du
   plan ; les messages plus récents ne peuvent donc pas modifier rétroactivement une exécution déjà
   admise. Le journal canonique reste la source de vérité. Une Task issue du control plane
   conversationnel conserve le message déclencheur et ses métadonnées serveur dans `Task.data`,
   mais ne duplique plus l'historique complet dans `Task.messages`. Si l'admission a déjà produit
   un objectif autonome, le dispatcher reçoit directement ce libellé et cet objectif ; les
   providers ne relisent plus la session Messenger, Memory ou la continuité historique consommées
   par cet appel. Le contexte de salon et d'interlocuteur reste déterministe dans `Task.data` et
   `messaging_context`, tandis que le Working Set et les apports du plan, du briefing et du harnais
   peuvent encore enrichir le travail courant. Pour les autres Tasks, le provider Memory reçoit des
   identifiants structurés afin qu'un nom inclus dans la requête ne serve jamais de frontière d'identité. Pour
   une Task humaine, le rappel réunit les mémoires non conversationnelles et celles du contact
   courant, tout en excluant celles des autres contacts ; le Topic assigné à la Task est
   délibérément ignoré comme frontière dure, mais le rappel peut inférer un prior thématique
   additif depuis la requête. Les libellés du contact ne diluent pas la requête sémantique. Le
   brief automatique retient
   au plus un `core`, puis injecte directement le top-k borné déjà fusionné entre les rangs
   lexicaux, vectoriels et graphiques, sans second seuil absolu.
   Une défaillance locale
   est consignée mais ne bloque pas la Task. Le provider Working Set lit en plus le registre de la
   Task racine et injecte les références exactes des documents, fichiers, destinataires et reçus
   actifs ; toutes les feuilles d'un même plan voient donc le même état de travail.

   Hors admission à objectif autonome, les providers publient aussi des candidats structurés non
   conversationnels pour une origine
   Messenger humaine. Le compositeur les déduplique, les classe et les borne, fusionne les
   ressources partageant la même URI canonique, puis fige sur la racine une capsule par contact
   exact avant le dispatch. Elle réunit Tasks récentes, ressources de leurs Working Sets et
   mémoires scellées au contact, sans jamais filtrer par Topic. L'historique Messenger reste la
   projection native distincte et ses messages n'entrent pas dans cette capsule. Les enfants et
   retries relisent le manifeste ; seul le Working Set courant continue d'évoluer. Sans contact
   prouvé, la room collective n'est pas utilisée comme repli. Une conversation directe, y compris
   une session audio temps réel, ne possède pas de Task racine où figer une capsule : les
   providers recherchent alors les documents récents des Tasks et des rounds terminés de cet agent
   et de ce contact, rendent leurs URI `document://` dans la section de continuité de la session et
   excluent les fichiers temporaires ainsi que le texte libre non vérifié. Les Tasks liées
   présentées au contrôleur conservent toutes les entrées actives ou à venir, les pauses humaines
   âgées d'au plus 24 heures et les deux dernières terminales si elles ont moins d'une heure. Chacune
   expose sa date locale de création et `state_since`, fondé sur la dernière mise à jour avec repli
   sur la création, avec un objectif limité à 250 caractères. Le prompt distingue cette section
   `Continuity context` du rappel durable rendu
   sous `Long-term memory`.
   Le catalogue des Processes affectés suit une règle distincte : tous sont injectés jusqu’à dix ;
   au-delà, exactement les dix plus pertinents pour la demande courante sont retenus par classement
   sémantique multilingue avec repli lexical, sans seuil. Un Process correspondant a une priorité
   absolue sur l’admission d’une Task.
6. Le resolver fige le modèle, la cible, ses capacités effectives, les limites, le contexte de
   trace et l'`AgentRunContext` dans l’`AgentRunRequest`. Le snapshot canonique de l’agent — nom,
   genre, poste, personnalité et fiche de poste — est rendu dans le socle du prompt système de
   Task. Il gouverne notamment le style, les choix rédactionnels, l’auteur et les éventuelles
   préférences explicites de signature du contenu produit. La façade lie le `run_id` logique à la
   tentative courante, puis valide sa projection `AgentRunEnvelopeV1` sérialisable et sans secret.
   Cette enveloppe transporte le prompt système complet vers les harnais réseau ; Internal et
   Hermès reconstruisent le même arbre depuis le même snapshot avant leurs ajouts runtime.
   Les callbacks de progression, checkpoint et projection d'événements restent isolés dans
   l'`AgentRunControl` local.
   Un `LLMCall` est une trace d'inférence bas niveau, indépendante de la notion de Harness. Un
   appel conversationnel direct porte son `ConversationRound` sans Task ; un appel de Task porte
   la Task et sa tentative ; lorsque cette Task provient du control plane conversationnel, le même
   appel conserve cumulativement la Task, la tentative et le round d'origine. Le round exprime la
   provenance conversationnelle tandis que la Task et sa tentative restent propriétaires de
   l'exécution et de son accounting. Le Harness ne reçoit que l'identité de Task et de run ; le
   service LLM redérive le round côté serveur, recoupe le lien durable `ConversationTaskLink` avec
   le `conversation_round_id` figé dans les données de Task et refuse toute divergence. Le champ
   `purpose` distingue notamment `agent.dispatch`, `agent.briefing`, `agent.planning` et
   `agent.exec`, indépendamment du Harness concret.
7. La façade invoque le driver enregistré, normalise son mode streamé ou non streamé, impose le
   résultat terminal unique et projette les événements sémantiques dans la timeline de la
   `TaskAttempt`. Les deltas de tokens ne sont pas persistés. Un garde-fou commun observe les
   blocs de réflexion et le texte généré : au-delà de 30 répétitions consécutives d'un même motif
   sans activité d'outil, il ferme le stream et fait échouer le run pour dégénérescence sans
   nouvelle tentative automatique.
   Les surfaces live Conversation et Task partagent strictement le même contrat de contenu :
   chaque interaction est un `AIMessage`, leur accumulation est un `AIResult`, et le résultat
   terminal autoritaire est encore un `AIResult`. Les enveloppes WebSocket peuvent ajouter des
   signaux de contrôle ordonnés (`started`, `reset`, `finished`), mais ne définissent jamais un
   second DTO de message, ne reconstruisent jamais un faux flux depuis le texte terminal et ne
   mélangent jamais les blocs `thinking` à la réponse conversationnelle visible.
   Un Harness possédé par Galaris peut activer l'extension SSE facultative du client commun. Le
   runtime Claude Agent publie ainsi ses fins d'outils et ses blocs de raisonnement publics comme
   `AIMessage` pendant le run, puis la réponse finale autoritaire et son identifiant de session dans
   le résultat terminal. Ses appels modèle traversent le gateway Anthropic Galaris. DeepSeek
   consomme le callback de notifications
   de son SDK épinglé : ses vrais deltas `assistant/chunk`, raisonnements et résultats d'outils
   remplacent les anciens keepalives sans contenu. Ses appels modèles traversent parallèlement les
   gateways Galaris et peuplent les `LLMCall` corrélés.
   Le runtime Codex embarque le SDK Python officiel et son App Server local dans un conteneur
   dédié. Il traduit sa réponse finale en chunks Chat Completions et ses commentaires ou résumés
   publics de raisonnement en événements sémantiques `thinking`, conservés dans les étapes de
   réflexion de la Task. Les deltas publics sont diffusés immédiatement avec un `stream_id` stable
   par bloc ; les projections live les concatènent sans persister une étape par fragment. Aucun
   delta `agentMessage` n'est considéré terminal avant la fin du tour :
   le dernier item final devient la réponse et tous ses prédécesseurs restent des réflexions.
   Chaque couple App Server `itemId` + `summaryIndex` forme un bloc distinct ;
   une complétion tardive ne remplace jamais un fragment déjà observé et toute divergence est
   ajoutée comme un nouveau bloc. Il interrompt le tour si le client ferme le stream, monte le
   répertoire de travail persistant propre au runtime et projette les skills dans `CODEX_HOME`. Son
   serveur MCP Galaris est obligatoire et authentifié par un token système propre à l'agent ; les
   ressources canoniques et la mémoire restent donc gouvernées par Galaris. Ce token authentifie
   aussi le provider Responses privé de l'App Server sur `/api/llm/openai`. Codex reçoit le nom
   natif du modèle figé par `app.agent`, tandis que le code Galaris correspondant est propagé dans
   un en-tête corrélé : le gateway résout ainsi exactement le modèle `Agent Executor` en mode
   standard ou `Agent Executor high` en mode high du profil effectif, sans seconde résolution dans
   le runtime. Chaque requête Responses produit un `LLMCall` corrélé au run ; son usage natif et le
   coût fournisseur éventuel sont conservés avant tout repli sur les tarifs configurés. Le runtime
   Codex ne contacte donc plus directement l'authentification ChatGPT.
   Le harnais interne applique le même invariant terminal aux événements Pydantic AI : les deltas
   précédant des outils restent visibles comme progrès, puis le `AgentRunResultEvent.output`
   remplace exactement le résultat final. Pour un profil et un modèle dont le bridge déclare une
   politique Responses native, il utilise directement l'adaptateur Responses de Pydantic AI à
   travers le proxy en processus de Galaris, sans conversion Chat Completions. La politique choisit
   le profil du modèle routé et les extensions compatibles afin de conserver le raisonnement et les
   appels d'outils sans envoyer de champ propre à un autre fournisseur. Les autres modèles restent
   sur l'adaptateur Chat Completions compatible. Hermès garde `assistant.completed` autoritaire et
   publie désormais en direct les blocs `thinking` et les fins d'outils restaurées depuis sa session.
8. Le résultat structuré est appliqué au contrat de tâche, puis le port SQLAlchemy persiste la
   transition et les données produites.
9. Les observers terminaux inscrivent uniquement les projections déterministes nécessaires. Aucun
   driver ni Harness ne transforme implicitement le texte terminal en envoi Messenger : il rend
   l'`ExecutionResult` et conserve seulement le contexte de room nécessaire aux pièces jointes,
   interactions et outils explicitement appelés. Pour une Task issue d'un round texte,
   `app.conversation` garantit la projection du résultat dans Messenger et la saute lorsque le
   résultat terminal contient déjà une preuve de livraison réussie. Une Task Messenger directe sans
   lien conversationnel doit effectuer tout envoi demandé par un outil explicite. La recherche de
   nouveaux souvenirs dans les Tasks appartient au scanner opportuniste `app.dream` et ne s'exécute
   pas sur ce chemin.
10. Le scheduler clôt la tentative, libère le lease et programme éventuellement la suite.

## Identité, enveloppe et timeline du run

`AgentRunIdentityV1` distingue quatre niveaux qui ne doivent pas être fusionnés : la Task durable,
sa tentative liée au lease, le run logique conservé lors d'une reprise compatible et l'identifiant
opaque éventuellement attribué par le runtime. Une reprise du même objectif avec le même driver
conserve le run logique ; un changement de driver crée une nouvelle identité.

`AgentRunEnvelopeV1` est la future frontière de transport. Elle ne contient ni configuration
secrète du driver, ni objet SQLAlchemy, ni callback Python, ni chemin hôte. Les ressources y sont
référencées par URI canonique et les champs variables sont bornés. `AgentRunRequest` demeure le
contrat local afin que les drivers actuels conservent leur control plane sans le rendre
transportable par accident.

La timeline durable est une projection bornée dans `TaskAttempt.data`. Elle conserve les
identifiants, la séquence, le type d'événement, les résumés d'outils et le résultat terminal compact,
avec l'usage normalisé lorsqu'il existe. Le `ExecutionResult` porté par la Task reste la source de
vérité complète ; une erreur de projection de timeline ne transforme jamais un effet externe réussi
en échec rejouable.

## Checkpoints, effets et concurrence

Le checkpoint interne version 3 journalise chaque appel avant son exécution, puis son résultat.
Les outils inconnus sont considérés non idempotents et exclusifs. Les annotations MCP standard
`readOnlyHint` et `idempotentHint` d'un serveur externe complètent la politique des outils natifs,
sans jamais rendre rejouable un outil marqué destructif. Seuls les outils dont le contrat
atteste explicitement une lecture ou une opération idempotente peuvent être
réessayés après interruption ; seuls ceux marqués `safe` peuvent partager une fenêtre de concurrence
bornée. Un appel non idempotent resté `started` devient `outcome_unknown` et exige une résolution
visible plutôt qu'un rejeu automatique.
Le helper console v2 peut fournir cette résolution par un reçu distant lié à l’UUID enregistré
avant lancement. Une tentative de réconciliation reste bornée et conserve la même cible SSH.
Les retries manuels préservent le journal, et une tentative remplacée ou expirée ne peut plus
écrire de checkpoint. Le dernier état est également archivé dans `TaskAttempt.data.agent_checkpoint`.
Voir [ADR 0093](../../../../project/decisions/0093-tool-outcome-evidence-and-console-recovery.md).
Une ancienne classification conservatrice peut être réparée à la reprise lorsque le contrat natif
courant déclare désormais explicitement le même outil `read` ou `idempotent`; l'appel interrompu
est alors fermé comme retryable. Un outil encore inconnu ou non idempotent reste bloqué.

La barrière d'exécution laisse plusieurs lecteurs sûrs progresser ensemble, mais donne la priorité
à un writer en attente et restitue les résultats au modèle dans l'ordre d'invocation. Cette
politique reste volontairement pessimiste : déclarer une fonction sûre est une décision de contrat,
pas une inférence depuis son nom.

Avant chaque requête modèle, l'historique est compacté selon la fenêtre de contexte résolue. Les
paires appel/retour d'outil restent des unités atomiques et les éléments les plus récents sont
conservés dans le budget restant. Les arguments JSON d'un appel d'outil restent structurellement
valides : la compaction borne leurs valeurs volumineuses sans supprimer les champs requis.
L'adaptateur Chat historique résume localement les résultats
anciens volumineux avec leur empreinte. Lorsque la politique du fournisseur le permet (OpenAI/Codex
et xAI), l'adaptateur Responses appelle `/responses/compact` sur le préfixe ancien, conserve les deux
derniers blocs atomiques et réinjecte l'élément chiffré. Les autres politiques Responses utilisent le
bornage local. Les options de stockage, de résumé, de contexte et de replay du raisonnement sont
elles aussi propres à chaque politique. Si la compaction native échoue, le bornage local reste le
repli explicite.

## Usage et coût

Les drivers rapportent un `AgentUsage` commun : tokens d'entrée et de sortie, cache, raisonnement,
requêtes, appels d'outils et coût. Chaque dimension porte une qualité explicite. Le harnais interne
normalise l'usage Pydantic AI ; Hermès agrège ses appels LLM corrélés via le gateway Galaris et
marque les dimensions absentes comme `partial` ou `unknown`. Le client commun des harnais réseau
gérés agrège de la même manière les `LLMCall` du `run_id` pour Claude Agent, DeepSeek et Codex ; la
télémétrie propre au runtime ne sert que de repli lorsqu'aucun appel corrélé n'existe. Le coût exact
remonté par le fournisseur prime sur l'estimation par tokens, afin de conserver les tarifications
dynamiques ou par palier lorsqu'elles sont exposées.

Chaque `LLMCall` conserve séparément dans `raw_response` le corps fournisseur décodé pour une
réponse ordinaire. Un stream Responses conserve uniquement la valeur JSON du champ SSE `data` de
son événement terminal (`response.completed`, `response.failed`, `response.incomplete` ou
`error`), sans les préfixes `event:` et `data:` ni séparateur SSE. Cette valeur porte l'état final
complet sans répéter les deltas ni les enveloppes intermédiaires ; un stream Chat Completions, qui
ne possède pas toujours d'objet final autonome, conserve toutes ses lignes SSE observées dans leur
ordre. Cette trace d'audit est capturée avant la normalisation en texte, raisonnement et appels
d'outils ; elle n'est ni reconstruite depuis ces projections, ni utilisée comme résultat métier de
la Task.

Une feuille planifiée qui termine avec un résultat commençant par `BLOCKED:` donne au planner une
unique possibilité de récupération. Il reçoit la cause, les résultats acquis, les étapes restantes
et le catalogue effectif, puis choisit soit d'insérer une action sûre et matériellement différente,
soit d'arrêter le plan. Une nouvelle feuille bloquée ne déclenche jamais une seconde replanification.
Les étapes non exécutées sont marquées comme ignorées dans leurs métadonnées et exclues de la
synthèse ; l'échec terminal reste communiqué par le lien de conversation durable, ou directement
pour les anciennes Tasks Messenger qui ne possèdent pas ce lien.

## Working Set et postconditions de livrable

Le Working Set est un registre versionné stocké dans `Task.data["working_set"]` sur la racine du
plan. Une entrée typée porte au minimum un rôle stable, un type de ressource, une référence exacte,
un état (`active`, `superseded`, `stale` ou `failed`) et la Task productrice. Il ne copie ni le
contenu d'un document ni les octets d'un fichier. Une nouvelle référence active pour un même rôle
classe l'ancienne comme `superseded` sans la supprimer ; les sous-tâches lisent et mettent à jour
le registre de leur racine sous verrou.

Après la réussite réelle d'un outil natif, `app.tools.resource_effects` promeut son effet dans ce
registre. Le premier document créé reçoit le rôle `primary_working_document`; les créations
suivantes gardent chacune leur URI et un rôle de référence. Les étapes suivantes doivent les lire
ou les éditer par UUID. Les
écritures de fichier enregistrent l'URI provider exacte. Une livraison Messenger ou un upload
de partage produit séparément un `artifact` et un `delivery_receipt`; un message de succès textuel
n'est pas une preuve suffisante. Une erreur métier d'un outil fichier, document ou Messenger doit
remonter comme erreur d'outil et ne produit aucune ressource active.
Une mutation directement appliquée à l'URI durable exacte nommée par l'objectif constitue en
revanche le placement demandé : elle ne doit pas être recopiée artificiellement dans Messenger.
Pour un dépôt manipulé via `console://`, un `console_exec` terminé avec code zéro et contenant
`git push` inscrit un reçu durable `git_remote`; le texte de la commande sans résultat réussi ne
vaut jamais reçu. Le garde terminal corrèle chaque source produite à sa destination ou à son reçu :
livrer un autre fichier, copier seulement vers `console://` ou obtenir un exit code non nul ne
satisfait pas le contrat.

Chaque feuille matérialisée porte en outre `artifact_policy` (`none`, `intermediate`, `final`) et
`delivery_policy` (`forbidden`, `required`), normalisées par le serveur depuis les outils exacts du
plan. Une feuille intermédiaire ne reçoit aucun outil de livraison, même si le runtime souhaite
spontanément publier son fichier. Seule une feuille qui déclare explicitement un outil d'envoi ou
de partage peut produire l'artefact final et son reçu. L'envoi Messenger copie le fichier vers le
provider de destination sans supprimer sa source.

Le planner ne peut terminer un plan annoncé comme réussi si ses livrables exigent un document sans
document primaire, si un fichier produit n'a aucun artefact final actif, ou si une Task issue de
Messenger n'a aucun reçu de livraison. Le garde d'action applique la même exigence aux exécutions
directes qui produisent un fichier. Les feuilles d'un plan conservent les outils explicites de
messagerie, mais leur texte terminal n'est jamais envoyé automatiquement : seule la Task racine
porte la livraison automatique de secours. Un message de progression distinct ne vaut pas livraison
du résultat : le fallback est supprimé uniquement si le texte terminal exact a déjà été envoyé avec
succès par Messenger.

Si le dernier travail a produit un fichier vérifié mais s'est arrêté avant tout appel de livraison,
la racine conserve un marqueur `delivery_recovery` avec le chemin, la destination et la feuille
productrice. Un retry explicite rouvre uniquement cette feuille, conserve son journal d’effets puis
exécute directement l'unique outil natif autorisé avec ces arguments vérifiés, sans requête LLM.
Cette exécution déterministe réutilise la projection d'autorisation et l'enregistrement d'effets du
MCP. Une livraison déjà tentée sans reçu reste ambiguë et n'est jamais rejouée aveuglément. La passe
terminale déclenchée par un garde de budget ou de non-progrès
est, elle, strictement sans outils et limitée à une requête : elle rapporte les faits persistés sans
effectuer de nouveau travail.

## Tours conversationnels et sessions audio temps réel

Le streaming conserve la structure `AIResult → AIMessage → fragments`. Le `stream_id`
identifie une partie texte ou réflexion : les deltas enrichissent ce message, y compris
quand d'autres messages s'intercalent, tandis que les snapshots HTTP et terminaux remplacent
son contenu cumulatif sans le dupliquer. Le harnais interne publie la réflexion dès ses
premiers fragments et conserve les identités lors du regroupement temporel du texte.
Les cartes d'outils sont des mises à jour d'invocation, pas des fragments de texte :
`tool_call_external_id` (avec le numéro de retry éventuel), ou à défaut `stream_id`,
rapproche les événements live et les snapshots sans concaténer ni compter deux fois le résultat.
Hermès conserve cette identité depuis son historique et ses checkpoints. La projection terminale
Task inclut les AIMessages avec un contenu borné et sans arguments ni résultats structurés ;
sa liste d'outils fait autorité, y compris pour les harnais sans identifiant d'invocation.
Deux appels distincts au même outil restent deux cartes, même si leur contenu est identique.
Hermès publie aussi ses blocs texte et `thinking` avec une identité persistée et
`stream_mode="snapshot"` : leur contenu cumulatif remplace le bloc déjà reçu par HTTP.
Le mode `delta`, conservé par défaut, ajoute uniquement le fragment reçu. Un résultat
terminal élimine les copies live surnuméraires des réflexions historiques ; le snapshot
HTTP d'une Task terminée applique la même réconciliation si l'événement terminal a été perdu.
Le scheduler conversationnel et les deux moteurs vocaux utilisent `ConversationRuntimeStream`
pour publier le même résultat vers Chat. Les tours audio diffusent donc leurs messages avant
la fin de la synthèse vocale. Chaque événement est ordonné par round, tentative et séquence ;
le client conserve les réflexions reçues et rejette les événements des anciennes tentatives.
Le flux reste éphémère ; la trace finale et les messages Messenger assurent la persistance.
Pendant le run, l'API d'activité fournit le snapshot courant pour réparer une reconnexion
ou une séquence manquante. Une publication lente regroupe les fragments suivants en un
snapshot cumulatif sans bloquer la génération. Le jeton de lease est vérifié à chaque
écriture critique, y compris lors de la finalisation après transport.
Voir [ADR 0062](../../../../project/decisions/0062-identified-message-streams.md).

Un message humain Messenger est relié directement à un round de sa `Room` par `app.conversation`.
Son scheduler ne réclame ni Task, ni slot d’agent et lance un round court avec le harnais interne
Pydantic AI et le niveau texte `low` du profil effectif de l’agent. Une colonne vide est
une erreur de configuration et ne reprend ni l’exécuteur ni le profil courant lorsque l’agent a un
profil personnel. Le driver Hermès n’est jamais repris. Le toolset est une
projection dédiée : connexion active, case `Tool.conversation_enabled`, fonction déclarée
`short` ou `deferred` pour les fonctions natives, droits effectifs et profil du runtime. Un
connecteur MCP externe explicitement coché est monté avec ses états de fonctions courants ; ceux
qui ne sont pas cochés ne sont même pas résolus.

Le profil conversationnel du dispatcher répond directement aux humains et arbitre `EXEC`/`END`
pour un message émis par une autre IA. Ce `END` termine uniquement le round conversationnel sans
réponse ; `EXEC` lance toujours le contrôleur direct en effort `standard`. Ce profil n’expose ni
`PLAN`, ni effort `high`, ni briefing. `END` n’appartient plus au contrat actif du dispatcher de
Task, limité à `EXEC`/`BRIEFING`/`PLAN`. Les deux sorties structurées ne demandent aucune justification au
modèle : elles ne contiennent que les champs de routage nécessaires et sont bornées à 256 tokens.
Le champ historique de la décision durable reste réservé aux diagnostics et décisions
déterministes produits localement.

Le prompt système conversationnel est distinct de celui de l'executor, mais reprend son contrat
d'identité : nom, genre, poste, personnalité et fiche de poste. Il ajoute le contexte temporel et
social courant, l'inventaire natif autorisé et le catalogue compact des Process affectés à
l'agent. Il rend séparément les Tools des connexions actives réservés au mode Task, sans répéter
ceux autorisés dans la conversation, et interdit d'en déduire une absence d'accès : si la demande
requiert l'un d'eux, l'admission par `conversation_task_submit` est obligatoire. Ses règles
demandent une réponse immédiate pour le travail court ; un travail long lance d'abord un Process
correspondant avec `conversation_process_start`, ou crée sinon une Task avec
`conversation_task_submit`, sans jamais attendre leur fin.

Pour un humain, le dispatcher retourne `EXEC standard` avant tout chargement de modèle et sans
inférence, sur tous les canaux textuels. L'exécuteur décide d'utiliser un outil ou d'admettre du
travail durable. Le contrôleur ne juge plus une réponse réussie : absence d'admission, absence
d'outil ou formulation répétée ne provoquent aucune relance. Les erreurs d'exécution remontent au
scheduler, dont le budget et les protections contre les effets dupliqués restent applicables.
Le champ `requires_action` disparaît aussi du dispatcher de Task et du Lab. Les drivers interne
et Hermès acceptent un résultat réussi sans contrôle d'action ou d'artefact après réponse ; les
reçus d'effets et les reprises de livraison restent gouvernés par leurs contrats propres.
Une directive contenant `@task`, `@plan` ou `@effort`, quelle que soit sa position dans le message,
court-circuite plus tôt encore le dispatcher et le runtime conversationnels. Dans le Chat natif,
ces contrôles sont retirés du message visible et projetés en métadonnées avant admission ; les tags
encore présents sur les transports externes restent parsés de façon déterministe, puis l'opération
canonique crée une Task liée au round avant que sa confirmation ne soit publiée dans la room.
Le prompt demande préventivement une formulation nouvelle en une seule passe. Pour les pairs IA,
le dispatcher conserve ses limites anti-boucle et son choix `EXEC`/`END`. Il n'effectue aucun retry
de validation : une sortie structurée invalide déclenche immédiatement son fallback `END`.
Toute nouvelle racine, y compris celle demandée par `conversation_task_submit`, passe néanmoins
par un appel structuré dédié au niveau `standard` du profil effectif. Cet appel reconstruit
directement le `label` et l'`objective` autonomes depuis la chronologie canonique, le tour gelé,
Memory, la continuité, les travaux liés, les URL et les pièces jointes. Les arguments du tool ne
sont que des indices et les références absentes du contexte sont refusées. Sa consigne système est
le Param Markdown administrable `ai.task-objective-system-prompt`. Le serveur injecte
séparément le salon, l'interlocuteur et les contrôles de dispatch. Il vérifie l'idempotence avant
l'appel puis la fraîcheur du round après celui-ci ; aucun objet intermédiaire n'est persisté.
Ces directives ne font jamais planifier le contrôleur conversationnel : elles empruntent un chemin
déterministe `EXEC`, puis appellent l'opération canonique
d'admission avant tout runtime LLM conversationnel. Sur une Task durable, une directive de message
est une préférence négociée après résolution
des routes déclarées par `AgentDriverSpec.pipeline_policy`; elle ne peut donc pas activer une étape
que le driver n'expose pas. `@briefing` est actuellement indisponible puisque aucun driver actif
n'expose le briefing. Seul un
`forced_route` de création explicite reste une contrainte stricte.

Les commandes explicites d'arrêt et de renvoi d'une pièce jointe existante sont également des
contrôles déterministes exécutés avant le dispatcher et avant le modèle conversationnel. L'arrêt
cible la Task active la plus récente déjà liée à la room ; le renvoi cible l'UUID canonique du
fichier demandé. Une panne du modèle dispatcher applique immédiatement la route de secours bornée :
`EXEC` pour un humain et `END` pour une IA. Les textes émis avant un appel d'outil
restent dans la trace d'audit mais sont retirés de la réponse Messenger ; seule la réponse produite
après le dernier effet réussi est visible.

Les interactions à options suivent la même séparation. Un numéro ou alias exact est appliqué sans
LLM. Une réponse libre non reconnue poursuit le flux conversationnel avec la projection des choix
en attente dans sa portée exacte. Le modèle conversationnel peut alors sélectionner exclusivement
une option persistée par `conversation_choice_resolve`; il doit demander une clarification plutôt
que déduire un consentement ambigu. Lorsque le message réoriente le travail, il peut refuser
l'approbation devenue obsolète puis appeler `conversation_task_submit` avec `AMEND_CURRENT` ou
`AMEND_QUEUED`. `app.task` reste seul propriétaire de l'interruption et de la reprise durable.

Les prompts système des trois exécuteurs — Task, conversation textuelle et voix — sont construits
comme des arbres JSON ordonnés `galaris.system-prompt/v1`, puis convertis en Markdown par un
renderer unique à la frontière du modèle. Chaque arbre se termine par un nœud `raw_markdown`
alimenté par le Param correspondant à l’exécuteur. Ce suffixe n’est jamais sélectionné par LLM :
`ai.executor-system-prompt` couvre Internal et Hermès, le Param conversation couvre les rounds
textuels et le Param voix couvre le pipeline comme le realtime natif. La règle commune qui sépare
dialogue immédiat et action de fond vient séparément de `ai.conversation-action-policy`; elle est
injectée dans les prompts conversation et voix et figée dans les runs correspondants du Lab.
Cette politique classe chaque résultat demandé dans quatre voies : réponse directe, petit effet
conversationnel gouverné, Process affecté ou Task d'arrière-plan. Les opérations Memory bornées,
la consultation d'état et la résolution d'une interaction explicitement exposées restent au
premier plan ; un effet externe correspondant à un Process conserve une priorité absolue sur une
Task. Le catalogue de Processes ne répète plus cet arbitrage dans les prompts courts : il fournit
uniquement les métadonnées sélectionnées, tandis que la politique conversationnelle en est
l'unique propriétaire.

Les trois exécuteurs partagent un unique nœud `Untrusted data boundary` placé avant les données de
contexte. Les en-têtes Memory et les règles conversationnelles ne répètent plus cette hiérarchie.
Les prompts courts ouvrent en outre sur une identité déclarative à la première personne et ajoutent
un rappel d'incarnation immédiatement avant le suffixe configurable ; cette répétition de récence
est volontaire et distincte d'une duplication de politique.

Dans les conversations texte et voix, chaque message natif expose seulement une enveloppe visible
`[horodatage ISO local | auteur]`. Pydantic AI conserve parallèlement son timestamp et les données
d'expéditeur structurées pour la trace ; Hermès reçoit la même projection textuelle. Le rôle
humain/assistant reste celui du protocole natif et les pièces jointes restent dans leur message
d'origine. Langue, canal, room, expéditeur courant, localisation et état de continuité sont rendus
une seule fois dans le nœud système `Turn context` ou `Call context`. Le nettoyage terminal accepte
encore les anciens cartouches et `<galaris_message_context>` pour les sessions historiques.

Avant l’appel du runtime, le contrôleur textuel compose aussi les fournisseurs de contexte communs.
Le rappel de mémoire gouvernée est injecté dans le prompt et sa télémétrie sûre (requête, nombre,
troncature, identifiants et erreur éventuelle, sans recopier le contenu rappelé dans les métadonnées)
est conservée dans le `ExecutionResult`. La voix obtient la même projection par son
`AgentRunRequest`. Le monitoring affiche donc toujours un onglet mémoire pour ces deux surfaces,
y compris lorsque la mémoire est désactivée, vide ou non consultée. Les libellés techniques tels
que `Conversation — <agent>` sont génériques : la requête de rappel utilise l'objectif utilisateur
borné, afin de ne pas remplacer le sujet courant par le nom du runtime. La projection initiale des
Tasks filtre les travaux anciens selon leur état et borne chaque objectif, sans plafonner le nombre
de travaux encore actifs. Le modèle peut appeler `conversation_task_list` pour retrouver une Task
plus ancienne. Cet appel reste limité aux
Tasks racines du contexte conversationnel courant, omet leurs résultats volumineux et conserve les
références actives du Working Set ; `conversation_task_status` fournit le détail borné par UUID.

Galaris n’impose aucun plafond de sortie ni budget cumulé en tokens aux exécuteurs Task,
conversation et voix, ni aux mécanismes LLM spécialisés. Un historique ou un prompt déjà
constitué ne doit jamais empêcher une réponse à cause d’une borne applicative. La fenêtre de
contexte physique et les limites propres au fournisseur restent applicables. Les mécanismes Dream
n’ajoutent pas non plus de `request_limit` Pydantic AI : leurs reprises de validation restent
bornées par le contrat de sortie ou par leur boucle métier explicite. Dans leur suivi, `attempts`
compte les exécutions revendiquées du mécanisme, tandis que les requêtes LLM corrélées sont comptées
et affichées séparément : une exécution peut en contenir plusieurs. Un round textuel, qui doit rester
court et déléguer le travail substantiel, possède toutefois un timeout mural de cinq minutes : il
empêche un runtime ou un outil suspendu de renouveler indéfiniment son lease et
de bloquer tous les messages suivants de la room. Son scheduler renouvelle le lease durable pendant
l'exécution et annule aussi le flux si le token de propriété disparaît ; un même round ne peut donc
pas continuer dans deux appels provider.
Chaque outil MCP natif possède en plus un délai mural borné par
`TASK_TOOL_TIMEOUT_SECONDS` (300 secondes par défaut), inférieur au délai d'inactivité de l'action. Un
provider de fichiers ou un appel réseau suspendu rend ainsi une erreur d'outil récupérable au
runtime au lieu d'immobiliser toute la Task. `TASK_ACTION_TIMEOUT_SECONDS` est un watchdog de
progression durable : chaque checkpoint ou événement sémantique le réarme. La durée totale n'est
donc pas bornée et une Task peut rester active plusieurs jours ; seule une absence continue de
progression pendant la durée configurée termine la tentative avec un diagnostic explicite.
L'annulation d'un stream fournisseur finalise d'abord la trace `LLMCall` comme
`cancelled` dans une portée protégée de l'annulation HTTP, puis ferme les transports avec un délai
séparé ; la réconciliation des traces orphelines reste un filet de sécurité et non le chemin
nominal.
Le runtime temps réel interrompt aussi une prose significative répétée trois fois sans action, afin
qu'un modèle qui boucle ne maintienne pas indéfiniment un stream ouvert. Au démarrage, le scheduler
ferme aussi comme `cancelled` toute trace LLM restée `running` alors que son round est déjà
terminal. Le job périodique applique immédiatement la même règle à un appel `agent.exec` dont la
Task est déjà `SUCCESS` ou `ERROR`.

Une demande substantielle compare d'abord les Tasks récentes du même contexte. Le contrôleur
choisit explicitement de compléter le même livrable actif, de modifier un livrable encore en file,
de créer une Task indépendante ou de demander une clarification. Le backend valide le scope, la
révision et l'amendabilité. Une création rend son identifiant sans attendre ; un amendement
conserve l'UUID et inscrit une ligne `TaskAmendment` idempotente. Cette Task retourne au flux
nominal ci-dessus et utilise donc son driver habituel. Elle
reste un mode d’exécution de la même identité agentique et conserve intégralement son adresse
Messenger : le planner, le driver, les interactions d’approbation et les outils peuvent parler,
poser une question et publier le résultat final par le flux Task ordinaire. Le lien conversationnel
sert à la filiation et au suivi ; il ne rend pas la Task muette et ne duplique pas sa sortie.

Le contrôleur qui l'admet reste toujours interne, y compris lorsque l'agent est configuré avec
Hermès ; seule la Task nouvellement persistée repasse ensuite par la résolution normale de son
driver. Le garde conversationnel ne modifie donc ni le contrat `AgentDriver`, ni le chemin Hermès.

Un appel LLM du contrôleur porte `agent_run_id` et `conversation_round_id`, avec `task_id=NULL`.
Le proxy ne peut donc pas lui attribuer la Task externe active par heuristique. La limite du Harness
externe à une Task et la recherche de son unique lease durable corrèlent ses appels de travail,
y compris lorsque la requête atteint un autre worker backend.
Le round conserve également le `ExecutionResult` normalisé du harnais interne (prompts, trace
d’outils, opérations mémoire, coût et résultat terminal). La projection visible par un participant
autorisé de la room expose à la demande les réflexions, appels d'outils et résultats bornés après
retrait des credentials ; elle n'expose jamais le prompt système. Elle reste distincte des
`LLMCall` corrélés au round. Une tentative
interne en échec transmet aussi son `ExecutionResult` partiel au scheduler : les messages de
réflexion et d’outil, l’erreur, le coût et la durée sont accumulés avec ceux de la tentative
suivante. Après épuisement des tentatives, le round expose la réponse de secours réellement
envoyée, reste marqué en échec résolu et conserve les appels LLM en échec séparément.

Un appel vocal est persisté par `app.voice` dans une `VoiceConversationSession`; chacun de ses
traitements est un `ConversationRound`. Pour le pipeline STT → agent → TTS, la façade construit
directement un `AgentRunRequest(task_id=None)` avec `ConversationRound.id` comme `run_id` et
`conversation_round_id`, compose les mêmes providers
de contexte puis fige le driver `internal` et le modèle de conversation du profil effectif (avec
la même absence de repli que le texte). L’exécuteur Pydantic AI utilise le prompt conversationnel et exactement la
projection `conversation_only`; le driver Task configuré, notamment Hermès, et son catalogue
complet ne participent jamais au tour. Le contrat de stream terminal reste inchangé. Le scheduler,
les leases et les `TaskAttempt` ne participent pas à ce chemin.
Le résultat terminal normalisé est conservé sur le round et chargé à la demande dans le monitoring,
sans gonfler la liste des appels. Les `LLMCall` restent une projection corrélée séparée.

Les traces `LLMCall` sont des écritures d'audit et de comptabilité : une suppression de Task ne les
supprime jamais. Elle ferme immédiatement comme `cancelled` leurs éventuels appels encore marqués
`running`, sans modifier l'usage, les compteurs de tokens, le coût ni la sortie partielle.
Le champ de présentation `prompt` d'un appel `agent.exec` projette l'objectif durable de la Task ;
les messages exacts envoyés au fournisseur restent séparément dans `request_messages`, y compris
les rappels techniques ajoutés par un Harness. Le coût rapporté par le fournisseur est prioritaire
sur l'estimation issue des tarifs configurés ; un
adaptateur enregistré dans `app.llm.provider_facade` peut normaliser une forme propre au
fournisseur. `inference_cost` conserve ce montant comparable et `cost` représente le montant
facturé. Pour un modèle marqué `is_subscription`, chaque trace fige ce choix et conserve
`inference_cost`, mais son `cost` facturé vaut zéro. Le dashboard agrège le `cost` historique
des traces ; modifier l'abonnement actuel ne change jamais les mois passés.
Son coût API agrégé reste fondé sur `inference_cost`. Une
réconciliation périodique applique le même traitement aux traces sans activité persistée au-delà
du timeout d'action configuré, augmenté d'une marge de finalisation, et sert aussi de filet de
sécurité si le processus tombe entre la suppression de la Task et cette fermeture.

Une prise de parole pendant la réponse annule le run courant et termine le round en
`INTERRUPTED`, pas en `Task.ERROR`. Son objectif effectif reste en attente dans la session et est
préfixé au transcript suivant. Seule une réponse complète efface cet objectif. Le prompt commun
autorise la parole et les consultations bornées. Toute autre action doit lancer sans attente un
Process affecté via `conversation_process_start`, ou une Task autosuffisante via
`conversation_task_submit`; le runtime conversationnel ne réalise jamais cette action directement.

Le mode vocal `realtime` ne découpe pas l’audio en exécutions textuelles. `app.agent` compose une
fois l’identité, le prompt commun et les providers de contexte dans un
`RealtimeAgentContext`. `app.voice` ouvre ensuite une session via le contrat fournisseur de
`app.llm.provider_facade`; le bridge concret traduit uniquement le protocole distant.

La session reçoit uniquement les fonctions conversationnelles bornées nécessaires : recherche
mémoire, liste, création, amendement et lecture d’une Task, découverte/lecture des Process affectés
et lancement asynchrone d’un Process. Les noms de contrôle (`conversation_task_list`,
`conversation_task_submit`, `conversation_task_status`, `conversation_process_start`) et la politique d’action sont les mêmes
que pour le pipeline. `conversation_task_submit` utilise `AgentTaskPort`, crée ou amende la Task
durable avant de renvoyer son UUID, puis réveille le scheduler. Les fonctions Process passent par
la façade
`app.process`. Le modèle fournisseur n’a donc aucun accès direct à `app.task`, aux modèles ORM ni à
PostgreSQL.

Le sélecteur vocal unique de l'agent décide de l'architecture. Une ressource TTS utilise le
pipeline STT → exécuteur conversationnel → TTS. Une voix native associée à un modèle temps réel
ouvre une session audio → audio ; aucun faux transcript n'est créé. Les deux variantes
conservent le même contexte, la même politique conversationnelle, une surface d’outils bornée aux
conversations et la même persistance de session vocale.

## Matrice d’exécution

| Driver | Effort `standard` | Effort `high` | Briefing |
|---|---|---|---|
| `internal` | exécution Pydantic AI directe | exécution Pydantic AI directe | jamais (désactivé pour évaluation) |
| `hermes` | session `/v1/runs` directe | session `/v1/runs` directe, modèle `high` | jamais |

Le mécanisme, ses contrats, ses résultats historiques et ses benchmarks du Lab restent présents,
mais la politique statique du driver interne ne route plus les nouvelles Tasks vers `BRIEFING`.

La constante interne `HERMES_HIGH_KANBAN_ENABLED` est actuellement désactivée. Elle n’est ni un
paramètre d’environnement, ni un paramètre administrable : les nouvelles exécutions Hermès
`standard` et `high` utilisent donc toutes les deux le runtime direct. Le code Kanban reste isolé
sans backend de management actif, et la récupération de ses appels de fonction depuis
`LLMCall.tool_calls` est inactive et le chemin direct s’appuie sur le stream et la session
persistante Hermès.

La Task PostgreSQL reste l’autorité sur le lease, les tentatives et l’état final. Une carte créée
avant cette désactivation demeure un handle de runtime subordonné. Elle n’est jamais convertie en
run direct au risque de rejouer ses effets, mais son ancien transport partagé n’est plus disponible
depuis l’ADR 0058 et la reprise échoue explicitement.

## Erreur, annulation et reprise

- Une erreur retryable programme `next_attempt_at` et conserve la phase de reprise.
- Une défaillance de transport pendant la décomposition initiale d'un plan n'a encore produit
  ni enfant ni effet : le planner laisse donc le scheduler appliquer ses retries réseau bornés.
  Un résultat de plan déjà agrégé reste au contraire terminal et n'est jamais rejoué.
- Un lease expiré rend une action récupérable après arrêt du worker.
- Un run dont l'objectif a été remplacé pendant son exécution est publié comme `cancelled` et
  n'alimente ni les incidents ni les compteurs d'échec.
- `cancel_requested` est durable ; la capacité d’annulation du driver doit être déclarée.
- Le harnais interne enregistre chaque run actif sous son `run_id` et son `task_id`.
  Une annulation demandée au driver utilise le `CancellationToken` Pydantic AI ; une pause de
  Task ou une perte de lease peut conserver son annulation asyncio externe. Dans les deux cas,
  le runtime récupère l'historique détaché du run, persiste un checkpoint `interrupted`, interrompt
  la requête fournisseur et l’appel MCP en cours, arrête la commande console active, puis ferme
  toutes les ressources enregistrées. La reprise fournit cet historique à Pydantic AI, qui répare
  les appels d'outils incomplets avant le prochain tour ; le journal d'effets Galaris reste seul
  autoritaire pour décider si cette reprise est sûre.
- Le harnais interne accepte les appels d’outils parallèles et les borne à la limite du run.
  Le wrapper MCP central donne à chaque outil natif sa propre session SQLAlchemy courte ; la
  fonction MCP et ses services la récupèrent uniquement avec `get_db()`. Les checkpoints et événements
  sont verrouillés dans l'ordre du journal puis persistés par une transaction indépendante. Une
  défaillance locale effectue donc son rollback sans invalider la session d'un autre outil ni la
  transaction durable de la Task. Les outils déclarés `exclusive` restent des barrières, tandis
  que seuls les outils explicitement `safe` s'exécutent simultanément. Les sessions séquentielles
  du scheduler de Task et du contrôleur de conversation restent disponibles pendant
  l'initialisation du runtime (catalogue, modèle, contexte), puis leur transaction est libérée
  avant la première requête modèle ; aucune branche parallèle ne l'utilise.
- Trois résultats d’échec identiques et consécutifs pour le même outil et les mêmes arguments
  interrompent le run interne : le modèle ne peut pas transformer une erreur déterministe en boucle
  de milliers d’appels. Une lecture de ressource de skill invalide utilise en plus le protocole de
  retry Pydantic AI avec deux reprises maximum et fournit la liste des chemins réellement présents.
- Trois succès identiques et consécutifs sans progression pour le même outil et les mêmes arguments
  interrompent également l'exploration. Pour `file_create`, la signature ignore le contenu
  généré et compare le chemin et le nom afin d'empêcher une série de nouveaux brouillons
  équivalents. Le runtime accorde ensuite une unique finalisation bornée à partir de l'historique
  déjà capturé ; si elle réussit, le travail produit reste livrable au lieu de finir en erreur.
- Une réponse fournisseur terminée par `length` ou `content_filter` est un résultat incomplet, donc
  un échec. Son texte partiel reste observable dans la trace mais n’est jamais livré comme réponse
  Messenger terminale.
- Avant un appel d’outil interne, un checkpoint durable marque l’effet `started`. Son résultat et
  l’historique Pydantic AI rendent le checkpoint reprenable après passage à `completed`, ou à
  `failed` pour un rejet prouvé avant effet. `ModelRetry` seul ne prouve pas ce rejet : un timeout
  peut survenir après une mutation. Le serveur natif fournit une preuve liée à l’UUID de l’appel.
  Une erreur historique de validation structurée peut réparer le journal si le nom et l’identifiant
  correspondent ; une ancienne erreur textuelle ne suffit pas.
  Une reprise réinjecte cet historique et sert les résultats déjà journalisés sans rappeler
  l’outil. Un effet resté `started` après crash doit d’abord être réconcilié : sans preuve distante,
  il reste bloqué. Les arguments des appels sans réponse ne sont jamais compactés.
- La livraison Messenger de secours, exécutée hors MCP, suit le même protocole. Après accusé
  durable, une reprise retourne directement le résultat terminal sans rappeler le modèle ni
  renvoyer le message.
- Une reprise Hermès respecte la stratégie du checkpoint. Les checkpoints historiques sans
  stratégie restent des runs directs ; un checkpoint Kanban existant n’est ni recréé ni converti
  et échoue explicitement puisque son transport de management n’est plus disponible.
- L’annulation d’un run Hermès direct arrête `/v1/runs/{id}`. Celle d’un run Kanban reclaim le
  worker puis archive sa carte pour empêcher une nouvelle distribution.
- `Task.paused` et les raisons de pause suspendent l’ordonnancement sans remplacer la phase.
- `PAUSE` reste une valeur PostgreSQL héritée et ne doit pas être réutilisée.
- Une coordination attendue suspend la progression puis revient par l’événement explicite
  `RESUME_COLLABORATION`, sans rejouer les outils déjà exécutés.

## Points d’entrée à lire

- Contrats : `back/app/agent/contracts.py`, `task_port.py`.
- Orchestration : `back/app/agent/facade.py`, `dispatcher.py`, `planner_service.py`,
  `briefing_service.py`, `model_resolver.py`.
- Harnais interne : `back/app/harness/driver.py`, `executor.py`, `run_control.py`,
  `checkpoint.py`.
- Découverte des outils : `back/app/tools/catalog.py`, `tool_search_service.py` et
  `back/app/harness/mcp_toolset.py`.
- Persistance : `back/app/task/agent_adapter.py`, `workflow.py`, `scheduler.py`, `models.py`.
- Tests de frontière : `back/app/agent/tests/test_architecture.py`.
- Contexte et observers : `back/app/agent/context.py`, `observers.py` et
  [flux mémoire](memory.md).
- Conversation vocale : `back/app/voice/conversation_service.py`, `engine.py`,
  `realtime_engine.py` et `session.py`.
- Conversation texte : `back/app/conversation/`, `back/app/harness/conversation.py` et
  [flux Messenger](messaging.md).
