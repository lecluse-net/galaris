<p align="right"><strong>Français</strong> · <a href="../../en/components/claude-agent.md">English</a></p>

# Claude Agent Harness

## Claude Agent embarqué

Le backend installe le SDK Python et lance son exécutable local. Activez le paramètre
`harness.claude-embedded.enabled`, puis sélectionnez **Claude Agent embarqué** dans la fiche Agent. Cette affectation
fonctionne sans conteneur Claude dédié. Pydantic AI reste sélectionnable dans la même fiche.

Les appels passent par la passerelle locale de Galaris. Le journal LLM permet de retrouver
la tentative de tâche, le round Chat ou vocal, ou la soumission précise en mode `@deep`.
Les outils MCP externes utilisent les connexions du Service et ses fonctions autorisées en
conversation ou en tâche. Les demandes d’accord se traitent dans l’interface habituelle. Voir le
[flux d’exécution](../architecture/flows/agent-execution.md).

### Retour au routage conversationnel précédent

Pour rétablir Pydantic AI pour les nouveaux rounds de Chat et de voix par tours, passez
`harness.claude-embedded.conversations.enabled` à `false` via `PUT /api/params/{name}`
avec le droit de modifier les paramètres des harnais. Le réglage vaut `true` par défaut.
Conservez `harness.claude-embedded.enabled` à `true` pendant la transition. Les rounds déjà
admis terminent ou reprennent avec leur harnais d’origine. Les affectations de tâches et le
mode `@deep` continuent d’utiliser leur propre harnais. Remettez le réglage conversationnel
à `true` pour rétablir le routage vers Claude selon l’affectation de l’agent.

Avant de désactiver le SDK lui-même, laissez les rounds, tâches et soumissions Deep Claude
en cours se terminer ou traitez explicitement leurs reprises. Pour déplacer des exécutions
futures de tâches ou de Deep, modifiez l’affectation de l’agent dans sa fiche.

Si le worker d’une tâche Claude disparaît avant le premier effet d’un outil, le scheduler
peut relancer l’exécution en conservant son identité et son budget d’appels. Si le résultat
final est déjà enregistré dans le checkpoint, le worker suivant le récupère sans appel au modèle.
Le réglage du plafond de requêtes s’applique aux nouvelles tâches, aux nouveaux rounds de Chat
ou de voix et aux nouvelles soumissions Deep. Une reprise conserve le plafond enregistré et
compte les appels des tentatives précédentes. Une nouvelle soumission Deep prend le réglage
courant, même si elle reprend l’historique de la session. Les anciennes exécutions sans plafond
enregistré adoptent le réglage en vigueur à leur prochaine admission.

Une tâche embarquée interrompue après la création d’un document peut reprendre à partir
du reçu enregistré. Galaris vérifie que l’outil reste autorisé et que l’agent peut
toujours lire le document. La reprise utilise le reçu existant sans répéter la création.
Si le reçu manque ou que ces vérifications échouent, la reprise s’arrête avant un nouvel
appel au modèle. Elle conserve le plafond d’outils admis pour l’exécution et tient compte
des opérations déjà enregistrées.

### Qualification de l’image backend

`make tests-embedded-harness-image` exerce l’image locale désignée par
`EMBEDDED_HARNESS_IMAGE` et contrôle la révision `EMBEDDED_HARNESS_REVISION` embarquée.
La livraison lance aussi cette sonde sur l’image exacte du bundle. La sonde utilise
PostgreSQL isolé et simule le fournisseur de modèles. Elle vérifie les appels LLM
de deux rounds simultanés, le retour des nouveaux rounds sur Pydantic AI et une tâche
qui continue à utiliser Claude. Pendant l’activation de Claude, un agent Pydantic garde
son moteur dans Chat et Tâches. Un agent affecté à Codex ou DeepSeek Harness répond
dans Chat via Claude et envoie ses tâches au harnais affecté.
Par défaut, la sonde simule les endpoints des harnais managés. Le journal inclut l’identité de
l’image, les versions SDK et CLI, les appels rapprochés des reçus du fournisseur et les
tâches reçues par chaque harnais managé. Il vérifie aussi une demande `@task` depuis
Chat pour chaque affectation. La tâche conserve le lien avec son round, s’exécute sur le
harnais choisi et livre une seule notification de résultat dans la salle d’origine.
L’appel structuré partagé qui prépare l’objectif est rattaché au round. Pour une tâche
embarquée, l’appel d’exécution est en plus rattaché à la tâche et à sa tentative.
La sonde rejoue aussi une demande en langage naturel pour chaque affectation. Elle vérifie
l’appel à `task_run`, son reçu, le dispatch et l’exécution de la tâche, puis le retour dans
Chat. Elle teste l’accord et le refus dans les deux boucles embarquées en vérifiant les
tentatives de reprise et les effets de la décision.

