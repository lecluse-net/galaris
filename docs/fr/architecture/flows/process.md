<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/process.md">English</a></p>

# Flux des outils et processus

Un appel d’outil court retourne directement une sortie structurée. Une opération externe ou
longue devient un `ProcessRun` durable, afin que l’agent puisse attendre, reprendre, annuler et
analyser sans garder une requête ouverte.

```text
Agent runtime
   → catalogue app.tools / toolset MCP
   → outil @mcp_tool
   → app.process (définition + run + événement + job de démarrage)
   → registry d’engine
      ├── bridge.n8n
      └── fake engine de test
   → callback ou refresh périodique
   → transition durable + output/error nettoyé
   → résolution de la tâche d’attente éventuelle
```

## Découverte par l’agent

Les six fonctions personnelles `process_*` appartiennent au package socle `galaris` : la connexion
optionnelle `process` n’existe plus. L’inventaire du prompt est produit depuis exactement la même
projection que le serveur MCP ; il ne cite donc aucune fonction inactive, incompatible avec le
runtime, désactivée ou retirée du scope de la tâche.

Si `process_list`, `process_get` et `process_start` sont toutes autorisées, le prompt ajoute les
identifiants, libellés et descriptions des seules définitions affectées à l’agent. Jusqu’à dix
définitions, elles sont toutes injectées sans classement sémantique. Au-delà, la demande courante
classe l’ensemble avec le modèle vectoriel multilingue configuré et le prompt reçoit exactement les
dix premières, sans seuil d’exclusion ; une panne ou une absence de modèle utilise un classement
lexical déterministe. Le skill système `galaris` explique ensuite le workflow détaillé. La présence
du package ne vaut jamais autorisation sur une définition : `list_for_agent`, `get_for_agent` et
`start_process` filtrent ou revalident l’affectation durable.

La même projection personnelle est disponible comme arborescence en lecture seule sous
`galaris://process/`. Une définition utilise son `workflow_id` public comme locator, par exemple
`galaris://process/Kw70xUO8uRWkXvtX`; les identifiants SQL internes ne font pas partie du contrat.
`file_list` et `file_search` paginent côté serveur et ne révèlent jamais une définition affectée à
un autre agent. Le lancement reste exclusivement une action `process_start` ou
`conversation_process_start`.

Le contrôleur conversationnel utilise la même projection avec son lanceur spécialisé
`conversation_process_start`. Le catalogue est donc injecté lorsque `process_list`, `process_get`
et ce lanceur sont effectivement visibles. Le lanceur spécialisé force l’exécution asynchrone,
lie le run au round et confie sa notification terminale à l’outbox conversationnelle.
Un Process affecté qui correspond à l’action demandée a une priorité absolue sur la création ou
l’amendement d’une Task. Lorsque plus de dix définitions sont affectées et qu’un doute subsiste sur
la projection, le modèle consulte `process_list` et `process_get` avant d’utiliser une Task.

Dans l'interface Chat, la liste latérale des exécutions ne parcourt pas tous les runs historiques
de la room. Elle part du plus ancien message actuellement chargé, résout les rounds visibles, puis
réunit leurs `ConversationProcessLink` et les runs liés à l'arbre de Tasks issu de ces rounds.

Le scope réduit d’une feuille planifiée conserve les six fonctions personnelles : une sélection
d’outils faite en amont ne peut donc pas masquer le catalogue métier. Les fonctions sélectionnées
par le planner restent avides ; les autres fonctions autorisées restent dans le toolset interne
avec `defer_loading` et deviennent accessibles via `search_tools`. La projection MCP commune
continue d’appliquer les désactivations de fonctions et les contraintes du runtime avant cette
découverte.

Le planner reçoit toujours le manifeste exhaustif des noms. `app.tools.catalog` dérive sa version
depuis le même serveur MCP effectif. `app.tools.tool_search_service` enrichit ce manifeste par une
recherche hybride FTS + pgvector sur des métadonnées publiques bornées. Les embeddings sont
mutualisés par empreinte de définition, jamais par agent ; à chaque requête, les empreintes
candidates proviennent exclusivement du catalogue effectif de l’agent, du runtime et de la Task.
Une fiche vectorielle périmée ne confère donc aucun droit. Sans modèle vectoriel ou en cas de
panne sémantique, la recherche devient lexicale ; le manifeste exhaustif reste disponible.

