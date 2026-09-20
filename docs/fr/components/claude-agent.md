<p align="right"><strong>Français</strong> · <a href="../../en/components/claude-agent.md">English</a></p>

# Claude Agent Harness

Ce bridge provisionne une instance isolée du Claude Agent SDK par agent avec le gestionnaire
générique `bridge.harness`. Galaris l'exécute par le client Chat Completions commun de
`app.harnesses`; ni le SDK Claude ni son protocole interne ne remontent dans `app.agent`.

Le conteneur expose :

- `GET /health` pour la santé Compose ;
- `GET /v1/models` pour le probe du provider ;
- `POST /v1/chat/completions`, en JSON ou en SSE.

Le modèle demandé est le modèle d'exécution déjà résolu par `app.agent`. Le SDK pointe
obligatoirement vers `/api/llm/anthropic` avec un token système tournant : les modèles internes
Galaris restent donc disponibles, et chaque appel LLM est corrélé à la Task et au run. Le même
token donne accès au seul endpoint MCP de l'agent. Aucun credential Anthropic direct n'entre dans
le conteneur.

Les skills autorisés sont projetés sous `data/skills/.claude/skills`, le workspace sous
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

Une Task en approbation automatique utilise le mode `bypassPermissions`. Dans les autres cas, le
callback de permission refuse l'opération au lieu de permettre au runtime de simuler une
approbation humaine. Le nombre de tours et d'outils suit les limites figées dans
`AgentRunEnvelopeV1`.

`start`, `restart` et `update` construisent ou recréent l'image épinglée par
`requirements.txt`. `refresh` reprojette configuration, token MCP et skills avant de redémarrer.
La suppression du Harness détruit l'instance et révoque ses tokens système.