Pour exercer Codex et DeepSeek Harness, fournissez leurs identifiants d’images Docker
locales dans `EMBEDDED_HARNESS_CODEX_IMAGE` et `EMBEDDED_HARNESS_DSH_IMAGE`. La sonde démarre
leurs véritables conteneurs sur le réseau de test, appelle la passerelle Galaris et conserve
les identifiants des trois images. Les appels des tâches managées sont alors rapprochés
du fournisseur synthétique et vérifiés par tâche, tentative et round source éventuel.
Les tâches utilisent des agents et des affectations créés pour l’essai.

Avec `EMBEDDED_HARNESS_LOAD_ROOMS=8`, la même commande lance aussi huit nouvelles salles
par harnais sur le même profil, avec le fournisseur synthétique. Ce nombre doit dépasser
celui des workers de conversation et rester inférieur ou égal à 24. Le journal donne la
durée de chaque rafale et rapproche les appels de toutes les salles. En cas d’échec, la
sonde conserve aussi le journal PostgreSQL de l’instance de test.

## Claude Agent managé

Ce bridge provisionne une instance isolée du Claude Agent SDK par agent avec le gestionnaire
générique `bridge.harness`. Galaris l'exécute par le client Chat Completions commun de
`app.harnesses`; ni le SDK Claude ni son protocole interne ne remontent dans `app.agent`.

Le conteneur expose :

- `GET /health` pour la santé Compose ;
- `GET /v1/models` pour le probe du provider ;
- `POST /v1/chat/completions`, en JSON ou en SSE.

Le modèle demandé est le modèle d'exécution déjà résolu par `app.agent`. Le SDK pointe
obligatoirement vers `/api/llm/anthropic` avec un token système tournant : les modèles internes
Galaris restent donc disponibles, et chaque appel LLM est corrélé à la tâche et au run. Le même
token donne accès au seul endpoint MCP de l'agent. Aucun credential Anthropic direct n'entre dans
le conteneur.

Les compétences autorisées sont projetées sous `data/skills/.claude/skills`, le workspace sous
`data/workspace` et l'état Claude sous `data/claude`. Le conteneur est non privilégié, en lecture
seule hors du volume `data`, sans capabilities Linux et avec des limites de processus, CPU et
mémoire.

## Télémétrie

Le transport reste compatible avec un serveur Chat Completions ordinaire. Pour ce provider,
Galaris active en plus deux événements SSE nommés et versionnés :

- `galaris.agent-message/v1` transporte les fins d'appels d'outils et les blocs de raisonnement
  publics normalisés en `AIMessage` ;
- `galaris.agent-result/v1` transporte la réponse finale autoritaire, l'usage, le coût, la session
  SDK, le statut terminal et les refus de permission destinés à l'unique `ExecutionResult`.

Les deltas de texte restent des chunks OpenAI standards et peuvent contenir du progrès provisoire
avant un outil. À la fermeture, `ResultMessage.result` remplace ce texte dans le résultat durable ;
l'IHM reçoit donc le progrès en direct puis la réponse finale exacte. En parallèle, les appels au
gateway Anthropic alimentent les `LLMCall` corrélés au `run_id` au fil de l'exécution. À la
terminaison, le client commun agrège ces traces persistantes et les utilise comme source prioritaire
des tokens et du coût. L'usage du SDK reste un repli `partial` lorsque le gateway n'a produit aucune
trace ; il ne peut donc pas masquer un coût fournisseur exact ni une estimation tarifaire
explicitement qualifiée par Galaris.

Le SDK utilise `permission_mode="dontAsk"`. Claude découvre et lit les compétences par
`skills_list` et `skill_read`. Le serveur MCP applique les droits, la portée et le mode configuré
pour chaque fonction. La recherche d'outils et les lectures dans l'espace de travail sont
admises par le harnais après validation du contexte. Pour une action locale soumise à accord,
le hook vérifie l'autorisation Galaris de l'action exacte.
Le serveur MCP gère la demande d'accord et sa continuation sur le même appel. Les accords
mémorisés pour les outils locaux restent liés à l'agent, au harnais et à sa configuration.
Lorsqu’un outil local attend un accord, Claude managé sauvegarde le point de reprise
dans son volume de données et ferme le processus SDK. La décision réveille la même tâche.
Le harnais reprend l’appel différé avec la même autorisation à usage unique et vérifie
de nouveau le contexte et les données de l’action avant de l’exécuter.
Le nombre de tours et d'outils suit les limites figées dans `AgentRunEnvelopeV1`.
Le SDK gère l'historique de ses requêtes et la compaction dans la fenêtre de contexte du modèle.
Si le point de reprise du harnais atteint sa limite de taille, il conserve le résultat terminal,
le curseur et les résultats d'outils récents, avec des aperçus pour les entrées plus anciennes.

`start`, `restart` et `update` construisent ou recréent l'image épinglée par
`requirements.txt`. `refresh` reprojette configuration, token MCP et compétences avant de redémarrer.
La suppression du Harness détruit l'instance et révoque ses tokens système.