Les mutations de connexion, de paramètres et d’autorisation déclenchent une réconciliation
ciblée des catalogues concernés. Cette mise à jour accélère la recherche, mais ne porte pas la
sécurité : le catalogue effectif et ses droits sont toujours recalculés au moment de la
planification et de l’exécution.

Le bouton **Actualiser les outils** de l’écran Connexions lance la réconciliation administrative
complète. Une seule opération :

1. crée les connexions internes intégrées encore manquantes ;
2. reconstruit le catalogue effectif de chaque agent et interroge à nouveau ses serveurs MCP ;
3. réindexe les définitions publiques et recalcule leurs embeddings ;
4. supprime les fiches qui ne sont plus observées uniquement si tous les agents et toutes les
   sources ont répondu.

Une source distante indisponible rend le résultat partiel et interdit donc l’élagage global. Les
fiches historiques peuvent rester stockées, mais elles demeurent inéligibles tant que leur
empreinte n’appartient pas au catalogue effectif courant. L’ancien endpoint
`POST /connections/sync-integrated` est un alias déprécié ; le contrat courant est
`POST /connections/refresh-tools`.

Le package `process_admin`, inactif par défaut, constitue une surface distincte. Ses fonctions
`process_admin_*` peuvent créer, réaffecter ou supprimer une définition et gérer les runs de tous
les agents. Ses connexions sont créées inactives afin qu’aucun droit global ne soit accordé
implicitement.

Le package `galaris_admin` suit la même règle d’attribution explicite. Ses connexions sont créées
inactives et ses deux fonctions de lecture, `conversation_round_get` et `voice_turn_get`,
revérifient la connexion active côté serveur. Elles servent à analyser un tour textuel ou vocal
complet avec son état durable, sa trace d’exécution et tous ses appels LLM, sans rendre ce jeu de
données administratif disponible aux agents ordinaires.

## Démarrage

1. L’outil valide son schéma et résout la `Connection` sans rendre le secret au modèle.
2. `app.process` vérifie la définition et construit un snapshot de lancement.
3. Une clé explicite d’idempotence ou une empreinte de contenu empêche les doublons dans la
   fenêtre configurée.
4. Le run `queued` et son `ProcessStartJob` sont écrits avant l’appel distant.
5. Le worker démarre l’engine avec un `correlation_id` et un callback token propres au run.

## Progression et fin

Un engine renvoie un snapshot par callback ou par `refresh_run`. Chaque événement est ajouté
à `process_run_events`, puis la transition est validée par la matrice commune. Les payloads,
sorties et erreurs passent par le sanitizer et sa limite de taille.

Les états `success`, `error` et `cancelled` sont terminaux. Un callback tardif est journalisé
mais ne rouvre pas le run. Un `event_id` externe rend la redelivery idempotente. Lorsqu’une
tâche attend le process, seule l’entrée dans un état terminal résout cette attente.
La garde précède toute mutation du résultat, y compris pour un nouveau callback portant
le même statut terminal. Un rafraîchissement recharge l'état sous verrou après l'appel réseau.

## Corrélation des appels LLM et Agent

Un Process qui appelle directement les gateways LLM OpenAI Chat Completions, OpenAI Responses ou
Anthropic doit identifier son `ProcessRun`. Le contrat accepte, par ordre d'autorité :

1. le UUID canonique dans `X-Galaris-Process-Run-Id` ou `galaris_process_run_id` ;
2. le couple externe `galaris_workflow_id` + `galaris_engine_run_id`, résolu par `app.process`
   sous le scope Agent de l'appelant ;
3. le `process_run_id` figé dans les données de la Task lorsque le Process a déclenché un appel
   d'Agent et que les appels LLM bas niveau proviennent ensuite de cette Task.

Chaque appel direct porte `purpose=process.exec` et une FK `LLMCall.process_run_id`. Un appel LLM
appartenant à la Task déclenchée par le Process conserve cumulativement sa Task, sa tentative et son
ProcessRun ; son purpose reste alors `agent.exec`, car la Task possède l'inférence tandis que le
ProcessRun en exprime la provenance. Le service LLM redérive le ProcessRun depuis la Task pour le
harnais interne comme pour les runtimes externes et refuse un identifiant explicite divergent.

Avant de contacter le provider, les routes API vérifient que le ProcessRun appartient au scope
Agent du token et ajoutent l'événement d'observation `llm.called` ou `agent.called`. Le service de
persistance vérifie de nouveau l'existence du ProcessRun et sa cohérence avec l'Agent. Les détails
du run listent ensuite tous les `LLMCall` portant ce `process_run_id`.

## Projection vers Memory

Dream exécute `memory.project_process` sans LLM et hors du chemin d'exécution. Une définition
affectée devient une mémoire procédurale privée et source-managed. Seule la sortie assainie d'un
run `success` devient une mémoire épisodique : l'entrée, le snapshot brut, les erreurs et secrets
ne sont jamais projetés. La sortie est de nouveau filtrée puis bornée à 12 000 caractères.

Le résultat porte un lien `result_of` vers sa définition. La projection conserve les 20 dernières
réussites par agent et processus; les plus anciennes sont oubliées sans toucher aux `ProcessRun`
canoniques. Les suppressions et réaffectations sont réconciliées par les reçus Dream idempotents.

## Annulation

- Un run encore `queued` peut être annulé localement avec son job de départ.
- Un run distant passe par `cancelling`, puis attend la confirmation `cancelled`, `success` ou
  `error` de l’engine.
- Une nouvelle demande sur un état terminal retourne l’état existant.

Les runs `cancelling` restent dans le polling, y compris après une erreur réseau lors
de la demande d'annulation. Toute sortie terminale résout son éventuelle Task d'attente.
Le marqueur durable `await_resolved_at` n'est écrit qu'après cette résolution et le fan-in
du parent. Un callback dupliqué, un refresh ou le passage périodique reprend une résolution
interrompue sans modifier le résultat terminal ni réexécuter le Process.

## Déclencheurs de calendrier

Le bridge Calendar enregistre dans une transaction le curseur et tous les reçus découverts.
Chaque reçu contient un snapshot chiffré de l'action et utilise un lease récupérable pour
son dispatch. Les Tasks et Process sont soumis avec une clé d'idempotence stable ; la reprise
des reçus ne nécessite plus de relire le calendrier distant. Voir l'ADR 0067 pour les limites
de reprise des reçus historiques antérieurs à ce contrat.

## Fichiers

Les entrées fichier d'un process sont des URI canoniques `app.file_share` et peuvent donc venir de
la console, de Nextcloud, de Mail, de Messenger, de HTTPS ou d'un autre provider
autorisé. Le snapshot conserve cette URI et le vrai nom fourni par les métadonnées source. Le
bridge reçoit une URL de téléchargement temporaire rattachée au run ; lors de son appel, Galaris
matérialise la ressource de manière bornée et la supprime après la réponse. Il ne reçoit ni secret
provider ni chemin arbitraire de l’hôte, et aucune copie locale préalable n'est requise. Voir
[Médias et ressources](media-resources.md).

Les opérations immédiates de `app.file_share` manipulent des URI canoniques et streament avec une
taille et un timeout bornés. Elles ne créent pas artificiellement un `ProcessRun`. Un provider qui
expose une conversion, un export ou un transfert réellement asynchrone doit en revanche créer un
Process durable, rendre sa référence de résultat comme URI après succès et conserver les mêmes
règles d'idempotence, d'annulation et d'état terminal que les autres engines.

## Points d’entrée à lire

- Contrats d’engine : `back/app/process/engine.py` et `registry.py`.
- Persistance et matrice : `back/app/process/models.py`, `process_service.py`.
- Outils : `back/app/process/mcp.py` et `back/app/tools/mcp_loader.py`.
- Adaptateur n8n : `back/bridge/n8n/`.
